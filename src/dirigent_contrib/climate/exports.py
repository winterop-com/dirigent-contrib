"""``climate.export``: deliver a finished job's saved export through the service's own DHIS2 connection."""

import hashlib
from datetime import timedelta
from typing import ClassVar, Final

from pydantic import BaseModel, Field, JsonValue

from dirigent_common import BlockModel
from dirigent_contrib.climate.connection import client_for
from dirigent_contrib.climate.messages import EXPORT_REJECTED, JOB_FAILED, JOB_NOT_SUBMITTED, JOB_RUNNING, JOB_UNKNOWN
from dirigent_contrib.climate.web import call_json, json_of, mapping, refuse
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

#: The statuses of a delivery still on its way.
WAITING: Final = frozenset({"accepted", "running", "retrying"})

#: The status of a delivery that ran to the end, whatever its target made of it.
SUCCESSFUL: Final = "successful"

#: The outcome of a delivery the target refused.
REJECTED_OUTCOME: Final = "rejected"

#: How often a delivery is probed when the step does not say.
DELIVERY_POLL: Final = timedelta(seconds=15)

#: The handle keys the probe and the fetch read back.
EXPORT_ID: Final = "export_id"
REUSED: Final = "reused"
DRY_RUN: Final = "dry_run"


def export_path(export_id: str) -> str:
    """Where a named export is delivered."""
    return f"/exports/{segment(export_id)}"


def delivery_path(export_id: str, delivery_job_id: str) -> str:
    """Where one delivery is followed."""
    return f"{export_path(export_id)}/jobs/{segment(delivery_job_id)}"


def idempotency_key(ctx: StepContext) -> str:
    """The key one attempt delivers under, the same every time that attempt is executed.

    It is derived from the run, the step, the fan-out item and the attempt, so a worker that
    re-executes an attempt after a crash reuses the delivery the first execution queued, and
    a retry, which is a new attempt, queues a delivery of its own.
    """
    item = str(ctx.run_item_id) if ctx.run_item_id is not None else ""
    seed = f"dirigent:{ctx.run_id}:{ctx.step}:{item}:{ctx.attempt}"
    return hashlib.sha256(seed.encode()).hexdigest()


class ClimateExportConfig(BlockModel):
    """Which saved export to deliver, from which job."""

    connection: ConnectionRef
    """The code of the climate connection naming the instance."""

    export_id: str = Field(pattern=PLAIN_ID_PATTERN)
    """The named export the instance configures, the same one the job's workflow saved through."""

    job_id: str = Field(min_length=1)
    """The finished batch job whose saved payload is delivered, as `climate.job.run` outputs it."""

    dry_run: bool = False
    """Whether the target only validates the payload, writing nothing."""


class ClimateExportOutput(BlockModel):
    """What the delivery reported."""

    delivery_job_id: str
    """The delivery job the service ran."""

    export_id: str
    """The export that was delivered."""

    status: str
    """The delivery job's final status."""

    outcome: str | None = None
    """The report's outcome: success, partial, dry_run, cancelled or unknown."""

    reused: bool = False
    """Whether the service answered with a delivery this attempt had already queued."""

    dry_run: bool = False
    """Whether this was a validation only."""

    report: JsonValue = None
    """The export report exactly as the service answers with it: counts, conflicts and the target's task ids."""


