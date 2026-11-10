from __future__ import annotations

import secrets
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, status
from pwdlib import PasswordHash
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.dependencies import CurrentUser, DatabaseSession
from app.core.rate_limit import (
    clear_rate_limit,
    client_address,
    enforce_rate_limits,
    rate_limit_setting,
)
from app.core.security import create_access_token
from app.db.models import AuditVisibility, Team, User, UserRole
from app.modules.auth.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    PasswordResetResponse,
    UserCreatedResponse,
    UserCreateRequest,
    UserRead,
    UserUpdateRequest,
)
from app.modules.audit.service import record_audit_event

router = APIRouter(prefix="/auth", tags=["auth"])
users_router = APIRouter(prefix="/users", tags=["user administration"])
password_hash = PasswordHash.recommended()
DUMMY_PASSWORD_HASH = password_hash.hash("unmatched-user-password-check")
MANAGER_ROLES = {UserRole.OWNER, UserRole.MANAGER}


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="User not found")


def _managed_user(
    session: DatabaseSession,
    manager: User,
    user_id: UUID,
) -> User:
    user = session.scalar(
        select(User).where(User.id == user_id, User.team_id == manager.team_id)
    )
    if user is None:
        raise _not_found()
    if manager.role is UserRole.MANAGER and user.role is not UserRole.AGENT:
        raise _not_found()
    return user


def _ensure_active_owner_remains(
    session: DatabaseSession,
    user: User,
    *,
    new_role: UserRole | None,
    new_is_active: bool | None,
) -> None:
    loses_owner = user.role is UserRole.OWNER and (
        (new_role is not None and new_role is not UserRole.OWNER)
        or new_is_active is False
    )
    if not loses_owner:
        return
    other_active_owners = session.scalar(
        select(func.count(User.id)).where(
            User.team_id == user.team_id,
            User.role == UserRole.OWNER,
            User.is_active.is_(True),
            User.id != user.id,
        )
    )
    if not other_active_owners:
        raise HTTPException(
            status_code=409,
            detail="The team must retain at least one active owner",
        )


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    request: Request,
    session: DatabaseSession,
) -> LoginResponse:
    window_seconds = rate_limit_setting("LOGIN_RATE_WINDOW_SECONDS", 900)
    enforce_rate_limits(
        session,
        limits=(
            (
                "login_ip",
                client_address(request),
                rate_limit_setting("LOGIN_RATE_LIMIT_PER_IP", 30),
            ),
            (
                "login_email",
                payload.email,
                rate_limit_setting("LOGIN_RATE_LIMIT_PER_EMAIL", 10),
            ),
        ),
        window_seconds=window_seconds,
    )
    user = session.scalar(select(User).where(User.email == payload.email))
    stored_hash = user.password_hash if user is not None else DUMMY_PASSWORD_HASH
    password_is_valid = password_hash.verify(payload.password, stored_hash)
    if user is None or not password_is_valid or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    clear_rate_limit(session, scope="login_email", key=payload.email)
    token, expires_in = create_access_token(user)
    return LoginResponse(
        access_token=token,
        expires_in=expires_in,
        user=UserRead.model_validate(user),
    )


