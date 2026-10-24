"""Validation of model-extracted resume and job-description structure (PRD §7.1).

The model only *extracts*. Everything it returns is checked here against the
source text before it is stored, because a resume parser that "improves" a
bullet (adds a metric, upgrades "helped" to "led") would put words in the
candidate's mouth in the interview. Rules:

* Every resume bullet, education line, skill and JD evidence quote must appear
  in the source (fuzzy, `quote_support >= 0.85`, to tolerate PDF artefacts).
  Anything else is dropped and reported as a warning.
* Ids (r1, r1b2, e1, c3) are assigned here, never by the model, so they are
  stable, unique and safe to reference from skill-match judgements.
* Enum fields are coerced to the shared enums in CONTRACTS.md §2.

Output shapes are plain dicts matching `ResumeParsed` / `JobParsed` because
they are stored as JSON columns and returned verbatim by the API.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .citations import QUOTE_MATCH_THRESHOLD, quote_support
from .text import normalize, tokenize

IMPORTANCE = ("critical", "high", "medium", "low")
COMPETENCY_CATEGORIES = ("technical", "domain", "tool", "behavioral", "leadership", "communication")
MAX_ROLES, MAX_BULLETS_PER_ROLE, MAX_SKILLS, MAX_COMPETENCIES = 15, 15, 60, 25
_ID_RE = re.compile(r"^[a-z0-9]{1,16}$")
_LEADING_MARKER = re.compile(r"^\s*(?:[•\-\*–—▸>]|\d+[.)])\s+")
_TOKEN_PRECHECK = 0.6


def strip_marker(text: str) -> str:
    """Remove a leading bullet glyph or list number; it is layout, not content."""
    return _LEADING_MARKER.sub("", text).strip()


class SourceIndex:
    """Fast "does this quote appear in the source?" checks.

    `quote_support` slides a fuzzy window over the whole text, which is slow on a
    long resume when the quote is fabricated (no early exit). We first try an
    exact normalised substring match, then a cheap token-containment precheck,
    and only then run the fuzzy match on the few lines that share the most tokens.
    """

    def __init__(self, text: str):
        self.full = normalize(text)
        self.lines = [ln for ln in text.split("\n") if ln.strip()]
        self.line_tokens = [set(tokenize(ln, drop_stopwords=False)) for ln in self.lines]
        self.vocab = set().union(*self.line_tokens) if self.line_tokens else set()

    def support(self, quote: str) -> float:
        q_norm = normalize(quote).strip(" .\"'")
        if not q_norm:
            return 0.0
        if q_norm in self.full:
            return 1.0
        q_tokens = set(tokenize(quote, drop_stopwords=False))
        if not q_tokens or len(q_tokens & self.vocab) / len(q_tokens) < _TOKEN_PRECHECK:
            return 0.0
        ranked = sorted(range(len(self.lines)), key=lambda i: -len(q_tokens & self.line_tokens[i]))[:3]
        best = 0.0
        for i in ranked:
            region = " ".join(self.lines[max(0, i - 1) : i + 3])
            best = max(best, quote_support(quote, region))
        return best

    def contains(self, quote: str) -> bool:
        return self.support(quote) >= QUOTE_MATCH_THRESHOLD


@dataclass
class ParseOutcome:
    parsed: dict
    warnings: list[str] = field(default_factory=list)


def _str(value: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit] if isinstance(value, (str, int, float)) else ""


def _opt_str(value: Any, limit: int) -> str | None:
    return _str(value, limit) or None


def _short(text: str, n: int = 80) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def _str_list(value: Any) -> list[str]:
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def _verified_list(items: list[str], index: SourceIndex, limit: int, max_len: int) -> tuple[list[str], list[str]]:
    """Keep unique items found in the source; return (kept, dropped)."""
    kept, dropped, seen = [], [], set()
    for raw in items:
        text = strip_marker(_str(raw, max_len))
        if not text or text.lower() in seen:
            continue
        if index.contains(text):
            seen.add(text.lower())
            kept.append(text)
        else:
            dropped.append(text)
    return kept[:limit], dropped


# ---------------- resume ----------------

def _verified_field(value: Any, index: SourceIndex, limit: int, label: str, warnings: list[str]) -> str | None:
    text = _opt_str(value, limit)
    if text and not index.contains(text):
        warnings.append(f"Ignored the {label} \"{_short(text)}\" because it does not appear in your resume.")
        return None
    return text


def _validate_role(raw: dict, n: int, index: SourceIndex, warnings: list[str]) -> dict | None:
    title = _verified_field(raw.get("title"), index, 160, "role title", warnings) or ""
    company = _verified_field(raw.get("company"), index, 160, "company", warnings) or ""
    bullets: list[dict] = []
    seen: set[str] = set()
    for b in _str_list(raw.get("bullets")):
        text = strip_marker(_str(b, 600))
        if len(tokenize(text, drop_stopwords=False)) < 3 or text.lower() in seen:
            continue
        if not index.contains(text):
            warnings.append(f"Dropped a bullet that is not in your resume: \"{_short(text)}\"")
            continue
        seen.add(text.lower())
        bullets.append({"id": f"r{n}b{len(bullets) + 1}", "text": text})
    if not title and not company and not bullets:
        return None
    return {
        "id": f"r{n}", "title": title, "company": company,
        "start": _opt_str(raw.get("start"), 40), "end": _opt_str(raw.get("end"), 40),
        "bullets": bullets[:MAX_BULLETS_PER_ROLE],
    }


def validate_resume(raw: Any, source_text: str) -> ParseOutcome:
    """Validate a model's `ResumeParsed`-like JSON against the resume text."""
    if not isinstance(raw, dict):
        raise ValueError("resume parse must be a JSON object")
    index = SourceIndex(source_text)
    warnings: list[str] = []
    name = _verified_field(raw.get("name"), index, 120, "name", warnings)
    summary = _verified_field(raw.get("summary"), index, 1500, "summary", warnings)

    roles: list[dict] = []
    for r in raw.get("roles") or []:
        if isinstance(r, dict) and len(roles) < MAX_ROLES:
            role = _validate_role(r, len(roles) + 1, index, warnings)
            if role:
                roles.append(role)

    skills, dropped_skills = _verified_list(_str_list(raw.get("skills")), index, MAX_SKILLS, 80)
    if dropped_skills:
        warnings.append(f"Ignored {len(dropped_skills)} skill(s) not found in your resume: {', '.join(_short(s, 30) for s in dropped_skills[:5])}.")
    edu, dropped_edu = _verified_list(_str_list(raw.get("education")), index, 10, 300)
    certs, dropped_certs = _verified_list(_str_list(raw.get("certifications")), index, 20, 200)
    for label, dropped in (("education entry", dropped_edu), ("certification", dropped_certs)):
        warnings.extend(f"Ignored the {label} \"{_short(d)}\" because it does not appear in your resume." for d in dropped)

    if not any(r["bullets"] for r in roles):
        warnings.append("No experience bullets were found. Check the Experience section, or edit the parsed resume.")
    parsed = {
        "name": name, "summary": summary, "roles": roles, "skills": skills,
        "education": [{"id": f"e{i}", "text": t} for i, t in enumerate(edu, 1)],
        "certifications": certs,
    }
    return ParseOutcome(parsed, warnings)


