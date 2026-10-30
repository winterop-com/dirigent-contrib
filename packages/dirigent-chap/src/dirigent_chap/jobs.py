"""Following one Chap job: its status, its log on failure, its cancellation, and its result.

Every job-backed block submits through its own endpoint and then shares this: the status at
``/v1/jobs/{id}`` is what decides, and a result helper is only asked once that status says
``SUCCESS``, because a helper does not answer a failed job with a clean refusal.
"""

from datetime import timedelta
from typing import Any, ClassVar, Final

import httpx2
from pydantic import BaseModel, JsonValue

from dirigent_chap.connection import client_for
from dirigent_chap.messages import JOB_FAILED, JOB_NOT_SUBMITTED, JOB_RUNNING, JOB_UNKNOWN, JOB_UNSETTLED
from dirigent_chap.web import call_json, json_of, mapping, refuse
from dirigent_common import BlockModel
from dirigent_plugin import (
    BlockFailure,
    ConnectionRef,
    ErrorClass,
    Operator,
    ProbeResult,
    ProbeStatus,
    RemoteHandle,
    StepContext,
)

#: The status a job that finished well reports.
SUCCESS: Final = "SUCCESS"

#: The statuses a job never leaves, other than success.
FAILED: Final = frozenset({"FAILURE", "REVOKED"})

#: How often a Chap job is probed when the step does not say.
JOB_POLL: Final = timedelta(seconds=30)

#: How much of a failed job's log is written into the run.
LOG_TAIL: Final = 4000


def job_path(job_id: str, tail: str = "") -> str:
    """The path of one job, or of one of its sub-resources."""
    return f"/v1/jobs/{job_id}{tail}"


async def read_job(client: httpx2.AsyncClient, job_id: str) -> dict[str, JsonValue] | None:
    """Read a job's description, or None when Chap does not know it."""
    path = job_path(job_id)
    response = await client.get(path)
    if response.status_code == 404:
        return None
    if response.is_error:
        raise refuse(response, f"GET {path}")
    return mapping(json_of(response, f"GET {path}"))


async def log_tail(client: httpx2.AsyncClient, job_id: str) -> str:
    """The end of a job's captured log, or nothing when Chap has none to give."""
    try:
        response = await client.get(job_path(job_id, "/logs"))
    except httpx2.TransportError:
        return ""
    if response.is_error:
        return ""
    try:
        body: Any = response.json()
    except ValueError:
        body = response.text
    text = body if isinstance(body, str) else str(body)
    return text[-LOG_TAIL:]


async def observe(client: httpx2.AsyncClient, job_id: str, ctx: StepContext) -> ProbeResult:
    """Map a job's status onto a probe result, writing the log of a failed job into the run.

    ``PENDING`` and ``STARTED`` are running, and so is any status Chap adds later: only the
    statuses it documents as final end the step.
    """
    job = await read_job(client, job_id)
    if job is None:
        return ProbeResult(status=ProbeStatus.GONE, message=JOB_UNKNOWN.render(job=job_id))
    status = str(job.get("status") or "")
    if status == SUCCESS:
        return ProbeResult(status=ProbeStatus.SUCCEEDED, message=JOB_RUNNING.render(job=job_id, status=status))
    if status in FAILED:
        error = str(job.get("error") or "no error was recorded")
        tail = await log_tail(client, job_id)
        if tail:
            ctx.log.warning("the Chap job's log ends", job=job_id, log=tail)
        return ProbeResult(status=ProbeStatus.FAILED, message=JOB_FAILED.render(job=job_id, status=status, error=error))
    return ProbeResult(status=ProbeStatus.RUNNING, message=JOB_RUNNING.render(job=job_id, status=status or "unknown"))


async def result_of(client: httpx2.AsyncClient, job_id: str, helper: str) -> JsonValue:
    """Ask a result helper for a job's result, once the job's own status says it succeeded."""
    job = await read_job(client, job_id)
    status = str(job.get("status") or "") if job is not None else "unknown"
    if status != SUCCESS:
        raise BlockFailure(JOB_UNSETTLED, error_class=ErrorClass.TRANSIENT, job=job_id, status=status)
    return await call_json(client, "GET", job_path(job_id, f"/{helper}"))


async def cancel_job(client: httpx2.AsyncClient, job_id: str) -> bool:
    """Revoke a job; False when Chap would not, because it had finished or was never known."""
    response = await client.post(job_path(job_id, "/cancel"))
    return not response.is_error


class ChapJobConfig(BlockModel):
    """What every job-backed Chap block's config begins with."""

    connection: ConnectionRef
    """The code of the chap connection naming the server."""


class ChapJobOperator[ConfigT: ChapJobConfig, OutputT: BaseModel](Operator[ConfigT, OutputT]):
    """An operator that submits one Chap job, and probes and cancels it the same way as every other."""

    #: The result helper under ``/v1/jobs/{id}/`` the finished job's result is read from.
    result_helper: ClassVar[str]

    def handle(self, job_id: str, **meta: str) -> RemoteHandle:
        """The handle that follows a submitted job."""
        return RemoteHandle(block_id=self.spec.id, ref=job_id, meta=meta)

    async def probe(self, handle: RemoteHandle, config: ConfigT, ctx: StepContext) -> ProbeResult:
        """Read the job's status once."""
        async with client_for(ctx, config.connection) as client:
            return await observe(client, handle.ref, ctx)

    async def result(self, handle: RemoteHandle, config: ConfigT, ctx: StepContext) -> JsonValue:
        """Read the finished job's result from this block's helper."""
        async with client_for(ctx, config.connection) as client:
            return await result_of(client, handle.ref, self.result_helper)

    async def cancel(self, handle: RemoteHandle, config: ConfigT, ctx: StepContext) -> bool:
        """Ask Chap to revoke the job."""
        async with client_for(ctx, config.connection) as client:
            return await cancel_job(client, handle.ref)


async def submit(
    client: httpx2.AsyncClient, path: str, body: dict[str, JsonValue], **kwargs: Any
) -> dict[str, JsonValue]:
    """Post a job's request and read the answer as an object."""
    return mapping(await call_json(client, "POST", path, json=body, **kwargs))


def job_id_of(answer: dict[str, JsonValue], where: str) -> str:
    """The job id a submission answered with, refusing an answer without one."""
    job_id = answer.get("id")
    if not isinstance(job_id, str) or not job_id:
        raise BlockFailure(JOB_NOT_SUBMITTED, error_class=ErrorClass.UNKNOWN, where=where)
    return job_id
