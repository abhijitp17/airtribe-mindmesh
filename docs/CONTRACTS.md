# Slice 2 build contracts

This file is the single source of truth for the parallel build. Backend schemas and frontend types must match it exactly. If you need to change a contract, stop and report back; don't change it on your own.

## 0. Ground rules (all workstreams)

**File ownership.** Edit only files you own (§1). Files marked *shared, read-only* may be imported, not edited. The only exception is a file listed under your workstream as "append-only".

**Conventions that already exist (read before writing code):**

- `owner_id` on every user-owned row; every query filters by it; other users' resources → **404**.
- Pure logic goes in `backend/app/core/*.py` or `backend/app/services/*.py`, with no FastAPI or SQLAlchemy imports in `core/`. This matters for testing (see below).
- AI calls only through `app.ai.gateway.Gateway` (`complete_json(Request(...), validate=...)`). Every `Request` sets `task="<name>"` and puts the structured inputs the mock needs into `context`.
- Offline mock for a new task: create `backend/app/ai/mock_<feature>.py` and use `@register_mock("<task>")` from `app.ai.mock`. It's auto-loaded. Mocks must be deterministic and build output from `context` (no randomness).
- Prompts: use `app.ai.prompts.INJECTION_GUARD` and `_escape()`. Wrap untrusted text in tags (`<resume>`, `<job_description>`, `<candidate_answer>`, `<source>`).
- Models must never invent resume facts, metrics, quotes or page numbers. Validate model JSON in code and recompute any scores in code.
- Routers: `APIRouter`, dependencies `current_user`, `get_db`, `gateway_for` from `app.deps`. Map `BudgetExceeded` → 429 and `ModelError` → 503 (copy `_ai_call` from `routers/learning.py`).
- Tables: new tables live in the `models_*.py` files listed below. They're auto-registered by `db.load_all_models()`.
- Frontend: Next.js 15 app router, `"use client"` pages wrapped in `<Shell>`, styling **only** via existing classes in `web/src/app/globals.css` plus inline styles. Never use colour alone; always add a text label. Feature API clients import `{ request, json }` from `@/lib/api`.

**Testing constraint (important).** The build sandbox has **no FastAPI, SQLAlchemy or npm**. It does have Python 3.10, numpy, pypdf, pypdfium2, python-docx, reportlab and PyJWT. Tests run with a tiny pytest shim:

```bash
cd backend && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/sessions/jolly-amazing-mendel/mnt/outputs/minitest \
  python3 /sessions/jolly-amazing-mendel/mnt/outputs/minitest/run.py tests.test_<yours>
```

The shim supports plain `assert`, `pytest.raises(match=)`, `@pytest.fixture` (including generator fixtures), `@pytest.mark.parametrize` and the `sample_pdf` fixture from `tests/conftest.py`. It doesn't support `tmp_path`, `monkeypatch` or `capsys`; use `tempfile`. So put all non-trivial logic in pure modules and unit-test them here. Router and DB code must still be written carefully and checked with `python3 -m py_compile`. API tests that need FastAPI go in `tests/test_api_<feature>.py`, which CI runs and which doesn't have to run here. Use the pattern in `tests/test_api.py`.

**Shared, read-only:** `app/db.py`, `app/models.py`, `app/models_interview.py`, `app/models_goals.py`, `app/deps.py`, `app/ai/gateway.py`, `app/ai/mock.py`, `app/ai/prompts.py`, `app/schemas.py`, `app/config.py`, `app/main.py`, `web/src/lib/api.ts`, `web/src/components/Shell.tsx`, `web/src/components/ui.tsx`, `web/src/app/globals.css`, `docs/CONTRACTS.md`.

## 1. Workstreams and file ownership

