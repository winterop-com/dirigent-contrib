# Chap blocks

Every block the `dirigent-chap` pack contributes, with the config it takes and the output it
produces. The tables are the JSON Schemas each block publishes into the catalog -- the same ones
`GET /blocks` serves and the UI builds its step form from. Every block declares the `chap`
group and takes a `connection` naming a [`chap` connection](connection.md) by its code.

Chap changes fast, so these blocks lean on the parts of its API that do not: a job-backed block
submits through its own endpoint and then follows `/v1/jobs/{id}`, deciding from the job's
`status` alone before it asks a result helper for anything. `PENDING` and `STARTED` wait, and
so does any status Chap adds later; `SUCCESS` ends the step; `FAILURE` and `REVOKED` fail it,
with the end of the job's log from `/v1/jobs/{id}/logs` written into the run. Cancelling a step
sends `POST /v1/jobs/{id}/cancel`. A step's config carries the request body's fields in
snake_case; an undeclared key is sent to Chap as written, in Chap's camelCase, and the output
hands on Chap's JSON as it comes rather than pinning its shape.

**Idempotent** says whether re-running the block after an unclear failure is safe. No block in
this pack runs code on the worker.

| Block | Kind | Summary |
| --- | --- | --- |
| [`chap.dataset.import`](#chapdatasetimport) | operator | Import observations as a Chap dataset. |
| [`chap.backtest.run`](#chapbacktestrun) | operator | Run a Chap backtest on a stored dataset. |
| [`chap.prediction.run`](#chappredictionrun) | operator | Run a Chap prediction setup. |
| [`chap.prediction.read`](#chappredictionread) | operator | Read a Chap prediction's quantiles. |
| [`chap.models.list`](#chapmodelslist) | operator | List the models a Chap server has configured. |
| [`chap.thresholds`](#chapthresholds) | operator | Compute the endemic channel for a Chap dataset. |
| [`chap.alerts.record`](#chapalertsrecord) | operator | Record alerts in Chap's review queue. |
| [`chap.alerts.reviewed`](#chapalertsreviewed) | sensor | Wait for a Chap prediction's alerts to be reviewed. |
| [`chap.alerts.list`](#chapalertslist) | operator | List Chap alerts by their review state. |

## `chap.dataset.import`

Import observations as a Chap dataset.

Not idempotent. Polls every 30s unless the step says otherwise.

Sends the observations to `POST /v1/analytics/make-dataset`. Chap validates them synchronously
and answers with how many locations it took and every observation it rejected; the import
itself runs as a job, which the step follows at `/v1/jobs/{id}` and ends with the stored
dataset's id, read from `/v1/jobs/{id}/database_result`.

`dry_run: true` sends `dryRun=true` and ends at the validation, with no job. Under
`on_rejected: fail` the step validates with a dry run first and fails, as a refusal, when Chap
would reject anything, so nothing is imported; `warn` imports what Chap accepts and logs each
rejection.

Observations arrive as rows Chap spells for itself in `provided_data`, as a wide Chap CSV in
`csv`, or both. The CSV is unfolded into one observation per feature cell; an empty or `nan`
cell is sent as a missing value. Any undeclared key -- `dataSources`, `maskedRanges` -- is sent to
Chap as written. Note that `maskedRanges` deletes the target values inside the ranges for good.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string` | yes |  | The code of the chap connection naming the server. |
| `provided_data` | `object[]` |  |  | Observations as Chap spells them: `{period, orgUnit, value, featureName}`, one per row. |
| `csv` | `string or null` |  | `null` | A wide Chap CSV, the shape `aggregate_to_chap_csv` writes: `time_period`, `location`, and one column per feature. Each feature cell becomes one observation, sent beside `provided_data`. |
| `name` | `string` | yes |  | The name the dataset is stored under. |
| `geojson` | `object` | yes |  | The org units as a GeoJSON FeatureCollection, each feature's `id` the location its observations name. |
| `data_to_be_fetched` | `object[]` |  |  | Features Chap fetches itself, as Chap spells them: `{featureName, dataSourceName}`. |
| `dry_run` | `boolean` |  | `false` | Whether Chap only validates the observations and reports the rejections, importing nothing. |
| `on_rejected` | `"fail" or "warn"` |  | `"warn"` | What a rejected observation does: `warn` imports the rest and logs the rejections, `fail` imports nothing and fails the step. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `dataset_id` | `integer or null` |  | `null` | The stored dataset's id, which a backtest names; null for a dry run. |
| `job_id` | `string or null` |  | `null` | The import job Chap ran; null for a dry run. |
| `imported_count` | `integer` | yes |  | How many locations Chap accepted. |
| `rejected_count` | `integer` | yes |  | How many observations Chap rejected. |
| `rejected` | `any[]` |  |  | The first hundred rejections, in Chap's own words. |
| `dry_run` | `boolean` |  | `false` | Whether this was a validation only. |

## `chap.backtest.run`

Run a Chap backtest on a stored dataset.

Not idempotent. Polls every 30s unless the step says otherwise.

Submits `POST /v1/analytics/create-backtest` and follows the evaluation job. The output is the
backtest exactly as `/v1/jobs/{id}/evaluation_result` answers with it, with its
`aggregateMetrics` lifted out. A parameter left unset is not sent, so Chap applies the
defaults the server has saved for the dataset's period type -- the numbers in the table are
Chap's own defaults when nothing was saved. An unknown dataset (404) and a target column the
dataset lacks (422) are refusals.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string` | yes |  | The code of the chap connection naming the server. |
| `name` | `string` | yes |  | The name the backtest is stored under. |
| `model_id` | `integer or string` | yes |  | The configured model to evaluate, by its id or its name. |
| `dataset_id` | `integer` | yes |  | The stored dataset to evaluate it on, as `chap.dataset.import` outputs it. |
| `n_periods` | `integer or null` |  | `null` | How many periods ahead each split forecasts; Chap's default is 3. |
| `n_splits` | `integer or null` |  | `null` | How many train/test splits are evaluated; Chap's default is 7. |
| `stride` | `integer or null` |  | `null` | How many periods one split moves on from the last; Chap's default is 1. |
| `n_retrain` | `integer or null` |  | `null` | How many times the model is retrained across the splits; Chap's default is 1. |
| `future_weather_provider` | `string or null` |  | `null` | Where the forecast window's weather comes from; Chap's default is `climatology`. |
| `target_column` | `string or null` |  | `null` | The dataset column the model forecasts; Chap's default is `disease_cases`. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `backtest_id` | `integer or null` |  | `null` | The stored backtest's id. |
| `job_id` | `string` | yes |  | The evaluation job Chap ran. |
| `aggregate_metrics` | `any` |  | `null` | The backtest's `aggregateMetrics`, lifted out of it. |
| `backtest` | `any` |  | `null` | The backtest exactly as Chap's evaluation result answers with it. |

## `chap.prediction.run`

Run a Chap prediction setup.

Not idempotent. Polls every 30s unless the step says otherwise.

Submits `POST /v1/crud/prediction-setups/{predictionSetupId}/run` with the observations and
follows the forecast job; the output is the prediction as `/v1/jobs/{id}/prediction_result`
answers with it. An unknown setup (404), an archived model (409) and observations Chap cannot
use (422) are refusals and are never retried. The setup fixes the model, the target and the
future-weather provider.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string` | yes |  | The code of the chap connection naming the server. |
| `provided_data` | `object[]` |  |  | Observations as Chap spells them: `{period, orgUnit, value, featureName}`, one per row. |
| `csv` | `string or null` |  | `null` | A wide Chap CSV, the shape `aggregate_to_chap_csv` writes: `time_period`, `location`, and one column per feature. Each feature cell becomes one observation, sent beside `provided_data`. |
| `prediction_setup_id` | `integer` | yes |  | The saved prediction setup to forecast with, which fixes the model and its target. |
| `name` | `string` | yes |  | The name the prediction is stored under. |
| `geojson` | `object` | yes |  | The org units as a GeoJSON FeatureCollection, each feature's `id` the location its observations name. |
| `n_periods` | `integer or null` |  | `null` | How many periods ahead to forecast; Chap's default is 3. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `prediction_id` | `integer or null` |  | `null` | The stored prediction's id, which `chap.prediction.read` names. |
| `job_id` | `string` | yes |  | The forecast job Chap ran. |
| `prediction` | `any` |  | `null` | The prediction exactly as Chap's prediction result answers with it. |

## `chap.prediction.read`

Read a Chap prediction's quantiles.

Not idempotent.

Reads `GET /v1/analytics/prediction-entry/{predictionId}` with one `quantiles` parameter per
quantile, and hands on the entries as Chap answers with them.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string` | yes |  | The code of the chap connection naming the server. |
| `prediction_id` | `integer` | yes |  | The stored prediction to read, as `chap.prediction.run` outputs it. |
| `quantiles` | `number[]` |  |  | The quantiles to read each forecast at, each between 0 and 1. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `entries` | `any[]` | yes |  | The entries as Chap answers with them: `{period, orgUnit, quantile, value}`. |
| `count` | `integer` | yes |  | How many entries there are. |

## `chap.models.list`

List the models a Chap server has configured.

Not idempotent.

Reads `GET /v1/crud/configured-models` and hands on each model as Chap describes it.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string` | yes |  | The code of the chap connection naming the server. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `models` | `any[]` | yes |  | Each configured model as Chap answers with it: its `id`, `name`, `covariates`, `target` and the rest. |
| `count` | `integer` | yes |  | How many models there are. |

## `chap.thresholds`

Compute the endemic channel for a Chap dataset.

Not idempotent.

Posts `POST /v1/analytics/thresholds` and hands on the answer. `params.type` selects the
strategy; `GET /v1/analytics/thresholds/strategies` lists every strategy a server has, and the
two Chap ships are `seasonal` (`stdMultiplier`) and `percentile` (`quantile`,
`baselineYears`). A line parameter given as a list produces one threshold line per entry, so
`quantile: [0.25, 0.75]` is the endemic channel's band. Any undeclared key is sent as written.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string` | yes |  | The code of the chap connection naming the server. |
| `dataset_id` | `integer` | yes |  | The stored dataset whose historical `disease_cases` the thresholds are computed from. |
| `period_ids` | `string[]` | yes |  | The periods to compute thresholds for, at the dataset's own frequency, such as `2024-01`. |
| `locations` | `string[] or null` |  | `null` | The locations to restrict the answer to; every location in the dataset when unset. |
| `params` | `object` | yes |  | The strategy and its parameters as Chap spells them: `type` selects the strategy (`seasonal`, `percentile`, or any `GET /v1/analytics/thresholds/strategies` lists), and a line parameter such as `stdMultiplier` or `quantile` takes one value or a list, one threshold line each. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `params` | `any` |  | `null` | The parameters the thresholds were computed with, Chap's defaults applied. |
| `lines` | `any[]` |  |  | The line parameter of each threshold line, in the order of every entry's `values`. |
| `entries` | `any[]` |  |  | One entry per requested period and location: `{period, location, values}`, a value null where no threshold could be computed. |

## `chap.alerts.record`

Record alerts in Chap's review queue.

Not idempotent: a second alert for the same prediction, org unit and period is refused.

Posts `POST /v1/crud/alerts` with the alerts as written and hands on the ids Chap gave them.
Chap validates the whole batch before it writes any of it, so an unknown policy, level or
prediction (422) records nothing and is never retried. Every alert starts `pending`. A
prediction setup that names an alert policy raises its own alerts when its forecast finishes,
so a pipeline forecasting from one has nothing to record. Any undeclared key is sent as
written. See [Alert verification](index.md#alert-verification).

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string` | yes |  | The code of the chap connection naming the server. |
| `alerts` | `object[]` | yes |  | The alerts as Chap spells them: `{timePeriod, orgUnit, alertPolicyId, level, predictionId}`, each `level` one the policy defines. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `alert_ids` | `integer[]` | yes |  | The recorded alerts' ids, in the order they were sent; each starts `pending`. |
| `count` | `integer` | yes |  | How many alerts were recorded. |

## `chap.alerts.reviewed`

Wait for a Chap prediction's alerts to be reviewed.

A sensor. Pokes every 5m and gives up after 3 days unless the step says otherwise.

Each poke is one `GET /v1/crud/alerts?predictionId=...`, narrowed by `alertPolicyId` when the
step names a policy and to `org_units` when it names any. An alert whose `approved` is
`approved` or `declined` is decided; `pending`, and any state Chap adds later, is still
waiting. Under `release: all` the wait ends once nothing is pending, under `release: any` as
soon as one alert is decided, and under either a prediction that raised no alerts ends it at
once with empty lists. While it waits, the attempt says how far the review has come -- `3 of 7
reviewed` -- with the same fraction as its progress. The output splits the alerts by where they
stand, so a `for_each` over `approved` is one step per alert cleared for release.

The sensor never decides on an alert, and it is not a source: it waits inside the run that
forecast the prediction it names. `poll`, `deadline` and `on_timeout` are the step's own, as
for every sensor. See [Alert verification](index.md#alert-verification).

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string` | yes |  | The code of the chap connection naming the server. |
| `prediction_id` | `integer` | yes |  | The prediction whose alerts are waited on, as `chap.prediction.run` outputs it. |
| `alert_policy_id` | `integer or null` |  | `null` | Only the alerts raised against this policy; every policy when unset. |
| `org_units` | `string[] or null` |  | `null` | Only the alerts for these org units; every org unit when unset. |
| `release` | `"all" or "any"` |  | `"all"` | When the wait ends: `all` once no alert is pending, `any` as soon as one is decided. A prediction that raised no alerts ends it at once either way. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `approved` | `any[]` |  |  | The alerts a reviewer cleared for release, as Chap answers with them: `{id, timePeriod, orgUnit, alertPolicyId, level, predictionId, approvedBy, approvedAt, ...}`. |
| `declined` | `any[]` |  |  | The alerts a reviewer decided not to release, in the same shape. |
| `pending` | `any[]` |  |  | The alerts nobody has decided on yet, in the same shape. |
| `counts` | `object` |  |  | How many alerts there are, and how many of them are approved, declined and pending. |

The `counts` object carries `total`, `approved`, `declined` and `pending`.

## `chap.alerts.list`

List Chap alerts by their review state.

Idempotent.

The same listing `chap.alerts.reviewed` pokes with, read once and never waited on: every alert
the filters select, split into `approved`, `declined` and `pending`. With no `prediction_id`
it reads every prediction's alerts, and its `pending` is the whole review queue. It is the
step that releases what was approved when a review's deadline passed.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string` | yes |  | The code of the chap connection naming the server. |
| `prediction_id` | `integer or null` |  | `null` | Only the alerts this prediction raised; every prediction's when unset. |
| `alert_policy_id` | `integer or null` |  | `null` | Only the alerts raised against this policy; every policy when unset. |
| `org_units` | `string[] or null` |  | `null` | Only the alerts for these org units; every org unit when unset. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `approved` | `any[]` |  |  | The alerts a reviewer cleared for release, as Chap answers with them: `{id, timePeriod, orgUnit, alertPolicyId, level, predictionId, approvedBy, approvedAt, ...}`. |
| `declined` | `any[]` |  |  | The alerts a reviewer decided not to release, in the same shape. |
| `pending` | `any[]` |  |  | The alerts nobody has decided on yet, in the same shape. |
| `counts` | `object` |  |  | How many alerts there are, and how many of them are approved, declined and pending. |

## How a failure is classified

A refusal the server answers with is classified by its status: a 5xx and a 429 are
transient and retried within the step's budget, any other 4xx is a refusal and never retried. A
transport failure -- a refused connection, a timeout -- is transient. A refusal carries the
server's own words, its FastAPI `detail` where it gave one.

## Every refusal carries a code

Each refusal is minted in the pack's catalogue under the `chap` prefix, so a reader selects it by its code and a translation can replace its words.

| Code | Template |
| --- | --- |
| `chap.answered` | `{where} answered {status}: {remote}` |
| `chap.not_json` | `{where} answered with a body that is not JSON` |
| `chap.connection.unreachable` | `Chap did not answer: {detail}` |
| `chap.connection.auth_required` | `Chap requires an API token on every call but /system/info, and this connection carries none` |
| `chap.connection.token_refused` | `Chap refused the API token: {detail}` |
| `chap.job.running` | `job {job} is {status}` |
| `chap.job.failed` | `job {job} ended {status}: {error}` |
| `chap.job.unknown` | `Chap no longer knows job {job}` |
| `chap.job.unsettled` | `job {job} is {status} rather than SUCCESS, so it has no result to collect` |
| `chap.observations.missing` | `a step that sends observations to Chap needs provided_data, csv, or both` |
| `chap.csv.missing_column` | `the csv has no {column} column, which every row needs` |
| `chap.csv.bad_value` | `the csv's {column} on line {line} is '{value}', which is not a number` |
| `chap.dataset.rejected` | `Chap rejected {count} of the observations and on_rejected is fail, so nothing was imported: {detail}` |
| `chap.job.not_submitted` | `{where} answered without a job id to follow` |
| `chap.alerts.reviewing` | `{reviewed} of {total} reviewed` |
| `chap.alerts.not_a_list` | `{where} answered with something other than a list of alerts` |
| `chap.alerts.not_recorded` | `{where} answered without the ids of the alerts it recorded` |
