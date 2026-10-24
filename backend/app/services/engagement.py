"""Engagement use cases: gather Today inputs, weekly strip, countdown, debrief, wins (CONTRACTS §7).

The router stays thin; this module loads owner-scoped rows and hands plain data
to the pure modules `app.core.session_builder` and `app.core.wins`. Every query
filters by owner_id. No model calls happen here.
"""
from __future__ import annotations

import copy
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..clock import local_date, now_utc, user_today, user_tz, user_tz_name
from ..core import session_builder as sb
from ..core.interview_matrix import SkillResult, judgements_from_skills, skill_from_row
from ..core.mastery import AttemptEvidence, MasteryEstimate, estimate
from ..core.wins import SkillState, compute_wins, practised_dates, week_out, week_start
from ..models import Attempt, Document, Question, Quiz, User
from ..models_engagement import InterviewDebrief, StudySession, UserPrefs
from ..models_goals import Goal, PlanItem
from ..models_interview import InterviewSession, InterviewTurn, JobProfile, ResumeProfile, RolePrep, SkillMatch
from .graph import canonical_concept, concept_aliases
from . import interview as isvc
from .goals import build_plan, dropped_reason, topics_from_skills

READY_STATUSES = ("ready", "needs_attention")
GAP_PRIORITIES = ("critical", "high")
LEARNING_GOAL_DAYS = 28
LEARNING_GOAL_MINUTES = 30


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _day_start(d: date) -> datetime:
    """Start of the user's local day ``d``, in UTC (stored timestamps are UTC)."""
    return datetime.combine(d, time.min, tzinfo=user_tz.get()).astimezone(timezone.utc)


# ---------------- prefs ----------------

def get_prefs(user: User, db: Session) -> UserPrefs:
    """The user's prefs row, created with defaults on first read."""
    prefs = db.get(UserPrefs, user.id)
    if prefs is None:
        prefs = UserPrefs(owner_id=user.id, preparing_for=None, weekly_target=3, default_minutes=15, reminders=False,
                          quiet_start="21:00", quiet_end="08:00", reduce_transparency=False, onboarded_at=None)
        db.add(prefs)
        try:
            db.commit()
        except IntegrityError:  # a concurrent first read created it
            db.rollback()
            prefs = db.get(UserPrefs, user.id)
    if prefs.onboarded_at is None:
        _infer_onboarding(user, prefs, db)
    tz = user_tz_name()
    if tz and prefs.timezone != tz:  # remembered so reminder emails go out in the user's own evening
        prefs.timezone = tz
        db.commit()
    return prefs


def _infer_onboarding(user: User, prefs: UserPrefs, db: Session) -> None:
    """Someone who has already saved a prep, built a goal or uploaded material has answered
    "What are you preparing for?" by doing it, so Today shouldn't ask again."""
    has_prep = db.scalar(select(RolePrep.id).where(RolePrep.owner_id == user.id).limit(1)) is not None
    goal_type = db.scalar(select(Goal.goal_type).where(Goal.owner_id == user.id).order_by(Goal.created_at).limit(1))
    has_doc = db.scalar(select(Document.id).where(Document.owner_id == user.id).limit(1)) is not None
    if not (has_prep or goal_type or has_doc):
        return
    if prefs.preparing_for is None:
        prefs.preparing_for = "interview" if has_prep or goal_type == "interview" else ("exam" if goal_type == "exam" else "learn")
    prefs.onboarded_at = now_utc()
    prefs.updated_at = now_utc()
    db.commit()


def prefs_dict(p: UserPrefs) -> dict:
    return {
        "preparing_for": p.preparing_for, "weekly_target": p.weekly_target, "default_minutes": p.default_minutes,
        "reminders": bool(p.reminders), "quiet_start": p.quiet_start, "quiet_end": p.quiet_end,
        "reduce_transparency": bool(p.reduce_transparency), "onboarded": p.onboarded_at is not None,
    }


def apply_prefs_patch(p: UserPrefs, data: dict) -> None:
    """`data` is PrefsPatch.model_dump(exclude_unset=True); validation already happened in the schema."""
    if "preparing_for" in data:
        p.preparing_for = data["preparing_for"]  # nullable: null clears it
    for k in ("weekly_target", "default_minutes", "reminders", "quiet_start", "quiet_end", "reduce_transparency"):
        if data.get(k) is not None:
            setattr(p, k, data[k])
    if data.get("onboarded") is True and p.onboarded_at is None:
        p.onboarded_at = now_utc()
    p.updated_at = now_utc()


