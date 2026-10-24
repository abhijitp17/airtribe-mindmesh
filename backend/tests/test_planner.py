"""Pure tests for the deterministic planner (CONTRACTS §4, FR-021/023)."""
import random
from collections import defaultdict
from datetime import date, timedelta

import pytest

from app.ai.gateway import Gateway
from app.ai.mock import MockProvider
from app.core.citations import SourceRef
from app.core.planner import (
    PlanEntry,
    TopicSpec,
    adapt,
    compute_stats,
    mock_interview_count,
    plan_warning,
    schedule,
    study_dates,
    topics_from_skills,
    topological_order,
)
from app.services.goals import (
    build_plan, clean_topics, dropped_reason, goal_warning, is_dropped, propose_topics, spread_sources,
    topics_from_headings, topics_from_items,
)
from app.services.learning import ChunkData

MON = date(2026, 10, 12)  # a Monday
WEEKDAYS = [0, 1, 2, 3, 4]


def _topics(n, minutes=40, chain=True):
    return [
        TopicSpec(f"T{i}", f"C{i}", minutes, priority=1 + (i % 4),
                  prerequisites=[f"T{i - 1}"] if chain and i else [], source_chunk_ids=[f"c{i}"])
        for i in range(n)
    ]


def _daily(items):
    load = defaultdict(int)
    for it in items:
        if it.status != "skipped":
            load[it.scheduled_date] += it.estimated_minutes
    return load


def _check_invariants(items, start, deadline, budget, study_days, fixed_ids=()):
    for d, m in _daily(items).items():
        assert m <= budget, (d, m, budget)
    for it in items:
        if it.id in fixed_ids:
            continue
        assert start <= it.scheduled_date <= deadline, it
        assert it.scheduled_date.weekday() in study_days, it
        assert it.estimated_minutes > 0
        assert it.activity_type in ("learn", "practice", "review", "mock_interview", "drill")
    assert [i.position for i in items] == list(range(len(items)))


# ---------- basics ----------

def test_study_dates_respects_weekdays_and_range():
    ds = study_dates(MON, MON + timedelta(days=13), WEEKDAYS)
    assert len(ds) == 10 and all(d.weekday() < 5 for d in ds)
    assert study_dates(MON, MON - timedelta(days=1), WEEKDAYS) == []
    assert study_dates(MON, MON + timedelta(days=5), []) == []


def test_simple_plan_fits_and_orders_learn_practice_review():
    items, warn = schedule(MON, MON + timedelta(days=27), 60, WEEKDAYS, _topics(3, 40))
    assert warn is None
    _check_invariants(items, MON, MON + timedelta(days=27), 60, WEEKDAYS)
    for t in ("T0", "T1", "T2"):
        mine = [i for i in items if i.topic == t]
        learn = max(i.scheduled_date for i in mine if i.activity_type == "learn")
        practice = [i for i in mine if i.activity_type == "practice"]
        assert len(practice) == 1 and practice[0].scheduled_date >= learn
        assert all(i.reason for i in mine)
        assert mine[0].source_chunk_ids


def test_prerequisites_ordered_even_if_proposed_backwards():
    ts = [TopicSpec("B", prerequisites=["A"], est_minutes=30), TopicSpec("A", est_minutes=30)]
    assert [t.topic for t in topological_order(ts)] == ["A", "B"]
    items, _ = schedule(MON, MON + timedelta(days=20), 45, WEEKDAYS, ts)
    a_end = max(i.scheduled_date for i in items if i.topic == "A" and i.activity_type == "learn")
    b_start = min(i.scheduled_date for i in items if i.topic == "B" and i.activity_type == "learn")
    assert b_start >= a_end


def test_cycle_does_not_hang():
    ts = [TopicSpec("A", prerequisites=["B"]), TopicSpec("B", prerequisites=["A"])]
    assert {t.topic for t in topological_order(ts)} == {"A", "B"}


def test_large_topic_is_split_within_budget():
    items, warn = schedule(MON, MON + timedelta(days=20), 30, WEEKDAYS, [TopicSpec("Big", est_minutes=100)])
    assert warn is None
    learn = [i for i in items if i.activity_type == "learn"]
    assert len(learn) >= 4 and sum(i.estimated_minutes for i in learn) == 100
    assert all(i.estimated_minutes <= 30 for i in learn)
    assert "part 1 of" in learn[0].objective
    assert all(i.estimated_minutes >= 10 for i in learn)


