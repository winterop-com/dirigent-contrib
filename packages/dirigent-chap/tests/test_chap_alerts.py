"""``chap.alerts.reviewed``, ``chap.alerts.list`` and ``chap.alerts.record``: Chap's alert release gate."""

from typing import Any

import pytest
from pydantic import ValidationError

from chapserver import BASE_URL, CONNECTION, ChapServer
from dirigent_chap.alerts import (
    ChapAlertsListOperator,
    ChapAlertsOutput,
    ChapAlertsRecordOperator,
    ChapAlertsRecordOutput,
    ChapAlertsReviewedSensor,
)
from dirigent_chap.connection import ChapConnectionConfig
from dirigent_plugin import BlockFailure, ErrorClass, NotYet
from dirigent_testing import FakeContext, call_block

ALERTS = "/v1/crud/alerts"

PREDICTION = 7


def alert(alert_id: int, approved: str = "pending", org_unit: str = "OU1", **fields: Any) -> dict[str, Any]:
    """An alert in the shape ``GET /v1/crud/alerts`` answers with."""
    decided = approved != "pending"
    return {
        "id": alert_id,
        "timePeriod": "2025-10",
        "orgUnit": org_unit,
        "alertPolicyId": 3,
        "level": "action",
        "predictionId": PREDICTION,
        "created": "2025-10-01T08:00:00Z",
        "approved": approved,
        "approvedBy": "reviewer" if decided else None,
        "approvedAt": "2025-10-02T09:00:00Z" if decided else None,
        **fields,
    }


def reviewed(**config: Any) -> dict[str, Any]:
    return {"connection": CONNECTION, "prediction_id": PREDICTION, **config}


async def test_a_pending_review_waits_and_says_how_far_it_has_come(ctx: FakeContext, chap: ChapServer) -> None:
    alerts = [alert(1, "approved"), alert(2, "declined"), alert(3, "approved")] + [alert(n) for n in range(4, 8)]
    chap.on("GET", ALERTS, body=alerts)
    answer = await call_block(ChapAlertsReviewedSensor(), reviewed(), ctx)
    assert isinstance(answer, NotYet)
    assert answer.message == "3 of 7 reviewed"
    assert answer.progress == pytest.approx(3 / 7)
    assert dict(chap.sent("GET", ALERTS)[-1].url.params) == {"predictionId": str(PREDICTION)}


async def test_a_review_that_finishes_ends_the_wait_with_the_decided_alerts(ctx: FakeContext, chap: ChapServer) -> None:
    chap.on("GET", ALERTS, body=[alert(1), alert(2)])
    chap.on("GET", ALERTS, body=[alert(1, "approved"), alert(2, "approved")])
    sensor = ChapAlertsReviewedSensor()
    assert isinstance(await call_block(sensor, reviewed(), ctx), NotYet)
    output = await call_block(sensor, reviewed(), ctx)
    assert isinstance(output, ChapAlertsOutput)
    assert [item["id"] for item in output.approved] == [1, 2]  # type: ignore[index, call-overload]
    assert (output.declined, output.pending) == ([], [])
    assert output.counts.model_dump() == {"total": 2, "approved": 2, "declined": 0, "pending": 0}


async def test_a_prediction_with_no_alerts_ends_the_wait_at_once(ctx: FakeContext, chap: ChapServer) -> None:
    chap.on("GET", ALERTS, body=[])
    for release in ("all", "any"):
        output = await call_block(ChapAlertsReviewedSensor(), reviewed(release=release), ctx)
        assert isinstance(output, ChapAlertsOutput)
        assert (output.approved, output.declined, output.pending, output.counts.total) == ([], [], [], 0)


async def test_a_mixed_review_splits_the_approved_from_the_declined(ctx: FakeContext, chap: ChapServer) -> None:
    chap.on("GET", ALERTS, body=[alert(1, "approved"), alert(2, "declined", "OU2"), alert(3, "approved", "OU3")])
    output = await call_block(ChapAlertsReviewedSensor(), reviewed(), ctx)
    assert isinstance(output, ChapAlertsOutput)
    assert [item["orgUnit"] for item in output.approved] == ["OU1", "OU3"]  # type: ignore[index, call-overload]
    assert [item["orgUnit"] for item in output.declined] == ["OU2"]  # type: ignore[index, call-overload]
    assert output.counts.model_dump() == {"total": 3, "approved": 2, "declined": 1, "pending": 0}


async def test_release_any_ends_the_wait_on_the_first_decision(ctx: FakeContext, chap: ChapServer) -> None:
    chap.on("GET", ALERTS, body=[alert(1), alert(2)])
    chap.on("GET", ALERTS, body=[alert(1, "declined"), alert(2)])
    sensor = ChapAlertsReviewedSensor()
    assert isinstance(await call_block(sensor, reviewed(release="any"), ctx), NotYet)
    output = await call_block(sensor, reviewed(release="any"), ctx)
    assert isinstance(output, ChapAlertsOutput)
    assert output.counts.model_dump() == {"total": 2, "approved": 0, "declined": 1, "pending": 1}


async def test_a_state_chap_adds_later_keeps_the_wait_going(ctx: FakeContext, chap: ChapServer) -> None:
    chap.on("GET", ALERTS, body=[alert(1, "approved"), alert(2, "escalated")])
    answer = await call_block(ChapAlertsReviewedSensor(), reviewed(), ctx)
    assert isinstance(answer, NotYet) and answer.message == "1 of 2 reviewed"


