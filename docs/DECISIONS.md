# Engineering decisions — slice 1

Each entry: what we chose, why, and when to revisit.

## 1. Thin vertical slice before platform breadth
Chosen: the full learning loop working end to end on one document type (text PDFs), not a complete platform with no features.
Why: citation accuracy and question quality are the riskiest assumptions in the PRD. We need real users on the loop as early as possible.
Revisit: never. Every later slice should also ship end to end.

## 2. Citations are verified in code, not trusted
The model has to return a verbatim quote for every source it cites. `core/citations.py` rejects citations that point to unknown source ids, and quotes that don't fuzzy-match (≥0.85) the retrieved chunk. It strips the rejected markers from the answer and labels the answer `verified / partial / unverified / not_found / general`.
Why: PRD principle "grounded by default" and the ≥95% valid-citation release gate. A wrong page number does more damage to trust than having no citation.

## 3. BM25 retrieval in-process, pgvector later
Why: there's no infra to run, the results are deterministic and testable, and it's strong on the term-heavy questions people ask about textbooks. The `Retriever` protocol lets us add semantic search and rank fusion without touching callers. Postgres in compose already uses the pgvector image.
Revisit: when the eval set shows recall misses on paraphrased questions. Expect this in slice 2.

## 4. Structure-aware chunking with page anchors
Chunks follow heading and paragraph boundaries (target 1,200 chars, max 2,000), never split mid-line, and carry `page_start`, `page_end` and `section_path`.
Revisit: once OCR/multimodal parsing lands and we can see layout (tables, formulas as images).

## 5. Deterministic code where possible
MCQ grading, rubric score arithmetic (the model judges each criterion, code computes the score), mastery, question validation, deduplication, next-action rules and budgets are all plain code. The model only does what needs language understanding.
Why: PRD 11.4. It's also reproducible and cheaper.

## 6. Mastery: transparent rules, raw attempts stored
Weighted average by question type (applied > short > MCQ) and difficulty, with a 14-day half-life decay. Fewer than 3 answers = "Not enough evidence", which is shown separately from "Needs work". Every estimate comes with a plain-English explanation. Raw attempts are stored, so we can recompute when we move to knowledge tracing.

## 7. Provider-agnostic AI gateway with a mock provider
Every model call goes through `ai/gateway.py`: tier routing (main/fast), retries with backoff, a one-shot JSON repair, per-user rolling 24h token budget, and usage events (metadata only, no content). The deterministic `MockProvider` means CI, demos and frontend work don't need an API key.

## 8. Prompt-injection posture
Document text and student answers are wrapped in tags. Tag-like sequences inside them are neutralised, and the system prompt says tagged content is data. Even if an injection gets through, citation verification and schema validation limit the damage: the model can't add a citation that isn't in the source, and it can't save a question that fails the schema.

## 9. Tenant isolation at the query layer
Every user-owned table has `owner_id`. Every query filters by it. Other users' resources return 404, not 403. `tests/test_api.py::test_cross_user_isolation` enforces this.
Next: add Postgres row-level security as a second layer before beta.

## 10. Auth: first-party for now
scrypt (stdlib) + HS256 JWT so the app runs locally with zero external services. The PRD recommends a managed identity provider. Only `deps.current_user` changes when we swap.

## 11. Copyright guardrail
Uploads need an explicit "I have the right to use this file for personal study" confirmation (enforced by the API, not just the UI). Files are private, the original is served only to its owner with `no-store` caching, and nothing is shared across users.

## Known gaps (deliberate, tracked)
- No OCR: scanned pages are detected and flagged, not read.
- Ingestion runs as an in-process background task. Move to a real worker queue (the job is already idempotent) before multi-instance deploys.
- `create_all` instead of Alembic migrations. Switch before the first real deployment.
- Goals and study plans (FR-020 to FR-023) aren't in this slice. "Next action" is rule-based from the mastery state.
- No rate limiting at the HTTP layer yet (only token budgets).
- Token stored in localStorage. Move to httpOnly cookies along with the managed auth provider.

## Slice 2 (built 2026-10-10, parallel build against docs/CONTRACTS.md)

### 12. Contract-first parallel build
Seven workstreams (eval, interview backend, interview UI, goals, retrieval, hardening, UX) were built at the same time against a frozen contract, with strict file ownership. Shared extension points meant no one had to edit shared files: `models_*.py` auto-registration (`db.load_all_models`), `@register_mock` for offline AI tasks, and `routers/*` stubs already mounted in `main.py`.

### 13. Interview prep: the model extracts, code decides
The model only parses (resume, JD) and judges per-bullet evidence. Every extracted bullet and JD quote must fuzzy-match the source text or it's dropped with a warning, so hallucinated experience can't enter the matrix. Gap type, priority (PRD §7.3 factors, shown to the user) and readiness are deterministic code. A skill that only appears in the "skills" list is never "strong". No assessment means "unverified", never "weak". Interview scores are recomputed from rubric criteria in code. There's at most one follow-up per question, and `missing_details` asks the candidate for facts instead of inventing them. User priority overrides survive a recompute.

### 14. Planner: the model proposes topics, code schedules
`core/planner.py` guarantees no day exceeds the budget, nothing is scheduled past the deadline, prerequisites come first, and reviews are spaced (+1/+3/+7 days). It's property-tested over 85 random configs. Topics that don't fit are dropped (lowest priority first) as visible "Left out" items with a warning, never silently compressed. User-edited items stay fixed through a regenerate. Adaptation produces a *proposal* the user accepts or rejects (FR-023).

