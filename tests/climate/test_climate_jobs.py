"""``climate.export``, ``climate.ingest`` and ``climate.sync``: the jobs the service runs in the background."""

from typing import Any

import pytest

from dirigent_contrib.climate.exports import (
    ClimateExportConfig,
    ClimateExportOperator,
    ClimateExportOutput,
    idempotency_key,
)
from dirigent_contrib.climate.ingestions import (
    ClimateIngestConfig,
    ClimateIngestionOutput,
    ClimateIngestOperator,
    ClimateSyncOperator,
)
from dirigent_contrib.climate.messages import EXPORT_REJECTED
from dirigent_plugin import BlockFailure, ErrorClass, ProbeStatus, RemoteHandle
from dirigent_testing import FakeContext, call_block
from tests.climate.climateserver import CONNECTION, ClimateServer, settle

EXPORT = {"connection": CONNECTION, "export_id": "rainfall-monthly", "job_id": "j1", "dry_run": True}

DELIVERY = "/exports/rainfall-monthly/jobs/d1"


def _accepted(reused: bool = False) -> dict[str, Any]:
    return {
        "delivery_job_id": "d1",
        "export_id": "rainfall-monthly",
        "dry_run": True,
        "reused": reused,
        "status_url": DELIVERY,
        "report_url": DELIVERY,
    }


def _delivery(status: str, report: dict[str, Any] | None = None, error: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "delivery_job_id": "d1",
        "export_id": "rainfall-monthly",
        "status": status,
        "created_at": "2026-10-30T00:00:00Z",
        "finished_at": None,
        "error": error,
        "report": report,
    }


def _report(outcome: str) -> dict[str, Any]:
    return {"plugin_id": "dhis2", "outcome": outcome, "payload_sha256": "x", "imported": 3, "conflicts": []}


def _record(status: str, **fields: Any) -> dict[str, Any]:
    return {"jobID": "i1", "processID": "ingestion", "status": status, "createdAt": "2026-10-30T00:00:00Z", **fields}


async def test_a_delivery_is_queued_under_the_attempts_idempotency_key(ctx: FakeContext, ocs: ClimateServer) -> None:
    ocs.on("POST", "/exports/rainfall-monthly", status=202, body=_accepted())
    handle = await call_block(ClimateExportOperator(), EXPORT, ctx)
    assert isinstance(handle, RemoteHandle) and handle.ref == "d1"
    sent = ocs.sent("POST", "/exports/rainfall-monthly")[0]
    assert sent.headers["idempotency-key"] == idempotency_key(ctx.as_context())
    assert ocs.body("POST", "/exports/rainfall-monthly") == {"job_id": "j1", "dry_run": True}


def test_the_key_is_the_same_for_one_attempt_and_differs_for_the_next(ctx: FakeContext) -> None:
    first = idempotency_key(ctx.as_context())
    assert idempotency_key(ctx.as_context()) == first
    ctx.attempt = 2
    assert idempotency_key(ctx.as_context()) != first


async def test_a_delivery_is_followed_to_its_report(ctx: FakeContext, ocs: ClimateServer) -> None:
    ocs.on("GET", DELIVERY, body=_delivery("accepted"))
    ocs.on("GET", DELIVERY, body=_delivery("running"))
    ocs.on("GET", DELIVERY, body=_delivery("successful", _report("dry_run")))
    block = ClimateExportOperator()
    handle = RemoteHandle(
        block_id="climate.export", ref="d1", meta={"export_id": "rainfall-monthly", "dry_run": "true"}
    )
    probes, output = await settle(block, handle, ClimateExportConfig.model_validate(EXPORT), ctx)
    assert [probe.status for probe in probes] == [ProbeStatus.RUNNING, ProbeStatus.RUNNING, ProbeStatus.SUCCEEDED]
    assert isinstance(output, ClimateExportOutput)
    assert (output.status, output.outcome, output.dry_run) == ("successful", "dry_run", True)
    assert output.report == _report("dry_run")


async def test_a_report_the_target_rejected_fails_as_a_refusal(ctx: FakeContext, ocs: ClimateServer) -> None:
    ocs.on("GET", DELIVERY, body=_delivery("successful", {**_report("rejected"), "message": "E7619"}))
    block = ClimateExportOperator()
    handle = RemoteHandle(block_id="climate.export", ref="d1", meta={"export_id": "rainfall-monthly"})
    with pytest.raises(BlockFailure) as raised:
        await settle(block, handle, ClimateExportConfig.model_validate(EXPORT), ctx)
    assert raised.value.code == EXPORT_REJECTED.code
    assert raised.value.error_class is ErrorClass.REJECTED
    assert "E7619" in str(raised.value)


@pytest.mark.parametrize("status", ["failed", "cancelled"])
async def test_a_delivery_that_ended_badly_fails_with_its_error(
    status: str, ctx: FakeContext, ocs: ClimateServer
) -> None:
    ocs.on("GET", DELIVERY, body=_delivery(status, error={"type": "DeliveryError", "message": "DHIS2 unreachable"}))
    block = ClimateExportOperator()
    handle = RemoteHandle(block_id="climate.export", ref="d1", meta={"export_id": "rainfall-monthly"})
    probes, _ = await settle(block, handle, ClimateExportConfig.model_validate(EXPORT), ctx)
    assert probes[-1].status is ProbeStatus.FAILED
    assert probes[-1].message is not None and "DHIS2 unreachable" in probes[-1].message


