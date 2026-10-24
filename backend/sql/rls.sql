-- Mindmesh Postgres row-level security (workstream F). Idempotent: safe to re-run.
--
--   psql "$DATABASE_URL" -f sql/rls.sql        (after `alembic upgrade head`)
--
-- WHAT IT DOES
--   Every table in the current schema with an owner_id column gets
--   ENABLE + FORCE ROW LEVEL SECURITY and the policy
--       owner_id = current_setting('app.user_id', true)
--   FORCE makes the policy apply even to the table owner (the app's DB role),
--   so a query that forgets `WHERE owner_id = :me` returns nothing instead of
--   other users' rows. This is defence in depth: the app's explicit owner_id
--   filters stay the primary control (CONTRACTS §0).
--
-- HOW THE APP SETS app.user_id (per transaction, pool-safe)
--   An SQLAlchemy `after_begin` session event runs
--       SELECT set_config('app.user_id', :uid, true)
--   at the start of every transaction, using session.info["user_id"], which
--   deps.current_user sets right after the bearer token is verified and BEFORE
--   its first query (so the very first transaction is already scoped). The
--   third argument `true` is SET LOCAL semantics: the value disappears at
--   COMMIT / ROLLBACK, so a pooled connection never leaks one user's id to the
--   next request. The hook re-runs after every commit (new transaction). With
--   no id set, current_setting(..., true) is NULL/'' and no row matches
--   (fail closed).
--
-- SYSTEM WORK (ingestion, job worker)
--   Background jobs have no request user. app.jobs runs every handler inside
--   jobs.system_context() (a contextvar); when it is active the same hook runs
--       SELECT set_config('app.rls_bypass', 'on', true)
--   which the second (permissive) policy below honours. Only trusted server
--   code sets it; user input never reaches set_config names.
--   Stricter alternative: run worker.py as a separate role with BYPASSRLS
--   (see mindmesh_admin below) and drop the mindmesh_system policy.
--
-- NOT COVERED
--   * users: login/signup must look a user up by email before any id is known.
--     Protected by the app (only /auth/me exposes it). Not RLS'd.
--   * jobs: system table with no owner_id; payloads hold ids only.
--   * Foreign-key cascades (DELETE /auth/me) bypass RLS by design in Postgres,
--     so account deletion still removes every child row.
--
-- ADMIN / OPERATIONS ROLE
--   Use a separate, non-owner role for support and maintenance so humans never
--   use the app role. BYPASSRLS needs a superuser to grant:
--
--     CREATE ROLE mindmesh_admin NOLOGIN BYPASSRLS;
--     GRANT USAGE ON SCHEMA public TO mindmesh_admin;
--     GRANT SELECT ON ALL TABLES IN SCHEMA public TO mindmesh_admin;
--     GRANT mindmesh_admin TO <named human login>;   -- audited, per person
--
--   Migrations (alembic) run as the table owner. DDL is unaffected by RLS.

DO $$
DECLARE
    t record;
BEGIN
    FOR t IN
        SELECT c.table_schema, c.table_name
        FROM information_schema.columns c
        JOIN information_schema.tables tb
          ON tb.table_schema = c.table_schema AND tb.table_name = c.table_name
        WHERE c.column_name = 'owner_id'
          AND c.table_schema = current_schema()
          AND tb.table_type = 'BASE TABLE'
        ORDER BY c.table_name
    LOOP
        EXECUTE format('ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY', t.table_schema, t.table_name);
        EXECUTE format('ALTER TABLE %I.%I FORCE ROW LEVEL SECURITY', t.table_schema, t.table_name);

        EXECUTE format('DROP POLICY IF EXISTS mindmesh_owner ON %I.%I', t.table_schema, t.table_name);
        EXECUTE format(
            'CREATE POLICY mindmesh_owner ON %I.%I AS PERMISSIVE FOR ALL '
            'USING (owner_id = current_setting(''app.user_id'', true)) '
            'WITH CHECK (owner_id = current_setting(''app.user_id'', true))',
            t.table_schema, t.table_name);

        EXECUTE format('DROP POLICY IF EXISTS mindmesh_system ON %I.%I', t.table_schema, t.table_name);
        EXECUTE format(
            'CREATE POLICY mindmesh_system ON %I.%I AS PERMISSIVE FOR ALL '
            'USING (current_setting(''app.rls_bypass'', true) = ''on'') '
            'WITH CHECK (current_setting(''app.rls_bypass'', true) = ''on'')',
            t.table_schema, t.table_name);

        RAISE NOTICE 'RLS enabled on %.%', t.table_schema, t.table_name;
    END LOOP;
END
$$;

-- Tables expected today (for review; the loop above is authoritative):
--   documents, chunks, chat_messages, quizzes, questions, attempts, usage_events,
--   resume_profiles, job_profiles, role_preps, skill_matches, interview_sessions,
--   interview_turns, goals, plan_items, plan_proposals,
--   user_prefs (owner_id is its primary key; same policy applies), study_sessions, interview_debriefs
--
-- Verify:
--   SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class
--   WHERE relkind = 'r' AND relnamespace = current_schema()::regnamespace ORDER BY 1;
--
-- Roll back (emergency):
--   ALTER TABLE <t> NO FORCE ROW LEVEL SECURITY; ALTER TABLE <t> DISABLE ROW LEVEL SECURITY;