### 15. Retrieval v2: hybrid without new infrastructure
BM25 + a hashed word/char-n-gram embedder (numpy only), fused with RRF (k=60). Paraphrase recall@3 went from 8/9 to 9/9, typos/spelling variants from 0/3 to 3/3, and eval citation page accuracy from 0.677 to 0.708. A question takes ~8 ms over 3k chunks once indexed. The `Embedder` protocol is the swap point for a learned model or pgvector. That needs its own threshold calibration, documented in `core/hybrid.py`. OCR (tesseract) is optional, capped at 50 pages and 120 s per document, and never fails ingestion.

### 16. Hardening
Request IDs, security headers, token-bucket rate limits (separate login/signup bucket), a request-size guard, a DB job queue with a separate `worker` service (`SKIP LOCKED` on Postgres, at-least-once with idempotent handlers), an Alembic baseline, Postgres RLS (`sql/rls.sql`) as a second layer behind app-level owner filters, and full data export at `GET /api/account/export`.

### Known issue surfaced by evals
**not_found recall is 0.375.** Off-topic questions that share one ordinary word with the text ("capital of France" vs "working capital") still get answered. This existed in v1 and isn't a regression. Fix options, in order: (a) add a cheap model "is this answerable from these sources?" check before answering, (b) require ≥2 matching query terms for short queries, (c) a learned embedder with calibrated thresholds. Track it with `python -m evals.run`.

### Not yet verified (sandbox had no FastAPI/SQLAlchemy/npm)
The pure logic is covered by 332 passing tests. These haven't run anywhere yet: the router/DB code, the API test files (`tests/test_api*.py`), the Alembic migration, RLS, and the TypeScript build. First run: `pytest`, `npm run typecheck && npm run build`, `docker compose up --build`, then `alembic upgrade head` on a fresh DB.

## Slice 3 (built 2026-10-10): final Aura UI and retention features

### 17. Aura is the final design system
Frosted glass over a soft mint/sky/peach glow, Avenir Next at regular and medium weights, thin line icons, arrow tiles on tappable cards, and one safety-orange action per screen. All tokens and classes live in `web/src/app/globals.css`, and the old class names still work. Contrast rules are written at the top of the file: orange always carries charcoal text, and stone grey is only used on glass or white. A "Reduce transparency" setting (Profile) and the OS `prefers-reduced-transparency` both switch glass to solid. It's applied before first paint from `localStorage.mindmesh_solid`.

### 18. Structure from the UX research
The app has three places: **Today** (`/`), **Prep** (`/prep`, which holds role preps and study goals) and **Library** (`/library`). Profile sits behind the avatar. Phones get a floating tab bar. Old routes still work: `/interview` and `/goals` redirect to `/prep`. Signed-out visitors land on **`/welcome`**, a free gap report that needs no account. Signing up from it keeps the report (`report_token` is passed to `/auth/signup`).

### 19. Retention features
- **Timed sessions:** you choose 5, 15 or 30 minutes and the session is built deterministically (`core/session_builder.py`, no model calls). The order is due reviews, then today's plan items, then the top interview gap, then fresh practice. It never runs over the chosen time.
- **Weekly target:** a target you set, instead of daily streaks.
- **Wins:** plain-language wins after each session.
- **One question at a time:** quizzes now show one question per screen, and a quiz started from a session returns to it.
- **Post-interview debrief:** after the interview date, the app asks how it went. It then offers to prepare for the next round, start a new role, or turn the remaining gaps into a learning goal.

### 20. Answerability gate (fixes the known issue)
Before the tutor answers, a word check rejects questions that share only one ordinary word with the documents ("capital of France" vs "working capital"). It skips the extra check when the match is clearly strong, and otherwise asks a fast model "can these pages answer this?". Evals: not_found_recall 0.375 → **1.000**, with no change to citation accuracy, key-fact recall or top-1 retrieval. About a third of questions trigger the extra fast-model call. If that check returns something unusable, the question is allowed through rather than silently blocked.

### Verification status (slice 3)
- **Backend:** 404 pure tests pass, and the evals pass against the new baseline.
- **Web:** the whole `web/src` tree passes a strict TypeScript check (`noUnusedLocals`) against stand-in React/Next type definitions.
- **Migration:** Alembic revision `0002_engagement` adds the three new tables, and RLS covers them.
- **Not yet run:** a real `npm run build`, the FastAPI API tests (`tests/test_api*.py`), the migrations against Postgres, and any check in a real browser.

## P0: first real run (2026-10-17)

### 21. Results
- **Backend:** 429 tests pass, including the API tests (first run), in any file order. The mock eval matches the baseline on every metric (citation validity 1.000).
- **Web:** `tsc --noEmit` and `next build` pass (18 routes).
- **Postgres 16:** `alembic upgrade head` runs both revisions, `alembic check` finds no drift between models and migrations, and `sql/rls.sql` enables and forces RLS on all 19 owner tables (idempotent).
- **RLS works end to end:** `tests/test_postgres_rls.py` runs the learning loop through the DB job queue with RLS forced. It then checks at the database that rows are invisible without the owner's `app.user_id` (fail closed), that cross-user updates change nothing, that inserts under another user's id are rejected, and that account deletion still cascades. It's skipped unless `MINDMESH_PG_URL` is set; CI's `postgres` job runs it.
- **Not verified:** `docker compose up` itself (no Docker on the dev machine). The compose changes below were checked by replaying the init script on a scratch database.

