# Chap examples

The pack ships its examples inside the distribution and contributes them through the
`examples()` hook, so an instance with the pack installed lists them without a checkout:

```bash
dg examples list --plugin chap
dg examples show chap-predict-and-read
```

They live in
[`packages/dirigent-chap/src/dirigent_chap/shelves/`](https://github.com/winterop-com/dirigent-contrib/tree/main/packages/dirigent-chap/src/dirigent_chap/shelves),
on two shelves. Each document opens with a header that says what it does and why it is
configured as it is, and carries the connections it uses, each with a name and a description.

## `chap/`: the native blocks

| Document | The operation |
| --- | --- |
| `chap-models` | List the configured models a backtest names. |
| `chap-import-dataset-dry-run` | Validate observations as a dry run and read the rejections. |
| `chap-backtest` | Backtest a model on a stored dataset, with the server's saved defaults. |
| `chap-predict-and-read` | Forecast from a prediction setup, then read its quantiles at 0.1, 0.5 and 0.9. A starter. |
| `chap-thresholds` | Compute the lower and upper edge of the endemic channel for a stored dataset. |

They carry `chap-local`, a chap-core server on `http://localhost:8000` without auth.

## `chap-climate/`: Chap fed from the open climate service

`climate-to-chap-backtest` is the climate-and-health loop in one document: `climate.aggregate`
runs the open climate service's `aggregate_to_chap_csv` workflow, `storage.read` reads the CSV
back whatever its size, `chap.dataset.import` unfolds it into observations beside the case
counts and imports them, and `chap.backtest.run` evaluates a model on the dataset. It needs
`dirigent-climate` installed beside this pack. The aggregation reads the public demo of the
open climate service; the dataset and the backtest are written to the local Chap.

```yaml
  dataset:
    block: chap.dataset.import
    depends_on: [reload]
    config:
      connection: chap-local
      name: "rainfall and cases ${params.start} to ${params.end}"
      geojson: "${params.org_units}"
      csv: "${steps.reload.output.text}"
      provided_data: "${params.cases}"
      on_rejected: fail
```

## Running one

A document that names a remote system cannot run against a mock, so `dg run --local` runs it
against the server its connection names:

```bash
dg run --local examples/chap/chap-models.yaml
dg run --local examples/chap/chap-predict-and-read.yaml -p prediction_setup_id=1
```

`--connections FILE` replaces a carried connection by code, which points a document at your
own server without editing it. A copy made with `dg pipeline new` from a starter names its
connections under `requires.connections` instead of carrying them.

## How they are tested

The pack's test suite holds every document to the catalog the packs contribute: each is a
`dirigent/v1` pipeline coded after its file, every step's config fits its block's published
schema, every block it names is under `requires.blocks`, every connection it carries has a name
and a description, and every `${steps.<step>.output.<field>}` names a field the earlier step
publishes and depends on. A step naming a block from elsewhere -- the engine's `storage.read` --
is left out of the schema check, since it is not this pack's to answer for.
