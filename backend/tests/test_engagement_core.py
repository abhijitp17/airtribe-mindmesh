"""Pure tests for engagement (CONTRACTS §7): session builder, wins, week strip, public report pieces."""
import random
from datetime import date, timedelta

import pytest

from app.ai.gateway import Gateway
from app.ai.mock import MockProvider
from app.core.session_builder import (
    COST,
    BuilderInput,
    DocRef,
    DueReview,
    FreshConcept,
    PlanItemIn,
    PrepGap,
    PrepRef,
    build_session,
    build_suggestions,
)
from app.core.wins import SkillState, compute_wins, practised_dates, week_out, week_start
from app.ratelimit import TokenBucketLimiter
from app.services import public_report as pr
from tests.test_interview_samples import SAMPLE_JD, SAMPLE_RESUME

KINDS = {"review", "quiz", "learn", "story", "mock_question", "plan_item"}
TARGET_KEYS = {
    "quiz": {"type", "quiz_id", "document_ids", "focus"},
    "interview": {"type", "prep_id", "session_id"},
    "plan_item": {"type", "goal_id", "item_id"},
    "link": {"type", "href"},
}
STEP_KEYS = {"id", "kind", "title", "detail", "minutes", "concept", "target", "status"}


def _full():
    return BuilderInput(
        due_reviews=[DueReview("Little's Law", 9, "developing", ["d1"]), DueReview("Variability", 2, "weak", ["d1"])],
        plan_items=[PlanItemIn("i1", "g1", "Pass ops exam", "Queueing basics", 10, "Queueing")],
        prep_gaps=[PrepGap("p1", "s1", "Stakeholder management", "critical", "evidence_gap", "behavioral", "Analyst", "Amazon")],
        fresh=[FreshConcept("Kingman", 1, ["d1"])],
        documents=[DocRef("d1", "Factory Physics")],
        preps=[PrepRef("p1", "Analyst", "Amazon")],
    )


def _check_shape(step):
    assert set(step) == STEP_KEYS
    assert step["kind"] in KINDS and step["status"] == "pending"
    assert isinstance(step["minutes"], int) and step["minutes"] >= 1
    assert set(step["target"]) == TARGET_KEYS[step["target"]["type"]]
    assert step["detail"] and step["detail"].endswith(".") and "\n" not in step["detail"]
    assert len(step["detail"]) <= 120


# ---------- builder: priority, costs, fill ----------

def test_priority_order_for_30_minutes():
    steps = build_session(30, _full())
    kinds = [s["kind"] for s in steps]
    assert kinds[:4] == ["review", "review", "plan_item", "story"]
    assert steps[0]["concept"] == "Little's Law"  # the service orders reviews; the builder keeps that order
    assert steps[1]["detail"] == "Due for review: this was shaky when you last practised it 2 days ago."
    assert sum(s["minutes"] for s in steps) <= 30
    for s in steps:
        _check_shape(s)


def test_reviews_keep_input_order_and_detail():
    steps = build_session(15, _full())
    assert steps[0]["title"] == "Review Little's Law"
    assert steps[0]["detail"] == "Due for review: last practised 9 days ago."
    assert steps[0]["target"] == {"type": "quiz", "quiz_id": None, "document_ids": ["d1"], "focus": "Little's Law"}


def test_time_costs():
    inp = _full()
    steps = build_session(30, inp)
    by_kind = {s["kind"]: s["minutes"] for s in steps if s["kind"] != "plan_item"}
    for k, m in by_kind.items():
        assert m == COST[k]
    plan = next(s for s in steps if s["kind"] == "plan_item")
    assert plan["minutes"] == 10
    assert plan["target"] == {"type": "plan_item", "goal_id": "g1", "item_id": "i1"}


def test_plan_item_capped_at_remaining():
    inp = BuilderInput(plan_items=[PlanItemIn("i1", "g1", "Goal", "Long topic", 45)])
    steps = build_session(15, inp)
    assert len(steps) == 1 and steps[0]["minutes"] == 15
    five = build_session(5, inp)
    assert len(five) == 1 and five[0]["minutes"] == 5


def test_five_minutes_is_exactly_one_step():
    steps = build_session(5, _full())
    assert len(steps) == 1 and steps[0]["kind"] == "review"


def test_critical_gap_detail_mentions_company():
    inp = BuilderInput(prep_gaps=[PrepGap("p1", "s1", "SQL", "critical", "unverified", "technical", "Analyst", "Amazon")])
    steps = build_session(15, inp)
    assert steps[0]["kind"] == "mock_question"
    assert steps[0]["detail"] == "Critical for your Amazon role."
    assert steps[0]["target"] == {"type": "interview", "prep_id": "p1", "session_id": None}


def test_story_step_degrades_to_question_in_five_minutes():
    inp = BuilderInput(prep_gaps=[PrepGap("p1", "s1", "Leadership", "high", "evidence_gap", "leadership", "PM", None)])
    assert build_session(15, inp)[0]["kind"] == "story"
    five = build_session(5, inp)
    assert len(five) == 1 and five[0]["kind"] == "mock_question" and five[0]["minutes"] == 5
    assert five[0]["detail"] == "High priority for your PM role."


