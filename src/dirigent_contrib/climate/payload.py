"""A payload the service streams back, written to the run's storage and inlined when it is small.

Every payload lands in storage under the run's scratch, so a step that follows can read it
whatever its size. One no larger than the instance lets a block inline is also handed on
decoded, in the two fields ``storage.read`` decodes into: ``value`` for JSON, ``text`` for text.
"""

import contextlib
import json
from typing import Final

import httpx2
from pydantic import JsonValue

from dirigent_common import BlockModel
from dirigent_contrib.climate.messages import NOT_JSON, RESPONSE_TOO_LARGE
from dirigent_contrib.climate.web import refuse
from dirigent_contrib.limits import pieces, read_error
from dirigent_plugin import BlockFailure, ErrorClass, StepContext

#: The extension a captured payload is named with, by the media type it arrived as.
EXTENSIONS: Final = {
    "application/json": ".json",
    "application/geo+json": ".geojson",
    "text/csv": ".csv",
    "text/plain": ".txt",
}


class Payload(BlockModel):
    """Where a payload was written, what it is, and the payload itself when it is small."""

    uri: str
    """Where the payload was written, under the run's scratch; `storage.read` reads it back."""

    content_type: str
    """The media type the service sent it as."""

    size_bytes: int
    """How large it is."""

    value: JsonValue = None
    """The payload parsed as JSON, set when it is JSON and no larger than the instance lets a block
    inline; `uri` holds it either way."""

    text: str | None = None
    """The payload as text, set when it is text, such as a CSV, and no larger than the instance lets a
    block inline; `uri` holds it either way."""


def media_type(response: httpx2.Response) -> str:
    """The media type a response declares, without its parameters."""
    return response.headers.get("content-type", "application/octet-stream").split(";", 1)[0].strip().lower()


def _textual(kind: str) -> bool:
    """Whether a media type is one a payload is decoded as text for."""
    return kind.startswith("text/") or kind in ("application/csv",)


def _jsonish(kind: str) -> bool:
    """Whether a media type is JSON, under any of the names the service may give it."""
    return kind == "application/json" or kind.endswith("+json")


async def capture(ctx: StepContext, response: httpx2.Response, name: str, where: str, max_response: int) -> Payload:
    """Stream a response into the run's storage, keeping it in memory only while it is small enough to inline.

    An answer past ``max_response`` is refused with no more than that much of it written.
    """
    if response.is_error:
        raise refuse(await read_error(response), where)
    kind = media_type(response)
    held = bytearray()
    size = 0
    limit = ctx.inline_capture
    async with ctx.capture(f"{name}{EXTENSIONS.get(kind, '.bin')}", content_type=kind) as sink:
        async with contextlib.aclosing(pieces(response)) as decoded:
            async for chunk in decoded:
                if size + len(chunk) > max_response:
                    raise BlockFailure(
                        RESPONSE_TOO_LARGE, error_class=ErrorClass.REJECTED, where=where, limit=max_response
                    )
                await sink.write(chunk)
                size += len(chunk)
                if size <= limit:
                    held.extend(chunk)
        uri = sink.uri
    payload = Payload(uri=uri, content_type=kind, size_bytes=size)
    if size > limit:
        return payload
    if _jsonish(kind):
        try:
            payload.value = json.loads(bytes(held))
        except ValueError as error:
            raise BlockFailure(NOT_JSON, error_class=ErrorClass.UNKNOWN, where=where) from error
    elif _textual(kind):
        payload.text = bytes(held).decode(response.encoding or "utf-8", errors="replace")
    return payload
