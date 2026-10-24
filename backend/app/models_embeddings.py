"""Stored dense embeddings per chunk and model (core/dense.py). Owner-scoped (RLS); deleted with the chunk."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .models import _now, _uuid


class ChunkEmbedding(Base):
    __tablename__ = "chunk_embeddings"
    __table_args__ = (UniqueConstraint("chunk_id", "model", name="uq_chunk_embeddings_chunk_model"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    chunk_id: Mapped[str] = mapped_column(ForeignKey("chunks.id", ondelete="CASCADE"), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    model: Mapped[str] = mapped_column(String(64))  # "<provider>:<model>"
    dim: Mapped[int] = mapped_column(Integer)
    vector: Mapped[bytes] = mapped_column(LargeBinary)  # float32, L2-normalised
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
