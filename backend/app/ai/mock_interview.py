"""Deterministic offline handlers for the interview-prep tasks.

These are real heuristic parsers and graders, not canned replies, so the
whole interview flow (including validation of what they return) can be
demoed and tested without an API key. They read only `Request.context` and
use no randomness. Their output still goes through the same validation as a
real model's, so a heuristic mistake is dropped rather than stored.
"""
from __future__ import annotations

import re

from ..core.interview_deepdive import analyse_claim
from ..core.interview_engine import QuestionPlan, template_question
from ..core.interview_parse import category_from_text, importance_from_text, strip_marker
from ..core.text import tokenize
from .mock import register_mock

# ---------------- shared line helpers ----------------

_BULLET_LINE = re.compile(r"^\s*(?:[•\-\*–—▸>]|\d+[.)])\s+")
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_DATE = rf"(?:{_MONTH}\s+\d{{4}}|\d{{1,2}}/\d{{4}}|\d{{4}})"
_RANGE_RE = re.compile(rf"\(?\s*({_DATE})\s*(?:-|–|—|to)\s*({_DATE}|present|current|now)\s*\)?", re.I)


def _lines(text: str) -> list[str]:
    return [ln.strip() for ln in (text or "").split("\n")]


def _is_bullet(line: str) -> bool:
    return bool(_BULLET_LINE.match(line))


def _header_key(line: str, headers: dict[str, str]) -> str | None:
    """Map a section-header line to its canonical section, or None."""
    clean = re.sub(r"[:\s]+$", "", line).strip().lower()
    if not clean or len(clean.split()) > 5 or _is_bullet(line):
        return None
    return headers.get(clean)


def _collect_bullets(lines: list[str]) -> list[tuple[bool, str]]:
    """Join wrapped continuation lines onto their bullet; returns (is_bullet, text) items."""
    items: list[tuple[bool, str]] = []
    for ln in lines:
        if not ln:
            continue
        if _is_bullet(ln):
            items.append((True, strip_marker(ln)))
        elif items and items[-1][0] and (ln[0].islower() or items[-1][1].endswith((",", "-", "and", "&"))):
            items[-1] = (True, f"{items[-1][1]} {ln}")
        else:
            items.append((False, ln))
    return items


# ---------------- resume_parse ----------------

_RESUME_HEADERS = {
    **{h: "summary" for h in ("summary", "profile", "professional summary", "about me", "objective", "career summary")},
    **{h: "experience" for h in ("experience", "work experience", "professional experience", "employment", "employment history", "work history", "career history", "relevant experience")},
    **{h: "projects" for h in ("projects", "selected projects", "key projects")},
    **{h: "skills" for h in ("skills", "technical skills", "core skills", "key skills", "skills & tools", "skills and tools", "tools", "technologies", "core competencies")},
    **{h: "education" for h in ("education", "education & training", "academic background", "qualifications")},
    **{h: "certifications" for h in ("certifications", "certificates", "licenses & certifications", "licenses and certifications")},
}
_TITLE_WORDS = re.compile(
    r"\b(engineer|analyst|manager|scientist|developer|lead|director|consultant|intern|associate|specialist|"
    r"designer|officer|head|vp|vice president|coordinator|architect|administrator|researcher|executive|"
    r"strategist|owner|founder|advisor|accountant|teacher|nurse|technician|representative)\b",
    re.I,
)
_SPLIT_HEADER = re.compile(r"\s+(?:\||—|–|-|@|at)\s+|,\s+")


def _split_sections(text: str, headers: dict[str, str]) -> tuple[list[str], dict[str, list[str]]]:
    preamble: list[str] = []
    sections: dict[str, list[str]] = {}
    current: list[str] = preamble
    for ln in _lines(text):
        key = _header_key(ln, headers)
        if key:
            current = sections.setdefault(key, [])
        else:
            current.append(ln)
    return preamble, sections


