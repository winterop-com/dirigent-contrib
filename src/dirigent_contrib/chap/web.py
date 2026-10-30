"""What the Chap blocks share: one call, its refusal classified, and its JSON read back."""

import json
from typing import Any, Final, cast

import httpx2
from pydantic import JsonValue

from dirigent_contrib.chap.messages import ANSWERED, NOT_JSON
from dirigent_plugin import BlockFailure, ErrorClass

#: How much of a refusal's body is quoted back, so a page of HTML does not become the message.
QUOTED: Final = 500


def status_class(status: int) -> ErrorClass:
    """Classify an HTTP status the way retry policy needs it classified.

    A 429 is the one client error that asks to be retried: the server is rate limiting, and
    the same call succeeds once the window has passed.
    """
    if status >= 500 or status == 429:
        return ErrorClass.TRANSIENT
    if 400 <= status < 500:
        return ErrorClass.REJECTED
    return ErrorClass.UNKNOWN


def remote_words(response: httpx2.Response) -> str:
    """Say what Chap said, in its own words: FastAPI's ``detail``, or the body's opening."""
    try:
        body: Any = response.json()
    except ValueError:
        return response.text[:QUOTED] or response.reason_phrase
    detail: object = cast("dict[str, object]", body).get("detail") if isinstance(body, dict) else None
    if isinstance(detail, str):
        return detail[:QUOTED]
    if detail is not None:
        return json.dumps(detail)[:QUOTED]
    return json.dumps(body)[:QUOTED]


def refuse(response: httpx2.Response, where: str) -> BlockFailure:
    """Turn a refusal Chap answered with into a classified failure the engine can act on."""
    status = response.status_code
    return BlockFailure(
        ANSWERED, error_class=status_class(status), where=where, status=status, remote=remote_words(response)
    )


async def call(client: httpx2.AsyncClient, method: str, path: str, **kwargs: Any) -> httpx2.Response:
    """Make one call, and raise the classified refusal when Chap answers with an error.

    A transport failure is left to propagate: the plugin contract classifies it as transient.
    """
    response = await client.request(method, path, **kwargs)
    if response.is_error:
        raise refuse(response, f"{method} {path}")
    return response


def json_of(response: httpx2.Response, where: str) -> JsonValue:
    """Read a body as JSON, refusing one that is not."""
    try:
        parsed: JsonValue = response.json()
    except ValueError as error:
        raise BlockFailure(NOT_JSON, error_class=ErrorClass.UNKNOWN, where=where) from error
    return parsed


async def call_json(client: httpx2.AsyncClient, method: str, path: str, **kwargs: Any) -> JsonValue:
    """Make one call and read its answer as JSON."""
    response = await call(client, method, path, **kwargs)
    return json_of(response, f"{method} {path}")


def mapping(value: JsonValue) -> dict[str, JsonValue]:
    """Read a JSON value as an object, or as an empty one when it is anything else."""
    return value if isinstance(value, dict) else {}
