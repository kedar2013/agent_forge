"""Backing table for the saga/compensation worked example — see
app/tool_registry/reservation_demo_tool.py and
scripts/seed_reliability_demo.py. Not a real inventory system: exists purely
so 'reserve' has something real to decrement and 'release' something real to
increment back, proving compensation actually fires end-to-end rather than
just being structurally wired up."""

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ReliabilityDemoInventory(Base):
    __tablename__ = "reliability_demo_inventory"

    item: Mapped[str] = mapped_column(String, primary_key=True)
    available: Mapped[int] = mapped_column(Integer, nullable=False)
