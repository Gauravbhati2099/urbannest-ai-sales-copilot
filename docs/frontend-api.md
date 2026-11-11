# Frontend API guide

This guide describes the HTTP API exposed by the UrbanNest backend for the CRM
frontend. The interactive OpenAPI reference is available at `/docs` on a
running backend.

## Connection and authentication

The API prefix defaults to `/api/v1` (configurable with `API_V1_PREFIX`).
Configure the frontend's `VITE_API_BASE_URL` as the backend origin, without the
`/api/v1` suffix. For local development, the API normally runs at
`http://127.0.0.1:8000`.

All endpoints require `Authorization: Bearer <access_token>` except
`POST /api/v1/auth/login`, `POST /api/v1/public/leads`, and `GET /health`.
Send JSON requests with `Content-Type: application/json`. UUIDs use their
standard string form and timestamps use ISO 8601; timestamps submitted for
tasks or activities must include a timezone.

Login returns an access token and `expires_in` in seconds. Keep the token in
session storage and send it as a bearer token on authenticated requests. A
temporary account password requires the user to call the password-change
endpoint before accessing other CRM routes. Changing a password returns a new
token; changing an account's role or deactivating it revokes its existing
tokens.

### Roles and visibility

- **Owner:** access to all leads, tasks, team members, and team administration.
- **Manager:** access to all team leads and tasks, and management of agent
  accounts; managers cannot view or manage owners or other managers through
  user administration.
- **Agent:** access only to assigned leads and their related tasks. An agent
  may create or update tasks only for themselves and cannot reassign leads.
- Public lead submission is unauthenticated and is accepted only when the
  backend's `PUBLIC_LEAD_TEAM_ID` is configured.

### Common responses

Successful requests use the response shape listed below. Errors use JSON with a
`detail` field unless the endpoint returns a CSV file or a streaming response.

| Status | Meaning |
|---|---|
| 400 | Request cannot be processed, such as an incorrect current password. |
| 401 | Missing/invalid bearer token or invalid login credentials. |
| 403 | Authenticated user lacks the required role or permission. |
| 404 | Resource does not exist or is outside the caller's visibility. |
| 409 | Conflict, such as a duplicate email or an account-state restriction. |
| 413 | CSV exceeds the supported size or row limit. |
| 415 | CSV upload has an unsupported media type. |
| 422 | Invalid input, unsupported filter combination, or rate limit exceeded
  (login/public intake use 429 instead). |
| 429 | Login/public intake or live audit stream has reached its limit. A
  `Retry-After` header may be present. |
| 503 | Public intake is not configured, AI is unavailable, or a backend service
  is unavailable. |

Validation errors generally use FastAPI's standard `{"detail": [...]}` response.
Do not treat every `fetch` network failure as a CORS configuration issue: a
server error or unavailable API can also prevent the browser from reading the
response.

## Authentication and account endpoints

| Method and path | Access | Purpose and response |
|---|---|---|
| `POST /api/v1/auth/login` | Public | Authenticate and return `LoginResponse`. |
| `POST /api/v1/auth/change-password` | Authenticated | Change your password and return a replacement `LoginResponse`. |
| `GET /api/v1/auth/me` | Authenticated | Return the current `UserRead`. |
| `PATCH /api/v1/auth/me/profile` | Authenticated | Update your own profile; currently supports `phone`. |
| `GET /api/v1/users` | Owner, manager | List team accounts. Managers see agents only. |
| `POST /api/v1/users` | Owner, manager | Create an account and return its one-time temporary password. Managers can create agents only. |
| `PATCH /api/v1/users/{user_id}` | Owner, manager | Update a managed user's name, role, or active status. |
| `POST /api/v1/users/{user_id}/password-reset` | Owner, manager | Reset a managed user's password and return the temporary password. |
| `POST /api/v1/users/password-reset-all` | Owner | Reset every account in the team and download a CSV of temporary passwords. |

### Login request

```json
{
  "email": "agent@example.com",
  "password": "your-password"
}
```

Email is trimmed and lowercased. On success, the response contains
`access_token`, `token_type`, `expires_in`, and `user`. An incorrect email or
password returns 401. Repeated attempts can return 429.

### Password change request

```json
{
  "current_password": "current-password",
  "new_password": "a-new-password-at-least-12-characters"
}
```

The new password must be 12-128 characters, non-blank, and different from the
current password. A successful response has the same shape as login and
contains the replacement token.

### User fields and filters

`UserRead` contains `id`, `team_id`, `full_name`, `email`, `phone`, `role`,
`is_active`, and `must_change_password`. Password hashes are never returned.

