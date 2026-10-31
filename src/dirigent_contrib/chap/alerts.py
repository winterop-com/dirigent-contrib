"""Chap's alert release gate: ``chap.alerts.record`` raises alerts, ``chap.alerts.reviewed`` waits on their review.

An alert lands in Chap as ``pending``, and a reviewer moves it to ``approved`` or ``declined``
through ``POST /v1/crud/alerts/$approve`` from wherever they work. These blocks never decide
on an alert: they record them, read where each one stands, and hand the decided ones on.
"""

from datetime import timedelta
from typing import ClassVar, Final, Literal

from pydantic import BaseModel, Field, JsonValue

from dirigent_common import BlockModel
from dirigent_contrib.chap.bodies import PassThroughConfig, body_of
from dirigent_contrib.chap.connection import client_for
from dirigent_contrib.chap.messages import ALERTS_NOT_A_LIST, ALERTS_NOT_RECORDED, ALERTS_REVIEWING
from dirigent_contrib.chap.web import call_json, mapping
from dirigent_contrib.limits import BoundedClient
from dirigent_plugin import (
    BlockFailure,
    ConnectionRef,
    ErrorClass,
    NotYet,
    Operator,
    OperatorSpec,
    Sensor,
    SensorSpec,
    StepContext,
)

ALERTS_PATH: Final = "/v1/crud/alerts"

#: The gate states that are a reviewer's decision. Any other state, ``pending`` or one Chap adds
#: later, is still waiting on one.
APPROVED: Final = "approved"
DECLINED: Final = "declined"

#: How often the review is looked at when the step does not say: a person decides, not a job.
REVIEW_POLL: Final = timedelta(minutes=5)

#: How long the review may take when the step does not say.
REVIEW_DEADLINE: Final = timedelta(days=3)

type Release = Literal["all", "any"]


class ChapAlertsListConfig(BlockModel):
    """Which alerts a step looks at."""

    connection: ConnectionRef
    """The code of the chap connection naming the server."""

    prediction_id: int | None = None
    """Only the alerts this prediction raised; every prediction's when unset."""

    alert_policy_id: int | None = None
    """Only the alerts raised against this policy; every policy when unset."""

    org_units: list[str] | None = None
    """Only the alerts for these org units; every org unit when unset."""


class ChapAlertCounts(BlockModel):
    """How many alerts stand where in the release gate."""

    total: int = 0
    """Every alert the step looked at."""

    approved: int = 0
    """The alerts cleared for release."""

    declined: int = 0
    """The alerts decided against."""

    pending: int = 0
    """The alerts still waiting on a reviewer."""


class ChapAlertsOutput(BlockModel):
    """The alerts, split by where they stand in the release gate."""

    approved: list[JsonValue] = Field(default_factory=list[JsonValue])
    """The alerts a reviewer cleared for release, as Chap answers with them: `{id, timePeriod, orgUnit,
    alertPolicyId, level, predictionId, approvedBy, approvedAt, ...}`."""

    declined: list[JsonValue] = Field(default_factory=list[JsonValue])
    """The alerts a reviewer decided not to release, in the same shape."""

    pending: list[JsonValue] = Field(default_factory=list[JsonValue])
    """The alerts nobody has decided on yet, in the same shape."""

    counts: ChapAlertCounts = Field(default_factory=ChapAlertCounts)
    """How many alerts there are, and how many of them are approved, declined and pending."""


async def list_alerts(
    client: BoundedClient, config: "ChapAlertsListConfig | ChapAlertsReviewedConfig"
) -> ChapAlertsOutput:
    """Read the alerts a step looks at, and split them by their gate state."""
    params: dict[str, int] = {}
    if config.prediction_id is not None:
        params["predictionId"] = config.prediction_id
    if config.alert_policy_id is not None:
        params["alertPolicyId"] = config.alert_policy_id
    answer = await call_json(client, "GET", ALERTS_PATH, params=params)
    if not isinstance(answer, list):
        raise BlockFailure(ALERTS_NOT_A_LIST, error_class=ErrorClass.UNKNOWN, where=f"GET {ALERTS_PATH}")
    wanted = set(config.org_units) if config.org_units is not None else None
    output = ChapAlertsOutput()
    for alert in answer:
        if wanted is not None and mapping(alert).get("orgUnit") not in wanted:
            continue
        state = mapping(alert).get("approved")
        if state == APPROVED:
            output.approved.append(alert)
        elif state == DECLINED:
            output.declined.append(alert)
        else:
            output.pending.append(alert)
    output.counts = ChapAlertCounts(
        total=len(output.approved) + len(output.declined) + len(output.pending),
        approved=len(output.approved),
        declined=len(output.declined),
        pending=len(output.pending),
    )
    return output


