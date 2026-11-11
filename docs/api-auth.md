# Authentication and scoped API contract

For a frontend-oriented account lifecycle diagram and details on token,
password, profile, audit, and AI data handling, see
[Authentication flow and user-data handling](./authentication-and-data.md).

The FastAPI application is started from the `backend` directory with:

```powershell
..\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Run the backend tests from the same directory with:

```powershell
$env:PYTHONPATH = "."
..\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

OpenAPI documentation is available at `/docs`; `/health` is a public process
liveness check. Authenticated requests use `Authorization: Bearer <access_token>`.
Login accepts JSON and returns an access token plus the public user profile.
Tokens contain only the user ID and standard access-token metadata. Every
authenticated request reloads the user from the database, so role/team claims
from a browser are never trusted and deactivated accounts are rejected.

## Endpoints

| Method | Path | Access / behavior |
|---|---|---|
| `POST` | `/api/v1/auth/login` | Public; email/password login |
| `GET` | `/api/v1/auth/me` | Authenticated user's current profile, email, optional phone, and role |
| `PATCH` | `/api/v1/auth/me/profile` | Authenticated user updates or clears their own optional phone number |
| `POST` | `/api/v1/auth/change-password` | Authenticated; verifies current password, changes password and invalidates prior tokens |
| `GET` | `/api/v1/users` | Owner/manager team roster; manager sees agents only; supports pagination and active filter |
| `POST` | `/api/v1/users` | Owner can provision team roles; manager can provision agents; returns one-time temporary password |
| `PATCH` | `/api/v1/users/{user_id}` | Owner can change roles/status; manager can update/deactivate agents only |
| `POST` | `/api/v1/users/{user_id}/password-reset` | Owner/manager issues one-time temporary password; all existing sessions are revoked |
| `POST` | `/api/v1/users/password-reset-all` | Owner only; requires `{"confirmation":"RESET ALL"}`, resets every team account (including inactive and owner accounts), and returns a no-store CSV with one-time temporary passwords and roles |
| `GET` | `/api/v1/audit/events` | Paginated shared audit feed; event visibility is filtered by role and accessible leads |
| `GET` | `/api/v1/audit/unread-count` | Current user's unread count within their authorized audit feed |
| `POST` | `/api/v1/audit/read` | Moves only the caller's read cursor; audit events remain shared |
| `GET` | `/api/v1/audit/stream` | Authenticated Server-Sent Events stream backed by PostgreSQL `LISTEN/NOTIFY` |
| `GET` | `/api/v1/leads` | Team-scoped; filters: `status`, `source`, `assigned_to`, `q`, `location`, budget range; agents see assigned leads |
| `POST` | `/api/v1/leads` | Authenticated lead creation; an agent's lead is assigned to that agent |
| `GET` | `/api/v1/leads/{lead_id}` | Same record visibility as the lead list; inaccessible IDs return `404` |
| `PATCH` | `/api/v1/leads/{lead_id}` | Visible lead only; managers/owners may reassign within the active team |
| `GET` | `/api/v1/leads/{lead_id}/activities` | Timeline only for a visible lead |
| `POST` | `/api/v1/leads/{lead_id}/activities` | Adds an authenticated actor's timeline entry and marks existing scores stale |
| `POST` | `/api/v1/leads/import` | UTF-8 CSV upload; manager/owner only; at most 2 MB / 500 rows; returns row-level errors |
| `POST` | `/api/v1/public/leads` | Public website lead form; team comes from `PUBLIC_LEAD_TEAM_ID`; shared PostgreSQL rate-limited |
| `GET` | `/api/v1/leads/{lead_id}/ai/score` | Latest visible lead score, including stale state; returns `null` before scoring |
| `POST` | `/api/v1/leads/{lead_id}/ai/score` | Scores a visible lead, stores structured score history and usage metadata |
| `POST` | `/api/v1/leads/{lead_id}/ai/draft` | Drafts a visible lead's follow-up; saves as an editable `draft`, never sends |
| `POST` | `/api/v1/leads/{lead_id}/ai/extract` | Returns validated proposed property/task fields for user confirmation; does not save them |
| `GET` | `/api/v1/dashboard/summary` | Role-scoped pipeline totals, open-task counts, and due-today/overdue task lists |
| `GET` | `/api/v1/tasks` | Managers/owners see team tasks; agents see tasks on their assigned leads; defaults to `status=open`; supports `status=open\|completed\|cancelled` and timezone-aware `due=today\|overdue` filters |
| `GET` | `/api/v1/tasks/{task_id}` | Returns a task only when the caller can access its lead and task assignment |
| `POST` | `/api/v1/tasks` | Creates a task for a visible lead; assignee must be active and in the same team |
| `PATCH` | `/api/v1/tasks/{task_id}` | Managers/owners may update/reassign team tasks; agents may update their own assigned tasks |

