"""``climate.job.run`` runs a process graph as an openEO batch job; ``climate.job.result`` downloads what it made."""

import re
from datetime import timedelta
from typing import ClassVar, Final
from urllib.parse import unquote

import httpx2
from pydantic import BaseModel, Field, JsonValue

from dirigent_common import BlockModel, Size
from dirigent_contrib.climate.connection import client_for
from dirigent_contrib.climate.graphs import GraphConfig
from dirigent_contrib.climate.messages import (
    JOB_ASSET_OUTSIDE,
    JOB_FAILED,
    JOB_NO_ASSET,
    JOB_NOT_SUBMITTED,
    JOB_RUNNING,
    JOB_UNKNOWN,
)
from dirigent_contrib.climate.payload import Payload, capture
from dirigent_contrib.climate.web import call, call_json, json_of, mapping, refuse
from dirigent_contrib.limits import BoundedClient
from dirigent_contrib.paths import PLAIN_ID_PATTERN, is_plain_id, segment
from dirigent_plugin import (
    BlockFailure,
    ConnectionRef,
    ErrorClass,
    Operator,
    OperatorSpec,
    ProbeResult,
    ProbeStatus,
    RemoteHandle,
    StepContext,
)

JOBS_PATH: Final = "/jobs"

#: The statuses of a job that is still on its way.
WAITING: Final = frozenset({"created", "queued", "running"})

#: The status of a job whose results are ready.
FINISHED: Final = "finished"

#: The statuses a job never leaves, other than finishing.
ENDED: Final = frozenset({"error", "canceled"})

#: How often a batch job is probed when the step does not say.
BATCH_POLL: Final = timedelta(seconds=15)

#: How much of a failed job's log is written into the run.
LOG_TAIL: Final = 4000

#: The asset a finished export's payload is published under.
RESULT_ASSET: Final = "result"


def job_path(job_id: str, tail: str = "") -> str:
    """The path of one batch job, or of one of its sub-resources."""
    return f"{JOBS_PATH}/{segment(job_id)}{tail}"


class ClimateJobRunConfig(GraphConfig):
    """The graph one batch job executes."""

    title: str | None = None
    """The title the job is listed under on the service."""


class ClimateJobRunOutput(BlockModel):
    """The finished job and the results it published."""

    job_id: str
    """The batch job's id, which `climate.job.result` and `climate.export` name."""

    assets: list[str]
    """The names of the assets the results carry, such as `result` and `manifest`."""

    results: JsonValue = None
    """The results' STAC item, exactly as the service answers with it."""


class ClimateJobRunOperator(Operator[ClimateJobRunConfig, ClimateJobRunOutput]):
    """Creates a batch job, starts it, and waits for it to finish."""

    spec = OperatorSpec(
        id="climate.job.run", summary="Run an openEO batch job on the open climate service.", default_poll=BATCH_POLL
    )
    config_model: ClassVar[type[BaseModel]] = ClimateJobRunConfig
    output_model: ClassVar[type[BaseModel]] = ClimateJobRunOutput

    async def execute(self, config: ClimateJobRunConfig, ctx: StepContext) -> RemoteHandle:
        """Create the job, queue it, and hand back the handle that follows it."""
        body: dict[str, JsonValue] = {"process": config.process()}
        if config.title is not None:
            body["title"] = config.title
        async with client_for(ctx, config.connection) as client:
            created = await call(client, "POST", JOBS_PATH, json=body)
            job_id = _created_id(created)
            await call(client, "POST", job_path(job_id, "/results"))
        ctx.log.info("batch job queued", job=job_id)
        return RemoteHandle(block_id=self.spec.id, ref=job_id)

    async def probe(self, handle: RemoteHandle, config: ClimateJobRunConfig, ctx: StepContext) -> ProbeResult:
        """Read the job's status once, writing the log of a failed job into the run."""
        path = job_path(handle.ref)
        async with client_for(ctx, config.connection) as client:
            response = await client.request("GET", path)
        if response.status_code == 404:
            return ProbeResult(status=ProbeStatus.GONE, message=JOB_UNKNOWN.render(job=handle.ref))
        if response.is_error:
            raise refuse(response, f"GET {path}")
        job = mapping(json_of(response, f"GET {path}"))
        status = str(job.get("status") or "")
        if status == FINISHED:
            return ProbeResult(status=ProbeStatus.SUCCEEDED, message=JOB_RUNNING.render(job=handle.ref, status=status))
        if status in ENDED:
            logs = str(job.get("logs") or "")
            if logs:
                ctx.log.warning("the batch job's log ends", job=handle.ref, log=logs[-LOG_TAIL:])
            detail = logs.strip().splitlines()[-1] if logs.strip() else "the job left no log"
            return ProbeResult(
                status=ProbeStatus.FAILED, message=JOB_FAILED.render(job=handle.ref, status=status, detail=detail)
            )
        return ProbeResult(
            status=ProbeStatus.RUNNING, message=JOB_RUNNING.render(job=handle.ref, status=status or "unknown")
        )

    async def fetch(self, handle: RemoteHandle, config: ClimateJobRunConfig, ctx: StepContext) -> ClimateJobRunOutput:
        """Read the finished job's results item."""
        async with client_for(ctx, config.connection) as client:
            results = await call_json(client, "GET", job_path(handle.ref, "/results"))
        assets = mapping(mapping(results).get("assets"))
        return ClimateJobRunOutput(job_id=handle.ref, assets=sorted(assets), results=results)

    async def cancel(self, handle: RemoteHandle, config: ClimateJobRunConfig, ctx: StepContext) -> bool:
        """Ask the service to stop the job."""
        async with (
            client_for(ctx, config.connection) as client,
            client.stream("DELETE", job_path(handle.ref, "/results")) as response,
        ):
            return not response.is_error


