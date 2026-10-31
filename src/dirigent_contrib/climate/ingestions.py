"""``climate.ingest`` and ``climate.sync``: bring a managed dataset in or forward, as a background job.

Both are asked to respond asynchronously and answer with the job to follow in ``Location``;
from there they are one job record, probed and cancelled the same way.
"""

from datetime import timedelta
from typing import ClassVar, Final

import httpx2
from pydantic import BaseModel, Field, JsonValue

from dirigent_common import BlockModel
from dirigent_contrib.climate.connection import client_for
from dirigent_contrib.climate.messages import (
    JOB_FAILED,
    JOB_NOT_FINISHED_INLINE,
    JOB_NOT_SUBMITTED,
    JOB_NOT_SYNCABLE,
    JOB_RUNNING,
    JOB_UNKNOWN,
)
from dirigent_contrib.climate.web import QUOTED, call, json_of, mapping, refuse
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

INGESTIONS_PATH: Final = "/ingestions"

#: Where every ingestion and sync job is followed.
INGESTION_JOBS_PATH: Final = "/ingestions/jobs"

#: What asks the service to queue the work and answer at once.
RESPOND_ASYNC: Final = {"Prefer": "respond-async"}

#: The statuses of a job still on its way.
WAITING: Final = frozenset({"accepted", "running", "retrying"})

#: The status of a job that finished well.
SUCCESSFUL: Final = "successful"

#: The status of a sync that wrote nothing because the source cannot serve a declared release yet.
WAITING_FOR_SOURCE: Final = "waiting_for_source"

#: The statuses an answer holding the work itself, rather than a job, may end a step with.
INLINE_SUCCESS: Final = frozenset({"completed", "up_to_date", WAITING_FOR_SOURCE})

#: The status of a sync of a static dataset, which no retry changes.
NOT_SYNCABLE: Final = "not_syncable"

#: How often an ingestion or sync is probed when the step does not say.
INGESTION_POLL: Final = timedelta(seconds=30)


def sync_path(dataset_id: str) -> str:
    """Where one managed dataset is synced."""
    return f"/sync/{segment(dataset_id)}"


def ingestion_job_path(job_id: str) -> str:
    """Where one ingestion or sync job is followed."""
    return f"{INGESTION_JOBS_PATH}/{segment(job_id)}"


class ClimateIngestionOutput(BlockModel):
    """What the finished job recorded."""

    job_id: str | None = None
    """The job the service ran; null when it did the work inline and answered with it."""

    status: str
    """The job's final status or the inline answer's, and `waiting_for_source` whenever a sync says so."""

    finished_at: str | None = None
    """When the job finished, in the service's own timestamp."""

    result: JsonValue = None
    """The job's result, or the inline answer, exactly as the service gives it."""


class ClimateIngestionConfig(BlockModel):
    """What every ingestion-shaped block's config begins with."""

    connection: ConnectionRef
    """The code of the climate connection naming the instance."""

    dataset_id: str = Field(pattern=PLAIN_ID_PATTERN)
    """The dataset the job brings in or forward."""


