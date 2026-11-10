# UrbanNest Realty CRM — AI Sales Copilot

FastAPI and PostgreSQL backend for a role-scoped real-estate CRM. The project
includes lead and task workflows, AI-assisted lead features, audit events, and
server-enforced account permissions.

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

## Project documentation

- [Plan and ownership](docs/PLAN.md)
- [Architecture decisions](docs/approach.md)
- [Database ERD](docs/ERD.md)
- [Technology stack](docs/techstack.md)
- [API and authentication contract](docs/api-auth.md)

The frontend, live application URL, and demo credentials are not included in
this repository yet. Do not use real client data.
