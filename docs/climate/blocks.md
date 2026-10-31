# Climate blocks

Every block the open climate service pack contributes, with the config it takes and the output it
produces. The tables are the JSON Schemas each block publishes into the catalog -- the same ones
`GET /blocks` serves and the UI builds its step form from. Every block declares the `climate`
group and takes a `connection` naming a [`climate` connection](connection.md) by its code.

**Idempotent** says whether re-running the block after an unclear failure is safe. No block in
this pack runs code on the worker.

| Block | Kind | Summary |
| --- | --- | --- |
| [`climate.datasets.list`](#climatedatasetslist) | operator | List the open climate service's datasets. |
| [`climate.aggregate`](#climateaggregate) | operator | Aggregate a climate dataset to org units with the open climate service. |
| [`climate.job.run`](#climatejobrun) | operator | Run an openEO batch job on the open climate service. |
| [`climate.job.result`](#climatejobresult) | operator | Download a finished open climate service job's payload. |
| [`climate.export`](#climateexport) | operator | Deliver an open climate service export to its target. |
| [`climate.ingest`](#climateingest) | operator | Ingest a dataset into the open climate service. |
| [`climate.sync`](#climatesync) | operator | Sync a managed open climate service dataset forward. |

## `climate.datasets.list`

List the open climate service's datasets.

Not idempotent.

Reads `GET /datasets?f=json` with `Accept: application/json`, and hands on each dataset as the
service describes it.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string` | yes |  | The code of the climate connection naming the instance. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `datasets` | `any[]` | yes |  | Each dataset as the service answers with it: its `dataset_id`, `period_type`, `variable`, `extent` and the rest. |
| `count` | `integer` | yes |  | How many datasets there are. |

## `climate.aggregate`

Aggregate a climate dataset to org units with the open climate service.

Not idempotent.

Posts the graph to `POST /result` and streams the answer into the run's storage. A step names
a built-in workflow and its arguments, or writes a whole openEO `process_graph`, and exactly
one of the two:

| Workflow | What it answers with | Needs |
| --- | --- | --- |
| `aggregate_to_dhis2_json` | A DHIS2 dataValueSet, shaped by a named export the instance configures. | `export` |
| `aggregate_to_chap_csv` | A wide Chap CSV: `time_period`, `location`, one column per variable. | `period_type`, optionally |
| `aggregate_by_features` | One value per feature and time step, in no fixed format. | |

Every workflow takes `dataset_id`, `start`, `end` and `geometries`, whose features' `id`s are
the org units, and reduces each org unit's pixels with `method`. The payload is written under
the run's scratch and its `uri` is always in the output; a payload no larger than the
instance's inline limit is also in `value` (JSON) or `text` (CSV). A larger one is read back
with `storage.read`. The `timeout` is the step's own, because an aggregation over a long range
takes minutes; it defaults to 5m.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string` | yes |  | The code of the climate connection naming the instance. |
| `workflow` | `"aggregate_to_dhis2_json" or "aggregate_to_chap_csv" or "aggregate_by_features" or null` |  | `null` | The built-in workflow to run: `aggregate_to_dhis2_json`, `aggregate_to_chap_csv` or `aggregate_by_features`. |
| `dataset_id` | `string or null` |  | `null` | The published dataset the workflow aggregates, as `climate.datasets.list` lists it. |
| `start` | `string or null` |  | `null` | The first day the workflow loads, as an ISO date. |
| `end` | `string or null` |  | `null` | The last day the workflow loads, as an ISO date. |
| `geometries` | `object or null` |  | `null` | The org units as a GeoJSON FeatureCollection, each feature's `id` the org unit's uid. |
| `method` | `"mean" or "min" or "max" or "sum" or "median"` |  | `"mean"` | How the pixels inside each org unit are reduced to one value: mean, min, max, sum or median. |
| `export` | `string or null` |  | `null` | The named DHIS2 export the instance configures, which `aggregate_to_dhis2_json` saves through. |
| `period_type` | `string or null` |  | `null` | The period type each time step is written as, for `aggregate_to_chap_csv`: day, week, month, quarter or year; the service's default is month. |
| `process_graph` | `object or null` |  | `null` | A whole openEO process graph, node id to node, run in place of a workflow. |
| `timeout` | `string (humane-duration)` |  | `"5m"` | How long the service may take to answer; an aggregation over a long range takes minutes. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `uri` | `string` | yes |  | Where the payload was written, under the run's scratch; `storage.read` reads it back. |
| `content_type` | `string` | yes |  | The media type the service sent it as. |
| `size_bytes` | `integer` | yes |  | How large it is. |
| `value` | `any` |  | `null` | The payload parsed as JSON, set when it is JSON and no larger than the instance lets a block inline; `uri` holds it either way. |
| `text` | `string or null` |  | `null` | The payload as text, set when it is text, such as a CSV, and no larger than the instance lets a block inline; `uri` holds it either way. |
| `workflow` | `"aggregate_to_dhis2_json" or "aggregate_to_chap_csv" or "aggregate_by_features" or null` |  | `null` | The built-in workflow that ran, or null for a graph the step wrote out. |

## `climate.job.run`

Run an openEO batch job on the open climate service.

Not idempotent. Polls every 15s unless the step says otherwise.

Creates an openEO batch job with `POST /jobs` and queues it with `POST /jobs/{id}/results`,
then probes `GET /jobs/{id}`: `created`, `queued` and `running` wait, `finished` ends the step
with the job's results item from `GET /jobs/{id}/results`, and `error` or `canceled` fails it
with the job's own log written into the run. Cancelling the step sends
`DELETE /jobs/{id}/results`. The graph is named the way `climate.aggregate` names one.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string` | yes |  | The code of the climate connection naming the instance. |
| `workflow` | `"aggregate_to_dhis2_json" or "aggregate_to_chap_csv" or "aggregate_by_features" or null` |  | `null` | The built-in workflow to run: `aggregate_to_dhis2_json`, `aggregate_to_chap_csv` or `aggregate_by_features`. |
| `dataset_id` | `string or null` |  | `null` | The published dataset the workflow aggregates, as `climate.datasets.list` lists it. |
| `start` | `string or null` |  | `null` | The first day the workflow loads, as an ISO date. |
| `end` | `string or null` |  | `null` | The last day the workflow loads, as an ISO date. |
| `geometries` | `object or null` |  | `null` | The org units as a GeoJSON FeatureCollection, each feature's `id` the org unit's uid. |
| `method` | `"mean" or "min" or "max" or "sum" or "median"` |  | `"mean"` | How the pixels inside each org unit are reduced to one value: mean, min, max, sum or median. |
| `export` | `string or null` |  | `null` | The named DHIS2 export the instance configures, which `aggregate_to_dhis2_json` saves through. |
| `period_type` | `string or null` |  | `null` | The period type each time step is written as, for `aggregate_to_chap_csv`: day, week, month, quarter or year; the service's default is month. |
| `process_graph` | `object or null` |  | `null` | A whole openEO process graph, node id to node, run in place of a workflow. |
| `title` | `string or null` |  | `null` | The title the job is listed under on the service. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `job_id` | `string` | yes |  | The batch job's id, which `climate.job.result` and `climate.export` name. |
| `assets` | `string[]` | yes |  | The names of the assets the results carry, such as `result` and `manifest`. |
| `results` | `any` |  | `null` | The results' STAC item, exactly as the service answers with it. |

## `climate.job.result`

Download a finished open climate service job's payload.

Not idempotent.

Reads the job's results item, finds the asset named `asset`, and streams its `href` into the
run's storage; the `href` is read under the connection's `base_url`, so an instance served
under a path prefix such as `/ocs` is reached there. The output is the same as
`climate.aggregate`'s: always a `uri`, and the payload in `value` or `text` when it is small. A
DHIS2 dataValueSet from `aggregate_to_dhis2_json` feeds `dhis2.data_value_set_import`
directly, through `storage.read` when it is larger than the inline limit.

**Why a block of its own, not an option on `climate.job.run`.** A job's results item is small
and its payload may not be: kept apart, `climate.job.run` settles on a few kilobytes, the
download is retried on its own without running the job again, it can fetch any asset rather
than one decided at submission, and it composes with a job some other run, or the service's
own schedule, made. A fetch that downloaded the payload would also repeat the whole download
every time the engine's at-least-once fetch is replayed.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string` | yes |  | The code of the climate connection naming the instance. |
| `job_id` | `string` | yes |  | The finished batch job, as `climate.job.run` outputs it. |
| `asset` | `string` |  | `"result"` | The asset of the job's results to download; `result` is the payload a workflow saved, such as the DHIS2 dataValueSet `aggregate_to_dhis2_json` writes. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `uri` | `string` | yes |  | Where the payload was written, under the run's scratch; `storage.read` reads it back. |
| `content_type` | `string` | yes |  | The media type the service sent it as. |
| `size_bytes` | `integer` | yes |  | How large it is. |
| `value` | `any` |  | `null` | The payload parsed as JSON, set when it is JSON and no larger than the instance lets a block inline; `uri` holds it either way. |
| `text` | `string or null` |  | `null` | The payload as text, set when it is text, such as a CSV, and no larger than the instance lets a block inline; `uri` holds it either way. |
| `job_id` | `string` | yes |  | The job the payload belongs to. |
| `asset` | `string` | yes |  | The asset that was downloaded. |
| `href` | `string` | yes |  | Where the service serves the asset. |

## `climate.export`

Deliver an open climate service export to its target.

Not idempotent. Polls every 15s unless the step says otherwise.

Posts `POST /exports/{export_id}` with `{job_id, dry_run}` under an `Idempotency-Key` header
derived from the run, the step, the fan-out item and the attempt: the same attempt executed
twice, after a worker crash, gets the delivery it queued the first time, and a retry, which is
a new attempt, queues its own. The step then probes `GET /exports/{export_id}/jobs/{id}`:
`accepted`, `running` and `retrying` wait, `failed` and `cancelled` fail with the job's error,
and `successful` ends with the export report -- unless the report's `outcome` is `rejected`, which
fails the step as a refusal. The service delivers with its own DHIS2 credentials; a delivery
cannot be cancelled from here.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string` | yes |  | The code of the climate connection naming the instance. |
| `export_id` | `string` | yes |  | The named export the instance configures, the same one the job's workflow saved through. |
| `job_id` | `string` | yes |  | The finished batch job whose saved payload is delivered, as `climate.job.run` outputs it. |
| `dry_run` | `boolean` |  | `false` | Whether the target only validates the payload, writing nothing. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `delivery_job_id` | `string` | yes |  | The delivery job the service ran. |
| `export_id` | `string` | yes |  | The export that was delivered. |
| `status` | `string` | yes |  | The delivery job's final status. |
| `outcome` | `string or null` |  | `null` | The report's outcome: success, partial, dry_run, cancelled or unknown. |
| `reused` | `boolean` |  | `false` | Whether the service answered with a delivery this attempt had already queued. |
| `dry_run` | `boolean` |  | `false` | Whether this was a validation only. |
| `report` | `any` |  | `null` | The export report exactly as the service answers with it: counts, conflicts and the target's task ids. |

## `climate.ingest`

Ingest a dataset into the open climate service.

Not idempotent. Polls every 30s unless the step says otherwise.

Posts `POST /ingestions` with `Prefer: respond-async`, so the service answers 202 with
`Location: /ingestions/jobs/{id}`, and probes that job: `accepted`, `running` and `retrying`
wait with the job's `progress.percent` as the step's progress, `successful` ends with the job's
record, and `failed` or `cancelled` fail with its error. Cancelling the step sends
`DELETE /ingestions/jobs/{id}`, which the service honours at its next checkpoint.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string` | yes |  | The code of the climate connection naming the instance. |
| `dataset_id` | `string` | yes |  | The dataset the job brings in or forward. |
| `start` | `string or null` |  | `null` | The first time step to bring in, as an ISO date; the source's own start when unset. |
| `end` | `string or null` |  | `null` | The last time step to bring in, as an ISO date; the latest available when unset. |
| `overwrite` | `boolean` |  | `false` | Whether time steps already held are fetched again and replaced. |
| `publish` | `boolean` |  | `true` | Whether the dataset is published once it is in. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `job_id` | `string or null` |  | `null` | The job the service ran; null when it did the work inline and answered with it. |
| `status` | `string` | yes |  | The job's final status, or the inline answer's. |
| `finished_at` | `string or null` |  | `null` | When the job finished, in the service's own timestamp. |
| `result` | `any` |  | `null` | The job's result, or the inline answer, exactly as the service gives it. |

## `climate.sync`

Sync a managed open climate service dataset forward.

Not idempotent. Polls every 30s unless the step says otherwise.

Posts `POST /sync/{dataset_id}` with `Prefer: respond-async` and follows the job exactly as
`climate.ingest` does. A sync the service answers at once, rather than with a job, ends the step
with that answer and a null `job_id`.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string` | yes |  | The code of the climate connection naming the instance. |
| `dataset_id` | `string` | yes |  | The dataset the job brings in or forward. |
| `end` | `string or null` |  | `null` | The last time step to bring in, as an ISO date; the latest available when unset. |
| `publish` | `boolean` |  | `true` | Whether the dataset is published once it is synced. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `job_id` | `string or null` |  | `null` | The job the service ran; null when it did the work inline and answered with it. |
| `status` | `string` | yes |  | The job's final status, or the inline answer's. |
| `finished_at` | `string or null` |  | `null` | When the job finished, in the service's own timestamp. |
| `result` | `any` |  | `null` | The job's result, or the inline answer, exactly as the service gives it. |

## What a path may carry

`climate.sync`'s `dataset_id`, `climate.ingest`'s `dataset_id`, `climate.export`'s `export_id` and
`climate.job.result`'s `job_id` go into a request's path or name what does, so each must be one id:
a letter or a digit, then letters, digits, `.`, `_` and `-`, at most 256 characters. Anything else
refuses the config and sends nothing. A job id the service answers with is held to the same rule,
in a body or a `Location`, and any other fails the step with `climate.job.not_submitted`.

## How a failure is classified

A refusal the server answers with is classified by its status: a 5xx and a 429 are
transient and retried within the step's budget, any other 4xx is a refusal and never retried. A
transport failure -- a refused connection, a timeout -- is transient. A refusal carries the
server's own words, its FastAPI `detail` where it gave one.

## Every refusal carries a code

Each refusal is minted in the pack's catalogue under the `climate` prefix, so a reader selects it by its code and a translation can replace its words.

| Code | Template |
| --- | --- |
| `climate.answered` | `{where} answered {status}: {remote}` |
| `climate.not_json` | `{where} answered with a body that is not JSON` |
| `climate.connection.unreachable` | `the open climate service did not answer: {detail}` |
| `climate.connection.unhealthy` | `the open climate service reports itself {status}` |
| `climate.connection.read_only` | `the open climate service is read-only: it reads and aggregates, and refuses jobs, ingestions, syncs and exports` |
| `climate.graph.one_of` | `a step names a workflow or carries a process_graph, and exactly one` |
| `climate.graph.missing` | `the {workflow} workflow needs {field}` |
| `climate.graph.stray` | `{field} is an argument of {owner} only, and this step runs {workflow}` |
| `climate.job.not_submitted` | `{where} answered without a job id to follow` |
| `climate.job.running` | `job {job} is {status}` |
| `climate.job.failed` | `job {job} ended {status}: {detail}` |
| `climate.job.unknown` | `the open climate service no longer knows job {job}` |
| `climate.job.no_asset` | `job {job}'s results carry no asset named {asset}; they carry {available}` |
| `climate.export.rejected` | `the target refused export {export}: {detail}` |