def _role_from_header(header_lines: list[str]) -> dict:
    """Title/company/dates from the non-bullet lines above a role's bullets."""
    joined = " | ".join(header_lines)
    start = end = None
    m = _RANGE_RE.search(joined)
    if m:
        start, end = m.group(1), m.group(2)
        joined = (joined[: m.start()] + joined[m.end():]).strip(" |,–—-")
    parts = [p.strip(" |,()") for p in _SPLIT_HEADER.split(joined) if p and p.strip(" |,()")]
    parts = [p for p in parts if not re.fullmatch(r"[\w\s]*\b(remote|hybrid|on-?site)\b[\w\s]*|[A-Z][a-z]+,?\s?[A-Z]{2}", p)] or parts
    title = next((p for p in parts if _TITLE_WORDS.search(p)), parts[0] if parts else "")
    company = next((p for p in parts if p != title), "")
    return {"title": title, "company": company, "start": start, "end": end, "bullets": []}


def _parse_roles(lines: list[str]) -> list[dict]:
    roles: list[dict] = []
    pending: list[str] = []
    for is_bullet, text in _collect_bullets(lines):
        if is_bullet:
            if pending or not roles:
                roles.append(_role_from_header(pending[-2:] or ["Experience"]))
                pending = []
            roles[-1]["bullets"].append(text)
        else:
            pending.append(text)
    return roles


def _parse_skills(lines: list[str]) -> list[str]:
    out: list[str] = []
    for ln in lines:
        body = strip_marker(ln)
        if ":" in body:
            body = body.split(":", 1)[1]
        out.extend(s.strip(" .") for s in re.split(r"[,;|•·/]", body) if 1 <= len(s.strip(" .").split()) <= 5)
    return list(dict.fromkeys(out))


@register_mock("resume_parse")
def _resume_parse(ctx: dict) -> dict:
    preamble, sections = _split_sections(ctx.get("text", ""), _RESUME_HEADERS)
    head = [ln for ln in preamble if ln]
    name = head[0] if head and len(head[0].split()) <= 5 and not re.search(r"[@\d|]", head[0]) else None
    roles = _parse_roles(sections.get("experience", [])) + _parse_roles(sections.get("projects", []))
    return {
        "name": name,
        "summary": " ".join(ln for ln in sections.get("summary", []) if ln) or None,
        "roles": roles,
        "skills": _parse_skills(sections.get("skills", [])),
        "education": [strip_marker(ln) for ln in sections.get("education", []) if ln],
        "certifications": [strip_marker(ln) for ln in sections.get("certifications", []) if ln],
    }


# ---------------- jd_parse ----------------

_JD_HEADERS = {
    **{h: "responsibilities" for h in ("responsibilities", "key responsibilities", "what you'll do", "what you will do", "the role", "your role", "duties", "role overview", "in this role you will", "day to day")},
    **{h: "requirements" for h in ("requirements", "qualifications", "what you'll bring", "what you will bring", "who you are", "what we're looking for", "what we are looking for", "about you", "skills", "minimum qualifications", "basic qualifications", "required qualifications", "you have")},
    **{h: "must" for h in ("must have", "must-have", "must haves", "must-haves", "essential", "essential skills", "required skills", "required")},
    **{h: "preferred" for h in ("preferred", "preferred qualifications", "preferred skills", "desirable", "ideally", "bonus points", "it would be great if")},
    **{h: "nice" for h in ("nice to have", "nice-to-have", "nice to haves", "nice-to-haves", "bonus", "pluses", "a plus")},
    **{h: "about" for h in ("about us", "about the company", "who we are", "benefits", "what we offer", "perks", "compensation")},
}
_SECTION_IMPORTANCE = {"must": "critical", "requirements": "high", "bullets": "high", "preferred": "medium", "nice": "low", "responsibilities": "high"}
_LEAD_IN = re.compile(
    r"^(?:(?:you\s+)?(?:must|should)\s+(?:have|be)\s+|(?:have|has)\s+|"
    r"\d+\+?\s*(?:years?|yrs?)(?:\s+of)?(?:\s+\w+)?\s+(?:experience\s+)?(?:with|in|using|of)?\s*|"
    r"(?:strong|solid|proven|excellent|demonstrated|deep|good|working|hands-on|advanced|basic)\s+|"
    r"(?:experience|proficiency|expertise|familiarity|knowledge|understanding|fluency|skills?)\s+(?:with|in|of|using)\s+|"
    r"(?:ability|able)\s+to\s+|comfortable\s+(?:with|using)\s+|track record (?:of|in)\s+|"
    r"(?:bachelor'?s|master'?s|degree)\b.*?\bin\s+)+",
    re.I,
)
_SENIORITY = re.compile(r"\b(intern|junior|associate|mid[- ]level|senior|staff|principal|lead|head|director)\b", re.I)


