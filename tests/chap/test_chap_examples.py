"""The pack's example shelves must conform to its own contribution, checked by the kit.

``check_pack_examples`` is a single-pack check, so a document that composes this pack with
another is checked with the steps no installed contribution provides removed: the engine's
own ``storage.read`` and ``transform.jq``, and the ``dhis2.message`` of ``dirigent-dhis2``,
which is not installed beside this repository's tests. The ``chap-climate`` shelf is checked
against this pack and the climate pack together, since its documents are built from both.
"""

import re
from pathlib import Path
from typing import Any, Final, cast

import pytest
import yaml

from dirigent_common import HumaneJsonSchema
from dirigent_contrib.chap import ChapPlugin
from dirigent_contrib.climate import ClimatePlugin
from dirigent_plugin import AnyOperator, AnySensor, Contribution, merge_contributions
from dirigent_testing import check_pack_examples

SHELVES = Path(str(ChapPlugin().examples()[0]))

CONTRIBUTION = merge_contributions([ChapPlugin().contribute(), ClimatePlugin().contribute()])

#: The output fields of the blocks from elsewhere the documents read.
ENGINE_OUTPUTS: Final = {
    "storage.read": {"content_type", "text", "value", "bytes_read"},
    "transform.jq": {"value"},
}

#: A reference to an earlier step's output field.
STEP_OUTPUT: Final = re.compile(r"\$\{steps\.([a-z_]+)\.output\.([a-z_]+)")

DOCUMENTS = sorted(SHELVES.rglob("*.yaml"))


def _load(path: Path) -> dict[str, Any]:
    return cast("dict[str, Any]", yaml.safe_load(path.read_text()))


def _only_known_steps(document: dict[str, Any], contribution: Contribution) -> dict[str, Any]:
    known = set(contribution.block_ids())
    steps = cast("dict[str, Any]", document.get("steps", {}))
    return {**document, "steps": {name: step for name, step in steps.items() if step.get("block") in known}}


def test_the_shelves_the_hook_answers_with_are_the_ones_in_the_package() -> None:
    assert SHELVES.is_dir() and SHELVES.parent.name == "chap"
    assert {path.parent.name for path in DOCUMENTS} == {"chap", "chap-climate", "chap-dhis2"}


def test_every_example_conforms_to_the_catalog(tmp_path: Path) -> None:
    for path in DOCUMENTS:
        (tmp_path / path.name).write_text(yaml.safe_dump(_only_known_steps(_load(path), CONTRIBUTION)))
    issues = check_pack_examples(CONTRIBUTION, tmp_path)
    assert issues == [], "\n".join(issues)


@pytest.mark.parametrize("path", DOCUMENTS, ids=[path.stem for path in DOCUMENTS])
def test_every_block_a_document_names_is_required(path: Path) -> None:
    document = _load(path)
    named = {step["block"] for step in document["steps"].values()}
    assert named <= set(document["requires"]["blocks"])


@pytest.mark.parametrize("path", DOCUMENTS, ids=[path.stem for path in DOCUMENTS])
def test_every_carried_connection_has_a_name_and_a_description(path: Path) -> None:
    for code, connection in cast("dict[str, Any]", _load(path).get("connections", {})).items():
        assert connection.get("name") and connection.get("description"), code


@pytest.mark.parametrize("path", DOCUMENTS, ids=[path.stem for path in DOCUMENTS])
def test_every_output_a_step_reads_is_one_the_earlier_step_publishes(path: Path) -> None:
    contributed: list[AnyOperator | AnySensor] = [*CONTRIBUTION.operators, *CONTRIBUTION.sensors]
    blocks = {block.spec.id: block for block in contributed}
    steps = cast("dict[str, Any]", _load(path)["steps"])
    for name, step in steps.items():
        for source, field in STEP_OUTPUT.findall(yaml.safe_dump(step.get("config", {}))):
            assert source in step.get("depends_on", []), f"{name} reads {source} without depending on it"
            block_id = steps[source]["block"]
            if block_id in blocks:
                schema = blocks[block_id].output_model.model_json_schema(schema_generator=HumaneJsonSchema)
                published = set(schema["properties"])
            else:
                published = ENGINE_OUTPUTS[block_id]
            assert field in published, f"{name} reads {source}.{field}, which {block_id} does not publish"


def test_a_starter_is_a_flow_that_says_what_it_is_for() -> None:
    starters = [path for path in DOCUMENTS if "starter" in _load(path).get("tags", [])]
    assert len(starters) >= 2
    for path in starters:
        document = _load(path)
        assert len(document["steps"]) >= 2 and document["description"], path.name


def test_every_document_opens_with_a_header_that_teaches() -> None:
    for path in DOCUMENTS:
        header = [line for line in path.read_text().splitlines() if line.startswith("#")]
        assert len(header) >= 5, f"{path.name} has no header worth reading"