def test_reviews_are_spaced_after_practice():
    items, _ = schedule(MON, MON + timedelta(days=30), 60, list(range(7)), [TopicSpec("A", est_minutes=30)])
    practice = next(i for i in items if i.activity_type == "practice")
    reviews = sorted(i.scheduled_date for i in items if i.activity_type == "review")
    assert [(d - practice.scheduled_date).days for d in reviews] == [1, 3, 7]


def test_reviews_skipped_when_no_capacity_but_no_warning():
    # Budget exactly fills learn+practice; reviews can't fit but nothing core is dropped.
    items, warn = schedule(MON, MON, 40, list(range(7)), [TopicSpec("A", est_minutes=30)])
    assert warn is None
    assert not [i for i in items if i.activity_type == "review"]


def test_infeasible_drops_lowest_priority_with_warning():
    ts = [
        TopicSpec("Core", est_minutes=60, priority=4),
        TopicSpec("Nice", est_minutes=60, priority=1),
        TopicSpec("Useful", est_minutes=60, priority=3),
    ]
    items, warn = schedule(MON, MON + timedelta(days=2), 60, WEEKDAYS, ts)
    assert warn and "Nice" in warn and "Core" not in warn
    assert "Nice" not in {i.topic for i in items}
    assert "Core" in {i.topic for i in items}
    _check_invariants(items, MON, MON + timedelta(days=2), 60, WEEKDAYS)


def test_never_compresses_silently():
    ts = [TopicSpec("A", est_minutes=120, priority=4), TopicSpec("B", est_minutes=120, priority=2)]
    items, warn = schedule(MON, MON + timedelta(days=1), 60, WEEKDAYS, ts)
    learned = {t: sum(i.estimated_minutes for i in items if i.topic == t and i.activity_type == "learn") for t in "AB"}
    for t, m in learned.items():
        assert m in (0, 120)  # whole topic or dropped, never shortened
    assert warn is not None


def test_no_study_days_warns():
    items, warn = schedule(MON, MON + timedelta(days=4), 60, [5, 6], [TopicSpec("A")])
    assert items == [] and warn and "no study days" in warn


def test_fixed_items_stay_and_count_against_budget():
    fixed = [PlanEntry(MON, "My own session", "learn", 50, id="fx1")]
    items, _ = schedule(MON, MON + timedelta(days=14), 60, WEEKDAYS, _topics(3, 30), fixed)
    f = next(i for i in items if i.id == "fx1")
    assert f.scheduled_date == MON and f.estimated_minutes == 50 and f.fixed
    assert _daily(items)[MON] <= 60
    _check_invariants(items, MON, MON + timedelta(days=14), 60, WEEKDAYS, fixed_ids={"fx1"})


def test_fixed_item_for_topic_replaces_generated_learn():
    fixed = [PlanEntry(MON + timedelta(days=2), "T0", "learn", 40, id="fx")]
    items, _ = schedule(MON, MON + timedelta(days=14), 60, WEEKDAYS, _topics(2, 40), fixed)
    t0_learn = [i for i in items if i.topic == "T0" and i.activity_type == "learn"]
    assert [i.id for i in t0_learn] == ["fx"]
    t0_practice = next(i for i in items if i.topic == "T0" and i.activity_type == "practice")
    assert t0_practice.scheduled_date >= MON + timedelta(days=2)


def test_interview_mocks_in_final_days():
    deadline = MON + timedelta(days=18)  # 15 weekdays
    n = mock_interview_count(MON, deadline, WEEKDAYS)
    assert n == 2
    items, warn = schedule(MON, deadline, 90, WEEKDAYS, _topics(3, 30), mock_interviews=n)
    mocks = [i for i in items if i.activity_type == "mock_interview"]
    assert len(mocks) == 2
    last_days = study_dates(MON, deadline, WEEKDAYS)[-3:]
    assert all(m.scheduled_date in last_days for m in mocks)
    _check_invariants(items, MON, deadline, 90, WEEKDAYS)


def test_topics_from_skills_orders_critical_first_and_skips_strong():
    skills = [
        {"name": "SQL", "priority": "medium", "gap_type": "knowledge_gap", "linked_chunk_ids": ["a"]},
        {"name": "Stakeholders", "priority": "critical", "gap_type": "evidence_gap"},
        {"name": "Python", "priority": "high", "gap_type": "strong"},
        {"name": "Stats", "priority": "low", "gap_type": "application_gap", "user_override": {"priority": "high"}},
    ]
    ts = topics_from_skills(skills)
    assert [t.topic for t in ts] == ["Stakeholders", "Stats", "SQL"]
    assert ts[0].activity == "drill" and ts[2].source_chunk_ids == ["a"]


