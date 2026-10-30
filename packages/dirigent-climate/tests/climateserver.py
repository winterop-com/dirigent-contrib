"""A scripted open climate service: each route answers what a test wrote for it, and every request is kept."""

import json
from collections.abc import Mapping
from typing import Any, Final

import httpx2
from pydantic import BaseModel

from dirigent_plugin import Operator, ProbeResult, ProbeStatus, RemoteHandle, StepContext
from dirigent_testing import FakeContext

#: The code the tests' climate connection is installed under.
CONNECTION: Final = "climate-test"

#: Where the scripted server answers.
BASE_URL: Final = "http://climate.test"


class ClimateServer:
    """Answers each route from a queue the test fills; the last answer repeats."""

    def __init__(self) -> None:
        """Start with no routes and no requests."""
        self.routes: dict[tuple[str, str], list[httpx2.Response]] = {}
        self.requests: list[httpx2.Request] = []

    def on(
        self,
        method: str,
        path: str,
        *,
        status: int = 200,
        body: Any = None,
        text: str | None = None,
        content: bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> "ClimateServer":
        """Queue one answer for a route."""
        if content is not None:
            response = httpx2.Response(status, content=content, headers=headers)
        elif text is not None:
            response = httpx2.Response(status, text=text, headers=headers)
        else:
            response = httpx2.Response(status, json=body, headers=headers)
        self.routes.setdefault((method, path), []).append(response)
        return self

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        """Answer a request from its route's queue, or 404 when no route was written."""
        self.requests.append(request)
        queue = self.routes.get((request.method, request.url.path))
        if not queue:
            return httpx2.Response(404, json={"detail": f"no route for {request.method} {request.url.path}"})
        return queue.pop(0) if len(queue) > 1 else queue[0]

    def sent(self, method: str, path: str) -> list[httpx2.Request]:
        """Every request made to one route, in order."""
        return [request for request in self.requests if request.method == method and request.url.path == path]

    def body(self, method: str, path: str) -> Any:
        """The JSON body of the last request made to a route."""
        return json.loads(self.sent(method, path)[-1].content)


async def settle(
    block: Operator[Any, Any], handle: RemoteHandle, config: BaseModel, ctx: FakeContext
) -> tuple[list[ProbeResult], BaseModel | None]:
    """Probe a handle until it settles, then fetch when it succeeded; the probes are returned too."""
    context: StepContext = ctx.as_context()
    probes: list[ProbeResult] = []
    for _ in range(10):
        probe = await block.probe(handle, config, context)
        probes.append(probe)
        if probe.status is not ProbeStatus.RUNNING:
            break
    if probes[-1].status is ProbeStatus.SUCCEEDED:
        return probes, await block.fetch(handle, config, context)
    return probes, None