def test_learn_gap_target_is_link():
    inp = BuilderInput(prep_gaps=[PrepGap("p1", "s1", "Kubernetes", "high", "knowledge_gap")])
    s = build_session(15, inp)[0]
    assert s["kind"] == "learn" and s["minutes"] == 8 and s["target"] == {"type": "link", "href": "/interview/p1"}


def test_fallback_doc_quiz_when_only_material():
    inp = BuilderInput(documents=[DocRef("d1", "Factory Physics")])
    for m in (5, 15, 30):
        steps = build_session(m, inp)
        assert steps and steps[0]["title"] == "Take a 5-question quiz on Factory Physics"
        assert steps[0]["target"]["document_ids"] == ["d1"]


def test_fallback_question_when_only_prep():
    inp = BuilderInput(preps=[PrepRef("p1", "Data analyst", None)])
    steps = build_session(5, inp)
    assert len(steps) == 1 and steps[0]["kind"] == "mock_question"
    assert steps[0]["detail"] == "Keeps your practice for your Data analyst role going."


def test_empty_input_gives_empty_list():
    assert build_session(30, BuilderInput()) == []
    assert build_suggestions(BuilderInput()) == {"5": [], "15": [], "30": []}


def test_invalid_minutes():
    with pytest.raises(ValueError, match="5, 15 or 30"):
        build_session(10, _full())


def test_step_ids_stable_and_unique():
    a, b = build_session(30, _full()), build_session(30, _full())
    assert [s["id"] for s in a] == [s["id"] for s in b]
    assert len({s["id"] for s in a}) == len(a)
    # The same subject gets the same id across time choices
    sug = build_suggestions(_full())
    assert sug["5"][0]["id"] == sug["30"][0]["id"]


def test_duplicate_concepts_collapse():
    inp = BuilderInput(due_reviews=[DueReview("SQL", 3), DueReview("sql ", 4)], fresh=[FreshConcept("SQL")])
    steps = build_session(30, inp)
    assert [s["kind"] for s in steps] == ["review"]


def test_doc_fallback_skipped_when_covered():
    inp = BuilderInput(fresh=[FreshConcept("Kingman", 0, ["d1"])], documents=[DocRef("d1", "FP"), DocRef("d2", "Other")])
    steps = build_session(30, inp)
    titles = [s["title"] for s in steps]
    assert "Take a 5-question quiz on FP" not in titles and "Take a 5-question quiz on Other" in titles


def _random_input(rng):
    n = rng.randint
    return BuilderInput(
        due_reviews=[DueReview(f"C{i}", n(0, 30), rng.choice(["weak", "developing", "strong"]), [f"d{n(0, 2)}"]) for i in range(n(0, 5))],
        plan_items=[PlanItemIn(f"i{i}", "g", "Goal", f"Topic {i}", n(1, 90)) for i in range(n(0, 4))],
        prep_gaps=[PrepGap("p", f"s{i}", f"Skill {i}", rng.choice(["critical", "high"]),
                           rng.choice(["evidence_gap", "knowledge_gap", "unverified", "communication_gap", "stretch", "application_gap"]),
                           "technical", "Role", rng.choice([None, "Acme"])) for i in range(n(0, 4))],
        fresh=[FreshConcept(f"F{i}", n(0, 2), []) for i in range(n(0, 4))],
        documents=[DocRef(f"d{i}", f"Doc {i}") for i in range(n(0, 3))],
        preps=[PrepRef("p", "Role", None)] if rng.random() < 0.4 else [],
    )


def test_randomised_invariants():
    rng = random.Random(1234)
    for _ in range(600):
        inp = _random_input(rng)
        sug = build_suggestions(inp)
        for key, steps in sug.items():
            m = int(key)
            assert sum(s["minutes"] for s in steps) <= m, (m, steps)
            assert len({s["id"] for s in steps}) == len(steps)
            if m == 5:
                assert len(steps) <= 1
            if inp.has_material():
                assert steps, (m, inp)
            for s in steps:
                _check_shape(s)
        assert build_suggestions(inp) == sug  # deterministic


def test_randomised_priority_respected():
    rank = {"review": 0, "plan_item": 1}
    rng = random.Random(99)
    for _ in range(300):
        inp = _random_input(rng)
        steps = build_session(30, inp)
        seen = [rank.get(s["kind"], 2) for s in steps if s["id"].split("-")[0] in ("review", "plan")]
        assert seen == sorted(seen)
        if inp.due_reviews:
            assert steps[0]["kind"] == "review"


# ---------- wins ----------

def test_level_up_title():
    wins = compute_wins(levels_before={"Little's Law": "developing"}, levels_after={"Little's Law": "strong"},
                        attempts_before=10, attempts_in_session=2)
    assert wins == [{"kind": "level_up", "title": "Little's Law is now strong",
                     "detail": "It moved up from developing after this session."}]


