"""The block and connection pages are kept by hand, so they are held to what the catalog publishes.

Every field a block or the connection publishes says what it is, and what it says is on the
page in the spelling a table cell renders it in, so a field added or a docstring rewritten
fails here rather than drifting out of the page quietly.
"""

from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import BaseModel

from dirigent_common import HumaneJsonSchema, as_markdown
from dirigent_contrib.climate import ClimatePlugin
from dirigent_contrib.climate.connection import ClimateConnectionConfig

DOCS = Path(__file__).resolve().parents[2] / "docs" / "climate"

CONTRIBUTION = ClimatePlugin().contribute()


def _fields(model: type[BaseModel]) -> dict[str, Any]:
    schema = model.model_json_schema(mode="serialization", schema_generator=HumaneJsonSchema)
    return cast("dict[str, Any]", schema.get("properties", {}))


def _published() -> list[Any]:
    cases: list[Any] = []
    for block in CONTRIBUTION.operators:
        for table, model in (("config", block.config_model), ("output", block.output_model)):
            for name, field in _fields(model).items():
                cases.append(pytest.param("blocks.md", field.get("description"), id=f"{block.spec.id}-{table}-{name}"))
    for name, field in _fields(ClimateConnectionConfig).items():
        cases.append(pytest.param("connection.md", field.get("description"), id=f"connection-{name}"))
    return cases


PUBLISHED = _published()


def _in_a_table_cell(description: str) -> str:
    paragraph = description.strip().split("\n\n", 1)[0]
    return as_markdown(" ".join(paragraph.split())).replace("|", "\\|")


def test_there_are_published_fields_to_check() -> None:
    assert len(PUBLISHED) > 40


@pytest.mark.parametrize(("page", "description"), PUBLISHED)
def test_every_published_field_is_described_on_its_page(page: str, description: str | None) -> None:
    assert description, "the field has no docstring"
    assert _in_a_table_cell(description) in (DOCS / page).read_text(), "the page does not carry what the docstring says"


def test_every_block_has_a_section_on_the_blocks_page() -> None:
    page = (DOCS / "blocks.md").read_text()
    for block in CONTRIBUTION.operators:
        assert f"## `{block.spec.id}`" in page, block.spec.id
