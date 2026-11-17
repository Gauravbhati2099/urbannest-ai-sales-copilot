# AI inference and CRM MCP services

UrbanNest keeps the authenticated CRM API, AI inference provider, and CRM MCP
tool server as separate processes. The normal `scripts/start.py` command starts
only the CRM API. You choose whether to host inference and MCP beside the API
or on separate machines. The frontend continues to call the CRM API; it never
receives an inference or MCP service credential.

## Services and configuration

| Service | ASGI app | Enable flag | Purpose |
|---|---|---|---|
| CRM API | `app.main:app` | existing API config | Auth, tenant checks, database, browser API |
| Ollama inference provider | `app.modules.ai.inference_service:app` | `INFERENCE_SERVICE_ENABLED=true` | Structured AI operations and chat model calls |
| CRM MCP server | `app.modules.chatbot.mcp_service:app` | `MCP_ENABLED=true` | Five authenticated, read-only CRM tools |

Set `AI_SERVICES_ENABLED=true` on the CRM API to expose lead score, message
draft, note extraction, and chat routes. Set `VITE_CHAT_ENABLED=true` in the
frontend build environment to show its chat page. AI feature routes return 404
when disabled. Set `INFERENCE_SERVICE_URL` and the matching
`INFERENCE_SERVICE_TOKEN` on the CRM API to route all model inference through
the separate provider. Without the service URL, AI requests use the configured
provider directly (useful for a single-host local deployment). Both paths use
Ollama; configure `AI_PROVIDER=ollama`, `OLLAMA_MODEL`, and `OLLAMA_BASE_URL`
on the machine that runs the inference provider.

Generate distinct long random values for `INFERENCE_SERVICE_TOKEN` and
`MCP_SERVICE_TOKEN`; neither may reuse the JWT secret. Keep both private.
Remote service URLs must use HTTPS. For a private network with no TLS,
`INFERENCE_ALLOW_REMOTE_HTTP=true` and `MCP_ALLOW_REMOTE_HTTP=true` explicitly
allow HTTP, but the bearer tokens and CRM access token then traverse that
network unencrypted. Prefer a VPN or private network with TLS.

## MCP access to the Render CRM API

The MCP process can run on the same server as the API or on a separate device.
For a separate device, expose its MCP endpoint at a stable HTTPS URL reachable
from Render, then configure these Render API environment values:

```text
AI_SERVICES_ENABLED=true
MCP_SERVER_URL=https://your-device.example.com/mcp
MCP_SERVICE_TOKEN=<same dedicated token configured on MCP host>
```

On the MCP host configure:

```text
MCP_ENABLED=true
MCP_SERVICE_TOKEN=<same dedicated token configured on Render API>
MCP_ALLOWED_HOSTS=your-device.example.com
BACKEND_API_BASE_URL=https://urbannest-ai-sales-copilot.onrender.com
API_V1_PREFIX=/api/v1
```

The MCP service connects outbound to the backend. The user device does not
need inbound access to Render. The MCP service authenticates the API's service
token and requires the original signed in user's bearer token on every tool
request, forwarding only that user token to the CRM API. The CRM API still
performs normal identity, role, team, and record authorization checks. Never
put either service token in frontend environment variables.

The hostname in the MCP URL must be permitted by `MCP_ALLOWED_HOSTS`; use
exact host entries. If the MCP host is on the same machine as the API, use
loopback URLs, for example `MCP_SERVER_URL=http://127.0.0.1:8001/mcp` and
`BACKEND_API_BASE_URL=http://127.0.0.1:8000`.

## Starting separate processes

Run each command from `backend` in its own terminal or service manager. These
commands are intentionally not part of the regular start script:

```powershell
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --env-file .env
```

```powershell
..\.venv\Scripts\python.exe -m uvicorn app.modules.ai.inference_service:app --host 0.0.0.0 --port 8002 --env-file .env
```

```powershell
..\.venv\Scripts\python.exe -m uvicorn app.modules.chatbot.mcp_service:app --host 0.0.0.0 --port 8001 --env-file .env
```

Only run and expose the services you choose to host. Restrict inference and
MCP ingress to the CRM API or private network. The MCP service's `/mcp` endpoint
uses Streamable HTTP and requires both credentials; its health/readiness can be
checked by the deployment platform without credentials only if configured at
the platform layer (the MCP transport itself protects HTTP requests).

The five read-only MCP tools search leads, fetch lead summaries, list tasks,
search estates, and fetch estate details. Tool inputs reject authority fields,
and output projections omit contact details, notes, and other unnecessary
fields. The model receives bounded results and cannot write CRM data.

## Local frontend

Use a development database. Configure the local API and services in
`backend/.env`, apply database migrations, make sure Ollama is running and the
chosen model has been pulled, and set `VITE_API_BASE_URL` and
`VITE_CHAT_ENABLED=true` in `frontend/.env.local`. Start the frontend with
`npm run dev`. The frontend calls the normal API at the configured base URL.

Conversation history belongs to the authenticated user and expires after 30
days. Chat stores the user/assistant text and tool names/statuses, but not
service credentials, user access tokens, or full CRM tool results.
