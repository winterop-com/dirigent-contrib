"""The ``climate`` connection kind: one instance of the open climate service, and the client for it."""

import re
from datetime import timedelta
from typing import ClassVar, Final, cast

import httpx2
from pydantic import BaseModel, ConfigDict, Field, field_validator

from dirigent_common import BlockModel, Duration, HealthReport, Size
from dirigent_contrib.climate.messages import (
    BAD_HEADER,
    CONNECTION_READ_ONLY,
    CONNECTION_UNHEALTHY,
    CONNECTION_UNREACHABLE,
    PAST_DEADLINE,
    RESPONSE_TOO_LARGE,
)
from dirigent_contrib.climate.web import remote_words
from dirigent_contrib.limits import BoundedClient, Limits
from dirigent_plugin import ConnectionKind, ConnectionRef, StepContext

HEALTH_PATH: Final = "/health"
INFO_PATH: Final = "/info"

#: The health the service reports when nothing is wrong.
HEALTHY: Final = "healthy"

#: The health it reports when it answers but something under it is failing.
DEGRADED: Final = "degraded"

#: What a header's name may hold, as HTTP defines one.
HEADER_NAME: Final = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+")

#: What a header's value may hold: visible ASCII, with spaces only between its words.
HEADER_VALUE: Final = re.compile(r"(?:[\x21-\x7e]+(?: +[\x21-\x7e]+)*)?")


class ClimateConnectionConfig(BlockModel):
    """Everything needed to talk to one instance of the open climate service."""

    model_config = ConfigDict(hide_input_in_errors=True)

    base_url: str = Field(min_length=1)
    """The service root every request path is resolved against, such as `https://climate-demo.dhis2.org/ocs`."""

    headers: dict[str, str] = Field(default_factory=dict[str, str])
    """Extra headers sent on every request, for an instance behind a proxy that wants them. They are
    stored as written, not as secrets."""

    verify_tls: bool = True
    """Whether certificates are verified; turning this off is a per-connection decision."""

    timeout: Duration = Field(default=timedelta(seconds=30), gt=timedelta(0))
    """The timeout applied to each read of every request through this connection, unless a block says otherwise."""

    request_deadline: Duration = Field(default=timedelta(minutes=10), gt=timedelta(0))
    """The longest one request through this connection may take, start to last byte, unless a block says otherwise."""

    max_response: Size = Field(default=64 * 1024 * 1024, ge=1)
    """The most one response through this connection may decode to, unless a block says otherwise; a larger one is
    refused."""

    @field_validator("headers")
    @classmethod
    def _headers_can_be_sent(cls, headers: dict[str, str]) -> dict[str, str]:
        """Reject a header that cannot be sent, without saying what it held."""
        for name, value in headers.items():
            if HEADER_NAME.fullmatch(name) is None or HEADER_VALUE.fullmatch(value) is None:
                raise ValueError(BAD_HEADER.render())
        return headers


def settings_of(config: BaseModel) -> ClimateConnectionConfig:
    """Read a connection's config as this kind's own model, whichever model the caller held."""
    if isinstance(config, ClimateConnectionConfig):
        return config
    return ClimateConnectionConfig.model_validate(config.model_dump())


def build_client(
    config: ClimateConnectionConfig, transport: httpx2.AsyncBaseTransport | None = None
) -> httpx2.AsyncClient:
    """Build a client bound to the connection's URL, headers, TLS setting and timeout."""
    return httpx2.AsyncClient(
        base_url=config.base_url,
        headers=config.headers,
        verify=config.verify_tls,
        timeout=config.timeout.total_seconds(),
        transport=transport,
    )


def bounded(client: httpx2.AsyncClient, config: ClimateConnectionConfig) -> BoundedClient:
    """Hold a client to the connection's limits."""
    return BoundedClient(
        client,
        Limits(
            max_response=config.max_response,
            request_deadline=config.request_deadline.total_seconds(),
            too_large=RESPONSE_TOO_LARGE,
            past_deadline=PAST_DEADLINE,
        ),
    )


def client_for(ctx: StepContext, ref: ConnectionRef) -> BoundedClient:
    """The client one block call uses: the one the engine builds for the connection, with its headers on."""
    config = ctx.connection(ref, ClimateConnectionConfig)
    client = ctx.http(ref)
    client.headers.update(config.headers)
    return bounded(client, config)


#: A sun half behind a cloud, on the 24-unit grid.
CLIMATE_MARK: Final = (
    "M9 2h2v3H9Z"
    "M2.6 4.6l1.4-1.4l2.1 2.1l-1.4 1.4Z"
    "M2 10h3v2H2Z"
    "M10 7a4 4 0 0 1 3.7 2.5A6 6 0 0 0 7.2 12.8A4 4 0 0 1 10 7Z"
    "M8 21a4 4 0 0 1 0-8a5.5 5.5 0 0 1 10.6 1.5A3.3 3.3 0 0 1 18 21Z"
)


class ClimateConnectionKind(ConnectionKind):
    """The connection kind every block in this pack resolves its instance through."""

    id: ClassVar[str] = "climate"
    config_model: ClassVar[type[BaseModel]] = ClimateConnectionConfig
    mark: ClassVar[str | None] = CLIMATE_MARK

    def __init__(self, transport: httpx2.AsyncBaseTransport | None = None) -> None:
        """Check through the given transport, or through the network when none is given."""
        self._transport = transport

    async def check(self, config: BaseModel) -> HealthReport:
        """Ask the service how it is and what it is, never raising.

        A read-only instance is healthy, and the report says that it refuses every write.
        """
        try:
            settings = settings_of(config)
            async with bounded(build_client(settings, self._transport), settings) as client:
                health = await client.request("GET", HEALTH_PATH)
                if health.is_error:
                    detail = f"GET {HEALTH_PATH} answered {health.status_code}: {remote_words(health)}"
                    return HealthReport(healthy=False, detail=CONNECTION_UNREACHABLE.render(detail=detail))
                status = str(_object(health).get("status") or "")
                info = await client.request("GET", INFO_PATH)
                about = _object(info) if not info.is_error else {}
        except Exception as error:  # noqa: BLE001 - a health check reports its verdict, it never raises
            detail = str(error) or type(error).__name__
            return HealthReport(healthy=False, detail=CONNECTION_UNREACHABLE.render(detail=detail))
        version = str(about["app_version"]) if about.get("app_version") else None
        details: list[str] = []
        if status != HEALTHY:
            details.append(CONNECTION_UNHEALTHY.render(status=status or "without a status"))
        if about.get("read_only") is True:
            details.append(CONNECTION_READ_ONLY.render())
        return HealthReport(
            healthy=status in (HEALTHY, DEGRADED),
            detail="; ".join(details) or None,
            version=version,
        )


def _object(response: httpx2.Response) -> dict[str, object]:
    """Read a body as a JSON object, or as an empty one when it is not."""
    try:
        body: object = response.json()
    except ValueError:
        return {}
    if not isinstance(body, dict):
        return {}
    return {str(key): value for key, value in cast("dict[object, object]", body).items()}
