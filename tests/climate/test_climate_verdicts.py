"""A step succeeds only on an answer that says so: a delivery's report, and work done inline."""

from typing import Any

import pytest

from dirigent_contrib.climate.exports import ClimateExportConfig, ClimateExportOperator, ClimateExportOutput
from dirigent_contrib.climate.ingestions import (
    ClimateIngestionOutput,
    ClimateIngestOperator,
    ClimateSyncConfig,
    ClimateSyncOperator,
)
from dirigent_plugin import AnyOperator, BlockFailure, ErrorClass, ProbeStatus, RemoteHandle
from dirigent_testing import FakeContext, call_block
from tests.climate.climateserver import CONNECTION, ClimateServer, settle

EXPORT_PATH = "/exports/e"
DELIVERY = "/exports/e/jobs/d1"

DIFFERS = "climate.export.dry_run_differs"
NO_OUTCOME = "climate.export.no_outcome"
NOT_FINISHED = "climate.job.not_finished_inline"


def _export(dry_run: bool) -> dict[str, Any]:
    return {"connection": CONNECTION, "export_id": "e", "job_id": "j1", "dry_run": dry_run}


@pytest.mark.parametrize("asked", [True, False])
async def test_an_acceptance_answering_another_dry_run_fails(asked: bool, ctx: FakeContext, ocs: ClimateServer) -> None:
    ocs.on("POST", EXPORT_PATH, status=202, body={"delivery_job_id": "d1", "dry_run": not asked})
    with pytest.raises(BlockFailure) as refused:
        await call_block(ClimateExportOperator(), _export(asked), ctx)
    assert refused.value.code == DIFFERS
    assert refused.value.error_class is ErrorClass.UNKNOWN


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param({"delivery_job_id": "d1", "dry_run": True}, id="the-same"),
        pytest.param({"delivery_job_id": "d1"}, id="no-echo"),
        pytest.param({"delivery_job_id": "d1", "dry_run": "true"}, id="not-a-boolean"),
    ],
)
async def test_an_acceptance_that_does_not_differ_is_followed(
    answer: dict[str, Any], ctx: FakeContext, ocs: ClimateServer
) -> None:
    ocs.on("POST", EXPORT_PATH, status=202, body=answer)
    handle = await call_block(ClimateExportOperator(), _export(True), ctx)
    assert isinstance(handle, RemoteHandle)
    assert handle.meta["dry_run"] == "true"


async def _fetch(ctx: FakeContext, ocs: ClimateServer, delivery: dict[str, Any], *, asked: bool) -> ClimateExportOutput:
    ocs.on("GET", DELIVERY, body={"status": "successful", **delivery})
    handle = RemoteHandle(
        block_id="climate.export", ref="d1", meta={"export_id": "e", "dry_run": "true" if asked else "false"}
    )
    config = ClimateExportConfig.model_validate(_export(asked))
    return await ClimateExportOperator().fetch(handle, config, ctx.as_context())


@pytest.mark.parametrize(
    ("asked", "outcome"),
    [
        pytest.param(True, "success", id="wrote-under-a-dry-run"),
        pytest.param(True, "SUCCESS", id="wrote-under-a-dry-run-uppercase"),
        pytest.param(False, "dry_run", id="validated-under-a-delivery"),
        pytest.param(False, "DRY_RUN", id="validated-under-a-delivery-uppercase"),
    ],
)
async def test_an_outcome_of_what_the_step_did_not_ask_fails(
    asked: bool, outcome: str, ctx: FakeContext, ocs: ClimateServer
) -> None:
    with pytest.raises(BlockFailure) as refused:
        await _fetch(ctx, ocs, {"report": {"outcome": outcome}}, asked=asked)
    assert refused.value.code == DIFFERS


@pytest.mark.parametrize(
    "delivery",
    [
        pytest.param({"report": None}, id="report-null"),
        pytest.param({}, id="no-report"),
        pytest.param({"report": "not a report"}, id="report-text"),
        pytest.param({"report": {"imported": 0, "conflicts": [{"value": "bad"}]}}, id="no-outcome"),
        pytest.param({"report": {"outcome": None}}, id="outcome-null"),
        pytest.param({"report": {"outcome": ""}}, id="outcome-empty"),
        pytest.param({"report": {"outcome": 1}}, id="outcome-a-number"),
    ],
)
async def test_a_report_with_no_outcome_fails(delivery: dict[str, Any], ctx: FakeContext, ocs: ClimateServer) -> None:
    with pytest.raises(BlockFailure) as refused:
        await _fetch(ctx, ocs, delivery, asked=False)
    assert refused.value.code == NO_OUTCOME
    assert refused.value.error_class is ErrorClass.UNKNOWN


async def test_a_rejection_in_capitals_is_a_rejection(ctx: FakeContext, ocs: ClimateServer) -> None:
    with pytest.raises(BlockFailure) as refused:
        await _fetch(ctx, ocs, {"report": {"outcome": "REJECTED", "message": "E7619"}}, asked=False)
    assert refused.value.code == "climate.export.rejected"
    assert refused.value.error_class is ErrorClass.REJECTED


@pytest.mark.parametrize(
    ("asked", "outcome"),
    [
        (True, "dry_run"),
        (False, "success"),
        (False, "partial"),
        (True, "partial"),
        (False, "cancelled"),
        (False, "unknown"),
    ],
)
async def test_the_documented_outcomes_keep_their_results(
    asked: bool, outcome: str, ctx: FakeContext, ocs: ClimateServer
) -> None:
    output = await _fetch(ctx, ocs, {"report": {"outcome": outcome}}, asked=asked)
    assert (output.outcome, output.dry_run) == (outcome, asked)


