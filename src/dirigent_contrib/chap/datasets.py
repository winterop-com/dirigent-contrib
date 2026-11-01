"""``chap.dataset.import``: store observations as a named Chap dataset, validated first and imported as a job."""

import asyncio
import json
from typing import ClassVar, Final, Literal

from pydantic import BaseModel, Field, JsonValue

from dirigent_common import BlockModel
from dirigent_contrib.chap.bodies import ObservationsConfig, body_of
from dirigent_contrib.chap.connection import client_for
from dirigent_contrib.chap.jobs import JOB_POLL, ChapJobConfig, ChapJobOperator, job_id_of, submit
from dirigent_contrib.chap.messages import DATASET_NOT_VALIDATED, DATASET_REJECTED
from dirigent_contrib.chap.web import mapping
from dirigent_plugin import BlockFailure, ErrorClass, OperatorSpec, RemoteHandle, StepContext

MAKE_DATASET_PATH: Final = "/v1/analytics/make-dataset"

#: How many rejected rows an output or a refusal carries.
REJECTED_KEPT: Final = 100

#: How many bytes of rejected rows an output, a log or a handle carries.
REJECTED_BYTES: Final = 64 * 1024

#: How many rejected rows a refusal names in its message.
REJECTED_NAMED: Final = 3

#: The handle keys carrying what the synchronous validation said, for the output.
IMPORTED: Final = "imported_count"
REJECTED: Final = "rejected"
REJECTED_COUNT: Final = "rejected_count"


class ChapDatasetImportConfig(ChapJobConfig, ObservationsConfig):
    """What one dataset import sends.

    Any undeclared key, such as `dataSources` or `maskedRanges`, is sent to Chap as written.
    """

    name: str = Field(min_length=1)
    """The name the dataset is stored under."""

    geojson: dict[str, JsonValue]
    """The org units as a GeoJSON FeatureCollection, each feature's `id` the location its observations name."""

    data_to_be_fetched: list[dict[str, JsonValue]] = Field(default_factory=list[dict[str, JsonValue]])
    """Features Chap fetches itself, as Chap spells them: `{featureName, dataSourceName}`."""

    dry_run: bool = False
    """Whether Chap only validates the observations and reports the rejections, importing nothing."""

    on_rejected: Literal["fail", "warn"] = "warn"
    """What a rejected observation does: `warn` imports the rest and logs the rejections, `fail` imports
    nothing and fails the step."""


class ChapDatasetImportOutput(BlockModel):
    """What the import stored, and what Chap refused to."""

    dataset_id: int | None = None
    """The stored dataset's id, which a backtest names; null for a dry run."""

    job_id: str | None = None
    """The import job Chap ran; null for a dry run."""

    imported_count: int
    """How many locations Chap accepted."""

    rejected_count: int
    """How many observations Chap rejected."""

    rejected: list[JsonValue] = Field(default_factory=list[JsonValue])
    """The first hundred rejections, up to 64KB of them, in Chap's own words."""

    dry_run: bool = False
    """Whether this was a validation only."""


class ChapDatasetImportOperator(ChapJobOperator[ChapDatasetImportConfig, ChapDatasetImportOutput]):
    """Validates observations against Chap, then imports them as a dataset and waits for the job."""

    spec = OperatorSpec(
        id="chap.dataset.import", summary="Import observations as a Chap dataset.", default_poll=JOB_POLL
    )
    config_model: ClassVar[type[BaseModel]] = ChapDatasetImportConfig
    output_model: ClassVar[type[BaseModel]] = ChapDatasetImportOutput
    result_helper: ClassVar[str] = "database_result"

    async def execute(
        self, config: ChapDatasetImportConfig, ctx: StepContext
    ) -> ChapDatasetImportOutput | RemoteHandle:
        """Validate, and either answer the dry run or submit the import and hand back its job.

        Under ``on_rejected: fail`` the observations are validated with a dry run first, so a
        rejection fails the step before Chap has imported any of the rows it did accept.
        """
        body = body_of(config, "name", "geojson", "data_to_be_fetched")
        body["providedData"] = await asyncio.to_thread(config.observations)
        async with client_for(ctx, config.connection) as client:
            if config.dry_run or config.on_rejected == "fail":
                checked = await submit(client, MAKE_DATASET_PATH, body, params={"dryRun": "true"})
                if not isinstance(checked.get(REJECTED), list):
                    raise BlockFailure(
                        DATASET_NOT_VALIDATED, error_class=ErrorClass.UNKNOWN, where=f"POST {MAKE_DATASET_PATH}"
                    )
                rejected = _rejections(checked)
                if rejected and config.on_rejected == "fail":
                    raise BlockFailure(
                        DATASET_REJECTED,
                        error_class=ErrorClass.REJECTED,
                        count=len(rejected),
                        detail="; ".join(json.dumps(row) for row in _kept(rejected)[:REJECTED_NAMED]),
                    )
                if config.dry_run:
                    return _output(checked, dry_run=True)
            answer = await submit(client, MAKE_DATASET_PATH, body)
        rejected = _rejections(answer)
        kept = _kept(rejected)
        for row in kept:
            ctx.log.warning("Chap rejected an observation", rejection=row)
        job_id = job_id_of(answer, f"POST {MAKE_DATASET_PATH}")
        ctx.log.info("dataset import submitted", job=job_id)
        return self.handle(
            job_id,
            **{
                IMPORTED: str(answer.get("importedCount") or 0),
                REJECTED_COUNT: str(len(rejected)),
                REJECTED: json.dumps(kept),
            },
        )

    async def fetch(
        self, handle: RemoteHandle, config: ChapDatasetImportConfig, ctx: StepContext
    ) -> ChapDatasetImportOutput:
        """Read the stored dataset's id off the finished job."""
        stored = mapping(await self.result(handle, config, ctx))
        dataset_id = stored.get("id")
        rejected: list[JsonValue] = json.loads(handle.meta.get(REJECTED, "[]"))
        return ChapDatasetImportOutput(
            dataset_id=dataset_id if isinstance(dataset_id, int) else None,
            job_id=handle.ref,
            imported_count=int(handle.meta.get(IMPORTED, "0")),
            rejected_count=int(handle.meta.get(REJECTED_COUNT, "0")),
            rejected=rejected,
        )


def _rejections(answer: dict[str, JsonValue]) -> list[JsonValue]:
    """The rows an import summary says Chap rejected."""
    rejected = answer.get("rejected")
    return list(rejected) if isinstance(rejected, list) else []


def _kept(rejected: list[JsonValue]) -> list[JsonValue]:
    """The rejected rows that are carried on: the first hundred, as far as they fit their bytes."""
    kept: list[JsonValue] = []
    size = 0
    for row in rejected[:REJECTED_KEPT]:
        size += len(json.dumps(row))
        if size > REJECTED_BYTES:
            break
        kept.append(row)
    return kept


def _output(answer: dict[str, JsonValue], *, dry_run: bool) -> ChapDatasetImportOutput:
    """Read an import summary as the step's output."""
    rejected = _rejections(answer)
    imported = answer.get("importedCount")
    return ChapDatasetImportOutput(
        imported_count=imported if isinstance(imported, int) else 0,
        rejected_count=len(rejected),
        rejected=_kept(rejected),
        dry_run=dry_run,
    )
