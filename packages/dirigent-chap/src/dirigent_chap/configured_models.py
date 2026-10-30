"""``chap.models.list``: the models a Chap server has configured, which a backtest names."""

from typing import ClassVar

from pydantic import BaseModel, JsonValue

from dirigent_chap.connection import CONFIGURED_MODELS_PATH, client_for
from dirigent_chap.web import call_json
from dirigent_common import BlockModel
from dirigent_plugin import ConnectionRef, Operator, OperatorSpec, StepContext


class ChapModelsListConfig(BlockModel):
    """Which server to list the models of."""

    connection: ConnectionRef
    """The code of the chap connection naming the server."""


class ChapModelsListOutput(BlockModel):
    """The configured models, as Chap describes them."""

    models: list[JsonValue]
    """Each configured model as Chap answers with it: its `id`, `name`, `covariates`, `target` and the rest."""

    count: int
    """How many models there are."""


class ChapModelsListOperator(Operator[ChapModelsListConfig, ChapModelsListOutput]):
    """Lists the configured models."""

    spec = OperatorSpec(id="chap.models.list", summary="List the models a Chap server has configured.", idempotent=True)
    config_model: ClassVar[type[BaseModel]] = ChapModelsListConfig
    output_model: ClassVar[type[BaseModel]] = ChapModelsListOutput

    async def execute(self, config: ChapModelsListConfig, ctx: StepContext) -> ChapModelsListOutput:
        """Read the list once."""
        async with client_for(ctx, config.connection) as client:
            answer = await call_json(client, "GET", CONFIGURED_MODELS_PATH)
        models = list(answer) if isinstance(answer, list) else []
        return ChapModelsListOutput(models=models, count=len(models))
