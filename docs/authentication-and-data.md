# Authentication flow and user-data handling

This document describes how the current frontend and backend handle sign-in,
team account provisioning, password changes, and related user data. It
complements the [frontend API guide](./frontend-api.md) and
[authentication contract](./api-auth.md).

## Authentication and account lifecycle

```mermaid
sequenceDiagram
    autonumber
    actor User
    actor Admin as Owner, manager, or co-owner
    participant UI as React frontend
    participant API as FastAPI API
    participant DB as PostgreSQL

    User->>UI: Submit email and password
    UI->>API: POST /api/v1/auth/login
    API->>DB: Check shared rate limits; look up user
    API->>API: Verify password against Argon2 hash
    alt Credentials valid and account active
        API-->>UI: Access token, expiry, public user profile
        UI->>UI: Store token in sessionStorage
    else Invalid credentials or inactive account
        API-->>UI: 401 Invalid email or password
    end

    loop Authenticated API request
        UI->>API: Request with Authorization: Bearer token
        API->>API: Verify JWT signature, issuer, expiry, user ID and version
        API->>DB: Reload active user and current role/team
        API->>API: Enforce team, role and co-owner permissions
        API-->>UI: Authorized response or 401/403/404
    end

    Admin->>UI: Confirm account creation or password reset
    UI->>API: POST /api/v1/users or /password-reset
    API->>API: Enforce administrator role and team scope
    API->>API: Generate random temporary password; hash with Argon2
    API->>DB: Store hash, force password change, record safe audit event
    API-->>UI: Public user data and one-time temporary password
    UI->>UI: Keep temporary password in page memory for display

    User->>UI: Sign in with temporary password
    UI->>API: POST /api/v1/auth/login
    API-->>UI: Token and user profile with must_change_password=true
    UI->>API: POST /api/v1/auth/change-password
    API->>API: Verify current password; hash new password
    API->>DB: Update hash; increment auth_version
    API-->>UI: Replacement token and updated profile
```

### What the flow means for the frontend

1. **Login:** submit the email and password as JSON. The API normalizes the
   email, rate-limits the attempt, and verifies the password. Successful login
   returns a bearer token, its lifetime, and a public profile. It does not
   return a password or password hash.
2. **Token use:** send `Authorization: Bearer <access_token>` on authenticated
   requests. The backend verifies the token, then reloads the account from the
   database on each request. The browser's cached role or team is not treated
   as authority.
3. **Temporary passwords:** account creation and administrator resets return a
   newly generated password once. Display it only after the operation
   succeeds, provide a private handoff to the user, and do not put it in a URL,
   analytics event, or persistent browser storage.
4. **Required password change:** a user marked `must_change_password` is
   restricted to the password-change and current-user routes until they change
   the temporary password. A successful change returns a replacement token.
5. **Revocation:** a password change/reset, role change, or deactivation
   increments the account's `auth_version`. Tokens with the old version no
   longer authorize API requests. Resetting another user's password also
   requires that user to change it at next login.
6. **Bulk reset:** the owner confirms the operation, then the API rotates all
   team account passwords and returns a CSV. The frontend downloads it and
   signs out the owner. The file contains live credentials: keep it private,
   distribute each password securely, and delete the download when finished.

The UI asks for confirmation before creating an account; changing a password;
resetting an individual or all passwords; changing a user's role; and
activating or deactivating an account. Cancellation makes no API request.
Confirmation is a user-experience safeguard, not an authorization boundary:
the backend independently enforces roles, ownership, team scope, and
validation.

## How user and related data are handled

| Data | Handling |
|---|---|
| Passwords | Sent in request bodies (use HTTPS in production); stored in PostgreSQL only as Argon2 hashes. Temporary passwords are generated server-side and returned only for the creation/reset operation. Existing passwords cannot be retrieved. |
| Access tokens | Signed JWTs include the user ID, authentication version, issuer, and expiry. The frontend keeps the current token in tab-scoped `sessionStorage`, sends it in the bearer header, and removes it on sign-out. The token is not used as a source of role/team permissions. |
| User profile | PostgreSQL holds the account's team, name, email, optional phone, role, active state, password hash, superuser flag, four co-owner permission flags, and auth-version/password-change flags. API user responses omit the password hash and other authentication secrets. |
| Authorization | The backend derives the acting user, team, role, and current permission flags from the verified token and database row. Queries remain team-scoped; agent records are further scoped to assignment. Co-owner read/write/delete permissions apply to authenticated CRM routes, while `can_manage_users` separately grants management of agent accounts. |
| Login limits | Shared fixed-window counters are stored in PostgreSQL. Email/IP keys are HMACed with the JWT secret before storage; raw email addresses and IP addresses are not written to the counter table. |
| Audit records | Account and password-security actions create audit events. Audit change data is designed to omit passwords, contact details, lead notes, and task descriptions. User-facing responses do not include password hashes. |
| Browser preferences | Theme and sidebar preferences use `localStorage`; the bearer token uses `sessionStorage`. Temporary passwords are held in frontend page state for display and are not intentionally saved to browser storage. |
| Bulk reset CSV | Generated by the API with no-store response headers; the frontend downloads the file and does not upload it elsewhere. Anyone who obtains the file can use its temporary passwords until they are changed or invalidated. |
| AI context | AI prompts include lead context such as first name, source, status, budget, location, notes, and recent activities. Email and phone fields are excluded; email/phone patterns in free text are redacted. Gemini sends the prompt to Google's API; Ollama sends it to the configured Ollama server. Provider/model, token counts, latency, outcome, and request ID can be stored as usage metadata; prompts and completions are not stored by the application. |

### Security and operational notes

- Production browser-to-API traffic should use HTTPS. Configure CORS with the
  exact frontend origin; CORS is not authentication.
- A `401` indicates missing/invalid credentials or token. A `403` indicates
  the authenticated user lacks permission. A `500` is an unexpected server
  failure; check backend logs rather than treating it as a password error.
- Temporary credentials and the bulk-reset CSV are sensitive. Do not paste
  them into support tickets, commit them, or send them through untrusted
  channels.
- The application has no email-based self-service password reset configured.
  An owner, manager, or user-enabled co-owner must issue a reset for another
  user.
- A development superuser is an owner-level account limited to its configured
  development team. Startup creates it only when `DEV_SUPERUSER_BOOTSTRAP=true`,
  all `DEV_SUPERUSER_*` fields are provided, and `APP_ENV=development`.
  Credentials are hashed before storage and are not logged. The bootstrap is
  idempotent and refuses to change an existing account's password.
- No automatic application-level user-data retention/deletion policy is
  implemented here. Database retention, backups, provider-side AI data
  handling, and production credential rotation should be configured for the
  deployment and its operational requirements.
