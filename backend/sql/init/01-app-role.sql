-- Runs once, on first start of the docker compose db (docker-entrypoint-initdb.d),
-- as the image's superuser (POSTGRES_USER) on POSTGRES_DB.
--
-- The api and worker must NOT connect as that superuser: superusers bypass row-level
-- security, which would turn every policy in sql/rls.sql into a no-op. They connect as
-- mindmesh_app instead, an ordinary role that owns the schema (so create_all / Alembic
-- can create tables, and FORCE ROW LEVEL SECURITY applies to it as table owner).
-- tests/test_postgres_rls.py fails if the app role can bypass RLS.

CREATE ROLE mindmesh_app LOGIN PASSWORD 'mindmesh_app'
    NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;

GRANT CONNECT, TEMPORARY ON DATABASE mindmesh TO mindmesh_app;
ALTER SCHEMA public OWNER TO mindmesh_app;

-- Extensions need the superuser; pgvector is used from P2 (semantic retrieval).
CREATE EXTENSION IF NOT EXISTS vector;
