# Service levels (SLOs), metrics and alerts

Targets for the beta, measured from `GET /api/metrics` (Prometheus text format; off unless
`METRICS_TOKEN` is set, then `Authorization: Bearer <token>`). Alert rules:
`deploy/prometheus/alerts.yml`. Metrics carry no user data: requests are labelled by path with ids
replaced (`/api/documents/{id}`), and 404s are all `unmatched`.

| SLO | Target (30 days) | Measured by |
|---|---|---|
| Availability | 99.5% of requests not 5xx (error budget 0.5%, about 3.6 hours) | `mindmesh_http_requests_total` |
| Latency, non-AI requests | 95% under 300 ms | `mindmesh_http_request_duration_seconds` |
| Tutor answers | 95% within 8 s | same, `route="/api/tutor/ask"` |
| Model calls | under 5% fail after retries | `mindmesh_ai_calls_total` |
| Document processing | 95% of documents up to 100 pages ready within 2 minutes; first pages usable within 15 s | `pages_done`, `processing_started_at` (log-based until a histogram is added) |
| Background jobs | no job kind fails permanently more than 3 times an hour | `mindmesh_jobs_total` |

## Knowledge-graph query budgets

The per-request graph work (P2) is budgeted and tested (`tests/test_graph_budgets.py`, one user's
graph of 2,000 concepts and ~6,000 edges on SQLite). Measured on a laptop:

| Query | Budget | Measured |
|---|---|---|
| Prerequisite chain (recursive, depth 5) | 150 ms | ~4 ms |
| Concept aliases (merged names) | 400 ms | ~6 ms |
| Retrieval hints for the tutor | 600 ms | ~30 ms |
| Plan ordering from grounded edges (40 topics) | 150 ms | ~1 ms |

## Error budget policy

* Fast burn (2% of the monthly budget in an hour) pages; slow burn (on track to spend it in about
  5 days) opens a ticket.
* While more than half the budget is spent, ship only fixes and reliability work.
* Model-provider outages count against the budget: the product is the answer, not our uptime.

## When an alert fires

1. `/api/health/ready`: database and Redis reachable?
2. Logs by `request_id` (JSON lines; no user content). `mindmesh.access` gives route, status, timing.
3. `MindmeshModelErrors`: check the provider status page and the API key; answers fall back to
   "temporarily unavailable" (503) rather than guessing.
4. `MindmeshJobsFailing`: `jobs.last_error` for that kind; a failed ingestion never deletes the
   uploaded file, and "Retry" reprocesses it.
5. Pool exhaustion shows as 503 with `Retry-After` (DECISIONS #33): scale API processes or the pool.
