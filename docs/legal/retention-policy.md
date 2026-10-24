# Data retention (DRAFT, needs legal review)

| Data | Kept | How it ends |
|---|---|---|
| Account, documents, files, extracted text, tutor history, quizzes, preps, plans, sessions, reports | Until you delete them or your account | Deleting an account removes rows (database cascade) and stored files at once |
| Sign-in identity (Clerk) | Until account deletion | Deleted through Clerk's API by a queued job (retried until it succeeds) |
| Signed-out gap reports | Up to 30 minutes | Expire automatically (Redis TTL / in-memory) unless claimed at sign-up |
| Reminder email log (kind + date) | [DECISION: e.g. 90 days] (at least 8 days) | Hourly purge job: `RETENTION_EMAIL_LOG_DAYS` |
| AI usage records (task, model, token counts; no content) | [DECISION: e.g. 13 months, for cost and abuse limits] (at least 2 days) | Hourly purge job: `RETENTION_USAGE_DAYS` |
| Product events (event names and counts, e.g. "uploaded a document"; no content) | [DECISION: e.g. 13 months] | Hourly purge job: `RETENTION_EVENTS_DAYS` |
| Finished background jobs (ids only, e.g. a document id or a deleted account's sign-in id) | 30 days [CHECK] | Hourly purge job: `RETENTION_JOBS_DAYS` |
| Application logs (request ID, path, status, timing; no bodies or query strings) | [DECISION: e.g. 30 days] | Log platform retention setting |
| Error reports (no request bodies, local variables, cookies or auth headers) | [DECISION: e.g. 30-90 days] | Error-tracker retention setting |
| Database and file backups | [DECISION: e.g. 30 days] | Rolling expiry; deleted accounts disappear from backups when they age out |
| Data at subprocessors | Per each contract (see `subprocessors.md`) | [CHECK each provider's deletion terms] |

Engineering: the purge jobs are built (`backend/app/services/retention.py`). Until a period is
decided its setting is 0, which keeps everything; set the `RETENTION_*_DAYS` values once the
[DECISION]s are made. `python -m app.tools.purge --dry-run` shows what a setting would delete.