async def test_an_ingestion_is_queued_asynchronously_and_followed_by_its_location(
    ctx: FakeContext, ocs: ClimateServer
) -> None:
    ocs.on(
        "POST",
        "/ingestions",
        status=202,
        body={"ingestion_id": "i1", "status": "accepted", "dataset": None},
        headers={"Location": "/ingestions/jobs/i1"},
    )
    config = {"connection": CONNECTION, "dataset_id": "chirps3_precipitation_daily", "start": "2025-01-01"}
    handle = await call_block(ClimateIngestOperator(), config, ctx)
    assert isinstance(handle, RemoteHandle) and handle.ref == "i1"
    sent = ocs.sent("POST", "/ingestions")[0]
    assert sent.headers["prefer"] == "respond-async"
    assert ocs.body("POST", "/ingestions") == {
        "dataset_id": "chirps3_precipitation_daily",
        "start": "2025-01-01",
        "end": None,
        "overwrite": False,
        "publish": True,
    }


async def test_an_ingestion_reports_progress_and_finishes_with_its_result(ctx: FakeContext, ocs: ClimateServer) -> None:
    ocs.on("GET", "/ingestions/jobs/i1", body=_record("running", progress={"percent": 40.0, "message": "2 of 5"}))
    ocs.on("GET", "/ingestions/jobs/i1", body=_record("successful", result={"dataset_id": "x"}, finishedAt="t"))
    block = ClimateIngestOperator()
    config = ClimateIngestConfig.model_validate({"connection": CONNECTION, "dataset_id": "x"})
    probes, output = await settle(block, RemoteHandle(block_id="climate.ingest", ref="i1"), config, ctx)
    assert (probes[0].progress, probes[0].message) == (0.4, "2 of 5")
    assert isinstance(output, ClimateIngestionOutput)
    assert (output.job_id, output.status, output.result, output.finished_at) == (
        "i1",
        "successful",
        {"dataset_id": "x"},
        "t",
    )


async def test_a_failed_ingestion_fails_with_its_error(ctx: FakeContext, ocs: ClimateServer) -> None:
    ocs.on("GET", "/ingestions/jobs/i1", body=_record("failed", error={"type": "Fetch", "message": "source down"}))
    block = ClimateIngestOperator()
    config = ClimateIngestConfig.model_validate({"connection": CONNECTION, "dataset_id": "x"})
    probes, _ = await settle(block, RemoteHandle(block_id="climate.ingest", ref="i1"), config, ctx)
    assert probes[-1].status is ProbeStatus.FAILED
    assert probes[-1].message is not None and "source down" in probes[-1].message


async def test_a_sync_is_queued_for_its_dataset(ctx: FakeContext, ocs: ClimateServer) -> None:
    ocs.on(
        "POST",
        "/sync/era5land_temperature_daily",
        status=202,
        body={"sync_id": None, "status": "accepted", "message": "Sync queued"},
        headers={"Location": "/ingestions/jobs/s1"},
    )
    config = {"connection": CONNECTION, "dataset_id": "era5land_temperature_daily", "publish": False}
    handle = await call_block(ClimateSyncOperator(), config, ctx)
    assert isinstance(handle, RemoteHandle) and handle.ref == "s1"
    assert ocs.body("POST", "/sync/era5land_temperature_daily") == {"end": None, "publish": False}


async def test_work_the_service_did_inline_is_the_output_at_once(ctx: FakeContext, ocs: ClimateServer) -> None:
    answer = {"sync_id": "s2", "status": "up_to_date", "message": "nothing to sync"}
    ocs.on("POST", "/sync/x", body=answer)
    output = await call_block(ClimateSyncOperator(), {"connection": CONNECTION, "dataset_id": "x"}, ctx)
    assert isinstance(output, ClimateIngestionOutput)
    assert (output.job_id, output.status, output.result) == (None, "up_to_date", answer)


async def test_cancel_asks_the_service_to_stop_the_job(ctx: FakeContext, ocs: ClimateServer) -> None:
    ocs.on("DELETE", "/ingestions/jobs/i1", status=202, body=_record("running", cancelRequested=True))
    config = ClimateIngestConfig.model_validate({"connection": CONNECTION, "dataset_id": "x"})
    handle = RemoteHandle(block_id="climate.ingest", ref="i1")
    assert await ClimateIngestOperator().cancel(handle, config, ctx.as_context()) is True


async def test_a_read_only_instance_refuses_an_ingestion(ctx: FakeContext, ocs: ClimateServer) -> None:
    ocs.on("POST", "/ingestions", status=403, body={"detail": "This instance is read-only"})
    with pytest.raises(BlockFailure) as raised:
        await call_block(ClimateIngestOperator(), {"connection": CONNECTION, "dataset_id": "x"}, ctx)
    assert raised.value.error_class is ErrorClass.REJECTED
    assert "read-only" in str(raised.value)