Lead and task lists are paginated with `limit` (1–100) and `offset` query
parameters. Clients must not send `team_id`, `created_by`, `actor_id`, or role
as authority; the backend derives these from the authenticated user. Record
lookups are filtered by team and, for agents, assignment before returning a
result. Status and assignment changes create timeline activities in the same
transaction. Changes to score-relevant lead fields and new activities mark
existing lead scores stale transactionally. Task due filters apply only to
open tasks; combine `due=today` or `due=overdue` with the default status or
`status=open`.

## Roles

- **Agent:** reads assigned leads and their timelines; can create leads assigned
  to self; cannot reassign leads; can create tasks on accessible leads and
  update tasks assigned to self.
- **Manager:** reads and updates leads and tasks in their team; can assign leads
  and task ownership to active same-team users.
- **Owner:** same team-wide record access and assignment capabilities as a
  manager. Cross-team records are never exposed.

## User provisioning and password recovery

There is no public registration. Owners can provision team users, including
managers and agents; managers can provision agents only. Only owners can change
roles. Managers can update or deactivate agent accounts, but cannot manage
owners or other managers. User-management routes never accept a team ID from
the client; accounts are created in the acting administrator's team.
Provisioning validates and normalizes names and email addresses, accepts only
the defined roles, and rejects unexpected request fields. Invalid or expired
bearer tokens are rejected with `401`; an identifier such as
`PUBLIC_LEAD_TEAM_ID` is configuration, not an authentication credential.

New accounts and administrative password resets receive a randomly generated
temporary password in the response exactly once and must change it before
accessing CRM data. `POST /api/v1/auth/change-password` verifies the current
password, enforces a 12-character minimum, and returns a replacement access
token. Password reset, password change, role changes, and deactivation revoke
previous access tokens. The API prevents deactivating or demoting the team's
last active owner. Passwords are hashed with Argon2; store temporary
credentials securely and do not send them over an untrusted channel.
The frontend requires explicit confirmation before account creation, password
changes/resets, role changes, and account activation/deactivation; these
prompts supplement but do not replace backend authorization.

The owner-only bulk reset endpoint is intentionally destructive: it rotates
credentials and invalidates sessions for every account in the owner's team.
The response contains newly generated temporary passwords exactly once; it
never returns existing passwords. The frontend requires confirmation, downloads
the CSV without storing it in the application, and signs the owner out. Keep
the downloaded file private, distribute credentials securely, and delete the
file when it is no longer needed. Each user must change their temporary
password before using CRM data.

The assessment has no email provider configured, so self-service email reset
links are not available. This admin-issued reset is the recovery path.

## Shared audit feed and notifications

Each change creates one `audit_events` row for the team. Events are not
duplicated per user. `audit_read_cursors` stores at most one read timestamp per
user; marking events read changes that cursor, not the shared event rows.

- Owners and managers can see all events in their team.
- Agents can see team events without a lead association, events for leads
  currently assigned to them, and their own actor-only events.
