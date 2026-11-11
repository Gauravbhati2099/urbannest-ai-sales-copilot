from __future__ import annotations

import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.modules.audit.router import router as audit_router
from app.modules.auth.router import router as auth_router, users_router
from app.modules.ai.router import router as ai_router
from app.modules.leads.router import public_router, router as leads_router
from app.modules.tasks.router import router as tasks_router
from app.modules.dashboard.router import router as dashboard_router


def create_app() -> FastAPI:
    api_prefix = os.getenv("API_V1_PREFIX", "/api/v1").rstrip("/")
    if not api_prefix.startswith("/"):
        raise RuntimeError("API_V1_PREFIX must start with '/'")
    try:
        ZoneInfo(os.getenv("APP_TIMEZONE", "Asia/Kolkata"))
    except ZoneInfoNotFoundError as exc:
        raise RuntimeError("APP_TIMEZONE must be a valid IANA timezone") from exc

    app = FastAPI(title=os.getenv("APP_NAME", "Infinaut CRM API"), version="1.0.0")
    origins = [
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "").split(",")
        if origin.strip()
    ]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH"],
            allow_headers=["Authorization", "Content-Type"],
        )

    app.include_router(auth_router, prefix=api_prefix)
    app.include_router(users_router, prefix=api_prefix)
    app.include_router(audit_router, prefix=api_prefix)
    app.include_router(ai_router, prefix=api_prefix)
    app.include_router(leads_router, prefix=api_prefix)
    app.include_router(tasks_router, prefix=api_prefix)
    app.include_router(dashboard_router, prefix=api_prefix)
    app.include_router(public_router, prefix=api_prefix)

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        """Report that the API process is responsive."""
        return {"status": "ok"}

    return app


app = create_app()
