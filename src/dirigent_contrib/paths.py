"""What a value must be to name one thing in a request's path, in every pack."""

import re
from typing import Final
from urllib.parse import quote

#: One id, as a config field publishes it: a letter or digit, then letters, digits, ``.``, ``_`` and ``-``.
PLAIN_ID_PATTERN: Final = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$"

_PLAIN_ID: Final = re.compile(PLAIN_ID_PATTERN)


def is_plain_id(value: str) -> bool:
    """Whether a value is one id, and so stays one segment of a request's path."""
    return _PLAIN_ID.fullmatch(value) is not None


def segment(value: str) -> str:
    """Encode a value as one segment of a request's path."""
    return quote(value, safe="")
