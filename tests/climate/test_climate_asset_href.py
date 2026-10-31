"""``climate.job.result`` reads an asset's href only under the connection's ``base_url``."""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx2
import pytest
import pytest_asyncio

from dirigent_contrib.climate.batch import ClimateJobResultOperator, ClimateJobResultOutput
from dirigent_contrib.climate.connection import ClimateConnectionConfig, build_client
from dirigent_plugin import BlockFailure, ErrorClass
from dirigent_testing import FakeContext, call_block
from tests.climate.climateserver import CONNECTION

BASE_URL = "https://service.test/ocs"
RESULTS_PATH = "/ocs/jobs/j1/results"
OUTSIDE = "climate.job.asset_outside"

REFUSED = [
    pytest.param("http://other.test/stolen", id="another-host"),
    pytest.param("HTTP://other.test/stolen", id="another-host-uppercase-scheme"),
    pytest.param("https://service.test.other.test/ocs/x", id="lookalike-host"),
    pytest.param("https://service.test:8443/ocs/x", id="another-port"),
    pytest.param("http://service.test/ocs/x", id="plain-http-under-https"),
    pytest.param("https://user:pw@service.test/ocs/x", id="userinfo"),
    pytest.param("https://service.test/admin/secret", id="same-origin-outside-the-prefix"),
    pytest.param("https://service.test/ocs-admin/secret", id="prefix-lookalike"),
    pytest.param("https://service.test/", id="same-origin-root"),
    pytest.param("https://service.test/ocs/../admin", id="same-origin-climbing"),
    pytest.param("../admin/secret", id="relative-parent"),
    pytest.param("../../../admin/secret", id="relative-past-the-root"),
    pytest.param("/../admin/secret", id="rooted-parent"),
    pytest.param("jobs/../../admin/secret", id="inner-parent"),
    pytest.param("../x?y=1#f", id="parent-with-query"),
    pytest.param("%2e%2e/admin", id="encoded-parent"),
    pytest.param("..%2fadmin", id="encoded-slash"),
    pytest.param("%252e%252e/admin", id="double-encoded-parent"),
    pytest.param("..\\admin", id="backslash-parent"),
    pytest.param("..%5cadmin", id="encoded-backslash-parent"),
    pytest.param("..;/admin", id="parent-with-a-parameter"),
    pytest.param("..;x=1/admin", id="parent-with-a-named-parameter"),
    pytest.param("a\nb", id="not-a-url"),
]

READ = [
    pytest.param("jobs/j1/results/rain.json", "/ocs/jobs/j1/results/rain.json", id="relative"),
    pytest.param("/jobs/j1/results/rain.json", "/ocs/jobs/j1/results/rain.json", id="rooted"),
    pytest.param("./rain.json", "/ocs/rain.json", id="dot-segment"),
    pytest.param("a/../rain.json", "/ocs/rain.json", id="parent-staying-under-the-prefix"),
    pytest.param("?x=1", "/ocs/", id="query-only"),
    pytest.param("rain.json?u=http://other.test/", "/ocs/rain.json", id="a-url-in-the-query"),
    pytest.param("rain.json?up=../..", "/ocs/rain.json", id="parent-segments-in-the-query"),
    pytest.param("https://service.test/ocs/rain.json", "/ocs/rain.json", id="same-origin-under-the-prefix"),
    pytest.param("https://service.test:443/ocs/rain.json", "/ocs/rain.json", id="the-default-port-written-out"),
    pytest.param("https://SERVICE.test/ocs/rain.json", "/ocs/rain.json", id="uppercase-host"),
]


