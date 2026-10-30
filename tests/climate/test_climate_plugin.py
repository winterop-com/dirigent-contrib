"""Tests for the climate pack's plugin wiring."""

from typing import Any, cast

from pluginkit import PluginManager

from dirigent_common import API_VERSION, HumaneJsonSchema
from dirigent_contrib.climate import ClimatePlugin, plugin
from dirigent_plugin import ENTRY_POINT_GROUP, PROJECT_NAME, contribute, markers
from dirigent_testing import assert_contribution_conforms

CLIMATE_BLOCKS = [
    "climate.aggregate",
    "climate.datasets.list",
    "climate.export",
    "climate.ingest",
    "climate.job.result",
    "climate.job.run",
    "climate.sync",
]

#: The blocks that queue a job on the service and follow it, and so are probed.
PROBED = {"climate.export", "climate.ingest", "climate.job.run", "climate.sync"}


def test_the_pack_contributes_the_climate_blocks() -> None:
    contribution = ClimatePlugin().contribute()
    assert contribution.api_version == API_VERSION
    assert sorted(contribution.block_ids()) == CLIMATE_BLOCKS
    assert [connection.id for connection in contribution.connection_kinds] == ["climate"]
    assert contribution.sensors == []
    assert [catalogue.prefix for catalogue in contribution.labels] == ["climate"]


def test_the_contribution_is_well_formed() -> None:
    assert assert_contribution_conforms(ClimatePlugin().contribute()) == []


def test_every_climate_block_shelves_under_the_climate_group() -> None:
    contribution = ClimatePlugin().contribute()
    assert {operator.spec.group for operator in contribution.operators} == {"climate"}


def test_the_job_blocks_poll_and_the_reads_are_idempotent() -> None:
    contribution = ClimatePlugin().contribute()
    for operator in contribution.operators:
        if operator.spec.id in PROBED:
            assert operator.spec.default_poll is not None, operator.spec.id
            assert not operator.spec.idempotent, operator.spec.id
        else:
            assert operator.spec.idempotent, operator.spec.id


def test_every_climate_block_marks_its_connection_field_as_a_reference() -> None:
    for operator in ClimatePlugin().contribute().operators:
        schema = operator.config_model.model_json_schema(mode="serialization", schema_generator=HumaneJsonSchema)
        field = cast("dict[str, Any]", schema["properties"]["connection"])
        ref = cast("str", field["$ref"]).removeprefix("#/$defs/")
        assert schema["$defs"][ref]["x-dirigent-ref"] == "connection", operator.spec.id
        assert schema["required"][0] == "connection" or "connection" in schema["required"], operator.spec.id


def test_no_climate_block_runs_code_on_the_worker() -> None:
    assert [op.spec.id for op in ClimatePlugin().contribute().operators if op.spec.local_execution] == []


def test_the_pack_registers_through_a_plugin_manager() -> None:
    manager = PluginManager(PROJECT_NAME)
    manager.add_extension_points(markers)
    manager.register(plugin, name="climate")
    collected = [sorted(contribution.block_ids()) for contribution in manager.caller(contribute)()]
    assert collected == [CLIMATE_BLOCKS]


def test_the_pack_is_discovered_through_the_entry_point_group() -> None:
    manager = PluginManager(PROJECT_NAME)
    manager.add_extension_points(markers)
    assert manager.load_entrypoints(ENTRY_POINT_GROUP) >= 1
    assert manager.get_plugin("climate") is not None