- Agent account/security changes are admin-only; owners and managers can see
  them. Team-wide items such as a new public website inquiry are shared with
  all team members without exposing lead contact data.
- Audit change data omits lead contact details, notes, task descriptions, and
  passwords. It records only safe fields needed to understand the change.

Use `GET /api/v1/audit/events` to load or refresh the authorized feed. The
`unread_count` in the response is scoped to the same visible events. Call
`POST /api/v1/audit/read` to mark the caller's visible feed read. To receive
live invalidations, connect to `/api/v1/audit/stream` with the normal bearer
token and handle `audit` events; each message contains an event ID, after which
the client should refresh the feed. An `audit-sync` event is sent on connect so
the client can fetch an initial/current feed after subscribing. PostgreSQL
`NOTIFY` is transactional, so
clients are notified only after the event transaction commits. The stream
rechecks event visibility and closes when the user's account is deactivated
or its authentication version changes. Each active stream uses one dedicated
PostgreSQL connection; close streams when the client no longer needs updates.
Because browser `EventSource` cannot set an `Authorization` header, a bearer
token client should consume this SSE endpoint through `fetch` and a streaming
response reader (or use an authenticated same-site cookie strategy).

## Rate limiting and connection limits

The app uses shared PostgreSQL fixed-window counters, so limits are consistent
across workers and instances without Redis. Counter keys are HMACed with the
JWT secret; raw email addresses and IP addresses are not stored in the
rate-limit table. A 429 response includes `Retry-After`.

Defaults, configurable through environment variables and listed in
`backend/.env.example`:

- Login: 30 attempts per client IP and 10 attempts per normalized email per
  15-minute window. Attempts count regardless of outcome; a successful login
  clears only that email's counters.
- Public lead intake: 10 requests per client IP per 10-minute window.
- Audit SSE: at most 2 streams per user and 10 streams globally. PostgreSQL
  advisory locks release automatically when a stream connection closes or
  drops.

Set `PUBLIC_LEAD_TEAM_ID` to the intended team's UUID before enabling public
intake; the endpoint returns `503` if it is missing or invalid. Public intake
creates an unassigned website lead and a system-authored timeline item.
PostgreSQL counters provide distributed app-level protection for
`/api/v1/auth/login` and `/api/v1/public/leads`. A separate gateway was not
configured because this deployment is currently Render-only. If one is added,
it must forward the client address only from trusted proxy hops, and
Uvicorn/platform proxy-header trust must be restricted to known proxy IPs. The
app deliberately does not trust arbitrary `X-Forwarded-For` values.

`APP_TIMEZONE` defaults to `Asia/Kolkata` and controls due-today/overdue
boundaries; timestamps remain stored in UTC. AI provider selection is server
side via `AI_PROVIDER=gemini|ollama`; provider credentials and model settings
are never returned from the API. AI context excludes lead email/phone and
redacts contact details in notes and activity text; AI prompts and completions
are not stored. `ai_usage` stores provider/model, feature, token counts,
latency, outcome, and a request ID. AI-generated output is schema-validated.
Extraction is a proposal only; message drafting does not send anything.

The API currently has no public account registration, email-based password
reset, refresh-token, or logout endpoint. Use a random `JWT_SECRET_KEY` of at
least 32 bytes and keep it server-side; changing that key invalidates existing
tokens. Access-token lifetimes are configured by
`ACCESS_TOKEN_EXPIRE_MINUTES` (5–1440 minutes; default 60). Distributed application rate limits are enabled. With the current Render-only
deployment, these are enforced by the API against shared PostgreSQL counters;
no separate pre-app gateway rule is configured in this repository. Add a
gateway that supports per-path limits if an additional edge layer is required.

There is currently no frontend application in this workspace, so frontend
integration is pending the teammate's app/repository. The endpoints above and
`/docs` are the API handoff contract.
