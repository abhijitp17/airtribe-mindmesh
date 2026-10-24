"""AI cost report (app/tools/cost_report.py): priced by model, per active user, no content."""
from app.db import SessionLocal
from app.models import UsageEvent, User
from app.tools.cost_report import build_report, price_for, prices


def test_price_lookup_handles_dated_ids_and_mock():
    t = prices()
    assert price_for("claude-sonnet-4-5-20250929", t) == (3.0, 15.0)
    assert price_for("claude-haiku-5-5", t) == (0.10, 0.50)
    assert price_for("mock-claude-sonnet-4-5", t) == (0.0, 0.0)
    assert price_for("some-other-model", t) is None


def test_report_totals_and_per_user_cost(client, monkeypatch):
    monkeypatch.setenv("MODEL_PRICES_JSON", '{"claude-test": [10, 100]}')
    with SessionLocal() as db:
        users = [User(email=f"cost{i}@example.com", password_hash=None) for i in range(2)]
        db.add_all(users)
        db.flush()
        for u in users:
            db.add(UsageEvent(owner_id=u.id, task="tutor", model="claude-test-1", input_tokens=100_000,
                              output_tokens=10_000, latency_ms=900, prompt_version="v"))
        db.add(UsageEvent(owner_id=users[0].id, task="quiz", model="unknown-x", input_tokens=5, output_tokens=5,
                          latency_ms=1, prompt_version="v"))
        db.commit()
    r = build_report(days=1)
    tutor = next(x for x in r["by_task"] if x["task"] == "tutor")
    assert tutor["calls"] == 2 and tutor["cost_usd"] == 2 * (100_000 * 10 + 10_000 * 100) / 1e6  # $4.00
    assert r["active_users"] == 2 and r["per_active_user_per_day_usd"] == 2.0
    assert r["unpriced_models"] == ["unknown-x"]
