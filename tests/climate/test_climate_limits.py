"""What one answer from the climate service may cost, against a hostile service on loopback."""

import asyncio
import json
import tracemalloc
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx2
import pytest
import pytest_asyncio
from pydantic import ValidationError

from dirigent_contrib.climate.aggregate import ClimateAggregateOperator, ClimateAggregateOutput
from dirigent_contrib.climate.batch import ClimateJobResultOperator, ClimateJobRunConfig, ClimateJobRunOperator
from dirigent_contrib.climate.connection import ClimateConnectionConfig, ClimateConnectionKind, build_client
from dirigent_contrib.climate.datasets import ClimateDatasetsListOperator
from dirigent_contrib.climate.exports import ClimateExportConfig, ClimateExportOperator
from dirigent_contrib.climate.ingestions import ClimateIngestConfig, ClimateIngestOperator
from dirigent_plugin import BlockFailure, ErrorClass, RemoteHandle
from dirigent_testing import FakeContext, FakeStorage, call_block
from tests.climate.climateserver import CONNECTION
from tests.hostile import MIB, Hostile, answer, double_gzip, drip, json_answer

GRAPH: dict[str, Any] = {"agg": {"process_id": "aggregate_by_features", "arguments": {}, "result": True}}

AGGREGATE_CONFIG: dict[str, Any] = {"connection": CONNECTION, "process_graph": GRAPH}

RESULT = "POST /result"
HEALTH = "GET /health"
INFO = "GET /info"

TOO_LARGE = "climate.response_too_large"
PAST_DEADLINE = "climate.past_deadline"

#: How long a test waits on a drip before calling it unbounded.
GUARD = 10


@pytest_asyncio.fixture
async def hostile() -> AsyncIterator[Hostile]:
    server = Hostile()
    await server.start()
    try:
        yield server
    finally:
        server.stop()


def _connect(ctx: FakeContext, monkeypatch: pytest.MonkeyPatch, hostile: Hostile, **limits: Any) -> None:
    """Point the context's connection at the hostile service, over a real client with no transport."""
    config = ClimateConnectionConfig.model_validate({"base_url": hostile.url, **limits})

    def http(ref: str) -> httpx2.AsyncClient:
        return build_client(config)

    ctx.connections[CONNECTION] = config
    monkeypatch.setattr(ctx, "http", http)


def _stored(storage: FakeStorage) -> int:
    """How many bytes the run's storage holds."""
    return sum(path.stat().st_size for path in Path(storage.root).rglob("*") if path.is_file())


async def test_an_aggregate_past_the_default_limit_stops_at_it(
    ctx: FakeContext, monkeypatch: pytest.MonkeyPatch, hostile: Hostile, block_storage: FakeStorage
) -> None:
    hostile.on(RESULT, double_gzip(65 * MIB))
    _connect(ctx, monkeypatch, hostile)
    with pytest.raises(BlockFailure) as refused:
        await call_block(ClimateAggregateOperator(), AGGREGATE_CONFIG, ctx)
    assert refused.value.code == TOO_LARGE
    assert refused.value.error_class is ErrorClass.REJECTED
    assert _stored(block_storage) <= 64 * MIB


async def test_an_aggregate_past_the_limit_writes_at_most_the_limit(
    ctx: FakeContext, monkeypatch: pytest.MonkeyPatch, hostile: Hostile, block_storage: FakeStorage
) -> None:
    hostile.on(RESULT, double_gzip(40 * MIB))
    _connect(ctx, monkeypatch, hostile, max_response="1MB")
    with pytest.raises(BlockFailure) as refused:
        await call_block(ClimateAggregateOperator(), AGGREGATE_CONFIG, ctx)
    assert refused.value.code == TOO_LARGE
    assert RESULT in str(refused.value)
    assert _stored(block_storage) <= MIB


