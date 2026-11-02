"""The ``climate`` connection kind: one instance of the open climate service, and the client for it."""

import re
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import ClassVar, Final, Self, cast
from urllib.parse import quote, quote_plus, urlsplit

import httpx2
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from dirigent_common import BlockModel, Duration, HealthReport, Size, scrub, secrets_of
from dirigent_contrib.climate.messages import (
    BAD_BASE_URL,
    BAD_CREDENTIAL,
    BAD_HEADER,
    CONNECTION_READ_ONLY,
    CONNECTION_UNHEALTHY,
    CONNECTION_UNREACHABLE,
    CREDENTIAL_HEADER_REFUSED,
    CREDENTIAL_TWO_PLACES,
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

#: What a query parameter a credential is sent as may be called.
QUERY_NAME: Final = re.compile(r"[A-Za-z0-9_.~-]+")

#: The header a credential is sent in when the connection names neither a header nor a query parameter.
DEFAULT_CREDENTIAL_HEADER: Final = "Authorization"

#: What a credential may hold: visible ASCII with no whitespace, the only text a header value carries unchanged.
CREDENTIAL: Final = re.compile(r"[\x21-\x7e]+")

#: A word that makes a header's name, read without its separators, the name of a credential.
CREDENTIAL_WORDS: Final = (
    "accesskey",
    "apikey",
    "authorization",
    "bearer",
    "cookie",
    "credential",
    "passwd",
    "password",
    "privatekey",
    "secret",
    "token",
)

#: A whole segment of a header's name that does the same.
CREDENTIAL_SEGMENTS: Final = frozenset({"auth", "session"})

#: The segment before a final `key` that says the key addresses something rather than unlocks it.
ADDRESSING_KEYS: Final = frozenset({"cache", "dedup", "deduplication", "idempotency", "partition", "routing", "sort"})


def carries_credential(name: str) -> bool:
    """Whether a header's name, in any case and with a hyphen or an underscore, is that of a credential."""
    segments = re.split(r"[-_]", name.lower())
    if any(word in "".join(segments) for word in CREDENTIAL_WORDS) or CREDENTIAL_SEGMENTS.intersection(segments):
        return True
    return segments[-1] == "key" and (len(segments) == 1 or segments[-2] not in ADDRESSING_KEYS)


class ClimateConnectionConfig(BlockModel):
    """Everything needed to talk to one instance of the open climate service."""

    model_config = ConfigDict(hide_input_in_errors=True)

    base_url: str = Field(min_length=1)
    """The service root every request path is resolved against, such as `https://climate-demo.dhis2.org/ocs`; a
    user, a password, a query or a fragment in it is refused."""

    headers: dict[str, str] = Field(default_factory=dict[str, str])
    """Extra headers sent on every request, for an instance behind a proxy that wants them. They are
    stored as written, so one whose name carries a credential is refused."""

    credential: SecretStr | None = None
    """A credential a proxy in front of the instance wants on every request: visible ASCII with no whitespace."""

    credential_header: str | None = None
    """The header `credential` is sent in, `Authorization` when unset."""

    credential_query: str | None = None
    """The query parameter `credential` is sent as instead of a header, for a proxy that reads no other."""

    credential_scheme: str | None = None
    """The word sent before `credential` in its header, such as `Bearer`; unset sends the credential alone."""

    verify_tls: bool = True
    """Whether certificates are verified; turning this off is a per-connection decision."""

    timeout: Duration = Field(default=timedelta(seconds=30), gt=timedelta(0))
    """The timeout applied to each read of every request through this connection, unless a block says otherwise."""

    request_deadline: Duration = Field(default=timedelta(minutes=10), gt=timedelta(0))
    """The longest one request through this connection may take, start to last byte, unless a block says otherwise."""

    max_response: Size = Field(default=64 * 1024 * 1024, ge=1)
    """The most one response through this connection may decode to, unless a block says otherwise; a larger one is
    refused."""

    @field_validator("base_url")
    @classmethod
    def _base_url_holds_only_where(cls, url: str) -> str:
        """Refuse a user, a password, a query or a fragment, none of which a root needs."""
        split = urlsplit(url)
        if "@" in split.netloc or split.query or split.fragment:
            raise ValueError(BAD_BASE_URL.render())
        return url

    @field_validator("headers")
    @classmethod
    def _headers_can_be_sent(cls, headers: dict[str, str]) -> dict[str, str]:
        """Reject a header that cannot be sent, without saying what it held."""
        for name, value in headers.items():
            if HEADER_NAME.fullmatch(name) is None or HEADER_VALUE.fullmatch(value) is None:
                raise ValueError(BAD_HEADER.render())
            if carries_credential(name):
                raise ValueError(CREDENTIAL_HEADER_REFUSED.render(header=name))
        return headers

    @field_validator("credential")
    @classmethod
    def _credential_fits_a_header(cls, credential: SecretStr | None) -> SecretStr | None:
        """Read an empty credential as unset, and reject one that cannot be sent without saying what it held."""
        if credential is None or not credential.get_secret_value():
            return None
        if CREDENTIAL.fullmatch(credential.get_secret_value()) is None:
            raise ValueError(BAD_CREDENTIAL.render())
        return credential

    @field_validator("credential_header", "credential_scheme")
    @classmethod
    def _word_can_be_sent(cls, word: str | None) -> str | None:
        """Reject a header name or a scheme that is not an HTTP token."""
        if word is not None and HEADER_NAME.fullmatch(word) is None:
            raise ValueError(BAD_HEADER.render())
        return word

    @field_validator("credential_query")
    @classmethod
    def _query_name_can_be_sent(cls, name: str | None) -> str | None:
        """Reject a name a query parameter cannot be sent under unchanged."""
        if name is not None and QUERY_NAME.fullmatch(name) is None:
            raise ValueError(BAD_HEADER.render())
        return name

    @model_validator(mode="after")
    def _credential_goes_in_one_place(self) -> Self:
        """Refuse a credential told to go in two places, and a plain header spelling the name it is sent in."""
        if self.credential_query is not None and (self.credential_header or self.credential_scheme):
            raise ValueError(CREDENTIAL_TWO_PLACES.render())
        for name in self.headers:
            if name.lower() == (self.credential_header or DEFAULT_CREDENTIAL_HEADER).lower():
                raise ValueError(CREDENTIAL_HEADER_REFUSED.render(header=name))
        return self


def settings_of(config: BaseModel) -> ClimateConnectionConfig:
    """Read a connection's config as this kind's own model, whichever model the caller held."""
    if isinstance(config, ClimateConnectionConfig):
        return config
    return ClimateConnectionConfig.model_validate(config.model_dump())


def authorize(client: httpx2.AsyncClient, config: ClimateConnectionConfig) -> httpx2.AsyncClient:
    """Put the connection's headers and its credential on a client."""
    client.headers.update(config.headers)
    if config.credential is None:
        return client
    secret = config.credential.get_secret_value()
    if config.credential_query is not None:
        client.event_hooks = {
            "request": [*client.event_hooks["request"], _parameter_on_origin(config, config.credential_query, secret)],
            "response": client.event_hooks["response"],
        }
        return client
    scheme = f"{config.credential_scheme} " if config.credential_scheme else ""
    client.headers[config.credential_header or DEFAULT_CREDENTIAL_HEADER] = f"{scheme}{secret}"
    return client


def _parameter_on_origin(
    config: ClimateConnectionConfig, name: str, value: str
) -> Callable[[httpx2.Request], Awaitable[None]]:
    """A request hook setting a query parameter on the connection's origin and taking it off anywhere else."""
    base = httpx2.URL(config.base_url)

    async def hook(request: httpx2.Request) -> None:
        if (request.url.scheme, request.url.host, request.url.port) == (base.scheme, base.host, base.port):
            request.url = request.url.copy_set_param(name, value)
        else:
            request.url = request.url.copy_remove_param(name)

    return hook


def _held(settings: ClimateConnectionConfig) -> set[str]:
    """Every spelling of the credential a report may quote, a URL's among them."""
    held = secrets_of(settings)
    if settings.credential is not None:
        secret = settings.credential.get_secret_value()
        held |= {quote(secret, safe=""), quote(secret), quote_plus(secret)}
    return held


def build_client(
    config: ClimateConnectionConfig, transport: httpx2.AsyncBaseTransport | None = None
) -> httpx2.AsyncClient:
    """Build a client bound to the connection's URL, headers, credential, TLS setting and timeout."""
    client = httpx2.AsyncClient(
        base_url=config.base_url,
        verify=config.verify_tls,
        timeout=config.timeout.total_seconds(),
        transport=transport,
    )
    return authorize(client, config)


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
    return bounded(authorize(ctx.http(ref), config), config)


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

        A read-only instance is healthy, and the report says that it refuses every write. A credential
        the service or a proxy quotes back does not reach the report.
        """
        held: set[str] = set()
        try:
            settings = settings_of(config)
            held = _held(settings)
            async with bounded(build_client(settings, self._transport), settings) as client:
                health = await client.request("GET", HEALTH_PATH)
                if health.is_error:
                    detail = f"GET {HEALTH_PATH} answered {health.status_code}: {remote_words(health)}"
                    return HealthReport(healthy=False, detail=CONNECTION_UNREACHABLE.render(detail=scrub(detail, held)))
                status = str(_object(health).get("status") or "")
                info = await client.request("GET", INFO_PATH)
                about = _object(info) if not info.is_error else {}
        except Exception as error:  # noqa: BLE001 - a health check reports its verdict, it never raises
            detail = scrub(str(error), held) or type(error).__name__
            return HealthReport(healthy=False, detail=CONNECTION_UNREACHABLE.render(detail=detail))
        version = scrub(str(about["app_version"]), held) if about.get("app_version") else None
        details: list[str] = []
        if status != HEALTHY:
            details.append(CONNECTION_UNHEALTHY.render(status=scrub(status, held) or "without a status"))
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
