# Chap

**The Chap pack for dirigent.**

Chap, the climate and health modelling platform, brings disease forecasting models together
behind one API: a dataset of observations and covariates per org unit, a backtest that
evaluates a model on it, a prediction setup that keeps forecasting with the model a backtest
chose, and the alerts a forecast raises, held until a person clears them for release. This
pack makes each of those a step:

| Block | What it does |
| --- | --- |
| [`chap.dataset.import`](blocks.md#chapdatasetimport) | Validates observations, imports them as a dataset, and waits for the import job. |
| [`chap.backtest.run`](blocks.md#chapbacktestrun) | Runs a backtest of a configured model on a stored dataset. |
| [`chap.prediction.run`](blocks.md#chappredictionrun) | Forecasts from a saved prediction setup with fresh observations. |
| [`chap.prediction.read`](blocks.md#chappredictionread) | Reads a prediction's forecasts at the quantiles asked for. |
| [`chap.models.list`](blocks.md#chapmodelslist) | Lists the server's configured models. |
| [`chap.thresholds`](blocks.md#chapthresholds) | Computes outbreak thresholds, the endemic channel, for a dataset. |
| [`chap.alerts.record`](blocks.md#chapalertsrecord) | Records alerts against a policy, each one waiting for review. |
| [`chap.alerts.reviewed`](blocks.md#chapalertsreviewed) | A sensor: waits until a prediction's alerts are reviewed, and hands on the approved ones. |
| [`chap.alerts.list`](blocks.md#chapalertslist) | Reads where alerts stand in the review, once. |

All of them are configured from one [`chap` connection](connection.md), with or without an
API token. The [examples](examples.md) are runnable documents for each, and one that feeds
Chap from the open climate service.

## Built to survive Chap's releases

Chap tags a release every two weeks, so the blocks keep their coupling to it small:

- A step's config carries the request body's fields. The few a block reads are declared, in
  snake_case; any other key is sent to Chap exactly as written, in Chap's camelCase, so a field
  Chap adds is usable the day it ships.
- An output hands on Chap's JSON as it comes. Only the ids the next step needs -- a dataset id,
  a backtest id, a prediction id -- are lifted out.
- A job is followed at `/v1/jobs/{id}`, which is the stable part of the API, and its status
  decides alone. A released Chap answers with the bare status and master with the whole job;
  both are read, and an answer that is neither fails the step rather than leaving it waiting.
  [Rehearsed against](#rehearsed-against) names the Chap releases this was checked against.

## Alert verification

An alert is only sent once a person has cleared it. That decision is made where the verifier
works -- a review component embedded in DHIS2, in the modelling app, anywhere -- and it always
goes to Chap, through `POST /v1/crud/alerts/$approve`. Chap holds each alert, its state and who
decided it, so every tool that shows alerts shows the same decision, and the record outlives
any run. A pipeline does not ask the question or host the answer. It waits on the state Chap
holds:

1. `chap.prediction.run` forecasts. A setup that names an alert policy has Chap raise the
   alerts itself; otherwise `chap.alerts.record` records the ones a step derived from the
   forecast. Either way each alert starts `pending`.
2. `chap.alerts.reviewed` waits on the prediction's alerts. A waiting sensor holds no worker,
   so two days of review is a row with a due time. The attempt says how far the review has
   come, `3 of 7 reviewed`.
3. Once the review is done the sensor hands on `approved`, `declined` and `pending`, and a
   `for_each` over `approved` sends each cleared alert on -- `dhis2.message` to the district,
   in the [example](examples.md#chap-dhis2-alerts-reviewed-in-chap-sent-through-dhis2).

`release` says when the review is done. `all`, the default, waits until no alert is pending.
`any` ends the wait on the first decision, for a pipeline that should act as soon as anyone
has looked. A prediction that raised no alerts ends the wait at once under either, with empty
lists: there is nothing to review.

**Releasing what was approved by a deadline** is not a third mode. The deadline is the
engine's, the same `deadline` and `on_timeout` every sensor has, and the sensor cannot see it:
a poke knows when its wait began, not when it ends. A mode for it would be a second clock in
the block's config that could disagree with the step's. So the deadline stays the step's, and
what happens after it is said with the graph:

```yaml
  review:
    block: chap.alerts.reviewed
    depends_on: [forecast]
    deadline: 2d
    on_timeout: skip            # the deadline passing is not a failure
    config:
      connection: chap-local
      prediction_id: "${steps.forecast.output.prediction_id}"

  released:
    block: chap.alerts.list
    depends_on: [forecast, review]
    rule: all_done              # runs whether the review finished or ran out of time
    config:
      connection: chap-local
      prediction_id: "${steps.forecast.output.prediction_id}"

  notify:
    block: dhis2.message
    depends_on: [released]
    for_each: "${steps.released.output.approved}"
    config:
      connection: dhis2-local
      subject: "${item.level} alert for ${item.timePeriod}"
      text: "Chap forecasts an outbreak at the ${item.level} level for ${item.timePeriod}."
      org_units: ["${item.orgUnit}"]
```

The run then shows the review as `skipped` when time ran out and `succeeded` when it did not,
and `released.output.pending` names what nobody got to. A forecast that failed fails
`released` too, alongside the run it already failed. With `on_timeout: fail`, the default,
an unreviewed forecast fails the run where an operator sees it instead.

## Rehearsed against

| Chap | How |
| --- | --- |
| chap-core 2.5.1 | Every request and answer shape in the tests is taken from 2.5.1's OpenAPI document and its source (`rest_api/v1/jobs.py`, `v1/routers/analytics.py`, `v1/routers/crud.py`, `auth.py`). |
| The public demo at `https://climate-demo.dhis2.org/chap/stable`, 2.5.1 | Read live: `/system/info` answers `auth_required: true`, and `/v1/crud/configured-models` refuses a call without a token with 401, which is the case the connection check reports. Its OpenAPI document lists the alert routes, and `GET /v1/crud/alerts` refuses a call without a token with 401. No token for the demo was available, so nothing behind it was called, and no alert was ever written to it. |
| `GET /v1/jobs/{id}`: chap-core v2.5.1 and `master` at `d78b4c23` | Read from the source at both: v2.5.1's `get_job_status` answers with the bare status, master's `get_job` with the whole job since `ef17a258`, and both report Celery's states (`rest_api/celery_tasks.py`). The tests answer every job-backed block in each shape. Check this row again at each Chap release. |
| chap-core `master` at `ff8d1c0a` | The alert shapes and states (`pending`, `approved`, `declined`) are taken from `database/alert_tables.py`, `rest_api/data_models.py` and the alert routes in `v1/routers/crud.py`, which Chap marks experimental, and from `services/alert_service.py`, which raises a setup's alerts when its forecast finishes. |

Unit tests answer every block from a scripted Chap; nothing in them reaches the network.
