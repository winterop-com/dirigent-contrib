"""``climate.datasets.list`` and ``climate.aggregate``: the reads, and what a payload becomes."""

import json
from typing import Any

import pytest
from pydantic import ValidationError

from dirigent_contrib.climate.aggregate import ClimateAggregateOperator, ClimateAggregateOutput
from dirigent_contrib.climate.datasets import ClimateDatasetsListOperator, ClimateDatasetsListOutput
from dirigent_contrib.climate.messages import GRAPH_MISSING, GRAPH_ONE_OF, GRAPH_STRAY
from dirigent_plugin import BlockFailure, ErrorClass
from dirigent_testing import FakeContext, call_block
from tests.climate.climateserver import CONNECTION, ClimateServer

GEOMETRIES: dict[str, Any] = {
    "type": "FeatureCollection",
    "features": [{"type": "Feature", "id": "OU1", "properties": {}, "geometry": None}],
}

VALUE_SET = {"dataValues": [{"dataElement": "DE1", "period": "202501", "orgUnit": "OU1", "value": "12.5"}]}


def _config(**overrides: Any) -> dict[str, Any]:
    return {
        "connection": CONNECTION,
        "workflow": "aggregate_to_dhis2_json",
        "dataset_id": "chirps3_precipitation_daily",
        "start": "2025-01-01",
        "end": "2025-01-31",
        "geometries": GEOMETRIES,
        "export": "rainfall-monthly",
        **overrides,
    }


async def test_the_datasets_are_listed_as_json(ctx: FakeContext, ocs: ClimateServer) -> None:
    items = [{"dataset_id": "chirps3_precipitation_daily", "period_type": "daily"}]
    ocs.on("GET", "/datasets", body={"kind": "DatasetList", "items": items})
    output = await call_block(ClimateDatasetsListOperator(), {"connection": CONNECTION}, ctx)
    assert isinstance(output, ClimateDatasetsListOutput)
    assert (output.datasets, output.count) == (items, 1)
    sent = ocs.sent("GET", "/datasets")[0]
    assert sent.url.params["f"] == "json"
    assert sent.headers["accept"] == "application/json"
    assert sent.headers["x-proxy-key"] == "k"


async def test_a_workflow_runs_as_one_node_and_a_small_answer_is_inlined(ctx: FakeContext, ocs: ClimateServer) -> None:
    ocs.on("POST", "/result", body=VALUE_SET)
    output = await call_block(ClimateAggregateOperator(), _config(method="sum"), ctx)
    assert isinstance(output, ClimateAggregateOutput)
    assert output.value == VALUE_SET
    assert output.content_type == "application/json"
    assert output.workflow == "aggregate_to_dhis2_json"
    written = ctx.storage.path_for(output.uri).read_bytes()
    assert json.loads(written) == VALUE_SET
    assert output.size_bytes == len(written)
    assert ocs.body("POST", "/result") == {
        "process": {
            "process_graph": {
                "agg": {
                    "process_id": "aggregate_to_dhis2_json",
                    "arguments": {
                        "dataset_id": "chirps3_precipitation_daily",
                        "temporal_extent": ["2025-01-01", "2025-01-31"],
                        "geometries": GEOMETRIES,
                        "method": "sum",
                        "export": "rainfall-monthly",
                    },
                    "result": True,
                }
            }
        }
    }


async def test_a_chap_csv_is_inlined_as_text(ctx: FakeContext, ocs: ClimateServer) -> None:
    csv = "time_period,location,precip\n2025-01,OU1,12.5\n"
    ocs.on("POST", "/result", text=csv, headers={"content-type": "text/csv; charset=utf-8"})
    config = _config(workflow="aggregate_to_chap_csv", export=None, period_type="month")
    output = await call_block(ClimateAggregateOperator(), config, ctx)
    assert isinstance(output, ClimateAggregateOutput)
    assert (output.text, output.value, output.content_type) == (csv, None, "text/csv")
    assert output.uri.endswith(".csv")
    assert ocs.body("POST", "/result")["process"]["process_graph"]["agg"]["arguments"]["period_type"] == "month"


async def test_a_payload_past_the_inline_limit_is_left_in_storage(ctx: FakeContext, ocs: ClimateServer) -> None:
    ctx.inline_capture = 16
    ocs.on("POST", "/result", body=VALUE_SET)
    output = await call_block(ClimateAggregateOperator(), _config(), ctx)
    assert isinstance(output, ClimateAggregateOutput)
    assert output.value is None
    assert json.loads(ctx.storage.path_for(output.uri).read_bytes()) == VALUE_SET


async def test_a_whole_process_graph_is_sent_as_written(ctx: FakeContext, ocs: ClimateServer) -> None:
    graph = {"load": {"process_id": "load_collection", "arguments": {"id": "x"}, "result": True}}
    ocs.on("POST", "/result", body={})
    await call_block(ClimateAggregateOperator(), {"connection": CONNECTION, "process_graph": graph}, ctx)
    assert ocs.body("POST", "/result") == {"process": {"process_graph": graph}}


async def test_a_refusal_is_classified_and_quoted(ctx: FakeContext, ocs: ClimateServer) -> None:
    ocs.on("POST", "/result", status=400, body={"detail": "Unknown dataset"})
    with pytest.raises(BlockFailure) as raised:
        await call_block(ClimateAggregateOperator(), _config(), ctx)
    assert raised.value.error_class is ErrorClass.REJECTED
    assert "Unknown dataset" in str(raised.value)


def test_a_step_names_exactly_one_graph() -> None:
    with pytest.raises(ValidationError, match=GRAPH_ONE_OF.render()):
        ClimateAggregateOperator.config_model.model_validate({"connection": CONNECTION})
    with pytest.raises(ValidationError, match=GRAPH_ONE_OF.render()):
        ClimateAggregateOperator.config_model.model_validate(_config(process_graph={}))


def test_a_workflow_needs_its_arguments() -> None:
    with pytest.raises(ValidationError, match=GRAPH_MISSING.render(workflow="aggregate_to_dhis2_json", field="export")):
        ClimateAggregateOperator.config_model.model_validate(_config(export=None))
    with pytest.raises(ValidationError, match="needs geometries"):
        ClimateAggregateOperator.config_model.model_validate(_config(geometries=None))


def test_an_argument_of_another_workflow_is_refused() -> None:
    stray = GRAPH_STRAY.render(field="export", owner="aggregate_to_dhis2_json", workflow="aggregate_by_features")
    with pytest.raises(ValidationError, match=stray):
        ClimateAggregateOperator.config_model.model_validate(_config(workflow="aggregate_by_features"))