def _valid_id(value: Any) -> bool:
    return isinstance(value, str) and bool(_ID_RE.match(value))


def _reserve(items: list[Any]) -> set[str]:
    """Server-format ids already present in an edit. Minted ids must avoid them, so a
    new row (client id like "comp-<uuid>" or "") never steals an existing row's id."""
    return {i.get("id") for i in items if isinstance(i, dict) and _valid_id(i.get("id"))}


def _fresh_id(preferred: Any, used: set[str], fallback: str, reserved: set[str] | None = None) -> str:
    """Keep a user-supplied id when it is well-formed and unique; otherwise mint one.

    Client-side ids for new rows ("role-…", "b-…", "comp-…", "") don't match the
    server format and are replaced with a server id.
    """
    reserved = reserved or set()
    cand = preferred if _valid_id(preferred) and preferred not in used else None
    if cand is None:
        cand, k = fallback, 1
        while cand in used or cand in reserved:
            k += 1
            cand = f"{fallback}x{k}"
    used.add(cand)
    return cand


def normalize_resume_edit(parsed: dict) -> dict:
    """Clean a user-corrected `ResumeParsed`.

    The user is the authority on their own resume, so edits are not checked
    against the source; we only enforce shape and keep ids stable so skill
    matches that reference unchanged bullets still resolve after a recompute.
    """
    used: set[str] = set()
    raw_roles = [r for r in parsed.get("roles") or [] if isinstance(r, dict)]
    reserved = _reserve(raw_roles) | _reserve(parsed.get("education") or [])
    for r in raw_roles:
        reserved |= _reserve(r.get("bullets") or [])
    roles = []
    for i, r in enumerate(raw_roles, 1):
        rid = _fresh_id(r.get("id"), used, f"r{i}", reserved)
        bullets = []
        for j, b in enumerate(r.get("bullets") or [], 1):
            text = strip_marker(_str(b.get("text"), 600))
            if text:
                bullets.append({"id": _fresh_id(b.get("id"), used, f"{rid}b{j}", reserved), "text": text})
        roles.append({
            "id": rid, "title": _str(r.get("title"), 160), "company": _str(r.get("company"), 160),
            "start": _opt_str(r.get("start"), 40), "end": _opt_str(r.get("end"), 40), "bullets": bullets,
        })
    education = []
    for i, e in enumerate(parsed.get("education") or [], 1):
        text = _str(e.get("text"), 300)
        if text:
            education.append({"id": _fresh_id(e.get("id"), used, f"e{i}", reserved), "text": text})
    return {
        "name": _opt_str(parsed.get("name"), 120), "summary": _opt_str(parsed.get("summary"), 1500),
        "roles": roles,
        "skills": list(dict.fromkeys(s for s in (_str(x, 80) for x in parsed.get("skills") or []) if s)),
        "education": education,
        "certifications": [c for c in (_str(x, 200) for x in parsed.get("certifications") or []) if c],
    }


