"""``chap.backtest.run``: train and evaluate a configured model on a stored dataset, as a Chap job."""

from typing import ClassVar, Final

from pydantic import BaseModel, Field, JsonValue

from dirigent_common import BlockModel
from dirigent_contrib.chap.bodies import PassThroughConfig, body_of
from dirigent_contrib.chap.connection import client_for
from dirigent_contrib.chap.jobs import JOB_POLL, ChapJobConfig, ChapJobOperator, job_id_of, submit
from dirigent_contrib.chap.web import mapping
from dirigent_plugin import OperatorSpec, RemoteHandle, StepContext

CREATE_BACKTEST_PATH: Final = "/v1/analytics/create-backtest"


class ChapBacktestRunConfig(ChapJobConfig, PassThroughConfig):
    """What one backtest asks of Chap.

    A parameter left unset takes the server's saved default, and any undeclared key is sent to
    Chap as written.
    """

    name: str = Field(min_length=1)
    """The name the backtest is stored under."""

    model_id: int | str
    """The configured model to evaluate, by its id or its name."""

    dataset_id: int
    """The stored dataset to evaluate it on, as `chap.dataset.import` outputs it."""

    n_periods: int | None = Field(default=None, ge=1)
    """How many periods ahead each split forecasts; Chap's default is 3."""

    n_splits: int | None = Field(default=None, ge=1)
    """How many train/test splits are evaluated; Chap's default is 7."""

    stride: int | None = Field(default=None, ge=1)
    """How many periods one split moves on from the last; Chap's default is 1."""

    n_retrain: int | None = Field(default=None, ge=1)
    """How many times the model is retrained across the splits; Chap's default is 1."""

    future_weather_provider: str | None = None
    """Where the forecast window's weather comes from; Chap's default is `climatology`."""

    target_column: str | None = None
    """The dataset column the model forecasts; Chap's default is `disease_cases`."""


class ChapBacktestRunOutput(BlockModel):
    """The backtest the finished job stored, as Chap describes it."""

    backtest_id: int | None = None
    """The stored backtest's id."""

    job_id: str
    """The evaluation job Chap ran."""

    aggregate_metrics: JsonValue = None
    """The backtest's `aggregateMetrics`, lifted out of it."""

    backtest: JsonValue = None
    """The backtest exactly as Chap's evaluation result answers with it."""


class ChapBacktestRunOperator(ChapJobOperator[ChapBacktestRunConfig, ChapBacktestRunOutput]):
    """Submits a backtest and waits for its evaluation job."""

    spec = OperatorSpec(
        id="chap.backtest.run", summary="Run a Chap backtest on a stored dataset.", default_poll=JOB_POLL
    )
    config_model: ClassVar[type[BaseModel]] = ChapBacktestRunConfig
    output_model: ClassVar[type[BaseModel]] = ChapBacktestRunOutput
    result_helper: ClassVar[str] = "evaluation_result"

    async def execute(self, config: ChapBacktestRunConfig, ctx: StepContext) -> RemoteHandle:
        """Submit the backtest and hand back its job."""
        body = body_of(
            config,
            "name",
            "model_id",
            "dataset_id",
            "n_periods",
            "n_splits",
            "stride",
            "n_retrain",
            "future_weather_provider",
            "target_column",
        )
        async with client_for(ctx, config.connection) as client:
            answer = await submit(client, CREATE_BACKTEST_PATH, body)
        job_id = job_id_of(answer, f"POST {CREATE_BACKTEST_PATH}")
        ctx.log.info("backtest submitted", job=job_id)
        return self.handle(job_id)

    async def fetch(
        self, handle: RemoteHandle, config: ChapBacktestRunConfig, ctx: StepContext
    ) -> ChapBacktestRunOutput:
        """Read the stored backtest off the finished job."""
        backtest = await self.result(handle, config, ctx)
        described = mapping(backtest)
        backtest_id = described.get("id")
        return ChapBacktestRunOutput(
            backtest_id=backtest_id if isinstance(backtest_id, int) else None,
            job_id=handle.ref,
            aggregate_metrics=described.get("aggregateMetrics"),
            backtest=backtest,
        )
