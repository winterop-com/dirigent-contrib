"""Every document on every shelf opens its description with a sentence a list row can show."""

import re
from pathlib import Path
from typing import Final

import pytest
import yaml

#: Every document the package's packs ship.
DOCUMENTS: Final = sorted((Path(__file__).parents[1] / "src" / "dirigent_contrib").glob("*/shelves/**/*.yaml"))

#: The most a description's first sentence may run to, which is what a list row has room for.
FIRST_SENTENCE_AT_MOST: Final = 80


def test_there_are_documents_to_check() -> None:
    assert DOCUMENTS


@pytest.mark.parametrize("path", DOCUMENTS, ids=[path.stem for path in DOCUMENTS])
def test_a_description_opens_with_a_short_plain_sentence(path: Path) -> None:
    description = yaml.safe_load(path.read_text()).get("description")
    assert description, "the document says nothing about what it does"
    paragraph = " ".join(str(description).strip().split("\n\n", 1)[0].split())
    sentence = re.split(r"(?<=[.!?])\s", paragraph, maxsplit=1)[0]
    assert len(sentence) <= FIRST_SENTENCE_AT_MOST, sentence
    assert "`" not in sentence, sentence
