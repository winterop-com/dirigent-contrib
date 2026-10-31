"""Every refusal the climate pack makes, catalogued under the ``climate`` prefix."""

from dirigent_common import Catalogue

CLIMATE = Catalogue("climate")

ANSWERED = CLIMATE.define("answered", "{where} answered {status}: {remote}")

NOT_JSON = CLIMATE.define("not_json", "{where} answered with a body that is not JSON")

BAD_HEADER = CLIMATE.define(
    "connection.bad_header",
    "a header's name must be an HTTP token and its value visible ASCII with no leading or trailing whitespace, "
    "or it cannot be sent",
)

CONNECTION_UNREACHABLE = CLIMATE.define("connection.unreachable", "the open climate service did not answer: {detail}")

CONNECTION_UNHEALTHY = CLIMATE.define("connection.unhealthy", "the open climate service reports itself {status}")

CONNECTION_READ_ONLY = CLIMATE.define(
    "connection.read_only",
    "the open climate service is read-only: it reads and aggregates, and refuses jobs, ingestions, syncs and exports",
)

GRAPH_ONE_OF = CLIMATE.define("graph.one_of", "a step names a workflow or carries a process_graph, and exactly one")

GRAPH_MISSING = CLIMATE.define("graph.missing", "the {workflow} workflow needs {field}")

GRAPH_STRAY = CLIMATE.define("graph.stray", "{field} is an argument of {owner} only, and this step runs {workflow}")

JOB_NOT_SUBMITTED = CLIMATE.define("job.not_submitted", "{where} answered without a job id to follow")

JOB_RUNNING = CLIMATE.define("job.running", "job {job} is {status}")

JOB_FAILED = CLIMATE.define("job.failed", "job {job} ended {status}: {detail}")

JOB_UNKNOWN = CLIMATE.define("job.unknown", "the open climate service no longer knows job {job}")

JOB_NO_ASSET = CLIMATE.define(
    "job.no_asset", "job {job}'s results carry no asset named {asset}; they carry {available}"
)

JOB_ASSET_OUTSIDE = CLIMATE.define(
    "job.asset_outside", "job {job}'s asset {asset} is not served under the connection's base_url, so it was not read"
)

EXPORT_REJECTED = CLIMATE.define("export.rejected", "the target refused export {export}: {detail}")
