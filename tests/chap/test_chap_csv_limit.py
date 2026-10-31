"""A CSV of a few KB unfolds to columns times rows, so what it may unfold to is held before anything is built."""

import threading
import tracemalloc
from typing import Any

import pytest
from pydantic import ValidationError

from dirigent_contrib.chap import bodies
from dirigent_contrib.chap.bodies import csv_observations
from dirigent_contrib.chap.datasets import ChapDatasetImportOperator
from dirigent_contrib.chap.predictions import ChapPredictionRunOperator
from dirigent_plugin import AnyOperator, BlockFailure, ErrorClass
from dirigent_testing import FakeContext, call_block
from tests.chap.chapserver import CONNECTION, ChapServer

MIB = 1024 * 1024
TOO_LARGE = "chap.csv.too_large"

GEOJSON: dict[str, Any] = {"type": "FeatureCollection", "features": []}


def _wide(features: int, rows: int, row: str) -> str:
    """A CSV of that many feature columns and rows, each row written the same."""
    columns = ",".join(f"f{number}" for number in range(features))
    return f"time_period,location,{columns}\n" + f"{row}\n" * rows


def _dataset(csv: str, **config: Any) -> dict[str, Any]:
    return {"connection": CONNECTION, "name": "d", "geojson": GEOJSON, "csv": csv, **config}


def _prediction(csv: str, **config: Any) -> dict[str, Any]:
    return {"connection": CONNECTION, "prediction_setup_id": 5, "name": "p", "geojson": GEOJSON, "csv": csv, **config}


async def test_short_rows_past_the_default_limit_send_nothing_at_little_cost(
    ctx: FakeContext, chap: ChapServer
) -> None:
    csv = _wide(2000, 300, "202501,OU1")
    assert len(csv) < 20 * 1024
    tracemalloc.start()
    try:
        with pytest.raises(BlockFailure) as refused:
            await call_block(ChapDatasetImportOperator(), _dataset(csv, on_rejected="fail"), ctx)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert refused.value.code == TOO_LARGE
    assert refused.value.error_class is ErrorClass.REJECTED
    assert "600000" in str(refused.value)
    assert chap.requests == []
    assert peak < 16 * MIB


async def test_rows_of_commas_past_the_limit_send_nothing(ctx: FakeContext, chap: ChapServer) -> None:
    csv = _wide(100, 100, "202501,OU1" + "," * 100)
    with pytest.raises(BlockFailure) as refused:
        await call_block(ChapDatasetImportOperator(), _dataset(csv, max_observations=9999), ctx)
    assert refused.value.code == TOO_LARGE
    assert chap.requests == []


async def test_a_forecast_is_held_to_the_same_limit(ctx: FakeContext, chap: ChapServer) -> None:
    csv = _wide(100, 100, "202501,OU1")
    with pytest.raises(BlockFailure) as refused:
        await call_block(ChapPredictionRunOperator(), _prediction(csv, max_observations=9999), ctx)
    assert refused.value.code == TOO_LARGE
    assert chap.requests == []


def test_exactly_the_limit_unfolds() -> None:
    assert len(csv_observations(_wide(10, 10, "202501,OU1,1"), 100)) == 100
    with pytest.raises(BlockFailure):
        csv_observations(_wide(10, 10, "202501,OU1,1"), 99)


def test_a_blank_line_is_not_a_row_when_counting() -> None:
    assert len(csv_observations("time_period,location,f\n\n202501,OU1,1\n\n", 1)) == 1


async def test_a_step_may_raise_the_limit_and_it_is_not_sent_to_chap(ctx: FakeContext, chap: ChapServer) -> None:
    chap.on("POST", "/v1/analytics/make-dataset", body={"id": "job-1", "importedCount": 1, "rejected": []})
    csv = _wide(10, 10, "202501,OU1,1")
    await call_block(ChapDatasetImportOperator(), _dataset(csv, max_observations=100), ctx)
    body = chap.body("POST", "/v1/analytics/make-dataset")
    assert len(body["providedData"]) == 100
    assert "max_observations" not in body
    assert "maxObservations" not in body


@pytest.mark.parametrize("value", [0, -1])
def test_a_limit_of_nothing_is_refused(value: int) -> None:
    with pytest.raises(ValidationError):
        ChapDatasetImportOperator.config_model.model_validate(_dataset("x", max_observations=value))


@pytest.mark.parametrize(
    ("block", "config", "route"),
    [
        pytest.param(ChapDatasetImportOperator(), _dataset, "/v1/analytics/make-dataset", id="dataset"),
        pytest.param(ChapPredictionRunOperator(), _prediction, "/v1/crud/prediction-setups/5/run", id="prediction"),
    ],
)
async def test_a_csv_is_unfolded_off_the_event_loop(
    block: AnyOperator,
    config: Any,
    route: str,
    ctx: FakeContext,
    chap: ChapServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    threads: list[threading.Thread] = []
    unfold = bodies.csv_observations

    def recording(*arguments: Any) -> list[Any]:
        threads.append(threading.current_thread())
        return unfold(*arguments)

    monkeypatch.setattr(bodies, "csv_observations", recording)
    chap.on("POST", route, body={"id": "job-1", "importedCount": 1, "rejected": []})
    await call_block(block, config("time_period,location,f\n202501,OU1,1\n"), ctx)
    assert threads
    assert threads[0] is not threading.current_thread()