async def test_a_step_may_raise_the_limit_for_its_own_answer(
    ctx: FakeContext, monkeypatch: pytest.MonkeyPatch, hostile: Hostile
) -> None:
    hostile.on(RESULT, double_gzip(2 * MIB))
    _connect(ctx, monkeypatch, hostile, max_response="1MB")
    output = await call_block(ClimateAggregateOperator(), {**AGGREGATE_CONFIG, "max_response": "4MB"}, ctx)
    assert isinstance(output, ClimateAggregateOutput)
    assert output.size_bytes > 2 * MIB


async def test_an_error_answer_past_the_limit_keeps_its_status_at_little_cost(
    ctx: FakeContext, monkeypatch: pytest.MonkeyPatch, hostile: Hostile
) -> None:
    hostile.on(RESULT, double_gzip(40 * MIB, "500 Internal Server Error"))
    _connect(ctx, monkeypatch, hostile)
    tracemalloc.start()
    try:
        with pytest.raises(BlockFailure) as refused:
            await call_block(ClimateAggregateOperator(), AGGREGATE_CONFIG, ctx)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert refused.value.code == "climate.answered"
    assert refused.value.error_class is ErrorClass.TRANSIENT
    assert peak < 16 * MIB
    assert len(str(refused.value)) < 1024


async def test_a_short_error_answer_is_quoted_as_before(
    ctx: FakeContext, monkeypatch: pytest.MonkeyPatch, hostile: Hostile
) -> None:
    hostile.on(RESULT, json_answer({"detail": "no such graph"}, "422 Unprocessable Entity"))
    _connect(ctx, monkeypatch, hostile)
    with pytest.raises(BlockFailure) as refused:
        await call_block(ClimateAggregateOperator(), AGGREGATE_CONFIG, ctx)
    assert "no such graph" in str(refused.value)
    assert refused.value.error_class is ErrorClass.REJECTED


async def test_an_aggregate_drip_fails_at_its_timeout(
    ctx: FakeContext, monkeypatch: pytest.MonkeyPatch, hostile: Hostile
) -> None:
    hostile.on(RESULT, drip)
    _connect(ctx, monkeypatch, hostile)
    async with asyncio.timeout(GUARD):
        with pytest.raises(BlockFailure) as refused:
            await call_block(ClimateAggregateOperator(), {**AGGREGATE_CONFIG, "timeout": "200ms"}, ctx)
    assert refused.value.code == PAST_DEADLINE
    assert refused.value.error_class is ErrorClass.TRANSIENT


async def test_a_results_read_past_the_limit_is_refused_at_little_cost(
    ctx: FakeContext, monkeypatch: pytest.MonkeyPatch, hostile: Hostile
) -> None:
    hostile.on("GET /jobs/j1/results", double_gzip(40 * MIB))
    _connect(ctx, monkeypatch, hostile, max_response="1MB")
    tracemalloc.start()
    try:
        with pytest.raises(BlockFailure) as refused:
            await call_block(ClimateJobResultOperator(), {"connection": CONNECTION, "job_id": "j1"}, ctx)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert refused.value.code == TOO_LARGE
    assert peak < 16 * MIB


async def test_an_asset_past_the_limit_writes_at_most_the_limit(
    ctx: FakeContext, monkeypatch: pytest.MonkeyPatch, hostile: Hostile, block_storage: FakeStorage
) -> None:
    hostile.on("GET /jobs/j1/results", json_answer({"assets": {"result": {"href": "rain.json"}}}))
    hostile.on("GET /rain.json", double_gzip(40 * MIB))
    _connect(ctx, monkeypatch, hostile, max_response="1MB")
    with pytest.raises(BlockFailure) as refused:
        await call_block(ClimateJobResultOperator(), {"connection": CONNECTION, "job_id": "j1"}, ctx)
    assert refused.value.code == TOO_LARGE
    assert _stored(block_storage) <= MIB


async def test_a_step_may_raise_the_limit_for_its_own_asset(
    ctx: FakeContext, monkeypatch: pytest.MonkeyPatch, hostile: Hostile
) -> None:
    hostile.on("GET /jobs/j1/results", json_answer({"assets": {"result": {"href": "rain.json"}}}))
    hostile.on("GET /rain.json", double_gzip(2 * MIB))
    _connect(ctx, monkeypatch, hostile, max_response="1MB")
    config = {"connection": CONNECTION, "job_id": "j1", "max_response": "4MB"}
    output = await call_block(ClimateJobResultOperator(), config, ctx)
    assert output.model_dump()["size_bytes"] > 2 * MIB


