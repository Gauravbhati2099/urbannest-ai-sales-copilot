# Architecture and system design approach

**Project:** Infinaut CRM: AI Sales Copilot for UrbanNest Realty  
**Status:** Initial proposal for the 48-hour assessment; revisit decisions after the first working deployment  
**Current scope:** FastAPI backend, managed PostgreSQL, separate frontend, AI features A1–A3  
**Explicitly not in the initial infrastructure:** Redis, message broker, Kubernetes, and independently deployed microservices

This document records the main architecture questions, viable alternatives, and the proposed trade-offs. The goal is not to maximize the number of technologies. It is to ship a secure, demonstrable CRM quickly while keeping boundaries clear enough to support a later modular/service-based experiment.

## 1. Executive recommendation

Start with a **modular monolith**: one FastAPI application, one managed PostgreSQL database, one frontend application, and an external AI provider accessed server-side. Keep modules separated by business responsibility, but deploy and operate the API as one service.

Use the database as the durable source of truth. Use frontend query caching for perceived speed, with explicit invalidation and user-scoped keys. Do not introduce Redis or a broker for the assessment. Run required work inline with visible timeouts and errors; avoid pretending that in-process background tasks are durable.

Only extract a separate service after observing a real reason, such as independent scaling, a separate release cadence, provider-specific worker needs, or a clear reliability boundary. First validate those boundaries inside the monolith.

```text
Responsive frontend
        | HTTPS / JSON / bearer token
        v
FastAPI modular monolith
  auth + authorization
  leads + pipeline
  activities + tasks
  AI orchestration
        | SQLAlchemy / transactions
        v
Managed PostgreSQL
        |
        +---- outbound HTTPS ---- AI provider
```

## 2. Architecture questions and decisions

### Q1. Monolith or microservices?

**Options**

- **Modular monolith:** one deployable API, with internal modules and clear interfaces.
- **Microservices:** independently deployed services for identity, CRM, AI, notifications, and possibly reporting.

**Recommendation: modular monolith for the assessment.**

Two candidates, a 48-hour deadline, one primary workflow, and a single relational data model favor one deployable backend. A modular monolith keeps local development, deployment, authorization, transactions, and debugging understandable. It avoids spending the deadline on service discovery, cross-service authentication, network failure handling, duplicated schemas, and distributed transactions.

This does not mean putting everything in one file. Use modules and service interfaces from the start. Treat a later service extraction as an experiment after the core is working, not as a prerequisite to demonstrate architecture.

**Cost / trade-off:** modules share a process and deployment, so they cannot scale independently. That is acceptable at assessment scale. Define an extraction trigger before splitting.

### Q2. How should the FastAPI application be structured?

**Recommendation: organize around business capabilities, not technical layers alone.**

One possible layout:

```text
app/
  main.py                 # app creation, middleware, router registration
  core/                   # settings, auth utilities, shared errors
  db/                     # engine, session dependency, base metadata
  modules/
    auth/
      router.py
      schemas.py
      service.py
      repository.py
    leads/
    activities/
    tasks/
    ai/
  tests/
alembic/
```

Routes handle HTTP concerns and validation; services implement use cases and authorization-aware coordination; repositories (or focused query functions) handle persistence. Keep dependencies explicit. Avoid circular imports and avoid one generic repository abstraction that hides important SQL or tenant filters.

A module may call another module through a service/use-case interface. Do not make internal HTTP calls between modules in one process. Shared transactions should use a single database session/unit of work.

### Q3. What database and persistence strategy?

**Options**

- Managed PostgreSQL with SQLAlchemy and Alembic.
- A document database or unversioned schema setup.
- A local SQLite-only design.

**Recommendation: managed PostgreSQL, SQLAlchemy, and Alembic.**

The CRM has relational users, teams, leads, activities, tasks, and AI history. PostgreSQL supports the needed relationships, constraints, indexes, transactions, and JSON fields for AI factors. Alembic makes schema changes repeatable between development and deployment.

Use one database for the first release. Aiven, Neon, and Supabase are candidates; select based on the actual free-plan limits, inactivity/expiry behavior, connection ceiling, region, and deployment fit at kickoff rather than relying on remembered quota figures. Write migrations as the schema contract; never rely on automatic table creation in production. Keep the provider's connection URL and credentials in server-side environment configuration.

**Important:** do not assume the managed database API key is the same thing as a PostgreSQL connection URL. Use the provider's documented server-side connection mechanism. Never place either credential in frontend code or commit it to Git. If a key has already been committed or shared, rotate it.

#### Connection pooling: what it is and how to size it