def _serve(ctx: FakeContext, monkeypatch: pytest.MonkeyPatch, href: str) -> list[httpx2.Request]:
    """Answer the results read with one asset's href and everything else with a small JSON answer."""
    sent: list[httpx2.Request] = []

    def answer(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        if request.url.path == RESULTS_PATH:
            return httpx2.Response(200, json={"assets": {"result": {"href": href}}})
        return httpx2.Response(200, json={"read": True})

    def http(ref: str) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(base_url=BASE_URL, transport=httpx2.MockTransport(answer))

    ctx.connections[CONNECTION] = ClimateConnectionConfig(base_url=BASE_URL, headers={"X-Proxy-Key": "dummy"})
    monkeypatch.setattr(ctx, "http", http)
    return sent


@pytest.mark.parametrize("href", REFUSED)
async def test_an_href_off_the_base_url_is_refused_before_it_is_sent(
    href: str, ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent = _serve(ctx, monkeypatch, href)
    with pytest.raises(BlockFailure) as refused:
        await call_block(ClimateJobResultOperator(), {"connection": CONNECTION, "job_id": "j1"}, ctx)
    assert refused.value.code == OUTSIDE
    assert refused.value.error_class is ErrorClass.REJECTED
    assert [request.url.path for request in sent] == [RESULTS_PATH]
    assert href not in str(refused.value)


@pytest.mark.parametrize(("href", "path"), READ)
async def test_an_href_under_the_base_url_is_read(
    href: str, path: str, ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent = _serve(ctx, monkeypatch, href)
    output = await call_block(ClimateJobResultOperator(), {"connection": CONNECTION, "job_id": "j1"}, ctx)
    assert isinstance(output, ClimateJobResultOutput)
    assert output.href == href
    assert [request.url.path for request in sent] == [RESULTS_PATH, path]


class Listener:
    """A loopback server keeping the path and proxy header of every request it answers."""

    def __init__(self, body: bytes) -> None:
        """Answer every request with this JSON body."""
        self.body = body
        self.requests: list[tuple[str, str | None]] = []
        self.port = 0

    async def __call__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Read one request's head, keep what it asked for, and answer it."""
        try:
            head = (await reader.readuntil(b"\r\n\r\n")).decode().split("\r\n")
            headers = dict(line.lower().split(": ", 1) for line in head[1:] if line)
            self.requests.append((head[0].split(" ")[1], headers.get("x-proxy-key")))
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n"
                + f"Content-Length: {len(self.body)}\r\n\r\n".encode()
                + self.body
            )
            await writer.drain()
        finally:
            writer.close()


@pytest_asyncio.fixture
async def listeners() -> AsyncIterator[Any]:
    """Start a listener for each body a test asks for, on its own loopback port."""
    servers: list[asyncio.Server] = []

    async def start(body: bytes) -> Listener:
        listener = Listener(body)
        server = await asyncio.start_server(listener, "127.0.0.1", 0)
        servers.append(server)
        listener.port = server.sockets[0].getsockname()[1]
        return listener

    try:
        yield start
    finally:
        for server in servers:
            server.close()


async def test_a_real_client_sends_nothing_to_another_port(
    ctx: FakeContext, monkeypatch: pytest.MonkeyPatch, listeners: Any
) -> None:
    outside = await listeners(b'{"secret": "dummy"}')
    results = {"assets": {"result": {"href": f"http://127.0.0.1:{outside.port}/stolen"}}}
    service = await listeners(json.dumps(results).encode())
    config = ClimateConnectionConfig(
        base_url=f"http://127.0.0.1:{service.port}/ocs", headers={"X-Proxy-Key": "dummy-key"}
    )

    def http(ref: str) -> httpx2.AsyncClient:
        return build_client(config)

    ctx.connections[CONNECTION] = config
    monkeypatch.setattr(ctx, "http", http)
    with pytest.raises(BlockFailure) as refused:
        await call_block(ClimateJobResultOperator(), {"connection": CONNECTION, "job_id": "j1"}, ctx)
    assert refused.value.code == OUTSIDE
    assert outside.requests == []
    assert service.requests == [("/ocs/jobs/j1/results", "dummy-key")]
