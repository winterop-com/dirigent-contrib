"""``chap.backtest.run``: a backtest submitted with Chap's defaults left to Chap, and its result read back."""

import pytest

from chapserver import CONNECTION, ChapServer, job, settle
from dirigent_chap.backtests import ChapBacktestRunConfig, ChapBacktestRunOperator, ChapBacktestRunOutput
from dirigent_chap.messages import JOB_NOT_SUBMITTED
from dirigent_plugin import BlockFailure, ErrorClass, RemoteHandle
from dirigent_testing import FakeContext, call_block

CREATE = "/v1/analytics/create-backtest"

BACKTEST = {"id": 7, "name": "laos", "aggregateMetrics": {"crps": 1.25}, "datasetId": 42}


async def test_unset_parameters_are_left_for_chaps_saved_defaults(ctx: FakeContext, chap: ChapServer) -> None:
    chap.on("POST", CREATE, body={"id": "job-b"})
    config = {"connection": CONNECTION, "name": "laos", "model_id": "naive_model", "dataset_id": 42, "n_splits": 4}
    handle = await call_block(ChapBacktestRunOperator(), config, ctx)
    assert isinstance(handle, RemoteHandle) and handle.ref == "job-b"
    assert chap.body("POST", CREATE) == {"name": "laos", "modelId": "naive_model", "datasetId": 42, "nSplits": 4}


async def test_every_declared_parameter_is_sent_camel_case(ctx: FakeContext, chap: ChapServer) -> None:
    chap.on("POST", CREATE, body={"id": "job-b"})
    config = {
        "connection": CONNECTION,
        "name": "laos",
        "model_id": 3,
        "dataset_id": 42,
        "n_periods": 3,
        "n_splits": 7,
        "stride": 1,
        "n_retrain": 1,
        "future_weather_provider": "climatology",
        "target_column": "disease_cases",
    }
    await call_block(ChapBacktestRunOperator(), config, ctx)
    assert chap.body("POST", CREATE) == {
        "name": "laos",
        "modelId": 3,
        "datasetId": 42,
        "nPeriods": 3,
        "nSplits": 7,
        "stride": 1,
        "nRetrain": 1,
        "futureWeatherProvider": "climatology",
        "targetColumn": "disease_cases",
    }


async def test_the_finished_backtest_is_read_with_its_metrics_lifted(ctx: FakeContext, chap: ChapServer) -> None:
    chap.on("GET", "/v1/jobs/job-b", body=job("job-b", "SUCCESS"))
    chap.on("GET", "/v1/jobs/job-b/evaluation_result", body=BACKTEST)
    block = ChapBacktestRunOperator()
    config = ChapBacktestRunConfig.model_validate(
        {"connection": CONNECTION, "name": "laos", "model_id": 3, "dataset_id": 42}
    )
    _, output = await settle(block, block.handle("job-b"), config, ctx)
    assert isinstance(output, ChapBacktestRunOutput)
    assert (output.backtest_id, output.job_id) == (7, "job-b")
    assert output.aggregate_metrics == {"crps": 1.25}
    assert output.backtest == BACKTEST


async def test_an_unknown_dataset_is_a_refusal(ctx: FakeContext, chap: ChapServer) -> None:
    chap.on("POST", CREATE, status=404, body={"detail": "Dataset 42 not found"})
    config = {"connection": CONNECTION, "name": "laos", "model_id": 3, "dataset_id": 42}
    with pytest.raises(BlockFailure) as raised:
        await call_block(ChapBacktestRunOperator(), config, ctx)
    assert raised.value.error_class is ErrorClass.REJECTED
    assert "Dataset 42 not found" in str(raised.value)


async def test_a_submission_without_a_job_id_fails(ctx: FakeContext, chap: ChapServer) -> None:
    chap.on("POST", CREATE, body={})
    config = {"connection": CONNECTION, "name": "laos", "model_id": 3, "dataset_id": 42}
    with pytest.raises(BlockFailure) as raised:
        await call_block(ChapBacktestRunOperator(), config, ctx)
    assert raised.value.code == JOB_NOT_SUBMITTED.code
