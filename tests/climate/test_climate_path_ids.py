"""A document's value or a service's answer names one thing in a path, and cannot move a request elsewhere."""

from typing import Any

import pytest
from pydantic import ValidationError

from dirigent_contrib.climate.batch import (
    ClimateJobResultOperator,
    ClimateJobRunConfig,
    ClimateJobRunOperator,
    job_path,
)
from dirigent_contrib.climate.exports import ClimateExportConfig, ClimateExportOperator, delivery_path, export_path
from dirigent_contrib.climate.ingestions import (
    ClimateIngestConfig,
    ClimateIngestOperator,
    ClimateSyncOperator,
    ingestion_job_path,
    sync_path,
)
from dirigent_plugin import AnyOperator, BlockFailure, ErrorClass, ProbeStatus, RemoteHandle
from dirigent_testing import FakeContext, call_block
from tests.climate.climateserver import CONNECTION, ClimateServer

GRAPH: dict[str, Any] = {"agg": {"process_id": "aggregate_by_features", "arguments": {}, "result": True}}

NOT_ONE_ID = [
    "..",
    "../x",
    "../../other-app/admin",
    "x/y",
    "x?publish=false",
    "x#",
    "%2e%2e/x",
    "..%2fx",
    "x\n",
    " x",
    "x y",
    ".hidden",
    "-x",
    "",
    "x" * 257,
]

ONE_ID = ["era5land_temperature_daily", "rainfall-daily", "j1", "v1.2", "6f1c7a7e-2f0b-4a55-9d0a-1c2d3e4f5a6b"]

BLOCKS = [
    pytest.param(ClimateSyncOperator(), {"dataset_id": "VALUE"}, "dataset_id", id="sync"),
    pytest.param(ClimateIngestOperator(), {"dataset_id": "VALUE"}, "dataset_id", id="ingest"),
    pytest.param(ClimateExportOperator(), {"export_id": "VALUE", "job_id": "j1"}, "export_id", id="export"),
    pytest.param(ClimateJobResultOperator(), {"job_id": "VALUE"}, "job_id", id="job-result"),
]


def _with(config: dict[str, Any], value: str) -> dict[str, Any]:
    return {"connection": CONNECTION, **{key: value if held == "VALUE" else held for key, held in config.items()}}


@pytest.mark.parametrize(("block", "config", "field"), BLOCKS)
@pytest.mark.parametrize("value", NOT_ONE_ID)
async def test_a_config_value_that_is_not_one_id_sends_nothing(
    block: AnyOperator, config: dict[str, Any], field: str, value: str, ctx: FakeContext, ocs: ClimateServer
) -> None:
    with pytest.raises(ValidationError) as refused:
        await call_block(block, _with(config, value), ctx)
    assert field in str(refused.value)
    assert ocs.requests == []


@pytest.mark.parametrize(("block", "config", "field"), BLOCKS)
@pytest.mark.parametrize("value", ONE_ID)
def test_a_config_value_that_is_one_id_is_accepted(
    block: AnyOperator, config: dict[str, Any], field: str, value: str
) -> None:
    validated = block.config_model.model_validate(_with(config, value))
    assert getattr(validated, field) == value


def test_a_job_id_only_sent_in_a_body_is_not_held_to_it() -> None:
    config = ClimateExportConfig.model_validate({"connection": CONNECTION, "export_id": "e", "job_id": "a/b"})
    assert config.job_id == "a/b"


ANSWERS_NOT_ONE_ID = ["../../other-app/items/7#", "../crud/datasets/7#", "..", "x?force=1", "a/b", "x\n", "%2e%2e"]


@pytest.mark.parametrize("job_id", ANSWERS_NOT_ONE_ID)
async def test_a_created_job_whose_id_is_not_one_id_is_not_followed(
    job_id: str, ctx: FakeContext, ocs: ClimateServer
) -> None:
    ocs.on("POST", "/jobs", status=201, body={"id": job_id})
    with pytest.raises(BlockFailure) as refused:
        await call_block(ClimateJobRunOperator(), {"connection": CONNECTION, "process_graph": GRAPH}, ctx)
    assert refused.value.code == "climate.job.not_submitted"
    assert refused.value.error_class is ErrorClass.UNKNOWN
    assert [request.url.path for request in ocs.requests] == ["/jobs"]


