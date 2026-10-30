# dirigent-contrib

[![CI](https://github.com/winterop-com/dirigent-contrib/actions/workflows/ci.yaml/badge.svg?branch=main)](https://github.com/winterop-com/dirigent-contrib/actions/workflows/ci.yaml)
[![Docs](https://img.shields.io/badge/docs-winterop--com.github.io%2Fdirigent--contrib-2b2f38)](https://winterop-com.github.io/dirigent-contrib/)

Block packs for [dirigent](https://github.com/winterop-com/dirigent) that reach outside systems,
all in one package. Installing `dirigent-contrib` is the whole of the configuration: the host
finds each pack through its entry point.

```bash
uv tool install dirigent-cli --with dirigent-contrib
```

Documentation: <https://winterop-com.github.io/dirigent-contrib/>.

## Chap

The `chap` connection kind and the blocks that drive one Chap (chap-core) server, in
`dirigent_contrib.chap`: import observations as a dataset, run a backtest, forecast from a saved
prediction setup, read the forecast's quantiles, list the configured models, compute the endemic
channel, and record a forecast's alerts and wait for a person to review them in Chap.

| Block | Kind | What it does |
| --- | --- | --- |
| `chap.dataset.import` | operator, probed | Validates observations, imports them as a dataset, and waits for the import job. |
| `chap.backtest.run` | operator, probed | Runs a backtest of a configured model on a stored dataset. |
| `chap.prediction.run` | operator, probed | Forecasts from a saved prediction setup with fresh observations. |
| `chap.prediction.read` | operator | Reads a prediction's forecasts at the quantiles asked for. |
| `chap.models.list` | operator | Lists the server's configured models. |
| `chap.thresholds` | operator | Computes outbreak thresholds, the endemic channel, for a dataset. |
| `chap.alerts.record` | operator | Records alerts against a policy, each one waiting for review. |
| `chap.alerts.reviewed` | sensor | Waits until a prediction's alerts are reviewed, and hands on the approved ones. |
| `chap.alerts.list` | operator | Reads where alerts stand in the review, once. |

## The open climate service

The `climate` connection kind and the blocks that drive one instance of the open climate service,
in `dirigent_contrib.climate`: list its datasets, aggregate one to org units, run a batch job and
download what it made, deliver a saved export to DHIS2, and ingest or sync a managed dataset.

| Block | Kind | What it does |
| --- | --- | --- |
| `climate.datasets.list` | operator | Lists the published datasets. |
| `climate.aggregate` | operator | Runs a process graph synchronously and keeps its payload. |
| `climate.job.run` | operator, probed | Runs a process graph as an openEO batch job. |
| `climate.job.result` | operator | Downloads a finished job's payload into the run's storage. |
| `climate.export` | operator, probed | Delivers a job's saved export through the service's own DHIS2 connection. |
| `climate.ingest` | operator, probed | Creates or updates a managed dataset. |
| `climate.sync` | operator, probed | Brings a managed dataset forward from its latest time step. |

## Working on it

One package, with a subpackage per system under `src/dirigent_contrib/` and its tests under
`tests/`. The gates CI runs:

```bash
make sync
make check
make test
make docs
```

Live checks against a real server only read, and are opt-in:

```bash
DIRIGENT_LIVE=1 uv run pytest -m live
DIRIGENT_LIVE=1 CHAP_LIVE_URL=http://localhost:8000 uv run pytest -m live
```

## Licence

Copyright (c) 2026 Morten Olav Hansen. All rights reserved. The source is published for
reference only: no licence to use, copy, modify or distribute it is granted, and any use
beyond reading requires written permission.
