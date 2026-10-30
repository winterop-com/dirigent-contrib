"""``climate.job.run`` and ``climate.job.result``: a batch job followed to its results, and its payload downloaded."""

import json
from typing import Any

import httpx2
import pytest

from dirigent_contrib.climate.batch import (
    ClimateJobResultOperator,
    ClimateJobResultOutput,
    ClimateJobRunConfig,
    ClimateJobRunOperator,
    ClimateJobRunOutput,
)
from dirigent_contrib.climate.messages import JOB_NO_ASSET
from dirigent_plugin import BlockFailure, ErrorClass, ProbeStatus, RemoteHandle
from dirigent_testing import FakeContext, call_block
from tests.climate.climateserver import CONNECTION, ClimateServer, settle

GRAPH: dict[str, Any] = {"agg": {"process_id": "aggregate_by_features", "arguments": {}, "result": True}}

RESULTS: dict[str, Any] = {
    "type": "Feature",
    "stac_version": "1.1.0",
    "id": "j1",
    "assets": {
        "result": {"href": "/jobs/j1/results/rainfall.json", "type": "application/json", "roles": ["data"]},
        "manifest": {"href": "/jobs/j1/results/manifest.json", "type": "application/json", "roles": ["metadata"]},
    },
    "links": [],
}

VALUE_SET = {"dataValues": [{"dataElement": "DE1", "period": "202501", "orgUnit": "OU1", "value": "12.5"}]}


def _record(status: str, **fields: Any) -> dict[str, Any]:
    return {"id": "j1", "status": status, "created": "2026-10-30T00:00:00Z", "process": {}, **fields}


def _run_config() -> ClimateJobRunConfig:
    return ClimateJobRunConfig.model_validate({"connection": CONNECTION, "process_graph": GRAPH, "title": "t"})


async def test_a_job_is_created_then_queued(ctx: FakeContext, ocs: ClimateServer) -> None:
    ocs.on("POST", "/jobs", status=201, body=_record("created"), headers={"Location": "/jobs/j1"})
    ocs.on("POST", "/jobs/j1/results", status=202)
    handle = await call_block(
        ClimateJobRunOperator(), {"connection": CONNECTION, "process_graph": GRAPH, "title": "t"}, ctx
    )
    assert isinstance(handle, RemoteHandle) and handle.ref == "j1"
    assert ocs.body("POST", "/jobs") == {"process": {"process_graph": GRAPH}, "title": "t"}
    assert len(ocs.sent("POST", "/jobs/j1/results")) == 1


async def test_a_created_job_without_an_id_in_its_body_is_read_off_its_location(
    ctx: FakeContext, ocs: ClimateServer
) -> None:
    ocs.on("POST", "/jobs", status=201, text="", headers={"Location": "/jobs/j9"})
    ocs.on("POST", "/jobs/j9/results", status=202)
    handle = await call_block(ClimateJobRunOperator(), {"connection": CONNECTION, "process_graph": GRAPH}, ctx)
    assert isinstance(handle, RemoteHandle) and handle.ref == "j9"


async def test_a_job_is_followed_to_its_results(ctx: FakeContext, ocs: ClimateServer) -> None:
    for status in ("queued", "running", "finished"):
        ocs.on("GET", "/jobs/j1", body=_record(status))
    ocs.on("GET", "/jobs/j1/results", body=RESULTS)
    block = ClimateJobRunOperator()
    probes, output = await settle(block, RemoteHandle(block_id="climate.job.run", ref="j1"), _run_config(), ctx)
    assert [probe.status for probe in probes] == [ProbeStatus.RUNNING, ProbeStatus.RUNNING, ProbeStatus.SUCCEEDED]
    assert isinstance(output, ClimateJobRunOutput)
    assert (output.job_id, output.assets, output.results) == ("j1", ["manifest", "result"], RESULTS)


