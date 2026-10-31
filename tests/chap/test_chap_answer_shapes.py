"""An answer of another shape than a route documents is a failure, not a truthful empty result."""

import json
from typing import Any

import pytest

from dirigent_contrib.chap.configured_models import ChapModelsListOperator, ChapModelsListOutput
from dirigent_contrib.chap.datasets import ChapDatasetImportOperator, ChapDatasetImportOutput
from dirigent_contrib.chap.predictions import ChapPredictionReadOperator, ChapPredictionReadOutput
from dirigent_contrib.chap.thresholds import ChapThresholdsOperator, ChapThresholdsOutput
from dirigent_plugin import AnyOperator, BlockFailure, ErrorClass, RemoteHandle
from dirigent_testing import FakeContext, call_block
from tests.chap.chapserver import CONNECTION, ChapServer

MAKE = "/v1/analytics/make-dataset"
ENTRIES = "/v1/analytics/prediction-entry/11"
MODELS = "/v1/crud/configured-models"
THRESHOLDS = "/v1/analytics/thresholds"

GEOJSON: dict[str, Any] = {"type": "FeatureCollection", "features": []}

ROW = {"period": "202501", "orgUnit": "OU1", "value": 4.0, "featureName": "disease_cases"}

BREACHING = {"period": "202502", "orgUnit": "OU1", "quantile": 0.5, "value": 999.0}

NOT_A_LIST = [
    pytest.param({}, id="empty-object"),
    pytest.param({"detail": "gateway"}, id="object"),
    pytest.param({"entries": [BREACHING]}, id="object-holding-the-rows"),
    pytest.param(None, id="null"),
    pytest.param("rows", id="text"),
    pytest.param(3, id="number"),
    pytest.param(True, id="boolean"),
]

READS = [
    pytest.param(ChapPredictionReadOperator(), {"prediction_id": 11}, ENTRIES, id="prediction-read"),
    pytest.param(ChapModelsListOperator(), {}, MODELS, id="models-list"),
]


@pytest.mark.parametrize(("block", "config", "route"), READS)
@pytest.mark.parametrize("answer", NOT_A_LIST)
async def test_a_read_answered_with_anything_but_a_list_fails(
    block: AnyOperator, config: dict[str, Any], route: str, answer: Any, ctx: FakeContext, chap: ChapServer
) -> None:
    chap.on("GET", route, text=json.dumps(answer))
    with pytest.raises(BlockFailure) as refused:
        await call_block(block, {"connection": CONNECTION, **config}, ctx)
    assert refused.value.code == "chap.not_a_list"
    assert refused.value.error_class is ErrorClass.UNKNOWN
    assert route in str(refused.value)


async def test_a_read_answered_with_an_empty_list_is_still_empty(ctx: FakeContext, chap: ChapServer) -> None:
    chap.on("GET", ENTRIES, body=[])
    chap.on("GET", MODELS, body=[])
    read = await call_block(ChapPredictionReadOperator(), {"connection": CONNECTION, "prediction_id": 11}, ctx)
    models = await call_block(ChapModelsListOperator(), {"connection": CONNECTION}, ctx)
    assert isinstance(read, ChapPredictionReadOutput) and read.count == 0
    assert isinstance(models, ChapModelsListOutput) and models.count == 0


THRESHOLD_CONFIG: dict[str, Any] = {
    "connection": CONNECTION,
    "dataset_id": 42,
    "period_ids": ["2024-01"],
    "params": {"type": "seasonal"},
}


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param({}, id="empty-object"),
        pytest.param({"detail": "gateway"}, id="object"),
        pytest.param({"lines": [2.0]}, id="no-entries"),
        pytest.param({"lines": [2.0], "entries": "rows"}, id="entries-not-a-list"),
        pytest.param([], id="a-list"),
        pytest.param(None, id="null"),
    ],
)
async def test_thresholds_with_no_list_of_entries_fail(answer: Any, ctx: FakeContext, chap: ChapServer) -> None:
    chap.on("POST", THRESHOLDS, text=json.dumps(answer))
    with pytest.raises(BlockFailure) as refused:
        await call_block(ChapThresholdsOperator(), THRESHOLD_CONFIG, ctx)
    assert refused.value.code == "chap.thresholds.no_entries"
    assert refused.value.error_class is ErrorClass.UNKNOWN


