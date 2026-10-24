"""Signed-out gap report: resume + JD in, top 5 skills out (CONTRACTS §7, acquisition front door).

Nothing is written to the database. The parsed report lives in a small
in-memory TTL cache keyed by an opaque token, so a visitor who signs up can
keep it (`claim`). Model calls go through a Gateway with no per-user budget and
no usage persistence, but with a process-wide hourly call cap so the endpoint
can't be used to burn the provider budget.

Limits and the cache are shared across API processes when REDIS_URL is set
(app.shared_state); otherwise they are per process.
"""
from __future__ import annotations

import json
import os
import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Callable

from ..ai.gateway import BudgetExceeded, Gateway
from ..clock import user_today
from ..config import get_settings
from ..core.interview_matrix import SkillResult
from ..core.interview_parse import resume_bullets
from ..core.interview_plan import build_plan
from ..core.interview_text import prepare_text
from ..ratelimit import client_ip, trusted_proxy_hops
from ..shared_state import token_bucket, ttl_cache
from . import interview as isvc

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session

TOP_N = 5
TTL_SECONDS = 30 * 60
MAX_ENTRIES = 500
PER_IP_PER_HOUR = int(os.getenv("PUBLIC_REPORT_PER_IP_PER_HOUR", "5"))  # e2e raises it; keep 5 in prod
GLOBAL_CALLS_PER_HOUR = 600  # ~200 reports/hour across all visitors (3 model calls each)
MIN_CHARS, MAX_CHARS = 200, 20_000

# 5 requests per IP per hour: capacity 5, refilled at 5/3600 tokens per second.
ip_limiter = token_bucket("public-report-ip", rate_per_minute=PER_IP_PER_HOUR / 60.0, capacity=PER_IP_PER_HOUR)
_global_calls = token_bucket("public-report-calls", rate_per_minute=GLOBAL_CALLS_PER_HOUR / 60.0,
                             capacity=GLOBAL_CALLS_PER_HOUR)


JOB_URL_PER_IP_PER_HOUR = int(os.getenv("PUBLIC_JOB_URL_PER_IP_PER_HOUR", "20"))
job_url_limiter = token_bucket("public-job-url-ip", rate_per_minute=JOB_URL_PER_IP_PER_HOUR / 60.0,
                               capacity=JOB_URL_PER_IP_PER_HOUR)


share_view_limiter = token_bucket("public-share-ip", rate_per_minute=1.0, capacity=60)


def request_ip(peer: str | None, forwarded_for: str | None) -> str:
    """Client IP using the same proxy-trust rules as the global rate limiter."""
    return client_ip(peer, forwarded_for, trusted_proxy_hops())


def check_ip(ip: str):
    """Returns the limiter Decision; the router maps a refusal to 429 + Retry-After."""
    return ip_limiter.hit(f"public-report:{ip}")


# ---------------- gateway ----------------

def _global_cap(_requested: int) -> None:
    if not _global_calls.hit("public").allowed:
        raise BudgetExceeded("We're getting a lot of report requests right now. Please try again in a few minutes.")


def public_gateway() -> Gateway:
    from ..deps import _get_provider  # the configured provider (mock or Anthropic), shared with signed-in use

    s = get_settings()
    return Gateway(_get_provider(), s.model_main, s.model_fast, budget_check=_global_cap, on_usage=None)


# ---------------- cache ----------------

@dataclass
class CachedReport:
    resume_text: str
    resume_parsed: dict
    resume_warnings: list[str]
    job_text: str
    job_parsed: dict
    skills: list[dict]  # SkillResult fields
    expires_at: datetime
    created: float = field(default_factory=time.monotonic)


class TTLCache:
    def __init__(self, ttl: float = TTL_SECONDS, max_entries: int = MAX_ENTRIES, clock: Callable[[], float] = time.monotonic):
        self.ttl, self.max_entries, self._clock = ttl, max_entries, clock
        self._data: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()

    def _sweep(self, now: float) -> None:
        for k in [k for k, (exp, _) in self._data.items() if exp <= now]:
            del self._data[k]

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            now = self._clock()
            self._sweep(now)
            self._data[key] = (now + self.ttl, value)
            self._data.move_to_end(key)
            while len(self._data) > self.max_entries:
                self._data.popitem(last=False)  # oldest first

    def get(self, key: str) -> Any | None:
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            if item[0] <= self._clock():
                del self._data[key]
                return None
            return item[1]

    def pop(self, key: str) -> Any | None:
        with self._lock:
            item = self._data.pop(key, None)
            if item is None or item[0] <= self._clock():
                return None
            return item[1]

    def __len__(self) -> int:
        return len(self._data)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


def _dump_report(r: CachedReport) -> str:
    d = asdict(r)
    d.pop("created")  # a per-process monotonic reading; meaningless elsewhere
    d["expires_at"] = r.expires_at.isoformat()
    return json.dumps(d)


def _load_report(raw: str) -> CachedReport:
    d = json.loads(raw)
    d["expires_at"] = datetime.fromisoformat(d["expires_at"])
    return CachedReport(**d)


cache = ttl_cache("public-report", TTL_SECONDS, TTLCache(), dumps=_dump_report, loads=_load_report)


# ---------------- report ----------------

_WHY = {
    "knowledge_gap": "Your quiz answers show this isn't solid yet, and the role rates it {imp}.",
    "application_gap": "You know the basics, but the role expects you to apply it ({imp}).",
    "evidence_gap": "The role rates this {imp}, but your resume doesn't show a concrete example yet.",
    "communication_gap": "Your resume shows it, but your answers didn't get it across yet.",
    "unverified": "Your resume claims it, but nothing has tested it yet, and the role rates it {imp}.",
    "stretch": "This is a stretch for your background; the role rates it {imp}.",
    "strong": "Your resume gives clear evidence for this, and the role rates it {imp}.",
}


