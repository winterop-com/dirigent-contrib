"""``chap.prediction.run`` and ``chap.prediction.read``: a forecast from a saved setup, and its quantiles."""

from typing import Any

import pytest

from dirigent_contrib.chap.predictions import (
    ChapPredictionReadOperator,
    ChapPredictionReadOutput,
    ChapPredictionRunConfig,
    ChapPredictionRunOperator,
    ChapPredictionRunOutput,
)
from dirigent_plugin import BlockFailure, ErrorClass, RemoteHandle
from dirigent_testing import FakeContext, call_block
from tests.chap.chapserver import CONNECTION, ChapServer, job, settle

RUN = "/v1/crud/prediction-setups/5/run"

ROW = {"period": "202501", "orgUnit": "OU1", "value": 4.0, "featureName": "disease_cases"}


def _config(**overrides: Any) -> dict[str, Any]:
    return {
        "connection": CONNECTION,
        "prediction_setup_id": 5,
        "name": "next quarter",
        "geojson": {"type": "FeatureCollection", "features": []},
        "provided_data": [ROW],
        **overrides,
    }


async def test_a_setup_is_run_with_the_observations_it_is_given(ctx: FakeContext, chap: ChapServer) -> None:
    chap.on("POST", RUN, body={"id": "job-p"})
    handle = await call_block(ChapPredictionRunOperator(), _config(n_periods=3, type="prediction"), ctx)
    assert isinstance(handle, RemoteHandle) and handle.ref == "job-p"
    body = chap.body("POST", RUN)
    assert body["providedData"] == [ROW]
    assert (body["name"], body["nPeriods"], body["type"]) == ("next quarter", 3, "prediction")


@pytest.mark.parametrize("status", [404, 409, 422])
async def test_an_unknown_setup_an_archived_model_and_bad_data_are_refusals(
    status: int, ctx: FakeContext, chap: ChapServer
) -> None:
    chap.on("POST", RUN, status=status, body={"detail": "no"})
    with pytest.raises(BlockFailure) as raised:
        await call_block(ChapPredictionRunOperator(), _config(), ctx)
    assert raised.value.error_class is ErrorClass.REJECTED


async def test_the_finished_prediction_is_read_back(ctx: FakeContext, chap: ChapServer) -> None:
    prediction = {"id": 11, "name": "next quarter", "nPeriods": 3}
    chap.on("GET", "/v1/jobs/job-p", body=job("job-p", "SUCCESS"))
    chap.on("GET", "/v1/jobs/job-p/prediction_result", body=prediction)
    block = ChapPredictionRunOperator()
    config = ChapPredictionRunConfig.model_validate(_config())
    _, output = await settle(block, block.handle("job-p"), config, ctx)
    assert isinstance(output, ChapPredictionRunOutput)
    assert (output.prediction_id, output.prediction) == (11, prediction)


async def test_quantiles_are_read_one_query_parameter_each(ctx: FakeContext, chap: ChapServer) -> None:
    entries = [{"period": "202502", "orgUnit": "OU1", "quantile": 0.5, "value": 3.0}]
    chap.on("GET", "/v1/analytics/prediction-entry/11", body=entries)
    config = {"connection": CONNECTION, "prediction_id": 11, "quantiles": [0.25, 0.5, 0.75]}
    output = await call_block(ChapPredictionReadOperator(), config, ctx)
    assert isinstance(output, ChapPredictionReadOutput)
    assert (output.entries, output.count) == (entries, 1)
    sent = chap.sent("GET", "/v1/analytics/prediction-entry/11")[0]
    assert sent.url.params.get_list("quantiles") == ["0.25", "0.5", "0.75"]


async def test_the_default_quantiles_are_the_median_and_its_band(ctx: FakeContext, chap: ChapServer) -> None:
    chap.on("GET", "/v1/analytics/prediction-entry/11", body=[])
    await call_block(ChapPredictionReadOperator(), {"connection": CONNECTION, "prediction_id": 11}, ctx)
    sent = chap.sent("GET", "/v1/analytics/prediction-entry/11")[0]
    assert sent.url.params.get_list("quantiles") == ["0.1", "0.5", "0.9"]
