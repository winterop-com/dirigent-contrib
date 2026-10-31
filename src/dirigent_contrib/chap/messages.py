"""Every refusal the Chap pack makes, catalogued under the ``chap`` prefix."""

from dirigent_common import Catalogue

CHAP = Catalogue("chap")

ANSWERED = CHAP.define("answered", "{where} answered {status}: {remote}")

NOT_JSON = CHAP.define("not_json", "{where} answered with a body that is not JSON")

BAD_API_TOKEN = CHAP.define(
    "connection.bad_api_token",
    "an api_token must be visible ASCII with no whitespace, or it cannot be sent as a header value",
)

RESPONSE_TOO_LARGE = CHAP.define(
    "response_too_large",
    "{where} answered with more than max_response ({limit} bytes) and the rest was not read; "
    "raise max_response if the answer is expected",
)

PAST_DEADLINE = CHAP.define("past_deadline", "{where} took longer than the {seconds} seconds it is allowed")

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

CSV_TOO_LARGE = CHAP.define(
    "csv.too_large", "the csv unfolds to {count} observations, more than max_observations allows ({limit})"
)

DATASET_REJECTED = CHAP.define(
    "dataset.rejected",
    "Chap rejected {count} of the observations and on_rejected is fail, so nothing was imported: {detail}",
)

JOB_NOT_SUBMITTED = CHAP.define("job.not_submitted", "{where} answered without a job id to follow")

PREDICTION_NOT_STORED = CHAP.define("prediction.not_stored", "job {job} finished without an integer prediction id")

ALERTS_REVIEWING = CHAP.define("alerts.reviewing", "{reviewed} of {total} reviewed")

ALERTS_NOT_A_LIST = CHAP.define("alerts.not_a_list", "{where} answered with something other than a list of alerts")

ALERTS_OUTSIDE = CHAP.define(
    "alerts.outside", "{where} answered with an alert whose {field} is not the {asked} asked for"
)

ALERTS_NOT_RECORDED = CHAP.define("alerts.not_recorded", "{where} answered without the ids of the alerts it recorded")
