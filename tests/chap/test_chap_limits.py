"""What one answer from Chap may cost, against a hostile server on loopback."""

import asyncio
import gzip
import json
import tracemalloc
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import httpx2
import pytest
import pytest_asyncio
from pydantic import ValidationError

from dirigent_contrib.chap.alerts import ChapAlertsListOperator
from dirigent_contrib.chap.backtests import ChapBacktestRunConfig, ChapBacktestRunOperator
from dirigent_contrib.chap.configured_models import ChapModelsListOperator, ChapModelsListOutput
from dirigent_contrib.chap.connection import ChapConnectionConfig, ChapConnectionKind, build_client
from dirigent_contrib.chap.datasets import ChapDatasetImportOperator
from dirigent_plugin import BlockFailure, ErrorClass, ProbeStatus, RemoteHandle
from dirigent_testing import FakeContext, call_block
from tests.chap.chapserver import CONNECTION, ChapServer
from tests.hostile import MIB, Hostile, answer, double_gzip, drip, json_answer

TOKEN = "DUMMYTOKEN4567"

MODELS = "GET /v1/crud/configured-models"
INFO = "GET /system/info"
JOB = "GET /v1/jobs/job-1"
LOGS = "GET /v1/jobs/job-1/logs"
CANCEL = "POST /v1/jobs/job-1/cancel"

TOO_LARGE = "chap.response_too_large"
PAST_DEADLINE = "chap.past_deadline"

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
    """Point the context's connection at the hostile server, over a real client with no transport."""
    config = ChapConnectionConfig.model_validate({"base_url": hostile.url, "api_token": TOKEN, **limits})

    def http(ref: str) -> httpx2.AsyncClient:
        return build_client(config)

    ctx.connections[CONNECTION] = config
    monkeypatch.setattr(ctx, "http", http)


def _config(hostile: Hostile, **limits: Any) -> ChapConnectionConfig:
    return ChapConnectionConfig.model_validate({"base_url": hostile.url, "api_token": TOKEN, **limits})


BACKTEST: dict[str, Any] = {"connection": CONNECTION, "name": "b", "model_id": 1, "dataset_id": 2}


async def test_a_block_read_past_the_default_limit_is_refused(
    ctx: FakeContext, monkeypatch: pytest.MonkeyPatch, hostile: Hostile
) -> None:
    hostile.on(MODELS, double_gzip(65 * MIB))
    _connect(ctx, monkeypatch, hostile)
    with pytest.raises(BlockFailure) as refused:
        await call_block(ChapModelsListOperator(), {"connection": CONNECTION}, ctx)
    assert refused.value.code == TOO_LARGE
    assert refused.value.error_class is ErrorClass.REJECTED


async def test_a_block_read_past_the_limit_costs_little(
    ctx: FakeContext, monkeypatch: pytest.MonkeyPatch, hostile: Hostile
) -> None:
    hostile.on(MODELS, double_gzip(40 * MIB))
    _connect(ctx, monkeypatch, hostile, max_response="1MB")
    tracemalloc.start()
    try:
        with pytest.raises(BlockFailure) as refused:
            await call_block(ChapModelsListOperator(), {"connection": CONNECTION}, ctx)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert refused.value.code == TOO_LARGE
    assert peak < 16 * MIB
    assert MODELS in str(refused.value)
    assert TOKEN not in str(refused.value)


async def test_a_read_within_the_limit_still_answers(
    ctx: FakeContext, monkeypatch: pytest.MonkeyPatch, hostile: Hostile
) -> None:
    body = gzip.compress(json.dumps([{"id": 1}]).encode())
    hostile.on(MODELS, answer("200 OK", body, "Content-Encoding: gzip", "Content-Type: application/json"))
    _connect(ctx, monkeypatch, hostile, max_response="1MB")
    output = await call_block(ChapModelsListOperator(), {"connection": CONNECTION}, ctx)
    assert isinstance(output, ChapModelsListOutput)
    assert output.models == [{"id": 1}]


