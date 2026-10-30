"""The process graph a step runs: one of the service's built-in workflows, or a graph written out whole."""

from typing import Final, Literal

from pydantic import JsonValue, model_validator

from dirigent_climate.messages import GRAPH_MISSING, GRAPH_ONE_OF, GRAPH_STRAY
from dirigent_common import BlockModel
from dirigent_plugin import ConnectionRef

#: The built-in workflow that saves a DHIS2 dataValueSet through a named export.
DHIS2_JSON: Final = "aggregate_to_dhis2_json"

#: The built-in workflow that writes a wide Chap CSV.
CHAP_CSV: Final = "aggregate_to_chap_csv"

#: The built-in workflow that saves nothing and leaves the format to the caller.
BY_FEATURES: Final = "aggregate_by_features"

type Workflow = Literal["aggregate_to_dhis2_json", "aggregate_to_chap_csv", "aggregate_by_features"]

type Method = Literal["mean", "min", "max", "sum", "median"]

#: The node a workflow is called from in the graph this builds.
NODE: Final = "agg"


class GraphConfig(BlockModel):
    """A step that runs a process graph: a built-in workflow and its arguments, or a graph of its own."""

    connection: ConnectionRef
    """The code of the climate connection naming the instance."""

    workflow: Workflow | None = None
    """The built-in workflow to run: `aggregate_to_dhis2_json`, `aggregate_to_chap_csv` or
    `aggregate_by_features`."""

    dataset_id: str | None = None
    """The published dataset the workflow aggregates, as `climate.datasets.list` lists it."""

    start: str | None = None
    """The first day the workflow loads, as an ISO date."""

    end: str | None = None
    """The last day the workflow loads, as an ISO date."""

    geometries: dict[str, JsonValue] | None = None
    """The org units as a GeoJSON FeatureCollection, each feature's `id` the org unit's uid."""

    method: Method = "mean"
    """How the pixels inside each org unit are reduced to one value: mean, min, max, sum or median."""

    export: str | None = None
    """The named DHIS2 export the instance configures, which `aggregate_to_dhis2_json` saves through."""

    period_type: str | None = None
    """The period type each time step is written as, for `aggregate_to_chap_csv`: day, week, month,
    quarter or year; the service's default is month."""

    process_graph: dict[str, JsonValue] | None = None
    """A whole openEO process graph, node id to node, run in place of a workflow."""

    @model_validator(mode="after")
    def _one_graph(self) -> "GraphConfig":
        """Refuse a step that names no graph, or two, or a workflow without what it needs."""
        if (self.workflow is None) == (self.process_graph is None):
            raise ValueError(GRAPH_ONE_OF.render())
        if self.workflow is None:
            return self
        for field in ("dataset_id", "start", "end", "geometries"):
            if getattr(self, field) is None:
                raise ValueError(GRAPH_MISSING.render(workflow=self.workflow, field=field))
        if self.workflow == DHIS2_JSON and self.export is None:
            raise ValueError(GRAPH_MISSING.render(workflow=self.workflow, field="export"))
        if self.workflow != DHIS2_JSON and self.export is not None:
            raise ValueError(GRAPH_STRAY.render(field="export", owner=DHIS2_JSON, workflow=self.workflow))
        if self.workflow != CHAP_CSV and self.period_type is not None:
            raise ValueError(GRAPH_STRAY.render(field="period_type", owner=CHAP_CSV, workflow=self.workflow))
        return self

    def graph(self) -> dict[str, JsonValue]:
        """The process graph this step runs, as the service's ``process`` reads it."""
        if self.process_graph is not None:
            return self.process_graph
        arguments: dict[str, JsonValue] = {
            "dataset_id": self.dataset_id,
            "temporal_extent": [self.start, self.end],
            "geometries": self.geometries,
            "method": self.method,
        }
        if self.export is not None:
            arguments["export"] = self.export
        if self.period_type is not None:
            arguments["period_type"] = self.period_type
        return {NODE: {"process_id": self.workflow, "arguments": arguments, "result": True}}

    def process(self) -> dict[str, JsonValue]:
        """The ``process`` object a request carries the graph in."""
        return {"process_graph": self.graph()}