### 22. Fixes
- **Docker compose bypassed RLS entirely.** The api and worker connected as the image superuser, and superusers ignore every policy. Running the RLS tests as a superuser reproduces it (2 failures). They now connect as `mindmesh_app`, a non-superuser created by `backend/sql/init/01-app-role.sql`, and the RLS test fails if the app role can bypass RLS.
- **API tests shared one database.** Each test file set its own `DATABASE_URL`, but `app.db` builds one engine per process, so reused emails collided depending on file order. `conftest.py` now gives every `client` test empty tables, and `test_api.py` reads the storage dir from settings.
- **OCR would crash in production.** `core/ocr.py` needs `pypdfium2`, which wasn't in `requirements.txt`.
- **CI:** dependency audits (`pip-audit`; `npm audit` gated at critical), Dependabot, and the `postgres` job.

### Known issues
- `npm audit` reports a high-severity `postcss` advisory via Next 15 (source-map file disclosure at build time). The fix is the breaking Next 16 upgrade; schedule it in P1.
- Homebrew's `pgvector` ships for Postgres 17/18 only. Local pg16 has no `vector` until P2 needs it (build from source or move dev to pg17); the compose image already includes it.
- `uvicorn --reload` watches `backend/.venv`, so a `pip install` restarts (and can crash) a running dev server. Use `--reload-dir app` if this bites.
- The repo lives on an iCloud-synced Desktop, which creates "name 2" conflict copies of files. Keeping the repo outside iCloud is safer for `.git`.

## P1 Wave 1: foundations (2026-10-17)

### 23. Knowledge graph in Postgres, not a graph database
Each user's graph is small (hundreds of concepts, thousands of edges) and the product asks 1–3-hop questions, which recursive CTEs answer in milliseconds. Keeping it in Postgres keeps RLS, transactions, account export and deletion working with no extra system. Wave 1 adds `kg_nodes` and `kg_edges` (migration 0003), concept nodes from quizzes and plans, and the planner's prerequisite ordering saved as `verified=False` edges. P2 grounds edges in page quotes, merges duplicate concepts and links interview competencies. Revisit only for a cross-user graph at millions of nodes, and even then as a read-only copy fed from Postgres.

### 24. "Today" is the user's calendar day
The planner used the server's date and the Today screen used UTC, so near midnight a new plan had nothing for "today" (found by the e2e tests at 02:00 IST). The web client now sends its IANA timezone as `X-Timezone`, `app/clock.py` turns it into the user's date, and missing or unknown zones fall back to UTC. Timestamps stay UTC. Never use `date.today()` in the backend.