# ---------------- mastery ----------------

@dataclass
class _Evidence:
    by_concept: dict[str, list[AttemptEvidence]]
    docs_by_concept: dict[str, list[str]]


def _evidence(user_id: str, db: Session, before: datetime | None = None) -> _Evidence:
    """Same evidence as GET /progress: unflagged questions, assessed attempts, oldest first."""
    q = (
        select(Attempt, Question, Quiz.document_ids)
        .join(Question, Question.id == Attempt.question_id)
        .join(Quiz, Quiz.id == Question.quiz_id)
        .where(Attempt.owner_id == user_id, Question.flagged.is_(None))
        .order_by(Attempt.created_at)
    )
    if before is not None:
        q = q.where(Attempt.created_at < before)
    by_concept: dict[str, list[AttemptEvidence]] = defaultdict(list)
    docs: dict[str, list[str]] = defaultdict(list)
    aliases = concept_aliases(db, user_id)  # merged concepts count as one
    for a, qn, doc_ids in db.execute(q).all():
        if a.verdict == "unassessed":
            continue
        concept = canonical_concept(qn.concept, aliases)
        by_concept[concept].append(AttemptEvidence(a.score, qn.qtype, qn.difficulty, a.created_at))
        for d in doc_ids or []:
            if d not in docs[concept]:
                docs[concept].append(d)
    return _Evidence(dict(by_concept), dict(docs))


def mastery(user_id: str, db: Session, now: datetime | None = None, before: datetime | None = None) -> dict[str, MasteryEstimate]:
    ev = _evidence(user_id, db, before)
    return {c: estimate(c, a, now) for c, a in ev.by_concept.items()}


# ---------------- preps ----------------

def active_prep(user_id: str, db: Session, today: date) -> tuple[RolePrep, JobProfile] | None:
    """Most recent prep whose interview is today or later, or has no date."""
    row = db.execute(
        select(RolePrep, JobProfile)
        .join(JobProfile, JobProfile.id == RolePrep.job_id)
        .where(RolePrep.owner_id == user_id, JobProfile.owner_id == user_id,
               (RolePrep.interview_date.is_(None)) | (RolePrep.interview_date >= today))
        .order_by(RolePrep.created_at.desc())
        .limit(1)
    ).first()
    return (row[0], row[1]) if row else None


def _effective_priority(s: SkillMatch) -> str:
    return ((s.user_override or {}).get("priority") if isinstance(s.user_override, dict) else None) or s.priority


def top_gaps(prep: RolePrep, job: JobProfile, db: Session, limit: int = 3) -> list[sb.PrepGap]:
    rows = db.scalars(
        select(SkillMatch).where(SkillMatch.prep_id == prep.id, SkillMatch.owner_id == prep.owner_id).order_by(SkillMatch.rank)
    ).all()
    gaps = [s for s in rows if s.gap_type != "strong" and _effective_priority(s) in GAP_PRIORITIES]
    gaps.sort(key=lambda s: (0 if _effective_priority(s) == "critical" else 1, s.rank))
    return [
        sb.PrepGap(prep_id=prep.id, skill_id=s.id, name=s.name, priority=_effective_priority(s), gap_type=s.gap_type,
                   category=s.category, role_title=job.role_title or "", company=job.company)
        for s in gaps[:limit]
    ]


# ---------------- builder input ----------------

def ready_documents(user_id: str, db: Session) -> list[Document]:
    return list(db.scalars(
        select(Document).where(Document.owner_id == user_id, Document.status.in_(READY_STATUSES)).order_by(Document.created_at.desc())
    ).all())


def todays_plan_items(user_id: str, db: Session, today: date) -> list[tuple[PlanItem, Goal]]:
    """Pending items scheduled today across active goals (same query as GET /today)."""
    rows = db.execute(
        select(PlanItem, Goal)
        .join(Goal, Goal.id == PlanItem.goal_id)
        .where(PlanItem.owner_id == user_id, Goal.owner_id == user_id, Goal.status == "active",
               PlanItem.scheduled_date == today, PlanItem.status == "pending")
        .order_by(Goal.created_at, PlanItem.position)
    ).all()
    return [(i, g) for i, g in rows]


