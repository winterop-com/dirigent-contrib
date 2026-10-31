"""A job id Chap answers with names one job in a path, and cannot move a poll or a cancel elsewhere."""

from typing import Any

import pytest

from dirigent_contrib.chap.backtests import ChapBacktestRunConfig, ChapBacktestRunOperator
from dirigent_contrib.chap.jobs import job_path
from dirigent_plugin import BlockFailure, ErrorClass, ProbeStatus, RemoteHandle
from dirigent_testing import FakeContext, call_block
from tests.chap.chapserver import CONNECTION, ChapServer

SUBMIT = "/v1/analytics/create-backtest"

CONFIG: dict[str, Any] = {"connection": CONNECTION, "name": "b", "model_id": 1, "dataset_id": 2}


@pytest.mark.parametrize(
    "job_id", ["../crud/datasets/7#", "../../other-app/items/7#", "..", "x?force=1", "a/b", "x\n", "%2e%2e", ""]
)
async def test_a_submission_answered_with_anything_but_one_id_fails(
    job_id: str, ctx: FakeContext, chap: ChapServer
) -> None:
    chap.on("POST", SUBMIT, body={"id": job_id})
    with pytest.raises(BlockFailure) as refused:
        await call_block(ChapBacktestRunOperator(), CONFIG, ctx)
    assert refused.value.code == "chap.job.not_submitted"
    assert refused.value.error_class is ErrorClass.UNKNOWN
    assert len(chap.requests) == 1


@pytest.mark.parametrize("job_id", ["job-1", "6f1c7a7e-2f0b-4a55-9d0a-1c2d3e4f5a6b", "celery.task_1"])
async def test_a_submission_answered_with_one_id_is_followed(job_id: str, ctx: FakeContext, chap: ChapServer) -> None:
    chap.on("POST", SUBMIT, body={"id": job_id})
    handle = await call_block(ChapBacktestRunOperator(), CONFIG, ctx)
    assert isinstance(handle, RemoteHandle) and handle.ref == job_id


def test_a_job_path_keeps_a_value_to_one_segment() -> None:
    assert job_path("a/b?c#d", "/cancel") == "/v1/jobs/a%2Fb%3Fc%23d/cancel"
    assert job_path("job-1", "/logs") == "/v1/jobs/job-1/logs"


async def test_a_handle_already_holding_a_bad_id_stays_under_jobs(ctx: FakeContext, chap: ChapServer) -> None:
    handle = RemoteHandle(block_id="chap.backtest.run", ref="../crud/datasets/7")
    config = ChapBacktestRunConfig.model_validate(CONFIG)
    block = ChapBacktestRunOperator()
    probe = await block.probe(handle, config, ctx.as_context())
    await block.cancel(handle, config, ctx.as_context())
    assert probe.status is ProbeStatus.GONE
    assert [request.url.raw_path for request in chap.requests] == [
        b"/v1/jobs/..%2Fcrud%2Fdatasets%2F7",
        b"/v1/jobs/..%2Fcrud%2Fdatasets%2F7/cancel",
    ]
