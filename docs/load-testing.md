# Load testing

`backend/scripts/loadtest.py` runs concurrent learners through the core loop: sign up, upload a
2-page PDF, then per round ask the tutor, load Today, make a 3-question quiz and answer a
question. Never point it at production: it creates accounts.

```bash
# API against Postgres + Redis, mock AI with simulated model latency, 2 worker processes
DATABASE_URL=postgresql+psycopg://... REDIS_URL=redis://localhost:6379/13 AI_PROVIDER=mock \
MOCK_LATENCY_MS=1500 uvicorn app.main:app --port 8300 --workers 2
python scripts/loadtest.py --base http://localhost:8300 --users 100 --rounds 2
```

## Results (2026-10-17, MacBook Air, Postgres 16 + Redis 8 local, 2 uvicorn workers)

**Finding.** Each request held its DB connection for its whole life, including the AI model
call. With 100 learners and 1.5 s simulated model latency the default pool (5 + 10 per process)
ran out: 30 requests hit `QueuePool limit ... timed out` after 30 s and connections dropped. With
a real model (5-20 s per call) about 15 concurrent tutor questions per process would have
exhausted the pool.

**Fix.** Before every model call the gateway gives a read-only transaction's connection back
to the pool (`release_if_idle`; a transaction that has written keeps it, so routes stay atomic).
The pool is configurable (`DB_POOL_SIZE` 10, `DB_MAX_OVERFLOW` 20, `DB_POOL_TIMEOUT` 10 s), and
an exhausted pool returns 503 with `Retry-After` instead of a 500 after 30 s.

| 100 learners x 2 rounds, 1.5 s AI latency | Before | After |
|---|---|---|
| Pool timeouts | 30 (+ dropped connections) | 0 |
| Errors | many | 0 of 1,000 requests |
| Tutor answer p50 / p95 | - | 1.7 s / 3.3 s (up to two model calls) |
| Quiz p50 / p95 | - | 1.7 s / 3.0 s |
| Today p50 / p95 | - | 0.18 s / 0.61 s |

Without model latency (mock answers instantly), 20 learners: 440 requests, 0 errors, every
p95 under 135 ms (sign-up is the slowest: scrypt password hashing is deliberately slow).

**Capacity notes.** Throughput with a real model is bound by the model and the token budget,
not the API. Scale API processes horizontally (shared state is in Redis and Postgres), keep
the DB pool x processes under Postgres `max_connections`, and re-run this test with
`MOCK_LATENCY_MS` set to the p95 measured by the real-model eval.
