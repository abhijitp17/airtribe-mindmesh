# Mindmesh: MVP (slices 1–3)

First end-to-end slice of the AI Learning & Career Intelligence OS (see the PRD):

**upload a PDF → extract text with page anchors → ask a tutor that cites pages (citations verified in code) → generate a quiz → get graded with a rubric → see a mastery map and a next action.**

Slice 2 adds: **interview prep** (resume + job description → role-skill matrix with gap types and explainable priorities → mock interview with rubric/STAR feedback), **goals & study plans** (deadline- and budget-safe schedules, adapt proposals, "Today" view), **hybrid retrieval + optional OCR**, an **eval harness** (`python -m evals.run`), and **hardening** (rate limits, security headers, job worker, Alembic, Postgres RLS, data export, settings page).

Slice 3 delivers the final **Aura** design (frosted glass, one orange action per screen) and the structure from the UX research: **Today** (timed 5/15/30-minute sessions, weekly target, wins, post-interview debrief), **Prep** (role preps + study goals), **Library** (documents, tutor, one-question-at-a-time quizzes) and a signed-out **gap report** at `/welcome`. The tutor now declines off-topic questions reliably (eval not_found recall 1.0).

Review the UI without running anything: open `docs/ui-preview.html` in a browser.

The build contracts are in `docs/CONTRACTS.md`. Decisions and known issues are in `docs/DECISIONS.md`.

## Run it

### Option A — Docker (Postgres, API, web)

```bash
cp .env.example .env          # add ANTHROPIC_API_KEY, or leave empty for offline mock mode
docker compose up --build
```

Open http://localhost:3300. API docs: http://localhost:8300/docs.

Once the API has started (it creates the tables), turn on row-level security:

```bash
docker compose exec -T db psql -U mindmesh_app -d mindmesh -v ON_ERROR_STOP=1 < backend/sql/rls.sql
```

The api and worker connect as `mindmesh_app`, a non-superuser created by `backend/sql/init/01-app-role.sql` on the db's first start. Superusers bypass RLS. If your `pgdata` volume predates that script, run it once as `mindmesh` and recreate the tables, or start from a fresh volume.

### Option B — local dev (SQLite, no Docker)

```bash
# API
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
export ANTHROPIC_API_KEY=sk-ant-...   # optional; omit for mock mode
uvicorn app.main:app --reload --port 8300

# Web (new terminal)
cd web
npm install
npm run dev
```

### Tests and evals

```bash
cd backend && pytest -q                                   # unit + service + API tests
python -m evals.run --baseline evals/baseline.json        # quality regression check (mock provider)
python -m evals.run --provider anthropic                  # same eval with real Claude
cd ../web && npm run typecheck && npm run build
```

To run the API against a local Postgres instead of SQLite (Homebrew `postgresql@16`), create a non-superuser role that owns the database, then:

```bash
cd backend
export DATABASE_URL=postgresql+psycopg://mindmesh:mindmesh@localhost:5432/mindmesh
alembic upgrade head
PGPASSWORD=mindmesh psql -h localhost -U mindmesh -d mindmesh -f sql/rls.sql
MINDMESH_PG_URL=$DATABASE_URL pytest -q tests/test_postgres_rls.py   # migrations + RLS isolation checks
```

Database migrations: `cd backend && alembic upgrade head` (see `backend/alembic/README` if your DB was created by the old create-on-boot path). Background jobs run in the `worker` service under Docker (`JOB_BACKEND=db`).

`tests/test_core.py` covers the deterministic parts (PDF extraction, chunking, BM25, citation verification, question validation, grading, mastery). `tests/test_services.py` runs the learning loop on a generated PDF, including a model that fabricates citations. `tests/test_api.py` runs the full HTTP flow and checks that one user can't reach another user's data.

## Mock mode vs Claude

With no `ANTHROPIC_API_KEY`, the backend uses a deterministic **mock provider**. It builds answers and questions from your actual retrieved text, so you can test the whole product offline. However, explanations are just extracted sentences. Set the key to use Claude (`claude-sonnet-4-5` for tutoring and grading, `claude-haiku-4-5` for question generation; you can change both in `.env`).

## Layout

```
backend/app/
  core/        pure logic, no I/O: pdf_extract, chunking, retrieval (BM25), citations, assessment, mastery
  ai/          gateway (routing, retries, JSON repair, budgets), prompts (versioned), mock provider
  services/    learning loop use cases + ingestion job
  routers/     auth, documents, learning (tutor, quizzes, attempts, progress)
  models.py    SQLAlchemy schema (owner_id on every user table)
web/src/
  app/         login, home (next action, library, mastery), documents/[id] (reader + tutor), quiz/[id]
  components/  SourceViewer, Tutor, Shell, ui
```
