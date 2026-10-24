# Mindmesh: notes for Claude

Start with `docs/CONTEXT_LOG.md` (project state, every task so far, open work), then `docs/DECISIONS.md`.

- Backend: `cd backend && .venv/bin/python -m pytest -q` (tests use a throwaway DB; never point them at
  `backend/mindmesh.db`). Postgres/Redis suites need `MINDMESH_PG_URL` / `MINDMESH_REDIS_URL`.
- Web: `cd web && npm run typecheck && npm run build && npx playwright test`. Mobile: `cd mobile && npm run typecheck && npm test`.
- Ports: web 3300, API 8300 (3000/8000 belong to the separate Planora project; never use them).
- Evals: `APP_ENV=test AI_PROVIDER=mock .venv/bin/python -m evals.run --baseline evals/baseline.json`, plus
  `evals.graph_eval --gate` and `evals.notes_eval --gate`.
- Schema changes: Alembic migration + `alembic check` clean; owner tables get RLS via `python -m app.tools.migrate`.
- Rules: user's day via `app.clock.user_today()`; no user content in logs/emails/errors; no sampling params
  to Anthropic; pin deps ≥ 2 weeks old; secrets only in ignored `.env`/`.env.local`.
- Git: `origin` is `git@github.com:abhijitp17/mindmesh.git` (private). Work on a branch, open a PR into `main`.

## Backend dependencies (DECISIONS #68)
Docker and CI install `backend/requirements.lock` / `requirements-dev.lock` (exact versions, hashes). After changing
`requirements*.txt`, run `backend/scripts/lock.sh` (needs `uv`), run the tests, and commit the lock files too.