def test_unverified_to_weak_is_not_a_win():
    assert compute_wins(levels_before={}, levels_after={"X": "weak"}, attempts_before=5, attempts_in_session=3) == []
    assert compute_wins(levels_before={"X": "strong"}, levels_after={"X": "developing"}, attempts_before=5, attempts_in_session=1) == []


def test_first_answer_and_rating():
    wins = compute_wins(levels_before={}, levels_after={"SQL": "developing"}, attempts_before=0, attempts_in_session=3)
    assert [w["kind"] for w in wins] == ["first_answer", "level_up"]
    assert wins[1]["title"] == "SQL is now developing"


def test_no_attempts_no_first_answer():
    assert compute_wins(levels_before={}, levels_after={}, attempts_before=0, attempts_in_session=0) == []


def test_gap_closed():
    before = {"p:c1": SkillState("SQL", "unverified", "Amazon"), "p:c2": SkillState("Python", "strong")}
    after = {"p:c1": SkillState("SQL", "strong", "Amazon"), "p:c2": SkillState("Python", "strong")}
    wins = compute_wins(levels_before={}, levels_after={}, attempts_before=3, attempts_in_session=1,
                        skills_before=before, skills_after=after)
    assert wins == [{"kind": "gap_closed", "title": "SQL is no longer a gap",
                     "detail": "Your answers now show SQL is strong for your Amazon role."}]


def test_target_met_only_when_crossing():
    base = dict(levels_before={}, levels_after={}, attempts_before=3, attempts_in_session=0)
    assert [w["kind"] for w in compute_wins(**base, week_done_before=2, week_done_after=3, weekly_target=3)] == ["target_met"]
    assert compute_wins(**base, week_done_before=3, week_done_after=3, weekly_target=3) == []
    assert compute_wins(**base, week_done_before=1, week_done_after=2, weekly_target=3) == []


# ---------- week ----------

def test_week_start_is_monday():
    assert week_start(date(2026, 10, 10)) == date(2026, 10, 5)  # Saturday -> Monday
    assert week_start(date(2026, 10, 5)) == date(2026, 10, 5)
    assert week_start(date(2026, 10, 11)) == date(2026, 10, 5)  # Sunday


def test_week_out():
    today = date(2026, 10, 8)  # Thursday
    practised = practised_dates([date(2026, 10, 5)], [date(2026, 10, 5), date(2026, 10, 8), date(2026, 10, 1), date(2026, 10, 12)])
    w = week_out(today, practised, 3)
    assert w["target"] == 3 and w["done"] == 2
    assert [d["date"] for d in w["days"]] == [(date(2026, 10, 5) + timedelta(days=i)).isoformat() for i in range(7)]
    assert [d["practised"] for d in w["days"]] == [True, False, False, True, False, False, False]
    assert [d["is_today"] for d in w["days"]] == [False, False, False, True, False, False, False]


# ---------- public report (pure parts) ----------

def test_ttl_cache_expiry_and_cap():
    t = [0.0]
    c = pr.TTLCache(ttl=10, max_entries=2, clock=lambda: t[0])
    c.put("a", 1)
    c.put("b", 2)
    c.put("c", 3)
    assert c.get("a") is None and c.get("b") == 2 and len(c) == 2
    t[0] = 11
    assert c.get("b") is None and c.pop("c") is None


def test_ip_limiter_five_per_hour():
    t = [0.0]
    lim = TokenBucketLimiter(rate_per_minute=5 / 60.0, capacity=5, clock=lambda: t[0])
    assert all(lim.hit("ip:1").allowed for _ in range(5))
    d = lim.hit("ip:1")
    assert not d.allowed and 700 <= d.retry_after <= 721
    t[0] = 721
    assert lim.hit("ip:1").allowed
    assert pr.ip_limiter.capacity == 5 and abs(pr.ip_limiter.rate - 5 / 3600) < 1e-12


def test_build_report_with_mock():
    gw = Gateway(MockProvider(), "m", "f", budget_check=pr._global_cap)
    r = pr.build_report(gw, SAMPLE_RESUME, SAMPLE_JD)
    assert set(r) == {"token", "role_title", "company", "skills", "hidden_count", "warnings", "expires_at"}
    assert len(r["skills"]) <= 5 and r["hidden_count"] >= 0
    assert r["role_title"] and len(r["token"]) >= 32
    for s in r["skills"]:
        assert set(s) == {"name", "importance", "gap_type", "priority", "assessed_level", "evidence_quote", "jd_quote", "why", "next_step"}
        assert s["jd_quote"] in SAMPLE_JD
        assert s["evidence_quote"] is None or s["evidence_quote"] in SAMPLE_RESUME
        assert s["why"].endswith(".")
    assert pr.cache.get(r["token"]) is not None
    pr.cache.pop(r["token"])


def test_build_report_rejects_short_text():
    gw = Gateway(MockProvider(), "m", "f")
    with pytest.raises(ValueError, match="200 to 20000"):
        pr.build_report(gw, "too short", SAMPLE_JD)


def test_claim_unknown_token_is_none():
    assert pr.claim(None, "u", None) is None
    assert pr.claim("nope", "u", None) is None
