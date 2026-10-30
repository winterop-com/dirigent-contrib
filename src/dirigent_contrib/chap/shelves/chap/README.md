# Chap examples: the native blocks

These pipelines use the `chap.*` blocks the Chap pack contributes. Each one is a
single operation against one Chap server, small enough to read in a sitting and to lift into
a real pipeline unchanged.

Each document carries a `chap-local` connection: a chap-core server started with
`docker compose up` in a chap-core checkout, on port 8000, with `CHAP_API_TOKEN` unset. A
server that sets it wants the token on the connection; every block sends it as
`Authorization: Bearer`.

| File | The operation |
| --- | --- |
| [chap-models.yaml](chap-models.yaml) | List the configured models a backtest names. |
| [chap-import-dataset-dry-run.yaml](chap-import-dataset-dry-run.yaml) | Validate observations as a dry run and read the rejections. |
| [chap-backtest.yaml](chap-backtest.yaml) | Backtest a model on a stored dataset, with the server's saved defaults. |
| [chap-predict-and-read.yaml](chap-predict-and-read.yaml) | Forecast from a prediction setup, then read its quantiles. |
| [chap-thresholds.yaml](chap-thresholds.yaml) | Compute the endemic channel for a stored dataset. |

The climate-and-health loop, which reads the open climate service before it writes to Chap,
is on its own shelf: [`../chap-climate/`](../chap-climate). The alert review, which waits on
Chap and then messages districts through DHIS2, is on [`../chap-dhis2/`](../chap-dhis2).