async def test_a_created_job_whose_location_climbs_is_not_followed(ctx: FakeContext, ocs: ClimateServer) -> None:
    ocs.on("POST", "/jobs", status=201, text="", headers={"Location": "/jobs/.."})
    with pytest.raises(BlockFailure) as refused:
        await call_block(ClimateJobRunOperator(), {"connection": CONNECTION, "process_graph": GRAPH}, ctx)
    assert refused.value.code == "climate.job.not_submitted"
    assert len(ocs.requests) == 1


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param({"headers": {"Location": "/ingestions/jobs/.."}}, id="location-parent"),
        pytest.param({"headers": {"Location": "/ingestions/jobs/x?force=1"}}, id="location-query"),
        pytest.param({"body": {"ingestion_id": "../../other-app/items/7#"}}, id="body"),
    ],
)
async def test_a_queued_ingestion_whose_id_is_not_one_id_fails(
    answer: dict[str, Any], ctx: FakeContext, ocs: ClimateServer
) -> None:
    ocs.on("POST", "/ingestions", status=202, **answer)
    with pytest.raises(BlockFailure) as refused:
        await call_block(ClimateIngestOperator(), {"connection": CONNECTION, "dataset_id": "x"}, ctx)
    assert refused.value.code == "climate.job.not_submitted"
    assert len(ocs.requests) == 1


@pytest.mark.parametrize("delivery", ANSWERS_NOT_ONE_ID)
async def test_a_delivery_whose_id_is_not_one_id_fails(delivery: str, ctx: FakeContext, ocs: ClimateServer) -> None:
    ocs.on("POST", "/exports/e", status=202, body={"delivery_job_id": delivery})
    with pytest.raises(BlockFailure) as refused:
        await call_block(ClimateExportOperator(), {"connection": CONNECTION, "export_id": "e", "job_id": "j1"}, ctx)
    assert refused.value.code == "climate.job.not_submitted"
    assert len(ocs.requests) == 1


def test_the_path_helpers_keep_a_value_to_one_segment() -> None:
    assert job_path("a/b?c#d", "/results") == "/jobs/a%2Fb%3Fc%23d/results"
    assert sync_path("a/b") == "/sync/a%2Fb"
    assert export_path("a/b") == "/exports/a%2Fb"
    assert delivery_path("a/b", "c/d") == "/exports/a%2Fb/jobs/c%2Fd"
    assert ingestion_job_path("a/b") == "/ingestions/jobs/a%2Fb"


def test_the_path_helpers_leave_a_plain_id_as_it_is() -> None:
    assert job_path("j1", "/results") == "/jobs/j1/results"
    assert delivery_path("rainfall-monthly", "d.1_x") == "/exports/rainfall-monthly/jobs/d.1_x"


async def test_a_handle_already_holding_a_bad_id_stays_under_jobs(ctx: FakeContext, ocs: ClimateServer) -> None:
    handle = RemoteHandle(block_id="climate.job.run", ref="../../other-app/items/7")
    config = ClimateJobRunConfig.model_validate({"connection": CONNECTION, "process_graph": GRAPH})
    probe = await ClimateJobRunOperator().probe(handle, config, ctx.as_context())
    await ClimateJobRunOperator().cancel(handle, config, ctx.as_context())
    assert probe.status is ProbeStatus.GONE
    assert [request.url.raw_path for request in ocs.requests] == [
        b"/jobs/..%2F..%2Fother-app%2Fitems%2F7",
        b"/jobs/..%2F..%2Fother-app%2Fitems%2F7/results",
    ]


async def test_an_ingestion_handle_already_holding_a_bad_id_stays_under_its_path(
    ctx: FakeContext, ocs: ClimateServer
) -> None:
    handle = RemoteHandle(block_id="climate.ingest", ref="../../other-app")
    config = ClimateIngestConfig.model_validate({"connection": CONNECTION, "dataset_id": "x"})
    await ClimateIngestOperator().cancel(handle, config, ctx.as_context())
    assert ocs.requests[0].url.raw_path == b"/ingestions/jobs/..%2F..%2Fother-app"
