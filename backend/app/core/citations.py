"""Citation verification (PRD 9.2 step 6, FR-030).

The model is asked to return an answer with inline markers like [S2] plus a
supporting quote for each source it cites. We never trust that blindly:

1. The cited source id must be one we actually retrieved for this question.
2. The quote must really appear in that source (fuzzy, to tolerate PDF
   whitespace and hyphenation artifacts).

Citations that fail are dropped, markers pointing at them are removed from
the answer text, and the response is labelled so the UI can show
"verified", "partially verified", or "unverified".
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from .text import normalize, tokenize

MARKER_RE = re.compile(r"\[(S\d+)\]")
QUOTE_MATCH_THRESHOLD = 0.85
MIN_QUOTE_TOKENS = 3


@dataclass
class SourceRef:
    label: str  # "S1"
    chunk_id: str
    text: str
    page_start: int
    page_end: int
    section: str = ""


@dataclass
class VerifiedCitation:
    label: str
    chunk_id: str
    quote: str
    page_start: int
    page_end: int
    section: str
    match_score: float


@dataclass
class VerificationResult:
    answer: str
    citations: list[VerifiedCitation]
    rejected: list[dict] = field(default_factory=list)
    status: str = "unverified"  # verified | partial | unverified | not_found | general


def quote_support(quote: str, source_text: str) -> float:
    """How well `quote` is contained in `source_text`, from 0 to 1."""
    q = normalize(quote).strip(" .\"'")
    s = normalize(source_text)
    if not q:
        return 0.0
    if q in s:
        return 1.0
    # Sliding-window fuzzy match on roughly quote-sized windows.
    best = 0.0
    window = len(q)
    step = max(1, window // 4)
    for start in range(0, max(1, len(s) - window + 1), step):
        seg = s[start : start + window + window // 5]
        ratio = SequenceMatcher(None, q, seg, autojunk=False).ratio()
        if ratio > best:
            best = ratio
            if best >= 0.98:
                break
    return best


def verify(answer: str, claimed: list[dict], sources: list[SourceRef], found: bool) -> VerificationResult:
    """Validate model-claimed citations against retrieved sources."""
    if not found:
        return VerificationResult(answer=strip_markers(answer), citations=[], status="not_found")

    by_label = {s.label: s for s in sources}
    accepted: dict[str, VerifiedCitation] = {}
    rejected: list[dict] = []

    for c in claimed or []:
        label = str(c.get("source", "")).strip().strip("[]")
        quote = str(c.get("quote", "")).strip()
        src = by_label.get(label)
        if src is None:
            rejected.append({"source": label, "reason": "unknown source"})
            continue
        if len(tokenize(quote, drop_stopwords=False)) < MIN_QUOTE_TOKENS:
            rejected.append({"source": label, "reason": "quote too short"})
            continue
        score = quote_support(quote, src.text)
        if score < QUOTE_MATCH_THRESHOLD:
            rejected.append({"source": label, "reason": "quote not found in source", "score": round(score, 2)})
            continue
        if label not in accepted or score > accepted[label].match_score:
            accepted[label] = VerifiedCitation(
                label, src.chunk_id, quote, src.page_start, src.page_end, src.section, round(score, 3)
            )

    used = set(MARKER_RE.findall(answer))
    # Remove markers that point to unverified sources so the UI never shows a bad citation.
    cleaned = MARKER_RE.sub(lambda m: m.group(0) if m.group(1) in accepted else "", answer)
    cleaned = re.sub(r"[ \t]+([.,;:])", r"\1", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()

    if not accepted:
        status = "unverified"
    elif rejected or (used - set(accepted)):
        status = "partial"
    else:
        status = "verified"
    ordered = sorted(accepted.values(), key=lambda v: int(v.label[1:]))
    return VerificationResult(answer=cleaned, citations=ordered, rejected=rejected, status=status)


def strip_markers(text: str) -> str:
    return re.sub(r"[ \t]{2,}", " ", MARKER_RE.sub("", text)).strip()