def builder_input(user_id: str, db: Session, now: datetime | None = None) -> sb.BuilderInput:
    now = now or now_utc()
    today = local_date(now)
    ev = _evidence(user_id, db)
    ready = ready_documents(user_id, db)
    ready_ids = {d.id for d in ready}
    estimates = [estimate(c, a, now) for c, a in ev.by_concept.items()]

    def docs_for(concept: str) -> list[str]:
        return [d for d in ev.docs_by_concept.get(concept, []) if d in ready_ids]

    due = sorted((m for m in estimates if m.due_for_review),
                 key=lambda m: (m.level != "weak", _aware(m.last_assessed_at) if m.last_assessed_at else now, m.concept.casefold()))
    reviews = [
        sb.DueReview(m.concept, max(0, (now - _aware(m.last_assessed_at)).days) if m.last_assessed_at else 0, m.level, docs_for(m.concept))
        for m in due
    ]
    roots = root_causes(user_id, db, estimates, docs_for, ready_ids)
    fresh_rows = sorted((m for m in estimates if m.level == "unverified" and not m.due_for_review),
                        key=lambda m: (-m.evidence_count, m.concept.casefold()))
    fresh = [sb.FreshConcept(m.concept, m.evidence_count, docs_for(m.concept)) for m in fresh_rows]

    plan = [
        sb.PlanItemIn(id=i.id, goal_id=g.id, goal_title=g.title, topic=i.topic, estimated_minutes=i.estimated_minutes,
                      concept=i.concept, activity_type=i.activity_type)
        for i, g in todays_plan_items(user_id, db, today)
    ]
    gaps: list[sb.PrepGap] = []
    preps: list[sb.PrepRef] = []
    ap = active_prep(user_id, db, today)
    if ap:
        prep, job = ap
        gaps = top_gaps(prep, job, db)
        preps = [sb.PrepRef(prep.id, job.role_title or "", job.company)]
    docs = [sb.DocRef(d.id, d.title or d.filename) for d in ready]
    return sb.BuilderInput(due_reviews=reviews, root_causes=roots, plan_items=plan, prep_gaps=gaps, fresh=fresh,
                           documents=docs, preps=preps)


MAX_WEAK_CHECKED = 5


def root_causes(user_id: str, db: Session, estimates: list[MasteryEstimate], docs_for, ready_ids: set[str]) -> list[sb.RootCause]:
    """For each weak concept (weakest first), the nearest prerequisite that is itself weak or untested
    and has material to practise from (knowledge graph, P2: root-cause practice)."""
    from .concepts import documents_covering
    from .knowledge_graph import canonical_key, direct_prerequisite_verified, prerequisite_chain

    by_key = {canonical_key(m.concept): m for m in estimates}
    out: list[sb.RootCause] = []
    for m in sorted((m for m in estimates if m.level == "weak"), key=lambda m: m.estimate)[:MAX_WEAK_CHECKED]:
        for name, depth in prerequisite_chain(db, user_id, m.concept, max_depth=2):
            pm = by_key.get(canonical_key(name))
            level = pm.level if pm else "unverified"
            if level not in ("weak", "unverified"):
                continue
            docs = docs_for(name) or [d for d in documents_covering(db, user_id, name) if d in ready_ids] or docs_for(m.concept)
            if not docs:
                continue
            grounded = depth == 1 and direct_prerequisite_verified(db, user_id, name, m.concept)
            out.append(sb.RootCause(name, m.concept, level, grounded, docs))
            break
    return out


# ---------------- week ----------------

def practised_in_range(user_id: str, db: Session, start: date, end_exclusive: date,
                       exclude_session_id: str | None = None, attempts_before: datetime | None = None) -> set[date]:
    lo, hi = _day_start(start), _day_start(end_exclusive)
    sq = select(StudySession.completed_at).where(
        StudySession.owner_id == user_id, StudySession.status == "completed",
        StudySession.completed_at.is_not(None), StudySession.completed_at >= lo, StudySession.completed_at < hi,
    )
    if exclude_session_id:
        sq = sq.where(StudySession.id != exclude_session_id)
    aq = select(Attempt.created_at).where(Attempt.owner_id == user_id, Attempt.created_at >= lo, Attempt.created_at < hi)
    if attempts_before is not None:
        aq = aq.where(Attempt.created_at < attempts_before)
    sessions = [local_date(d) for d in db.scalars(sq).all() if d is not None]
    attempts = [local_date(d) for d in db.scalars(aq).all() if d is not None]
    return {d for d in practised_dates(sessions, attempts) if start <= d < end_exclusive}