async def test_an_answer_of_exactly_the_limit_is_read(
    ctx: FakeContext, monkeypatch: pytest.MonkeyPatch, hostile: Hostile
) -> None:
    body = json.dumps(["x" * 100]).encode()
    hostile.on(MODELS, answer("200 OK", body, "Content-Type: application/json"))
    _connect(ctx, monkeypatch, hostile, max_response=len(body))
    output = await call_block(ChapModelsListOperator(), {"connection": CONNECTION}, ctx)
    assert isinstance(output, ChapModelsListOutput)
    _connect(ctx, monkeypatch, hostile, max_response=len(body) - 1)
    with pytest.raises(BlockFailure) as refused:
        await call_block(ChapModelsListOperator(), {"connection": CONNECTION}, ctx)
    assert refused.value.code == TOO_LARGE


async def test_an_error_answer_past_the_limit_keeps_its_status_at_little_cost(
    ctx: FakeContext, monkeypatch: pytest.MonkeyPatch, hostile: Hostile
) -> None:
    hostile.on(MODELS, double_gzip(40 * MIB, "503 Service Unavailable"))
    _connect(ctx, monkeypatch, hostile, max_response="1MB")
    tracemalloc.start()
    try:
        with pytest.raises(BlockFailure) as refused:
            await call_block(ChapModelsListOperator(), {"connection": CONNECTION}, ctx)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert refused.value.code == "chap.answered"
    assert refused.value.error_class is ErrorClass.TRANSIENT
    assert peak < 16 * MIB
    assert len(str(refused.value)) < 1024


async def test_a_short_error_answer_is_quoted_as_before(
    ctx: FakeContext, monkeypatch: pytest.MonkeyPatch, hostile: Hostile
) -> None:
    hostile.on(MODELS, json_answer({"detail": "no such thing"}, "422 Unprocessable Entity"))
    _connect(ctx, monkeypatch, hostile)
    with pytest.raises(BlockFailure) as refused:
        await call_block(ChapModelsListOperator(), {"connection": CONNECTION}, ctx)
    assert "no such thing" in str(refused.value)
    assert refused.value.error_class is ErrorClass.REJECTED


async def test_a_job_read_past_the_limit_is_refused(
    ctx: FakeContext, monkeypatch: pytest.MonkeyPatch, hostile: Hostile
) -> None:
    hostile.on(JOB, double_gzip(8 * MIB))
    _connect(ctx, monkeypatch, hostile, max_response="1MB")
    block = ChapBacktestRunOperator()
    config = ChapBacktestRunConfig.model_validate(BACKTEST)
    with pytest.raises(BlockFailure) as refused:
        await block.probe(block.handle("job-1"), config, ctx.as_context())
    assert refused.value.code == TOO_LARGE


async def test_a_log_past_the_limit_does_not_lose_the_jobs_failure(
    ctx: FakeContext, monkeypatch: pytest.MonkeyPatch, hostile: Hostile
) -> None:
    hostile.on(JOB, json_answer({"id": "job-1", "status": "FAILURE", "error": "out of memory"}))
    hostile.on(LOGS, double_gzip(8 * MIB))
    _connect(ctx, monkeypatch, hostile, max_response="1MB")
    block = ChapBacktestRunOperator()
    config = ChapBacktestRunConfig.model_validate(BACKTEST)
    probe = await block.probe(block.handle("job-1"), config, ctx.as_context())
    assert probe.status is ProbeStatus.FAILED
    assert "out of memory" in (probe.message or "")


async def test_a_dripped_log_does_not_lose_the_jobs_failure(
    ctx: FakeContext, monkeypatch: pytest.MonkeyPatch, hostile: Hostile
) -> None:
    hostile.on(JOB, json_answer({"id": "job-1", "status": "FAILURE", "error": "out of memory"}))
    hostile.on(LOGS, drip)
    _connect(ctx, monkeypatch, hostile, request_deadline=timedelta(milliseconds=200))
    block = ChapBacktestRunOperator()
    config = ChapBacktestRunConfig.model_validate(BACKTEST)
    async with asyncio.timeout(GUARD):
        probe = await block.probe(block.handle("job-1"), config, ctx.as_context())
    assert probe.status is ProbeStatus.FAILED


