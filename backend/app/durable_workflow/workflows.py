"""The reservation-demo saga, durably orchestrated by Temporal — reserve,
then confirm; if confirm fails, compensate by releasing the reservation,
then re-raise so the workflow itself reports failed (matching
reservation_demo_tool's "the turn needs to actually fail, not just narrate
a failure" intent). Same three-step shape as
app.reliability.compensation's in-process saga, but durable across a
WORKER PROCESS crash: Temporal persists this workflow's history after
every activity completes, so a worker that dies between reserve and
confirm doesn't lose the reservation or leave inventory silently
decremented forever — a new worker picks up exactly where the last one
left off, replaying this same deterministic code up to that point.

`workflow.info().workflow_id` doubles as the reservation's idempotency key
(see activities.py's TemporalReservation) — stable across a replay (part
of the workflow's own immutable identity, not re-derived with anything
random) and, as a bonus, Temporal itself deduplicates a second `start` call
with the same workflow_id, so starting "the same" reservation twice from
the caller's side is already safe before this module's own idempotency
check ever runs.
"""

from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from app.durable_workflow.activities import (
        ConfirmInput,
        ReleaseInput,
        ReserveInput,
        ReserveResult,
    )


@dataclass
class ReservationSagaInput:
    item: str
    quantity: int
    order_id: str


@dataclass
class ReservationSagaResult:
    status: str  # "confirmed" | "insufficient_inventory" | "compensated"
    reservation_id: str
    detail: str | None = None


@workflow.defn
class ReservationSagaWorkflow:
    @workflow.run
    async def run(self, input: ReservationSagaInput) -> ReservationSagaResult:
        reservation_id = workflow.info().workflow_id

        reserve_result: ReserveResult = await workflow.execute_activity(
            "reserve_inventory",
            ReserveInput(reservation_id=reservation_id, item=input.item, quantity=input.quantity),
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        if not reserve_result.reserved:
            return ReservationSagaResult(
                status="insufficient_inventory", reservation_id=reservation_id, detail=reserve_result.reason
            )

        try:
            await workflow.execute_activity(
                "confirm_order",
                ConfirmInput(reservation_id=reservation_id, order_id=input.order_id),
                start_to_close_timeout=timedelta(seconds=10),
                # Deliberately not retried -- a confirm failure here is a
                # business-logic decline (see activities.confirm_order's
                # FORCE_FAIL trigger), not a transient infrastructure
                # blip; retrying it would just fail again and delay
                # compensation for no benefit.
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        except ActivityError as exc:
            await workflow.execute_activity(
                "release_inventory",
                ReleaseInput(reservation_id=reservation_id),
                start_to_close_timeout=timedelta(seconds=10),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            return ReservationSagaResult(
                status="compensated", reservation_id=reservation_id, detail=str(exc.cause or exc)
            )

        return ReservationSagaResult(status="confirmed", reservation_id=reservation_id)
