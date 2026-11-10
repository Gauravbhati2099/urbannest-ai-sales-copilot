from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates
from sqlalchemy.sql import and_

from app.db.base import Base


def enum_type(enum_class: type[Enum], name: str) -> SqlEnum:
    return SqlEnum(
        enum_class,
        name=name,
        native_enum=False,
        create_constraint=True,
        values_callable=lambda members: [member.value for member in members],
        validate_strings=True,
    )


class UserRole(str, Enum):
    OWNER = "owner"
    MANAGER = "manager"
    AGENT = "agent"


class LeadStatus(str, Enum):
    NEW = "new"
    CONTACTED = "contacted"
    SITE_VISIT = "site_visit"
    NEGOTIATION = "negotiation"
    WON = "won"
    LOST = "lost"


class LeadSource(str, Enum):
    WEBSITE = "website"
    NINETY_NINE_ACRES = "99acres"
    MAGICBRICKS = "magicbricks"
    INSTAGRAM = "instagram"
    WHATSAPP = "whatsapp"
    WALK_IN = "walk_in"
    MANUAL = "manual"
    CSV_IMPORT = "csv_import"
    OTHER = "other"


class ActivityType(str, Enum):
    CALL = "call"
    NOTE = "note"
    SITE_VISIT = "site_visit"
    STATUS_CHANGE = "status_change"
    EMAIL = "email"
    WHATSAPP = "whatsapp"
    ASSIGNMENT_CHANGE = "assignment_change"
    OTHER = "other"


class AuditVisibility(str, Enum):
    TEAM = "team"
    ACTOR = "actor"
    ADMIN = "admin"


class TaskStatus(str, Enum):
    OPEN = "open"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class LeadTemperature(str, Enum):
    HOT = "hot"
    WARM = "warm"
    COLD = "cold"


class MessageChannel(str, Enum):
    WHATSAPP = "whatsapp"
    EMAIL = "email"


