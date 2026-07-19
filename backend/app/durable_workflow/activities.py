"""Temporal Activities for the reservation-demo saga — the durable
counterpart to `app.tool_registry.reservation_demo_tool`'s in-process
reserve/confirm/release modes, operating on the SAME
`reliability_demo_inventory` table so the two approaches are directly
comparable. Each activity is idempotent against its own retry via
`TemporalReservation` (see that model's docstring for why: Temporal's
at-least-once activity execution guarantee means any activity CAN run more
than once for the same logical step, and blindly re-applying a DB mutation
on retry would be a real bug, not just a theoretical one).
"""

import logging
from dataclasses import dataclass

from sqlalchemy import select
from temporalio import activity

from app.db import async_session_factory
from app.models.reliability_demo import ReliabilityDemoInventory, TemporalReservation

logger = logging.getLogger(__name__)


@dataclass
class ReserveInput:
    reservation_id: str
    item: str
    quantity: int


@dataclass
class ReserveResult:
    reserved: bool
    remaining: int | None
    reason: str | None = None


@dataclass
class ConfirmInput:
    reservation_id: str
    order_id: str


@dataclass
class ReleaseInput:
    reservation_id: str


@activity.defn
async def reserve_inventory(input: ReserveInput) -> ReserveResult:
    async with async_session_factory() as session:
        existing = await session.get(TemporalReservation, input.reservation_id)
        if existing is not None:
            # A retry of an already-applied reservation -- report the
            # SAME outcome without decrementing inventory a second time.
            logger.info("reserve_inventory: reservation %s already applied, skipping", input.reservation_id)
            row = await session.get(ReliabilityDemoInventory, input.item)
            return ReserveResult(reserved=True, remaining=row.available if row else None)

        row = await session.get(ReliabilityDemoInventory, input.item)
        if row is None or row.available < input.quantity:
            return ReserveResult(reserved=False, remaining=row.available if row else 0, reason="Insufficient inventory")

        row.available -= input.quantity
        session.add(
            TemporalReservation(
                id=input.reservation_id, item=input.item, quantity=input.quantity, status="reserved"
            )
        )
        await session.commit()
        return ReserveResult(reserved=True, remaining=row.available)


@activity.defn
async def confirm_order(input: ConfirmInput) -> None:
    async with async_session_factory() as session:
        reservation = await session.get(TemporalReservation, input.reservation_id)
        if reservation is not None and reservation.status == "confirmed":
            return  # already applied on a prior attempt

        if input.order_id == "FORCE_FAIL":
            # The demo's deliberate failure trigger (same convention as
            # reservation_demo_tool's confirm mode) -- raises so the
            # workflow sees a real activity failure and runs compensation,
            # not a soft error a workflow would have to remember to check.
            raise RuntimeError(
                "Payment authorization declined for order FORCE_FAIL — the reliability demo's deliberate failure trigger."
            )

        if reservation is not None:
            reservation.status = "confirmed"
            await session.commit()


@activity.defn
async def release_inventory(input: ReleaseInput) -> None:
    """The compensation action — releases a reservation's held quantity
    back to available inventory. Idempotent: a reservation already
    released (or never actually reserved, e.g. reserve_inventory returned
    reserved=False) is a no-op, not an error, so the workflow can call
    this unconditionally in its compensation path without first checking
    whether reserve actually succeeded."""
    async with async_session_factory() as session:
        reservation = await session.get(TemporalReservation, input.reservation_id)
        if reservation is None or reservation.status == "released":
            return

        row = await session.get(ReliabilityDemoInventory, reservation.item)
        if row is not None:
            row.available += reservation.quantity
        reservation.status = "released"
        await session.commit()
