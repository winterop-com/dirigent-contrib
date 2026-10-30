"""The ``chap`` connection kind: one Chap server, its optional API token, and the client for it."""

from datetime import timedelta
from typing import ClassVar, Final, cast

import httpx2
from pydantic import BaseModel, Field, SecretStr

from dirigent_common import BlockModel, Duration, HealthReport
from dirigent_contrib.chap.messages import CONNECTION_AUTH_REQUIRED, CONNECTION_TOKEN_REFUSED, CONNECTION_UNREACHABLE
from dirigent_contrib.chap.web import remote_words
from dirigent_plugin import ConnectionKind, ConnectionRef, StepContext

#: The one path Chap always answers without a token, and which says whether it wants one.
SYSTEM_INFO_PATH: Final = "/system/info"

#: The cheap authenticated read that proves a token.
CONFIGURED_MODELS_PATH: Final = "/v1/crud/configured-models"

#: The header a token travels in.
AUTHORIZATION: Final = "Authorization"


class ChapConnectionConfig(BlockModel):
    """Everything needed to talk to one Chap server."""

    base_url: str = Field(min_length=1)
    """The server root every request path is resolved against, such as `http://localhost:8000`."""

    api_token: SecretStr | None = None
    """The server's API token, sent as `Authorization: Bearer`; leave unset for a server without auth."""

    verify_tls: bool = True
    """Whether certificates are verified; turning this off is a per-connection decision."""

    timeout: Duration = Field(default=timedelta(seconds=30), gt=timedelta(0))
    """The timeout applied to every request through this connection."""


def settings_of(config: BaseModel) -> ChapConnectionConfig:
    """Read a connection's config as this kind's own model, whichever model the caller held."""
    if isinstance(config, ChapConnectionConfig):
        return config
    return ChapConnectionConfig.model_validate(config.model_dump())


def authorize(client: httpx2.AsyncClient, config: ChapConnectionConfig) -> httpx2.AsyncClient:
    """Put the connection's token on a client as a bearer credential, or take every credential off.

    A server without auth is sent no ``Authorization`` header at all, whatever the client was
    built with.
    """
    client.headers.pop(AUTHORIZATION, None)
    if config.api_token is not None:
        client.headers[AUTHORIZATION] = f"Bearer {config.api_token.get_secret_value()}"
    return client


def build_client(
    config: ChapConnectionConfig, transport: httpx2.AsyncBaseTransport | None = None
) -> httpx2.AsyncClient:
    """Build a client bound to the connection's URL, token, TLS setting and timeout."""
    client = httpx2.AsyncClient(
        base_url=config.base_url,
        verify=config.verify_tls,
        timeout=config.timeout.total_seconds(),
        transport=transport,
    )
    return authorize(client, config)


def client_for(ctx: StepContext, ref: ConnectionRef) -> httpx2.AsyncClient:
    """The client one block call uses: the one the engine builds for the connection, with its token as a bearer."""
    return authorize(ctx.http(ref), ctx.connection(ref, ChapConnectionConfig))


#: A forecast line rising through three points, over a baseline, on the 24-unit grid.
CHAP_MARK: Final = "M3 19h18v2H3ZM3 15.6l5-5.2l4 3.2l6.6-7.8l1.5 1.3l-7.8 9.2l-4-3.2l-3.8 4ZM17 4h4v4Z"


class ChapConnectionKind(ConnectionKind):
    """The connection kind every block in this pack resolves its server and token through."""

    id: ClassVar[str] = "chap"
    config_model: ClassVar[type[BaseModel]] = ChapConnectionConfig
    mark: ClassVar[str | None] = CHAP_MARK

    def __init__(self, transport: httpx2.AsyncBaseTransport | None = None) -> None:
        """Check through the given transport, or through the network when none is given."""
        self._transport = transport

    async def check(self, config: BaseModel) -> HealthReport:
        """Ask the server what it is, and prove the token on an authenticated read when one is set.

        ``/system/info`` is always open, and says whether the server wants a token: a server
        that does, reached through a connection without one, is reported unhealthy rather than
        healthy-until-the-first-step.
        """
        settings = settings_of(config)
        try:
            async with build_client(settings, self._transport) as client:
                info = await client.get(SYSTEM_INFO_PATH)
                if info.is_error:
                    return HealthReport(healthy=False, detail=CONNECTION_UNREACHABLE.render(detail=_said(info)))
                body = _object(info)
                version = body.get("chap_core_version")
                found = str(version) if version else None
                if body.get("auth_required") is True and settings.api_token is None:
                    return HealthReport(healthy=False, detail=CONNECTION_AUTH_REQUIRED.render(), version=found)
                if settings.api_token is not None:
                    proof = await client.get(CONFIGURED_MODELS_PATH)
                    if proof.status_code in (401, 403):
                        detail = CONNECTION_TOKEN_REFUSED.render(detail=remote_words(proof))
                        return HealthReport(healthy=False, detail=detail, version=found)
                    if proof.is_error:
                        return HealthReport(healthy=False, detail=CONNECTION_UNREACHABLE.render(detail=_said(proof)))
        except Exception as error:  # noqa: BLE001 - a health check reports its verdict, it never raises
            return HealthReport(
                healthy=False, detail=CONNECTION_UNREACHABLE.render(detail=str(error) or type(error).__name__)
            )
        return HealthReport(healthy=True, version=found)


def _said(response: httpx2.Response) -> str:
    """Name the call and what it was answered with."""
    request = response.request
    return f"{request.method} {request.url.path} answered {response.status_code}: {remote_words(response)}"


def _object(response: httpx2.Response) -> dict[str, object]:
    """Read a body as a JSON object, or as an empty one when it is not."""
    try:
        body: object = response.json()
    except ValueError:
        return {}
    if not isinstance(body, dict):
        return {}
    return {str(key): value for key, value in cast("dict[object, object]", body).items()}
