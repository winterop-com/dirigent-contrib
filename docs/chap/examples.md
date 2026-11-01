# Chap examples

The pack ships its examples inside the distribution and contributes them through the
`examples()` hook, so an instance with the pack installed lists them without a checkout:

```bash
dg examples list --plugin chap
dg examples show chap-predict-and-read
```

They live in
[`src/dirigent_contrib/chap/shelves/`](https://github.com/winterop-com/dirigent-contrib/tree/main/src/dirigent_contrib/chap/shelves),
on three shelves. Each document opens with a header that says what it does and why it is
configured as it is, and carries the connections it uses, each with a name and a description.

## `chap/`: the native blocks

| Document | The operation |
| --- | --- |
| `chap-models` | List the models a Chap server has configured. |
| `chap-import-dataset-dry-run` | Send observations to Chap as a dry run and read which ones it would reject. |
| `chap-backtest` | Backtest one Chap model on a stored dataset and read its metrics. |
| `chap-predict-and-read` | Forecast with a Chap prediction setup and read the forecast at three quantiles. A starter. |
| `chap-thresholds` | Compute the endemic channel's lower and upper edge for a stored Chap dataset. |

They carry `chap-local`, a chap-core server on `http://localhost:8000` without auth.

## `chap-climate/`: Chap fed from the open climate service

`climate-to-chap-backtest` is the climate-and-health loop in one document: `climate.aggregate`
runs the open climate service's `aggregate_to_chap_csv` workflow, `storage.read` reads the CSV
back whatever its size, `chap.dataset.import` unfolds it into observations beside the case
counts and imports them, and `chap.backtest.run` evaluates a model on the dataset. Both packs
are in `dirigent-contrib`, so it needs nothing more installed. The aggregation reads the public
demo of the open climate service; the dataset and the backtest are written to the local Chap.

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

## `chap-dhis2/`: alerts reviewed in Chap, sent through DHIS2

`chap-predict-alert-review-notify` is [alert verification](index.md#alert-verification) end to
end. `chap.prediction.run` forecasts and `chap.prediction.read` reads the 0.9 quantile;
`transform.jq` turns every cell that reaches the threshold into an alert, and
`chap.alerts.record` records them against the policy, each `pending`. `chap.alerts.reviewed`
then waits, every 10 minutes for up to two days, until a person has decided on every one of
them in Chap, from wherever they review. `dhis2.message`, from `dirigent-dhis2`, fans out over
the approved ones and messages the users assigned to each alert's org unit; a declined alert
sends nothing, and a forecast that breached nothing skips everything after `raise`. It needs
`dirigent-dhis2` installed beside this pack, and it carries `dhis2-local` beside `chap-local`,
since its last step sends real messages.

```yaml
  review:
    block: chap.alerts.reviewed
    depends_on: [forecast, record]
    poll: 10m
    deadline: 2d
    on_timeout: fail
    config:
      connection: chap-local
      prediction_id: "${steps.forecast.output.prediction_id}"
      alert_policy_id: "${params.alert_policy_id}"
      release: all

  notify:
    block: dhis2.message
    depends_on: [review]
    for_each: "${steps.review.output.approved}"
    config:
      connection: dhis2-local
      subject: "${item.level} alert for ${item.timePeriod}"
      text: "Chap forecasts an outbreak at the ${item.level} level for ${item.timePeriod}. ..."
      org_units: ["${item.orgUnit}"]
```

## Running one

A document that names a remote system cannot run against a mock, so `dg run --local` runs it
against the server its connection names:

```bash
dg run --local src/dirigent_contrib/chap/shelves/chap/chap-models.yaml
dg run --local src/dirigent_contrib/chap/shelves/chap/chap-predict-and-read.yaml -p prediction_setup_id=1
```

`--connections FILE` replaces a carried connection by code, which points a document at your
own server without editing it. A copy made with `dg pipeline new` from a starter names its
connections under `requires.connections` instead of carrying them.

## How they are tested

The pack's test suite holds every document to the catalog the packs contribute: each is a
`dirigent/v1` pipeline coded after its file, every step's config fits its block's published
schema, every block it names is under `requires.blocks`, every connection it carries has a name
and a description, and every `${steps.<step>.output.<field>}` names a field the earlier step
publishes and depends on. A step naming a block from elsewhere -- the engine's `storage.read` and
`transform.jq`, and `dhis2.message` from `dirigent-dhis2` -- is left out of the schema check,
since it is not this pack's to answer for.