### 25. Shared state in Redis, failing open to memory
With `REDIS_URL` set, rate limits (one atomic Lua token bucket) and the signed-out report cache (single-use claims via GETDEL) are shared across API processes. Without it, nothing changes. If Redis is down, a 5-second circuit breaker falls back to the per-process limits: no retries, so an outage costs one 0.5-second timeout every few seconds rather than about 4.5 seconds per request (redis-py's default).

### 26. Logs and errors never carry user content
JSON logs in prod with a request id on every line, and one access line per request with the path only. uvicorn's own access log is off because it records query strings and client IPs. Error tracking (Sentry-compatible, only when `SENTRY_DSN` is set) never sends request bodies, local variables, cookies, auth headers or query strings, because resumes and documents pass through every handler.

### 27. Uploads
Content-type checks were already by magic bytes. Added: an RFC 6266 `Content-Disposition` (non-Latin-1 filenames returned 500), DOCX zip-bomb limits before parsing, and an optional ClamAV scan (`UPLOAD_SCAN=clamd`) that fails closed.

### 28. Web on Next 16.3.8
Clears the npm advisory. Versions are pinned exactly, and only releases at least two weeks old are used (16.4.x was days old). `next lint` is gone in 16. `next-env.d.ts` is generated, so it's untracked; `npm run typecheck` regenerates it.

### Verification (end of Wave 1)
Backend: 457 tests in memory, 465 with the Redis tests, the API tests rerun through Redis, and Postgres migrate, `alembic check` and RLS tests (21 tables). Evals match the baseline. Web: typecheck, build and 3 Playwright flows; `npm audit` and `pip-audit` report nothing. Still not run: `docker compose up` and the CI workflow itself (the repo has no remote yet).

### Found for later waves
- **Onboarding (Wave 4):** Today still asks "What are you preparing for?" after the user has uploaded material and built a plan.
- **Copy (Wave 4):** the gap report says "The top 0 skills are below." when parsing finds nothing.
- **Mock parser:** a job ad or resume pasted as one paragraph yields no requirements or bullets offline. Check with the real model in task 9.
- **iCloud:** sync conflict copies inside `web/.next` broke typecheck and build twice. Move the repo out of the iCloud Desktop.

## P1 Wave 2: sign-in with Clerk (2026-10-17)

### 29. Clerk is the front door; Mindmesh keeps the user
Chosen over Auth0 (cost per user, redirect-only login) and Supabase Auth (a second Postgres, a self-built UI and cookie layer). The browser holds only Clerk's short-lived session token (about 60 s), refreshed through Clerk's httpOnly cookie. That replaces the long-lived token in `localStorage` and the separate cookie + CSRF task.
- **Verification** (`app/clerk.py`, PyJWT): RS256 only; `iss` = Frontend API URL; `azp` in `CLERK_AUTHORIZED_PARTIES` (required outside dev/test); `exp`/`nbf` with 5 s leeway; `sub`, `sid` present; `sts` not pending.
- **Mapping**: `users.external_id` (migration 0004). On a user's first request, one Backend API call creates the row. An existing local account is linked only when Clerk reports the email as verified (otherwise 403); an email linked to a different Clerk user gets 409. `users.id` stays the key for owner_id, RLS, export and deletion.
- **RLS subtlety:** the lookup transaction starts before the user id is known, so it's committed before the request continues. Without that, a new user's first upload was invisible to them on Postgres (caught by a Postgres test).
- **Modes:** `AUTH_PROVIDER=local` keeps email + password for dev, tests, CI and e2e with no external service. `clerk` turns the password endpoints off (404).
- **Gap report:** `POST /api/public/claim` (signed in, single-use) replaces carrying `report_token` in the sign-up request.
- **Lifecycle:** deleting an account removes our data first, then queues `delete_clerk_user` (retried with JOB_BACKEND=db). The webhook `/api/webhooks/clerk` handles `user.deleted` and `user.updated`; signatures are checked over the raw body with a 5-minute replay window, deliveries can repeat safely, and it's off until a signing secret is set.

### 30. Incident: a test run wiped the local dev database
On 2026-10-17 at 02:30 IST, a reverse-order test run deleted the rows in `backend/mindmesh.db` (2 accounts, 2 documents and their 5,324 chunks, 1 role prep with 7 skill matches). Cause: the P0 API-test fixture drops and recreates tables, and since Wave 1 importing the public-report service reads settings at import time. When `test_engagement_core.py` was imported first, settings were cached with the defaults (`./mindmesh.db`, `./data/uploads`) before any test set a temporary database. Alphabetical runs, including CI, never hit this order. No backup existed (no Time Machine; iCloud keeps no versions). The two original PDFs survived in `backend/data/uploads/0a48d984…/` and can be uploaded again; the pasted resume and job text are gone.
Fixes: `conftest.py` forces a throwaway database and upload directory before any test module is imported, overriding the shell; the reset refuses anything but a SQLite file under the system temp dir; `test_test_isolation.py` pins both. Verified in alphabetical, reverse, shuffled and the exact failing order, with `mindmesh.db` untouched. Lessons: tests that delete data need a guard checking where the data is, and order-dependence checks should also watch for side effects outside the test run, not only failures.

### Status (end of Wave 2 backend)
509 backend tests (517 with Redis), Postgres 6/6 including a Clerk-mode RLS test, `alembic check` clean, evals at baseline, `pip-audit` clean, web typecheck and 3 e2e flows (local auth) pass. Not done yet: the web integration (needs the Clerk keys) and running against a real Clerk instance.

## P1 Waves 2 (web), 3, 4 and 5 (2026-10-17)

### 31. Real-model calls were broken; provider updated for Claude 5-generation models
The provider passed `temperature`, which the installed `anthropic` 1.x SDK no longer accepts, so every real call raised `TypeError` before reaching the network. It was hidden because everything ran on the mock. Now: no sampling parameters; `max_tokens` of at least 16k (thinking counts against it); effort per tier only on 5.x models; server-side refusal fallbacks on Sonnet/Opus/Fable 5.x; refusals are not retried; truncation is an error, never half a JSON. A test drives the real SDK at a closed port, so any unsupported parameter fails CI. The default models stay Sonnet 4.5 / Haiku 4.5 (both still active) until `evals.compare_models` recommends a change on real PDFs.

### 32. Prompt injection: what code guarantees vs what the model must do
Code guarantees that planted text can't fake citations (CI gate on `gold/adversarial.jsonl`), that prompt tags are stripped from answers, and that answers render as plain text (no HTML or markdown in the web app). Whether the model obeys or echoes planted instructions is measured by `injection_resistance` with the real model (`--fail-under-injection 1.0`); the extractive mock echoes by design, so it isn't gated there.

### 33. DB connections are released before model calls
Load test, 100 learners with 1.5 s simulated model latency: the pool (5+10) ran out and requests timed out after 30 s, because each request held its connection through the model call. `Gateway.before_call` now ends read-only transactions before each call (transactions that have written keep their connection, so routes stay atomic); the pool is configurable; an exhausted pool answers 503 + `Retry-After`. After: 1,000 requests, 0 errors. See `docs/load-testing.md`.

### 34. Product (Wave 4)
Onboarding is inferred from activity; empty gap reports explain what to fix; citations scroll to and pulse the cited sentence (word-level matching, Devanagari-safe); question reports have reasons, a triage list in the Library, Undo and a content-free operator report; email reminders and a weekly summary over SMTP in the user's own time zone, idempotent across workers, with one-click unsubscribe. Emails carry counts only.

### 35. Web sign-in (Wave 2 web)
Clerk behind `NEXT_PUBLIC_AUTH_PROVIDER` (local stays the default for dev and CI). `src/proxy.ts` guards pages; tokens come from Clerk's `getToken()`; a signed-out report survives the OAuth redirect in `sessionStorage` and is claimed on `/claim`. Verified with a placeholder key (build; public and protected routes); real sign-in needs the dashboard keys. `.env.local` files are now git-ignored (the Clerk secret would otherwise have been committable).

### 36. Launch readiness (Wave 5)
Accessibility: axe WCAG 2.2 AA on 11 screens in CI (fixed: loading placeholders with an ignored `aria-label`). Deploy kit: `app.tools.migrate` (Alembic + RLS) as a compose step the API waits for, a prod compose override, `/api/health/ready`, tag-triggered image builds. Cost report per task, model and active user. Legal drafts and the usability kit (`docs/legal/`, `docs/usability-test-kit.md`). iCloud: Next's build output moved to `.nosync` folders.

### Status (end of P1 build)
577 backend tests (with Redis), Postgres 7/7, `alembic check` clean, evals at baseline plus the adversarial gate, 9 e2e flows including accessibility, both web build modes, audits clean.
**Needs you:** Clerk keys (then real sign-in check); an Anthropic key + 3–5 PDFs (real-model eval and model choice); a GitHub remote (CI and release workflows have never run); hosting (staging; `docker compose` has never run); an email provider; the `[DECISION]`s in `docs/legal/`; usability participants. **Still to build once decided:** purge jobs for the retention periods.

## P1 Wave 6 (2026-10-19)

### 37. Job ad import from a link: the server fetches, so it's an SSRF surface
`POST /api/public/job-from-url` (signed out, no model call, nothing stored, 20 per IP per hour). http/https on default ports only, no credentials in the URL; every address the host resolves to must be public (loopback, private, link-local incl. cloud metadata, CGNAT, multicast, reserved and IPv4-mapped forms are refused); the connection goes to the checked address with Host and TLS SNI set to the name, so DNS can't change between check and fetch and certificates are still verified; redirects are followed by hand (max 3), each re-checked; 2 MB, 6 s, HTML or text only. schema.org `JobPosting` JSON-LD is preferred over page text. Sites that need JavaScript or a sign-in get "paste the text instead". The URL is never logged.

### 38. Filling the processing wait
Documents over 12 pages save their first pages' chunks straight away; `pages_done` and `processing_started_at` (migration 0007) report progress. Ask and quizzes accept a document that is still processing once `pages_done` is set (answers use the pages read so far, and the UI says so). The final pass keeps every early chunk whose content didn't change, so citations made during the wait still resolve. The wait screen shows pages read and time left, the topics found so far, "Try 3 quick questions" and "Read and ask now"; Library cards link to it. Push or email "it's ready" notices are not built (the page says it's safe to leave).

### 39. Concept extraction as a job
After processing, `extract_concepts` makes one fast-tier call over an outline (each section's start, topped up with evenly spaced excerpts, at most 30 × 420 characters). A concept is kept only if its quote is found in the excerpt it names (the citation rule), is specific (no "Introduction"), and isn't a duplicate by `canonical_key`. Stored as `document --covers--> concept` edges (`source=model`, `verified=true`, provenance: chunk, page, quote) from a `kind=document` node; re-running replaces them; deleting the document removes its node and edges, while shared concept nodes stay. Charged to the owner's daily budget and skipped quietly when over; a failure never affects the document (`jobs.chain`). `CONCEPT_EXTRACTION=off` turns it off. First use: topic suggestions in Practise.

### 40. Fixed: practice just after local midnight didn't count
`practised_in_range` bounded its query by UTC midnight, so in India anything practised between 00:00 and 05:30 was missed: the evening reminder still went out, and Today's week row showed the day empty. Day bounds now use the user's time zone. Found because the digest tests failed when run just after midnight IST; they, and the Postgres reminder test, also no longer depend on the weekday (Mondays add the weekly summary).

## P1 Wave 7 (2026-10-19): the last buildable P1 items

### 41. Retention purge jobs, with the legal periods still to be chosen
`services/retention.py`, run hourly by the worker and by `python -m app.tools.purge [--dry-run]`. Each period is a setting in days; **0 means keep**, the default for the email log, AI usage records and product events until the `[DECISION]`s in `docs/legal/retention-policy.md` are made. Finished job rows default to 30 days, because their payloads can carry identifiers (a deleted account's Clerk id). A period shorter than the product needs is raised and logged (email log 8 days for one-per-day and weekly idempotency; usage 2 days for the 24-hour budget). Batched deletes; queued and running jobs are never touched; works under RLS through the system context.

### 42. First-party product analytics and the activation metric
`product_events` (migration 0008, owner-scoped, RLS, purged by retention). An event is a name plus allowlisted properties that can only be booleans, small integers or short lowercase tokens, so content can't be stored by mistake. No third-party analytics: nothing leaves our database. Activation follows ux-research: a gap report on the user's own resume and a job, or a verified (or partly verified) cited answer plus an answered question. It is recorded once, with the path and seconds since sign-up. Analytics never fails a request (`analytics.record` swallows and logs).

### 43. Goal-first vs upload-first onboarding experiment
The arm is a stable hash of experiment + user id (no storage, never flips); `EXPERIMENT_ONBOARDING` = on (50/50) | off (control, goal-first) | goal_first | upload_first. Exposure is recorded when the onboarding is actually shown, and the server decides the arm in that event, so a client can't skew it. Upload-first starts with "Upload a document" or "Add your resume and a job", and the goal is inferred later (DECISIONS #34). Primary metric: activation within 3 minutes of sign-up; 1 and 7 days are secondary. `python -m app.tools.experiment_report` prints counts per arm with two-proportion p-values, and warns below about 400 users per arm (needed to see 10 points around 50% at 80% power).

### 44. Accessibility: keyboard, reflow and motion are now CI checks
`web/e2e/keyboard.spec.ts`: a Tab audit on every main screen (visible focus at each stop, no traps), keyboard-only gap report, tutor and quiz, Escape returning focus, 320px reflow, and reduced motion. Found and fixed: date fields had no visible focus in Chromium. Screen-reader checks (VoiceOver, TalkBack) still need a person; they are listed in `docs/accessibility.md`.


## P2 Intelligence (2026-10-19, branch `phase-2/intelligence`)

### 45. Concept merging: precise rules, model for the rest, never delete
Rules merge only certain duplicates: plurals, acronyms with a single expansion in the user's graph, and parentheticals. On `evals/gold/concept_merges.jsonl` they score 27/27 with no false merges, gated in CI. Names that share most words go to a fast-model check, and a "no" is remembered. A merge moves the edges, sets `kg_nodes.merged_into_id` (migration 0009) and leaves a `same_as` audit edge. Attempts keep their original concept name; `concept_aliases` makes mastery, sessions and retrieval treat the names as one. `rebuild_graph` (job) runs after concept extraction, quiz creation and prep changes.

### 46. Prerequisite edges must quote the material
Concept extraction (the same single call) also returns prerequisites, each with a quote from the excerpt that shows the dependency. Unverifiable, two-way, self and unknown-concept claims are dropped. Grounded edges are `verified` (source `document`, provenance with page and quote); a matching planner guess is upgraded. Only grounded edges drive plan ordering and root-cause practice (labelled "your material says so"); planner guesses don't. Deleting the document removes the edges it grounded.

### 47. Skills link to concepts in the learner's material
`competency --maps_to--> concept`: by rule (same words, acronym, contained words; verified), else a fast-model judgement (unverified). Skipped when skills and concepts haven't changed (a signature on a `meta` node). The skill card shows "Concepts to study in your material" with a link to the page (`/documents/{id}?page=N`).

### 48. Knowledge tracing replaces the weighted average
Bayesian Knowledge Tracing per learner × concept:
- Guess rates depend on question type (an MCQ is easy to guess, an applied answer isn't), and slip and guess shift with difficulty.
- Partial scores count as partial evidence.
- Knowledge drifts back towards the prior with a 90-day half-life. Review timing still follows the old interval rule, so a month off doesn't relabel a strong concept.

On simulated learners drawn from a different (IRT-style) model it predicts the next answer better: log loss 0.57 vs 0.62, AUC 0.75 vs 0.70, gated in CI. The parameters are priors; `app.tools.fit_mastery` fits them once a few hundred real sequences exist.

### 49. Root-cause practice
Today starts with the nearest prerequisite (depth ≤ 2) of the weakest concepts that is itself weak or untested and has material to practise from, at most two ("Practise X first: Y builds on X"). New plans add grounded prerequisite edges between their topics before scheduling. This meets the P2 exit criterion "prerequisite-first sessions".

### 50. Graph-aware retrieval
The search query gains the other names of the concepts a question mentions (from merges). The passage a concept was extracted from is moved into the top results only if retrieval already ranked it as a candidate. The coverage gate is untouched and no hints means identical results; the eval set is unchanged. Example: "What is WIP?" now finds the "work in process" passage.

### 51. Learned embeddings: built, off until a provider is chosen
Anthropic has no embeddings API and recommends Voyage AI, so `DENSE_EMBEDDER=voyage` with `VOYAGE_API_KEY` is the production path; `fake` is a deterministic stand-in for tests.
- **Storage:** vectors live per chunk and model (`chunk_embeddings`, migration 0010, RLS). On Postgres, `app.tools.pgvector_setup` adds `vector(dim)` with an HNSW index for in-database search (CI uses the pgvector image; Homebrew has no pgvector for Postgres 16, so that path is verified in CI only).
- **Fusion:** dense is a third RRF list at half weight. Coverage is still decided by the lexical signals, and dense joins the gate only after `evals.calibrate_dense` sets `DENSE_FOUND_THRESHOLD`.
- **Bug found and fixed:** the eval exposed that fusing a weak embedder could flip a found answer to not-found, because the answerability check only had signals for the top 6 lexical hits.
- **Still to run:** the P2 exit criterion "at least matching current evals" needs the real model: `python -m evals.run --dense voyage`.

### 52. Tables and formulas
Pages where plain extraction shreds a table (a run of very short lines) are re-read in pypdf layout mode. Table regions become pipe-delimited rows; formula lines stay on their own lines. The chunker never merges them into prose and splits long tables between rows with the header repeated. Vision-model transcription of figures and scanned tables stays a later option (OCR=vision, needs the key).

### 53. Graph quality gates, SLOs and query budgets
`evals/graph_eval.py --gate` runs in CI: merge precision 1.0, knowledge tracing beats the rules, and extraction quotes check out. It also reports concept recall and edge precision/recall against `evals/gold/graph.json`; the edge-precision gate (≥ 0.8) applies only with the real model, because the mock's edges are synthetic. `/api/metrics` (Prometheus text, `METRICS_TOKEN`) uses id-free labels; SLOs and burn-rate alerts are in `docs/slo.md` and `deploy/prometheus/alerts.yml`. Graph queries on a 2,000-concept graph take 1–30 ms against 150–600 ms budgets (test). The onboarding experiment report adds 7-day retention.

### 54. Shared taxonomy: not yet, and how it would work
Concepts, edges and links are private to each user (owner_id + RLS). A shared skill taxonomy (P3) would be a separate read-only table maintained by us, never written from user content. User concepts would link to it with `maps_to` edges in their own graph, so no user's material, names or mastery leak across accounts. Any aggregate built from user graphs (for example, common prerequisites) needs k-anonymity (at least 20 users per fact) and a privacy review first.

### Status (end of P2 build)
728 backend tests, Postgres 7/7 (+1 pgvector test that runs in CI), Redis 8/8, 19 e2e flows, eval gates (QA, adversarial, graph/mastery), `alembic check` clean, audits clean.
**Needs you for P2:** a Voyage AI key (then `evals.run --dense voyage` and `evals.calibrate_dense`); an Anthropic key (edge-precision gate on the real model, model judgements for merges and skill links); MFA (a Clerk dashboard setting); a penetration test before public launch; a data-protection compliance review.

## P3 Scale & expand (2026-10-24, branch `phase-3/expand`)

### 55. Role landing pages and shareable plans
`/roles/{slug}` (static, public) says what interviews for a role usually test and opens the gap report with a typical, illustrative ad pre-filled. Share links for a prep plan show only the role, interview date, plan steps and skill priorities: never the resume, job text, documents, answers or identity. Links expire after 30 days, can be revoked, and are limited to 5 per prep; only a SHA-256 of the token is stored, and public reads are rate-limited and run in the system context.

### 56. Voice mock interviews use the browser's speech features
No speech provider or key is needed. Questions are read aloud and spoken answers become editable text; the learner submits text as before. Feedback per answer covers time, pace and filler words. The page discloses that in Chrome and Edge speech recognition runs on the browser maker's servers. Typing always works, and speech errors never break the page. Dedicated speech models are a provider decision for later.

### 57. Notes-first answers (the token-saving chatbot)
`/api/notes/ask` and `/ask` try the cheap paths first:
1. Graph questions (mastery, prerequisites, which notes cover a topic) are answered from the database.
2. A repeat of a verified AI answer is reused only when every cited quote is still in its passage.
3. Lookups that the no-model coverage check rates confident get sentences quoted verbatim with pages.

Otherwise the passages are shown free with a token estimate, or a labelled general AI answer is offered; a model is called only when the learner chooses it. Planted instructions are never quoted. Eval gate in CI (`evals/notes_eval.py`): 61% of answerable questions are answered locally at 96% page precision, with 0 off-topic and 0 injection leaks. A savings meter shows answers and tokens saved.

### 58. More document formats
Word, text, Markdown and HTML are detected from content and converted to the same pages, chunks and citations as PDFs. Headings become sections and tables become rows; text is split into "pages" of about 3,000 characters so citations stay specific. Word files get zip-bomb limits, and unsupported types return 415 with a clear message.

### 59. Shared skill taxonomy
32 curated skills with aliases ship in the code (`app/data/taxonomy.json`); a test checks that no alias belongs to two skills. Users' concepts and job skills link to private taxonomy nodes in their own graph, per #54. `/api/me/skill-profile` and "Your skills" on Progress show, for each skill, its concepts, job skills, best mastery and the roles asking for it.

### 60. Workers scale out; periodic work elects a leader
`--concurrency N` runs jobs in parallel threads per process, and jobs already use SKIP LOCKED across processes. Stale-job recovery, emails and the retention purge run on one leader at a time using Postgres advisory locks. Production compose has worker replicas.

### 61. Push notifications through Expo
`push_tokens` (migration 0012) stores one row per device; a token moves to whoever signs in on that device. Reminders and the weekly summary go by email and/or push, at most once per day per kind under a single claim, counts only. Tokens Expo reports as `DeviceNotRegistered` are disabled. `PUSH_BACKEND=off|console|expo`. Real delivery needs an Expo project and a device build.

### 62. Mobile app: Expo SDK 57, not 58
SDK 58 needs react-native 0.88 and react-native-screens 4.30, both under two weeks old, so the app uses SDK 57 (react-native 0.86.3) with every dependency pinned to a release at least two weeks old.
- **Screens:** Today with working sessions (quizzes and interview answers open the web app), Ask my notes, Library, Prep, Settings with reminders and push.
- **Tests:** Jest unit tests, plus a CI job (typecheck, tests, web export). It was driven as a web build against a local API; native runs need an iOS simulator runtime.
- **Known findings:** `node-forge` and `zod` sit in Expo's command-line tool, which isn't shipped in the app; node-forge has no patched release, and Zod's fix is a new major version. `decode-uri-component` (via the router) is a moderate DoS on a crafted deep link; its fix changes module format and breaks the router. All clear with SDK 58 once it is two weeks old (around mid-November).

### 63. Security exception: Next.js 16.4.3 the day after release
Critical unauthenticated remote code execution (GHSA-2464-fhr4-w9xw, GHSA-673q-mjm6-r5xr) affected 16.0.0–16.4.0. A critical fix outranks the two-week rule; the web audit is now clean.

### Status (P3 build)
782 backend tests, Postgres 8/8 (+1 pgvector test in CI), Redis 8/8, 26 e2e flows, 4 mobile unit tests, all eval gates (QA, adversarial, graph/mastery, notes-first), `alembic check` clean, pip-audit and web npm audit clean.
**Needs you for P3:** coach/university pilot and partner content policy; institutional SSO (Clerk plan); SOC 2; read replicas, CDN and autoscaling (with hosting); dedicated speech models; an iOS simulator runtime for native mobile runs and mobile e2e; an Expo project for push delivery.

### 64. Brand: the "Mesh" design system replaces Aura
The teammate's landing page (Replit handoff, 2026-10-24; references in `docs/brand/`) set a new look, and the user chose it for the whole product: warm parchment (`#F5F2E9`), teal-charcoal ink, deep green (`#194D43`) for the one action per screen, muted coral (`#E78363`) for what needs attention; DM Sans for reading, Manrope for display, DM Mono for labels, self-hosted at build time by `next/font` (no request to Google from visitors). Only tokens and a few rules changed in `globals.css`, so every screen moved at once; legacy names (`--orange`, `--peach`, ...) are aliases. Contrast was checked for every text/background pair (rules at the top of `globals.css`): green carries `--on-green` text (9.0:1), coral carries ink (4.9:1), `--ink-2` never sits on sage (4.3:1). `mobile/src/theme.ts` mirrors it. Paper surfaces replace frosted glass, so "Reduce transparency" matters less but still works.

### 65. Public front page at /about; the signed-out home goes there
The landing page was rebuilt inside the Next.js app rather than kept as a separate Vite/pnpm site: one codebase, one deploy, and the e2e axe/keyboard/320px checks cover it. The Replit monorepo's Express/Drizzle packages duplicated the FastAPI backend and were not brought over. Signed-out visits to `/` go to `/about` (local auth: `Shell`; Clerk: `proxy.ts`). Honesty rules from the handoff kept: every illustration is labelled "Example", there is no mailing-list form (calls to action open real sign-up or the free gap report), no invented testimonials, and the copy keeps the knowledge-first order (Phase I is the product, career intelligence its application).

### 66. Knowledge map (`/map`, `GET /api/me/graph`)
The graph P1–P3 built is now drawn: concepts (merged ones folded in), prerequisite edges (dashed until grounded in a quote), mastery per concept, taxonomy skill, and the documents covering it with page and quote, so every node traces to a source. Read-only; nothing is inferred at view time. Capped at 150 concepts (max 400), best connected first, and the response says how many exist. The layout is a small deterministic force layout (`web/src/lib/graph-layout.ts`, no dependency, a few ms for 150 nodes): prerequisite springs, a pull toward each concept's main document, capped long-range repulsion, then turned to its long axis. Accessibility: every concept is a keyboard button whose name says its level in words, a List view gives the same content as text, and the map pans sideways on phones. "Ask your notes" is docked bottom-right (from the sketch) and uses the notes-first flow (#55-57), so opening it never calls the AI.

### 67. Notebook + Trail: the app's structure
The user weighed a "My Book" design (a book per goal, bookmark tabs, page turns) against "The Trail" (a gated journey Upload → Learn → Prove → Role gaps → Interview). Chosen: the Trail as structure, the book as texture.
- **One notebook per person**, not one per goal: knowledge is one mesh shared by every goal. Today is the cover: "<name>'s notebook", the active goal, the interview countdown, one "Continue where you left off" ribbon (the single primary action), a handwritten next-step note (Caveat; decorative, the words are plain text), and goals as bookmark tabs on the top edge.
- **The trail is progress, not a menu or a gate:** Learn (a usable document) → Practise (10 assessed answers) → Prove (3 strong concepts) → Interview (one finished mock). Every stop is a link at all times. Thresholds live in `services/journey.py` (`GET /api/me/journey`), which also picks the most recent unfinished thing for the ribbon: an open mock interview, study session or quiz, or the last document worked in.
- **Four places in the nav:** Today, Map, Library, Prep. Asking moved out of the tab bar into a dock on every screen (`AskDock`, notes-first, hidden where a screen has its own question box or a timed task) and into **⌘K** (`CommandBar`, a native `<dialog>`: screens, goals, documents, concepts, or "Ask your notes"). `/ask` remains as a full page.
- **Book texture only where it means something:** the reader and tutor form a two-page spread with a spine on wide screens; citations are margin notes. No page curls or page-turn animations.
- **First run:** `POST /api/documents/sample` adds a short original chapter (`app/data/sample-notebook.md`, "How Learning Sticks", whose ideas build on each other so the map has links) through the normal upload path. It is idempotent and deletable.

### Status (P4 brand + map)
787 backend tests (5 new), 29 e2e flows (3 new: front page, knowledge map, notebook cover; `/map` and `/about` added to the keyboard and 320px checks), 4 mobile tests, web and mobile typecheck clean.

### 68. Backend dependencies are locked
`requirements.txt` and `requirements-dev.txt` only set version ranges, so every Docker build used to install whatever was newest that day, which ignored the two-week rule and made builds unrepeatable. They stay as the ranges (what Dependabot edits); `requirements.lock` and `requirements-dev.lock` pin exact versions with hashes, generated by `backend/scripts/lock.sh` with `uv pip compile --universal --exclude-newer <14 days ago>`. The Dockerfile and CI install only from the locks, with `--require-hashes`.
- **Exceptions** (listed in the script): `anthropic==1.14.0` (14 Oct), because `ai/gateway.py` needs its server-side fallbacks and `output_config` (commit `64fa864`); `pillow>=13.0.0` (16 Oct), `pypdf>=6.21.2` (21 Oct) and `certifi>=2026.10.19` for security fixes that `pip-audit` flagged. A security fix outranks the two-week rule (as in #63).
- **Updating:** merge or edit a range, run `backend/scripts/lock.sh` (needs `uv`), run the tests, commit both files. A range Dependabot raises past the lock's cutoff fails to resolve until the release is two weeks old, which is the rule working.
- Web and mobile were already locked (`package-lock.json`). Still floating: the `python:3.12-slim` and Node base images; pin them by digest at the first deploy.

## Roadmap for the next slices

1. **First real run:** ✅ done in P0 (above), except `docker compose up`.
2. **Real-model eval:** tooling ✅ (`evals.make_gold`, `evals.compare_models`, adversarial set); run it with a key on 3–5 real PDFs, then tune prompts and answerability thresholds.
3. **Usability test:** kit ✅ (`docs/usability-test-kit.md`); run it on staging with 8–10 users.
4. **Production hardening:** ✅ Clerk sign-in (keys pending), ✅ Redis, ✅ email reminders and weekly summary, ✅ deploy kit; staging deploy pending a hosting choice.
5. **Mobile app (Expo)** reusing the design tokens (Aura, now Mesh #64); voice mock interviews once text practice is validated.
