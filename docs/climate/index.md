# dirigent-climate

**The open climate service pack for dirigent.**

The open climate service ingests climate and population datasets -- CHIRPS, ERA5-Land,
WorldPop -- keeps them current, and aggregates them to org units, synchronously or as openEO
batch jobs, into the shapes DHIS2 and Chap read. This pack makes each of those a step:

| Block | What it does |
| --- | --- |
| [`climate.datasets.list`](blocks.md#climatedatasetslist) | Lists the published datasets. |
| [`climate.aggregate`](blocks.md#climateaggregate) | Runs a process graph synchronously and keeps its payload. |
| [`climate.job.run`](blocks.md#climatejobrun) | Runs a process graph as an openEO batch job. |
| [`climate.job.result`](blocks.md#climatejobresult) | Downloads a finished job's payload into the run's storage. |
| [`climate.export`](blocks.md#climateexport) | Delivers a job's saved export through the service's own DHIS2 connection. |
| [`climate.ingest`](blocks.md#climateingest) | Creates or updates a managed dataset. |
| [`climate.sync`](blocks.md#climatesync) | Brings a managed dataset forward from its latest time step. |

All of them are configured from one [`climate` connection](connection.md). The
[examples](examples.md) are runnable documents for each, and one that carries the result into
DHIS2 through `dirigent-dhis2`.

## Two ways into DHIS2

An aggregation the service shapes as a dataValueSet reaches DHIS2 one of two ways, and the
pack supports both:

- **The service delivers it.** `climate.job.run` runs `aggregate_to_dhis2_json`, and
  `climate.export` hands the saved payload to the service's own delivery, which sends it with
  the DHIS2 credentials the service holds and reports back.
- **The run imports it.** `climate.job.result` downloads the payload into the run's storage and
  `dhis2.data_value_set_import` from `dirigent-dhis2` imports it with a `dhis2` connection the
  instance holds, so the import summary, its conflicts and the retry policy are the run's own.

## Payloads go to storage

A payload the service answers with -- an aggregation, a job's result asset -- is streamed into the
run's storage, never held whole: the output always carries its `uri`. One no larger than the
instance lets a block inline is also in the output, decoded into `value` (JSON) or `text` (CSV),
the two fields `storage.read` decodes into, so a small dataValueSet feeds the next step with no
read in between and a large one is read back from `uri`.

## Rehearsed against

| The open climate service | How |
| --- | --- |
| 0.1.1, at commit `1ad5d7c9` of `dhis2/open-climate-service` | Every request and answer shape in the tests is taken from its OpenAPI document and its source: `openeo/routes.py` and `jobs.py` for batch jobs and their result assets, `ingestions/routes.py` for the asynchronous ingest and sync, `exports/routes.py` and `report.py` for delivery, and the three workflows under `plugins/workflows/`. |
| The public demo at `https://climate-demo.dhis2.org/ocs`, 0.1.1 | Read live: `/health`, `/info` (`read_only: false`) and `/datasets?f=json`. Nothing that creates a job, an ingestion, a sync or an export was sent to it. |

Unit tests answer every block from a scripted service; nothing in them reaches the network.
