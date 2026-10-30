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
| `timeout` | `string (humane-duration)` |  | `"30s"` | The timeout applied to every request through this connection, unless a block says otherwise. |

`headers` is for an instance behind a proxy that wants a header of its own on every request.
They are stored as written rather than encrypted, so a credential the proxy wants is better
kept in the proxy than here.

A block that waits on the service longer than the connection's `timeout` says so itself:
`climate.aggregate` takes a `timeout` of its own, 5m by default, because an aggregation over a
long range is answered in minutes.

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