`GET /api/v1/users` accepts `limit` (1-100, default 50), `offset` (default 0),
and optional `is_active` (`true` or `false`).

Create a user with `full_name`, `email`, and `role` (`owner`, `manager`, or
`agent`). `PATCH /api/v1/users/{user_id}` accepts one or more of `full_name`,
`role`, and `is_active`. Omit fields that should not change. Managers may not
change roles. The team must retain an active owner, and an owner cannot
deactivate themselves.

For bulk reset, submit `{"confirmation":"RESET ALL"}`. The response is a
`text/csv` attachment named `urbannest-password-resets.csv`; it contains
temporary passwords and must be kept private. The operation revokes existing
sessions and requires users to change their temporary passwords.

## Leads and activities

| Method and path | Access | Purpose and response |
|---|---|---|
| `GET /api/v1/leads` | Authenticated | List visible leads with pagination and optional filters. |
| `POST /api/v1/leads` | Authenticated | Create a lead; returns `LeadRead` with status 201. |
| `GET /api/v1/leads/{lead_id}` | Authenticated | Read one visible lead. |
| `PATCH /api/v1/leads/{lead_id}` | Authenticated | Partially update one visible lead. |
| `GET /api/v1/leads/{lead_id}/activities` | Authenticated | List the lead's activities, newest first. |
| `POST /api/v1/leads/{lead_id}/activities` | Authenticated | Add an activity; returns `ActivityRead` with status 201. |
| `POST /api/v1/leads/import` | Owner, manager | Import leads from a CSV file and return per-row results. |
| `POST /api/v1/public/leads` | Public | Submit a website inquiry; returns `LeadRead` with status 201. |

`LeadRead` includes `id`, `team_id`, `assigned_to`, `created_by`, `full_name`,
`email`, `phone`, `source`, `status`, `budget_min_inr`, `budget_max_inr`,
`bhk`, `preferred_location`, `notes`, `created_at`, and `updated_at`.
`source` is one of `website`, `99acres`, `magicbricks`, `instagram`,
`whatsapp`, `walk_in`, `manual`, `csv_import`, or `other`. `status` is one of
`new`, `contacted`, `site_visit`, `negotiation`, `won`, or `lost`. Budgets are
non-negative INR integer amounts; if both are provided, minimum must not exceed
maximum.

`GET /api/v1/leads` accepts:

- `limit` (1-100, default 50) and `offset` (default 0);
- `status` and `source` enum filters;
- `assigned_to` (UUID; agents may only request their own ID);
- `q` (1-100 characters; searches name, email, phone, and location);
- `location` (1-160 characters);
- `budget_min_inr` and `budget_max_inr` (non-negative integers; filters for
  overlapping budget ranges).

Lead create fields are `full_name` (required), and optional `email`, `phone`,
`source` (default `manual`), `status` (default `new`), `budget_min_inr`,
`budget_max_inr`, `bhk`, `preferred_location`, `notes`, and `assigned_to`.
Agents are automatically assigned their own leads and cannot assign leads to
other users. Managers and owners can assign a lead to an active member of
their team. In a PATCH, omitted fields are unchanged; nullable contact,
budget, location, notes, and assignee fields can be cleared with `null`.

Activities have `type` (`call`, `note`, `site_visit`, `status_change`, `email`,
`whatsapp`, `assignment_change`, or `other`), `body`, and optional
timezone-aware `occurred_at` (defaults to the current time). Adding an activity
marks any existing AI lead score stale.

### CSV import

Send a multipart form upload with the field name `file` and a UTF-8 CSV file.
Maximum size is 2 MiB and maximum row count is 500. The header must include
`full_name`; supported columns are `full_name`, `email`, `phone`, `source`,
`status`, `budget_min_inr`, `budget_max_inr`, `bhk`, `preferred_location`,
`notes`, and `assigned_to`. Optional source defaults to `csv_import`; status
defaults to `new`. Unknown/duplicate headers, invalid rows, or invalid
assignments are reported in `errors` without rejecting other valid rows. The
response has `created_count`, `rejected_count`, `created_lead_ids`, and
`errors` (`row` and `message`).

### Public lead submission

Submit `full_name` plus optional `email`, `phone`, budget range, `bhk`, and
`preferred_location`. The server sets source to `website`, status to `new`,
and assigns the lead to no user. This endpoint is rate limited and requires a
valid backend `PUBLIC_LEAD_TEAM_ID`; misconfiguration returns 503.

## Tasks and dashboard