class ClimateExportOperator(Operator[ClimateExportConfig, ClimateExportOutput]):
    """Queues one delivery of a saved export and waits for its report."""

    spec = OperatorSpec(
        id="climate.export", summary="Deliver an open climate service export to its target.", default_poll=DELIVERY_POLL
    )
    config_model: ClassVar[type[BaseModel]] = ClimateExportConfig
    output_model: ClassVar[type[BaseModel]] = ClimateExportOutput

    async def execute(self, config: ClimateExportConfig, ctx: StepContext) -> RemoteHandle:
        """Queue the delivery under this attempt's idempotency key."""
        path = export_path(config.export_id)
        async with client_for(ctx, config.connection) as client:
            accepted = mapping(
                await call_json(
                    client,
                    "POST",
                    path,
                    json={"job_id": config.job_id, "dry_run": config.dry_run},
                    headers={"Idempotency-Key": idempotency_key(ctx)},
                )
            )
        delivery = accepted.get("delivery_job_id")
        if not isinstance(delivery, str) or not is_plain_id(delivery):
            raise BlockFailure(JOB_NOT_SUBMITTED, error_class=ErrorClass.UNKNOWN, where=f"POST {path}")
        reused = accepted.get("reused") is True
        ctx.log.info("delivery queued", delivery=delivery, reused=reused)
        return RemoteHandle(
            block_id=self.spec.id,
            ref=delivery,
            meta={EXPORT_ID: config.export_id, REUSED: str(reused).lower(), DRY_RUN: str(config.dry_run).lower()},
        )

    async def probe(self, handle: RemoteHandle, config: ClimateExportConfig, ctx: StepContext) -> ProbeResult:
        """Read the delivery's status once."""
        delivery = await self._read(handle, config, ctx)
        if delivery is None:
            return ProbeResult(status=ProbeStatus.GONE, message=JOB_UNKNOWN.render(job=handle.ref))
        status = str(delivery.get("status") or "")
        if status == SUCCESSFUL:
            return ProbeResult(status=ProbeStatus.SUCCEEDED, message=JOB_RUNNING.render(job=handle.ref, status=status))
        if status in WAITING or not status:
            return ProbeResult(status=ProbeStatus.RUNNING, message=JOB_RUNNING.render(job=handle.ref, status=status))
        error = mapping(delivery.get("error"))
        detail = str(error.get("message") or "no error was recorded")
        return ProbeResult(
            status=ProbeStatus.FAILED, message=JOB_FAILED.render(job=handle.ref, status=status, detail=detail)
        )

    async def fetch(self, handle: RemoteHandle, config: ClimateExportConfig, ctx: StepContext) -> ClimateExportOutput:
        """Read the delivery's report; a report the target rejected fails the step as a refusal."""
        delivery = await self._read(handle, config, ctx)
        if delivery is None:
            raise BlockFailure(JOB_UNKNOWN, error_class=ErrorClass.TRANSIENT, job=handle.ref)
        report = mapping(delivery.get("report"))
        outcome = report.get("outcome")
        if outcome == REJECTED_OUTCOME:
            raise BlockFailure(
                EXPORT_REJECTED,
                error_class=ErrorClass.REJECTED,
                export=handle.meta.get(EXPORT_ID, config.export_id),
                detail=str(report.get("message") or f"{len(_conflicts(report))} conflicts"),
            )
        return ClimateExportOutput(
            delivery_job_id=handle.ref,
            export_id=handle.meta.get(EXPORT_ID, config.export_id),
            status=str(delivery.get("status") or ""),
            outcome=str(outcome) if outcome is not None else None,
            reused=handle.meta.get(REUSED) == "true",
            dry_run=handle.meta.get(DRY_RUN) == "true",
            report=delivery.get("report"),
        )

    async def _read(
        self, handle: RemoteHandle, config: ClimateExportConfig, ctx: StepContext
    ) -> dict[str, JsonValue] | None:
        """Read the delivery, or None when the service no longer knows it."""
        path = delivery_path(handle.meta.get(EXPORT_ID, config.export_id), handle.ref)
        async with client_for(ctx, config.connection) as client:
            response = await client.request("GET", path)
        if response.status_code == 404:
            return None
        if response.is_error:
            raise refuse(response, f"GET {path}")
        return mapping(json_of(response, f"GET {path}"))


def _conflicts(report: dict[str, JsonValue]) -> list[JsonValue]:
    """The conflicts a report names."""
    conflicts = report.get("conflicts")
    return list(conflicts) if isinstance(conflicts, list) else []
