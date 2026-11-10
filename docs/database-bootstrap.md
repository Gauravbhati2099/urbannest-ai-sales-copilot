# Database bootstrap plan

## Scope

Create the initial PostgreSQL schema from the finalized SQLAlchemy ORM, then add fictional UrbanNest demo data. Before migration, the hosted database contained only Alembic's empty version table and zero application tables.

## Execution order and gates

1. **Load configuration safely**
   - Read `backend/.env` locally; never print or commit it.
   - Normalize PostgreSQL URLs to the installed Psycopg 3 dialect in code, without rewriting the user's URL.
   - Use SQLAlchemy pool settings from environment configuration.
2. **Generate the initial Alembic revision**
   - Autogenerate from `Base.metadata`.
   - Review all eight tables, primary/unique/foreign keys, check constraints, enum checks, indexes, nullable public/system actors, and PostgreSQL JSONB.
   - Confirm there are no `DROP` operations or unrelated database objects.
3. **Apply the initial migration** — complete
   - Verify the target is still the expected empty hosted database.
   - Apply the initial revision only; do not drop schemas or existing objects.
   - Revision `d943dc36f66f` applied; all eight application tables were verified.
   - `alembic check` reports no schema differences from the ORM.
4. **Seed demo data** — complete
   - Run an idempotent seed script: one UrbanNest team, one owner, two managers, twelve agents, 50 fictional leads, timeline activities, and assigned tasks with overdue/today/upcoming examples.
   - Use `.invalid` email addresses and no real contact details.
   - Seeded 1 team, 15 users, 50 leads, 50 activities, and 50 tasks. No AI scores/messages/usage rows are fabricated.
   - All 15 passwords are Argon2 hashes. A random shared demo password was printed once after commit; passwords are not written to source files.
   - Re-running the seed adds no duplicate team, accounts, leads, activities, or tasks.
5. **Verify** — complete
   - Query table and seeded-record counts.
   - Confirm generated accounts have role values and password hashes, not plaintext passwords.
   - Re-run the local ORM integrity tests.

## Safety boundaries

- Never print a database URL, JWT secret, or API key. The seed command prints its generated, temporary demo password once after the transaction commits.
- Never run `drop`, schema reset, or destructive migration operations.
- If the hosted database is no longer empty, stop and inspect before applying the initial revision.
- The seed dataset is synthetic assessment data only.
- Generated demo passwords are temporary credentials; rotate them before any public or shared use.
