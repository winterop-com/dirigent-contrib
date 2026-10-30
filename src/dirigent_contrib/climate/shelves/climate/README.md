# Climate examples: the native blocks

These pipelines use the `climate.*` blocks the open climate service pack contributes, against one
instance of the open climate service. Each is one operation, small enough to read in a sitting
and to lift into a real pipeline unchanged.

The documents that only read carry `climate-demo`, the public demo at
`https://climate-demo.dhis2.org/ocs`. The ones that write -- a batch job, a delivery, an
ingestion, a sync -- carry `climate-local`, a service you run yourself on port 9000, because
the demo is shared.

| File | The operation |
| --- | --- |
| [climate-datasets.yaml](climate-datasets.yaml) | List the published datasets, with their period types and extents. |
| [climate-aggregate-to-dhis2.yaml](climate-aggregate-to-dhis2.yaml) | Aggregate a dataset to org units as a DHIS2 dataValueSet, synchronously. |
| [climate-batch-and-export.yaml](climate-batch-and-export.yaml) | The same as a batch job, then the service's own delivery to DHIS2 as a dry run. |
| [climate-ingest.yaml](climate-ingest.yaml) | Create or update a managed dataset. |
| [climate-sync.yaml](climate-sync.yaml) | Bring a managed dataset forward to its source's newest data. |

Documents that carry the payload out of the service into another pack's blocks are on their
own shelf: [`../climate-dhis2/`](../climate-dhis2).