async def test_a_dataset_listing_past_the_limit_is_refused(
    ctx: FakeContext, monkeypatch: pytest.MonkeyPatch, hostile: Hostile
) -> None:
    hostile.on("GET /datasets", double_gzip(8 * MIB))
    _connect(ctx, monkeypatch, hostile, max_response="1MB")
    with pytest.raises(BlockFailure) as refused:
        await call_block(ClimateDatasetsListOperator(), {"connection": CONNECTION}, ctx)
    assert refused.value.code == TOO_LARGE


async def test_a_batch_probe_past_the_limit_is_refused(
    ctx: FakeContext, monkeypatch: pytest.MonkeyPatch, hostile: Hostile
) -> None:
    hostile.on("GET /jobs/j1", double_gzip(8 * MIB))
    _connect(ctx, monkeypatch, hostile, max_response="1MB")
    config = ClimateJobRunConfig.model_validate(AGGREGATE_CONFIG)
    handle = RemoteHandle(block_id="climate.job.run", ref="j1")
    with pytest.raises(BlockFailure) as refused:
        await ClimateJobRunOperator().probe(handle, config, ctx.as_context())
    assert refused.value.code == TOO_LARGE


async def test_a_delivery_read_past_the_limit_is_refused(
    ctx: FakeContext, monkeypatch: pytest.MonkeyPatch, hostile: Hostile
) -> None:
    hostile.on("GET /exports/e/jobs/d1", double_gzip(8 * MIB))
    _connect(ctx, monkeypatch, hostile, max_response="1MB")
    config = ClimateExportConfig.model_validate({"connection": CONNECTION, "export_id": "e", "job_id": "j1"})
    handle = RemoteHandle(block_id="climate.export", ref="d1", meta={"export_id": "e"})
    with pytest.raises(BlockFailure) as refused:
        await ClimateExportOperator().probe(handle, config, ctx.as_context())
    assert refused.value.code == TOO_LARGE


async def test_an_ingestion_read_past_the_limit_is_refused(
    ctx: FakeContext, monkeypatch: pytest.MonkeyPatch, hostile: Hostile
) -> None:
    hostile.on("GET /ingestions/jobs/i1", double_gzip(8 * MIB))
    _connect(ctx, monkeypatch, hostile, max_response="1MB")
    config = ClimateIngestConfig.model_validate({"connection": CONNECTION, "dataset_id": "x"})
    handle = RemoteHandle(block_id="climate.ingest", ref="i1")
    with pytest.raises(BlockFailure) as refused:
        await ClimateIngestOperator().probe(handle, config, ctx.as_context())
    assert refused.value.code == TOO_LARGE


@pytest.mark.parametrize(
    ("route", "block", "config", "ref"),
    [
        pytest.param(
            "DELETE /jobs/j1/results",
            ClimateJobRunOperator(),
            ClimateJobRunConfig.model_validate(AGGREGATE_CONFIG),
            "j1",
            id="batch",
        ),
        pytest.param(
            "DELETE /ingestions/jobs/i1",
            ClimateIngestOperator(),
            ClimateIngestConfig.model_validate({"connection": CONNECTION, "dataset_id": "x"}),
            "i1",
            id="ingestion",
        ),
    ],
)
async def test_a_cancel_reads_only_its_status(
    route: str,
    block: Any,
    config: Any,
    ref: str,
    ctx: FakeContext,
    monkeypatch: pytest.MonkeyPatch,
    hostile: Hostile,
) -> None:
    hostile.on(route, double_gzip(40 * MIB))
    _connect(ctx, monkeypatch, hostile)
    handle = RemoteHandle(block_id=block.spec.id, ref=ref)
    tracemalloc.start()
    try:
        cancelled = await block.cancel(handle, config, ctx.as_context())
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert cancelled is True
    assert peak < 16 * MIB