class MessageStatus(str, Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"


class AIUsageStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TimestampMixin(CreatedAtMixin):
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class Team(TimestampMixin, Base):
    __tablename__ = "teams"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(160), nullable=False)

    users: Mapped[list[User]] = relationship(
        back_populates="team", foreign_keys="User.team_id"
    )
    leads: Mapped[list[Lead]] = relationship(
        back_populates="team", foreign_keys="Lead.team_id"
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("id", "team_id", name="uq_users_id_team"),
        CheckConstraint(
            "email = lower(trim(email))", name="ck_users_email_normalized"
        ),
        Index("uq_users_email_lower", func.lower(text("email")), unique=True),
        Index("ix_users_team_role", "team_id", "role"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    team_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False
    )
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        enum_type(UserRole, "user_role"), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    auth_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    team: Mapped[Team] = relationship(back_populates="users", foreign_keys=[team_id])
    assigned_leads: Mapped[list[Lead]] = relationship(
        back_populates="assignee",
        foreign_keys="Lead.assigned_to",
        primaryjoin=lambda: and_(
            User.id == Lead.assigned_to, User.team_id == Lead.team_id
        ),
    )
    created_leads: Mapped[list[Lead]] = relationship(
        back_populates="creator",
        foreign_keys="Lead.created_by",
        primaryjoin=lambda: and_(
            User.id == Lead.created_by, User.team_id == Lead.team_id
        ),
    )
    activities: Mapped[list[Activity]] = relationship(
        back_populates="actor",
        foreign_keys="Activity.actor_id",
        primaryjoin=lambda: and_(
            User.id == Activity.actor_id, User.team_id == Activity.team_id
        ),
    )
    assigned_tasks: Mapped[list[Task]] = relationship(
        back_populates="assignee",
        foreign_keys="Task.assigned_to",
        primaryjoin=lambda: and_(
            User.id == Task.assigned_to, User.team_id == Task.team_id
        ),
    )
    created_tasks: Mapped[list[Task]] = relationship(
        back_populates="creator",
        foreign_keys="Task.created_by",
        primaryjoin=lambda: and_(
            User.id == Task.created_by, User.team_id == Task.team_id
        ),
    )
    requested_scores: Mapped[list[LeadScore]] = relationship(
        back_populates="requested_by_user",
        foreign_keys="LeadScore.requested_by",
        primaryjoin=lambda: and_(
            User.id == LeadScore.requested_by, User.team_id == LeadScore.team_id
        ),
    )
    drafted_messages: Mapped[list[Message]] = relationship(
        back_populates="drafted_by_user",
        foreign_keys="Message.drafted_by",
        primaryjoin=lambda: and_(
            User.id == Message.drafted_by, User.team_id == Message.team_id
        ),
    )
    ai_usage_records: Mapped[list[AIUsage]] = relationship(
        back_populates="user",
        foreign_keys="AIUsage.user_id",
        primaryjoin=lambda: and_(
            User.id == AIUsage.user_id, User.team_id == AIUsage.team_id
        ),
    )

    @validates("email")
    def normalize_email(self, _key: str, value: str) -> str:
        del _key
        return value.strip().lower()


class Lead(TimestampMixin, Base):
    __tablename__ = "leads"
    __table_args__ = (
        UniqueConstraint("id", "team_id", name="uq_leads_id_team"),
        ForeignKeyConstraint(
            ["assigned_to", "team_id"],
            ["users.id", "users.team_id"],
            name="fk_leads_assignee_team",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["created_by", "team_id"],
            ["users.id", "users.team_id"],
            name="fk_leads_creator_team",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "budget_min_inr IS NULL OR budget_min_inr >= 0",
            name="ck_leads_budget_min_nonnegative",
        ),
        CheckConstraint(
            "budget_max_inr IS NULL OR budget_max_inr >= 0",
            name="ck_leads_budget_max_nonnegative",
        ),
        CheckConstraint(
            "budget_min_inr IS NULL OR budget_max_inr IS NULL OR "
            "budget_min_inr <= budget_max_inr",
            name="ck_leads_budget_range",
        ),
        CheckConstraint("bhk IS NULL OR bhk > 0", name="ck_leads_bhk_positive"),
        Index("ix_leads_team_status", "team_id", "status"),
        Index("ix_leads_team_assignee_status", "team_id", "assigned_to", "status"),
        Index("ix_leads_team_created_at", "team_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    team_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False
    )
    assigned_to: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(40))
    source: Mapped[LeadSource] = mapped_column(
        enum_type(LeadSource, "lead_source"),
        nullable=False,
        default=LeadSource.MANUAL,
        server_default=text("'manual'"),
    )
    status: Mapped[LeadStatus] = mapped_column(
        enum_type(LeadStatus, "lead_status"),
        nullable=False,
        default=LeadStatus.NEW,
        server_default=text("'new'"),
    )
    budget_min_inr: Mapped[int | None] = mapped_column(Integer)
    budget_max_inr: Mapped[int | None] = mapped_column(Integer)
    bhk: Mapped[int | None] = mapped_column(Integer)
    preferred_location: Mapped[str | None] = mapped_column(String(160))
    notes: Mapped[str | None] = mapped_column(Text)

    team: Mapped[Team] = relationship(back_populates="leads", foreign_keys=[team_id])
    assignee: Mapped[User | None] = relationship(
        back_populates="assigned_leads",
        foreign_keys=[assigned_to],
        primaryjoin=lambda: and_(
            Lead.assigned_to == User.id, Lead.team_id == User.team_id
        ),
    )
    creator: Mapped[User | None] = relationship(
        back_populates="created_leads",
        foreign_keys=[created_by],
        primaryjoin=lambda: and_(
            Lead.created_by == User.id, Lead.team_id == User.team_id
        ),
    )
    activities: Mapped[list[Activity]] = relationship(
        back_populates="lead",
        foreign_keys="Activity.lead_id",
        primaryjoin=lambda: and_(
            Lead.id == Activity.lead_id, Lead.team_id == Activity.team_id
        ),
    )
    tasks: Mapped[list[Task]] = relationship(
        back_populates="lead",
        foreign_keys="Task.lead_id",
        primaryjoin=lambda: and_(Lead.id == Task.lead_id, Lead.team_id == Task.team_id),
    )
    scores: Mapped[list[LeadScore]] = relationship(
        back_populates="lead",
        foreign_keys="LeadScore.lead_id",
        primaryjoin=lambda: and_(
            Lead.id == LeadScore.lead_id, Lead.team_id == LeadScore.team_id
        ),
    )
    messages: Mapped[list[Message]] = relationship(
        back_populates="lead",
        foreign_keys="Message.lead_id",
        primaryjoin=lambda: and_(
            Lead.id == Message.lead_id, Lead.team_id == Message.team_id
        ),
    )
    ai_usage_records: Mapped[list[AIUsage]] = relationship(
        back_populates="lead",
        foreign_keys="AIUsage.lead_id",
        primaryjoin=lambda: and_(
            Lead.id == AIUsage.lead_id, Lead.team_id == AIUsage.team_id
        ),
    )


class Activity(CreatedAtMixin, Base):
    __tablename__ = "activities"
    __table_args__ = (
        ForeignKeyConstraint(
            ["lead_id", "team_id"],
            ["leads.id", "leads.team_id"],
            name="fk_activities_lead_team",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["actor_id", "team_id"],
            ["users.id", "users.team_id"],
            name="fk_activities_actor_team",
            ondelete="RESTRICT",
        ),
        Index("ix_activities_team_lead_occurred", "team_id", "lead_id", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    team_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False
    )
    lead_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    type: Mapped[ActivityType] = mapped_column(
        enum_type(ActivityType, "activity_type"), nullable=False
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    lead: Mapped[Lead] = relationship(
        back_populates="activities",
        foreign_keys=[lead_id],
        primaryjoin=lambda: and_(
            Activity.lead_id == Lead.id, Activity.team_id == Lead.team_id
        ),
    )
    actor: Mapped[User | None] = relationship(
        back_populates="activities",
        foreign_keys=[actor_id],
        primaryjoin=lambda: and_(
            Activity.actor_id == User.id, Activity.team_id == User.team_id
        ),
    )


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["lead_id", "team_id"],
            ["leads.id", "leads.team_id"],
            name="fk_tasks_lead_team",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["assigned_to", "team_id"],
            ["users.id", "users.team_id"],
            name="fk_tasks_assignee_team",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["created_by", "team_id"],
            ["users.id", "users.team_id"],
            name="fk_tasks_creator_team",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(status = 'completed' AND completed_at IS NOT NULL) OR "
            "(status != 'completed' AND completed_at IS NULL)",
            name="ck_tasks_completion_time",
        ),
        Index("ix_tasks_team_assignee_status_due", "team_id", "assigned_to", "status", "due_at"),
        Index("ix_tasks_team_lead_due", "team_id", "lead_id", "due_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    team_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False
    )
    lead_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    assigned_to: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    created_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[TaskStatus] = mapped_column(
        enum_type(TaskStatus, "task_status"),
        nullable=False,
        default=TaskStatus.OPEN,
        server_default=text("'open'"),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    lead: Mapped[Lead] = relationship(
        back_populates="tasks",
        foreign_keys=[lead_id],
        primaryjoin=lambda: and_(Task.lead_id == Lead.id, Task.team_id == Lead.team_id),
    )
    assignee: Mapped[User] = relationship(
        back_populates="assigned_tasks",
        foreign_keys=[assigned_to],
        primaryjoin=lambda: and_(
            Task.assigned_to == User.id, Task.team_id == User.team_id
        ),
    )
    creator: Mapped[User] = relationship(
        back_populates="created_tasks",
        foreign_keys=[created_by],
        primaryjoin=lambda: and_(Task.created_by == User.id, Task.team_id == User.team_id),
    )


class AuditEvent(CreatedAtMixin, Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["actor_id", "team_id"],
            ["users.id", "users.team_id"],
            name="fk_audit_events_actor_team",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["lead_id", "team_id"],
            ["leads.id", "leads.team_id"],
            name="fk_audit_events_lead_team",
            ondelete="RESTRICT",
        ),
        Index("ix_audit_events_team_created", "team_id", "created_at"),
        Index(
            "ix_audit_events_team_lead_created",
            "team_id",
            "lead_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    team_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False
    )
    actor_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    actor_name: Mapped[str | None] = mapped_column(String(160))
    lead_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    visibility: Mapped[AuditVisibility] = mapped_column(
        enum_type(AuditVisibility, "audit_visibility"),
        nullable=False,
    )
    summary: Mapped[str] = mapped_column(String(255), nullable=False)
    changes: Mapped[dict[str, object] | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql")
    )


class AuditReadCursor(Base):
    __tablename__ = "audit_read_cursors"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "team_id"],
            ["users.id", "users.team_id"],
            name="fk_audit_read_cursors_user_team",
            ondelete="CASCADE",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    team_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    last_read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RateLimitBucket(Base):
    __tablename__ = "rate_limit_buckets"
    __table_args__ = (
        Index("ix_rate_limit_buckets_window_start", "window_start"),
    )

    scope: Mapped[str] = mapped_column(String(40), primary_key=True)
    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False)


class LeadScore(CreatedAtMixin, Base):
    __tablename__ = "ai_scores"
    __table_args__ = (
        ForeignKeyConstraint(
            ["lead_id", "team_id"],
            ["leads.id", "leads.team_id"],
            name="fk_ai_scores_lead_team",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["requested_by", "team_id"],
            ["users.id", "users.team_id"],
            name="fk_ai_scores_requester_team",
            ondelete="RESTRICT",
        ),
        CheckConstraint("score BETWEEN 0 AND 100", name="ck_ai_scores_range"),
        CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0",
            name="ck_ai_scores_input_tokens_nonnegative",
        ),
        CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name="ck_ai_scores_output_tokens_nonnegative",
        ),
        Index("ix_ai_scores_team_lead_created", "team_id", "lead_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    team_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False
    )
    lead_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    requested_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    temperature: Mapped[LeadTemperature] = mapped_column(
        enum_type(LeadTemperature, "lead_temperature"), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    factors: Mapped[dict[str, object] | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql")
    )
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    context_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    is_stale: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)

    lead: Mapped[Lead] = relationship(
        back_populates="scores",
        foreign_keys=[lead_id],
        primaryjoin=lambda: and_(
            LeadScore.lead_id == Lead.id, LeadScore.team_id == Lead.team_id
        ),
    )
    requested_by_user: Mapped[User] = relationship(
        back_populates="requested_scores",
        foreign_keys=[requested_by],
        primaryjoin=lambda: and_(
            LeadScore.requested_by == User.id, LeadScore.team_id == User.team_id
        ),
    )