# ---------- property-style ----------

@pytest.mark.parametrize("seed", list(range(60)))
def test_random_configs_respect_all_invariants(seed):
    rng = random.Random(seed)
    start = MON + timedelta(days=rng.randint(0, 6))
    deadline = start + timedelta(days=rng.randint(0, 40))
    budget = rng.choice([10, 15, 20, 30, 45, 60, 90, 120, 240])
    study = sorted(rng.sample(range(7), rng.randint(1, 7)))
    n = rng.randint(0, 12)
    ts = []
    for i in range(n):
        pre = [f"T{j}" for j in range(i) if rng.random() < 0.3]
        ts.append(TopicSpec(f"T{i}", f"C{i}", rng.randint(10, 180), rng.randint(1, 4), pre,
                            activity=rng.choice(["learn", "learn", "practice", "drill"])))
    fixed = []
    for k in range(rng.randint(0, 3)):
        days = study_dates(start, deadline, study)
        if days:
            fixed.append(PlanEntry(rng.choice(days), f"Fixed{k}", "learn", rng.randint(5, budget), id=f"f{k}"))
    # fixed items alone must not already exceed a day's budget for this property test
    load = _daily(fixed)
    if any(m > budget for m in load.values()):
        fixed = fixed[:1]
    mocks = rng.randint(0, 3)
    items, warn = schedule(start, deadline, budget, study, ts, fixed, mocks)
    _check_invariants(items, start, deadline, budget, study, fixed_ids={f.id for f in fixed})
    scheduled = {i.topic for i in items}
    dropped = [t.topic for t in ts if t.topic not in scheduled]
    if dropped:
        assert warn and all(d in warn for d in dropped)
    # prerequisites: a kept topic never starts before its kept prerequisites finish
    first = {}
    last = {}
    for i in items:
        if i.activity_type in ("learn", "practice", "drill") and i.id is None:
            first.setdefault(i.topic, i.scheduled_date)
            first[i.topic] = min(first[i.topic], i.scheduled_date)
            last[i.topic] = max(last.get(i.topic, i.scheduled_date), i.scheduled_date)
    for t in ts:
        if t.topic in first:
            for p in t.prerequisites:
                if p in first:
                    core_first = min(i.scheduled_date for i in items if i.topic == t.topic and i.activity_type == t.activity)
                    core_last_p = max(i.scheduled_date for i in items if i.topic == p and i.activity_type == next(x.activity for x in ts if x.topic == p))
                    assert core_first >= core_last_p, (t.topic, p)
    # no topic is shortened
    for t in ts:
        got = sum(i.estimated_minutes for i in items if i.topic == t.topic and i.activity_type == t.activity)
        assert got in (0, t.est_minutes), (t.topic, got, t.est_minutes)


@pytest.mark.parametrize("seed", list(range(25)))
def test_dropping_prefers_low_priority(seed):
    rng = random.Random(1000 + seed)
    ts = [TopicSpec(f"T{i}", est_minutes=rng.randint(20, 60), priority=rng.randint(1, 4)) for i in range(8)]
    items, warn = schedule(MON, MON + timedelta(days=3), 60, WEEKDAYS, ts)
    kept = {i.topic for i in items}
    dropped = [t for t in ts if t.topic not in kept]
    if dropped:
        assert warn
        # at least one dropped topic is of minimal priority among all
        assert min(t.priority for t in dropped) == min(t.priority for t in ts)


# ---------- adapt ----------

def _row(id, d, topic, act="learn", m=30, status="pending", concept=None, pos=0):
    return {"id": id, "scheduled_date": d, "topic": topic, "activity_type": act, "estimated_minutes": m,
            "status": status, "concept": concept, "position": pos}


def test_adapt_moves_missed_items_within_budget():
    today = MON + timedelta(days=2)
    items = [
        _row("a", MON, "A", m=40),
        _row("b", today, "B", m=40),
        _row("c", MON, "Done", status="done"),
    ]
    res = adapt(items, today, MON + timedelta(days=10), 60, WEEKDAYS)
    assert res is not None and "missed 1" in res.reason
    (ch,) = res.changes
    assert ch["op"] == "move" and ch["item_id"] == "a" and ch["why"]
    assert date.fromisoformat(ch["to_date"]) > today  # today already holds 40 of 60
    assert ch["to_date"] != today.isoformat()


