"""``chap.dataset.import``: validation, the import job it follows, and the dataset id it ends with."""

from typing import Any

import pytest
from pydantic import ValidationError

from dirigent_contrib.chap.bodies import csv_observations
from dirigent_contrib.chap.datasets import ChapDatasetImportConfig, ChapDatasetImportOperator, ChapDatasetImportOutput
from dirigent_contrib.chap.messages import CSV_MISSING_COLUMN, DATASET_REJECTED, OBSERVATIONS_MISSING
from dirigent_plugin import BlockFailure, ErrorClass, ProbeStatus, RemoteHandle
from dirigent_testing import FakeContext, call_block
from tests.chap.chapserver import CONNECTION, ChapServer, job, settle

MAKE = "/v1/analytics/make-dataset"

GEOJSON: dict[str, Any] = {
    "type": "FeatureCollection",
    "features": [{"type": "Feature", "id": "OU1", "properties": {}, "geometry": None}],
}

ROW = {"period": "202501", "orgUnit": "OU1", "value": 4.0, "featureName": "disease_cases"}

REJECTION: dict[str, Any] = {
    "reason": "Missing polygon in geojson",
    "orgUnit": "OU2",
    "featureName": "polygon",
    "timePeriods": [],
}


def _config(**overrides: Any) -> dict[str, Any]:
    return {"connection": CONNECTION, "name": "laos", "geojson": GEOJSON, "provided_data": [ROW], **overrides}


async def test_a_dry_run_validates_and_answers_without_a_job(ctx: FakeContext, chap: ChapServer) -> None:
    chap.on("POST", MAKE, body={"id": None, "importedCount": 1, "rejected": [REJECTION]})
    output = await call_block(ChapDatasetImportOperator(), _config(dry_run=True), ctx)
    assert isinstance(output, ChapDatasetImportOutput)
    assert output.dry_run is True
    assert output.dataset_id is None
    assert (output.imported_count, output.rejected_count) == (1, 1)
    sent = chap.sent("POST", MAKE)
    assert len(sent) == 1 and sent[0].url.params["dryRun"] == "true"


async def test_the_body_is_camel_case_and_passes_undeclared_keys_through(ctx: FakeContext, chap: ChapServer) -> None:
    chap.on("POST", MAKE, body={"id": "job-1", "importedCount": 1, "rejected": []})
    masked = [{"start": "202501", "end": "202502"}]
    fetched = [{"featureName": "rainfall", "dataSourceName": "era5"}]
    await call_block(ChapDatasetImportOperator(), _config(data_to_be_fetched=fetched, maskedRanges=masked), ctx)
    body = chap.body("POST", MAKE)
    assert body["name"] == "laos"
    assert body["geojson"] == GEOJSON
    assert body["providedData"] == [ROW]
    assert body["dataToBeFetched"] == fetched
    assert body["maskedRanges"] == masked
    assert {"dry_run", "on_rejected", "connection", "csv", "provided_data"}.isdisjoint(body)


async def test_an_import_is_followed_to_the_dataset_it_stored(ctx: FakeContext, chap: ChapServer) -> None:
    chap.on("POST", MAKE, body={"id": "job-1", "importedCount": 1, "rejected": [REJECTION]})
    chap.on("GET", "/v1/jobs/job-1", body=job("job-1", "PENDING"))
    chap.on("GET", "/v1/jobs/job-1", body=job("job-1", "STARTED"))
    chap.on("GET", "/v1/jobs/job-1", body=job("job-1", "SUCCESS"))
    chap.on("GET", "/v1/jobs/job-1/database_result", body={"id": 42})
    block = ChapDatasetImportOperator()
    config = ChapDatasetImportConfig.model_validate(_config())
    handle = await block.execute(config, ctx.as_context())
    assert isinstance(handle, RemoteHandle) and handle.ref == "job-1"
    probes, output = await settle(block, handle, config, ctx)
    assert [probe.status for probe in probes] == [ProbeStatus.RUNNING, ProbeStatus.RUNNING, ProbeStatus.SUCCEEDED]
    assert isinstance(output, ChapDatasetImportOutput)
    assert (output.dataset_id, output.job_id, output.rejected_count) == (42, "job-1", 1)
    assert output.rejected == [REJECTION]
    assert "Chap rejected an observation" in ctx.log.messages()
    assert len(chap.sent("POST", MAKE)) == 1


async def test_on_rejected_fail_refuses_before_anything_is_imported(ctx: FakeContext, chap: ChapServer) -> None:
    chap.on("POST", MAKE, body={"id": None, "importedCount": 1, "rejected": [REJECTION]})
    with pytest.raises(BlockFailure) as raised:
        await call_block(ChapDatasetImportOperator(), _config(on_rejected="fail"), ctx)
    assert raised.value.code == DATASET_REJECTED.code
    assert raised.value.error_class is ErrorClass.REJECTED
    sent = chap.sent("POST", MAKE)
    assert len(sent) == 1 and sent[0].url.params["dryRun"] == "true"


async def test_on_rejected_fail_imports_once_validation_is_clean(ctx: FakeContext, chap: ChapServer) -> None:
    chap.on("POST", MAKE, body={"id": None, "importedCount": 1, "rejected": []})
    chap.on("POST", MAKE, body={"id": "job-2", "importedCount": 1, "rejected": []})
    handle = await call_block(ChapDatasetImportOperator(), _config(on_rejected="fail"), ctx)
    assert isinstance(handle, RemoteHandle) and handle.ref == "job-2"
    assert [request.url.params.get("dryRun") for request in chap.sent("POST", MAKE)] == ["true", None]