class Message(TimestampMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["lead_id", "team_id"],
            ["leads.id", "leads.team_id"],
            name="fk_messages_lead_team",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["drafted_by", "team_id"],
            ["users.id", "users.team_id"],
            name="fk_messages_drafter_team",
            ondelete="RESTRICT",
        ),
        Index("ix_messages_team_lead_created", "team_id", "lead_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    team_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False
    )
    lead_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    drafted_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    channel: Mapped[MessageChannel] = mapped_column(
        enum_type(MessageChannel, "message_channel"), nullable=False
    )
    tone: Mapped[str] = mapped_column(String(40), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[MessageStatus] = mapped_column(
        enum_type(MessageStatus, "message_status"),
        nullable=False,
        default=MessageStatus.DRAFT,
        server_default=text("'draft'"),
    )
    provider: Mapped[str | None] = mapped_column(String(80))
    model: Mapped[str | None] = mapped_column(String(120))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_message_id: Mapped[str | None] = mapped_column(String(255))

    lead: Mapped[Lead] = relationship(
        back_populates="messages",
        foreign_keys=[lead_id],
        primaryjoin=lambda: and_(
            Message.lead_id == Lead.id, Message.team_id == Lead.team_id
        ),
    )
    drafted_by_user: Mapped[User] = relationship(
        back_populates="drafted_messages",
        foreign_keys=[drafted_by],
        primaryjoin=lambda: and_(
            Message.drafted_by == User.id, Message.team_id == User.team_id
        ),
    )


class AIUsage(CreatedAtMixin, Base):
    __tablename__ = "ai_usage"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "team_id"],
            ["users.id", "users.team_id"],
            name="fk_ai_usage_user_team",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["lead_id", "team_id"],
            ["leads.id", "leads.team_id"],
            name="fk_ai_usage_lead_team",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0",
            name="ck_ai_usage_input_tokens_nonnegative",
        ),
        CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name="ck_ai_usage_output_tokens_nonnegative",
        ),
        CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0",
            name="ck_ai_usage_latency_nonnegative",
        ),
        CheckConstraint(
            "estimated_cost IS NULL OR estimated_cost >= 0",
            name="ck_ai_usage_cost_nonnegative",
        ),
        CheckConstraint(
            "(estimated_cost IS NULL AND cost_currency IS NULL) OR "
            "(estimated_cost IS NOT NULL AND cost_currency IS NOT NULL)",
            name="ck_ai_usage_cost_currency_pair",
        ),
        CheckConstraint(
            "cost_currency IS NULL OR length(cost_currency) = 3",
            name="ck_ai_usage_cost_currency_length",
        ),
        CheckConstraint(
            "cost_currency IS NULL OR cost_currency = upper(cost_currency)",
            name="ck_ai_usage_cost_currency_uppercase",
        ),
        Index("ix_ai_usage_team_created", "team_id", "created_at"),
        Index("ix_ai_usage_team_feature_created", "team_id", "feature", "created_at"),
        Index("ix_ai_usage_request_id", "request_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    team_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    lead_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    feature: Mapped[str] = mapped_column(String(80), nullable=False)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    cost_currency: Mapped[str | None] = mapped_column(String(3))
    request_id: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[AIUsageStatus] = mapped_column(
        enum_type(AIUsageStatus, "ai_usage_status"), nullable=False
    )
    error_category: Mapped[str | None] = mapped_column(String(80))

    user: Mapped[User] = relationship(
        back_populates="ai_usage_records",
        foreign_keys=[user_id],
        primaryjoin=lambda: and_(AIUsage.user_id == User.id, AIUsage.team_id == User.team_id),
    )
    lead: Mapped[Lead | None] = relationship(
        back_populates="ai_usage_records",
        foreign_keys=[lead_id],
        primaryjoin=lambda: and_(
            AIUsage.lead_id == Lead.id, AIUsage.team_id == Lead.team_id
        ),
    )

    @validates("cost_currency")
    def normalize_cost_currency(
        self, _key: str, value: str | None
    ) -> str | None:
        del _key
        return value.strip().upper() if value is not None else None