@router.post("/change-password", response_model=LoginResponse)
def change_password(
    payload: ChangePasswordRequest,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> LoginResponse:
    if not password_hash.verify(payload.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if password_hash.verify(payload.new_password, current_user.password_hash):
        raise HTTPException(
            status_code=422,
            detail="New password must differ from the current password",
        )
    current_user.password_hash = password_hash.hash(payload.new_password)
    current_user.must_change_password = False
    current_user.auth_version += 1
    record_audit_event(
        session,
        team_id=current_user.team_id,
        actor_id=current_user.id,
        lead_id=None,
        entity_type="user",
        entity_id=current_user.id,
        action="password_changed",
        visibility=AuditVisibility.ACTOR,
        summary="Your password was changed",
    )
    session.commit()
    session.refresh(current_user)
    token, expires_in = create_access_token(current_user)
    return LoginResponse(
        access_token=token,
        expires_in=expires_in,
        user=UserRead.model_validate(current_user),
    )


@router.get("/me", response_model=UserRead)
def read_current_user(current_user: CurrentUser) -> UserRead:
    return UserRead.model_validate(current_user)


@users_router.get("", response_model=list[UserRead])
def list_team_users(
    current_user: CurrentUser,
    session: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    is_active: bool | None = None,
) -> list[User]:
    if current_user.role not in MANAGER_ROLES:
        raise HTTPException(status_code=403, detail="Forbidden")
    statement = select(User).where(User.team_id == current_user.team_id)
    if current_user.role is UserRole.MANAGER:
        statement = statement.where(User.role == UserRole.AGENT)
    if is_active is not None:
        statement = statement.where(User.is_active.is_(is_active))
    return list(
        session.scalars(
            statement.order_by(User.full_name, User.email).limit(limit).offset(offset)
        ).all()
    )


@users_router.post("", response_model=UserCreatedResponse, status_code=201)
def create_team_user(
    payload: UserCreateRequest,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> UserCreatedResponse:
    if current_user.role not in MANAGER_ROLES:
        raise HTTPException(status_code=403, detail="Forbidden")
    if current_user.role is UserRole.MANAGER and payload.role is not UserRole.AGENT:
        raise HTTPException(status_code=403, detail="Managers may only create agents")
    team = session.scalar(select(Team).where(Team.id == current_user.team_id))
    if team is None:
        raise HTTPException(status_code=409, detail="User team no longer exists")

    temporary_password = secrets.token_urlsafe(24)
    user = User(
        team_id=current_user.team_id,
        full_name=payload.full_name,
        email=payload.email,
        password_hash=password_hash.hash(temporary_password),
        role=payload.role,
        is_active=True,
        auth_version=0,
        must_change_password=True,
    )
    session.add(user)
    try:
        session.flush()
        record_audit_event(
            session,
            team_id=user.team_id,
            actor_id=current_user.id,
            lead_id=None,
            entity_type="user",
            entity_id=user.id,
            action="created",
            visibility=AuditVisibility.ADMIN,
            summary="A team user account was created",
            changes={"role": user.role.value},
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="An account with this email already exists",
        ) from exc
    session.refresh(user)
    return UserCreatedResponse(
        user=UserRead.model_validate(user),
        temporary_password=temporary_password,
    )


@users_router.patch("/{user_id}", response_model=UserRead)
def update_team_user(
    user_id: UUID,
    payload: UserUpdateRequest,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> UserRead:
    if current_user.role not in MANAGER_ROLES:
        raise HTTPException(status_code=403, detail="Forbidden")
    user = _managed_user(session, current_user, user_id)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="Provide at least one field to update")
    if any(value is None for value in changes.values()):
        raise HTTPException(status_code=422, detail="User fields cannot be null")
    if current_user.role is UserRole.MANAGER and "role" in changes:
        raise HTTPException(status_code=403, detail="Only owners may change user roles")
    if user.id == current_user.id and changes.get("is_active") is False:
        raise HTTPException(status_code=409, detail="You cannot deactivate your own account")
    _ensure_active_owner_remains(
        session,
        user,
        new_role=changes.get("role"),
        new_is_active=changes.get("is_active"),
    )
    should_revoke_sessions = (
        ("role" in changes and changes["role"] != user.role)
        or changes.get("is_active") is False
    )
    audit_changes = {}
    for field, value in changes.items():
        old_value = getattr(user, field)
        if old_value == value:
            continue
        if field == "role":
            audit_changes[field] = {
                "from": old_value.value,
                "to": value.value,
            }
        elif field == "is_active":
            audit_changes[field] = {"from": old_value, "to": value}
        elif field == "full_name":
            audit_changes[field] = {"changed": True}
        setattr(user, field, value)
    if should_revoke_sessions:
        user.auth_version += 1
    if audit_changes:
        record_audit_event(
            session,
            team_id=user.team_id,
            actor_id=current_user.id,
            lead_id=None,
            entity_type="user",
            entity_id=user.id,
            action="updated",
            visibility=AuditVisibility.ADMIN,
            summary="A team user account was updated",
            changes=audit_changes,
        )
    session.commit()
    session.refresh(user)
    return UserRead.model_validate(user)


@users_router.post("/{user_id}/password-reset", response_model=PasswordResetResponse)
def reset_user_password(
    user_id: UUID,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> PasswordResetResponse:
    if current_user.role not in MANAGER_ROLES:
        raise HTTPException(status_code=403, detail="Forbidden")
    user = _managed_user(session, current_user, user_id)
    if user.id == current_user.id:
        raise HTTPException(
            status_code=409,
            detail="Use the change-password endpoint to change your own password",
        )
    if not user.is_active:
        raise HTTPException(status_code=409, detail="Cannot reset an inactive account")
    temporary_password = secrets.token_urlsafe(24)
    user.password_hash = password_hash.hash(temporary_password)
    user.auth_version += 1
    user.must_change_password = True
    record_audit_event(
        session,
        team_id=user.team_id,
        actor_id=current_user.id,
        lead_id=None,
        entity_type="user",
        entity_id=user.id,
        action="password_reset",
        visibility=AuditVisibility.ADMIN,
        summary="A team user's password was reset",
    )
    session.commit()
    return PasswordResetResponse(
        user_id=user.id,
        temporary_password=temporary_password,
    )
