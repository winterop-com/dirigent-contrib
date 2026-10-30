"""The open climate service pack: the ``climate`` connection kind and the blocks for one instance."""

from collections.abc import Sequence
from importlib.resources import files
from importlib.resources.abc import Traversable

from dirigent_climate.aggregate import ClimateAggregateConfig, ClimateAggregateOperator, ClimateAggregateOutput
from dirigent_climate.batch import (
    ClimateJobResultConfig,
    ClimateJobResultOperator,
    ClimateJobResultOutput,
    ClimateJobRunConfig,
    ClimateJobRunOperator,
    ClimateJobRunOutput,
)
from dirigent_climate.connection import ClimateConnectionConfig, ClimateConnectionKind, build_client, client_for
from dirigent_climate.datasets import ClimateDatasetsListConfig, ClimateDatasetsListOperator, ClimateDatasetsListOutput
from dirigent_climate.exports import ClimateExportConfig, ClimateExportOperator, ClimateExportOutput
from dirigent_climate.ingestions import (
    ClimateIngestConfig,
    ClimateIngestionOutput,
    ClimateIngestOperator,
    ClimateSyncConfig,
    ClimateSyncOperator,
)
from dirigent_climate.messages import CLIMATE
from dirigent_climate.payload import Payload
from dirigent_plugin import Contribution, extension

#: The directory the pack's example shelves live in, inside this distribution.
SHELVES_DIRECTORY = "shelves"


class ClimatePlugin:
    """The plugin object the host discovers under the dirigent.plugins.v1 entry-point group."""

    @extension
    def contribute(self) -> Contribution:
        """Contribute the climate blocks and the ``climate`` connection kind they are configured from."""
        return Contribution(
            operators=[
                ClimateDatasetsListOperator(),
                ClimateAggregateOperator(),
                ClimateJobRunOperator(),
                ClimateJobResultOperator(),
                ClimateExportOperator(),
                ClimateIngestOperator(),
                ClimateSyncOperator(),
            ],
            connection_kinds=[ClimateConnectionKind()],
            labels=[CLIMATE],
        )

    @extension
    def examples(self) -> Sequence[Traversable]:
        """Contribute the example shelves this distribution carries."""
        return [files(__package__ or "dirigent_climate") / SHELVES_DIRECTORY]


plugin = ClimatePlugin()

__all__ = [
    "SHELVES_DIRECTORY",
    "ClimateAggregateConfig",
    "ClimateAggregateOperator",
    "ClimateAggregateOutput",
    "ClimateConnectionConfig",
    "ClimateConnectionKind",
    "ClimateDatasetsListConfig",
    "ClimateDatasetsListOperator",
    "ClimateDatasetsListOutput",
    "ClimateExportConfig",
    "ClimateExportOperator",
    "ClimateExportOutput",
    "ClimateIngestConfig",
    "ClimateIngestOperator",
    "ClimateIngestionOutput",
    "ClimateJobResultConfig",
    "ClimateJobResultOperator",
    "ClimateJobResultOutput",
    "ClimateJobRunConfig",
    "ClimateJobRunOperator",
    "ClimateJobRunOutput",
    "ClimatePlugin",
    "ClimateSyncConfig",
    "ClimateSyncOperator",
    "Payload",
    "build_client",
    "client_for",
    "plugin",
]
