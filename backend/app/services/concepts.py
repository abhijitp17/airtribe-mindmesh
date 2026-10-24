"""Concept extraction as a background job (knowledge graph, P1).

After a document is processed, one fast-model call reads an outline of it (the start of
each section, plus evenly spaced excerpts when it has few headings) and lists the concepts
it teaches. Each concept must come with a quote from the excerpt it names; anything whose
quote isn't found in that excerpt is dropped, the same rule as tutor citations.

Stored in the knowledge graph as  document --covers--> concept  edges (source "model",
verified because each is grounded in a quote; the chunk id, page and quote are kept as
provenance). A "document" node stands in for the document; deleting the document removes
it and its edges. Re-running replaces the document's edges, so the job is idempotent.

Cost: one fast-tier call per document, charged to the owner's daily budget. Over budget,
the job skips quietly (concepts are a nice-to-have; nothing else depends on them yet).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..ai.gateway import BudgetExceeded, Request
from ..ai.prompts import CONCEPTS_SYSTEM, concepts_user
from ..config import get_settings
from ..core.citations import SourceRef, quote_support
from ..models import Chunk, Document
from ..models_kg import KgEdge, KgNode
from .knowledge_graph import canonical_key, upsert_concepts

log = logging.getLogger("mindmesh.concepts")

COVERS = "covers"
MAX_EXCERPTS = 30
EXCERPT_CHARS = 420
MAX_CONCEPTS = 20
MIN_QUOTE_SUPPORT = 0.9
_GENERIC = {"introduction", "summary", "conclusion", "conclusions", "overview", "contents", "table of contents",
            "preface", "index", "references", "bibliography", "exercises", "appendix", "chapter", "section"}


_NUMBERING = re.compile(r"^(?:(?:chapter|section|part|unit)\s+)?(?:\d+(?:\.\d+)*[.:)]?|[ivxlc]+[.:)])\s+", re.I)


def clean_name(raw: object) -> str:
    """Collapse spaces and drop section numbering ("1.2 Variability", "Chapter 3: Queues")."""
    return _NUMBERING.sub("", " ".join(str(raw or "").split())).strip(" .:;,-")


@dataclass
class FoundConcept:
    name: str
    chunk_id: str
    page: int
    quote: str


@dataclass
class FoundPrerequisite:
    before: str  # concept names as kept in FoundConcept
    after: str
    chunk_id: str
    page: int
    quote: str


# ---------------------------------------------------------------- pure parts

def pick_excerpts(chunks: list[Chunk], limit: int = MAX_EXCERPTS) -> list[SourceRef]:
    """First chunk of every section, topped up with evenly spaced chunks, in document order."""
    if not chunks:
        return []
    ordered = sorted(chunks, key=lambda c: c.ordinal)
    picked: dict[str, Chunk] = {}
    seen_sections: set[str] = set()
    for c in ordered:
        if c.section and c.section not in seen_sections:
            seen_sections.add(c.section)
            picked[c.id] = c
    if len(picked) > limit:  # many sections: keep an even spread of them
        heads = list(picked.values())
        step = len(heads) / limit
        picked = {h.id: h for h in (heads[int(i * step)] for i in range(limit))}
    elif len(picked) < limit:  # few headings: add evenly spaced body chunks from the rest
        rest = [c for c in ordered if c.id not in picked]
        room = min(limit - len(picked), len(rest))
        if room:
            step = len(rest) / room
            picked.update((c.id, c) for c in (rest[int(i * step)] for i in range(room)))
    chosen = sorted(picked.values(), key=lambda c: c.ordinal)
    return [SourceRef(label=f"S{n}", chunk_id=c.id, text=c.text[:EXCERPT_CHARS], page_start=c.page_start,
                      page_end=c.page_end, section=c.section) for n, c in enumerate(chosen, start=1)]


def validate_concepts(data: object, sources: list[SourceRef]) -> list[FoundConcept]:
    """Keep well-formed, quote-grounded, distinct concepts. Raises ValueError if the shape is wrong."""
    if not isinstance(data, dict) or not isinstance(data.get("concepts"), list):
        raise ValueError("expected {'concepts': [...]}")
    by_label = {s.label: s for s in sources}
    out: list[FoundConcept] = []
    keys: set[str] = set()
    for item in data["concepts"]:
        if not isinstance(item, dict):
            continue
        name = clean_name(item.get("name"))
        src = by_label.get(str(item.get("source") or "").strip())
        quote = " ".join(str(item.get("quote") or "").split())
        key = canonical_key(name)
        if (not name or len(name) > 80 or len(name.split()) > 8 or not key or key in keys or key in _GENERIC
                or src is None or len(quote.split()) < 3 or quote_support(quote, src.text) < MIN_QUOTE_SUPPORT):
            continue
        keys.add(key)
        out.append(FoundConcept(name=name, chunk_id=src.chunk_id, page=src.page_start, quote=quote[:300]))
        if len(out) >= MAX_CONCEPTS:
            break
    return out


def validate_prerequisites(data: object, sources: list[SourceRef], concepts: list[FoundConcept]) -> list[FoundPrerequisite]:
    """Grounded prerequisite edges between kept concepts: the quote must be in the excerpt it names."""
    if not isinstance(data, dict) or not isinstance(data.get("prerequisites", []), list):
        return []
    by_label = {s.label: s for s in sources}
    names = {canonical_key(c.name): c.name for c in concepts}
    out: list[FoundPrerequisite] = []
    pairs: set[tuple[str, str]] = set()
    for item in data.get("prerequisites", []):
        if not isinstance(item, dict):
            continue
        before, after = names.get(canonical_key(clean_name(item.get("before")))), names.get(canonical_key(clean_name(item.get("after"))))
        src = by_label.get(str(item.get("source") or "").strip())
        quote = " ".join(str(item.get("quote") or "").split())
        if (not before or not after or before == after or src is None or len(quote.split()) < 3
                or quote_support(quote, src.text) < MIN_QUOTE_SUPPORT):
            continue
        key = (canonical_key(before), canonical_key(after))
        if key in pairs or (key[1], key[0]) in pairs:  # duplicates and two-way claims
            continue
        pairs.add(key)
        out.append(FoundPrerequisite(before, after, src.chunk_id, src.page_start, quote[:300]))
    return out[: MAX_CONCEPTS * 2]


def validate_extraction(data: object, sources: list[SourceRef]) -> tuple[list[FoundConcept], list[FoundPrerequisite]]:
    concepts = validate_concepts(data, sources)
    return concepts, validate_prerequisites(data, sources, concepts)


# ---------------------------------------------------------------- storage

def _document_node(db: Session, doc: Document) -> KgNode:
    node = db.scalar(select(KgNode).where(KgNode.owner_id == doc.owner_id, KgNode.kind == "document",
                                          KgNode.canonical_key == doc.id))
    name = (doc.title or doc.filename or "Document")[:120]
    if node is None:
        node = KgNode(owner_id=doc.owner_id, kind="document", name=name, canonical_key=doc.id)
        db.add(node)
        db.flush()
    else:
        node.name = name
    return node


def save_document_concepts(db: Session, doc: Document, found: list[FoundConcept],
                           prerequisites: list[FoundPrerequisite] | None = None) -> int:
    node = _document_node(db, doc)
    db.execute(delete(KgEdge).where(KgEdge.owner_id == doc.owner_id, KgEdge.src_id == node.id, KgEdge.rel == COVERS))
    concepts = upsert_concepts(db, doc.owner_id, [f.name for f in found])
    added = 0
    for f in found:
        target = concepts.get(canonical_key(f.name))
        if target is None:
            continue
        db.add(KgEdge(owner_id=doc.owner_id, src_id=node.id, dst_id=target.id, rel=COVERS, source="model",
                      verified=True, provenance={"document_id": doc.id, "chunk_id": f.chunk_id, "page": f.page,
                                                 "quote": f.quote}))
        added += 1
    _save_prerequisites(db, doc, concepts, prerequisites or [])
    return added


def _save_prerequisites(db: Session, doc: Document, concepts: dict[str, KgNode], found: list[FoundPrerequisite]) -> int:
    """Replace this document's grounded prerequisite edges (source "document", verified, with the quote)."""
    from .knowledge_graph import PREREQUISITE_OF

    old = [e for e in db.scalars(select(KgEdge).where(KgEdge.owner_id == doc.owner_id, KgEdge.rel == PREREQUISITE_OF,
                                                        KgEdge.source == "document"))
           if (e.provenance or {}).get("document_id") == doc.id]
    for e in old:
        db.delete(e)
    db.flush()
    existing = {(e.src_id, e.dst_id) for e in db.scalars(select(KgEdge).where(
        KgEdge.owner_id == doc.owner_id, KgEdge.rel == PREREQUISITE_OF))}
    added = 0
    for p in found:
        a, b = concepts.get(canonical_key(p.before)), concepts.get(canonical_key(p.after))
        if not a or not b or a.id == b.id or (b.id, a.id) in existing:
            continue
        prov = {"document_id": doc.id, "chunk_id": p.chunk_id, "page": p.page, "quote": p.quote}
        if (a.id, b.id) in existing:  # the planner guessed it already: now it's grounded
            edge = db.scalar(select(KgEdge).where(KgEdge.owner_id == doc.owner_id, KgEdge.src_id == a.id,
                                                  KgEdge.dst_id == b.id, KgEdge.rel == PREREQUISITE_OF))
            if edge is not None and not edge.verified:
                edge.verified, edge.source, edge.provenance = True, "document", {**(edge.provenance or {}), **prov}
            continue
        db.add(KgEdge(owner_id=doc.owner_id, src_id=a.id, dst_id=b.id, rel=PREREQUISITE_OF, source="document",
                      verified=True, provenance=prov))
        existing.add((a.id, b.id))
        added += 1
    return added


