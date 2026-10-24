"""Notes-first answers (P3): answer from the learner's own knowledge base without a model call when
that's reliable, and say when the AI is needed. Pure: no database, no model.

* `classify` routes a question: about the learner's own learning (mastery, prerequisites, which notes
  cover a topic: answered from the database), a reasoning question (compare, apply, why: suggest the
  AI), or a lookup.
* `extract` builds an extractive answer: the sentences from the retrieved passages that best match the
  question, each quoted verbatim with its page. Nothing is paraphrased, so nothing can be invented.
* `question_key` normalises a question so a repeat ("What's Little's Law?" / "what is littles law")
  can reuse an answer the AI already wrote and verified.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .answerability import content_tokens
from .citations import SourceRef

MASTERY = re.compile(r"\b(?:how well do i know|what do i know about|how am i doing (?:with|on|in)|my (?:level|progress|mastery) (?:in|on|with|for))\s+(?P<topic>.+)", re.I)
PREREQ = re.compile(r"\b(?:what should i (?:learn|know|study|understand)(?: first)? before|prerequisites? (?:of|for)|what (?:does|do) (?P<t2>.+?) (?:build|depend|rely) on)\s*(?P<topic>.*)", re.I)
DOCS = re.compile(r"\b(?:which|what) (?:documents?|notes?|files?|pages?|material) (?:cover|covers|explain|explains|mention|mentions|talk about|teach|teaches|discuss|discusses)\s+(?P<topic>.+)", re.I)
SYNTHESIS = re.compile(r"\b(?:compare|comparison|difference between|differ|versus|vs\.?|pros and cons|trade-?offs?|why (?:does|do|is|are|would|should)|how would|how should|should i|apply|applied to|in my (?:case|situation|job)|step[- ]by[- ]step|evaluate|critique|summari[sz]e (?:everything|all))\b", re.I)

MAX_SENTENCES = 3
MIN_SENTENCE_WORDS = 6


@dataclass
class Route:
    kind: str  # mastery | prerequisites | documents | synthesis | lookup
    topic: str = ""


def _topic(s: str) -> str:
    return re.sub(r"[?.!]+$", "", " ".join((s or "").split())).strip(" '\"")


def classify(question: str) -> Route:
    q = question.strip()
    for kind, rx in (("mastery", MASTERY), ("prerequisites", PREREQ), ("documents", DOCS)):
        m = rx.search(q)
        if m:
            topic = _topic(m.groupdict().get("topic") or "") or _topic(m.groupdict().get("t2") or "")
            if topic:
                return Route(kind, topic)
    if SYNTHESIS.search(q):
        return Route("synthesis")
    return Route("lookup")


@dataclass
class Extract:
    answer: str
    citations: list[dict]  # label, chunk_id, quote, page_start, page_end, section


_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")
# Text that addresses an AI rather than a reader: planted instructions are never quoted as an answer.
_INSTRUCTION = re.compile(
    r"</?\s*(?:system|source|sources|student_answer|question|assistant|user|developer|instructions?)\b[^>]*>"
    r"|\b(?:ignore|disregard|forget)\b.{0,40}\b(?:instructions?|rules|prompt)\b"
    r"|\b(?:system prompt|developer mode|jailbreak|as an ai|you are now|reply only|respond only|"
    r"end every answer|system notice|new instructions)\b", re.I)


def _sentences(text: str) -> list[str]:
    flat = " ".join(text.split())
    return [s.strip() for s in _SENT.split(flat)
            if len(s.split()) >= MIN_SENTENCE_WORDS and not _INSTRUCTION.search(s)]


def extract(question: str, sources: list[SourceRef]) -> Extract | None:
    """The best-matching sentences from the passages, in reading order, quoted verbatim.
    None when no sentence shares a content word with the question."""
    q = set(content_tokens(question))
    if not q or not sources:
        return None
    scored = []
    for rank, src in enumerate(sources):
        for pos, sent in enumerate(_sentences(src.text)):
            overlap = len(q & set(content_tokens(sent)))
            if overlap:
                # Prefer more question words, then higher-ranked passages, then earlier sentences.
                scored.append((-overlap, rank, pos, src, sent))
    if not scored:
        return None
    best = sorted(scored, key=lambda t: t[:3])[:MAX_SENTENCES]
    best.sort(key=lambda t: (t[1], t[2]))  # reading order
    cites, seen = [], {}
    for _, _, _, src, sent in best:
        label = seen.setdefault(src.chunk_id, f"S{len(seen) + 1}")
        cites.append({"label": label, "chunk_id": src.chunk_id, "quote": sent, "page_start": src.page_start,
                      "page_end": src.page_end, "section": src.section})
    answer = " ".join(f"{c['quote']} [{c['label']}]" for c in cites)
    return Extract(answer, cites)


_CONTRACTIONS = re.compile(r"\b(what|who|where|how|that|it|there)['’]s\b", re.I)


def question_key(question: str) -> frozenset[str]:
    q = re.sub(r"\bwhats\b", "what is", _CONTRACTIONS.sub(r"\1 is", question), flags=re.I)
    q = re.sub(r"['’]", "", q)  # "Little's" and "Littles" are the same word here
    return frozenset(content_tokens(q))


def same_question(a: frozenset[str], b: frozenset[str]) -> bool:
    """Repeat questions: the same content words, or nearly (one extra or missing word in a long one)."""
    if not a or not b:
        return False
    if a == b:
        return True
    inter = len(a & b)
    return min(len(a), len(b)) >= 4 and inter / len(a | b) >= 0.8
