"""The pack's catalogue: every refusal it can make is minted under the ``chap`` prefix."""

from pathlib import Path

import pytest

import dirigent_contrib.chap
from dirigent_common import Message
from dirigent_contrib.chap import messages
from dirigent_contrib.chap.messages import CHAP
from dirigent_testing import check_pack_messages

MESSAGES = [pytest.param(message, id=name) for name, message in CHAP.messages.items()]

#: The block reference, which publishes the codes a reader selects a refusal by.
PAGE = Path(__file__).resolve().parents[2] / "docs" / "chap" / "blocks.md"


def test_the_catalogue_holds_every_refusal_the_pack_makes() -> None:
    assert CHAP.prefix == "chap"
    assert len(CHAP.messages) > 10


@pytest.mark.parametrize("message", MESSAGES)
def test_a_message_is_coded_under_the_pack_prefix(message: Message) -> None:
    assert message.code.startswith("chap.")


def test_every_message_is_exported_under_its_own_constant() -> None:
    held = {message.code for message in vars(messages).values() if isinstance(message, Message)}
    assert held == {message.code for message in CHAP.messages.values()}


@pytest.mark.parametrize("message", MESSAGES)
def test_a_message_renders_every_param_its_template_names(message: Message) -> None:
    rendered = message.render(**{field: field for field in message.fields})
    assert "{" not in rendered
    for field in message.fields:
        assert field in rendered


@pytest.mark.parametrize("message", MESSAGES)
def test_the_page_publishes_the_message_under_its_code(message: Message) -> None:
    assert f"| `{message.code}` | `{message.text}` |" in PAGE.read_text()


def test_every_refusal_the_pack_makes_carries_a_code() -> None:
    assert check_pack_messages(Path(dirigent_contrib.chap.__file__).parent) == []