def week(user: User, db: Session, today: date | None = None) -> dict:
    today = today or user_today()
    start = week_start(today)
    target = get_prefs(user, db).weekly_target
    return week_out(today, practised_in_range(user.id, db, start, start + timedelta(days=7)), target)


# ---------------- today preview ----------------

def countdown(user_id: str, db: Session, today: date) -> dict | None:
    row = db.execute(
        select(RolePrep, JobProfile)
        .join(JobProfile, JobProfile.id == RolePrep.job_id)
        .where(RolePrep.owner_id == user_id, RolePrep.interview_date.is_not(None), RolePrep.interview_date >= today)
        .order_by(RolePrep.interview_date, RolePrep.created_at.desc())
        .limit(1)
    ).first()
    if not row:
        return None
    prep, job = row
    return {"prep_id": prep.id, "role_title": job.role_title or "", "company": job.company,
            "interview_date": prep.interview_date, "days_left": (prep.interview_date - today).days}


def debrief_due(user_id: str, db: Session, today: date) -> dict | None:
    debriefed = select(InterviewDebrief.prep_id).where(InterviewDebrief.owner_id == user_id)
    row = db.execute(
        select(RolePrep, JobProfile)
        .join(JobProfile, JobProfile.id == RolePrep.job_id)
        .where(RolePrep.owner_id == user_id, RolePrep.interview_date.is_not(None), RolePrep.interview_date < today,
               RolePrep.id.not_in(debriefed))
        .order_by(RolePrep.interview_date.desc())
        .limit(1)
    ).first()
    if not row:
        return None
    prep, job = row
    return {"prep_id": prep.id, "role_title": job.role_title or "", "company": job.company, "interview_date": prep.interview_date}


def last_win(user_id: str, db: Session) -> dict | None:
    s = db.scalar(
        select(StudySession).where(StudySession.owner_id == user_id, StudySession.status == "completed")
        .order_by(StudySession.completed_at.desc()).limit(1)
    )
    return (s.wins or [None])[0] if s else None


def _count(db: Session, q) -> int:
    return int(db.scalar(select(func.count()).select_from(q.subquery())) or 0)


def today_preview(user: User, db: Session) -> dict:
    now = now_utc()
    today = local_date(now)
    inp = builder_input(user.id, db, now)
    library_count = _count(db, select(Document.id).where(Document.owner_id == user.id))
    has_prep = _count(db, select(RolePrep.id).where(RolePrep.owner_id == user.id)) > 0
    has_goal = _count(db, select(Goal.id).where(Goal.owner_id == user.id, Goal.status == "active")) > 0
    if library_count == 0 and not has_prep:
        empty_reason = "no_material"
    elif not has_goal and not inp.preps:
        empty_reason = "no_goal"
    else:
        empty_reason = None
    display = (user.display_name or "").strip()
    name = display.split()[0] if display else ""
    return {
        "greeting_name": name,
        "countdown": countdown(user.id, db, today),
        "week": week(user, db, today),
        "suggestions": sb.build_suggestions(inp),
        "last_win": last_win(user.id, db),
        "debrief_due": debrief_due(user.id, db, today),
        "empty_reason": empty_reason,
        "library_count": library_count,
    }


# ---------------- sessions ----------------

def start_session(user: User, db: Session, minutes: int) -> StudySession | None:
    steps = sb.build_session(minutes, builder_input(user.id, db))
    if not steps:
        return None
    s = StudySession(owner_id=user.id, minutes=minutes, steps=steps, status="active", wins=[], started_at=now_utc())
    db.add(s)
    db.commit()
    return s