def resume_bullets(parsed: dict) -> list[dict]:
    """Flatten bullets with their role title: the unit of resume evidence."""
    return [
        {"id": b["id"], "text": b["text"], "role_title": r.get("title") or r.get("company") or ""}
        for r in parsed.get("roles") or [] for b in r.get("bullets") or []
    ]


# ---------------- job description ----------------

_LOW_WORDS = re.compile(r"\b(nice[- ]to[- ]have|bonus|a plus|is a plus|pluses|good to have|not required)\b", re.I)
_MEDIUM_WORDS = re.compile(r"\b(preferred|preferably|ideally|desired|desirable|advantageous)\b", re.I)
_CRITICAL_WORDS = re.compile(r"\b(must|required|requirement|essential|mandatory)\b", re.I)


def importance_from_text(text: str, section_default: str = "medium") -> str:
    """Importance from the JD's own wording; explicit words beat the section default."""
    if _LOW_WORDS.search(text):
        return "low"
    if _MEDIUM_WORDS.search(text):
        return "medium"
    if _CRITICAL_WORDS.search(text):
        return "critical"
    return section_default


_CATEGORY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("leadership", re.compile(r"\b(lead(ing|ership)?|mentor\w*|coach\w*|manag(e|ing) (a )?team|people manage\w*|hiring)\b", re.I)),
    ("communication", re.compile(r"\b(communicat\w*|present\w*|storytell\w*|written|verbal|explain\w*|articulat\w*)\b", re.I)),
    ("behavioral", re.compile(r"\b(collaborat\w*|stakeholder\w*|cross[- ]functional|teamwork|ownership|self[- ]starter|autonom\w*|adaptab\w*|prioriti\w*|curious|curiosity|influenc\w*)\b", re.I)),
    ("tool", re.compile(r"\b(excel|tableau|looker|power ?bi|jira|git(hub)?|docker|kubernetes|aws|gcp|azure|airflow|dbt|snowflake|bigquery|salesforce|figma|spark|terraform|jenkins|hubspot)\b", re.I)),
    ("domain", re.compile(r"\b(industry|domain|financ\w*|fintech|healthcare|retail|e-?commerce|supply chain|insurance|banking|regulat\w*|compliance|logistics|payments|marketing|clinical)\b", re.I)),
)