async def test_a_cancel_reads_only_its_status(
    ctx: FakeContext, monkeypatch: pytest.MonkeyPatch, hostile: Hostile
) -> None:
    hostile.on(CANCEL, double_gzip(40 * MIB))
    _connect(ctx, monkeypatch, hostile)
    block = ChapBacktestRunOperator()
    config = ChapBacktestRunConfig.model_validate(BACKTEST)
    tracemalloc.start()
    try:
        cancelled = await block.cancel(block.handle("job-1"), config, ctx.as_context())
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert cancelled is True
    assert peak < 16 * MIB


async def test_a_check_past_the_limit_is_unhealthy(hostile: Hostile) -> None:
    hostile.on(INFO, double_gzip(8 * MIB))
    report = await ChapConnectionKind().check(_config(hostile, max_response="1MB"))
    assert report.healthy is False
    assert INFO in (report.detail or "")


async def test_a_check_proving_the_token_past_the_limit_is_unhealthy(hostile: Hostile) -> None:
    hostile.on(INFO, json_answer({"chap_core_version": "2.5.1", "auth_required": True}))
    hostile.on(MODELS, double_gzip(8 * MIB))
    report = await ChapConnectionKind().check(_config(hostile, max_response="1MB"))
    assert report.healthy is False
    assert MODELS in (report.detail or "")


async def test_a_drip_fails_a_block_at_the_deadline_as_transient(
    ctx: FakeContext, monkeypatch: pytest.MonkeyPatch, hostile: Hostile
) -> None:
    hostile.on("GET /v1/crud/alerts", drip)
    _connect(ctx, monkeypatch, hostile, request_deadline=timedelta(milliseconds=200), timeout="1s")
    async with asyncio.timeout(GUARD):
        with pytest.raises(BlockFailure) as refused:
            await call_block(ChapAlertsListOperator(), {"connection": CONNECTION}, ctx)
    assert refused.value.code == PAST_DEADLINE
    assert refused.value.error_class is ErrorClass.TRANSIENT


async def test_a_drip_fails_a_check_at_the_deadline(hostile: Hostile) -> None:
    hostile.on(INFO, drip)
    config = _config(hostile, request_deadline=timedelta(milliseconds=200), timeout="1s")
    async with asyncio.timeout(GUARD):
        report = await ChapConnectionKind().check(config)
    assert report.healthy is False
    assert INFO in (report.detail or "")


GEOJSON: dict[str, Any] = {"type": "FeatureCollection", "features": []}

ROW = {"period": "202501", "orgUnit": "OU1", "value": 4.0, "featureName": "disease_cases"}


async def test_a_large_rejected_list_is_held_to_a_budget_in_the_handle(ctx: FakeContext, chap: ChapServer) -> None:
    rejected = [{"reason": "x" * 4096, "orgUnit": f"OU{number}"} for number in range(90)]
    chap.on("POST", "/v1/analytics/make-dataset", body={"id": "job-1", "importedCount": 1, "rejected": rejected})
    config = {"connection": CONNECTION, "name": "d", "geojson": GEOJSON, "provided_data": [ROW]}
    handle = await call_block(ChapDatasetImportOperator(), config, ctx)
    assert isinstance(handle, RemoteHandle)
    assert handle.meta["rejected_count"] == "90"
    assert len(handle.meta["rejected"]) <= 64 * 1024
    assert json.loads(handle.meta["rejected"])[0] == rejected[0]


def test_the_limits_read_as_a_size_and_a_duration() -> None:
    config = ChapConnectionConfig.model_validate(
        {"base_url": "http://x", "max_response": "16KB", "request_deadline": "2m"}
    )
    assert config.max_response == 16 * 1024
    assert config.request_deadline == timedelta(minutes=2)


def test_the_limits_have_defaults() -> None:
    config = ChapConnectionConfig.model_validate({"base_url": "http://x"})
    assert config.max_response == 64 * MIB
    assert config.request_deadline == timedelta(minutes=10)


@pytest.mark.parametrize(("field", "value"), [("max_response", 0), ("request_deadline", "0s")])
def test_a_limit_of_nothing_is_refused(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        ChapConnectionConfig.model_validate({"base_url": "http://x", field: value})
