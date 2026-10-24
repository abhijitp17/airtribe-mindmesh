"""Answerability gate (CONTRACTS §8): do the retrieved sources really cover the question?

Retrieval's coverage gate (``core.hybrid``) only asks "is there *some* lexical
or embedding match?". A single shared ordinary word is enough for that:
"What is the capital of Australia?" matches "working capital" with bm25 ~0.6,
and "In what year did the Berlin Wall fall?" matches "every year". The tutor
then answers from an irrelevant chunk. This module adds a cheap lexical guard
in front of a model check:

    lexical_verdict(question, sources, hits_meta)
        "confident" -> answer, skip the model check (saves a call)
        "reject"    -> return not_found without any model call
        "uncertain" -> ask the model (Gateway task "answerable", tier fast)

Signals (all computed on the stemmed content tokens of ``core.text.tokenize``,
minus ``GENERIC`` question verbs such as "calculate", "explain", "say"):

* ``n``        number of distinct query content tokens.
* coverage     the largest number of distinct query tokens found in a single
               chunk among the top ``TOP_CHUNKS`` sources ("best chunk").
* spread       distinct query tokens found across those top chunks combined.
* rarest token the query token(s) with the lowest document frequency across
               all provided sources. A token that appears in no source has
               df 0, so it is the rarest. ``rare_covered`` means the best
               chunk contains every rarest token, which implies every query
               token occurs somewhere in the sources.
* bigram       two query tokens adjacent in the question are also adjacent in a
               top chunk ("cost of equity" -> cost equity).
* bm25 / cosine  the raw retrieval signals of the hits (``core.hybrid.HybridHit``).

Rules (``need = min(2, n)``):

* reject     n <= SHORT_QUERY_MAX and fewer than ``need`` distinct query
             tokens across the top chunks, and max cosine of the top chunks
             < COSINE_RESCUE. This is §8 rule 1: a short query needs two distinct
             shared terms, so one shared common word ("capital", "year",
             "law", "stock") isn't enough. The terms are counted across the top 3
             chunks rather than within one, because a short practical question
             can be split over neighbouring chunks.
* confident  (a) coverage >= need and bm25 of the best chunk >= CONFIDENT_BM25 and
             (rare_covered or (bigram and coverage/n >= CONFIDENT_FRACTION)).
             This is §8 rule 2 ("bm25 >= 3.0 and >= 2 shared terms") plus a
             specificity check. Without it "boiling point of water at sea
             level" (point + level, bm25 5.3) or "tax rate in Sweden" (tax rate
             bigram) would skip the model check.
             (b) or the best chunk contains *every* query token (bm25 > 0).
             This is scale-free, so it still works on tiny corpora, where IDF
             and therefore bm25 are low ("What is variability?" over a 2-chunk
             PDF has bm25 1.3).
* uncertain  everything else, including all long (> 6 token) questions that
             aren't confident. Those are typically paraphrases ("My emergency
             room is always packed...") that only the model can judge.

Calibration (mock provider, HashingEmbedder "hash-v1"; the eval corpus
``evals/docs/{operations,finance}.txt``, 42 gold cases, and 44 held-out cases in
``tests/test_answerability.py``, asserted by ``test_calibration_on_eval_corpus``):

    gold answerable (34)            reject 0, confident 22, uncertain 12
    gold not_found (8)              3 no sources, reject 3, uncertain 2, confident 0
    held-out answerable (20)        reject 0, confident 19, uncertain 1
    held-out off-topic (24)         4 no sources, reject 15, uncertain 5, confident 0
    cosine of the best top-3 chunk on short off-topic queries that share one
    word with the text: max 0.164 ("Who is the current CEO of Apple?"), median ~0.09.
COSINE_RESCUE = 0.25 is well above that max, so the rescue only fires on a
near-duplicate of a chunk (e.g. an OCR variant of a single-term definition),
which hash-v1 scores at 0.25-0.45.
CONFIDENT_BM25 = 3.0 is the §8 value. Off-topic best-chunk bm25 reaches 5.31
(ops-nf-02), so bm25 alone can't separate them. That's why rule (a) also
needs the rarest query token to be covered: "boil" and "water" are absent, so
the case stays uncertain. No off-topic case in either set is confident, so
the model check is always the second line of defence.

Model-check failure policy: if the model reply can't be parsed or validated
(even after the gateway's repair attempt), we use the lexical verdict. Only
"uncertain" reaches the model, so the fallback is always ``answerable=True``
(``fallback_answerable``). A broken or garbled model must never silently
block real questions. The tutor's own ``found=false`` and citation
verification still apply downstream.

Known limitations: tokens are matched after the tiny stemmer in
``core.text`` plus a prefix rule (``_close``: "machine"/"machin",
"utilisation"/"utiliz"). Other morphology it misses ("profits" vs
"profitable") counts as absent. The calibration corpora are two English
textbook-style documents; recalibrate for other languages or embedders. A short question with two common shared words and an absent
subject goes to the model rather than being rejected. That costs one fast
call, not a wrong answer.
"""
from __future__ import annotations

from typing import Literal, Mapping, Sequence

from .citations import SourceRef
from .text import stem, tokenize

Verdict = Literal["confident", "uncertain", "reject"]

