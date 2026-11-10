# Infinaut CRM – Technology Stack

**Project:** Infinaut CRM: AI Sales Copilot  
**Client:** UrbanNest Realty  
**Architecture:** Modular Monolith  
**Deployment:** Vercel + Render + Aiven PostgreSQL

## 1. Architecture Overview

The application follows a modular monolithic architecture with a separate frontend and backend.

The frontend communicates with the FastAPI backend through REST APIs. The backend handles authentication, authorization, business logic, database operations and AI orchestration.

AI functionality is integrated within the backend rather than deployed as a separate microservice.

## 2. Technology Stack

| Layer | Technology | Purpose |
|---|---|---|
| Frontend | Next.js + React | CRM user interface |
| Styling | Tailwind CSS | Responsive UI and styling |
| Backend | Python + FastAPI | REST API and business logic |
| Database | PostgreSQL | Persistent application data |
| Database Hosting | Aiven | Managed PostgreSQL hosting |
| ORM | SQLAlchemy | Database access and ORM |
| Migrations | Alembic | Database schema versioning |
| Authentication | JWT | Session authentication and authorization |
| Data Validation | Pydantic | Request and response validation |
| AI Orchestration | LangGraph | Multi-step AI workflows |
| Primary AI Provider | Google Gemini | Lead scoring, message drafting and note extraction |
| Local AI Provider | Ollama | Local inference and development fallback |
| Frontend Hosting | Vercel | Frontend deployment |
| Backend Hosting | Render | FastAPI deployment |
| Frontend Analytics | Vercel Analytics | Visitor and frontend performance monitoring |
| Backend Monitoring | Render Metrics and Logs | Backend health and runtime monitoring |

## 3. Backend Architecture

The backend will use a modular structure to keep individual business domains independent and maintainable.

### Core Modules

- **Authentication:** Login, token generation, current-user identification and role-based access.
- **Users and Teams:** User management, roles and team relationships.
- **Leads:** Lead creation, updates, assignment, filtering and pipeline management.
- **Activities:** Lead activity timeline and interaction history.
- **Tasks:** Follow-up scheduling, reminders and task completion.
- **AI:** AI provider integration, prompt management, usage tracking and LangGraph workflows.
- **Analytics:** CRM business metrics and operational reporting.

### Proposed Backend Structure

```text
backend/
├── app/
│   ├── main.py
│   ├── core/
│   │   ├── config.py
│   │   ├── security.py
│   │   └── dependencies.py
│   ├── db/
│   │   ├── session.py
│   │   ├── base.py
│   │   └── models.py
│   └── modules/
│       ├── auth/
│       ├── users/
│       ├── leads/
│       ├── activities/
│       ├── tasks/
│       ├── analytics/
│       └── ai/
│           ├── router.py
│           ├── service.py
│           ├── providers/
│           │   ├── base.py
│           │   ├── gemini.py
│           │   └── ollama.py
│           ├── graphs/
│           │   ├── lead_scoring.py
│           │   ├── message_drafting.py
│           │   ├── note_extraction.py
│           │   └── sales_assistant.py
│           ├── schemas.py
│           └── prompts.py
├── alembic/
├── tests/
├── .env.example
├── requirements.txt
└── README.md
```

## 4. Database

PostgreSQL will be hosted on Aiven.

SQLAlchemy will handle database interactions, while Alembic will manage schema migrations.

### Core Tables

| Table | Responsibility |
|---|---|
| users | User accounts, roles and team association |
| teams | Agency team information |
| leads | Lead information and current pipeline status |
| activities | Lead interaction history |
| tasks | Follow-ups and reminders |
| ai_scores | AI-generated lead scores and explanations |
| messages | Generated and saved communication drafts |
| ai_usage | AI provider usage, token consumption, latency and errors |

