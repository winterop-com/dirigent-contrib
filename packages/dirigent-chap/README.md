# dirigent-chap

The Chap pack for [dirigent](https://github.com/winterop-com/dirigent). It contributes the
`chap` connection kind and the blocks that drive one Chap (chap-core) server: import
observations as a dataset, run a backtest, forecast from a saved prediction setup, read the
forecast's quantiles, list the configured models, compute the endemic channel, and record a
forecast's alerts and wait for a person to review them in Chap.

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

```bash
uv add dirigent-chap
```

Documentation: <https://winterop-com.github.io/dirigent-contrib/chap/>.

## Licence

Copyright (c) 2026 Morten Olav Hansen. All rights reserved. The source is published for
reference only: no licence to use, copy, modify or distribute it is granted, and any use
beyond reading requires written permission.