def _competency_names(line: str) -> list[str]:
    """Short canonical names from one requirement line; lists of short items become several."""
    core = re.sub(r"\s*\b(?:is |are )?(?:a plus|preferred|required|nice to have|good to have|a must|a bonus)\b", "", line, flags=re.I)
    core = re.split(r"\s*(?:\(|;|:|\.\s|\.$| such as | including | e\.g\.| to (?!-))", _LEAD_IN.sub("", core), maxsplit=1)[0]
    core = re.sub(r"\s+(?:domain\s+)?(?:experience|skills?|knowledge|expertise)\s*$", "", core.strip(" ,.-"), flags=re.I)
    # Split lists on commas, and/or and word/word slashes, but keep short tokens like "A/B" or "CI/CD".
    parts = re.split(r",\s*|\s+(?:and|or|&)\s+|(?<=\w{4})/(?=\w{4})", core)
    items = [i.strip(" ,.") for i in parts if i.strip(" ,.")]
    if len(items) > 1 and all(len(i.split()) <= 3 for i in items):
        return [i[:1].upper() + i[1:] for i in items[:5]]
    words = core.split()[:4]
    return [" ".join(words)[:1].upper() + " ".join(words)[1:]] if words else []


def _jd_title_company(preamble: list[str], text: str) -> tuple[str, str | None]:
    head = [ln for ln in preamble if ln]
    labelled = re.search(r"^(?:job title|title|role|position)\s*:\s*(.+)$", text, re.I | re.M)
    title = labelled.group(1).strip() if labelled else (head[0] if head else "Untitled role")
    company_m = (re.search(r"^company\s*:\s*(.+)$", text, re.I | re.M)
                 or re.search(r"\babout\s+([A-Z][\w&.'-]*(?:[ \t]+[A-Z][\w&.'-]*){0,3})", text)
                 or re.search(r"\b(?:at|join)[ \t]+([A-Z][\w&.'-]*(?:[ \t]+[A-Z][\w&.'-]*){0,2})", text))
    company = company_m.group(1).strip(" .,") if company_m else None
    if company and company.lower() in ("us", "the company", "the role", "you"):
        company = None
    if title and " at " in title and not labelled:
        title, company = title.split(" at ", 1)[0].strip(), company or title.split(" at ", 1)[1].strip()
    return re.sub(r"\s*[-–—|].*$", "", title).strip() or title, company


@register_mock("jd_parse")
def _jd_parse(ctx: dict) -> dict:
    text = ctx.get("text", "")
    preamble, sections = _split_sections(text, _JD_HEADERS)
    title, company = _jd_title_company(preamble, text)
    seniority_m = _SENIORITY.search(title)

    responsibilities = [t for b, t in _collect_bullets(sections.get("responsibilities", [])) if b]
    sources = [(k, sections[k]) for k in ("must", "requirements", "preferred", "nice") if k in sections]
    if not sources and "responsibilities" in sections:
        sources = [("responsibilities", sections["responsibilities"])]
    if not sources:
        sources = [("bullets", preamble)]  # unstructured JD: only bulleted lines are requirements

    competencies = []
    for key, lines in sources:
        for is_bullet, line in _collect_bullets(lines):
            if not is_bullet and key != "requirements":
                continue
            names = _competency_names(line)
            for name in names:
                cat = category_from_text(name)
                if cat == "technical" and len(names) == 1:
                    cat = category_from_text(line)
                importance = importance_from_text(line, _SECTION_IMPORTANCE.get(key, "medium"))
                competencies.append({
                    "name": name, "category": cat, "importance": importance,
                    "required": key in ("must", "requirements", "bullets") and importance in ("critical", "high"),
                    "evidence_quote": line,
                })
    return {
        "role_title": title, "company": company,
        "seniority": seniority_m.group(1).capitalize() if seniority_m else None,
        "responsibilities": responsibilities[:15], "competencies": competencies,
    }


# ---------------- skill_match ----------------

_GENERIC = set(tokenize("experience skills strong ability knowledge work working using management"))