def remove_document(db: Session, owner_id: str, document_id: str) -> None:
    """Drop the document's node and its edges (concept nodes stay: quizzes and plans share them)."""
    ids = db.scalars(select(KgNode.id).where(KgNode.owner_id == owner_id, KgNode.kind == "document",
                                             KgNode.canonical_key == document_id)).all()
    if ids:
        db.execute(delete(KgEdge).where(KgEdge.owner_id == owner_id, KgEdge.src_id.in_(ids)))
        db.execute(delete(KgNode).where(KgNode.id.in_(ids)))
    # Prerequisites grounded only in this document lose their evidence with it.
    for e in db.scalars(select(KgEdge).where(KgEdge.owner_id == owner_id, KgEdge.source == "document")):
        if (e.provenance or {}).get("document_id") == document_id:
            db.delete(e)


def document_concepts(db: Session, owner_id: str, document_id: str) -> list[dict]:
    """Concepts a document covers, in page order, with the quote that grounds each."""
    node_id = db.scalar(select(KgNode.id).where(KgNode.owner_id == owner_id, KgNode.kind == "document",
                                                KgNode.canonical_key == document_id))
    if node_id is None:
        return []
    rows = db.execute(
        select(KgNode.name, KgEdge.provenance).join(KgEdge, KgEdge.dst_id == KgNode.id)
        .where(KgEdge.owner_id == owner_id, KgEdge.src_id == node_id, KgEdge.rel == COVERS)
        .order_by(KgEdge.created_at)
    ).all()
    out = [{"name": name, "page": int(prov.get("page") or 0), "quote": str(prov.get("quote") or ""),
            "chunk_id": str(prov.get("chunk_id") or "")} for name, prov in rows]
    return sorted(out, key=lambda c: c["page"])


