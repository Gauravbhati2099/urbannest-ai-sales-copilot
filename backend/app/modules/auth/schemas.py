from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.normalization import normalize_email, normalize_person_name
from app.modules.leads.schemas import PhoneFields
from app.db.models import UserRole


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return normalize_email(value, required=True) or ""


class PasswordRecoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return normalize_email(value, required=True) or ""


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    team_id: UUID
    manager_id: UUID | None
    full_name: str
    email: str
    phone: str | None
    phone_country_code: str | None
    phone_region: str | None
    phone_national_number: str | None
    role: UserRole
    is_superuser: bool
    can_read: bool
    can_write: bool
    can_delete: bool
    can_manage_users: bool
    is_active: bool
    must_change_password: bool


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserRead


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)

    @field_validator("new_password")
    @classmethod
    def reject_whitespace_only_password(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Password must not be blank")
        return value


class UserCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=1, max_length=160)
    email: str = Field(min_length=3, max_length=320)
    role: UserRole
    manager_id: UUID | None = None
    can_read: bool | None = None
    can_write: bool | None = None
    can_delete: bool | None = None
    can_manage_users: bool | None = None

    @field_validator("full_name")
    @classmethod
    def normalize_full_name(cls, value: str) -> str:
        return normalize_person_name(value)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return normalize_email(value, required=True) or ""


class UserUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(default=None, min_length=1, max_length=160)
    manager_id: UUID | None = None
    role: UserRole | None = None
    is_active: bool | None = None
    can_read: bool | None = None
    can_write: bool | None = None
    can_delete: bool | None = None
    can_manage_users: bool | None = None

    @field_validator("full_name")
    @classmethod
    def normalize_full_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_person_name(value)


class ProfileUpdateRequest(PhoneFields):
    pass


class BulkPasswordResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation: str = Field(pattern=r"^RESET ALL$")


class UserCreatedResponse(BaseModel):
    user: UserRead
    temporary_password: str


class PasswordResetResponse(BaseModel):
    user_id: UUID
    temporary_password: str
    must_change_password: bool = True


class PasswordRecoveryResponse(BaseModel):
    message: str = (
        "If an active account matches that email, its team owner can help with a reset."
    )
