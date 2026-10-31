"""The ``chap`` connection: its health check in both auth modes, and the client a block is handed."""

import httpx2
import pytest
from pydantic import SecretStr, ValidationError

from dirigent_contrib.chap.connection import ChapConnectionConfig, ChapConnectionKind, build_client, client_for
from dirigent_contrib.chap.messages import CONNECTION_AUTH_REQUIRED
from dirigent_testing import FakeContext
from tests.chap.chapserver import BASE_URL, CONNECTION, ChapServer

TOKEN = "t" * 32

DUMMY = "DUMMYTOKEN4567"


def _info(auth_required: bool) -> dict[str, object]:
    return {
        "chap_core_version": "2.5.1",
        "python_version": "3.13.14",
        "server_date": "2026-10-30T00:00:00+00:00",
        "server_time_zone_id": "Etc/UTC",
        "revision": "",
        "auth_required": auth_required,
    }


def _kind(server: ChapServer) -> ChapConnectionKind:
    return ChapConnectionKind(transport=httpx2.MockTransport(server))


async def test_an_open_server_without_a_token_is_healthy_and_says_its_version(chap: ChapServer) -> None:
    chap.on("GET", "/system/info", body=_info(auth_required=False))
    report = await _kind(chap).check(ChapConnectionConfig(base_url=BASE_URL))
    assert report.healthy is True
    assert report.version == "2.5.1"
    assert "authorization" not in chap.requests[0].headers
    assert chap.sent("GET", "/v1/crud/configured-models") == []


async def test_a_server_that_wants_a_token_is_unhealthy_through_a_connection_without_one(chap: ChapServer) -> None:
    chap.on("GET", "/system/info", body=_info(auth_required=True))
    report = await _kind(chap).check(ChapConnectionConfig(base_url=BASE_URL))
    assert report.healthy is False
    assert report.detail == CONNECTION_AUTH_REQUIRED.render()
    assert report.version == "2.5.1"


async def test_a_token_is_proven_on_an_authenticated_read_as_a_bearer(chap: ChapServer) -> None:
    chap.on("GET", "/system/info", body=_info(auth_required=True))
    chap.on("GET", "/v1/crud/configured-models", body=[])
    report = await _kind(chap).check(ChapConnectionConfig(base_url=BASE_URL, api_token=SecretStr(TOKEN)))
    assert report.healthy is True
    proof = chap.sent("GET", "/v1/crud/configured-models")[0]
    assert proof.headers["authorization"] == f"Bearer {TOKEN}"


async def test_a_refused_token_is_unhealthy_in_chaps_own_words(chap: ChapServer) -> None:
    chap.on("GET", "/system/info", body=_info(auth_required=True))
    chap.on("GET", "/v1/crud/configured-models", status=401, body={"detail": "Missing or invalid API token"})
    report = await _kind(chap).check(ChapConnectionConfig(base_url=BASE_URL, api_token=SecretStr(TOKEN)))
    assert report.healthy is False
    assert report.detail is not None and "Missing or invalid API token" in report.detail


async def test_an_unreachable_server_is_unhealthy_and_the_check_does_not_raise() -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    kind = ChapConnectionKind(transport=httpx2.MockTransport(refuse))
    report = await kind.check(ChapConnectionConfig(base_url=BASE_URL))
    assert report.healthy is False
    assert report.detail is not None and "connection refused" in report.detail


async def test_a_block_sends_the_token_as_a_bearer_whatever_the_engine_built(
    ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    built = httpx2.AsyncClient(base_url=BASE_URL, headers={"Authorization": f"ApiToken {TOKEN}"})

    def http(ref: str) -> httpx2.AsyncClient:
        return built

    monkeypatch.setattr(ctx, "http", http)
    async with client_for(ctx.as_context(), CONNECTION) as client:
        assert client.headers["authorization"] == f"Bearer {TOKEN}"


async def test_a_block_sends_no_credential_through_a_connection_without_a_token(ctx: FakeContext) -> None:
    ctx.connections[CONNECTION] = ChapConnectionConfig(base_url=BASE_URL)
    async with client_for(ctx.as_context(), CONNECTION) as client:
        assert "authorization" not in client.headers


def test_a_connection_needs_a_base_url() -> None:
    with pytest.raises(ValueError, match="base_url"):
        ChapConnectionConfig.model_validate({})


#: A dummy token, and what a paste or a file can do to it. None of them can be a header value whole.
BAD_TOKENS = [
    pytest.param(f"{DUMMY} ", id="trailing-blank"),
    pytest.param(f" {DUMMY}", id="leading-blank"),
    pytest.param(f"{DUMMY}\n", id="trailing-lf"),
    pytest.param(f"{DUMMY}\r\n", id="trailing-crlf"),
    pytest.param(f"{DUMMY}\nX-Injected: 1", id="inner-lf"),
    pytest.param(f"{DUMMY[:6]} {DUMMY[6:]}", id="inner-blank"),
    pytest.param(f"{DUMMY}\t", id="tab"),
    pytest.param(f"{DUMMY}é", id="non-ascii"),
    pytest.param("x" * 330 + "\n" + DUMMY, id="long-with-a-line-feed"),
]


@pytest.mark.parametrize("token", BAD_TOKENS)
def test_a_token_that_cannot_be_a_header_value_is_refused_without_repeating_it(token: str) -> None:
    with pytest.raises(ValidationError) as refused:
        ChapConnectionConfig.model_validate({"base_url": BASE_URL, "api_token": token})
    assert "visible ASCII" in str(refused.value)
    assert DUMMY not in str(refused.value)
    assert DUMMY not in repr(refused.value)
    assert DUMMY[:6] not in str(refused.value)


def test_an_empty_token_is_read_as_unset() -> None:
    config = ChapConnectionConfig.model_validate({"base_url": BASE_URL, "api_token": ""})
    assert config.api_token is None
    client = build_client(config)
    assert "authorization" not in client.headers


@pytest.mark.parametrize("token", [DUMMY, "t" * 32, "a.b-c_d~e+f/g=", "!#$%&'*"])
def test_a_token_of_visible_ascii_is_sent_as_written(token: str) -> None:
    config = ChapConnectionConfig.model_validate({"base_url": BASE_URL, "api_token": token})
    assert build_client(config).headers["authorization"] == f"Bearer {token}"