@register_mock("skill_match")
def _skill_match(ctx: dict) -> dict:
    """Token overlap between the competency name and each bullet."""
    bullets = [(b["id"], set(tokenize(b["text"]))) for b in ctx.get("bullets", [])]
    matches = []
    for c in ctx.get("competencies", []):
        name = set(tokenize(c["name"])) - _GENERIC or set(tokenize(c["name"]))
        evidence = []
        for bid, toks in bullets:
            if not name:
                break
            share = len(name & toks) / len(name)
            if share >= 0.99:
                evidence.append({"bullet_id": bid, "strength": "strong"})
            elif share >= 0.5:
                evidence.append({"bullet_id": bid, "strength": "partial"})
        matches.append({"competency_id": c["id"], "evidence": evidence})
    return {"matches": matches}


# ---------------- interview_question / follow-up ----------------

@register_mock("interview_question")
def _interview_question(ctx: dict) -> dict:
    plan = QuestionPlan(**ctx["plan"])
    return {"question": template_question(plan, ctx.get("role_title", ""))}


_PROBES: tuple[tuple[str, str], ...] = (
    ("concept", "Let's make that more precise. How would you define it in your own words, and where does it break down?"),
    ("example", "Can you give me one concrete example from your own work where you did this?"),
    ("trade-off", "What alternatives did you consider, and why did you choose this approach over them?"),
    ("assumption", "What assumptions are you making there, and what would you check first?"),
    ("quantitative", "Can you put rough numbers on that? Walk me through your estimate."),
    ("recommend", "So what would you recommend, and what is the biggest risk with it?"),
    ("personal", "Which part of that was yours specifically, and which decisions did you make yourself?"),
    ("own experience", "Where have you done something like this yourself, and what happened?"),
    ("knowledge", "What does this look like day to day in the role, in practice?"),
)


@register_mock("interview_follow_up")
def _interview_follow_up(ctx: dict) -> dict:
    """Ask for a missing detail (never state it), else probe the first unmet criterion."""
    details = ctx.get("missing_details") or []
    if details:
        ask = details[0].rstrip(".")
        return {"question": f"Let's go a bit deeper. Can you tell me {ask[:1].lower() + ask[1:]}?"}
    for crit in ctx.get("missing_criteria") or []:
        probe = next((q for key, q in _PROBES if key in crit.lower()), None)
        if probe:
            return {"question": probe}
    return {"question": "What trade-offs did you consider, and what would you do differently next time?"}


# ---------------- interview_grade ----------------

_FEATURES: dict[str, re.Pattern[str]] = {
    "situation": re.compile(r"\b(when|while|at my|in my (last|previous)|our team|the project|we were|there was|situation|context)\b", re.I),
    "task": re.compile(r"\b(my (goal|task|job|role|responsibility)|i was (asked|responsible|tasked)|i needed to|we needed to|the goal was|objective)\b", re.I),
    "action": re.compile(r"\bi (built|designed|led|created|wrote|analy[sz]ed|proposed|decided|ran|set up|implemented|worked|organi[sz]ed|met|spoke|negotiated|changed|introduced|automated|owned|reviewed|tested|used|chose|started)\b", re.I),
    "result": re.compile(r"\b(result|resulted|outcome|led to|so that|as a result|improv\w+|reduc\w+|increas\w+|saved|delivered|launched|achieved)\b", re.I),
    "number": re.compile(r"\d"),
    "reflection": re.compile(r"\b(learn(ed|t)|in hindsight|next time|would do differently|i would now|lesson|looking back|reflect\w*)\b", re.I),
    "tradeoff": re.compile(r"\b(trade-?offs?|however|on the other hand|downside|alternative\w*|instead|versus|vs\.?|limitations?|risk\w*|cost)\b", re.I),
    "structure": re.compile(r"\b(first(ly)?|second(ly)?|then|finally|next|step|overall|in summary|to start)\b", re.I),
    "assumption": re.compile(r"\b(assum\w+|clarify|clarifying|it depends|i would ask|first i'?d (ask|check))\b", re.I),
    "recommend": re.compile(r"\b(recommend\w*|i would (suggest|propose|prioriti[sz]e)|my suggestion|i'?d (go with|choose))\b", re.I),
    "baseline": re.compile(r"\b(baseline|before (the|my|we)|from \S+ to \S+|compared (to|with)|previously|starting point)\b", re.I),
    "measure": re.compile(r"\b(measur\w+|metric|defined|definition|tracked|calculated|kpi|dashboard)\b", re.I),
    "method": re.compile(r"\b(method|approach|model|technique|by (using|building|switching)|framework|process)\b", re.I),
    "attribution": re.compile(r"\b(a/?b|control group|attribut\w+|other factors|isolat\w+|causal|seasonality|holdout)\b", re.I),
    "example": re.compile(r"\b(for example|for instance|e\.g\.|in my (last|previous)|at my|once|one time|when i)\b", re.I),
}
_CRITERION_FEATURES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("situation", ("situation",)), ("task:", ("task",)), ("action:", ("action",)),
    ("result", ("result", "number")), ("reflection", ("reflection",)), ("specificity", ("number", "example")),
    ("assumption", ("assumption",)), ("structured approach", ("structure",)), ("quantitative", ("number",)),
    ("recommendation", ("recommend", "tradeoff")), ("baseline", ("baseline", "measure")),
    ("defines the claim", ("measure", "number")), ("personal contribution", ("action",)),
    ("method and trade-offs", ("method", "tradeoff")), ("attribution", ("attribution", "tradeoff")),
    ("trade-offs", ("tradeoff",)), ("clearly structured", ("structure",)), ("concrete", ("example", "action")),
    ("connects to their own experience", ("action", "example")), ("concept", ("concept",)), ("knowledge", ("concept",)),
)
_MISSING_DETAIL = {
    "result": "The concrete outcome of your work and how you measured it",
    "action": "What you personally did, as distinct from the team",
    "baseline": "The baseline before your change and the period you measured over",
    "defines the claim": "How the metric is defined and calculated",
    "attribution": "How you know the change came from your work and not other factors",
    "quantitative": "Rough numbers or estimates to support your reasoning",
}