| WS | Scope | Owns (create/edit) |
|---|---|---|
| **A** Eval harness | Gold-set format, scorer, CLI, sample set, CI | `backend/evals/**`, `backend/tests/test_evals.py`, `.github/workflows/ci.yml` |
| **B** Interview backend | Resume/JD parsing, skill matrix, gap + priority engine, mock interview engine, API §3 | `backend/app/core/interview_*.py`, `backend/app/services/interview*.py`, `backend/app/ai/prompts_interview.py`, `backend/app/ai/mock_interview.py`, `backend/app/routers/interview.py`, `backend/app/schemas_interview.py`, `backend/tests/test_interview*.py`, `backend/tests/test_api_interview.py` |
| **C** Interview frontend | All interview UI against §3 | `web/src/lib/api-interview.ts`, `web/src/app/interview/**`, `web/src/components/interview/**` |
| **D** Goals & plans | Planner (model proposes topics, code schedules), adaptation, API §4 **and** its UI | `backend/app/core/planner.py`, `backend/app/services/goals.py`, `backend/app/ai/prompts_goals.py`, `backend/app/ai/mock_goals.py`, `backend/app/routers/goals.py`, `backend/app/schemas_goals.py`, `backend/tests/test_planner.py`, `backend/tests/test_api_goals.py`, `web/src/lib/api-goals.ts`, `web/src/app/goals/**`, `web/src/components/goals/**` |
| **E** Retrieval v2 + OCR | Embeddings, hybrid search (RRF), OCR fallback hook | `backend/app/core/embeddings.py`, `backend/app/core/hybrid.py`, `backend/app/core/ocr.py`, `backend/tests/test_retrieval_v2.py`; **edit allowed:** `app/services/learning.py` (only the `retrieve()` function), `app/services/ingestion.py`, `app/core/pdf_extract.py` |
| **F** Hardening | Rate limiting, security headers, request IDs, DB job queue + worker, data export, Alembic, RLS SQL | `backend/app/middleware.py`, `backend/app/ratelimit.py`, `backend/app/jobs.py`, `backend/worker.py`, `backend/app/routers/account.py`, `backend/alembic/**`, `backend/alembic.ini`, `backend/sql/**`, `backend/tests/test_hardening.py`, `web/src/app/settings/**` |
| **G** UX polish | Review feedback from the UI preview | `web/src/components/SourceViewer.tsx`, `web/src/components/Tutor.tsx`, `web/src/app/quiz/**`, `web/src/app/page.tsx`, `web/src/app/login/**`, `web/src/app/documents/**`, `backend/app/core/mastery.py` (explanation text only, keep numbers and levels identical), `backend/tests/test_core.py` (only mastery explanation asserts), `docs/ui-preview.html` |

The integrator (principal) owns the shared files, `requirements*.txt`, `docker-compose.yml`, `.env.example`, `README.md` and `docs/DECISIONS.md`. If you need a dependency, list it in your final report instead of editing requirements.

## 2. Shared enums

```
Importance      = "critical" | "high" | "medium" | "low"
EvidenceStrength= "strong" | "partial" | "none"
AssessedLevel   = "strong" | "developing" | "weak" | "unverified"      (same as mastery.py levels)
Confidence      = "high" | "medium" | "low"
GapType         = "strong" | "knowledge_gap" | "application_gap" | "evidence_gap"
                | "communication_gap" | "unverified" | "stretch"
Priority        = "critical" | "high" | "medium" | "low"
CompetencyCat   = "technical" | "domain" | "tool" | "behavioral" | "leadership" | "communication"
QuestionCat     = "technical" | "behavioral" | "case" | "resume_deep_dive" | "role_specific"
```

## 3. Interview prep API (WS B implements, WS C consumes)

All paths are under `/api/interview`. Bearer auth on everything.

### Types