def _created_id(response: httpx2.Response) -> str:
    """The id a job was created under: in the body, or else in the ``Location`` it was answered with.

    An answer whose id is not one plain id is refused, as one without an id is.
    """
    try:
        body: JsonValue = response.json()
    except ValueError:
        body = None
    job_id = mapping(body).get("id")
    if not isinstance(job_id, str) or not job_id:
        job_id = response.headers.get("location", "").rstrip("/").rsplit("/", 1)[-1]
    if not is_plain_id(job_id):
        raise BlockFailure(JOB_NOT_SUBMITTED, error_class=ErrorClass.UNKNOWN, where=f"POST {JOBS_PATH}")
    return job_id


def _has_parent_segment(path: str) -> bool:
    """Whether a URL path climbs, under any number of percent-encodings, a backslash or a ``;`` parameter."""
    while (decoded := unquote(path)) != path:
        path = decoded
    return any(segment.split(";", 1)[0] == ".." for segment in re.split(r"[/\\]", path))


def _under_base_url(client: BoundedClient, target: str) -> bool:
    """Whether the URL the client resolves a target to stays on its ``base_url``, under that URL's path."""
    try:
        url = client.build_request("GET", target).url
    except httpx2.InvalidURL:
        return False
    base = client.base_url
    if (url.scheme, url.host, url.port) != (base.scheme, base.host, base.port) or url.userinfo:
        return False
    path = url.raw_path.partition(b"?")[0]
    return path.startswith(base.raw_path.partition(b"?")[0]) and not _has_parent_segment(path.decode("ascii"))


class ClimateJobResultConfig(BlockModel):
    """Which finished job's payload to download."""

    connection: ConnectionRef
    """The code of the climate connection naming the instance."""

    job_id: str = Field(pattern=PLAIN_ID_PATTERN)
    """The finished batch job, as `climate.job.run` outputs it."""

    asset: str = RESULT_ASSET
    """The asset of the job's results to download; `result` is the payload a workflow saved, such as
    the DHIS2 dataValueSet `aggregate_to_dhis2_json` writes."""

    max_response: Size | None = None
    """The most the downloaded asset may decode to; the connection's `max_response` when unset."""


class ClimateJobResultOutput(Payload):
    """The downloaded payload."""

    job_id: str
    """The job the payload belongs to."""

    asset: str
    """The asset that was downloaded."""

    href: str
    """Where the service serves the asset."""


class ClimateJobResultOperator(Operator[ClimateJobResultConfig, ClimateJobResultOutput]):
    """Downloads one asset of a finished batch job into the run's storage."""

    spec = OperatorSpec(
        id="climate.job.result", summary="Download a finished open climate service job's payload.", idempotent=True
    )
    config_model: ClassVar[type[BaseModel]] = ClimateJobResultConfig
    output_model: ClassVar[type[BaseModel]] = ClimateJobResultOutput

    async def execute(self, config: ClimateJobResultConfig, ctx: StepContext) -> ClimateJobResultOutput:
        """Find the asset in the job's results item, and stream it to storage.

        An asset's ``href`` is read against the connection's ``base_url``, so an instance served
        under a path prefix is reached under it. One that resolves anywhere else is refused
        before any request is sent for it.
        """
        async with client_for(ctx, config.connection) as client:
            results = await call_json(client, "GET", job_path(config.job_id, "/results"))
            assets = mapping(mapping(results).get("assets"))
            asset = mapping(assets.get(config.asset))
            href = asset.get("href")
            if not isinstance(href, str) or not href:
                raise BlockFailure(
                    JOB_NO_ASSET,
                    error_class=ErrorClass.REJECTED,
                    job=config.job_id,
                    asset=config.asset,
                    available=", ".join(sorted(assets)) or "none",
                )
            target = href if "://" in href else href.lstrip("/")
            if not _under_base_url(client, target):
                raise BlockFailure(
                    JOB_ASSET_OUTSIDE, error_class=ErrorClass.REJECTED, job=config.job_id, asset=config.asset
                )
            async with client.stream("GET", target) as response:
                limit = client.max_response if config.max_response is None else config.max_response
                payload = await capture(ctx, response, config.asset, f"GET {href}", limit)
        ctx.log.info("downloaded", job=config.job_id, asset=config.asset, size_bytes=payload.size_bytes)
        return ClimateJobResultOutput(**payload.model_dump(), job_id=config.job_id, asset=config.asset, href=href)