class ClimateIngestionOperator[ConfigT: ClimateIngestionConfig](Operator[ConfigT, ClimateIngestionOutput]):
    """An operator that queues one ingestion-shaped job and follows its record."""

    output_model: ClassVar[type[BaseModel]] = ClimateIngestionOutput

    def follow(self, response: httpx2.Response, where: str, ctx: StepContext) -> ClimateIngestionOutput | RemoteHandle:
        """The handle that follows a queued job, or the output of work the service says it finished inline."""
        if response.status_code != 202:
            answer = mapping(json_of(response, where))
            status = answer.get("status")
            if status == NOT_SYNCABLE:
                raise BlockFailure(JOB_NOT_SYNCABLE, error_class=ErrorClass.REJECTED, where=where)
            if not response.is_success or not isinstance(status, str) or status not in INLINE_SUCCESS:
                raise BlockFailure(
                    JOB_NOT_FINISHED_INLINE,
                    error_class=ErrorClass.UNKNOWN,
                    where=where,
                    status=response.status_code,
                    said=str(status)[:QUOTED],
                )
            return ClimateIngestionOutput(status=status, result=answer)
        location = response.headers.get("location", "").rstrip("/")
        job_id = location.rsplit("/", 1)[-1] if location else ""
        if not job_id:
            job_id = str(mapping(json_of(response, where)).get("ingestion_id") or "")
        if not is_plain_id(job_id):
            raise BlockFailure(JOB_NOT_SUBMITTED, error_class=ErrorClass.UNKNOWN, where=where)
        ctx.log.info("job queued", job=job_id)
        return RemoteHandle(block_id=self.spec.id, ref=job_id)

    async def read(self, handle: RemoteHandle, config: ConfigT, ctx: StepContext) -> dict[str, JsonValue] | None:
        """Read the job's record, or None when the service no longer knows it."""
        path = ingestion_job_path(handle.ref)
        async with client_for(ctx, config.connection) as client:
            response = await client.request("GET", path)
        if response.status_code == 404:
            return None
        if response.is_error:
            raise refuse(response, f"GET {path}")
        return mapping(json_of(response, f"GET {path}"))

    async def probe(self, handle: RemoteHandle, config: ConfigT, ctx: StepContext) -> ProbeResult:
        """Read the job's status and progress once."""
        record = await self.read(handle, config, ctx)
        if record is None:
            return ProbeResult(status=ProbeStatus.GONE, message=JOB_UNKNOWN.render(job=handle.ref))
        status = str(record.get("status") or "")
        if status == SUCCESSFUL:
            return ProbeResult(status=ProbeStatus.SUCCEEDED, message=JOB_RUNNING.render(job=handle.ref, status=status))
        if status in WAITING or not status:
            progress = mapping(record.get("progress"))
            percent = progress.get("percent")
            fraction = min(max(float(percent) / 100, 0.0), 1.0) if isinstance(percent, int | float) else None
            said = progress.get("message")
            message = str(said) if said else JOB_RUNNING.render(job=handle.ref, status=status or "unknown")
            return ProbeResult(status=ProbeStatus.RUNNING, message=message, progress=fraction)
        error = mapping(record.get("error"))
        detail = str(error.get("message") or "no error was recorded")
        return ProbeResult(
            status=ProbeStatus.FAILED, message=JOB_FAILED.render(job=handle.ref, status=status, detail=detail)
        )

    async def fetch(self, handle: RemoteHandle, config: ConfigT, ctx: StepContext) -> ClimateIngestionOutput:
        """Read the finished job's record, holding a sync's own word in its result to what it means."""
        record = await self.read(handle, config, ctx)
        if record is None:
            raise BlockFailure(JOB_UNKNOWN, error_class=ErrorClass.TRANSIENT, job=handle.ref)
        said = mapping(record.get("result")).get("status")
        if said == NOT_SYNCABLE:
            where = f"GET {ingestion_job_path(handle.ref)}"
            raise BlockFailure(JOB_NOT_SYNCABLE, error_class=ErrorClass.REJECTED, where=where)
        finished = record.get("finishedAt")
        return ClimateIngestionOutput(
            job_id=handle.ref,
            status=WAITING_FOR_SOURCE if said == WAITING_FOR_SOURCE else str(record.get("status") or ""),
            finished_at=str(finished) if finished else None,
            result=record.get("result"),
        )

    async def cancel(self, handle: RemoteHandle, config: ConfigT, ctx: StepContext) -> bool:
        """Ask the service to stop the job; it stops at its next checkpoint."""
        async with (
            client_for(ctx, config.connection) as client,
            client.stream("DELETE", ingestion_job_path(handle.ref)) as response,
        ):
            return not response.is_error


class ClimateIngestConfig(ClimateIngestionConfig):
    """What one ingestion brings in, from the dataset template `dataset_id` names."""

    start: str | None = None
    """The first time step to bring in, as an ISO date; the source's own start when unset."""

    end: str | None = None
    """The last time step to bring in, as an ISO date; the latest available when unset."""

    overwrite: bool = False
    """Whether time steps already held are fetched again and replaced."""

    publish: bool = True
    """Whether the dataset is published once it is in."""


class ClimateIngestOperator(ClimateIngestionOperator[ClimateIngestConfig]):
    """Creates or updates a managed dataset over the instance's configured extent."""

    spec = OperatorSpec(
        id="climate.ingest", summary="Ingest a dataset into the open climate service.", default_poll=INGESTION_POLL
    )
    config_model: ClassVar[type[BaseModel]] = ClimateIngestConfig

    async def execute(self, config: ClimateIngestConfig, ctx: StepContext) -> ClimateIngestionOutput | RemoteHandle:
        """Queue the ingestion and hand back the job that follows it."""
        body = config.model_dump(mode="json", include={"dataset_id", "start", "end", "overwrite", "publish"})
        async with client_for(ctx, config.connection) as client:
            response = await call(client, "POST", INGESTIONS_PATH, json=body, headers=RESPOND_ASYNC)
        return self.follow(response, f"POST {INGESTIONS_PATH}", ctx)


class ClimateSyncConfig(ClimateIngestionConfig):
    """What one sync brings forward, from the managed dataset's latest time step."""

    end: str | None = None
    """The last time step to bring in, as an ISO date; the latest available when unset."""

    publish: bool = True
    """Whether the dataset is published once it is synced."""


class ClimateSyncOperator(ClimateIngestionOperator[ClimateSyncConfig]):
    """Brings a managed dataset forward from its latest time step."""

    spec = OperatorSpec(
        id="climate.sync", summary="Sync a managed open climate service dataset forward.", default_poll=INGESTION_POLL
    )
    config_model: ClassVar[type[BaseModel]] = ClimateSyncConfig

    async def execute(self, config: ClimateSyncConfig, ctx: StepContext) -> ClimateIngestionOutput | RemoteHandle:
        """Queue the sync and hand back the job that follows it."""
        path = sync_path(config.dataset_id)
        body = config.model_dump(mode="json", include={"end", "publish"})
        async with client_for(ctx, config.connection) as client:
            response = await call(client, "POST", path, json=body, headers=RESPOND_ASYNC)
        return self.follow(response, f"POST {path}", ctx)
