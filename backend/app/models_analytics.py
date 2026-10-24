"""First-party product analytics: what happened, never what it said.

One row per product event (event name + a few allowlisted, content-free properties), owned by
the user it describes, so RLS isolates it and account deletion removes it. Used for the
activation metric and onboarding experiments (docs/ux-research.md). Purged by retention.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .models import _now, _uuid


class ProductEvent(Base):
    __tablename__ = "product_events"
    __table_args__ = (Index("ix_product_events_owner_name", "owner_id", "name"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(40))
    props: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
