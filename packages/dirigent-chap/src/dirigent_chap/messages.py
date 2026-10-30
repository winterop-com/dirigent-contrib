"""Every refusal the Chap pack makes, catalogued under the ``chap`` prefix."""

from dirigent_common import Catalogue

CHAP = Catalogue("chap")

ANSWERED = CHAP.define("answered", "{where} answered {status}: {remote}")

NOT_JSON = CHAP.define("not_json", "{where} answered with a body that is not JSON")

CONNECTION_UNREACHABLE = CHAP.define("connection.unreachable", "Chap did not answer: {detail}")

CONNECTION_AUTH_REQUIRED = CHAP.define(
    "connection.auth_required",
    "Chap requires an API token on every call but /system/info, and this connection carries none",
)

CONNECTION_TOKEN_REFUSED = CHAP.define("connection.token_refused", "Chap refused the API token: {detail}")

JOB_RUNNING = CHAP.define("job.running", "job {job} is {status}")

JOB_FAILED = CHAP.define("job.failed", "job {job} ended {status}: {error}")

JOB_UNKNOWN = CHAP.define("job.unknown", "Chap no longer knows job {job}")

JOB_UNSETTLED = CHAP.define(
    "job.unsettled",
    "job {job} is {status} rather than SUCCESS, so it has no result to collect",
)

OBSERVATIONS_MISSING = CHAP.define(
    "observations.missing",
    "a step that sends observations to Chap needs provided_data, csv, or both",
)

CSV_MISSING_COLUMN = CHAP.define("csv.missing_column", "the csv has no {column} column, which every row needs")

CSV_BAD_VALUE = CHAP.define("csv.bad_value", "the csv's {column} on line {line} is '{value}', which is not a number")

DATASET_REJECTED = CHAP.define(
    "dataset.rejected",
    "Chap rejected {count} of the observations and on_rejected is fail, so nothing was imported: {detail}",
)

JOB_NOT_SUBMITTED = CHAP.define("job.not_submitted", "{where} answered without a job id to follow")
