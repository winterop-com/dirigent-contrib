"""Opt-in checks against a real open climate service: ``DIRIGENT_LIVE=1``, and ``CLIMATE_LIVE_URL`` to name it.

They only read: the health check and the dataset listing.
"""

import os
from typing import Final

import httpx2
import pytest

from dirigent_climate.connection import ClimateConnectionConfig, ClimateConnectionKind, build_client
from dirigent_climate.datasets import ClimateDatasetsListOperator, ClimateDatasetsListOutput
from dirigent_testing import FakeContext, call_block

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("DIRIGENT_LIVE") != "1", reason="live checks run with DIRIGENT_LIVE=1"),
]

#: The public demo.
DEMO: Final = "https://climate-demo.dhis2.org/ocs"


def _config() -> ClimateConnectionConfig:
    return ClimateConnectionConfig(base_url=os.environ.get("CLIMATE_LIVE_URL", DEMO))


async def test_the_health_check_is_healthy_and_says_the_version() -> None:
    report = await ClimateConnectionKind().check(_config())
    assert report.healthy is True, report.detail
    assert report.version


async def test_the_datasets_are_listed(block_ctx: FakeContext, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config()
    block_ctx.connections["live"] = config

    def http(ref: str) -> httpx2.AsyncClient:
        return build_client(config)

    monkeypatch.setattr(block_ctx, "http", http)
    output = await call_block(ClimateDatasetsListOperator(), {"connection": "live"}, block_ctx)
    assert isinstance(output, ClimateDatasetsListOutput)
    assert output.count > 0
