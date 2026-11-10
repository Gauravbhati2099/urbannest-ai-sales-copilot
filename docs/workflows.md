# CRM workflow diagrams

These diagrams describe the implemented API boundaries and data flows. The
frontend may not expose every documented API feature yet; AI routes are
available through the backend API.

## Sign-in, access checks, and account recovery

```mermaid
flowchart TD
    Browser[Frontend] -->|Email and password| Login[POST /auth/login]
    Login --> Throttle[Database-backed login limits]
    Throttle --> Verify{Credentials valid<br/>and user active?}
    Verify -->|No| Deny[401 response]
    Verify -->|Yes| Token[Issue access token and user profile]
    Token --> Request[Authenticated API request]
    Request --> Authenticate[Verify token and load active user]
    Authenticate --> Scope[Apply team and role/record scope]
    Scope --> Decision{Authorized for this record<br/>and operation?}
    Decision -->|No| Forbidden[403 or scoped 404]
    Decision -->|Yes| Handler[Run API operation]
    Handler --> Database[(PostgreSQL)]

    Admin[Owner or manager] -->|Create user or reset password| Provision[Admin-only user endpoint]
    Provision --> Temporary[Return one-time temporary password]
    Temporary --> MustChange[Require password change at next sign-in]
    MustChange --> NewToken[Change password and issue replacement token]
```

The browser's role is only for presenting the appropriate controls. The API
loads identity and access from the database for protected requests; a client
supplied team ID or role never grants access.

## Lead intake, pipeline, follow-ups, and shared activity

```mermaid
flowchart TD
    Website[Website form] --> Public[POST /public/leads]
    Public --> PublicChecks[Validate fields, configuration, and shared rate limit]
    PublicChecks --> PublicLead[Create unassigned website lead]
    PublicLead --> PublicActivity[Add website inquiry timeline activity]
    PublicLead --> PublicAudit[Write contact-free team audit event]

    Manual[Authenticated user] --> CreateLead[POST /leads]
    CreateLead --> ManualLead[Validate and create lead in caller's team]
    ManualLead --> ManualAudit[Write lead audit event]

    CSV[Owner or manager CSV upload] --> Import[POST /leads/import]
    Import --> RowCheck[Validate file, rows, and same-team assignees]
    RowCheck --> Imported[Save valid rows and return row errors]
    Imported --> ImportAudit[Write team import audit event]

    Lead[Visible lead] --> Update[Update stage or assignment]
    Update --> History[Write timeline activity]
    Update --> Stale[Mark existing AI scores stale when relevant]
    Update --> ChangeAudit[Write safe audit change fields]
    History --> LeadCommit[Commit lead update]
    Stale --> LeadCommit
    ChangeAudit --> LeadCommit
    PublicActivity --> IntakeCommit[Commit public intake]
    PublicAudit --> IntakeCommit
    ManualAudit --> ManualCommit[Commit manual lead]
    ImportAudit --> ImportCommit[Commit CSV import]

    Lead --> FollowUp[Create follow-up task]
    FollowUp --> TaskChecks[Check lead visibility and active same-team assignee]
    TaskChecks --> OpenTask[Store open task and audit event]
    OpenTask --> TaskCommit[Commit task change]
    TaskCommit --> DueViews[Dashboard and task lists show open, due-today, overdue]
    DueViews --> Complete[PATCH /tasks/{task_id}: completed]
    Complete --> CompleteAudit[Write task update audit event]
    CompleteAudit --> CompleteCommit[Commit completion]
    CompleteCommit --> CompletedView[GET /tasks?status=completed]
    LeadCommit --> Notify[Publish committed audit event]
    IntakeCommit --> Notify
    ManualCommit --> Notify
    ImportCommit --> Notify
    TaskCommit --> Notify
    CompleteCommit --> Notify
    Notify --> Feed[Role-filtered shared activity feed]
    Feed --> Cursor[Each user has an independent read cursor]
```

Lead visibility is enforced on list and detail requests: agents see leads
assigned to them; managers and owners see their team's leads. Task access is
also checked against the related lead and task assignee. Audit events are
stored once per team and filtered for each viewer; read state is per user.

## AI-assisted lead workflows

```mermaid
flowchart TD
    Request[Authenticated AI request for a lead] --> Access{Can the user access<br/>this lead?}
    Access -->|No| Reject[Reject before provider call]
    Access -->|Yes| Context[Load lead and recent timeline]
    Context --> Minimize[Limit context and redact contact details]
    Minimize --> Feature{Requested feature}

    Feature -->|Lead score| ScorePrompt[Ask provider for structured score]
    ScorePrompt --> ScoreValidate[Validate score, temperature, reason, and factors]
    ScoreValidate --> ScoreStore[Mark prior current score stale and save score]

    Feature -->|Message draft| DraftPrompt[Ask for editable follow-up text]
    DraftPrompt --> DraftValidate[Validate structured response]
    DraftValidate --> DraftStore[Save message with draft status]
    DraftStore --> Review[User reviews and edits; no automatic sending]

    Feature -->|Notes extraction| ExtractPrompt[Redact and bound untrusted note text]
    ExtractPrompt --> ExtractValidate[Validate proposed property and task fields]
    ExtractValidate --> Proposal[Return proposal without saving]
    Proposal --> Confirm{User confirms or edits proposal?}
    Confirm -->|No| Discard[Discard proposal]
    Confirm -->|Yes| NormalAPI[Save through normal authenticated lead or task API]

    ScoreStore --> Usage[Record provider, model, token, latency, and outcome metadata]
    DraftStore --> Usage
    Proposal --> Usage
    ProviderError[Provider timeout or invalid response] --> Failure[Return explicit service error]
    Failure --> FailedUsage[Record failure category without storing prompt text]
```

AI output is treated as untrusted data: it is schema-validated and never used
as SQL or as a substitute for authorization. Short AI calls run inline with
explicit errors; they are not durable background jobs.
