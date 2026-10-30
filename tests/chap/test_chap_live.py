"""Opt-in checks against a real Chap: ``DIRIGENT_LIVE=1``, and ``CHAP_LIVE_URL`` to name the server.

They only read. Without ``CHAP_LIVE_TOKEN`` the server's answer to the health check is
asserted as the mode it runs in; with one, the token is proven and the models are listed.
"""

import os
from typing import Final

import httpx2
import pytest
from pydantic import SecretStr

from dirigent_contrib.chap.configured_models import ChapModelsListOperator, ChapModelsListOutput
from dirigent_contrib.chap.connection import ChapConnectionConfig, ChapConnectionKind, build_client
from dirigent_contrib.chap.messages import CONNECTION_AUTH_REQUIRED
from dirigent_testing import FakeContext, call_block

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("DIRIGENT_LIVE") != "1", reason="live checks run with DIRIGENT_LIVE=1"),
]

#: The public demo, which wants a token.
DEMO: Final = "https://climate-demo.dhis2.org/chap/stable"


def _config() -> ChapConnectionConfig:
    token = os.environ.get("CHAP_LIVE_TOKEN")
    return ChapConnectionConfig(
        base_url=os.environ.get("CHAP_LIVE_URL", DEMO), api_token=SecretStr(token) if token else None
    )


async def test_the_health_check_reports_the_servers_version_and_auth_mode() -> None:
    config = _config()
    report = await ChapConnectionKind().check(config)
    assert report.version
    if config.api_token is None and report.healthy is False:
        assert report.detail == CONNECTION_AUTH_REQUIRED.render()
    else:
        assert report.healthy is True, report.detail


async def test_the_models_are_listed_with_a_token(block_ctx: FakeContext, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config()
    if config.api_token is None:
        pytest.skip("listing the models needs CHAP_LIVE_TOKEN on a server with auth")
    block_ctx.connections["live"] = config

    def http(ref: str) -> httpx2.AsyncClient:
        return build_client(config)

    monkeypatch.setattr(block_ctx, "http", http)
    output = await call_block(ChapModelsListOperator(), {"connection": "live"}, block_ctx)
    assert isinstance(output, ChapModelsListOutput)