```ts
type ResumeBullet = { id: string; text: string };                  // text = verbatim from resume
type ResumeRole   = { id: string; title: string; company: string; start: string | null; end: string | null; bullets: ResumeBullet[] };
type ResumeParsed = {
  name: string | null;
  summary: string | null;
  roles: ResumeRole[];
  skills: string[];
  education: { id: string; text: string }[];
  certifications: string[];
};
type ResumeOut = { id: string; source_filename: string | null; parsed: ResumeParsed; warnings: string[];
                   user_confirmed: boolean; created_at: string; updated_at: string };

type Competency = { id: string; name: string; category: CompetencyCat; importance: Importance;
                    required: boolean; evidence_quote: string };   // evidence_quote verbatim from JD
type JobParsed  = { role_title: string; company: string | null; seniority: string | null;
                    responsibilities: string[]; competencies: Competency[] };
type JobOut     = { id: string; parsed: JobParsed; user_confirmed: boolean; created_at: string; updated_at: string };

type EvidenceRef = { bullet_id: string; text: string; role_title: string };
type SkillMatch = {
  id: string; competency_id: string; name: string; category: CompetencyCat;
  jd_importance: Importance;
  resume_strength: EvidenceStrength; resume_evidence: EvidenceRef[];
  assessed_level: AssessedLevel; assessed_explanation: string;
  confidence: Confidence;
  gap_type: GapType; priority: Priority;
  priority_factors: { importance: number; gap_severity: number; evidence_confidence: number;
                      urgency: number; feasibility: number };   // each 0..1, for "why this priority"
  recommended_action: string;
  linked_sources: { chunk_id: string; document_id: string; document_title: string; page_start: number; page_end: number; section: string }[];
  user_override: { priority?: Priority; note?: string } | null;
};
type PrepPlanItem = { id: string; competency_id: string | null; title: string;
                      activity: "learn" | "practice" | "story" | "mock_interview" | "drill";
                      estimated_minutes: number; reason: string };
type PrepOut = {
  id: string; resume_id: string; job_id: string; role_title: string; company: string | null;
  interview_date: string | null;  // YYYY-MM-DD
  document_ids: string[];
  skills: SkillMatch[];           // sorted by priority (critical first), then importance
  plan: PrepPlanItem[];
  readiness: ReadinessDim[];
  created_at: string; updated_at: string;
};
type PrepSummary = { id: string; role_title: string; company: string | null; interview_date: string | null;
                     critical_gaps: number; sessions: number; updated_at: string };
type ReadinessDim = { dimension: "role_knowledge" | "applied_problem_solving" | "resume_evidence"
                                 | "behavioral_examples" | "communication";
                      level: AssessedLevel; evidence_count: number; explanation: string };

type Criterion  = { criterion: string; points: number; status: "met" | "partial" | "missing"; evidence: string };
type Evaluation = {
  verdict: "strong" | "adequate" | "needs_work" | "unassessed";
  score: number;                     // 0..1, computed in code from criteria
  criteria: Criterion[];
  star: { situation: boolean; task: boolean; action: boolean; result: boolean; reflection: boolean } | null; // behavioral only
  strengths: string[]; improvements: string[];
  missing_details: string[];         // facts the CANDIDATE must supply (metrics, ownership); never invented
  feedback: string;
};
type InterviewTurn = { id: string; position: number; kind: "question" | "follow_up";
                       category: QuestionCat; competency_id: string | null; competency_name: string | null;
                       question: string; answer: string | null; evaluation: Evaluation | null;
                       asked_at: string; answered_at: string | null };
type SessionSummary = { overall: string; by_competency: { competency_id: string; name: string; score: number; attempts: number }[];
                        top_improvements: string[]; suggested_drills: string[] };
type InterviewSession = { id: string; prep_id: string; focus: "mixed" | "technical" | "behavioral" | "resume" | "case";
                          status: "active" | "completed"; target_questions: number; turns: InterviewTurn[];
                          summary: SessionSummary | null; started_at: string; ended_at: string | null };
type SessionListItem = { id: string; focus: string; status: string; questions: number; avg_score: number | null; started_at: string };
```

### Endpoints

| Method & path | Body | Returns |
|---|---|---|
| `POST /resumes` | multipart `file` (PDF/DOCX) **or** JSON `{ text }` | `ResumeOut` 201 |
| `GET /resumes` | – | `ResumeOut[]` |
| `GET /resumes/{id}` | – | `ResumeOut` |
| `PUT /resumes/{id}` | `{ parsed: ResumeParsed }` (user corrections; sets `user_confirmed=true`) | `ResumeOut` |
| `DELETE /resumes/{id}` | – | 204 |
| `POST /jobs` | `{ text }` | `JobOut` 201 |
| `GET /jobs/{id}` · `PUT /jobs/{id}` `{ parsed }` · `DELETE /jobs/{id}` | | `JobOut` / 204 |
| `POST /preps` | `{ resume_id, job_id, document_ids?: string[], interview_date?: string }` | `PrepOut` 201 (computes the matrix + plan) |
| `GET /preps` | – | `PrepSummary[]` |
| `GET /preps/{id}` | – | `PrepOut` (readiness recomputed from attempts and sessions) |
| `POST /preps/{id}/recompute` | – | `PrepOut` (re-run the matrix after resume/JD edits or new evidence) |
| `PATCH /preps/{id}/skills/{skill_id}` | `{ priority?: Priority, note?: string }` | `SkillMatch` |
| `PATCH /preps/{id}` | `{ interview_date?: string \| null, document_ids?: string[] }` | `PrepOut` |
| `DELETE /preps/{id}` | – | 204 |
| `GET /preps/{id}/deep-dive` | – | `{ bullet_id: string; bullet: string; questions: string[] }[]` (PRD 7.4) |
| `POST /preps/{id}/sessions` | `{ focus?: ..., target_questions?: 3..10 }` | `InterviewSession` 201 (first question already asked) |
| `GET /preps/{id}/sessions` | – | `SessionListItem[]` |
| `GET /sessions/{sid}` | – | `InterviewSession` |
| `POST /sessions/{sid}/answer` | `{ answer: string }` (answers the latest unanswered turn) | `InterviewSession` (evaluated turn, plus next turn appended: a follow-up or the next question; when the target is reached, `status=completed` with `summary`) |
| `POST /sessions/{sid}/end` | – | `InterviewSession` (completed, with summary) |

