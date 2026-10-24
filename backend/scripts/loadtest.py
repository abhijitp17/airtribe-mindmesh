"""Small load test for the Mindmesh API: concurrent learners doing the core loop.

    python scripts/loadtest.py --base http://localhost:8300 --users 20 --rounds 5

Each virtual user signs up (local auth), uploads a 2-page PDF, then repeats `rounds` times:
ask the tutor, load Today, make a 3-question quiz and answer one question. Prints latency
percentiles and error counts per endpoint. Run it against the mock AI provider to measure
Mindmesh itself (with a real model, model latency dominates and every request costs money).
Never point it at production: it creates accounts.
"""
from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
import uuid
from collections import defaultdict
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.conftest import SAMPLE_PAGES, make_pdf  # noqa: E402

PDF = make_pdf(SAMPLE_PAGES)
timings: dict[str, list[float]] = defaultdict(list)
errors: dict[str, int] = defaultdict(int)


async def call(client: httpx.AsyncClient, name: str, method: str, url: str, **kw) -> httpx.Response | None:
    start = time.perf_counter()
    try:
        r = await client.request(method, url, **kw)
    except httpx.HTTPError:
        errors[name] += 1
        return None
    timings[name].append((time.perf_counter() - start) * 1000)
    if r.status_code >= 400:
        errors[name] += 1
    return r


async def learner(base: str, rounds: int) -> None:
    async with httpx.AsyncClient(base_url=base, timeout=60) as c:
        r = await call(c, "signup", "POST", "/api/auth/signup",
                       json={"email": f"load-{uuid.uuid4().hex[:10]}@example.com", "password": "correct-horse-1"})
        if r is None or r.status_code != 201:
            return
        c.headers["Authorization"] = f"Bearer {r.json()['token']}"
        c.headers["X-Timezone"] = "Asia/Kolkata"
        r = await call(c, "upload", "POST", "/api/documents?rights_confirmed=true",
                       files={"file": ("load.pdf", PDF, "application/pdf")})
        if r is None or r.status_code != 201:
            return
        doc_id = r.json()["id"]
        for _ in range(100):  # wait for ingestion
            try:
                d = await c.get(f"/api/documents/{doc_id}")
            except httpx.HTTPError:
                errors["upload"] += 1
                return
            if d.status_code == 200 and d.json().get("status") == "ready":
                break
            await asyncio.sleep(0.1)
        for _ in range(rounds):
            await call(c, "tutor_ask", "POST", "/api/tutor/ask",
                       json={"question": "What is Little's Law?", "document_ids": [doc_id]})
            await call(c, "today_preview", "GET", "/api/today/preview")
            q = await call(c, "quiz_create", "POST", "/api/quizzes", json={"document_ids": [doc_id], "count": 3})
            if q is not None and q.status_code == 201 and q.json().get("questions"):
                first = q.json()["questions"][0]
                body = {"selected_index": 0} if first["qtype"] == "mcq" else {"answer_text": "throughput times cycle time"}
                await call(c, "attempt", "POST", f"/api/questions/{first['id']}/attempts", json=body)


def pct(values: list[float], p: float) -> float:
    s = sorted(values)
    return s[min(len(s) - 1, int(round(p / 100 * (len(s) - 1))))]


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", default="http://localhost:8300")
    ap.add_argument("--users", type=int, default=20)
    ap.add_argument("--rounds", type=int, default=5)
    args = ap.parse_args()
    started = time.perf_counter()
    await asyncio.gather(*(learner(args.base, args.rounds) for _ in range(args.users)))
    wall = time.perf_counter() - started
    total = sum(len(v) for v in timings.values())
    print(f"{args.users} users x {args.rounds} rounds: {total} requests in {wall:.1f}s ({total / wall:.0f} req/s)\n")
    print(f"{'endpoint':<15}{'n':>6}{'p50 ms':>9}{'p95 ms':>9}{'max ms':>9}{'errors':>8}")
    for name in ("signup", "upload", "tutor_ask", "today_preview", "quiz_create", "attempt"):
        v = timings.get(name, [])
        if v:
            print(f"{name:<15}{len(v):>6}{statistics.median(v):>9.0f}{pct(v, 95):>9.0f}{max(v):>9.0f}{errors[name]:>8}")
    return 1 if any(errors.values()) else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