A PostgreSQL connection is a reusable client session. Creating one for every HTTP request adds connection setup/authentication overhead and can exhaust the database's connection limit when requests or app instances grow. SQLAlchemy's application-side connection pool keeps a bounded set of connections and lends one to each database operation, returning it when the operation finishes. This is part of the FastAPI process; it is not Redis or another service.

Start with a small, configurable pool and calculate the maximum possible application connections:

```text
maximum app connections =
  app instances × worker processes per instance × (pool_size + max_overflow)
```

Include migrations, seed scripts, and any separate worker in the budget; keep capacity in reserve for administration and provider internals. Set `pool_size`, `max_overflow`, and connection timeout based on the provider's actual limit and the chosen host's worker/instance behavior. If using a serverless or frequently scaled host, check whether the database provider recommends a separate transaction pooler. Do not copy a pool size such as 3–5 without doing the total-connection calculation.

### Q4. Single organization or multi-tenant data model?

**Recommendation: include `team_id` on business records from day one.**

The assessment describes one agency, but ownership boundaries are clearer and safer when leads and users belong to a team. Resolve the team from the authenticated user; do not let an ordinary request choose an arbitrary team ID.

For each query or mutation, enforce both the user's team and role/assignment rules. Validate that a lead's assignee, activity actor, and task assignee belong to the same team. Use a shared authorization/query helper or service policy rather than remembering the filter ad hoc in every route.

PostgreSQL row-level security could add defense in depth, but introduces connection/session context and migration/testing complexity. For the assessment, use explicit backend authorization and add row-level security only if the team can implement and verify it correctly.

### Q5. How should authentication and authorization work?

**Recommendation: server-verified identity plus backend authorization on every operation.**

The frontend sends a bearer token. The API verifies it, loads or validates the active user and role, and scopes the database operation. The API must not trust a role, owner ID, agent ID, or team ID supplied by the browser. UI role checks improve UX only; they are not security controls.

Test authorization with at least:

- unauthenticated access to protected routes;
- Agent A trying to list, fetch by guessed ID, update, and request AI on Agent B's lead;
- manager and owner visibility boundaries;
- cross-team references when a second team is seeded in tests.

Choose access-token expiry and refresh behavior deliberately; for a small demo, a simple short-lived token flow may be sufficient if the limitations are documented. Do not store plaintext passwords. Keep token signing secrets server-side and out of logs.

### Q6. REST, GraphQL, or direct database access from the frontend?

**Recommendation: REST JSON with versioned routes.**

The workflows map naturally to resources and actions, FastAPI generates OpenAPI documentation, and the frontend/backend can work in parallel against a stable contract. Keep a consistent error envelope and pagination shape. Use DTO/Pydantic schemas rather than returning ORM objects directly.

GraphQL adds schema/resolver and authorization complexity without an identified need. The frontend must never access PostgreSQL directly; all reads and writes go through the authorized API.

### Q7. How do we handle AI without leaking data or giving it control?

**Recommendation: AI orchestration inside the FastAPI AI module, behind normal authorization.**

For a lead-specific request, load the lead and only its relevant recent history after verifying the caller can see it. Minimize personal data in prompts. For scoring and extraction, request a structured result and validate it with a Pydantic schema before storing or returning it. For message drafts, return editable text and do not claim it was sent.

For an assistant, expose a small set of typed, allowlisted query functions. The LLM selects among those functions; application code validates arguments and applies the same role/team scoping. Never execute LLM-generated SQL. Do not allow the model to invent user/team identities or bypass normal authorization.

Keep a provider-independent interface for operations such as `score_lead`, `draft_message`, and `extract_notes`; provider-specific SDK code belongs behind that interface and is selected through server-side configuration. Set request timeouts, handle provider errors explicitly, and record provider/model, token counts, latency, and outcome where available. Do not log prompts containing unnecessary lead PII, credentials, or raw provider responses by default. AI output is a suggestion, not a trusted database command.

**LangGraph is optional orchestration, not a required service.** Use a direct structured model call for a simple operation. Use LangGraph selectively when a workflow benefits from multiple steps, branching, tool selection, or resumable state—for example, a future assistant using allowlisted tools. A3 can return a validated proposal for frontend confirmation and then save through a normal authenticated API; a persistent graph interrupt is not required for this human approval. Do not put ordinary lead CRUD behind a graph, and do not let graph state replace the database or authorization checks.

### Q8. Should AI run synchronously or in a job queue?

**Recommendation: synchronous requests for short A1–A3 operations initially.**

For a small demo, lead scoring, message drafting, and extraction can run in a request with an explicit timeout, clear loading UI, and visible failure response. Save results only after schema validation and any required user confirmation.

