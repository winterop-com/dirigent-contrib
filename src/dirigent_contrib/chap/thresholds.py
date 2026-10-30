"""``chap.thresholds``: the endemic channel for a stored dataset, one threshold line per strategy parameter."""

from typing import ClassVar, Final

from pydantic import BaseModel, Field, JsonValue

from dirigent_common import BlockModel
from dirigent_contrib.chap.bodies import PassThroughConfig, body_of
from dirigent_contrib.chap.connection import client_for
from dirigent_contrib.chap.web import call_json, mapping
from dirigent_plugin import Operator, OperatorSpec, StepContext

THRESHOLDS_PATH: Final = "/v1/analytics/thresholds"


class ChapThresholdsConfig(PassThroughConfig):
    """What one threshold computation asks of Chap; any undeclared key is sent to Chap as written."""

    dataset_id: int
    """The stored dataset whose historical `disease_cases` the thresholds are computed from."""

    period_ids: list[str] = Field(min_length=1)
    """The periods to compute thresholds for, at the dataset's own frequency, such as `2024-01`."""

    locations: list[str] | None = None
    """The locations to restrict the answer to; every location in the dataset when unset."""

    params: dict[str, JsonValue]
    """The strategy and its parameters as Chap spells them: `type` selects the strategy (`seasonal`,
    `percentile`, or any `GET /v1/analytics/thresholds/strategies` lists), and a line parameter such as
    `stdMultiplier` or `quantile` takes one value or a list, one threshold line each."""


class ChapThresholdsOutput(BlockModel):
    """The threshold lines Chap computed, as it answers with them."""

    params: JsonValue = None
    """The parameters the thresholds were computed with, Chap's defaults applied."""

    lines: list[JsonValue] = Field(default_factory=list[JsonValue])
    """The line parameter of each threshold line, in the order of every entry's `values`."""

    entries: list[JsonValue] = Field(default_factory=list[JsonValue])
    """One entry per requested period and location: `{period, location, values}`, a value null where no
    threshold could be computed."""


class ChapThresholdsOperator(Operator[ChapThresholdsConfig, ChapThresholdsOutput]):
    """Computes outbreak thresholds for a dataset, answered at once."""

    spec = OperatorSpec(
        id="chap.thresholds", summary="Compute the endemic channel for a Chap dataset.", idempotent=True
    )
    config_model: ClassVar[type[BaseModel]] = ChapThresholdsConfig
    output_model: ClassVar[type[BaseModel]] = ChapThresholdsOutput

    async def execute(self, config: ChapThresholdsConfig, ctx: StepContext) -> ChapThresholdsOutput:
        """Compute the thresholds once.

        A dataset with no `disease_cases` (404) and periods at another frequency or no complete
        baseline year (400) are refusals, and are never retried.
        """
        body = body_of(config, "dataset_id", "period_ids", "locations", "params")
        async with client_for(ctx, config.connection) as client:
            answer = mapping(await call_json(client, "POST", THRESHOLDS_PATH, json=body))
        lines = answer.get("lines")
        entries = answer.get("entries")
        return ChapThresholdsOutput(
            params=answer.get("params"),
            lines=list(lines) if isinstance(lines, list) else [],
            entries=list(entries) if isinstance(entries, list) else [],
        )