| Method and path | Access | Purpose and response |
|---|---|---|
| `GET /api/v1/tasks` | Authenticated | List visible tasks, open by default. |
| `POST /api/v1/tasks` | Authenticated | Create an open follow-up task; returns status 201. |
| `GET /api/v1/tasks/{task_id}` | Authenticated | Read one visible task. |
| `PATCH /api/v1/tasks/{task_id}` | Authenticated | Change task status; managers and owners can also reassign it. |
| `GET /api/v1/dashboard/summary` | Authenticated | Return role-scoped lead and task summary data. |

Task listing accepts `limit` (1-100, default 50), `offset` (default 0),
`status` (`open`, `completed`, or `cancelled`; defaults to `open`) and `due`
(`today` or `overdue`). Due filters apply only to open tasks and use the
configured `APP_TIMEZONE`; combining a due filter with a non-open status
returns 422.

Task creation accepts `lead_id`, `title`, timezone-aware `due_at`, and optional
`description` and `assigned_to`. Agents can only create tasks for themselves.
Task updates accept `status` and, for managers/owners only, `assigned_to`.
`TaskRead` includes IDs for the task, team, lead, assignee, and creator; title,
description, due time, status, completion time, and creation/update times.

Dashboard summary includes `timezone`, `total_leads`, `pipeline_counts`,
`open_tasks`, `due_today_count`, `overdue_count`, `due_today`, and `overdue`.
Each task summary contains `id`, `lead_id`, `lead_name`, `lead_status`, `title`,
`due_at`, and `status`. Agents' counts and task lists are limited to their
assigned leads.

## AI assistance

| Method and path | Access | Purpose and response |
|---|---|---|
| `GET /api/v1/leads/{lead_id}/ai/score` | Authenticated | Return the latest stored score, or `null`. |
| `POST /api/v1/leads/{lead_id}/ai/score` | Authenticated | Generate and store a new score. |
| `POST /api/v1/leads/{lead_id}/ai/draft` | Authenticated | Generate and save a message draft for review. |
| `POST /api/v1/leads/{lead_id}/ai/extract` | Authenticated | Extract suggested fields and a possible task from notes. |

AI uses only the visible lead's CRM data and recent activity. Generated results
may be incomplete; review before acting. Drafting does not send the message.
Note extraction does not modify the lead or schedule a task. AI service errors
return 503.

Score results contain `score` (0-100), `temperature` (`hot`, `warm`, or
`cold`), `reason`, and `factors`. The score GET may return a stored record with
additional `id`, `created_at`, `is_stale`, `provider`, and `model` fields.
Existing scores are marked stale when relevant lead activity is added or a new
score is calculated.

Draft requests require `channel` (`whatsapp` or `email`) and optionally
`tone` (`professional`, `friendly`, `concise`, or `warm`; default
`professional`). The response contains the stored draft's `id`, `lead_id`,
`channel`, `tone`, `body`, `status`, and `created_at`.

Extraction requests contain `notes` (1-5000 characters). Results may include
`budget_min_inr`, `budget_max_inr`, `bhk`, `preferred_location`,
`next_task_title`, and timezone-aware `next_task_due_at`; unknown values are
`null`. A suggested task due time is only a proposal for the frontend to
present for confirmation.

## Audit feed and live updates

| Method and path | Access | Purpose and response |
|---|---|---|
| `GET /api/v1/audit/events` | Authenticated | Return visible events, read markers, and unread count. |
| `GET /api/v1/audit/unread-count` | Authenticated | Return the current unread count. |
| `POST /api/v1/audit/read` | Authenticated | Mark currently visible events read. |
| `GET /api/v1/audit/stream` | Authenticated | Subscribe to real-time audit update events using SSE. |

The event list accepts `limit` (1-100, default 50) and `offset` (default 0).
Each event contains `id`, `actor_id`, `actor_name`, `lead_id`, `entity_type`,
`entity_id`, `action`, `summary`, `changes`, `created_at`, and `is_read`.
Results are filtered by the caller's team, role, and visibility. Marking events
read updates the read cursor and returns `last_read_at`.

The stream response uses `text/event-stream`. Send the normal
`Authorization: Bearer <access_token>` header; browser `EventSource` cannot set
custom headers, so use a fetch-based SSE client when bearer authentication is
required. Events include an initial `audit-sync`, `audit` events with an
`event_id`, and keep-alive comments. Clients should refresh the event feed on
`audit-sync` or `audit`. The stream may return 429 with `Retry-After` when
capacity is full; a revoked/expired session emits `auth-revoked` before the
stream closes.

## Health check

`GET /health` is public and returns `{"status":"ok"}` when the API process is
responsive. It is a process health check, not a guarantee that every
dependency or authenticated endpoint is operating correctly.