def update_step(s: StudySession, step_id: str, status: str, quiz_id: str | None, db: Session) -> bool:
    """Returns False when the step doesn't exist. Reassigns the JSON list so the change is persisted."""
    steps = copy.deepcopy(list(s.steps or []))
    step = next((x for x in steps if x.get("id") == step_id), None)
    if step is None:
        return False
    step["status"] = status
    target = step.get("target") or {}
    if quiz_id and target.get("type") == "quiz":
        target["quiz_id"] = quiz_id
    if status == "done" and target.get("type") == "plan_item":
        item = db.scalar(select(PlanItem).where(PlanItem.id == target.get("item_id"), PlanItem.owner_id == s.owner_id))
        if item is not None and item.status == "pending":
            item.status = "done"
            item.completed_at = now_utc()
    s.steps = steps
    db.commit()
    return True


def _turns(prep_id: str, user_id: str, db: Session, before: datetime | None) -> list[tuple[str | None, dict | None]]:
    q = (
        select(InterviewTurn.competency_id, InterviewTurn.evaluation)
        .join(InterviewSession, InterviewSession.id == InterviewTurn.session_id)
        .where(InterviewSession.prep_id == prep_id, InterviewTurn.owner_id == user_id)
    )
    if before is not None:
        q = q.where((InterviewTurn.answered_at.is_(None)) | (InterviewTurn.answered_at < before))
    return [(r[0], r[1]) for r in db.execute(q).all()]


def _skill_states(prep: RolePrep, job: JobProfile, user_id: str, db: Session, now: datetime,
                  before: datetime | None) -> dict[str, SkillState]:
    """Gap type per competency, rescored in code from stored judgements (no model call)."""
    resume = db.scalar(select(ResumeProfile).where(ResumeProfile.id == prep.resume_id, ResumeProfile.owner_id == user_id))
    rows = db.scalars(select(SkillMatch).where(SkillMatch.prep_id == prep.id, SkillMatch.owner_id == user_id)).all()
    if resume is None or not rows:
        return {}
    stored: list[SkillResult] = [skill_from_row({c: getattr(r, c) for c in SkillResult.__dataclass_fields__}) for r in rows]
    inputs = isvc.MatrixInputs(
        attempts_by_concept=_evidence(user_id, db, before).by_concept,
        interview_by_competency=isvc.interview_signals(_turns(prep.id, user_id, db, before)),
        interview_date=prep.interview_date, today=local_date(now),
        overrides={r.competency_id: r.user_override for r in rows if r.user_override}, now=now,
    )
    results = isvc.score_matrix(job.parsed or {}, resume.parsed or {}, judgements_from_skills(stored), inputs)
    label = job.company or job.role_title or ""
    return {f"{prep.id}:{r.competency_id}": SkillState(r.name, r.gap_type, label) for r in results}


def complete_session(user: User, s: StudySession, db: Session) -> None:
    if s.status == "completed":
        return
    now = now_utc()
    start = _aware(s.started_at)
    before = mastery(user.id, db, now=now, before=start)
    after_all = mastery(user.id, db, now=now)
    attempts_before = _count(db, select(Attempt.id).where(Attempt.owner_id == user.id, Attempt.created_at < start))
    in_session_rows = db.execute(
        select(Attempt.created_at, Question.concept)
        .join(Question, Question.id == Attempt.question_id)
        .where(Attempt.owner_id == user.id, Attempt.created_at >= start)
    ).all()
    touched = {c for _, c in in_session_rows}
    after = {c: m.level for c, m in after_all.items() if c in touched}

    skills_before: dict[str, SkillState] = {}
    skills_after: dict[str, SkillState] = {}
    ap = active_prep(user.id, db, local_date(now))
    if ap:
        prep, job = ap
        skills_before = _skill_states(prep, job, user.id, db, now, start)
        skills_after = _skill_states(prep, job, user.id, db, now, None)

    today = local_date(now)
    wk = week_start(today)
    days_before = practised_in_range(user.id, db, wk, wk + timedelta(days=7), exclude_session_id=s.id, attempts_before=start)
    days_after = practised_in_range(user.id, db, wk, wk + timedelta(days=7), exclude_session_id=s.id) | {today}
    target = get_prefs(user, db).weekly_target

    s.wins = compute_wins(
        levels_before={c: m.level for c, m in before.items()}, levels_after=after,
        attempts_before=attempts_before, attempts_in_session=len(in_session_rows),
        skills_before=skills_before, skills_after=skills_after,
        week_done_before=len(days_before), week_done_after=len(days_after), weekly_target=target,
    )
    s.status = "completed"
    s.completed_at = now
    db.commit()


