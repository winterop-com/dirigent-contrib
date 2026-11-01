"""Following one Chap job: its status, its log on failure, its cancellation, and its result.

Every job-backed block submits through its own endpoint and then shares this: the status at
``/v1/jobs/{id}`` is what decides, and a result helper is only asked once that status says
``SUCCESS``, because a helper does not answer a failed job with a clean refusal.

A released Chap answers ``/v1/jobs/{id}`` with the bare status, a JSON string such as
``"SUCCESS"``; Chap's master answers with the whole job, the status under ``status`` and a
failure's reason under ``error``. Both are read.
"""

import json
from datetime import timedelta
from typing import Any, ClassVar, Final

import httpx2
from pydantic import BaseModel, JsonValue

from dirigent_common import BlockModel
from dirigent_contrib.chap.connection import client_for
from dirigent_contrib.chap.messages import (
    JOB_FAILED,
    JOB_NOT_SUBMITTED,
    JOB_RUNNING,
    JOB_UNKNOWN,
    JOB_UNREADABLE,
    JOB_UNRECOGNISED,
    JOB_UNSETTLED,
)
from dirigent_contrib.chap.web import QUOTED, call_json, json_of, mapping, refuse
from dirigent_contrib.limits import BoundedClient
from dirigent_contrib.paths import is_plain_id, segment
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

#: The statuses a job never leaves, other than success: Celery's final states.
FAILED: Final = frozenset({"FAILURE", "REVOKED", "REJECTED"})

#: The statuses of a job still queued or running: Celery's unfinished states.
RUNNING: Final = frozenset({"PENDING", "RECEIVED", "STARTED", "RETRY"})

#: How often a Chap job is probed when the step does not say.
JOB_POLL: Final = timedelta(seconds=30)

#: How much of a failed job's log is written into the run.
LOG_TAIL: Final = 4000


def job_path(job_id: str, tail: str = "") -> str:
    """The path of one job, or of one of its sub-resources."""
    return f"/v1/jobs/{segment(job_id)}{tail}"


async def read_job(client: BoundedClient, job_id: str) -> dict[str, JsonValue] | None:
    """Read a job as an object whose ``status`` is a word in capitals, or None when Chap does not know it.

    A bare status string becomes an object holding only that status. Any other answer, or a job
    without a status, is refused rather than read as one still running.
    """
    path = job_path(job_id)
    where = f"GET {path}"
    response = await client.request("GET", path)
    if response.status_code == 404:
        return None
    if response.is_error:
        raise refuse(response, where)
    answer = json_of(response, where)
    job = {"status": answer} if isinstance(answer, str) else mapping(answer)
    status = job.get("status")
    if not isinstance(status, str) or not status.strip():
        quoted = json.dumps(answer)[:QUOTED]
        raise BlockFailure(JOB_UNREADABLE, error_class=ErrorClass.REJECTED, where=where, answer=quoted)
    return {**job, "status": status.strip().upper()}


async def log_tail(client: BoundedClient, job_id: str) -> str:
    """The end of a job's captured log, or nothing when Chap has none to give within the connection's limits."""
    try:
        response = await client.request("GET", job_path(job_id, "/logs"))
    except (httpx2.TransportError, BlockFailure):
        return ""
    if response.is_error:
        return ""
    try:
        body: Any = response.json()
    except ValueError:
        body = response.text
    text = body if isinstance(body, str) else str(body)
    return text[-LOG_TAIL:]


async def observe(client: BoundedClient, job_id: str, ctx: StepContext) -> ProbeResult:
    """Map a job's status onto a probe result, writing the log of a failed job into the run.

    A status that is neither running nor final is refused, so a step never waits on a word it
    cannot read.
    """
    job = await read_job(client, job_id)
    if job is None:
        return ProbeResult(status=ProbeStatus.GONE, message=JOB_UNKNOWN.render(job=job_id))
    status = str(job["status"])
    if status in RUNNING:
        return ProbeResult(status=ProbeStatus.RUNNING, message=JOB_RUNNING.render(job=job_id, status=status))
    if status == SUCCESS:
        return ProbeResult(status=ProbeStatus.SUCCEEDED, message=JOB_RUNNING.render(job=job_id, status=status))
    if status in FAILED:
        error = str(job.get("error") or "no error was recorded")
        tail = await log_tail(client, job_id)
        if tail:
            ctx.log.warning("the Chap job's log ends", job=job_id, log=tail)
        return ProbeResult(status=ProbeStatus.FAILED, message=JOB_FAILED.render(job=job_id, status=status, error=error))
    raise BlockFailure(JOB_UNRECOGNISED, error_class=ErrorClass.REJECTED, job=job_id, status=status)


async def result_of(client: BoundedClient, job_id: str, helper: str) -> JsonValue:
    """Ask a result helper for a job's result, once the job's own status says it succeeded."""
    job = await read_job(client, job_id)
    status = str(job.get("status") or "") if job is not None else "unknown"
    if status != SUCCESS:
        raise BlockFailure(JOB_UNSETTLED, error_class=ErrorClass.TRANSIENT, job=job_id, status=status)
    return await call_json(client, "GET", job_path(job_id, f"/{helper}"))


async def cancel_job(client: BoundedClient, job_id: str) -> bool:
    """Revoke a job; False when Chap would not, because it had finished or was never known."""
    async with client.stream("POST", job_path(job_id, "/cancel")) as response:
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


async def submit(client: BoundedClient, path: str, body: dict[str, JsonValue], **kwargs: Any) -> dict[str, JsonValue]:
    """Post a job's request and read the answer as an object."""
    return mapping(await call_json(client, "POST", path, json=body, **kwargs))


def job_id_of(answer: dict[str, JsonValue], where: str) -> str:
    """The job id a submission answered with, refusing an answer without one or with anything but a plain id."""
    job_id = answer.get("id")
    if not isinstance(job_id, str) or not is_plain_id(job_id):
        raise BlockFailure(JOB_NOT_SUBMITTED, error_class=ErrorClass.UNKNOWN, where=where)
    return job_id
