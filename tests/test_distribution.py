"""One distribution carries every pack, and the host finds each through its own entry point."""

from importlib.metadata import distribution

from pluginkit import PluginManager

from dirigent_plugin import ENTRY_POINT_GROUP, PROJECT_NAME, Contribution, contribute, markers


def test_the_distribution_declares_one_entry_point_per_pack() -> None:
    entry_points = distribution("dirigent-contrib").entry_points.select(group=ENTRY_POINT_GROUP)
    assert {entry_point.name: entry_point.value for entry_point in entry_points} == {
        "chap": "dirigent_contrib.chap:plugin",
        "climate": "dirigent_contrib.climate:plugin",
    }


def test_each_pack_contributes_under_its_own_entry_point_and_its_own_prefix() -> None:
    manager = PluginManager(PROJECT_NAME)
    manager.add_extension_points(markers)
    manager.load_entrypoints(ENTRY_POINT_GROUP)
    collected: dict[str, Contribution] = dict(manager.caller(contribute).collect_with_plugins())
    for pack in ("chap", "climate"):
        assert {block.split(".")[0] for block in collected[pack].block_ids()} == {pack}
        assert [connection.id for connection in collected[pack].connection_kinds] == [pack]
