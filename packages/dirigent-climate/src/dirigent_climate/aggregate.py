"""``climate.aggregate``: run a process graph synchronously, and keep what it answers with."""

from datetime import timedelta
from typing import ClassVar, Final

from pydantic import BaseModel, Field

from dirigent_climate.connection import client_for
from dirigent_climate.graphs import GraphConfig, Workflow
from dirigent_climate.payload import Payload, capture
from dirigent_common import Duration
from dirigent_plugin import Operator, OperatorSpec, StepContext

RESULT_PATH: Final = "/result"


class ClimateAggregateConfig(GraphConfig):
    """The graph one synchronous run executes, and how long it may take."""

    timeout: Duration = Field(default=timedelta(minutes=5), gt=timedelta(0))
    """How long the service may take to answer; an aggregation over a long range takes minutes."""


class ClimateAggregateOutput(Payload):
    """What the graph answered with."""

    workflow: Workflow | None = None
    """The built-in workflow that ran, or null for a graph the step wrote out."""


class ClimateAggregateOperator(Operator[ClimateAggregateConfig, ClimateAggregateOutput]):
    """Runs a process graph on the service and keeps the payload it answers with."""

    spec = OperatorSpec(
        id="climate.aggregate",
        summary="Aggregate a climate dataset to org units with the open climate service.",
        idempotent=True,
    )
    config_model: ClassVar[type[BaseModel]] = ClimateAggregateConfig
    output_model: ClassVar[type[BaseModel]] = ClimateAggregateOutput

    async def execute(self, config: ClimateAggregateConfig, ctx: StepContext) -> ClimateAggregateOutput:
        """Run the graph once and stream its answer to storage."""
        where = f"POST {RESULT_PATH}"
        async with (
            client_for(ctx, config.connection) as client,
            client.stream(
                "POST", RESULT_PATH, json={"process": config.process()}, timeout=config.timeout.total_seconds()
            ) as response,
        ):
            payload = await capture(ctx, response, "aggregate", where)
        ctx.log.info("aggregated", workflow=config.workflow, size_bytes=payload.size_bytes, uri=payload.uri)
        return ClimateAggregateOutput(**payload.model_dump(), workflow=config.workflow)
