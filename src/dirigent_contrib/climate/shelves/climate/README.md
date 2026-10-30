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
| [climate-datasets.yaml](climate-datasets.yaml) | List the datasets the open climate service has published. |
| [climate-aggregate-to-dhis2.yaml](climate-aggregate-to-dhis2.yaml) | Aggregate daily rainfall to org units as a set of DHIS2 data values. |
| [climate-batch-and-export.yaml](climate-batch-and-export.yaml) | Aggregate climate data in a batch job, then rehearse sending it to DHIS2. |
| [climate-ingest.yaml](climate-ingest.yaml) | Bring a dataset into the open climate service and follow the job to the end. |
| [climate-sync.yaml](climate-sync.yaml) | Bring a climate dataset up to date with the newest data from its source. |

Documents that carry the payload out of the service into another pack's blocks are on their
own shelf: [`../climate-dhis2/`](../climate-dhis2).
