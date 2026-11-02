"""The ``climate`` connection: its health check, its read-only flag, and the client a block is handed."""

import httpx2
import pytest
from pydantic import SecretStr, ValidationError

from dirigent_common import secrets_of
from dirigent_contrib.climate.connection import (
    ClimateConnectionConfig,
    ClimateConnectionKind,
    build_client,
    client_for,
)
from dirigent_contrib.climate.messages import CONNECTION_READ_ONLY
from dirigent_testing import FakeContext
from tests.climate.climateserver import BASE_URL, CONNECTION, ClimateServer

DUMMY = "DUMMYHEADER4567"

INFO = {"app_version": "0.1.1", "python_version": "3.12.13", "uvicorn_version": "0.46.0", "read_only": False}


def _kind(server: ClimateServer) -> ClimateConnectionKind:
    return ClimateConnectionKind(transport=httpx2.MockTransport(server))


async def test_a_healthy_service_is_healthy_and_says_its_version(ocs: ClimateServer) -> None:
    ocs.on("GET", "/health", body={"status": "healthy"})
    ocs.on("GET", "/info", body=INFO)
    report = await _kind(ocs).check(ClimateConnectionConfig(base_url=BASE_URL, headers={"X-Proxy-Route": "k"}))
    assert (report.healthy, report.version, report.detail) == (True, "0.1.1", None)
    assert all(request.headers["x-proxy-route"] == "k" for request in ocs.requests)


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
        assert client.headers["x-proxy-route"] == "k"


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param({"X-Proxy-Route": f"{DUMMY} "}, id="trailing-blank"),
        pytest.param({"X-Proxy-Route": f" {DUMMY}"}, id="leading-blank"),
        pytest.param({"X-Proxy-Route": f"{DUMMY}\n"}, id="trailing-lf"),
        pytest.param({"X-Proxy-Route": f"{DUMMY}\r\n"}, id="trailing-crlf"),
        pytest.param({"X-Proxy-Route": f"{DUMMY}\nX-Injected: 1"}, id="inner-lf"),
        pytest.param({"X-Proxy-Route": f"{DUMMY}é"}, id="non-ascii"),
        pytest.param({f"{DUMMY}\n": "v"}, id="a-name-with-a-line-feed"),
        pytest.param({f"{DUMMY}: x": "v"}, id="a-name-with-a-colon"),
    ],
)
def test_a_header_that_cannot_be_sent_is_refused_without_repeating_it(headers: dict[str, str]) -> None:
    with pytest.raises(ValidationError) as refused:
        ClimateConnectionConfig.model_validate({"base_url": BASE_URL, "headers": headers})
    assert "cannot be sent" in str(refused.value)
    assert DUMMY not in str(refused.value)
    assert DUMMY not in repr(refused.value)


@pytest.mark.parametrize("value", ["k", "Bearer abc", "ApiKey  two  spaces", "a=b; c=d", ""])
def test_a_header_that_can_be_sent_is_kept_as_written(value: str) -> None:
    config = ClimateConnectionConfig.model_validate({"base_url": BASE_URL, "headers": {"X-Proxy-Route": value}})
    assert build_client(config).headers["x-proxy-route"] == value


@pytest.mark.parametrize(
    "name",
    [
        "Authorization",
        "authorization",
        "AUTHORIZATION",
        "Proxy-Authorization",
        "Cookie",
        "Set-Cookie",
        "X-Api-Key",
        "x_api_key",
        "X-APIKEY",
        "Api-Key",
        "X-Auth",
        "X-Auth-Token",
        "X-Amz-Security-Token",
        "X-Client-Secret",
        "X-Password",
        "X-Session-Id",
        "X-Proxy-Key",
        "Ocp-Apim-Subscription-Key",
        "Key",
    ],
)
def test_a_header_named_for_a_credential_is_refused_and_says_where_it_goes(name: str) -> None:
    with pytest.raises(ValidationError) as refused:
        ClimateConnectionConfig.model_validate({"base_url": BASE_URL, "headers": {name: DUMMY}})
    assert "put its value in credential" in str(refused.value)
    assert name in str(refused.value)
    assert DUMMY not in str(refused.value)
    assert DUMMY not in repr(refused.value)