Do not use FastAPI `BackgroundTasks` for work that must survive process restarts or guarantee delivery: it is in-process and not a durable queue. If model latency or reporting later requires durable/retried work, add a job boundary deliberately (for example, PostgreSQL-backed job/outbox first, or a broker/worker once justified).

### Q9. Is Redis needed for caching or coordination?

**Recommendation: no Redis in the initial version.**

Use frontend query caching for perceived speed, scoped to the logged-in user/team, and invalidate after mutations. The PostgreSQL database is the source of truth. Use indexed, paginated queries and measure before adding a server cache.

Without Redis, do not claim shared server cache, distributed locks, or cross-instance rate-limit state. Public lead intake can start with input validation, request-size limits, basic abuse controls at the hosting/provider edge, and duplicate detection if time allows. Add Redis only after a measured need such as shared rate limits, cache hot spots, or coordination across workers.

### Q10. How should frontend caching stay correct and private?

**Recommendation: cache server state in the frontend, but keep cache identity and invalidation explicit.**

Use query keys that include the authenticated identity/team and relevant filters. Clear user-specific cache on logout, account switch, or token invalidation. Invalidate related leads, pipeline, task, and dashboard queries after a mutation, CSV import, or AI update. If optimistic updates are used, restore/refetch on failure and show an error.

Do not cache private CRM responses in a shared CDN or publicly cache authenticated API responses. The backend must authorize each request even when the frontend has cached data.

### Q11. How should external channels be integrated?

**Recommendation: model source attribution now; integrate provider APIs only with time, credentials, and a confirmed need.**

Support website, property portal, Instagram, WhatsApp, and walk-in as lead sources. Deliver manual capture, CSV import, and the public form as reliable assessment paths. Do not represent a source label as a live integration.

A reviewed WhatsApp draft may offer a user-initiated handoff to WhatsApp, but the CRM should not mark it sent unless an actual sending integration confirms delivery. Webhooks, retries, signature verification, deduplication, and provider-specific error handling are separate work and should be scoped if they become requirements.

### Q12. How should the API be deployed?

**Recommendation: keep the API stateless and compatible with the selected host, and verify the actual deployment early.**

The assessment names Vercel for deployment, while this project uses FastAPI. In the first two hours, deploy a minimal FastAPI `/health` endpoint, verify an authenticated or protected database connectivity probe without exposing connection details, and make one frontend-to-backend request. This resolves runtime, CORS, network, and database connection assumptions before the full implementation. Do not assume a deployment target supports a long-running Python server just because it hosts the frontend.

If the API cannot run reliably on the required target, agree on an alternate API host while keeping the frontend on Vercel, and document the split. Keep configuration, CORS origins, database connection pooling, and AI credentials environment-specific.

### Q13. What testing gives the best confidence under a short deadline?

**Recommendation: prioritize authorization and end-to-end business paths over broad, shallow coverage.**

1. **Unit tests:** role policy, status/field validation, AI schema parsing.
2. **API/database tests:** auth, team/agent query scopes, lead/task mutations, imports, and invalid IDs.
3. **Integration smoke test:** login → create lead → change stage → add activity/task → verify list/detail.
4. **AI boundary tests:** unauthorized lead is rejected before provider invocation; malformed/timeout responses do not write invalid state.
5. **Frontend checks:** mobile and desktop core flows, loading/error/empty states, cache invalidation, logout cache clearing.
6. **Deployment smoke test:** demo credentials, health, database connectivity, and a full lead flow against the deployed URL.

Use fictional seed data only. Keep an automated or repeatable manual check for each demo role.

### Q14. What operational features are necessary now?

**Recommendation: minimal, privacy-aware operational visibility.**

Start with structured application logs for request ID, route, status, duration, and safe error category. Avoid tokens, passwords, database URLs, raw prompts, and unnecessary contact data in logs. Provide a liveness endpoint; add a separate readiness check only if it can report dependency health without exposing internal details. Track AI provider latency, failures, and token usage.

Do not add a metrics stack or tracing backend solely for the assessment. Make failures actionable in the UI and visible in server logs.

## 3. Decision summary

