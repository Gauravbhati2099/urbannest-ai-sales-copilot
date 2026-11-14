from __future__ import annotations

from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import User, UserRole
from app.db.session import get_db
from app.core.security import decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)
DatabaseSession = Annotated[Session, Depends(get_db)]


def is_team_record_manager(user: User) -> bool:
    return user.is_superuser or user.role in {
        UserRole.OWNER,
        UserRole.CO_OWNER,
        UserRole.MANAGER,
    }


def can_manage_team_users(user: User) -> bool:
    return (
        user.is_superuser
        or user.role in {UserRole.OWNER, UserRole.MANAGER}
        or (user.role is UserRole.CO_OWNER and user.can_manage_users)
    )


def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ],
    session: DatabaseSession,
    request: Request,
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized

    try:
        user_id, auth_version = decode_access_token(credentials.credentials)
    except jwt.InvalidTokenError:
        raise unauthorized from None

    user = session.scalar(select(User).where(User.id == user_id))
    if user is None or not user.is_active or user.auth_version != auth_version:
        raise unauthorized
    if user.must_change_password and not request.url.path.endswith(
        ("/auth/change-password", "/auth/me")
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "password_change_required",
                "message": "Change your temporary password before using the CRM",
            },
        )
    if user.role is UserRole.CO_OWNER and not user.is_superuser:
        path = request.url.path.rstrip("/")
        if path.endswith(("/auth/me", "/auth/me/profile", "/auth/change-password")):
            return user
        if path.endswith("/users/org-chart") and request.method == "GET":
            return user
        if (
            path.endswith("/leads/assignees")
            and request.method == "GET"
            and user.can_write
        ):
            return user
        if path.endswith("/users") and request.method == "GET" and user.can_manage_users:
            return user
        permitted = (
            user.can_read
            if request.method in {"GET", "HEAD"}
            else user.can_delete
            if request.method == "DELETE"
            else user.can_write
        )
        if not permitted:
            permission = (
                "read"
                if request.method in {"GET", "HEAD"}
                else "delete"
                if request.method == "DELETE"
                else "write"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": f"{permission}_permission_required",
                    "message": f"Your account does not have {permission} access",
                },
            )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
