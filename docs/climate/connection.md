# The `climate` connection

One `climate` connection is one instance of the open climate service. Every block in this pack
takes a `connection` field naming one by its `code`, and builds its client from it: the URL, the
extra headers, the TLS setting and the timeout all come from the connection, never from a step.
The service has no authentication of its own.

## Settings

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `base_url` | `string` | yes |  | The service root every request path is resolved against, such as `https://climate-demo.dhis2.org/ocs`. |
| `headers` | `object of string` |  |  | Extra headers sent on every request, for an instance behind a proxy that wants them. They are stored as written, not as secrets. |
| `verify_tls` | `boolean` |  | `true` | Whether certificates are verified; turning this off is a per-connection decision. |
| `timeout` | `string (humane-duration)` |  | `"30s"` | The timeout applied to each read of every request through this connection, unless a block says otherwise. |
| `request_deadline` | `string (humane-duration)` |  | `"10m"` | The longest one request through this connection may take, start to last byte, unless a block says otherwise. |
| `max_response` | `string (size) or integer` |  | `"64MB"` | The most one response through this connection may decode to, unless a block says otherwise; a larger one is refused. |

`headers` is for an instance behind a proxy that wants a header of its own on every request.
They are stored as written rather than encrypted, so a credential the proxy wants is better
kept in the proxy than here. A header that cannot be sent, such as a value with the trailing newline
a pasted or file-read value brings with it, is refused when the connection is created or updated,
and the refusal does not repeat it.

A block that waits on the service longer than the connection's `timeout` says so itself:
`climate.aggregate` takes a `timeout` of its own, 5m by default, because an aggregation over a
long range is answered in minutes. It limits each read and the whole request, in place of the
connection's `timeout` and `request_deadline`.

## What one answer may cost

The connection holds the service to two limits, on every request a block makes and on the health
check.

- `max_response` is counted as a body decodes, so a small compressed answer stops at the limit rather
  than expanding in the worker's memory or filling the run's storage. Past it the check is unhealthy
  and the step fails as `climate.response_too_large`, class `rejected`, with no more than the limit
  written to storage. `climate.aggregate` and `climate.job.result` take a `max_response` of their own for
  a payload known to be large. An error answer past it does not fail this way: only its opening is read,
  and its status still classifies it.
- `request_deadline` covers one request start to last byte. `timeout` limits each read instead, so a
  service sending a byte at a time never reaches it. Past the deadline the check is unhealthy and the
  step fails as `climate.past_deadline`, class `transient`, so a retry follows the step's own policy.
  It covers a download as well, so raise it for a payload that takes longer than 10m to arrive.

## The health check

The check asks `GET /health` and `GET /info`, and reports the service's `app_version` as the
connection's version:

| `/health` says | `/info` says | The check |
| --- | --- | --- |
| `healthy` | | Healthy. |
| `degraded` | | Healthy, with `climate.connection.unhealthy` as its detail. |
| `unhealthy`, or an error | | Unhealthy. |
| | `read_only: true` | The detail adds `climate.connection.read_only`: the instance reads and aggregates, and refuses every job, ingestion, sync and export. |

A service that does not answer is unhealthy with `climate.connection.unreachable`. The check
never raises.

## Creating one

```bash
dg connection create climate climate-demo \
  --name "Open climate service demo" \
  --set base_url=https://climate-demo.dhis2.org/ocs
```

The public demo is writable, but it is shared: the examples that write point at a service you
run yourself, on `http://localhost:9000`.
