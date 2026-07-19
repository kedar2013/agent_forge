"""Backing tables for the saga/compensation worked example — see
app/tool_registry/reservation_demo_tool.py (the in-process ADK-tool saga)
and app/durable_workflow/ (the SAME saga, durably orchestrated by a real
Temporal workflow instead). Not a real inventory system: exists purely so
'reserve' has something real to decrement and 'release' something real to
increment back, proving compensation actually fires end-to-end rather than
just being structurally wired up."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ReliabilityDemoInventory(Base):
    __tablename__ = "reliability_demo_inventory"

    item: Mapped[str] = mapped_column(String, primary_key=True)
    available: Mapped[int] = mapped_column(Integer, nullable=False)


RESERVATION_STATUSES = ("reserved", "confirmed", "released")


class TemporalReservation(Base):
    """Idempotency-key tracking for app.durable_workflow's Temporal-backed
    saga, keyed by `id` (the workflow supplies a stable reservation id —
    Temporal workflow code is deterministic/replay-safe, so the SAME id is
    generated across a replay). An activity retried by Temporal's own
    at-least-once execution guarantee checks this row first rather than
    blindly re-applying its effect a second time — the actual "idempotency
    keys on tool calls" this table exists to demonstrate, distinct from
    Temporal's own workflow-history replay (which handles replaying
    WORKFLOW code safely, not the external side effects its activities
    cause)."""

    __tablename__ = "temporal_reservations"
    __table_args__ = (CheckConstraint(f"status IN {RESERVATION_STATUSES}", name="temporal_reservations_status_check"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    item: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="reserved")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
