# dirigent-climate

The open climate service pack for [dirigent](https://github.com/winterop-com/dirigent). It
contributes the `climate` connection kind and the blocks that drive one instance of the open
climate service: list its datasets, aggregate one to org units, run a batch job and download
what it made, deliver a saved export to DHIS2, and ingest or sync a managed dataset.

| Block | Kind | What it does |
| --- | --- | --- |
| `climate.datasets.list` | operator | Lists the published datasets. |
| `climate.aggregate` | operator | Runs a process graph synchronously and keeps its payload. |
| `climate.job.run` | operator, probed | Runs a process graph as an openEO batch job. |
| `climate.job.result` | operator | Downloads a finished job's payload into the run's storage. |
| `climate.export` | operator, probed | Delivers a job's saved export through the service's own DHIS2 connection. |
| `climate.ingest` | operator, probed | Creates or updates a managed dataset. |
| `climate.sync` | operator, probed | Brings a managed dataset forward from its latest time step. |

```bash
uv add dirigent-climate
```

Documentation: <https://winterop-com.github.io/dirigent-contrib/climate/>.

## Licence

Copyright (c) 2026 Morten Olav Hansen. All rights reserved. The source is published for
reference only: no licence to use, copy, modify or distribute it is granted, and any use
beyond reading requires written permission.