@pytest.mark.parametrize(
    "name",
    ["Accept", "X-Proxy-Route", "X-Routing-Key", "Idempotency-Key", "X-Author", "X-Correlation-Id", "X-Keyboard"],
)
def test_a_header_that_names_no_credential_is_kept(name: str) -> None:
    config = ClimateConnectionConfig.model_validate({"base_url": BASE_URL, "headers": {name: "v"}})
    assert build_client(config).headers[name] == "v"


def test_a_plain_header_cannot_spell_the_name_the_credential_is_sent_in() -> None:
    with pytest.raises(ValidationError, match="put its value in credential"):
        ClimateConnectionConfig.model_validate(
            {"base_url": BASE_URL, "headers": {"x-tenant": "v"}, "credential_header": "X-Tenant"}
        )


@pytest.mark.parametrize(
    ("settings", "header", "sent"),
    [
        ({}, "authorization", DUMMY),
        ({"credential_scheme": "Bearer"}, "authorization", f"Bearer {DUMMY}"),
        ({"credential_header": "X-Proxy-Key"}, "x-proxy-key", DUMMY),
    ],
    ids=["alone", "under-a-scheme", "in-a-header-of-its-own"],
)
async def test_the_credential_is_sent_on_the_check_and_on_a_block(
    ocs: ClimateServer, ctx: FakeContext, settings: dict[str, str], header: str, sent: str
) -> None:
    config = ClimateConnectionConfig.model_validate({"base_url": BASE_URL, "credential": DUMMY, **settings})
    ocs.on("GET", "/health", body={"status": "healthy"})
    ocs.on("GET", "/info", body=INFO)
    await _kind(ocs).check(config)
    assert [request.headers[header] for request in ocs.requests] == [sent, sent]
    ctx.connections[CONNECTION] = config
    async with client_for(ctx.as_context(), CONNECTION) as client:
        assert client.headers[header] == sent


def test_the_credential_is_a_secret_the_config_does_not_show() -> None:
    config = ClimateConnectionConfig(base_url=BASE_URL, credential=SecretStr(DUMMY))
    assert DUMMY not in repr(config)
    assert DUMMY not in str(config.model_dump())
    assert secrets_of(config) == {DUMMY}


def test_no_credential_is_read_from_an_empty_one() -> None:
    config = ClimateConnectionConfig.model_validate({"base_url": BASE_URL, "credential": ""})
    assert config.credential is None
    assert "authorization" not in build_client(config).headers


@pytest.mark.parametrize("value", [f"{DUMMY}\n", f"Bearer {DUMMY}", f" {DUMMY}", f"{DUMMY}é"])
def test_a_credential_that_cannot_be_sent_is_refused_without_repeating_it(value: str) -> None:
    with pytest.raises(ValidationError, match="a credential must be visible ASCII") as refused:
        ClimateConnectionConfig.model_validate({"base_url": BASE_URL, "credential": value})
    assert DUMMY not in str(refused.value)
    assert DUMMY not in repr(refused.value)


async def test_a_credential_a_proxy_quotes_back_does_not_reach_the_health_report(ocs: ClimateServer) -> None:
    ocs.on("GET", "/health", status=401, text=f"refused key {DUMMY}")
    config = ClimateConnectionConfig(base_url=BASE_URL, credential=SecretStr(DUMMY), credential_header="X-Proxy-Key")
    report = await _kind(ocs).check(config)
    assert report.healthy is False
    assert report.detail is not None and "refused key ***" in report.detail


async def test_a_credential_a_transport_error_quotes_does_not_reach_the_health_report() -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError(f"rejected {request.headers['authorization']}", request=request)

    config = ClimateConnectionConfig(base_url=BASE_URL, credential=SecretStr(DUMMY))
    report = await ClimateConnectionKind(transport=httpx2.MockTransport(refuse)).check(config)
    assert report.healthy is False
    assert report.detail is not None and DUMMY not in report.detail