async def test_the_policy_and_org_units_narrow_what_is_waited_on(ctx: FakeContext, chap: ChapServer) -> None:
    chap.on("GET", ALERTS, body=[alert(1, "approved"), alert(2, org_unit="OU2")])
    output = await call_block(ChapAlertsReviewedSensor(), reviewed(alert_policy_id=3, org_units=["OU1"]), ctx)
    assert isinstance(output, ChapAlertsOutput) and output.counts.total == 1
    assert dict(chap.sent("GET", ALERTS)[-1].url.params) == {"predictionId": str(PREDICTION), "alertPolicyId": "3"}


async def test_the_sensor_sends_the_token_as_a_bearer(ctx: FakeContext, chap: ChapServer) -> None:
    chap.on("GET", ALERTS, body=[])
    await call_block(ChapAlertsReviewedSensor(), reviewed(), ctx)
    assert chap.sent("GET", ALERTS)[-1].headers["authorization"] == "Bearer " + "t" * 32


async def test_the_sensor_sends_no_credential_without_a_token(ctx: FakeContext, chap: ChapServer) -> None:
    ctx.connections[CONNECTION] = ChapConnectionConfig(base_url=BASE_URL)
    chap.on("GET", ALERTS, body=[])
    await call_block(ChapAlertsReviewedSensor(), reviewed(), ctx)
    assert "authorization" not in chap.sent("GET", ALERTS)[-1].headers


async def test_a_refused_token_is_a_refusal(ctx: FakeContext, chap: ChapServer) -> None:
    chap.on("GET", ALERTS, status=401, body={"detail": "Missing or invalid API token"})
    with pytest.raises(BlockFailure) as raised:
        await call_block(ChapAlertsReviewedSensor(), reviewed(), ctx)
    assert raised.value.error_class is ErrorClass.REJECTED


async def test_a_chap_error_is_transient_and_carries_chaps_words(ctx: FakeContext, chap: ChapServer) -> None:
    chap.on("GET", ALERTS, status=503, body={"detail": "database is restarting"})
    with pytest.raises(BlockFailure) as raised:
        await call_block(ChapAlertsReviewedSensor(), reviewed(), ctx)
    assert raised.value.error_class is ErrorClass.TRANSIENT
    assert "database is restarting" in str(raised.value)


async def test_an_answer_that_is_not_a_list_is_never_read_as_no_alerts(ctx: FakeContext, chap: ChapServer) -> None:
    chap.on("GET", ALERTS, body={"alerts": []})
    with pytest.raises(BlockFailure) as raised:
        await call_block(ChapAlertsReviewedSensor(), reviewed(), ctx)
    assert raised.value.code == "chap.alerts.not_a_list"


def test_the_sensor_needs_a_prediction_and_a_known_release() -> None:
    with pytest.raises(ValidationError):
        ChapAlertsReviewedSensor.config_model.model_validate({"connection": CONNECTION})
    with pytest.raises(ValidationError):
        ChapAlertsReviewedSensor.config_model.model_validate(reviewed(release="deadline"))


def test_the_sensor_waits_inside_a_run_rather_than_starting_one() -> None:
    assert ChapAlertsReviewedSensor.spec.source is False


async def test_the_list_reads_once_without_waiting(ctx: FakeContext, chap: ChapServer) -> None:
    chap.on("GET", ALERTS, body=[alert(1, "approved"), alert(2)])
    output = await call_block(ChapAlertsListOperator(), {"connection": CONNECTION, "prediction_id": PREDICTION}, ctx)
    assert isinstance(output, ChapAlertsOutput)
    assert output.counts.model_dump() == {"total": 2, "approved": 1, "declined": 0, "pending": 1}


async def test_record_passes_the_alerts_through_as_written(ctx: FakeContext, chap: ChapServer) -> None:
    chap.on("POST", ALERTS, body={"ids": [11, 12]})
    alerts = [
        {"timePeriod": "2025-10", "orgUnit": "OU1", "alertPolicyId": 3, "level": "action", "predictionId": 7},
        {"timePeriod": "2025-10", "orgUnit": "OU2", "alertPolicyId": 3, "level": "monitor", "predictionId": 7},
    ]
    output = await call_block(ChapAlertsRecordOperator(), {"connection": CONNECTION, "alerts": alerts}, ctx)
    assert isinstance(output, ChapAlertsRecordOutput)
    assert (output.alert_ids, output.count) == ([11, 12], 2)
    assert chap.body("POST", ALERTS) == {"alerts": alerts}


async def test_record_refused_by_chap_is_never_retried(ctx: FakeContext, chap: ChapServer) -> None:
    chap.on("POST", ALERTS, status=422, body={"detail": "AlertPolicy 3 has no level 'urgent'"})
    with pytest.raises(BlockFailure) as raised:
        await call_block(
            ChapAlertsRecordOperator(),
            {"connection": CONNECTION, "alerts": [{"orgUnit": "OU1", "level": "urgent"}]},
            ctx,
        )
    assert raised.value.error_class is ErrorClass.REJECTED


def test_record_needs_an_alert() -> None:
    with pytest.raises(ValidationError):
        ChapAlertsRecordOperator.config_model.model_validate({"connection": CONNECTION, "alerts": []})
