-- Administrative one-shot after migrations; no password appears in this file.
\getenv runtime_password PULSE_RUNTIME_PASSWORD
BEGIN;
SELECT 'CREATE ROLE pulse_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pulse_runtime')
\gexec
ALTER ROLE pulse_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD :'runtime_password';
GRANT pulse_runtime TO pulse;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO pulse_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO pulse_runtime;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO pulse_runtime;
-- An application login must never migrate, change history or alter its own grants.
REVOKE ALL ON django_migrations FROM pulse_runtime;
GRANT SELECT ON django_migrations TO pulse_runtime;
REVOKE UPDATE, DELETE, TRUNCATE ON
    core_identityevent, tickets_auditevent, tickets_ticketevent, tickets_comment,
    tickets_reopenpolicy, tickets_attachmentscan, tickets_idempotencyrecord
FROM pulse_runtime;
COMMIT;