async def test_thresholds_with_no_entries_for_those_periods_are_still_empty(ctx: FakeContext, chap: ChapServer) -> None:
    chap.on("POST", THRESHOLDS, body={"entries": []})
    output = await call_block(ChapThresholdsOperator(), THRESHOLD_CONFIG, ctx)
    assert isinstance(output, ChapThresholdsOutput)
    assert (output.lines, output.entries) == ([], [])


def _dataset(**config: Any) -> dict[str, Any]:
    return {"connection": CONNECTION, "name": "d", "geojson": GEOJSON, "provided_data": [ROW], **config}


NO_SUMMARY = [
    pytest.param({}, id="empty-object"),
    pytest.param({"id": None, "importedCount": 1}, id="no-rejected"),
    pytest.param({"id": None, "importedCount": 1, "rejected": None}, id="rejected-null"),
    pytest.param({"id": None, "importedCount": 1, "rejected": {"count": 3}}, id="rejected-an-object"),
    pytest.param({"id": None, "importedCount": 1, "rejections": [{"reason": "x"}]}, id="renamed-key"),
    pytest.param([], id="a-list"),
    pytest.param(None, id="null"),
]


@pytest.mark.parametrize("answer", NO_SUMMARY)
async def test_on_rejected_fail_does_not_import_on_a_validation_that_says_nothing(
    answer: Any, ctx: FakeContext, chap: ChapServer
) -> None:
    chap.on("POST", MAKE, text=json.dumps(answer))
    chap.on("POST", MAKE, body={"id": "job-real", "importedCount": 1, "rejected": []})
    with pytest.raises(BlockFailure) as refused:
        await call_block(ChapDatasetImportOperator(), _dataset(on_rejected="fail"), ctx)
    assert refused.value.code == "chap.dataset.not_validated"
    assert refused.value.error_class is ErrorClass.UNKNOWN
    assert len(chap.sent("POST", MAKE)) == 1


@pytest.mark.parametrize("answer", NO_SUMMARY)
async def test_a_dry_run_does_not_report_a_clean_validation_that_did_not_happen(
    answer: Any, ctx: FakeContext, chap: ChapServer
) -> None:
    chap.on("POST", MAKE, text=json.dumps(answer))
    with pytest.raises(BlockFailure) as refused:
        await call_block(ChapDatasetImportOperator(), _dataset(dry_run=True), ctx)
    assert refused.value.code == "chap.dataset.not_validated"


async def test_a_clean_validation_still_goes_on_to_import(ctx: FakeContext, chap: ChapServer) -> None:
    chap.on("POST", MAKE, body={"id": None, "importedCount": 1, "rejected": []})
    chap.on("POST", MAKE, body={"id": "job-2", "importedCount": 1, "rejected": []})
    handle = await call_block(ChapDatasetImportOperator(), _dataset(on_rejected="fail"), ctx)
    assert isinstance(handle, RemoteHandle) and handle.ref == "job-2"


async def test_the_real_posts_answer_is_not_held_to_it_once_a_job_is_started(
    ctx: FakeContext, chap: ChapServer
) -> None:
    chap.on("POST", MAKE, body={"id": "job-3", "importedCount": 1})
    handle = await call_block(ChapDatasetImportOperator(), _dataset(), ctx)
    assert isinstance(handle, RemoteHandle) and handle.ref == "job-3"


async def test_a_dry_run_with_rejections_still_reports_them(ctx: FakeContext, chap: ChapServer) -> None:
    chap.on("POST", MAKE, body={"id": None, "importedCount": 1, "rejected": [{"reason": "x"}]})
    output = await call_block(ChapDatasetImportOperator(), _dataset(dry_run=True), ctx)
    assert isinstance(output, ChapDatasetImportOutput)
    assert output.rejected_count == 1
