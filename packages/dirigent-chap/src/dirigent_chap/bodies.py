"""A Chap request body, built from a step's config: its declared fields renamed, the rest passed through.

Chap owns the shape of what it is sent and changes it often, so a block declares only the
fields it reads and lets the rest through: a key a step writes that the block does not
declare is sent to Chap exactly as written, in Chap's own camelCase spelling.
"""

import csv
import io
import math
from typing import Final

from pydantic import ConfigDict, Field, JsonValue, model_validator

from dirigent_chap.jobs import ChapJobConfig
from dirigent_chap.messages import CSV_BAD_VALUE, CSV_MISSING_COLUMN, OBSERVATIONS_MISSING
from dirigent_plugin import BlockFailure, ErrorClass

#: The columns of a Chap CSV that are not features.
PERIOD_COLUMN: Final = "time_period"
LOCATION_COLUMN: Final = "location"


class PassThroughConfig(ChapJobConfig):
    """A config whose undeclared keys are sent to Chap as written."""

    model_config = ConfigDict(use_attribute_docstrings=True, extra="allow")


def camel(name: str) -> str:
    """Spell a snake_case field the way Chap's JSON spells it."""
    head, *rest = name.split("_")
    return head + "".join(part.title() for part in rest)


def body_of(config: PassThroughConfig, *declared: str) -> dict[str, JsonValue]:
    """Build the body: each declared field that is set, renamed to camelCase, then every passed-through key.

    A declared field left at None is left out, so Chap applies its own default to it.
    """
    body: dict[str, JsonValue] = {}
    for name in declared:
        value = getattr(config, name)
        if value is not None:
            body[camel(name)] = config.model_dump(mode="json", include={name})[name]
    body.update(config.model_extra or {})
    return body


class ObservationsConfig(PassThroughConfig):
    """The observations a step sends: rows as Chap spells them, a Chap CSV, or both."""

    provided_data: list[dict[str, JsonValue]] = Field(default_factory=list[dict[str, JsonValue]])
    """Observations as Chap spells them: `{period, orgUnit, value, featureName}`, one per row."""

    csv: str | None = None
    """A wide Chap CSV, the shape `aggregate_to_chap_csv` writes: `time_period`, `location`, and one
    column per feature. Each feature cell becomes one observation, sent beside `provided_data`."""

    @model_validator(mode="after")
    def _require_observations(self) -> "ObservationsConfig":
        """Refuse a step that sends no observations at all."""
        if not self.provided_data and not self.csv:
            raise ValueError(OBSERVATIONS_MISSING.render())
        return self

    def observations(self) -> list[JsonValue]:
        """Every observation the step sends: the rows as written, then the CSV's cells."""
        rows: list[JsonValue] = list(self.provided_data)
        if self.csv:
            rows.extend(csv_observations(self.csv))
        return rows


def csv_observations(text: str) -> list[JsonValue]:
    """Unfold a wide Chap CSV into one observation per feature cell.

    An empty cell is a missing value and is sent as null, which Chap reads as missing.
    """
    reader = csv.DictReader(io.StringIO(text))
    columns = reader.fieldnames or []
    for column in (PERIOD_COLUMN, LOCATION_COLUMN):
        if column not in columns:
            raise BlockFailure(CSV_MISSING_COLUMN, error_class=ErrorClass.REJECTED, column=column)
    features = [column for column in columns if column not in (PERIOD_COLUMN, LOCATION_COLUMN)]
    rows: list[JsonValue] = []
    for line, record in enumerate(reader, start=2):
        for feature in features:
            rows.append(
                {
                    "period": record[PERIOD_COLUMN],
                    "orgUnit": record[LOCATION_COLUMN],
                    "featureName": feature,
                    "value": _number(record.get(feature), feature, line),
                }
            )
    return rows


def _number(cell: str | None, column: str, line: int) -> float | None:
    """Read one CSV cell as a number, an empty one or a NaN as missing."""
    if cell is None or not cell.strip():
        return None
    try:
        number = float(cell)
    except ValueError as error:
        raise BlockFailure(
            CSV_BAD_VALUE, error_class=ErrorClass.REJECTED, column=column, line=line, value=cell
        ) from error
    return number if math.isfinite(number) else None
