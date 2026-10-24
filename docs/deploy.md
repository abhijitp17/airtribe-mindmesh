# Deploying Mindmesh

Provider-neutral: any host that runs containers (a VM with Docker, Fly.io, Render, AWS ECS...).
Managed Postgres 16 + Redis are fine instead of the compose `db`/`redis` services.

## 1. Secrets and settings (`.env`, never committed)
| Setting | Notes |
|---|---|
| `JWT_SECRET` | Only with `AUTH_PROVIDER=local`. Long random string. |
| `AUTH_PROVIDER=clerk`, `CLERK_*` | Production Clerk instance: own domain, own Google + LinkedIn OAuth apps (see the Wave 2 checklist), `CLERK_AUTHORIZED_PARTIES=https://app.<domain>`, webhook to `https://api.<domain>/api/webhooks/clerk`. |
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | Build-time for the web image. |
| `ANTHROPIC_API_KEY` | Model choice only after `python -m evals.compare_models` says so. |
| `WEB_URL`, `API_PUBLIC_URL` | `https://app.<domain>`, `https://api.<domain>`: CORS, email links, web build. |
| `EMAIL_BACKEND=smtp`, `SMTP_*`, `EMAIL_FROM`, `EMAIL_TOKEN_SECRET` | Any SMTP provider. Set SPF/DKIM/DMARC for the sending domain. |
| `SENTRY_DSN` | Optional error tracking (no user content is sent). |
| `UPLOAD_SCAN=clamd`, `CLAMD_HOST` | Optional; uploads are refused if clamd is down. |
| `DB_POOL_SIZE` x `API_WORKERS` x replicas | Must stay under Postgres `max_connections`. |

## 2. First deploy
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```
`migrate` runs Alembic and row-level security, then `api` (checked by `/api/health/ready`),
`worker` (jobs + reminder emails) and `web` start. Put TLS in front (Caddy/nginx/platform LB):
`app.<domain>` -> web:3000, `api.<domain>` -> api:8000.

With managed Postgres: create a non-superuser owner role first (`backend/sql/init/01-app-role.sql`
shows how) and point `DATABASE_URL` at it. Superusers bypass row-level security.

## 3. Every release
Tag `vX.Y.Z` -> `.github/workflows/release.yml` publishes `ghcr.io/<repo>/api` and `/web`.
Pull the new tags and restart; `migrate` applies new migrations first.

## 4. Checks after deploy
- `GET /api/health/ready` -> 200 with `database: ok`, `redis: ok`.
- Sign up, upload a PDF, ask a question, take a quiz (or run the Playwright suite against the URL).
- `python -m app.tools.cost_report --days 1` and `python -m app.tools.flag_report --days 7` (inside the api container).

## 5. Backups and restore
Daily Postgres backups (managed service, or `pg_dump` from cron) and the `uploads` volume (or
object storage). Test a restore before the beta. Account deletion removes rows and files;
backups age out per the retention policy (docs/legal/retention-policy.md).

## Not verified yet
`docker compose up` has not been run on this project (no Docker on the dev machine) and the
GitHub workflows have not run (no remote). Do both on the first staging deploy.
