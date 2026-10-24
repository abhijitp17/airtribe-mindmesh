"""Offline mock for the ``answerable`` task (CONTRACTS §8).

A deterministic stand-in for the model check: is the question's *subject*
covered by the sources, not just one of its words?

1. The question is split into noun-phrase-like *runs* of content tokens
   (``core.text.tokenize`` stems). Stopwords, ``answerability.GENERIC`` verbs
   and punctuation end a run. The word after "how" ("how long", "how fast")
   is part of the question, not its subject, so it is dropped.
2. Prepositions (of, in, at, on, for, from, into, about, during) link a head run to a
   modifier run: "capital | of | Australia", "tax rate | in | Sweden".
3. A token is *grounded* if it occurs in some source (``matched_tokens``
   tolerates stemmer misses such as machine/machin).

Short questions (<= SHORT_QUERY_MAX content tokens) name a concept, so:
  * head + modifier pairs: every modifier run must be fully grounded in one
    source, and its head run must have a grounded token. The modifier is
    the restrictive part ("of France"), so it decides.
  * head noun phrase (the longest run, ties broken by the later run, which is
    usually the object of the question): at least half its tokens grounded.
Long questions describe a situation in everyday words (paraphrases such as "My
emergency room is always packed..."), so they're answerable when one source
grounds at least two distinct question tokens.

No sources means not answerable.
"""
from __future__ import annotations

import re

from ..core.answerability import GENERIC, SHORT_QUERY_MAX, content_tokens, matched_tokens
from ..core.text import normalize, tokenize
from .mock import register_mock

PREPOSITIONS = frozenset("of in at on for from into about during".split())
# Function words that end a run without linking ("changeovers quicker | without | spending").
BREAKERS = frozenset("without between against versus vs before after".split())
_WORD = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)*|[^\sa-z0-9]")


def phrase_runs(question: str) -> tuple[list[list[str]], list[tuple[int, int]]]:
    """(runs, links). ``links`` holds (head_run, modifier_run) index pairs joined by a preposition."""
    runs: list[list[str]] = []
    links: list[tuple[int, int]] = []
    cur: list[str] = []
    pending_prep = False
    skip_next = False

    def close() -> None:
        nonlocal cur
        if cur:
            runs.append(cur)
            cur = []

    for word in _WORD.findall(normalize(question).replace("-", " ")):
        if not word[0].isalnum():
            close()
            pending_prep = False
            continue
        if word == "how":
            close()
            skip_next = True
            pending_prep = False
            continue
        if word in BREAKERS:
            close()
            skip_next = pending_prep = False
            continue
        toks = tokenize(word)
        if not toks:  # stopword
            skip_next = False  # "how is WACC ...": only the word right after "how" is skipped
            if word in PREPOSITIONS and (cur or runs):
                close()
                pending_prep = True
            elif cur:
                close()
                pending_prep = False
            continue
        if skip_next:
            skip_next = False
            continue
        tok = toks[0]
        if tok in GENERIC:
            close()
            pending_prep = False
            continue
        if not cur and pending_prep and runs:
            links.append((len(runs) - 1, len(runs)))
        pending_prep = False
        cur.append(tok)
    close()
    return runs, links


def is_answerable(question: str, source_texts: list[str]) -> tuple[bool, str]:
    if not source_texts:
        return False, "No sources were retrieved."
    vocabs = [set(tokenize(t)) for t in source_texts]
    q = content_tokens(question)
    if not q:
        return True, "The question has no specific subject to check."
    grounded = set().union(*(matched_tokens(q, v) for v in vocabs))

    if len(q) > SHORT_QUERY_MAX:
        if len(grounded) >= 2:
            return True, "The sources cover several parts of the question."
        return False, "The sources share at most one word with the question."

    runs, links = phrase_runs(question)
    if not runs:
        return True, "The question has no specific subject to check."
    for _head, mod in links:
        if not any(len(matched_tokens(runs[mod], v)) == len(set(runs[mod])) for v in vocabs):
            missing = " ".join(t for t in runs[mod] if t not in grounded) or " ".join(runs[mod])
            return False, f"The sources don't cover '{missing}'."
    head_np = max(reversed(range(len(runs))), key=lambda i: len(runs[i]))
    np_tokens = set(runs[head_np])
    if 2 * len(np_tokens & grounded) < len(np_tokens):
        return False, f"The sources don't cover '{' '.join(runs[head_np])}'."
    return True, f"The sources cover '{' '.join(runs[head_np])}'."


@register_mock("answerable")
def _answerable(ctx: dict) -> dict:
    sources = ctx.get("sources", [])
    texts = [f"{getattr(s, 'section', '')} {getattr(s, 'text', '')}" for s in sources]
    ok, reason = is_answerable(str(ctx.get("question", "")), texts)
    return {"answerable": ok, "reason": reason}
