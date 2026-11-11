# Assessment feature and completion checklist

**Snapshot date:** 2026-11-11  
**Purpose:** summarize the implemented UrbanNest CRM, identify remaining work
for assessment completion, and separate optional bonus ideas from required
acceptance checks. This describes the repository; it does not certify the
deployed environment or an external assessment submission.

## Implemented features

### Backend and data

- FastAPI API with versioned `/api/v1` routes, OpenAPI documentation, health
  endpoint, startup configuration/database checks, and automatic Alembic
  migration upgrade.
- PostgreSQL-backed teams, users, leads, activities, follow-up tasks, AI score
  history, message drafts, audit events, rate-limit counters, and AI usage
  metadata.
- Password-hash authentication, bearer access tokens, active-account checks,
  rate-limited login, profile and password change, administrator-issued
  password resets, one-time temporary passwords, and forced password changes.
- Server-enforced team and record access for agents, managers, owners, and
  co-owners. Co-owner read/write/delete and user-management switches are
  owner-configurable. The development superuser bootstrap is opt-in and
  refuses to run outside `APP_ENV=development`.
- Lead creation, filtering, search, pipeline updates, details, assignment,
  activity timelines, CSV import with row-level results, and public lead intake
  with shared rate limiting.
- Follow-up creation, assignment, status changes, due-today/overdue filtering,
  and dashboard summaries. Task responses now include the assignee's display
  name so team-wide viewers can see who owns each follow-up.
- Shared, role-filtered audit feed and unread/read cursor behavior.
- Backend AI endpoints for lead scoring, unsent message drafting, and
  notes-to-structured-data proposals. AI context is access-scoped and
  minimized; output is validated and usage metadata is recorded.
- Fictional seed data for demo users, leads, activities, and follow-ups, plus a
  password-rotation script that recognizes the seeded account set.

### Frontend

- React/TypeScript CRM with login, required password changes, profile
  management, team administration, role/permission controls, and confirmations
  for consequential account changes.
- Role-scoped dashboard, lead list/details, activity, pipeline, follow-up and
  team views; search, filters, import workflow, and shared activity feed.
- Follow-up displays show the actual assignee rather than labeling all tasks
  “Assigned to you.”
- UI includes private-route no-index metadata and browser preference storage.
  The bearer token is held in tab-scoped `sessionStorage`.

## Required assessment completion work

These are remaining integration or evidence tasks, not claims that the APIs do
not exist.

1. **Connect the frontend to AI A1–A3.** The lead-detail AI controls are
   currently a disabled preview. Wire them to scoring, drafting, and extraction
   endpoints; show loading/provider errors; render saved score/stale state;
   allow editing drafts; and require user confirmation before saving extracted
   fields or a proposed task. Never imply a draft was sent.
2. **Finish public lead capture UX.** The public API endpoint exists, but the
   CRM frontend is not a public inquiry page. Add a responsive public form,
   validation and success/error states, and verify it creates a lead only in
   the configured team without exposing CRM data.
3. **Prove the full role journeys.** Demonstrate agent, manager, owner, and
   configured co-owner behavior, including cross-team denial, lead/task
   assignment, account provisioning, permission switches, password change,
   and reset. Verify the development superuser only in a development
   environment.
4. **Complete end-to-end checks.** Exercise lead creation through activity,
   task, completion, CSV import errors, public intake, audit notification, and
   AI failures against a clean migrated database and the deployed API.
5. **Verify product quality against the assessment plan.** Check responsive
   mobile/desktop layouts, keyboard/focus behavior, loading/empty/error states,
   site-visit context, source attribution, and confirmation on destructive or
   security-sensitive actions.
6. **Review cache and freshness behavior.** The app currently refreshes
   server-state through its API client and cancels stale refresh requests; it
   does not use a dedicated query-cache library. Confirm cache invalidation (or
   the existing refresh equivalent) after each lead, task, import, and AI
   mutation, and clear all user-scoped data on logout/account switch.
7. **Verify deployment and demo handoff.** Confirm the live frontend origin in
   CORS, database connectivity and migration head, production secrets and AI
   provider configuration, seeded fictional demo accounts, and a clean login
   walkthrough. Keep credentials private and do not use real client data.
8. **Capture acceptance evidence.** Record the live URLs, supported demo
   accounts/roles without exposing passwords in source control, test/build
   results, and a short demonstration showing the core workflows and
   authorization boundaries.

## Optional bonus features

Only start these after the required flows above pass:

- A restricted AI sales assistant using explicitly allowlisted, authorized
  query functions. Never execute model-generated SQL.
- A weekly team report generated from authorized real aggregates, with a
  transparent AI narrative and clear provider-failure handling.
- Duplicate-lead detection with human review before merging.
- Next-best-action suggestions grounded in a lead's authorized timeline.
- Multilingual message drafts, reviewed by the user before copying or sending.
- Real WhatsApp/email/portal integrations only when configured and tested with
  an actual provider. Until then, label drafts as drafts and sources as
  attribution; do not imply a message was sent or a portal was synchronized.

## Current local validation

The latest role and follow-up-assignee work passed the focused backend API
test and the complete backend test suite. The frontend production build, lint,
and `git diff --check` also passed. Repeat these checks after any further
assessment changes:

```powershell
Set-Location backend
$env:PYTHONPATH = "."
python -m unittest discover -s tests -v
```

Then run the frontend checks:

```powershell
Set-Location frontend
npm run build
npm run lint
```