# ---------------------------------------------------------------- the job

def extract_for_document(document_id: str) -> int:
    """Job body. Returns how many concepts were saved (0 when skipped)."""
    from ..db import SessionLocal
    from ..deps import user_gateway

    if not get_settings().concept_extraction:
        return 0
    db = SessionLocal()
    try:
        doc = db.get(Document, document_id)
        if doc is None or doc.status not in ("ready", "needs_attention"):
            return 0
        chunks = db.scalars(select(Chunk).where(Chunk.document_id == doc.id)).all()
        sources = pick_excerpts(list(chunks))
        if not sources:
            return 0
        req = Request(task="concept_extract", system=CONCEPTS_SYSTEM, user=concepts_user(sources), tier="fast",
                      max_tokens=2000, context={"sources": sources})
        try:
            found, prereqs = user_gateway(doc.owner_id, db).complete_json(
                req, validate=lambda d: validate_extraction(d, sources))
        except BudgetExceeded:
            log.info("concept extraction skipped: daily budget reached")
            return 0
        saved = save_document_concepts(db, doc, found, prereqs)
        db.commit()
        log.info("concepts saved for document %s: %d", doc.id, saved)
        from ..jobs import chain

        chain("rebuild_graph", {"owner_id": doc.owner_id})
        return saved
    finally:
        db.close()


def documents_covering(db: Session, owner_id: str, concept: str) -> list[str]:
    """Ids of the learner's documents that teach `concept` (covers edges), most recent first."""
    node = db.scalar(select(KgNode).where(KgNode.owner_id == owner_id, KgNode.kind == "concept",
                                          KgNode.canonical_key == canonical_key(concept)))
    if node is None:
        return []
    from .knowledge_graph import resolve

    node = resolve(db, node)
    rows = db.execute(select(KgNode.canonical_key).join(KgEdge, KgEdge.src_id == KgNode.id).where(
        KgEdge.owner_id == owner_id, KgEdge.rel == COVERS, KgEdge.dst_id == node.id).order_by(KgEdge.created_at.desc())).all()
    return [r[0] for r in rows]