def _features(answer: str, competency: str | None) -> dict[str, bool]:
    found = {k: bool(p.search(answer)) for k, p in _FEATURES.items()}
    comp = set(tokenize(competency or ""))
    found["concept"] = bool(comp & set(tokenize(answer))) and len(answer.split()) >= 25
    return found


def _status(criterion: str, feats: dict[str, bool], short: bool) -> str:
    low = criterion.lower()
    needed = next((f for key, f in _CRITERION_FEATURES if key in low), ("example",))
    hits = sum(feats.get(f, False) for f in needed)
    if hits == len(needed) and not short:
        return "met"
    return "partial" if hits else "missing"


@register_mock("interview_grade")
def _interview_grade(ctx: dict) -> dict:
    answer = ctx.get("answer", "")
    feats = _features(answer, ctx.get("competency"))
    short = len(answer.split()) < 30
    criteria = []
    for r in ctx.get("rubric", []):
        status = _status(r["criterion"], feats, short)
        criteria.append({"criterion": r["criterion"], "status": status, "evidence": answer[:140] if status != "missing" else ""})
    missing = [c["criterion"] for c in criteria if c["status"] == "missing"]
    details = list(dict.fromkeys(
        text for key, text in _MISSING_DETAIL.items()
        if any(key in m.lower() for m in missing) or (key == "result" and not feats["number"] and any("result" in m.lower() for m in missing))
    ))
    met = [c["criterion"].split(":", 1)[0] for c in criteria if c["status"] == "met"]
    return {
        "criteria": criteria,
        "strengths": [f"Covered: {m.lower()}" for m in met[:3]],
        "improvements": [f"Add: {m.split(':', 1)[-1].strip().lower()}" for m in missing[:3]],
        "missing_details": details[:3],
        "feedback": (
            f"Offline mock evaluation: your answer met {len(met)} of {len(criteria)} rubric criteria. "
            + ("Strengthen it with the missing details listed below, using your own real examples." if missing else "Well structured and specific.")
        ),
    }


# ---------------- interview_deep_dive ----------------

@register_mock("interview_deep_dive")
def _interview_deep_dive(ctx: dict) -> dict:
    items = []
    for b in ctx.get("bullets", []):
        claim = analyse_claim(b["text"])
        q = ("If you had to repeat this with half the time or budget, what would you cut and why?"
             if claim.metric else "Who else was involved, and how did you divide the work?")
        items.append({"bullet_id": b["id"], "questions": [q]})
    return {"items": items}