def test_adapt_removes_when_no_capacity():
    today = MON
    items = [_row("a", MON - timedelta(days=3), "A", m=60), _row("b", MON, "B", m=60)]
    res = adapt(items, today, MON, 60, WEEKDAYS)
    assert res.changes[0]["op"] == "remove" and "no study day" in res.changes[0]["why"]


def test_adapt_adds_review_for_weak_concepts():
    today = MON
    items = [_row("a", MON - timedelta(days=5), "A", status="done", concept="Little's Law"),
             _row("b", MON + timedelta(days=6), "B", concept="Variability")]
    res = adapt(items, today, MON + timedelta(days=14), 60, WEEKDAYS, {"little's law": "weak", "Variability": "strong"})
    assert res is not None
    adds = [c for c in res.changes if c["op"] == "add"]
    assert len(adds) == 1 and adds[0]["topic"] == "Little's Law" and adds[0]["activity_type"] == "review"
    assert "needs more work" in adds[0]["why"]


def test_adapt_ahead_of_schedule_returns_none():
    items = [_row("a", MON, "A", status="done"), _row("b", MON + timedelta(days=3), "B")]
    assert adapt(items, MON + timedelta(days=1), MON + timedelta(days=10), 60, WEEKDAYS, {"A": "strong"}) is None


def test_adapt_never_exceeds_budget():
    today = MON + timedelta(days=7)
    items = [_row(str(i), MON + timedelta(days=i % 5), f"T{i}", m=25) for i in range(10)]
    res = adapt(items, today, today + timedelta(days=2), 50, WEEKDAYS)  # 150 free minutes for 250 missed
    load = defaultdict(int)
    for c in res.changes:
        if c["op"] == "move":
            load[c["to_date"]] += c["minutes"]
    assert all(v <= 50 for v in load.values())
    assert any(c["op"] == "remove" for c in res.changes)


# ---------- stats ----------

def test_compute_stats_and_warning():
    today = MON + timedelta(days=1)
    items = [_row("a", MON, "A", status="done", m=30), _row("b", today, "B", m=30),
             _row("c", today, "C", m=40), _row("d", MON, "D", status="skipped", m=99)]
    s = compute_stats(items, today, MON + timedelta(days=4), 60, WEEKDAYS)
    assert s == {"total_minutes": 100, "done_minutes": 30, "items_done": 1, "items_total": 3,
                 "on_track": True, "days_left": 3, "capacity_minutes": 240}
    assert "budget" in plan_warning(items, today, MON + timedelta(days=4), 60)
    items.append(_row("e", MON, "E"))
    assert compute_stats(items, today, MON + timedelta(days=4), 60, WEEKDAYS)["on_track"] is False


# ---------- topic proposal (mock gateway) ----------

def _chunks():
    return [
        ChunkData("k1", "Little's Law relates WIP, throughput and cycle time. " * 5, 1, 1, "Chapter 1 > 1.1 Little's Law", "d1"),
        ChunkData("k2", "More about Little's Law and examples of using it on a line. " * 4, 1, 1, "Chapter 1 > 1.1 Little's Law", "d1"),
        ChunkData("k3", "Variability degrades performance of production systems. " * 5, 2, 2, "Chapter 1 > 1.2 Variability", "d1"),
    ]


def test_propose_topics_with_mock_is_deterministic_and_validated():
    gw = Gateway(MockProvider(), "main", "fast")
    a = propose_topics(gw, _chunks(), "learn", "Factory physics", "", "standard", MON + timedelta(days=20), 60)
    b = propose_topics(gw, _chunks(), "learn", "Factory physics", "", "standard", MON + timedelta(days=20), 60)
    assert [t.topic for t in a] == [t.topic for t in b] == ["Little's Law", "Variability"]
    assert a[1].prerequisites == ["Little's Law"]
    assert all(10 <= t.est_minutes <= 180 and t.source_chunk_ids for t in a)
    assert set(a[0].source_chunk_ids) <= {"k1", "k2"}


def test_clean_topics_rejects_bad_labels_clamps_and_dedupes():
    sources = [SourceRef("S1", "k1", "x", 1, 1, "A"), SourceRef("S2", "k2", "y", 2, 2, "B")]
    raw = {"topics": [
        {"topic": "A", "est_minutes": 999, "sources": ["S1"], "prerequisites": ["B"], "priority": "critical"},
        {"topic": "a", "sources": ["S1"]},
        {"topic": "Invented", "sources": ["S9"]},
        {"topic": "B", "est_minutes": "2", "sources": ["[S2]"], "prerequisites": ["A", "Nope"]},
        "junk",
    ]}
    ts = clean_topics(raw, sources)
    assert [t.topic for t in ts] == ["A", "B"]
    assert ts[0].est_minutes == 180 and ts[0].prerequisites == [] and ts[0].priority == 4
    assert ts[1].est_minutes == 10 and ts[1].prerequisites == ["A"] and ts[1].source_chunk_ids == ["k2"]


