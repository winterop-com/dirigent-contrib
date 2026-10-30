# dirigent-contrib

**Block packs for dirigent that reach outside systems, all in one package.**

| Pack | The system | What it contributes |
| --- | --- | --- |
| [Chap](chap/index.md) | Chap, the climate and health modelling platform (chap-core) | The `chap` connection kind and nine blocks: import a dataset, run a backtest, forecast from a prediction setup, read its quantiles, list the models, compute the endemic channel, and record a forecast's alerts and follow their review. |
| [The open climate service](climate/index.md) | The open climate service | The `climate` connection kind and seven blocks: list the datasets, aggregate one to org units, run a batch job and download what it made, deliver an export to DHIS2, ingest and sync a managed dataset. |

`dirigent-contrib` is one package with one version, and installing it brings both packs. Each
is a subpackage with an entry point of its own, `chap` and `climate`, and knows nothing of the
other. They are built to be used together and with
[`dirigent-dhis2`](https://winterop-com.github.io/dirigent-dhis2/), which stays a package of its
own: climate data aggregated to org units by the open climate service goes into DHIS2 as a
dataValueSet, or into Chap as the covariates of a dataset a model is evaluated and forecast on.

## How the packs are built

Every block is a step a pipeline names, configured from a connection the instance holds:

- A block that starts work the remote system runs in the background -- a Chap job, an openEO
  batch job, an ingestion, a delivery -- submits it once and hands the engine a handle. The
  engine probes the handle on a schedule, without holding a worker, and fetches the result when
  the remote says it is done. Cancelling the step cancels the remote job where the system has a
  way to.
- A refusal is classified the way the engine's retry policy needs it: a 5xx, a 429 and a
  transport failure are transient, every other 4xx is a refusal that is never retried, and the
  failure carries the system's own words.
- Every refusal the packs make is minted under a code, `chap.*` or `climate.*`, and catalogued
  on each pack's block page.

## Its relation to dirigent

Dirigent is a generic pipeline orchestrator: pipelines are documents, blocks arrive as plugin
packages, and the catalog an instance assembles from its installed packs is what validates a
pipeline and renders the builder's forms. What a pipeline, a run, a connection or a schema is,
and the whole of the CLI, live in [dirigent's own
documentation](https://winterop-com.github.io/dirigent/).

## Licence

Copyright (c) 2026 Morten Olav Hansen. All rights reserved. The source is published for
reference only: no licence to use, copy, modify or distribute it is granted, and any use
beyond reading requires written permission.
