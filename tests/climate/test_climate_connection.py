"""The ``climate`` connection: its health check, its read-only flag, and the client a block is handed."""

import httpx2

from dirigent_contrib.climate.connection import ClimateConnectionConfig, ClimateConnectionKind, client_for
from dirigent_contrib.climate.messages import CONNECTION_READ_ONLY
from dirigent_testing import FakeContext
from tests.climate.climateserver import BASE_URL, CONNECTION, ClimateServer

INFO = {"app_version": "0.1.1", "python_version": "3.12.13", "uvicorn_version": "0.46.0", "read_only": False}


def _kind(server: ClimateServer) -> ClimateConnectionKind:
    return ClimateConnectionKind(transport=httpx2.MockTransport(server))


async def test_a_healthy_service_is_healthy_and_says_its_version(ocs: ClimateServer) -> None:
    ocs.on("GET", "/health", body={"status": "healthy"})
    ocs.on("GET", "/info", body=INFO)
    report = await _kind(ocs).check(ClimateConnectionConfig(base_url=BASE_URL, headers={"X-Proxy-Key": "k"}))
    assert (report.healthy, report.version, report.detail) == (True, "0.1.1", None)
    assert all(request.headers["x-proxy-key"] == "k" for request in ocs.requests)


async def test_a_read_only_service_is_healthy_and_the_report_says_it_refuses_writes(ocs: ClimateServer) -> None:
    ocs.on("GET", "/health", body={"status": "healthy"})
    ocs.on("GET", "/info", body={**INFO, "read_only": True})
    report = await _kind(ocs).check(ClimateConnectionConfig(base_url=BASE_URL))
    assert report.healthy is True
    assert report.detail == CONNECTION_READ_ONLY.render()


async def test_a_degraded_service_is_healthy_with_a_detail_and_an_unhealthy_one_is_not(ocs: ClimateServer) -> None:
    ocs.on("GET", "/health", body={"status": "degraded"})
    ocs.on("GET", "/health", body={"status": "unhealthy"})
    ocs.on("GET", "/info", body=INFO)
    kind = _kind(ocs)
    degraded = await kind.check(ClimateConnectionConfig(base_url=BASE_URL))
    assert degraded.healthy is True and degraded.detail is not None and "degraded" in degraded.detail
    unhealthy = await kind.check(ClimateConnectionConfig(base_url=BASE_URL))
    assert unhealthy.healthy is False


async def test_a_service_that_answers_health_with_an_error_is_unhealthy(ocs: ClimateServer) -> None:
    ocs.on("GET", "/health", status=502, text="bad gateway")
    report = await _kind(ocs).check(ClimateConnectionConfig(base_url=BASE_URL))
    assert report.healthy is False
    assert report.detail is not None and "502" in report.detail


async def test_an_unreachable_service_is_unhealthy_and_the_check_does_not_raise() -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    report = await ClimateConnectionKind(transport=httpx2.MockTransport(refuse)).check(
        ClimateConnectionConfig(base_url=BASE_URL)
    )
    assert report.healthy is False


async def test_a_block_sends_the_connections_headers(ctx: FakeContext) -> None:
    async with client_for(ctx.as_context(), CONNECTION) as client:
        assert client.headers["x-proxy-key"] == "k"