SHORT_QUERY_MAX = 6  # §8: the two-term rule applies to queries with <= 6 content tokens
TOP_CHUNKS = 3  # same sources the model check sees
CONFIDENT_BM25 = 3.0  # §8 rule 2
CONFIDENT_FRACTION = 0.75  # bigram path: at least 3/4 of the query tokens in the best chunk
COSINE_RESCUE = 0.25  # see "Calibration"; off-topic max 0.164

# Question words and generic verbs that say what kind of answer is wanted, not
# what it is about. They're stemmed the same way as query tokens.
GENERIC = frozenset(stem(w) for w in """
    explain explained explains describe described describes define defined defines definition
    meaning mean means calculate calculated calculates calculation compute computed computes
    tell say says said state states stated happen happens happened get gets got give gives given
    make makes made making go goes going use used uses using thing things way ways kind type sort
    example examples please know many much
""".split())


def content_tokens(text: str) -> list[str]:
    """Distinct stemmed content tokens in question order, minus ``GENERIC``."""
    return list(dict.fromkeys(t for t in tokenize(text) if t not in GENERIC))


def _bigrams(tokens: Sequence[str]) -> set[tuple[str, str]]:
    return set(zip(tokens, tokens[1:]))


MIN_PREFIX = 5


def _close(a: str, b: str) -> bool:
    """Same word up to the stemmer's blind spots: "machine"/"machin" (from
    "machines"), "efficient"/"efficiency". Requires a shared prefix of at least
    ``MIN_PREFIX`` chars that covers all but the last char of the shorter token."""
    if a == b:
        return True
    short = min(len(a), len(b))
    if short < MIN_PREFIX or a.isdigit() or b.isdigit():
        return False
    i = 0
    while i < short and a[i] == b[i]:
        i += 1
    return i >= max(MIN_PREFIX, short - 1)


def matched_tokens(query: Sequence[str], vocab: set[str]) -> set[str]:
    """Query tokens present in ``vocab`` (exactly or by ``_close``)."""
    return {t for t in query if t in vocab or any(_close(t, u) for u in vocab if u[:2] == t[:2])}


def _signal(meta: Mapping[str, float] | None, key: str) -> float:
    if not meta:
        return 0.0
    try:
        return float(meta.get(key, 0.0))
    except (TypeError, ValueError):
        return 0.0


def lexical_verdict(
    question: str,
    sources: Sequence[SourceRef],
    hits_meta: Sequence[Mapping[str, float] | None] | None = None,
) -> Verdict:
    """Cheap lexical answerability verdict. See the module docstring.

    ``hits_meta`` is aligned with ``sources``. Each entry is a mapping with the
    raw ``bm25`` and ``cosine`` of that source's hit. Missing entries count as
    0, so without metadata the guard can reject or be uncertain but never
    confident.
    """
    if not sources:
        return "reject"
    q = content_tokens(question)
    if not q:
        return "uncertain"  # e.g. "what is it?": nothing to judge, let the model decide
    n, need = len(q), min(2, len(q))
    meta = list(hits_meta or [])
    meta += [None] * (len(sources) - len(meta))

    streams = [tokenize(f"{s.section} {s.text}") for s in sources]
    present = [matched_tokens(q, set(s)) for s in streams]
    top = list(range(min(TOP_CHUNKS, len(sources))))
    covers = [present[i] for i in top]
    best = max(top, key=lambda i: (len(covers[i]), -i))
    coverage = len(covers[best])
    max_cos = max(_signal(meta[i], "cosine") for i in top)

    spread = len(set().union(*covers))  # distinct query tokens across the top chunks
    if n <= SHORT_QUERY_MAX and spread < need and max_cos < COSINE_RESCUE:
        return "reject"

    df = {t: sum(t in p for p in present) for t in q}
    lowest = min(df.values())
    rare_covered = all(t in covers[best] for t in q if df[t] == lowest)
    q_bigrams = _bigrams([t for t in tokenize(question) if t not in GENERIC])
    bigram = any(q_bigrams & _bigrams(streams[i]) for i in top)
    strong = _signal(meta[best], "bm25") >= CONFIDENT_BM25
    if coverage >= need and strong and (rare_covered or (bigram and coverage / n >= CONFIDENT_FRACTION)):
        return "confident"
    if coverage == n and _signal(meta[best], "bm25") > 0.0:
        return "confident"  # full coverage: scale-free, so it also works on tiny corpora (low IDF)
    return "uncertain"


def parse_answerable(data: object) -> dict:
    """Validate the model's ``{"answerable": bool, "reason": str}`` reply.

    Raises ``ValueError`` on anything else, so the gateway runs its repair
    attempt and the caller can fall back (see ``fallback_answerable``).
    """
    if not isinstance(data, dict) or not isinstance(data.get("answerable"), bool):
        raise ValueError("answerable reply must be an object with a boolean 'answerable'")
    reason = data.get("reason", "")
    return {"answerable": data["answerable"], "reason": str(reason)[:300] if reason is not None else ""}


def fallback_answerable(verdict: Verdict) -> bool:
    """Decision when the model check is unusable: keep the lexical verdict.
    Only "reject" blocks, so an unparseable reply on an "uncertain" question lets it through."""
    return verdict != "reject"
