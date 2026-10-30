"""Installs the climate connection and answers every block from a scripted open climate service."""

import pytest

from dirigent_contrib.climate.connection import ClimateConnectionConfig
from dirigent_testing import FakeContext
from tests.climate.climateserver import BASE_URL, CONNECTION, ClimateServer


@pytest.fixture
def ocs() -> ClimateServer:
    return ClimateServer()


@pytest.fixture
def ctx(block_ctx: FakeContext, ocs: ClimateServer) -> FakeContext:
    """A context whose climate connection carries a proxy header, and whose HTTP is the scripted service."""
    block_ctx.connections[CONNECTION] = ClimateConnectionConfig(base_url=BASE_URL, headers={"X-Proxy-Key": "k"})
    block_ctx.handler = ocs
    return block_ctx