@pytest.mark.parametrize("status", ["error", "canceled"])
async def test_a_job_that_ended_badly_fails_with_its_log(status: str, ctx: FakeContext, ocs: ClimateServer) -> None:
    ocs.on("GET", "/jobs/j1", body=_record(status, logs="loading\nzonal failed: no overlap"))
    block = ClimateJobRunOperator()
    probes, output = await settle(block, RemoteHandle(block_id="climate.job.run", ref="j1"), _run_config(), ctx)
    assert probes[-1].status is ProbeStatus.FAILED
    assert probes[-1].message is not None and "zonal failed: no overlap" in probes[-1].message
    assert output is None
    assert ctx.log.entries[-1][2]["log"] == "loading\nzonal failed: no overlap"


async def test_a_job_the_service_no_longer_knows_is_gone(ctx: FakeContext, ocs: ClimateServer) -> None:
    probe = await ClimateJobRunOperator().probe(
        RemoteHandle(block_id="climate.job.run", ref="j1"), _run_config(), ctx.as_context()
    )
    assert probe.status is ProbeStatus.GONE


async def test_cancel_stops_the_job(ctx: FakeContext, ocs: ClimateServer) -> None:
    ocs.on("DELETE", "/jobs/j1/results", status=204)
    handle = RemoteHandle(block_id="climate.job.run", ref="j1")
    assert await ClimateJobRunOperator().cancel(handle, _run_config(), ctx.as_context()) is True


async def test_the_result_asset_is_downloaded_and_inlined(ctx: FakeContext, ocs: ClimateServer) -> None:
    ocs.on("GET", "/jobs/j1/results", body=RESULTS)
    ocs.on("GET", "/jobs/j1/results/rainfall.json", body=VALUE_SET)
    output = await call_block(ClimateJobResultOperator(), {"connection": CONNECTION, "job_id": "j1"}, ctx)
    assert isinstance(output, ClimateJobResultOutput)
    assert output.value == VALUE_SET
    assert (output.asset, output.href) == ("result", "/jobs/j1/results/rainfall.json")
    assert json.loads(ctx.storage.path_for(output.uri).read_bytes()) == VALUE_SET


async def test_an_asset_href_is_read_under_the_base_urls_path(
    ctx: FakeContext, ocs: ClimateServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    ocs.on("GET", "/ocs/jobs/j1/results", body=RESULTS)
    ocs.on("GET", "/ocs/jobs/j1/results/rainfall.json", body=VALUE_SET)
    prefixed = httpx2.AsyncClient(base_url="http://service.test/ocs", transport=httpx2.MockTransport(ocs))

    def http(ref: str) -> httpx2.AsyncClient:
        return prefixed

    monkeypatch.setattr(ctx, "http", http)
    output = await call_block(ClimateJobResultOperator(), {"connection": CONNECTION, "job_id": "j1"}, ctx)
    assert isinstance(output, ClimateJobResultOutput)
    assert output.value == VALUE_SET


async def test_another_asset_can_be_named(ctx: FakeContext, ocs: ClimateServer) -> None:
    ocs.on("GET", "/jobs/j1/results", body=RESULTS)
    ocs.on("GET", "/jobs/j1/results/manifest.json", body={"version": 1})
    config = {"connection": CONNECTION, "job_id": "j1", "asset": "manifest"}
    output = await call_block(ClimateJobResultOperator(), config, ctx)
    assert isinstance(output, ClimateJobResultOutput)
    assert output.value == {"version": 1}


async def test_an_asset_the_results_do_not_carry_is_refused_naming_those_they_do(
    ctx: FakeContext, ocs: ClimateServer
) -> None:
    ocs.on("GET", "/jobs/j1/results", body=RESULTS)
    with pytest.raises(BlockFailure) as raised:
        await call_block(ClimateJobResultOperator(), {"connection": CONNECTION, "job_id": "j1", "asset": "zarr"}, ctx)
    assert raised.value.code == JOB_NO_ASSET.code
    assert raised.value.error_class is ErrorClass.REJECTED
    assert "manifest, result" in str(raised.value)


async def test_results_of_a_job_that_is_not_finished_are_a_refusal(ctx: FakeContext, ocs: ClimateServer) -> None:
    ocs.on("GET", "/jobs/j1/results", status=400, body={"detail": "Results not available yet; job status is 'running'"})
    with pytest.raises(BlockFailure) as raised:
        await call_block(ClimateJobResultOperator(), {"connection": CONNECTION, "job_id": "j1"}, ctx)
    assert "not available yet" in str(raised.value)