class ChapAlertsReviewedConfig(BlockModel):
    """Which prediction's alerts to wait on, and when their review counts as done."""

    connection: ConnectionRef
    """The code of the chap connection naming the server."""

    prediction_id: int
    """The prediction whose alerts are waited on, as `chap.prediction.run` outputs it."""

    alert_policy_id: int | None = None
    """Only the alerts raised against this policy; every policy when unset."""

    org_units: list[str] | None = None
    """Only the alerts for these org units; every org unit when unset."""

    release: Release = "all"
    """When the wait ends: `all` once no alert is pending, `any` as soon as one is decided. A
    prediction that raised no alerts ends it at once either way."""


class ChapAlertsReviewedSensor(Sensor[ChapAlertsReviewedConfig, ChapAlertsOutput]):
    """Waits for a reviewer to decide on a prediction's alerts in Chap; each poke is one listing."""

    spec = SensorSpec(
        id="chap.alerts.reviewed",
        summary="Wait for a Chap prediction's alerts to be reviewed.",
        default_poll=REVIEW_POLL,
        default_deadline=REVIEW_DEADLINE,
    )
    config_model: ClassVar[type[BaseModel]] = ChapAlertsReviewedConfig
    output_model: ClassVar[type[BaseModel]] = ChapAlertsOutput

    async def poke(self, config: ChapAlertsReviewedConfig, ctx: StepContext) -> ChapAlertsOutput | NotYet:
        """List the prediction's alerts once, and succeed when the review is as far as `release` asks.

        A refusal Chap answers with fails the poke, classified as every block in the pack
        classifies one: a 5xx and a 429 are retried, any other 4xx is not.
        """
        async with client_for(ctx, config.connection) as client:
            alerts = await list_alerts(client, config)
        counts = alerts.counts
        reviewed = counts.approved + counts.declined
        done = counts.pending == 0 if config.release == "all" else reviewed > 0
        if counts.total == 0 or done:
            return alerts
        return NotYet(
            message=ALERTS_REVIEWING.render(reviewed=reviewed, total=counts.total),
            progress=reviewed / counts.total,
        )


class ChapAlertsListOperator(Operator[ChapAlertsListConfig, ChapAlertsOutput]):
    """Reads where alerts stand in the release gate, once, without waiting on anything."""

    spec = OperatorSpec(id="chap.alerts.list", summary="List Chap alerts by their review state.", idempotent=True)
    config_model: ClassVar[type[BaseModel]] = ChapAlertsListConfig
    output_model: ClassVar[type[BaseModel]] = ChapAlertsOutput

    async def execute(self, config: ChapAlertsListConfig, ctx: StepContext) -> ChapAlertsOutput:
        """List the alerts once."""
        async with client_for(ctx, config.connection) as client:
            return await list_alerts(client, config)


class ChapAlertsRecordConfig(PassThroughConfig):
    """The alerts to record; any undeclared key is sent to Chap as written."""

    alerts: list[dict[str, JsonValue]] = Field(min_length=1)
    """The alerts as Chap spells them: `{timePeriod, orgUnit, alertPolicyId, level, predictionId}`, each
    `level` one the policy defines."""


class ChapAlertsRecordOutput(BlockModel):
    """The alerts Chap recorded."""

    alert_ids: list[int]
    """The recorded alerts' ids, in the order they were sent; each starts `pending`."""

    count: int
    """How many alerts were recorded."""


class ChapAlertsRecordOperator(Operator[ChapAlertsRecordConfig, ChapAlertsRecordOutput]):
    """Records a batch of alerts against a policy, all of them or none."""

    spec = OperatorSpec(id="chap.alerts.record", summary="Record alerts in Chap's review queue.")
    config_model: ClassVar[type[BaseModel]] = ChapAlertsRecordConfig
    output_model: ClassVar[type[BaseModel]] = ChapAlertsRecordOutput

    async def execute(self, config: ChapAlertsRecordConfig, ctx: StepContext) -> ChapAlertsRecordOutput:
        """Record the batch once.

        An unknown policy, level or prediction, and a second alert for the same prediction,
        org unit and period, are answered 422 and never retried.
        """
        body = body_of(config, "alerts")
        async with client_for(ctx, config.connection) as client:
            answer = mapping(await call_json(client, "POST", ALERTS_PATH, json=body))
        ids = answer.get("ids")
        if not isinstance(ids, list) or not all(isinstance(alert_id, int) for alert_id in ids):
            raise BlockFailure(ALERTS_NOT_RECORDED, error_class=ErrorClass.UNKNOWN, where=f"POST {ALERTS_PATH}")
        alert_ids = [alert_id for alert_id in ids if isinstance(alert_id, int)]
        ctx.log.info("alerts recorded", count=len(alert_ids))
        return ChapAlertsRecordOutput(alert_ids=alert_ids, count=len(alert_ids))
