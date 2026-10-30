"""``chap.models.list`` and ``chap.thresholds``: the two blocks Chap answers at once."""

from typing import Any

import pytest
from pydantic import ValidationError

from dirigent_contrib.chap.configured_models import ChapModelsListOperator, ChapModelsListOutput
from dirigent_contrib.chap.thresholds import ChapThresholdsOperator, ChapThresholdsOutput
from dirigent_plugin import BlockFailure, ErrorClass
from dirigent_testing import FakeContext, call_block
from tests.chap.chapserver import CONNECTION, ChapServer

THRESHOLDS = "/v1/analytics/thresholds"


async def test_the_configured_models_are_listed_as_chap_describes_them(ctx: FakeContext, chap: ChapServer) -> None:
    models: list[dict[str, Any]] = [
        {"id": 1, "name": "naive_model", "covariates": [], "target": {"name": "disease_cases"}}
    ]
    chap.on("GET", "/v1/crud/configured-models", body=models)
    output = await call_block(ChapModelsListOperator(), {"connection": CONNECTION}, ctx)
    assert isinstance(output, ChapModelsListOutput)
    assert (output.models, output.count) == (models, 1)


async def test_a_refused_token_is_a_refusal(ctx: FakeContext, chap: ChapServer) -> None:
    chap.on("GET", "/v1/crud/configured-models", status=401, body={"detail": "Missing or invalid API token"})
    with pytest.raises(BlockFailure) as raised:
        await call_block(ChapModelsListOperator(), {"connection": CONNECTION}, ctx)
    assert raised.value.error_class is ErrorClass.REJECTED


async def test_thresholds_send_the_strategy_as_chap_spells_it(ctx: FakeContext, chap: ChapServer) -> None:
    answer = {
        "params": {"type": "percentile", "quantile": [0.25, 0.75], "baselineYears": 5},
        "lines": [0.25, 0.75],
        "entries": [{"period": "2024-01", "location": "OU1", "values": [1.0, None]}],
    }
    chap.on("POST", THRESHOLDS, body=answer)
    config = {
        "connection": CONNECTION,
        "dataset_id": 42,
        "period_ids": ["2024-01"],
        "params": {"type": "percentile", "quantile": [0.25, 0.75]},
    }
    output = await call_block(ChapThresholdsOperator(), config, ctx)
    assert isinstance(output, ChapThresholdsOutput)
    assert (output.params, output.lines, output.entries) == (answer["params"], answer["lines"], answer["entries"])
    assert chap.body("POST", THRESHOLDS) == {
        "datasetId": 42,
        "periodIds": ["2024-01"],
        "params": {"type": "percentile", "quantile": [0.25, 0.75]},
    }


async def test_thresholds_restricted_to_locations_send_them(ctx: FakeContext, chap: ChapServer) -> None:
    chap.on("POST", THRESHOLDS, body={"params": {}, "lines": [2.0], "entries": []})
    config = {
        "connection": CONNECTION,
        "dataset_id": 42,
        "period_ids": ["2024-01"],
        "locations": ["OU1"],
        "params": {"type": "seasonal"},
    }
    await call_block(ChapThresholdsOperator(), config, ctx)
    assert chap.body("POST", THRESHOLDS)["locations"] == ["OU1"]


def test_thresholds_need_periods_and_a_strategy() -> None:
    with pytest.raises(ValidationError):
        ChapThresholdsOperator.config_model.model_validate(
            {"connection": CONNECTION, "dataset_id": 42, "period_ids": []}
        )