Behaviour rules:

- Matrix logic is deterministic code. The model only extracts (resume → `ResumeParsed`, JD → `JobParsed`) and judges match strength per (competency, bullet) pair. `gap_type` and `priority` are computed in code from the PRD §7.3 factors. `assessed_level` comes from existing quiz mastery when a competency name matches a quiz concept (case-insensitive token overlap). Otherwise it's `unverified`.
- Never treat a keyword as proof. A skill only listed in "skills" with no bullet is `partial` at best.
- At most 1 follow-up per main question, and only when the evaluation has `missing_details` or `score < 0.6`.
- Follow-ups probe assumptions, metrics, ownership and trade-offs. When details are missing, the AI asks for them and never states them.

## 4. Goals & plans API (WS D implements end to end)

Paths are under `/api`.

```ts
type GoalType = "learn" | "revise" | "exam" | "interview";
type PlanItem = { id: string; position: number; scheduled_date: string; topic: string; concept: string | null;
                  activity_type: "learn" | "practice" | "review" | "mock_interview" | "drill";
                  estimated_minutes: number; objective: string;
                  sources: { chunk_id: string; document_id: string; page_start: number; page_end: number; section: string }[];
                  status: "pending" | "done" | "skipped"; user_edited: boolean; reason: string };
type ProposalChange = { op: "add" | "move" | "remove" | "resize"; item_id: string | null;
                        topic?: string; activity_type?: string; to_date?: string; minutes?: number; why: string };
type PlanProposal = { id: string; reason: string; changes: ProposalChange[]; status: "pending" | "accepted" | "rejected"; created_at: string };
type GoalOut = { id: string; goal_type: GoalType; title: string; target_outcome: string; deadline: string;
                 minutes_per_day: number; study_days: number[]; current_level: string; document_ids: string[];
                 prep_id: string | null; status: "active" | "paused" | "completed";
                 items: PlanItem[]; pending_proposal: PlanProposal | null;
                 stats: { total_minutes: number; done_minutes: number; items_done: number; items_total: number;
                          on_track: boolean; days_left: number; capacity_minutes: number };
                 feasibility_warning: string | null; created_at: string };
type GoalSummary = { id: string; title: string; goal_type: GoalType; deadline: string; status: string;
                     items_done: number; items_total: number; on_track: boolean; today_items: number };
type TodayOut = { date: string; items: (PlanItem & { goal_id: string; goal_title: string })[]; total_minutes: number };
```

| Method & path | Body | Returns |
|---|---|---|
| `POST /goals` | `{ goal_type, title, target_outcome?, deadline, minutes_per_day (10..480), study_days?, current_level?, document_ids, prep_id? }` | `GoalOut` 201 (plan generated) |
| `GET /goals` | – | `GoalSummary[]` |
| `GET /goals/{id}` | – | `GoalOut` |
| `PATCH /goals/{id}` | any of the create fields + `status` | `GoalOut` (edits keep `user_edited` items) |
| `DELETE /goals/{id}` | – | 204 |
| `POST /goals/{id}/regenerate` | `{ keep_edited?: boolean = true }` | `GoalOut` |
| `PATCH /plan-items/{id}` | `{ scheduled_date?, estimated_minutes?, topic?, status?, position? }` (sets `user_edited=true` except for status-only changes) | `PlanItem` |
| `POST /goals/{id}/items` | `{ topic, activity_type, scheduled_date, estimated_minutes }` | `PlanItem` 201 |
| `DELETE /plan-items/{id}` | – | 204 |
| `POST /goals/{id}/adapt` | – | `PlanProposal` or `null` (a proposal from missed sessions and weak mastery, with a reason) |
| `POST /plan-proposals/{id}/accept` · `/reject` | – | `GoalOut` |
| `GET /today` | – | `TodayOut` (pending items for today across active goals; missed items from earlier days appear as overdue only through adapt) |

