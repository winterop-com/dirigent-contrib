# Climate examples

The pack ships its examples inside the distribution and contributes them through the
`examples()` hook, so an instance with the pack installed lists them without a checkout:

```bash
dg examples list --plugin climate
dg examples show climate-sync-to-dhis2
```

They live in
[`src/dirigent_contrib/climate/shelves/`](https://github.com/winterop-com/dirigent-contrib/tree/main/src/dirigent_contrib/climate/shelves),
on two shelves. Each document opens with a header that says what it does and why it is
configured as it is, and carries the connections it uses, each with a name and a description.

## `climate/`: the native blocks

| Document | The operation |
| --- | --- |
| `climate-datasets` | List the datasets the open climate service has published. |
| `climate-aggregate-to-dhis2` | Aggregate daily rainfall to org units as a set of DHIS2 data values. |
| `climate-batch-and-export` | Aggregate climate data in a batch job, then rehearse sending it to DHIS2. A starter. |
| `climate-ingest` | Bring a dataset into the open climate service and follow the job to the end. |
| `climate-sync` | Bring a climate dataset up to date with the newest data from its source. |

The documents that only read carry `climate-demo`, the public demo. The ones that write carry
`climate-local`, a service you run yourself, because the demo is shared.

The aggregation at the heart of most of them:

```yaml
  aggregate:
    block: climate.aggregate
    config:
      connection: climate-demo
      workflow: aggregate_to_dhis2_json
      dataset_id: chirps3_precipitation_daily
      start: "${params.start}"
      end: "${params.end}"
      export: rainfall-daily
      method: mean
      geometries:
        type: FeatureCollection
        features: [...]
```

The `export` must be one the instance's configuration declares; it owns the data element, the
category option combos and the period type the values are written with.

## `climate-dhis2/`: into DHIS2 through `dirigent-dhis2`

`climate-sync-to-dhis2` is the nightly a climate-and-health deployment runs, in the shape of
CAPS: `climate.sync` brings the dataset forward, `climate.job.run` aggregates it with
`aggregate_to_dhis2_json` as a batch job, `climate.job.result` downloads the dataValueSet into
the run's storage, `storage.read` reads it back whatever its size, and
`dhis2.data_value_set_import` imports it -- as a dry run against the DHIS2 play demo, until it is
pointed at an instance whose org units the geometries name. It needs `dirigent-dhis2`
installed beside this pack.

```yaml
  result:
    block: climate.job.result
    depends_on: [aggregate]
    config:
      connection: climate-local
      job_id: "${steps.aggregate.output.job_id}"

  reload:
    block: storage.read
    depends_on: [result]
    config:
      source: "${steps.result.output.uri}"
      content_type: application/json
      max_size: 64mb

  load:
    block: dhis2.data_value_set_import
    depends_on: [reload]
    config:
      connection: dhis2-demo
      data_values: "${steps.reload.output.value}"
      dry_run: true
```

The Chap side of the loop, the open climate service feeding a Chap dataset and backtest, is
`climate-to-chap-backtest` on the [Chap shelves](../chap/examples.md).

## How they are tested

The pack's test suite holds every document to the catalog it contributes: each is a
`dirigent/v1` pipeline coded after its file, every step's config fits its block's published
schema, every block it names is under `requires.blocks`, every connection it carries has a name
and a description, and every `${steps.<step>.output.<field>}` names a field the earlier step
publishes and depends on. A step naming a block from elsewhere -- the engine's `storage.read`, or
`dhis2.data_value_set_import` -- is left out of the schema check: `dirigent-dhis2` is not
installed beside these tests, so its step is held to the output fields the document reads
rather than to its config schema.
