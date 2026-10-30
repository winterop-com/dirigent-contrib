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
| [chap-models.yaml](chap-models.yaml) | List the models a Chap server has configured. |
| [chap-import-dataset-dry-run.yaml](chap-import-dataset-dry-run.yaml) | Send observations to Chap as a dry run and read which ones it would reject. |
| [chap-backtest.yaml](chap-backtest.yaml) | Backtest one Chap model on a stored dataset and read its metrics. |
| [chap-predict-and-read.yaml](chap-predict-and-read.yaml) | Forecast with a Chap prediction setup and read the forecast at three quantiles. |
| [chap-thresholds.yaml](chap-thresholds.yaml) | Compute the endemic channel's lower and upper edge for a stored Chap dataset. |

The climate-and-health loop, which reads the open climate service before it writes to Chap,
is on its own shelf: [`../chap-climate/`](../chap-climate). The alert review, which waits on
Chap and then messages districts through DHIS2, is on [`../chap-dhis2/`](../chap-dhis2).
