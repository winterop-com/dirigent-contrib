"""``chap.prediction.run`` forecasts from a saved prediction setup; ``chap.prediction.read`` reads its quantiles."""

import asyncio
from typing import ClassVar, Final

from pydantic import BaseModel, Field, JsonValue

from dirigent_common import BlockModel
from dirigent_contrib.chap.bodies import ObservationsConfig, body_of
from dirigent_contrib.chap.connection import client_for
from dirigent_contrib.chap.jobs import JOB_POLL, ChapJobOperator, job_id_of, submit
from dirigent_contrib.chap.messages import NOT_A_LIST, PREDICTION_NOT_STORED
from dirigent_contrib.chap.web import call_json, mapping
from dirigent_plugin import BlockFailure, ConnectionRef, ErrorClass, Operator, OperatorSpec, RemoteHandle, StepContext


def run_path(prediction_setup_id: int) -> str:
    """Where a prediction setup is run."""
    return f"/v1/crud/prediction-setups/{prediction_setup_id}/run"


def entries_path(prediction_id: int) -> str:
    """Where a prediction's quantiles are read."""
    return f"/v1/analytics/prediction-entry/{prediction_id}"


#: The quantiles read when a step names none: the median and the 80% band around it.
DEFAULT_QUANTILES: Final = (0.1, 0.5, 0.9)


class ChapPredictionRunConfig(ObservationsConfig):
    """What one forecast from a saved setup sends.

    Any undeclared key, such as `type`, is sent to Chap as written.
    """

    prediction_setup_id: int
    """The saved prediction setup to forecast with, which fixes the model and its target."""

    name: str = Field(min_length=1)
    """The name the prediction is stored under."""

    geojson: dict[str, JsonValue]
    """The org units as a GeoJSON FeatureCollection, each feature's `id` the location its observations name."""

    n_periods: int | None = Field(default=None, ge=1)
    """How many periods ahead to forecast; Chap's default is 3."""


class ChapPredictionRunOutput(BlockModel):
    """The prediction the finished job stored, as Chap describes it."""

    prediction_id: int
    """The stored prediction's id, which `chap.prediction.read` names."""

    job_id: str
    """The forecast job Chap ran."""

    prediction: JsonValue = None
    """The prediction exactly as Chap's prediction result answers with it."""


class ChapPredictionRunOperator(ChapJobOperator[ChapPredictionRunConfig, ChapPredictionRunOutput]):
    """Runs a saved prediction setup on fresh observations and waits for the forecast job."""

    spec = OperatorSpec(id="chap.prediction.run", summary="Run a Chap prediction setup.", default_poll=JOB_POLL)
    config_model: ClassVar[type[BaseModel]] = ChapPredictionRunConfig
    output_model: ClassVar[type[BaseModel]] = ChapPredictionRunOutput
    result_helper: ClassVar[str] = "prediction_result"

    async def execute(self, config: ChapPredictionRunConfig, ctx: StepContext) -> RemoteHandle:
        """Submit the forecast and hand back its job.

        An unknown setup (404), an archived model (409) and observations Chap cannot use (422)
        are all refusals, and are never retried.
        """
        body = body_of(config, "name", "geojson", "n_periods")
        body["providedData"] = await asyncio.to_thread(config.observations)
        path = run_path(config.prediction_setup_id)
        async with client_for(ctx, config.connection) as client:
            answer = await submit(client, path, body)
        job_id = job_id_of(answer, f"POST {path}")
        ctx.log.info("prediction submitted", job=job_id)
        return self.handle(job_id)

    async def fetch(
        self, handle: RemoteHandle, config: ChapPredictionRunConfig, ctx: StepContext
    ) -> ChapPredictionRunOutput:
        """Read the stored prediction off the finished job, refusing a result with no integer id."""
        prediction = await self.result(handle, config, ctx)
        prediction_id = mapping(prediction).get("id")
        if not isinstance(prediction_id, int) or isinstance(prediction_id, bool):
            raise BlockFailure(PREDICTION_NOT_STORED, error_class=ErrorClass.UNKNOWN, job=handle.ref)
        return ChapPredictionRunOutput(
            prediction_id=prediction_id,
            job_id=handle.ref,
            prediction=prediction,
        )


class ChapPredictionReadConfig(BlockModel):
    """Which prediction to read, and at which quantiles."""

    connection: ConnectionRef
    """The code of the chap connection naming the server."""

    prediction_id: int
    """The stored prediction to read, as `chap.prediction.run` outputs it."""

    quantiles: list[float] = Field(default_factory=lambda: list(DEFAULT_QUANTILES), min_length=1)
    """The quantiles to read each forecast at, each between 0 and 1."""


class ChapPredictionReadOutput(BlockModel):
    """The prediction's quantiles, one entry per period, org unit and quantile."""

    entries: list[JsonValue]
    """The entries as Chap answers with them: `{period, orgUnit, quantile, value}`."""

    count: int
    """How many entries there are."""


class ChapPredictionReadOperator(Operator[ChapPredictionReadConfig, ChapPredictionReadOutput]):
    """Reads a stored prediction's forecasts at the quantiles a step asks for."""

    spec = OperatorSpec(id="chap.prediction.read", summary="Read a Chap prediction's quantiles.", idempotent=True)
    config_model: ClassVar[type[BaseModel]] = ChapPredictionReadConfig
    output_model: ClassVar[type[BaseModel]] = ChapPredictionReadOutput

    async def execute(self, config: ChapPredictionReadConfig, ctx: StepContext) -> ChapPredictionReadOutput:
        """Read the entries once."""
        path = entries_path(config.prediction_id)
        async with client_for(ctx, config.connection) as client:
            answer = await call_json(
                client,
                "GET",
                path,
                params=[("quantiles", str(quantile)) for quantile in config.quantiles],
            )
        if not isinstance(answer, list):
            raise BlockFailure(NOT_A_LIST, error_class=ErrorClass.UNKNOWN, where=f"GET {path}")
        return ChapPredictionReadOutput(entries=list(answer), count=len(answer))