def why_sentence(gap_type: str, importance: str, has_evidence: bool = False) -> str:
    if gap_type == "evidence_gap" and has_evidence:
        return f"Your resume touches on this, but the role rates it {importance} and wants a clearer example."
    return _WHY.get(gap_type, _WHY["unverified"]).format(imp=importance)


def public_skill(s: SkillResult, jd_quotes: dict[str, str]) -> dict:
    evidence = s.resume_evidence[0]["text"] if s.resume_evidence else None
    return {
        "name": s.name, "importance": s.jd_importance, "gap_type": s.gap_type, "priority": s.effective_priority,
        "assessed_level": s.assessed_level, "evidence_quote": evidence, "jd_quote": jd_quotes.get(s.competency_id, ""),
        "why": why_sentence(s.gap_type, s.jd_importance, evidence is not None), "next_step": s.recommended_action,
    }


def build_report(gw: Gateway, resume_text: str, job_text: str, today: date | None = None) -> dict:
    """Run parse -> match -> score. Raises InputError (unusable text), BudgetExceeded, ModelError, ValueError."""
    if not (MIN_CHARS <= len(resume_text) <= MAX_CHARS) or not (MIN_CHARS <= len(job_text) <= MAX_CHARS):
        raise ValueError(f"Each text must be {MIN_CHARS} to {MAX_CHARS} characters.")
    resume_in = prepare_text(resume_text, "resume")
    job_in = prepare_text(job_text, "job description")
    resume = isvc.parse_resume(gw, resume_in.text)
    job = isvc.parse_job(gw, job_in.text)
    judgements = isvc.match_skills(gw, job.parsed, resume.parsed)
    today = today or user_today()
    inputs = isvc.MatrixInputs(attempts_by_concept={}, interview_by_competency={}, interview_date=None, today=today, overrides={})
    results = isvc.score_matrix(job.parsed, resume.parsed, judgements, inputs)

    warnings = list(dict.fromkeys(resume_in.warnings + job_in.warnings + resume.warnings))
    if not results:
        warnings.append("We couldn't find clear requirements in that job description. Paste the full posting and try again.")
    if not resume_bullets(resume.parsed):
        warnings.append("We couldn't find bullet points in your resume, so evidence may be missing.")

    expires = datetime.now(timezone.utc) + timedelta(seconds=TTL_SECONDS)
    token = secrets.token_urlsafe(24)
    cache.put(token, CachedReport(
        resume_text=resume_in.text, resume_parsed=resume.parsed, resume_warnings=resume_in.warnings + resume.warnings,
        job_text=job_in.text, job_parsed=job.parsed, skills=[asdict(r) for r in results], expires_at=expires,
    ))
    quotes = {c["id"]: c.get("evidence_quote", "") for c in job.parsed.get("competencies") or []}
    return {
        "token": token, "role_title": job.parsed.get("role_title") or "", "company": job.parsed.get("company"),
        "skills": [public_skill(r, quotes) for r in results[:TOP_N]],
        "hidden_count": max(0, len(results) - TOP_N), "warnings": warnings, "expires_at": expires,
    }


# ---------------- claim on signup ----------------

_SKILL_FIELDS = ("name", "category", "jd_importance", "resume_strength", "resume_evidence", "assessed_level",
                 "assessed_explanation", "confidence", "gap_type", "priority", "priority_factors",
                 "recommended_action", "linked_chunk_ids", "user_override")


def claim(token: str | None, user_id: str, db: "Session") -> str | None:
    """Turn a cached report into ResumeProfile + JobProfile + RolePrep + SkillMatch rows. Returns the prep id.

    The token is single-use: it is removed from the cache whether or not it was still valid.
    """
    if not token:
        return None
    entry: CachedReport | None = cache.pop(token)
    if entry is None:
        return None
    from ..models_interview import JobProfile, ResumeProfile, RolePrep, SkillMatch  # lazy: keeps report logic DB-free

    resume = ResumeProfile(owner_id=user_id, source_filename=None, raw_text=entry.resume_text,
                           parsed=entry.resume_parsed, warnings=list(entry.resume_warnings), user_confirmed=False)
    jp = entry.job_parsed
    job = JobProfile(owner_id=user_id, raw_text=entry.job_text, role_title=(jp.get("role_title") or "")[:255],
                     company=jp.get("company"), seniority=jp.get("seniority"), parsed=jp, user_confirmed=False)
    db.add_all([resume, job])
    db.flush()
    results = [SkillResult(**{k: v for k, v in s.items() if k in SkillResult.__dataclass_fields__}) for s in entry.skills]
    prep = RolePrep(owner_id=user_id, resume_id=resume.id, job_id=job.id, document_ids=[], interview_date=None,
                    plan=build_plan(results))
    db.add(prep)
    db.flush()
    for rank, r in enumerate(results):
        row = SkillMatch(prep_id=prep.id, owner_id=user_id, rank=rank, competency_id=r.competency_id)
        for name in _SKILL_FIELDS:
            setattr(row, name, getattr(r, name))
        db.add(row)
    db.commit()
    return prep.id


__all__ = ["TTLCache", "build_report", "cache", "check_ip", "claim", "ip_limiter", "public_gateway", "request_ip", "why_sentence"]
