# The `chap` connection

One `chap` connection is one Chap server and, when the server wants one, its API token. Every
block in this pack takes a `connection` field naming one by its `code`, and builds its client
from it: the URL, the token, the TLS setting and the timeout all come from the connection,
never from a step.

## Settings

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `base_url` | `string` | yes |  | The server root every request path is resolved against, such as `http://localhost:8000`. |
| `api_token` | `string (password) or null` |  | `null` | The server's API token, sent as `Authorization: Bearer`: visible ASCII with no whitespace. Leave it unset for a server without auth. |
| `verify_tls` | `boolean` |  | `true` | Whether certificates are verified; turning this off is a per-connection decision. |
| `timeout` | `string (humane-duration)` |  | `"30s"` | The timeout applied to each read of every request through this connection. |
| `request_deadline` | `string (humane-duration)` |  | `"10m"` | The longest one request through this connection may take, start to last byte. |
| `max_response` | `string (size) or integer` |  | `"64MB"` | The most one response through this connection may decode to; a larger one is refused. |

`api_token` is the secret field: it is encrypted at rest with the instance key and redacted in
every read.

An `api_token` holding anything but visible ASCII, such as the trailing newline a pasted or
file-read token brings with it, is refused when the connection is created or updated, because it
cannot be sent as a header value. The refusal does not repeat the value. An empty one is read as
unset. A row stored before this rule fails when it is next read, so its check is unhealthy and its
steps fail until the token is set again. A token that was already written into a check's detail or a
step's error should be rotated.

## What one answer may cost

The connection holds Chap to two limits, on every request a block makes and on the health check.

- `max_response` is counted as a body decodes, so a small compressed answer stops at the limit rather
  than expanding in the worker's memory. Past it the check is unhealthy and the step fails as
  `chap.response_too_large`, class `rejected`. Raise it if a real read needs more. An error answer past
  it does not fail this way: only its opening is read, and its status still classifies it.
- `request_deadline` covers one request start to last byte. `timeout` limits each read instead, so a
  server sending a byte at a time never reaches it. Past the deadline the check is unhealthy and the
  step fails as `chap.past_deadline`, class `transient`, so a retry follows the step's own policy.

A failed job whose log cannot be read within these limits still fails with its own error, and a cancel
reads only the status of its answer.

## Two auth modes

Chap's authentication is opt-in, and the connection follows whichever mode the server runs in:

- **No auth.** A server started without `CHAP_API_TOKEN` -- `docker compose up` in a chap-core
  checkout, out of the box -- takes every call without a credential. Leave `api_token` unset and
  the blocks send no `Authorization` header at all.
- **Token.** A server started with `CHAP_API_TOKEN` set refuses every call but `/health` and
  `/system/info` without it. Set `api_token` to the same value and every block sends
  `Authorization: Bearer <token>`.

## The health check

The check asks `GET /system/info`, which Chap always answers without a token, and reports the
`chap_core_version` it gives as the connection's version. That answer also says whether the
server wants a token, in `auth_required`:

| The server | The connection | The check |
| --- | --- | --- |
| Wants no token | Carries none | Healthy. |
| Wants a token | Carries none | Unhealthy: `chap.connection.auth_required`. |
| Either | Carries a token | Proves it on `GET /v1/crud/configured-models`: healthy when Chap takes it, unhealthy with `chap.connection.token_refused` on a 401 or 403. |

A server that does not answer is unhealthy with `chap.connection.unreachable`. The check never
raises.

## Creating one

A local server without auth:

```bash
dg connection create chap chap-local \
  --name "Local Chap" \
  --set base_url=http://localhost:8000
```

A server with auth:

```bash
dg connection create chap chap-prod \
  --name "Chap" \
  --set base_url=https://chap.example.org \
  --set api_token="$CHAP_API_TOKEN"
```

To run one locally, start chap-core with `docker compose up` in its checkout (it serves on
port 8000; image `ghcr.io/dhis2-chap/chap-core:<tag>`), with `CHAP_API_TOKEN` exported to turn
auth on.
