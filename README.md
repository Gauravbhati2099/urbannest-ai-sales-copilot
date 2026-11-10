# UrbanNest Realty CRM — AI Sales Copilot

FastAPI and PostgreSQL backend with a React/TypeScript web app for a
role-scoped real-estate CRM. The project includes lead and task workflows,
AI-assisted lead endpoints, audit events, and server-enforced account
permissions.

## Backend development

1. Create a Python virtual environment and install dependencies:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
   ```

2. Copy `backend\.env.example` to `backend\.env` and configure PostgreSQL and a
   random `JWT_SECRET_KEY` (at least 32 bytes). Keep `.env` private.
3. From `backend`, run migrations and start the API:

   ```powershell
   ..\.venv\Scripts\alembic.exe upgrade head
   ..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
   ```

4. Open `http://127.0.0.1:8000/docs` for the API.

Run backend tests from `backend`:

```powershell
$env:PYTHONPATH = "."
..\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Frontend

The basic CRM frontend lives in `frontend`. It includes sign-in and forced
password change, role-scoped dashboard data, lead search and pipeline updates,
lead details and activity, follow-ups, CSV import for managers/owners, and the
shared activity feed. The theme preference is saved on the current browser.
On the leads page, press `/` to focus search; press `Escape` to dismiss an
open panel or dialog.

1. Create `frontend\.env.local` from `frontend\.env.example`. The default API
   URL is the deployed Render service; override `VITE_API_BASE_URL` when using
   a different API.
2. Install and start the frontend:

   ```powershell
   cd frontend
   npm install
   npm run dev
   ```

3. Before browser requests can reach the API, add the frontend origin to the
   backend Render service's `CORS_ORIGINS` environment variable. Use the exact
   origin, such as `https://your-frontend.onrender.com`, with no path or
   trailing slash; preserve any existing origins you still need.

For a Render Static Site, use `frontend` as the root directory, `npm install
&& npm run build` as the build command, and `dist` as the publish directory.
Set `VITE_API_BASE_URL` to
`https://urbannest-ai-sales-copilot.onrender.com` in the Static Site build
environment. After the site is deployed, add its exact URL to the API's
`CORS_ORIGINS` and redeploy the API.

The browser stores the bearer token in session storage, which clears when the
tab's session ends. Search requests are debounced and stale workspace refreshes
are cancelled. As this is an authenticated CRM rather than a public marketing
site, the frontend intentionally sets `noindex` metadata and disallows crawler
indexing. This frontend does not expose AI inference controls yet.

## Project documentation

- [Plan and ownership](docs/PLAN.md)
- [Architecture decisions](docs/approach.md)
- [Database ERD](docs/ERD.md)
- [Technology stack](docs/techstack.md)
- [API and authentication contract](docs/api-auth.md)

Do not use real client data. Demo credentials should be distributed securely
and never committed to this repository.
