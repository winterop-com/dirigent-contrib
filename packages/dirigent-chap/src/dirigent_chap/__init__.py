"""The Chap pack: the ``chap`` connection kind and the blocks for one Chap server."""

from collections.abc import Sequence
from importlib.resources import files
from importlib.resources.abc import Traversable

from dirigent_chap.backtests import ChapBacktestRunConfig, ChapBacktestRunOperator, ChapBacktestRunOutput
from dirigent_chap.configured_models import ChapModelsListConfig, ChapModelsListOperator, ChapModelsListOutput
from dirigent_chap.connection import ChapConnectionConfig, ChapConnectionKind, build_client, client_for
from dirigent_chap.datasets import ChapDatasetImportConfig, ChapDatasetImportOperator, ChapDatasetImportOutput
from dirigent_chap.messages import CHAP
from dirigent_chap.predictions import (
    ChapPredictionReadConfig,
    ChapPredictionReadOperator,
    ChapPredictionReadOutput,
    ChapPredictionRunConfig,
    ChapPredictionRunOperator,
    ChapPredictionRunOutput,
)
from dirigent_chap.thresholds import ChapThresholdsConfig, ChapThresholdsOperator, ChapThresholdsOutput
from dirigent_plugin import Contribution, extension

#: The directory the pack's example shelves live in, inside this distribution.
SHELVES_DIRECTORY = "shelves"


class ChapPlugin:
    """The plugin object the host discovers under the dirigent.plugins.v1 entry-point group."""

    @extension
    def contribute(self) -> Contribution:
        """Contribute the Chap blocks and the ``chap`` connection kind they are configured from."""
        return Contribution(
            operators=[
                ChapDatasetImportOperator(),
                ChapBacktestRunOperator(),
                ChapPredictionRunOperator(),
                ChapPredictionReadOperator(),
                ChapModelsListOperator(),
                ChapThresholdsOperator(),
            ],
            connection_kinds=[ChapConnectionKind()],
            labels=[CHAP],
        )

    @extension
    def examples(self) -> Sequence[Traversable]:
        """Contribute the example shelves this distribution carries."""
        return [files(__package__ or "dirigent_chap") / SHELVES_DIRECTORY]


plugin = ChapPlugin()

__all__ = [
    "SHELVES_DIRECTORY",
    "ChapBacktestRunConfig",
    "ChapBacktestRunOperator",
    "ChapBacktestRunOutput",
    "ChapConnectionConfig",
    "ChapConnectionKind",
    "ChapDatasetImportConfig",
    "ChapDatasetImportOperator",
    "ChapDatasetImportOutput",
    "ChapModelsListConfig",
    "ChapModelsListOperator",
    "ChapModelsListOutput",
    "ChapPlugin",
    "ChapPredictionReadConfig",
    "ChapPredictionReadOperator",
    "ChapPredictionReadOutput",
    "ChapPredictionRunConfig",
    "ChapPredictionRunOperator",
    "ChapPredictionRunOutput",
    "ChapThresholdsConfig",
    "ChapThresholdsOperator",
    "ChapThresholdsOutput",
    "build_client",
    "client_for",
    "plugin",
]