| Area | Initial decision | Revisit when |
|---|---|---|
| Backend topology | One FastAPI modular monolith | A module has independent scaling, reliability, ownership, or release requirements |
| Persistence | One managed PostgreSQL database; provider selected after quota/connection checks | Data volume, isolation, or operational requirements demonstrably exceed the single database |
| ORM/migrations | SQLAlchemy + Alembic | Team chooses a different stack before schema work begins |
| Database connections | Small bounded SQLAlchemy pool, sized across all app workers/instances | Host scaling or provider limits require a managed pooler or a different connection strategy |
| API | Versioned REST JSON + OpenAPI | Client needs show a concrete reason for a different query contract |
| Authorization | Backend role and record filters, with `team_id` boundary | Add row-level security as defense in depth only with tested connection context |
| AI | Provider abstraction; direct typed calls for simple features; LangGraph only where graph control flow adds value | Long-running workload or scale justifies durable worker extraction |
| AI usage | Store feature/provider/model, token counts, latency and outcome in a restricted `ai_usage` table | Retention, privacy, or analytics requirements call for more detailed controls |
| Score freshness | Mark prior lead scores stale after relevant lead/activity changes; keep score history | Event volume or recomputation needs justify a dedicated scoring worker |
| Jobs | Inline short operations; no durable async requirement assumed | Retries/scheduling/delivery guarantees become a real product need |
| Cache | Frontend query cache; PostgreSQL source of truth | Measurements show server-side cache/coordination need |
| Redis / brokers | Excluded initially | Shared rate limits, caching, locking, or durable queue needs are measured |
| Integrations | Manual/CSV/public form and source attribution | Provider access and confirmed use case are available |
| Deployment | Validate FastAPI host + Postgres connectivity early | Hosting constraints require an agreed alternate API runtime |

## 4. Future modular/service-based experiment

When the assessment submission is stable, use the existing module boundaries to run a small extraction experiment rather than splitting the entire CRM.

**Candidate first extraction: AI worker/service.** AI has distinct provider latency, token costs, timeouts, and possible retry needs. It can be extracted behind an internal interface such as `score_lead`, `draft_message`, and `extract_notes`, while the CRM API remains the authority for user identity, record access, and persistence.

Before extraction:

1. Keep AI application logic behind a module/service interface in the monolith.
2. Define request and response schemas that do not expose ORM models.
3. Ensure the caller passes only authorized, minimized context.
4. Record provider latency, failures, token usage, and actual user demand.
5. Define a deployment and failure fallback that does not make normal CRM access depend on AI availability.

For the first experiment, prefer a separately runnable worker/service in a development branch or environment with a narrow contract. Do not introduce a broker simply to make the diagram look distributed. If asynchronous durable work is required, define a job record/outbox, retry policy, idempotency key, timeout, and failure/dead-letter handling before choosing a queue technology.

**Success criteria:** the extracted module can be deployed or scaled independently; normal lead CRUD remains available when AI is down; authorization context cannot be broadened by the extracted service; retries do not duplicate score/message writes; operational complexity is justified by a measurable benefit. If these conditions are not met, return to the modular monolith.

## 5. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Tenant/agent data leaks through an unscoped query or AI prompt | Centralize authorization-aware query patterns; test list and direct-ID access; authorize before invoking AI. |
| Managed Postgres or deployment platform connection limits | Deploy a minimal health/database probe early; follow provider pooling guidance; avoid opening a new engine per request. |
| AI provider is slow, unavailable, or returns malformed output | Set timeout; validate structured output; surface errors; do not save invalid results; allow normal CRM work without AI. |
| Cache shows stale or another user's data | Include identity/team in keys, invalidate mutations, clear on logout/account switch, and keep private responses out of shared caches. |
| Scope creep into microservices or live channel integrations | Defer optional services/integrations until required flows and acceptance checks pass. |
| Assessment target and FastAPI runtime mismatch | Verify deployment in the foundation step and agree on a split host if necessary. |

## 6. Working decision log

Record confirmed decisions here during kickoff. Keep secrets out of this document.

| Decision | Current proposal | Confirmed value / owner |
|---|---|---|
| PostgreSQL provider and connection method | Compare Aiven, Neon, and Supabase current free-plan limits; server-side connection URL | TBD |
| API hosting | Deploy a FastAPI health/database probe in the first two hours; confirm frontend-to-API call | TBD |
| Frontend framework | Candidate 2's selection; REST/OpenAPI contract | TBD |
| AI provider/model | Provider-independent server interface; provider/model configured server-side | TBD |
| LangGraph scope | Optional library within the FastAPI AI module; use only for multi-step/tool workflows | TBD |
| SQLAlchemy pool sizing | Calculate across instances, workers, overflow, and operational connections against selected provider limit | TBD |
| Due-date timezone | `Asia/Kolkata`; store timestamps in UTC | TBD |
| Initial tenant scope | Include `team_id`; seed UrbanNest | TBD |
| Auth/token strategy | Server-verified bearer token and backend role checks | TBD |