def category_from_text(text: str) -> str:
    for category, pattern in _CATEGORY_PATTERNS:
        if pattern.search(text):
            return category
    return "technical"


def _validate_competency(raw: dict, index: SourceIndex, warnings: list[str]) -> dict | None:
    name = _str(raw.get("name"), 80)
    quote = strip_marker(_str(raw.get("evidence_quote"), 600))
    if not name:
        return None
    if not quote or not index.contains(quote):
        warnings.append(f"Dropped the competency \"{_short(name, 50)}\": its supporting quote is not in the job description.")
        return None
    category = str(raw.get("category", "")).lower()
    importance = str(raw.get("importance", "")).lower()
    importance = importance if importance in IMPORTANCE else importance_from_text(quote)
    required = raw.get("required")
    return {
        "name": name,
        "category": category if category in COMPETENCY_CATEGORIES else category_from_text(f"{name} {quote}"),
        "importance": importance,
        "required": required if isinstance(required, bool) else importance in ("critical", "high"),
        "evidence_quote": quote,
    }


def validate_job(raw: Any, source_text: str) -> ParseOutcome:
    """Validate a model's `JobParsed`-like JSON against the JD text."""
    if not isinstance(raw, dict):
        raise ValueError("job parse must be a JSON object")
    index = SourceIndex(source_text)
    warnings: list[str] = []
    competencies: list[dict] = []
    seen: set[str] = set()
    for c in raw.get("competencies") or []:
        if not isinstance(c, dict) or len(competencies) >= MAX_COMPETENCIES:
            continue
        comp = _validate_competency(c, index, warnings)
        if comp and comp["name"].lower() not in seen:
            seen.add(comp["name"].lower())
            competencies.append({"id": f"c{len(competencies) + 1}", **comp})
    responsibilities, dropped = _verified_list(_str_list(raw.get("responsibilities")), index, 15, 400)
    if dropped:
        warnings.append(f"Ignored {len(dropped)} responsibility line(s) not found in the job description.")
    if not competencies:
        warnings.append("No competencies could be verified in the job description. Add them by editing the parsed job.")
    company = _opt_str(raw.get("company"), 255)
    parsed = {
        "role_title": _str(raw.get("role_title"), 255) or "Untitled role",
        "company": company if company and index.contains(company) else None,
        "seniority": _opt_str(raw.get("seniority"), 60),
        "responsibilities": responsibilities,
        "competencies": competencies,
    }
    return ParseOutcome(parsed, warnings)


def normalize_job_edit(parsed: dict) -> dict:
    """Clean a user-corrected `JobParsed` (shape and enums only, ids kept stable)."""
    used: set[str] = set()
    reserved = _reserve(parsed.get("competencies") or [])
    comps = []
    for i, c in enumerate(parsed.get("competencies") or [], 1):
        name = _str(c.get("name"), 80)
        if not name:
            continue
        importance = c.get("importance") if c.get("importance") in IMPORTANCE else "medium"
        category = c.get("category") if c.get("category") in COMPETENCY_CATEGORIES else category_from_text(name)
        comps.append({
            "id": _fresh_id(c.get("id"), used, f"c{i}", reserved), "name": name, "category": category,
            "importance": importance, "required": bool(c.get("required", importance in ("critical", "high"))),
            "evidence_quote": _str(c.get("evidence_quote"), 600),
        })
    return {
        "role_title": _str(parsed.get("role_title"), 255) or "Untitled role",
        "company": _opt_str(parsed.get("company"), 255),
        "seniority": _opt_str(parsed.get("seniority"), 60),
        "responsibilities": [r for r in (_str(x, 400) for x in parsed.get("responsibilities") or []) if r],
        "competencies": comps,
    }
