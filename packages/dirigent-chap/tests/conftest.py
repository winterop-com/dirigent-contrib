"""Installs the chap connection and answers every block from a scripted Chap."""

import pytest
from pydantic import SecretStr

from chapserver import BASE_URL, CONNECTION, ChapServer
from dirigent_chap.connection import ChapConnectionConfig
from dirigent_testing import FakeContext


@pytest.fixture
def chap() -> ChapServer:
    return ChapServer()


@pytest.fixture
def ctx(block_ctx: FakeContext, chap: ChapServer) -> FakeContext:
    """A context whose chap connection carries a token, and whose HTTP is the scripted Chap."""
    block_ctx.connections[CONNECTION] = ChapConnectionConfig(base_url=BASE_URL, api_token=SecretStr("t" * 32))
    block_ctx.handler = chap
    return block_ctx
