import unittest
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import create_engine, event, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, configure_mappers
from sqlalchemy.schema import CreateTable

from app.db.base import Base
from app.db.models import (
    AIUsage,
    AIUsageStatus,
    Activity,
    ActivityType,
    AuditEvent,
    AuditVisibility,
    Lead,
    LeadScore,
    LeadSource,
    LeadStatus,
    LeadTemperature,
    Message,
    MessageChannel,
    MessageStatus,
    Task,
    Team,
    User,
    UserRole,
)


class DatabaseModelTests(unittest.TestCase):
    def setUp(self) -> None:
        configure_mappers()
        self.engine = create_engine("sqlite+pysqlite:///:memory:")

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(dbapi_connection, _) -> None:
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)

        self.team = Team(name="UrbanNest")
        other_team = Team(name="Other team")
        self.session.add_all([self.team, other_team])
        self.session.flush()

        self.owner = self.make_user(self.team.id, "owner@example.invalid", UserRole.OWNER)
        self.agent = self.make_user(self.team.id, "agent@example.invalid", UserRole.AGENT)
        self.other_agent = self.make_user(
            other_team.id, "other@example.invalid", UserRole.AGENT
        )
        self.session.add_all([self.owner, self.agent, self.other_agent])
        self.session.flush()

        self.lead = Lead(
            team_id=self.team.id,
            created_by=self.owner.id,
            assigned_to=self.agent.id,
            full_name="Fictional Lead",
            source=LeadSource.MANUAL,
            status=LeadStatus.NEW,
        )
        self.session.add(self.lead)
        self.session.commit()

    @staticmethod
    def make_user(team_id: UUID, email: str, role: UserRole) -> User:
        return User(
            team_id=team_id,
            full_name=email.split("@", maxsplit=1)[0],
            email=email,
            password_hash="test-hash",
            role=role,
        )

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def test_valid_same_team_relationships_persist(self) -> None:
        task = Task(
            team_id=self.team.id,
            lead_id=self.lead.id,
            assigned_to=self.agent.id,
            created_by=self.owner.id,
            title="Schedule follow-up",
            due_at=datetime.now(timezone.utc),
        )
        activity = Activity(
            team_id=self.team.id,
            lead_id=self.lead.id,
            actor_id=self.agent.id,
            type=ActivityType.NOTE,
            body="Fictional activity",
        )
        self.session.add_all([task, activity])
        self.session.commit()

        self.assertEqual(self.lead.assignee.id, self.agent.id)
        self.assertEqual(len(self.lead.tasks), 1)
        self.assertEqual(len(self.lead.activities), 1)

    def test_public_lead_and_system_activity_allow_missing_human_actor(self) -> None:
        public_lead = Lead(
            team_id=self.team.id,
            created_by=None,
            assigned_to=None,
            full_name="Public inquiry",
            source=LeadSource.WEBSITE,
            status=LeadStatus.NEW,
        )
        self.session.add(public_lead)
        self.session.flush()
        system_activity = Activity(
            team_id=self.team.id,
            lead_id=public_lead.id,
            actor_id=None,
            type=ActivityType.NOTE,
            body="Lead received from the public form",
        )
        self.session.add(system_activity)
        self.session.commit()

        self.assertIsNone(public_lead.creator)
        self.assertIsNone(system_activity.actor)

    def test_user_emails_are_normalized_and_case_insensitively_unique(self) -> None:
        normalized = self.make_user(
            self.team.id, "  New.User@Example.Invalid ", UserRole.AGENT
        )
        self.assertEqual(normalized.email, "new.user@example.invalid")
        self.session.add(normalized)
        self.session.commit()

        duplicate = self.make_user(
            self.team.id, "NEW.USER@example.invalid", UserRole.AGENT
        )
        self.session.add(duplicate)
        with self.assertRaises(IntegrityError):
            self.session.commit()
        self.session.rollback()

    def test_database_rejects_noncanonical_email_updates(self) -> None:
        with self.assertRaises(IntegrityError):
            self.session.execute(
                update(User)
                .where(User.id == self.agent.id)
                .values(email="Agent@Example.Invalid")
            )
            self.session.commit()
        self.session.rollback()

    def test_relationship_joins_include_team_scope(self) -> None:
        configure_mappers()
        relationships = (
            Lead.assignee,
            Lead.creator,
            Lead.activities,
            Lead.tasks,
            Lead.scores,
            Lead.messages,
            Lead.ai_usage_records,
        )
        joins = [str(relationship.property.primaryjoin) for relationship in relationships]

        self.assertTrue(all("team_id" in join for join in joins))

    def test_postgres_score_factors_use_jsonb(self) -> None:
        ddl = str(CreateTable(LeadScore.__table__).compile(dialect=postgresql.dialect()))
        self.assertIn("factors JSONB", ddl)

    def test_audit_changes_use_postgres_jsonb(self) -> None:
        ddl = str(CreateTable(AuditEvent.__table__).compile(dialect=postgresql.dialect()))
        self.assertIn("changes JSONB", ddl)

        audit_event = AuditEvent(
            team_id=self.team.id,
            actor_id=self.agent.id,
            actor_name=self.agent.full_name,
            lead_id=self.lead.id,
            entity_type="lead",
            entity_id=self.lead.id,
            action="updated",
            visibility=AuditVisibility.TEAM,
            summary="Lead status changed",
            changes={"status": {"from": "new", "to": "contacted"}},
        )
        self.session.add(audit_event)
        self.session.commit()
        self.assertEqual(
            audit_event.changes,
            {"status": {"from": "new", "to": "contacted"}},
        )

    def test_ai_usage_normalizes_currency_and_requires_it_with_cost(self) -> None:
        usage = AIUsage(
            team_id=self.team.id,
            user_id=self.agent.id,
            feature="lead_score",
            provider="test",
            model="test",
            status=AIUsageStatus.SUCCEEDED,
            estimated_cost=Decimal("0.001250"),
            cost_currency=" usd ",
            request_id="request-123",
        )
        self.assertEqual(usage.cost_currency, "USD")
        self.session.add(usage)
        self.session.commit()

        invalid_usage = AIUsage(
            team_id=self.team.id,
            user_id=self.agent.id,
            feature="lead_score",
            provider="test",
            model="test",
            status=AIUsageStatus.SUCCEEDED,
            estimated_cost=Decimal("0.001"),
        )
        self.session.add(invalid_usage)
        with self.assertRaises(IntegrityError):
            self.session.commit()
        self.session.rollback()

    def test_child_records_reject_cross_team_references(self) -> None:
        now = datetime.now(timezone.utc)
        invalid_rows = [
            Activity(
                team_id=self.team.id,
                lead_id=self.lead.id,
                actor_id=self.other_agent.id,
                type=ActivityType.NOTE,
                body="Invalid cross-team actor",
            ),
            Task(
                team_id=self.team.id,
                lead_id=self.lead.id,
                assigned_to=self.other_agent.id,
                created_by=self.owner.id,
                title="Invalid cross-team assignee",
                due_at=now,
            ),
            LeadScore(
                team_id=self.team.id,
                lead_id=self.lead.id,
                requested_by=self.other_agent.id,
                score=50,
                temperature=LeadTemperature.WARM,
                reason="Test",
                provider="test",
                model="test",
                context_hash="0" * 64,
            ),
            Message(
                team_id=self.team.id,
                lead_id=self.lead.id,
                drafted_by=self.other_agent.id,
                channel=MessageChannel.EMAIL,
                tone="neutral",
                body="Test draft",
                status=MessageStatus.DRAFT,
            ),
            AIUsage(
                team_id=self.team.id,
                user_id=self.other_agent.id,
                lead_id=self.lead.id,
                feature="score",
                provider="test",
                model="test",
                status=AIUsageStatus.SUCCEEDED,
            ),
        ]

        for row in invalid_rows:
            with self.subTest(model=type(row).__name__):
                self.session.add(row)
                with self.assertRaises(IntegrityError):
                    self.session.commit()
                self.session.rollback()


if __name__ == "__main__":
    unittest.main()