async def test_a_failed_job_fails_with_its_error_and_writes_its_log(ctx: FakeContext, chap: ChapServer) -> None:
    chap.on("GET", "/v1/jobs/job-1", body=job("job-1", "FAILURE", error="harmonisation broke"))
    chap.on("GET", "/v1/jobs/job-1/logs", body="line one\nTraceback: boom")
    block = ChapDatasetImportOperator()
    config = ChapDatasetImportConfig.model_validate(_config())
    probes, output = await settle(block, block.handle("job-1"), config, ctx)
    assert probes[-1].status is ProbeStatus.FAILED
    assert probes[-1].message is not None and "harmonisation broke" in probes[-1].message
    assert output is None
    assert ctx.log.entries[-1][2]["log"] == "line one\nTraceback: boom"
    assert chap.sent("GET", "/v1/jobs/job-1/database_result") == []


async def test_a_revoked_job_fails(ctx: FakeContext, chap: ChapServer) -> None:
    chap.on("GET", "/v1/jobs/job-1", body=job("job-1", "REVOKED"))
    block = ChapDatasetImportOperator()
    probes, _ = await settle(block, block.handle("job-1"), ChapDatasetImportConfig.model_validate(_config()), ctx)
    assert probes[-1].status is ProbeStatus.FAILED


async def test_a_status_chap_adds_later_keeps_the_step_waiting(ctx: FakeContext, chap: ChapServer) -> None:
    chap.on("GET", "/v1/jobs/job-1", body=job("job-1", "RETRY"))
    block = ChapDatasetImportOperator()
    config = ChapDatasetImportConfig.model_validate(_config())
    probe = await block.probe(block.handle("job-1"), config, ctx.as_context())
    assert probe.status is ProbeStatus.RUNNING


async def test_a_job_chap_no_longer_knows_is_gone(ctx: FakeContext, chap: ChapServer) -> None:
    block = ChapDatasetImportOperator()
    config = ChapDatasetImportConfig.model_validate(_config())
    probe = await block.probe(block.handle("job-1"), config, ctx.as_context())
    assert probe.status is ProbeStatus.GONE


async def test_fetch_reads_the_status_before_asking_the_result_helper(ctx: FakeContext, chap: ChapServer) -> None:
    chap.on("GET", "/v1/jobs/job-1", body=job("job-1", "FAILURE"))
    block = ChapDatasetImportOperator()
    config = ChapDatasetImportConfig.model_validate(_config())
    with pytest.raises(BlockFailure) as raised:
        await block.fetch(block.handle("job-1"), config, ctx.as_context())
    assert raised.value.error_class is ErrorClass.TRANSIENT
    assert chap.sent("GET", "/v1/jobs/job-1/database_result") == []


async def test_cancel_revokes_the_job(ctx: FakeContext, chap: ChapServer) -> None:
    chap.on("POST", "/v1/jobs/job-1/cancel", body={"message": "cancelled"})
    block = ChapDatasetImportOperator()
    config = ChapDatasetImportConfig.model_validate(_config())
    assert await block.cancel(block.handle("job-1"), config, ctx.as_context()) is True
    chap.on("POST", "/v1/jobs/job-2/cancel", status=400, body={"detail": "already finished"})
    assert await block.cancel(block.handle("job-2"), config, ctx.as_context()) is False


async def test_a_refusal_is_classified_by_its_status(ctx: FakeContext, chap: ChapServer) -> None:
    chap.on("POST", MAKE, status=400, body={"detail": {"message": "All regions rejected."}})
    with pytest.raises(BlockFailure) as raised:
        await call_block(ChapDatasetImportOperator(), _config(), ctx)
    assert raised.value.error_class is ErrorClass.REJECTED
    assert "All regions rejected." in str(raised.value)
    chap.routes.clear()
    chap.on("POST", MAKE, status=503, text="upstream down")
    with pytest.raises(BlockFailure) as raised:
        await call_block(ChapDatasetImportOperator(), _config(), ctx)
    assert raised.value.error_class is ErrorClass.TRANSIENT


def test_a_step_without_observations_is_refused_at_validation() -> None:
    with pytest.raises(ValidationError, match=OBSERVATIONS_MISSING.render()):
        ChapDatasetImportConfig.model_validate(_config(provided_data=[]))


async def test_a_chap_csv_unfolds_into_one_observation_per_feature_cell(ctx: FakeContext, chap: ChapServer) -> None:
    chap.on("POST", MAKE, body={"id": None, "importedCount": 2, "rejected": []})
    csv = "time_period,location,rainfall,mean_temperature\n2025-01,OU1,12.5,24\n2025-01,OU2,,nan\n"
    await call_block(ChapDatasetImportOperator(), _config(provided_data=[], csv=csv, dry_run=True), ctx)
    assert chap.body("POST", MAKE)["providedData"] == [
        {"period": "2025-01", "orgUnit": "OU1", "featureName": "rainfall", "value": 12.5},
        {"period": "2025-01", "orgUnit": "OU1", "featureName": "mean_temperature", "value": 24.0},
        {"period": "2025-01", "orgUnit": "OU2", "featureName": "rainfall", "value": None},
        {"period": "2025-01", "orgUnit": "OU2", "featureName": "mean_temperature", "value": None},
    ]


def test_a_csv_without_its_key_columns_is_refused() -> None:
    with pytest.raises(BlockFailure) as raised:
        csv_observations("period,location,rainfall\n2025-01,OU1,1\n")
    assert raised.value.code == CSV_MISSING_COLUMN.code
    assert raised.value.error_class is ErrorClass.REJECTED


def test_a_csv_cell_that_is_not_a_number_is_refused_with_its_line() -> None:
    with pytest.raises(BlockFailure, match="line 3"):
        csv_observations("time_period,location,rainfall\n2025-01,OU1,1\n2025-02,OU1,wet\n")
