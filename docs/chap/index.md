# dirigent-chap

**The Chap pack for dirigent.**

Chap, the climate and health modelling platform, brings disease forecasting models together
behind one API: a dataset of observations and covariates per org unit, a backtest that
evaluates a model on it, and a prediction setup that keeps forecasting with the model a
backtest chose. This pack makes each of those a step:

| Block | What it does |
| --- | --- |
| [`chap.dataset.import`](blocks.md#chapdatasetimport) | Validates observations, imports them as a dataset, and waits for the import job. |
| [`chap.backtest.run`](blocks.md#chapbacktestrun) | Runs a backtest of a configured model on a stored dataset. |
| [`chap.prediction.run`](blocks.md#chappredictionrun) | Forecasts from a saved prediction setup with fresh observations. |
| [`chap.prediction.read`](blocks.md#chappredictionread) | Reads a prediction's forecasts at the quantiles asked for. |
| [`chap.models.list`](blocks.md#chapmodelslist) | Lists the server's configured models. |
| [`chap.thresholds`](blocks.md#chapthresholds) | Computes outbreak thresholds, the endemic channel, for a dataset. |

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
- A job is followed at `/v1/jobs/{id}`, which is the stable part of the API, and its `status`
  decides alone. A status Chap adds later keeps the step waiting rather than failing it.

## Rehearsed against

| Chap | How |
| --- | --- |
| chap-core 2.5.1 | Every request and answer shape in the tests is taken from 2.5.1's OpenAPI document and its source (`rest_api/v1/jobs.py`, `v1/routers/analytics.py`, `v1/routers/crud.py`, `auth.py`). |
| The public demo at `https://climate-demo.dhis2.org/chap/stable`, 2.5.1 | Read live: `/system/info` answers `auth_required: true`, and `/v1/crud/configured-models` refuses a call without a token with 401, which is the case the connection check reports. No token for the demo was available, so nothing behind it was called. |

Unit tests answer every block from a scripted Chap; nothing in them reaches the network.
