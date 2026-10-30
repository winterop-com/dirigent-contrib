"""``climate.datasets.list``: the datasets the service has published, which every other block names."""

from typing import ClassVar, Final

from pydantic import BaseModel, JsonValue

from dirigent_common import BlockModel
from dirigent_contrib.climate.connection import client_for
from dirigent_contrib.climate.web import call_json, mapping
from dirigent_plugin import ConnectionRef, Operator, OperatorSpec, StepContext

DATASETS_PATH: Final = "/datasets"


class ClimateDatasetsListConfig(BlockModel):
    """Which instance to list the datasets of."""

    connection: ConnectionRef
    """The code of the climate connection naming the instance."""


class ClimateDatasetsListOutput(BlockModel):
    """The published datasets, as the service describes them."""

    datasets: list[JsonValue]
    """Each dataset as the service answers with it: its `dataset_id`, `period_type`, `variable`, `extent`
    and the rest."""

    count: int
    """How many datasets there are."""


class ClimateDatasetsListOperator(Operator[ClimateDatasetsListConfig, ClimateDatasetsListOutput]):
    """Lists the published datasets."""

    spec = OperatorSpec(
        id="climate.datasets.list", summary="List the open climate service's datasets.", idempotent=True
    )
    config_model: ClassVar[type[BaseModel]] = ClimateDatasetsListConfig
    output_model: ClassVar[type[BaseModel]] = ClimateDatasetsListOutput

    async def execute(self, config: ClimateDatasetsListConfig, ctx: StepContext) -> ClimateDatasetsListOutput:
        """Read the list once, as JSON rather than the page a browser is served."""
        async with client_for(ctx, config.connection) as client:
            answer = await call_json(
                client, "GET", DATASETS_PATH, params={"f": "json"}, headers={"Accept": "application/json"}
            )
        items = mapping(answer).get("items")
        datasets = list(items) if isinstance(items, list) else []
        return ClimateDatasetsListOutput(datasets=datasets, count=len(datasets))