def test_spread_sources_and_heading_fallback():
    srcs = spread_sources(_chunks())
    assert [s.label for s in srcs][:2] == ["S1", "S2"]
    ts = topics_from_headings(srcs)
    assert ts[0].topic == "Little's Law" and ts[-1].topic == "Variability"


def test_build_plan_revise_and_interview():
    ts = [TopicSpec("A", est_minutes=50), TopicSpec("B", est_minutes=50)]
    items, _, _ = build_plan(today=MON, goal_type="revise", deadline=MON + timedelta(days=20), minutes_per_day=60,
                          study_days=WEEKDAYS, level="standard", topics=ts)
    assert not [i for i in items if i.activity_type == "learn"]
    items, _, _ = build_plan(today=MON, goal_type="interview", deadline=MON + timedelta(days=20), minutes_per_day=60,
                          study_days=WEEKDAYS, level="beginner", topics=ts, interview=True)
    assert any(i.activity_type == "mock_interview" for i in items)


def test_build_plan_reports_dropped_topics():
    ts = [TopicSpec("Big", est_minutes=180, priority=1), TopicSpec("Core", est_minutes=30, priority=4)]
    items, warn, dropped = build_plan(today=MON, goal_type="learn", deadline=MON, minutes_per_day=60,
                                      study_days=WEEKDAYS, level="standard", topics=ts)
    assert [t.topic for t in dropped] == ["Big"] and "Big" in warn


# ---------- replans from stored rows ----------

def _entry_rows(entries):
    return [{"id": f"r{i}", **{k: getattr(e, k) for k in (
        "scheduled_date", "topic", "activity_type", "estimated_minutes", "concept", "objective",
        "source_chunk_ids", "reason", "status", "position", "user_edited")}} for i, e in enumerate(entries)]


def test_topics_from_items_round_trip():
    items, _ = schedule(MON, MON + timedelta(days=20), 30, WEEKDAYS,
                        [TopicSpec("A", est_minutes=70, source_chunk_ids=["x"], objective="Do A"), TopicSpec("B", est_minutes=20)])
    ts = topics_from_items(_entry_rows(items))
    assert [(t.topic, t.est_minutes, t.activity) for t in ts] == [("A", 70, "learn"), ("B", 20, "learn")]
    assert ts[0].objective == "Do A" and ts[0].source_chunk_ids == ["x"] and ts[1].prerequisites == ["A"]


def test_done_part_counts_only_its_minutes_on_replan():
    entries, _ = schedule(MON, MON + timedelta(days=20), 30, WEEKDAYS, [TopicSpec("A", est_minutes=90)])
    parts = [e for e in entries if e.activity_type == "learn"]
    assert len(parts) == 3
    done = PlanEntry(**{**parts[0].__dict__, "status": "done", "id": "p1"})
    today = MON + timedelta(days=7)
    items, warn = schedule(today, MON + timedelta(days=20), 30, WEEKDAYS, [TopicSpec("A", est_minutes=90)], [done])
    gen = [i for i in items if i.activity_type == "learn" and i.id is None]
    assert sum(i.estimated_minutes for i in gen) == 90 - done.estimated_minutes
    assert warn is None


def test_user_edited_item_covers_whole_topic():
    edited = PlanEntry(MON + timedelta(days=1), "A", "learn", 20, id="e1", user_edited=True)
    items, _ = schedule(MON, MON + timedelta(days=20), 30, WEEKDAYS, [TopicSpec("A", est_minutes=90)], [edited])
    assert [i.id for i in items if i.activity_type == "learn"] == ["e1"]


def test_goal_warning_from_dropped_rows():
    rows = [{"status": "skipped", "reason": dropped_reason(60, MON), "topic": "X", "scheduled_date": MON,
             "estimated_minutes": 60, "position": 0}]
    assert is_dropped(rows[0])
    w = goal_warning(rows, MON, MON + timedelta(days=5), 60, WEEKDAYS)
    assert w and "Left out" in w and "X" in w
    assert goal_warning([], MON, MON + timedelta(days=5), 60, WEEKDAYS) is None