The initial model uses a `teams` table and a `team_id` tenant key on users and business records. Users belong to one team for this assessment. Team-scoped composite foreign keys prevent activities, tasks, scores, messages and usage records from linking to a user or lead in another team.

The finalized ER model is in [`ERD.md`](./ERD.md); matching SQLAlchemy 2.x declarative models are in [`../backend/app/db/models.py`](../backend/app/db/models.py). The model includes `teams`, `users`, `leads`, `activities`, `tasks`, `ai_scores`, `messages` and `ai_usage`.

### Connection Management

SQLAlchemy connection pooling will be configured against Aiven's currently available connection limit and the deployed worker count. Pool limits multiply by every app instance and worker; calculate total possible connections before choosing values.

The `.env.example` contains the pool settings. A local `.env` is required for a real connection; never commit it. The ORM and migration are designed first, and the hosted database is not changed until the schema is reviewed and connection settings verified.

## 5. AI Architecture

AI functionality will be implemented through a provider abstraction layer.

This will allow the application to switch between Gemini and Ollama without changing the CRM's business logic.

### AI Features

| Feature | Implementation |
|---|---|
| A1 – Lead Scoring | Structured AI output with score, temperature and reasoning |
| A2 – Message Drafting | Context-aware WhatsApp and email generation |
| A3 – Note Extraction | Extract structured lead information with validation and user confirmation |
| A4 – Sales Assistant | LangGraph orchestration with controlled backend tools |
| A5 – Weekly AI Report | SQL-based aggregation followed by AI-generated insights |

### LangGraph Usage

LangGraph will be used selectively for workflows requiring multiple steps, conditional execution or tool orchestration.

It will not be introduced unnecessarily for simple LLM requests.

Examples:
- Sales assistant intent routing and tool execution.
- Multi-step lead analysis.
- Structured note extraction and validation.

User confirmation for extracted data will be handled through the frontend before changes are saved.

### AI Provider Configuration

Environment variables will control the selected provider, model and API credentials.

The application must remain operational when an AI provider is unavailable. CRM operations must not depend on successful AI execution.

## 6. Monitoring and Analytics

Monitoring will be divided into three areas.

### Infrastructure Monitoring

- Vercel Analytics: Visitor activity and frontend performance.
- Render Metrics: CPU, memory and backend service health.
- Render Logs: Runtime errors and deployment diagnostics.
- Aiven Monitoring: Database resource and connection usage.

### AI Usage Analytics

The `ai_usage` table will capture:

- AI feature and provider.
- Model identifier.
- Input and output token usage.
- Request latency.
- Estimated API cost.
- Success or failure status.
- Associated user and lead, where applicable.

### CRM Business Analytics

CRM analytics will be generated through PostgreSQL aggregation queries and exposed through role-protected FastAPI endpoints.

## 7. Deployment Architecture

| Component | Deployment |
|---|---|
| Next.js frontend | Vercel |
| FastAPI backend | Render |
| PostgreSQL database | Aiven |
| Gemini inference | Google Gemini API |
| Local inference | Ollama on development machine |

Production secrets will be configured through the respective hosting platform's environment-variable settings.

## 8. Engineering Principles

1. Modular monolith instead of unnecessary microservices.
2. Server-side role and resource-level authorization.
3. Database migrations managed through Alembic.
4. Pydantic validation for all AI-generated structured data.
5. AI provider abstraction to avoid vendor lock-in.
6. SQL aggregation for factual business metrics.
7. No direct execution of LLM-generated SQL.
8. Graceful degradation when AI services fail.
9. Minimal storage of personally identifiable information in logs.
10. Feature branches, pull requests and code reviews for team collaboration.

## 9. Scope Control

The initial implementation prioritizes authentication, lead management, pipeline operations, activity history, tasks and the three required AI features.

Advanced analytics, operational monitoring aggregation and additional AI workflows will be implemented after the core CRM is functional.

The architecture is intentionally designed to remain deployable and maintainable within the 48-hour assessment timeline.