Planner rules (enforce in `core/planner.py`, all deterministic):

- The model proposes ordered topics with prerequisites and an estimated effort. Code schedules them. The daily sum must never exceed `minutes_per_day`, and the plan must never be scheduled after `deadline` (FR-021, PRD 9.4 "plan never silently exceeds budget").
- If topics don't fit, drop the lowest priority and set `feasibility_warning`. Never compress silently.
- Interleave spaced `review` items for concepts after practice (1, 3, 7 days later when capacity allows).
- For `goal_type="interview"` with `prep_id`, seed topics from the prep's skill gaps (critical/high first) and add `mock_interview` items near the deadline.
- Regenerating keeps `user_edited` items fixed in place and plans around them.

## 5. Retrieval v2 (WS E)

`services.learning.retrieve(chunks, query, k)` keeps its signature and return type. Internally it does hybrid retrieval: BM25 plus vector similarity, fused with reciprocal rank fusion (k=60). The default embedder is a dependency-free hashed character n-gram TF-IDF embedder (`EMBEDDER=hash`), and the interface allows a real model later. OCR: `core/ocr.py` exposes `ocr_pages(pdf_bytes, page_numbers) -> dict[int, str]`. With `OCR=off` it's a no-op. With `tesseract`, it uses `pytesseract` if importable and renders pages via `pypdfium2`. Ingestion calls it for `low_text` pages and records which pages were OCR'd in `status_detail`. `MIN_SCORE` gating must keep "not in your documents" working (keep `test_tutor_not_found_for_unrelated_question` green).

## 6. Hardening (WS F)

- `GET /api/account/export` → JSON attachment with all of the user's rows across every table (no password hash, no file bytes; list storage keys as filenames).
- Middleware: request ID (`X-Request-ID`), security headers (CSP for the API, `X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options: DENY`), and an in-memory token-bucket rate limiter keyed by user or IP for POST/PUT/PATCH/DELETE when `RATE_LIMIT_PER_MINUTE>0` (429 with `Retry-After`).
- Job queue: a `jobs` table (in `app/jobs.py`, which defines its own model) with `enqueue(kind, payload)`, `claim_next()` (`SELECT … FOR UPDATE SKIP LOCKED` on Postgres, a simple transaction on SQLite), retries with backoff and `max_attempts`. `JOB_BACKEND=inline` keeps today's behaviour. `worker.py` runs the loop. Document ingestion is the first job kind. Note that `routers/documents.py` is integrator-owned: report the one-line change needed and don't make it yourself.
- Alembic baseline migration for all tables, plus `sql/rls.sql` with Postgres row-level security policies keyed on `current_setting('app.user_id')`.
- `web/src/app/settings/page.tsx`: profile (email), data export button, delete account (typed confirmation), privacy notes.

---

# Slice 3: final Aura UI and retention features

## 7. Engagement and public API (W2 implements; W4 and the login page consume)

All paths are under `/api` and need bearer auth unless marked *public*. TS types live in `web/src/lib/api-engagement.ts`, which is authoritative and read-only. Python schemas go in `backend/app/schemas_engagement.py` and must match it exactly. Tables are in `backend/app/models_engagement.py` (frozen).

