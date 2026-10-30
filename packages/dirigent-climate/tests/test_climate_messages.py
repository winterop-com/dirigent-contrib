"""The pack's catalogue: every refusal it can make is minted under the ``climate`` prefix."""

from pathlib import Path

import pytest

import dirigent_climate
from dirigent_climate import messages
from dirigent_climate.messages import CLIMATE
from dirigent_common import Message
from dirigent_testing import check_pack_messages

MESSAGES = [pytest.param(message, id=name) for name, message in CLIMATE.messages.items()]

#: The block reference, which publishes the codes a reader selects a refusal by.
PAGE = Path(__file__).resolve().parents[3] / "docs" / "climate" / "blocks.md"


def test_the_catalogue_holds_every_refusal_the_pack_makes() -> None:
    assert CLIMATE.prefix == "climate"
    assert len(CLIMATE.messages) > 10


@pytest.mark.parametrize("message", MESSAGES)
def test_a_message_is_coded_under_the_pack_prefix(message: Message) -> None:
    assert message.code.startswith("climate.")


def test_every_message_is_exported_under_its_own_constant() -> None:
    held = {message.code for message in vars(messages).values() if isinstance(message, Message)}
    assert held == {message.code for message in CLIMATE.messages.values()}


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
    assert check_pack_messages(Path(dirigent_climate.__file__).parent) == []