async def test_a_check_past_the_limit_is_unhealthy(hostile: Hostile) -> None:
    hostile.on(HEALTH, double_gzip(8 * MIB))
    config = ClimateConnectionConfig.model_validate({"base_url": hostile.url, "max_response": "1MB"})
    report = await ClimateConnectionKind().check(config)
    assert report.healthy is False
    assert HEALTH in (report.detail or "")


async def test_a_check_whose_info_is_past_the_limit_is_unhealthy(hostile: Hostile) -> None:
    hostile.on(HEALTH, json_answer({"status": "healthy"}))
    hostile.on(INFO, double_gzip(8 * MIB))
    config = ClimateConnectionConfig.model_validate({"base_url": hostile.url, "max_response": "1MB"})
    report = await ClimateConnectionKind().check(config)
    assert report.healthy is False
    assert INFO in (report.detail or "")


async def test_a_drip_fails_a_read_at_the_connections_deadline(
    ctx: FakeContext, monkeypatch: pytest.MonkeyPatch, hostile: Hostile
) -> None:
    hostile.on("GET /datasets", drip)
    _connect(ctx, monkeypatch, hostile, request_deadline=timedelta(milliseconds=200), timeout="1s")
    async with asyncio.timeout(GUARD):
        with pytest.raises(BlockFailure) as refused:
            await call_block(ClimateDatasetsListOperator(), {"connection": CONNECTION}, ctx)
    assert refused.value.code == PAST_DEADLINE
    assert refused.value.error_class is ErrorClass.TRANSIENT


async def test_a_drip_fails_a_download_at_the_connections_deadline(
    ctx: FakeContext, monkeypatch: pytest.MonkeyPatch, hostile: Hostile
) -> None:
    hostile.on("GET /jobs/j1/results", json_answer({"assets": {"result": {"href": "rain.json"}}}))
    hostile.on("GET /rain.json", drip)
    _connect(ctx, monkeypatch, hostile, request_deadline=timedelta(milliseconds=200), timeout="1s")
    async with asyncio.timeout(GUARD):
        with pytest.raises(BlockFailure) as refused:
            await call_block(ClimateJobResultOperator(), {"connection": CONNECTION, "job_id": "j1"}, ctx)
    assert refused.value.code == PAST_DEADLINE


async def test_a_drip_fails_a_check_at_the_deadline(hostile: Hostile) -> None:
    hostile.on(HEALTH, drip)
    config = ClimateConnectionConfig.model_validate(
        {"base_url": hostile.url, "request_deadline": timedelta(milliseconds=200), "timeout": "1s"}
    )
    async with asyncio.timeout(GUARD):
        report = await ClimateConnectionKind().check(config)
    assert report.healthy is False
    assert HEALTH in (report.detail or "")


async def test_a_small_answer_is_still_captured_and_inlined(
    ctx: FakeContext, monkeypatch: pytest.MonkeyPatch, hostile: Hostile
) -> None:
    hostile.on(RESULT, answer("200 OK", json.dumps({"rows": 1}).encode(), "Content-Type: application/json"))
    _connect(ctx, monkeypatch, hostile)
    output = await call_block(ClimateAggregateOperator(), AGGREGATE_CONFIG, ctx)
    assert isinstance(output, ClimateAggregateOutput)
    assert output.value == {"rows": 1}


def test_the_limits_read_as_a_size_and_a_duration() -> None:
    config = ClimateConnectionConfig.model_validate(
        {"base_url": "http://x", "max_response": "16KB", "request_deadline": "2m"}
    )
    assert config.max_response == 16 * 1024
    assert config.request_deadline == timedelta(minutes=2)


def test_the_limits_have_defaults() -> None:
    config = ClimateConnectionConfig.model_validate({"base_url": "http://x"})
    assert config.max_response == 64 * MIB
    assert config.request_deadline == timedelta(minutes=10)


@pytest.mark.parametrize(("field", "value"), [("max_response", 0), ("request_deadline", "0s")])
def test_a_limit_of_nothing_is_refused(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        ClimateConnectionConfig.model_validate({"base_url": "http://x", field: value})