| Method & path | Body | Returns |
|---|---|---|
| `GET /me/prefs` | – | `Prefs` (creates the defaults row on first read; `onboarded = onboarded_at is not null`) |
| `PATCH /me/prefs` | partial `Prefs` (+ `onboarded: true` sets `onboarded_at`) | `Prefs`. Validation: weekly_target 1..7, default_minutes ∈ {5,15,30}, times are HH:MM |
| `GET /today/preview` | – | `TodayPreview` |
| `GET /week` | – | `WeekOut` (Mon–Sun of the current week, user's local week assumed UTC for now) |
| `POST /sessions/study` | `{ minutes: 5\|15\|30 }` | `StudySessionOut` 201 (steps frozen at start) |
| `GET /sessions/study/{id}` | – | `StudySessionOut` |
| `PATCH /sessions/study/{id}/steps/{step_id}` | `{ status: "done"\|"skipped", quiz_id?: string\|null }` | `StudySessionOut` (stores the quiz_id on quiz steps so the session can show results) |
| `POST /sessions/study/{id}/complete` | – | `StudySessionOut` (status completed, `wins` computed) |
| `POST /interview/preps/{prep_id}/debrief` | `{ outcome, next_step, note }` | `DebriefOut` 201. `next_round` → copies the prep with a new date of null and returns `follow_up {type:"prep"}`. `learning_goal` → creates a learn goal from that prep's remaining gaps (reuse services.goals) and returns `follow_up {type:"goal"}`. `new_role` and `none` → `follow_up: null` |
| *public* `POST /public/gap-report` | `{ resume_text, job_text }` (each 200..20000 chars) | `PublicReport`. Nothing is persisted except an in-memory TTL cache (30 min) keyed by token. Rate-limited per IP (5/hour). Uses the existing interview parse/match services with the mock or real provider. Only the top 5 skills are returned |
| `POST /auth/signup` | existing body **+ optional** `report_token` | existing. If the token is valid, create ResumeProfile + JobProfile + RolePrep for the new user from the cached report. *Integrator applies this to routers/auth.py using a helper W2 provides: `services/public_report.claim(token, user_id, db) -> prep_id or None`* |

**Session builder rules** (pure, in `backend/app/core/session_builder.py`, unit-tested):

- Inputs: minutes (5/15/30); due-for-review concepts (from mastery); today's pending plan items (from goals); the top unresolved prep gaps (critical/high); ready document ids. **No model calls.**
- Priority order: due reviews, then today's plan items, then the top prep gap (story or mock_question), then fresh practice on unverified concepts.
- Step time costs: review 4, quiz 5, mock_question 5, story 6, learn 8. plan_item uses its estimated minutes, capped at the remaining time.
- Fill greedily without exceeding `minutes`. 5 min = exactly one step. Never return an empty list when any material or prep exists; fall back to "Take a 5-question quiz on <doc title>".
- Each step's `detail` is one short, plain sentence saying why it was chosen ("Due for review: last practised 9 days ago", "Critical for your Amazon role").
- `suggestions` in TodayPreview runs the builder for 5, 15 and 30.

**Wins** (pure): compare mastery levels before and after the session's attempts. `level_up` when a concept moves up a level; `gap_closed` when a prep skill moves out of a gap; `first_answer` when it's the user's first ever attempt; `target_met` when the week's done count reaches the target. Titles use plain words, e.g. "Little's Law is now strong".

**Week**: a day counts as practised if any StudySession completed that day **or** any Attempt was made.

## 8. Answerability gate (W3)

This fixes the eval's `not_found_recall` of 0.375. Add `app/core/answerability.py` (pure) and wire it into `services/learning.ask_tutor` *before* the tutor model call:

1. **Lexical guard**: for queries with ≤ 6 content tokens, require that at least 2 distinct query content tokens (or 1 if the query has only 1) appear in the top retrieved chunk, or a cosine ≥ the calibrated threshold. A single shared common word ("capital", "year", "level", "pricing") must not pass.
2. **Model check** (provider-agnostic): Gateway task `answerable` (tier fast) returns `{answerable: bool, reason}` given the question and the top 3 sources. The mock implements a deterministic version: answerable if the question's *head noun phrase* overlaps the source. Skip this check when the lexical guard is very confident (e.g. bm25 ≥ 3.0 and ≥ 2 shared terms) to save cost.
3. If not answerable, return `status=not_found` without calling the tutor.

**Acceptance**: `python -m evals.run` shows not_found_recall ≥ 0.875 with no drop in citation_page_accuracy, key_fact_recall or retrieval_recall_at_1 beyond 0.02. Update `evals/baseline.json` only once that holds. All existing tests stay green.

## 9. Final UI (Aura) rules for every screen

**Read first:** `web/src/app/globals.css` (the design system: tokens, `.glass`, `.hero-card`, `.tint-*`, `.badge.*`, `.segmented`, `.arrow-tile`, `.icon-well`, `.tile-link`, `.week-dots`, `.steps4`, `.page-head`, `.empty`, `.skeleton`), `web/src/components/Icon.tsx`, `web/src/components/Shell.tsx` (`BackLink`), and `docs/design-concepts.html` section F (the approved look).

- **Navigation**: Today `/`, Prep `/prep`, Library `/library`; Profile `/settings` via the avatar. Old routes keep working: `/interview/*` and `/goals/*` are Prep detail screens; `/documents/*` and `/quiz/*` are Library detail screens.
- **One orange per screen**: `.primary` (safety orange with charcoal text) is used for the single most important action only. Secondary actions use the default glass button or `.dark`. Gap and critical labels use `.badge.gap`.
- **Type**: medium weight (500) for headings and names; regular for body; no serif, no all-caps, no bold paragraphs.
- **Cards**: `.glass` / `.card` for surfaces; `.hero-card` for the one featured card per screen; `.tint-gap / .tint-unknown / .tint-ready` for state, always with a text label. Rounded corners come from the tokens.
- **Every tappable card** ends with an `.arrow-tile` containing `<Icon name="arrow" />` and is a real `<Link>` or `<button>`.
- **Copy**: plain words from the UX research. Today/Prep/Library. "What you know", not "mastery". "Not enough answers yet", not "unverified". "Update", not "recompute". "Rebuild my plan", not "regenerate". Errors say what happened and how to fix it.
- **States**: every data view has loading (`.skeleton` blocks), empty (`.empty` with one action) and error (`.notice.bad` with a retry) states.
- **Mobile first**: design at 375px wide first. Content must clear the floating tab bar (the container already pads the bottom). Tap targets ≥ 44px.
- **Accessibility**: labels on every input, `aria-pressed` on toggles, `aria-live="polite"` for async results, focus moves to new content after submit, colour never the only signal.
- Keep using the existing API clients (`@/lib/api`, `@/lib/api-interview`, `@/lib/api-goals`, `@/lib/api-engagement`); don't change their shapes.

## 10. Slice 3 ownership

| WS | Scope | Owns |
|---|---|---|
| **W2** Engagement backend | §7 everything | `backend/app/core/session_builder.py`, `backend/app/core/wins.py`, `backend/app/services/engagement.py`, `backend/app/services/public_report.py`, `backend/app/schemas_engagement.py`, `backend/app/routers/engagement.py`, `backend/app/routers/public.py`, `backend/tests/test_engagement*.py`, `backend/tests/test_api_engagement.py` |
| **W3** Answerability | §8 | `backend/app/core/answerability.py`, `backend/app/ai/mock_answerability.py`, `backend/tests/test_answerability.py`; edits allowed in `backend/app/services/learning.py` (`ask_tutor` only), `backend/app/ai/prompts.py` (append a new prompt constant only), `backend/evals/baseline.json` |
| **W4** Today and onboarding UI | Today `/`, onboarding, timed session, progress, welcome and login | `web/src/app/page.tsx`, `web/src/app/session/**`, `web/src/app/progress/**`, `web/src/app/welcome/**`, `web/src/app/login/**`, `web/src/components/today/**` |
| **W5** Prep UI | Prep hub + restyle every interview and goals screen | `web/src/app/prep/**`, `web/src/app/interview/**`, `web/src/app/goals/**`, `web/src/components/interview/**`, `web/src/components/goals/**` |
| **W6** Library UI | Library hub + restyle document, quiz and settings | `web/src/app/library/**`, `web/src/app/documents/**`, `web/src/app/quiz/**`, `web/src/app/settings/**`, `web/src/components/SourceViewer.tsx`, `web/src/components/Tutor.tsx`, `web/src/components/library/**`, `web/src/components/ui.tsx` (restyle only, keep exports) |
| **W7** Review preview | A static clickable mirror of the final Aura app | `docs/ui-preview.html` (rewrite) |

Shared, read-only for slice 3: `globals.css`, `Icon.tsx`, `Shell.tsx`, `layout.tsx`, `api*.ts`, `models*.py`, `main.py`, `deps.py`, `config.py`, `routers/auth.py`, `docs/CONTRACTS.md`. If you need a class that doesn't exist, use inline styles inside your files, or a `<style>` tag scoped by a class prefix unique to your workstream (`today-`, `prep-`, `lib-`). Don't edit globals.css.