# ---------------- debrief follow-ups ----------------

def copy_prep(prep: RolePrep, db: Session) -> RolePrep:
    """Next round: same resume, JD, documents and matrix; no date yet."""
    new = RolePrep(owner_id=prep.owner_id, resume_id=prep.resume_id, job_id=prep.job_id,
                   document_ids=list(prep.document_ids or []), interview_date=None, plan=copy.deepcopy(prep.plan or []))
    db.add(new)
    db.flush()
    rows = db.scalars(select(SkillMatch).where(SkillMatch.prep_id == prep.id, SkillMatch.owner_id == prep.owner_id).order_by(SkillMatch.rank)).all()
    for r in rows:
        db.add(SkillMatch(
            prep_id=new.id, owner_id=prep.owner_id, rank=r.rank, competency_id=r.competency_id, name=r.name,
            category=r.category, jd_importance=r.jd_importance, resume_strength=r.resume_strength,
            resume_evidence=copy.deepcopy(r.resume_evidence or []), assessed_level=r.assessed_level,
            assessed_explanation=r.assessed_explanation, confidence=r.confidence, gap_type=r.gap_type,
            priority=r.priority, priority_factors=copy.deepcopy(r.priority_factors or {}),
            recommended_action=r.recommended_action, linked_chunk_ids=list(r.linked_chunk_ids or []),
            user_override=copy.deepcopy(r.user_override) if r.user_override else None,
        ))
    db.flush()
    return new


def remaining_gap_topics(prep: RolePrep, db: Session) -> list:
    rows = db.scalars(select(SkillMatch).where(SkillMatch.prep_id == prep.id, SkillMatch.owner_id == prep.owner_id).order_by(SkillMatch.rank)).all()
    return topics_from_skills([
        {"name": s.name, "priority": s.priority, "gap_type": s.gap_type, "user_override": s.user_override,
         "linked_chunk_ids": list(s.linked_chunk_ids or []), "recommended_action": s.recommended_action}
        for s in rows
    ])


def learning_goal_from_prep(prep: RolePrep, job: JobProfile, topics: list, db: Session, today: date | None = None) -> Goal:
    """A `learn` goal over the prep's remaining gaps, scheduled in code (no model call)."""
    today = today or user_today()
    deadline = today + timedelta(days=LEARNING_GOAL_DAYS)
    study_days = [0, 1, 2, 3, 4]
    role = (job.role_title or "").strip() or "your interview"
    goal = Goal(
        owner_id=prep.owner_id, goal_type="learn", title=f"Keep learning: {role}"[:255],
        target_outcome=f"Close the gaps that are left from the {role} interview."[:2000],
        deadline=deadline, minutes_per_day=LEARNING_GOAL_MINUTES, study_days=study_days, current_level="standard",
        document_ids=list(prep.document_ids or []), prep_id=prep.id, status="active",
    )
    db.add(goal)
    db.flush()
    entries, _warning, dropped = build_plan(
        today=today, goal_type="learn", deadline=deadline, minutes_per_day=LEARNING_GOAL_MINUTES,
        study_days=study_days, level="standard", topics=topics, interview=False,
    )
    pos = 0
    for e in entries:
        if e.fixed:
            continue
        db.add(PlanItem(
            goal_id=goal.id, owner_id=prep.owner_id, position=pos, scheduled_date=e.scheduled_date, topic=e.topic[:255],
            concept=(e.concept or None) and e.concept[:120], activity_type=e.activity_type,
            estimated_minutes=e.estimated_minutes, objective=e.objective, source_chunk_ids=list(e.source_chunk_ids),
            status="pending", user_edited=False, reason=e.reason,
        ))
        pos += 1
    for t in dropped:
        db.add(PlanItem(
            goal_id=goal.id, owner_id=prep.owner_id, position=pos, scheduled_date=deadline, topic=t.topic[:255],
            concept=(t.concept or None) and t.concept[:120], activity_type=t.activity, estimated_minutes=t.est_minutes,
            objective=t.objective, source_chunk_ids=list(t.source_chunk_ids), status="skipped", user_edited=False,
            reason=dropped_reason(LEARNING_GOAL_MINUTES, deadline),
        ))
        pos += 1
    db.flush()
    return goal
