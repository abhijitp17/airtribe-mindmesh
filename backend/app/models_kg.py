"""Knowledge graph, P1 foundation: concept nodes and prerequisite edges per user.

Stored in Postgres/SQLite like everything else (decision: docs/DECISIONS.md #23), so
owner_id + RLS isolate it and deleting an account removes it. Edges written here are
unverified planner output; P2 grounds them in page quotes before the product uses them
to explain a weakness.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .models import _now, _uuid


class KgNode(Base):
    __tablename__ = "kg_nodes"
    __table_args__ = (UniqueConstraint("owner_id", "kind", "canonical_key", name="uq_kg_nodes_owner_kind_key"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16), default="concept")  # concept (competency, topic later)
    name: Mapped[str] = mapped_column(String(120))  # display name, first spelling seen
    canonical_key: Mapped[str] = mapped_column(String(120))  # knowledge_graph.canonical_key(name)
    # Set when this concept was merged into another (P2 concept merging); its edges moved there.
    merged_into_id: Mapped[str | None] = mapped_column(ForeignKey("kg_nodes.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class KgEdge(Base):
    __tablename__ = "kg_edges"
    __table_args__ = (
        UniqueConstraint("owner_id", "src_id", "dst_id", "rel", name="uq_kg_edges_owner_src_dst_rel"),
        CheckConstraint("src_id <> dst_id", name="ck_kg_edges_no_self_loop"),
        Index("ix_kg_edges_owner_dst_rel", "owner_id", "dst_id", "rel"),
        Index("ix_kg_edges_owner_src_rel", "owner_id", "src_id", "rel"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    src_id: Mapped[str] = mapped_column(ForeignKey("kg_nodes.id", ondelete="CASCADE"))
    dst_id: Mapped[str] = mapped_column(ForeignKey("kg_nodes.id", ondelete="CASCADE"))
    rel: Mapped[str] = mapped_column(String(24))  # prerequisite_of | covers | same_as | maps_to (see services/graph.py)
    source: Mapped[str] = mapped_column(String(16))  # planner | user (rule, model later)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)  # grounded in a page quote (P2)
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)  # goal_id, source_chunk_ids, ...
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