INLINE = [
    pytest.param(ClimateSyncOperator(), "/sync/x", id="sync"),
    pytest.param(ClimateIngestOperator(), "/ingestions", id="ingest"),
]


@pytest.mark.parametrize(("block", "route"), INLINE)
@pytest.mark.parametrize(
    ("status", "body"),
    [
        pytest.param(200, {"status": "failed", "error": {"message": "source down"}}, id="200-failed"),
        pytest.param(200, {"status": "cancelled"}, id="200-cancelled"),
        pytest.param(200, {"status": "running"}, id="200-running"),
        pytest.param(200, {"status": "successful"}, id="200-successful-is-the-job-paths-word"),
        pytest.param(200, {}, id="200-no-status"),
        pytest.param(200, {"status": ["successful"]}, id="200-status-a-list"),
        pytest.param(200, [], id="200-a-list"),
        pytest.param(201, {"status": "failed"}, id="201-failed"),
        pytest.param(302, {"status": "failed"}, id="302-failed"),
        pytest.param(302, {"status": "completed"}, id="302-completed"),
    ],
)
async def test_an_inline_answer_that_does_not_say_it_finished_fails(
    block: AnyOperator, route: str, status: int, body: Any, ctx: FakeContext, ocs: ClimateServer
) -> None:
    ocs.on("POST", route, status=status, body=body)
    with pytest.raises(BlockFailure) as refused:
        await call_block(block, {"connection": CONNECTION, "dataset_id": "x"}, ctx)
    assert refused.value.code == NOT_FINISHED
    assert refused.value.error_class is ErrorClass.UNKNOWN


@pytest.mark.parametrize(("block", "route"), INLINE)
@pytest.mark.parametrize("word", ["completed", "up_to_date", "waiting_for_source"])
async def test_an_inline_answer_that_says_it_finished_is_the_output(
    block: AnyOperator, route: str, word: str, ctx: FakeContext, ocs: ClimateServer
) -> None:
    ocs.on("POST", route, body={"status": word})
    output = await call_block(block, {"connection": CONNECTION, "dataset_id": "x"}, ctx)
    assert isinstance(output, ClimateIngestionOutput)
    assert (output.job_id, output.status) == (None, word)


@pytest.mark.parametrize(("block", "route"), INLINE)
async def test_a_dataset_that_can_never_sync_fails_without_a_retry(
    block: AnyOperator, route: str, ctx: FakeContext, ocs: ClimateServer
) -> None:
    ocs.on("POST", route, body={"sync_id": None, "status": "not_syncable", "message": "static"})
    with pytest.raises(BlockFailure) as refused:
        await call_block(block, {"connection": CONNECTION, "dataset_id": "x"}, ctx)
    assert refused.value.code == "climate.job.not_syncable"
    assert refused.value.error_class is ErrorClass.REJECTED


async def test_a_queued_job_is_still_followed(ctx: FakeContext, ocs: ClimateServer) -> None:
    ocs.on("POST", "/sync/x", status=202, headers={"Location": "/ingestions/jobs/s1"})
    handle = await call_block(ClimateSyncOperator(), {"connection": CONNECTION, "dataset_id": "x"}, ctx)
    assert isinstance(handle, RemoteHandle) and handle.ref == "s1"


JOB = "/ingestions/jobs/s1"


def _finished_job(result: Any) -> dict[str, Any]:
    return {"jobID": "s1", "status": "successful", "finishedAt": "t", "result": result}


async def _settle_sync(ctx: FakeContext, ocs: ClimateServer, result: Any) -> ClimateIngestionOutput:
    ocs.on("GET", JOB, body=_finished_job(result))
    config = ClimateSyncConfig.model_validate({"connection": CONNECTION, "dataset_id": "x"})
    handle = RemoteHandle(block_id="climate.sync", ref="s1")
    probes, output = await settle(ClimateSyncOperator(), handle, config, ctx)
    assert probes[-1].status is ProbeStatus.SUCCEEDED
    assert isinstance(output, ClimateIngestionOutput)
    return output


async def test_a_job_that_found_the_dataset_not_syncable_fails_without_a_retry(
    ctx: FakeContext, ocs: ClimateServer
) -> None:
    with pytest.raises(BlockFailure) as refused:
        await _settle_sync(ctx, ocs, {"sync_id": None, "status": "not_syncable", "message": "static"})
    assert refused.value.code == "climate.job.not_syncable"
    assert refused.value.error_class is ErrorClass.REJECTED
    assert JOB in str(refused.value)


async def test_a_job_waiting_for_its_source_succeeds_with_the_word_in_its_status(
    ctx: FakeContext, ocs: ClimateServer
) -> None:
    result = {"sync_id": None, "status": "waiting_for_source", "message": "release not served yet"}
    output = await _settle_sync(ctx, ocs, result)
    assert (output.job_id, output.status, output.result) == ("s1", "waiting_for_source", result)


@pytest.mark.parametrize(
    "result",
    [
        pytest.param({"status": "completed"}, id="completed"),
        pytest.param({"status": "up_to_date"}, id="up-to-date"),
        pytest.param({"dataset_id": "x"}, id="no-word"),
        pytest.param("text", id="not-an-object"),
        pytest.param(None, id="no-result"),
    ],
)
async def test_any_other_finished_job_keeps_the_jobs_own_status(
    result: Any, ctx: FakeContext, ocs: ClimateServer
) -> None:
    output = await _settle_sync(ctx, ocs, result)
    assert (output.status, output.result) == ("successful", result)
