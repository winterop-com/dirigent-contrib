"""Tests for the Chap pack's plugin wiring."""

from typing import Any, cast

from pluginkit import PluginManager

from dirigent_chap import ChapPlugin, plugin
from dirigent_common import API_VERSION, HumaneJsonSchema
from dirigent_plugin import ENTRY_POINT_GROUP, PROJECT_NAME, contribute, markers
from dirigent_testing import assert_contribution_conforms

CHAP_BLOCKS = [
    "chap.backtest.run",
    "chap.dataset.import",
    "chap.models.list",
    "chap.prediction.read",
    "chap.prediction.run",
    "chap.thresholds",
]

#: The blocks that submit a Chap job and follow it, and so are probed.
PROBED = {"chap.backtest.run", "chap.dataset.import", "chap.prediction.run"}


def test_the_pack_contributes_the_chap_blocks() -> None:
    contribution = ChapPlugin().contribute()
    assert contribution.api_version == API_VERSION
    assert sorted(contribution.block_ids()) == CHAP_BLOCKS
    assert [connection.id for connection in contribution.connection_kinds] == ["chap"]
    assert contribution.sensors == []
    assert [catalogue.prefix for catalogue in contribution.labels] == ["chap"]


def test_the_contribution_is_well_formed() -> None:
    assert assert_contribution_conforms(ChapPlugin().contribute()) == []


def test_every_chap_block_shelves_under_the_chap_group() -> None:
    contribution = ChapPlugin().contribute()
    assert {operator.spec.group for operator in contribution.operators} == {"chap"}


def test_the_job_blocks_poll_and_the_reads_are_idempotent() -> None:
    contribution = ChapPlugin().contribute()
    for operator in contribution.operators:
        if operator.spec.id in PROBED:
            assert operator.spec.default_poll is not None, operator.spec.id
            assert not operator.spec.idempotent, operator.spec.id
        else:
            assert operator.spec.idempotent, operator.spec.id


def test_every_chap_block_marks_its_connection_field_as_a_reference() -> None:
    for operator in ChapPlugin().contribute().operators:
        schema = operator.config_model.model_json_schema(mode="serialization", schema_generator=HumaneJsonSchema)
        field = cast("dict[str, Any]", schema["properties"]["connection"])
        ref = cast("str", field["$ref"]).removeprefix("#/$defs/")
        assert schema["$defs"][ref]["x-dirigent-ref"] == "connection", operator.spec.id
        assert schema["required"][0] == "connection" or "connection" in schema["required"], operator.spec.id


def test_no_chap_block_runs_code_on_the_worker() -> None:
    assert [op.spec.id for op in ChapPlugin().contribute().operators if op.spec.local_execution] == []


def test_the_pack_registers_through_a_plugin_manager() -> None:
    manager = PluginManager(PROJECT_NAME)
    manager.add_extension_points(markers)
    manager.register(plugin, name="chap")
    collected = [sorted(contribution.block_ids()) for contribution in manager.caller(contribute)()]
    assert collected == [CHAP_BLOCKS]


def test_the_pack_is_discovered_through_the_entry_point_group() -> None:
    manager = PluginManager(PROJECT_NAME)
    manager.add_extension_points(markers)
    assert manager.load_entrypoints(ENTRY_POINT_GROUP) >= 1
    assert manager.get_plugin("chap") is not None
