from __future__ import annotations

import csv
import io
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from fastapi.testclient import TestClient
from pwdlib import PasswordHash
from sqlalchemy import create_engine, event, func, make_url, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import (
    AIUsage,
    AIUsageStatus,
    Activity,
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
    RateLimitBucket,
    Task,
    Team,
    User,
    UserRole,
)
from app.db.session import get_db
from app.main import app
from app.modules.ai.schemas import (
    LeadScoreResult,
    MessageDraftResult,
    NoteExtractionResult,
)
from app.modules.ai.service import AIResult, AIServiceError
from app.modules.audit.router import _connect_limited_stream
from app.modules.auth.router import password_hash


class APIAuthAndAuthorizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.environment = patch.dict(
            os.environ,
            {
                "JWT_SECRET_KEY": "test-secret-key-with-at-least-32-bytes",
                "JWT_ALGORITHM": "HS256",
                "ACCESS_TOKEN_EXPIRE_MINUTES": "60",
            },
        )
        self.environment.start()
        self.engine = create_engine(
            "sqlite+pysqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(dbapi_connection, _) -> None:
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(
            bind=self.engine, autoflush=False, expire_on_commit=False
        )
        with self.session_factory.begin() as session:
            self.team = Team(name="UrbanNest test")
            self.other_team = Team(name="Other team")
            session.add_all([self.team, self.other_team])
            session.flush()
            hasher = PasswordHash.recommended()
            self.owner = self.make_user(session, self.team.id, "owner@example.test", UserRole.OWNER, hasher)
            self.manager = self.make_user(
                session, self.team.id, "manager@example.test", UserRole.MANAGER, hasher
            )
            self.agent = self.make_user(
                session, self.team.id, "agent@example.test", UserRole.AGENT, hasher
            )
            self.other_agent = self.make_user(
                session, self.team.id, "other.agent@example.test", UserRole.AGENT, hasher
            )
            self.external_agent = self.make_user(
                session,
                self.other_team.id,
                "external@example.test",
                UserRole.AGENT,
                hasher,
            )
            self.inactive_user = self.make_user(
                session,
                self.team.id,
                "inactive@example.test",
                UserRole.AGENT,
                hasher,
                is_active=False,
            )
            session.flush()
            self.assigned_lead = self.make_lead(session, self.team.id, self.agent.id, self.owner.id)
            self.second_assigned_lead = self.make_lead(
                session, self.team.id, self.agent.id, self.owner.id
            )
            self.other_assignee_lead = self.make_lead(
                session, self.team.id, self.other_agent.id, self.owner.id
            )
            self.external_lead = self.make_lead(
                session, self.other_team.id, self.external_agent.id, self.external_agent.id
            )
            self.own_task = Task(
                team_id=self.team.id,
                lead_id=self.assigned_lead.id,
                assigned_to=self.agent.id,
                created_by=self.manager.id,
                title="Agent task",
                due_at=datetime.now(timezone.utc) + timedelta(days=1),
            )
            self.team_task_on_agent_lead = Task(
                team_id=self.team.id,
                lead_id=self.assigned_lead.id,
                assigned_to=self.other_agent.id,
                created_by=self.manager.id,
                title="Manager-created task",
                due_at=datetime.now(timezone.utc) + timedelta(days=2),
            )
            session.add_all([self.own_task, self.team_task_on_agent_lead])
            session.flush()
            self.task_id = self.own_task.id
            self.other_assigned_task_id = self.team_task_on_agent_lead.id
            self.lead_id = self.assigned_lead.id
            self.second_lead_id = self.second_assigned_lead.id
            self.other_lead_id = self.other_assignee_lead.id
            self.external_lead_id = self.external_lead.id
            self.inactive_user_id = self.inactive_user.id
            self.owner_id = self.owner.id
            self.manager_id = self.manager.id
            self.agent_id = self.agent.id
            self.other_agent_id = self.other_agent.id
            self.external_agent_id = self.external_agent.id

        def override_get_db():
            with self.session_factory() as session:
                yield session

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)
        self.password = "Test-password-123!"

    @staticmethod
    def make_user(
        session: Session,
        team_id,
        email: str,
        role: UserRole,
        hasher: PasswordHash,
        *,
        is_active: bool = True,
    ) -> User:
        user = User(
            id=uuid4(),
            team_id=team_id,
            full_name=email.split("@", maxsplit=1)[0],
            email=email,
            password_hash=hasher.hash("Test-password-123!"),
            role=role,
            is_active=is_active,
        )
        session.add(user)
        return user

    @staticmethod
    def make_lead(
        session: Session, team_id, assigned_to, created_by
    ) -> Lead:
        lead = Lead(
            team_id=team_id,
            assigned_to=assigned_to,
            created_by=created_by,
            full_name=f"Lead {uuid4().hex[:8]}",
            source=LeadSource.MANUAL,
            status=LeadStatus.NEW,
        )
        session.add(lead)
        session.flush()
        return lead

    def tearDown(self) -> None:
        self.client.close()
        app.dependency_overrides.clear()
        self.engine.dispose()
        self.environment.stop()

    def login(self, email: str) -> str:
        response = self.client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": self.password},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["access_token"]

    def headers(self, email: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.login(email)}"}

    def test_login_normalizes_email_and_current_user_excludes_password_hash(self) -> None:
        response = self.client.post(
            "/api/v1/auth/login",
            json={"email": "  OWNER@EXAMPLE.TEST ", "password": self.password},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"]["role"], "owner")
        self.assertNotIn("password_hash", response.json()["user"])

        me = self.client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {response.json()['access_token']}"},
        )
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["team_id"], str(self.team.id))

    def test_rejects_bad_credentials_missing_token_and_inactive_users(self) -> None:
        bad_login = self.client.post(
            "/api/v1/auth/login",
            json={"email": "owner@example.test", "password": "wrong"},
        )
        self.assertEqual(bad_login.status_code, 401)
        self.assertEqual(
            self.client.get("/api/v1/auth/me").status_code,
            401,
        )
        inactive_login = self.client.post(
            "/api/v1/auth/login",
            json={"email": "inactive@example.test", "password": self.password},
        )
        self.assertEqual(inactive_login.status_code, 401)

    def test_login_throttle_is_shared_and_returns_retry_after(self) -> None:
        with patch.dict(
            os.environ,
            {
                "LOGIN_RATE_LIMIT_PER_EMAIL": "2",
                "LOGIN_RATE_LIMIT_PER_IP": "100",
                "LOGIN_RATE_WINDOW_SECONDS": "900",
            },
        ):
            for _ in range(2):
                response = self.client.post(
                    "/api/v1/auth/login",
                    json={
                        "email": "agent@example.test",
                        "password": "incorrect-password",
                    },
                )
                self.assertEqual(response.status_code, 401, response.text)

            throttled = self.client.post(
                "/api/v1/auth/login",
                json={
                    "email": "agent@example.test",
                    "password": "incorrect-password",
                },
            )
            self.assertEqual(throttled.status_code, 429, throttled.text)
            self.assertGreater(int(throttled.headers["Retry-After"]), 0)

            success = self.client.post(
                "/api/v1/auth/login",
                json={
                    "email": "manager@example.test",
                    "password": self.password,
                },
            )
            self.assertEqual(success.status_code, 200, success.text)

        with self.session_factory() as session:
            login_buckets = session.scalars(
                select(RateLimitBucket).where(
                    RateLimitBucket.scope == "login_email"
                )
            ).all()
            self.assertEqual(len(login_buckets), 1)
            self.assertEqual(login_buckets[0].hit_count, 3)

    def test_password_recovery_notifies_active_team_owner_without_resetting_password(
        self,
    ) -> None:
        original_hash = self.agent.password_hash
        with (
            patch.dict(
                os.environ,
                {
                    "SMTP_HOST": "smtp.example.test",
                    "SMTP_PORT": "587",
                    "SMTP_FROM_EMAIL": "crm@example.test",
                    "SMTP_USE_TLS": "true",
                    "SMTP_USE_SSL": "false",
                },
            ),
            patch(
                "app.modules.auth.router.send_password_recovery_notification"
            ) as send_notification,
        ):
            response = self.client.post(
                "/api/v1/auth/password-recovery",
                json={"email": "agent@example.test"},
            )

        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(
            response.json()["message"],
            "If an active account matches that email, its team owner can help with a reset.",
        )
        send_notification.assert_called_once()
        notified_user, notified_owners, smtp_settings = send_notification.call_args.args
        self.assertEqual(notified_user.email, "agent@example.test")
        self.assertEqual([owner.email for owner in notified_owners], ["owner@example.test"])
        self.assertEqual(smtp_settings.host, "smtp.example.test")
        with self.session_factory() as session:
            user = session.get(User, self.agent_id)
            assert user is not None
            self.assertEqual(user.password_hash, original_hash)

    def test_password_recovery_does_not_disclose_unknown_accounts(self) -> None:
        with (
            patch.dict(
                os.environ,
                {
                    "SMTP_HOST": "smtp.example.test",
                    "SMTP_PORT": "587",
                    "SMTP_FROM_EMAIL": "crm@example.test",
                    "SMTP_USE_TLS": "true",
                    "SMTP_USE_SSL": "false",
                },
            ),
            patch(
                "app.modules.auth.router.send_password_recovery_notification"
            ) as send_notification,
        ):
            response = self.client.post(
                "/api/v1/auth/password-recovery",
                json={"email": "unknown@example.test"},
            )

        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(
            response.json()["message"],
            "If an active account matches that email, its team owner can help with a reset.",
        )
        send_notification.assert_not_called()

    def test_existing_token_is_rejected_after_account_deactivation(self) -> None:
        token = self.login("agent@example.test")
        with self.session_factory.begin() as session:
            user = session.get(User, self.agent_id)
            assert user is not None
            user.is_active = False

        response = self.client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(response.status_code, 401)

    def test_malformed_bearer_token_is_rejected(self) -> None:
        response = self.client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer not-a-signed-token"},
        )
        self.assertEqual(response.status_code, 401)

    def test_user_creation_rejects_public_lead_team_id_as_bearer_token(self) -> None:
        response = self.client.post(
            "/api/v1/users",
            headers={
                "Authorization": (
                    "Bearer PUBLIC_LEAD_TEAM_ID="
                    "1976af9d-20e2-410f-a4e0-06a79a119f19"
                )
            },
            json={
                "full_name": "string",
                "email": "string",
                "role": "owner",
            },
        )

        self.assertEqual(response.status_code, 401, response.text)
        with self.session_factory() as session:
            self.assertIsNone(
                session.scalar(select(User).where(User.email == "string"))
            )

    def test_user_creation_rejects_invalid_fields_and_unexpected_authority(self) -> None:
        invalid_payloads = (
            {
                "full_name": "   ",
                "email": "person@example.test",
                "role": "agent",
            },
            {
                "full_name": "New Agent",
                "email": "not-an-email",
                "role": "agent",
            },
            {
                "full_name": "New Agent",
                "email": "new.agent@example.test",
                "role": "administrator",
            },
            {
                "full_name": "New Agent",
                "email": "new.agent@example.test",
                "role": "agent",
                "team_id": str(self.other_team.id),
            },
        )

        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                response = self.client.post(
                    "/api/v1/users",
                    headers=self.headers("owner@example.test"),
                    json=payload,
                )
                self.assertEqual(response.status_code, 422, response.text)

        with self.session_factory() as session:
            self.assertIsNone(
                session.scalar(
                    select(User).where(User.email == "new.agent@example.test")
                )
            )

    def test_manager_can_create_agent_with_temporary_password_and_force_change(self) -> None:
        response = self.client.post(
            "/api/v1/users",
            headers=self.headers("manager@example.test"),
            json={
                "full_name": "New Agent",
                "email": " New.Agent@Example.Test ",
                "role": "agent",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(body["user"]["email"], "new.agent@example.test")
        self.assertEqual(body["user"]["role"], "agent")
        self.assertTrue(body["user"]["must_change_password"])
        self.assertGreaterEqual(len(body["temporary_password"]), 24)

        with self.session_factory() as session:
            user = session.scalar(select(User).where(User.email == "new.agent@example.test"))
            assert user is not None
            self.assertTrue(password_hash.verify(body["temporary_password"], user.password_hash))

        login = self.client.post(
            "/api/v1/auth/login",
            json={
                "email": "new.agent@example.test",
                "password": body["temporary_password"],
            },
        )
        self.assertEqual(login.status_code, 200)
        self.assertTrue(login.json()["user"]["must_change_password"])
        token = login.json()["access_token"]
        blocked = self.client.get(
            "/api/v1/leads",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(blocked.status_code, 403)
        self.assertEqual(blocked.json()["detail"]["code"], "password_change_required")

    def test_owner_can_create_co_owner_with_explicit_global_permissions(self) -> None:
        manager_created = self.client.post(
            "/api/v1/users",
            headers=self.headers("owner@example.test"),
            json={
                "full_name": "New Manager",
                "email": "new.manager@example.test",
                "role": "manager",
            },
        )
        self.assertEqual(manager_created.status_code, 201, manager_created.text)

        response = self.client.post(
            "/api/v1/users",
            headers=self.headers("owner@example.test"),
            json={
                "full_name": "Limited Co-owner",
                "email": "co.owner@example.test",
                "role": "co_owner",
                "can_read": False,
                "can_write": False,
                "can_delete": False,
                "can_manage_users": True,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        co_owner = response.json()["user"]
        self.assertEqual(co_owner["role"], "co_owner")
        self.assertFalse(co_owner["can_read"])
        self.assertFalse(co_owner["can_write"])
        self.assertFalse(co_owner["can_delete"])
        self.assertTrue(co_owner["can_manage_users"])

        manager_denied = self.client.post(
            "/api/v1/users",
            headers=self.headers("manager@example.test"),
            json={
                "full_name": "Unauthorized Co-owner",
                "email": "unauthorized.co.owner@example.test",
                "role": "co_owner",
            },
        )
        self.assertEqual(manager_denied.status_code, 403)

        with self.session_factory.begin() as session:
            user = session.get(User, UUID(co_owner["id"]))
            assert user is not None
            user.password_hash = password_hash.hash(self.password)
            user.must_change_password = False
        headers = self.headers("co.owner@example.test")
        denied_read = self.client.get("/api/v1/leads", headers=headers)
        self.assertEqual(denied_read.status_code, 403)
        allowed_user_read = self.client.get("/api/v1/users", headers=headers)
        self.assertEqual(allowed_user_read.status_code, 200)
        self.assertEqual(
            {user["role"] for user in allowed_user_read.json()},
            {"agent"},
        )
        denied_write = self.client.patch(
            f"/api/v1/leads/{self.lead_id}",
            headers=headers,
            json={"status": "contacted"},
        )
        self.assertEqual(denied_write.status_code, 403)

    def test_co_owner_needs_delete_access_to_deactivate_team_agents(self) -> None:
        created = self.client.post(
            "/api/v1/users",
            headers=self.headers("owner@example.test"),
            json={
                "full_name": "Team Co-owner",
                "email": "team.co.owner@example.test",
                "role": "co_owner",
                "can_manage_users": True,
                "can_delete": False,
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        with self.session_factory.begin() as session:
            user = session.get(User, UUID(created.json()["user"]["id"]))
            assert user is not None
            user.password_hash = password_hash.hash(self.password)
            user.must_change_password = False
        co_owner_headers = self.headers("team.co.owner@example.test")
        denied = self.client.patch(
            f"/api/v1/users/{self.other_agent_id}",
            headers=co_owner_headers,
            json={"is_active": False},
        )
        self.assertEqual(denied.status_code, 403)

        enabled = self.client.patch(
            f"/api/v1/users/{created.json()['user']['id']}",
            headers=self.headers("owner@example.test"),
            json={"can_delete": True},
        )
        self.assertEqual(enabled.status_code, 200, enabled.text)
        allowed = self.client.patch(
            f"/api/v1/users/{self.other_agent_id}",
            headers=self.headers("team.co.owner@example.test"),
            json={"is_active": False},
        )
        self.assertEqual(allowed.status_code, 200, allowed.text)
        self.assertFalse(allowed.json()["is_active"])

    def test_forced_password_change_revokes_temporary_token_and_returns_new_one(self) -> None:
        temp_password = "Temporary-password-123!"
        with self.session_factory.begin() as session:
            user = session.get(User, self.agent_id)
            assert user is not None
            user.password_hash = password_hash.hash(temp_password)
            user.must_change_password = True
            user.auth_version += 1

        login = self.client.post(
            "/api/v1/auth/login",
            json={"email": "agent@example.test", "password": temp_password},
        )
        self.assertEqual(login.status_code, 200)
        old_token = login.json()["access_token"]

        change = self.client.post(
            "/api/v1/auth/change-password",
            headers={"Authorization": f"Bearer {old_token}"},
            json={
                "current_password": temp_password,
                "new_password": "New-secure-password-456!",
            },
        )
        self.assertEqual(change.status_code, 200, change.text)
        self.assertFalse(change.json()["user"]["must_change_password"])
        self.assertNotEqual(change.json()["access_token"], old_token)

        old_token_response = self.client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {old_token}"},
        )
        new_token_response = self.client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {change.json()['access_token']}"},
        )
        self.assertEqual(old_token_response.status_code, 401)
        self.assertEqual(new_token_response.status_code, 200)

    def test_manager_password_reset_invalidates_agent_sessions(self) -> None:
        old_token = self.login("agent@example.test")
        response = self.client.post(
            f"/api/v1/users/{self.agent_id}/password-reset",
            headers=self.headers("manager@example.test"),
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["must_change_password"])
        self.assertEqual(
            self.client.get(
                "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {old_token}"},
            ).status_code,
            401,
        )

        temp_login = self.client.post(
            "/api/v1/auth/login",
            json={
                "email": "agent@example.test",
                "password": response.json()["temporary_password"],
            },
        )
        self.assertEqual(temp_login.status_code, 200)
        self.assertTrue(temp_login.json()["user"]["must_change_password"])

    def test_owner_can_reset_all_team_accounts_and_download_temporary_passwords(self) -> None:
        owner_token = self.login("owner@example.test")
        manager_token = self.login("manager@example.test")
        agent_token = self.login("agent@example.test")
        with self.session_factory.begin() as session:
            manager = session.get(User, self.manager_id)
            assert manager is not None
            manager.phone = "+91 98765 43210"
            inactive = session.get(User, self.inactive_user_id)
            assert inactive is not None
            inactive.full_name = "=Inactive account"
        denied = self.client.post(
            "/api/v1/users/password-reset-all",
            headers=self.headers("manager@example.test"),
            json={"confirmation": "RESET ALL"},
        )
        self.assertEqual(denied.status_code, 403)

        missing_confirmation = self.client.post(
            "/api/v1/users/password-reset-all",
            headers=self.headers("owner@example.test"),
            json={"confirmation": "RESET"},
        )
        self.assertEqual(missing_confirmation.status_code, 422)

        response = self.client.post(
            "/api/v1/users/password-reset-all",
            headers=self.headers("owner@example.test"),
            json={"confirmation": "RESET ALL"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("text/csv", response.headers["content-type"])
        self.assertIn("no-store", response.headers["cache-control"])
        self.assertIn("attachment;", response.headers["content-disposition"])

        rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
        expected_user_ids = {
            str(self.owner_id),
            str(self.manager.id),
            str(self.agent_id),
            str(self.other_agent_id),
            str(self.inactive_user_id),
        }
        self.assertEqual({row["user_id"] for row in rows}, expected_user_ids)
        self.assertNotIn(str(self.external_agent_id), {row["user_id"] for row in rows})
        self.assertTrue(all(row["temporary_password"] for row in rows))
        manager_row = next(row for row in rows if row["user_id"] == str(self.manager_id))
        self.assertEqual(manager_row["email"], "manager@example.test")
        self.assertEqual(manager_row["phone"], "'+91 98765 43210")
        self.assertEqual(manager_row["role"], "manager")
        self.assertEqual(
            next(
                row["full_name"]
                for row in rows
                if row["user_id"] == str(self.inactive_user_id)
            ),
            "'=Inactive account",
        )

        with self.session_factory() as session:
            for row in rows:
                user = session.get(User, UUID(row["user_id"]))
                assert user is not None
                self.assertTrue(user.must_change_password)
                self.assertEqual(row["role"], user.role.value)
                self.assertTrue(password_hash.verify(row["temporary_password"], user.password_hash))
            audit_events = session.scalars(
                select(AuditEvent).where(
                    AuditEvent.action == "password_reset",
                    AuditEvent.team_id == self.team.id,
                )
            ).all()
            self.assertEqual(len(audit_events), len(expected_user_ids))
            self.assertTrue(all(event.changes is None for event in audit_events))

        self.assertEqual(
            self.client.get(
                "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {owner_token}"},
            ).status_code,
            401,
        )
        owner_temporary_password = next(
            row["temporary_password"]
            for row in rows
            if row["user_id"] == str(self.owner_id)
        )
        owner_login = self.client.post(
            "/api/v1/auth/login",
            json={
                "email": "owner@example.test",
                "password": owner_temporary_password,
            },
        )
        self.assertEqual(owner_login.status_code, 200, owner_login.text)
        self.assertTrue(owner_login.json()["user"]["must_change_password"])
        self.assertEqual(
            self.client.get(
                "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {manager_token}"},
            ).status_code,
            401,
        )
        self.assertEqual(
            self.client.get(
                "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {agent_token}"},
            ).status_code,
            401,
        )

    def test_user_can_update_and_clear_only_their_own_phone_number(self) -> None:
        headers = self.headers("agent@example.test")
        response = self.client.patch(
            "/api/v1/auth/me/profile",
            headers=headers,
            json={"phone": " +91 98765 43210 "},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["phone"], "+91 98765 43210")
        self.assertEqual(response.json()["email"], "agent@example.test")

        feed = self.client.get("/api/v1/audit/events", headers=headers)
        profile_event = next(
            event for event in feed.json()["events"] if event["action"] == "profile_updated"
        )
        self.assertEqual(profile_event["changes"], {"phone": {"changed": True}})
        self.assertNotIn("+91", str(profile_event["changes"]))

        cleared = self.client.patch(
            "/api/v1/auth/me/profile",
            headers=headers,
            json={"phone": None},
        )
        self.assertEqual(cleared.status_code, 200, cleared.text)
        self.assertIsNone(cleared.json()["phone"])

        empty_update = self.client.patch(
            "/api/v1/auth/me/profile",
            headers=headers,
            json={},
        )
        self.assertEqual(empty_update.status_code, 422)

    def test_only_owner_can_change_roles_and_last_active_owner_is_protected(self) -> None:
        manager_denied = self.client.patch(
            f"/api/v1/users/{self.other_agent_id}",
            headers=self.headers("manager@example.test"),
            json={"role": "manager"},
        )
        self.assertEqual(manager_denied.status_code, 403)

        owner_change = self.client.patch(
            f"/api/v1/users/{self.other_agent_id}",
            headers=self.headers("owner@example.test"),
            json={"role": "manager"},
        )
        self.assertEqual(owner_change.status_code, 200)
        self.assertEqual(owner_change.json()["role"], "manager")

        owner_self_deactivation = self.client.patch(
            f"/api/v1/users/{self.owner_id}",
            headers=self.headers("owner@example.test"),
            json={"is_active": False},
        )
        self.assertEqual(owner_self_deactivation.status_code, 409)

    def test_user_listing_and_deactivation_are_team_and_role_scoped(self) -> None:
        manager_users = self.client.get(
            "/api/v1/users", headers=self.headers("manager@example.test")
        )
        self.assertEqual(manager_users.status_code, 200)
        self.assertEqual({user["role"] for user in manager_users.json()}, {"agent"})

        agent_users = self.client.get(
            "/api/v1/users", headers=self.headers("agent@example.test")
        )
        self.assertEqual(agent_users.status_code, 403)

        manager_disable_manager = self.client.patch(
            f"/api/v1/users/{self.manager_id}",
            headers=self.headers("manager@example.test"),
            json={"is_active": False},
        )
        self.assertEqual(manager_disable_manager.status_code, 404)

    def test_audit_feed_visibility_is_shared_but_role_and_lead_scoped(self) -> None:
        events = [
            AuditEvent(
                team_id=self.team.id,
                actor_id=self.owner_id,
                lead_id=self.lead_id,
                entity_type="task",
                entity_id=self.task_id,
                action="updated",
                visibility=AuditVisibility.TEAM,
                summary="A follow-up task was updated",
                changes={"status": {"from": "open", "to": "completed"}},
            ),
            AuditEvent(
                team_id=self.team.id,
                actor_id=self.owner_id,
                lead_id=self.lead_id,
                entity_type="lead",
                entity_id=self.lead_id,
                action="updated",
                visibility=AuditVisibility.TEAM,
                summary="Assigned lead changed",
                changes={"status": {"from": "new", "to": "contacted"}},
            ),
            AuditEvent(
                team_id=self.team.id,
                actor_id=self.manager_id,
                lead_id=self.other_lead_id,
                entity_type="lead",
                entity_id=self.other_lead_id,
                action="updated",
                visibility=AuditVisibility.TEAM,
                summary="Other agent lead changed",
            ),
            AuditEvent(
                team_id=self.team.id,
                actor_id=self.agent_id,
                lead_id=None,
                entity_type="user",
                entity_id=self.agent_id,
                action="password_changed",
                visibility=AuditVisibility.ACTOR,
                summary="Your password was changed",
            ),
            AuditEvent(
                team_id=self.team.id,
                actor_id=self.manager_id,
                lead_id=None,
                entity_type="user",
                entity_id=self.agent_id,
                action="role_updated",
                visibility=AuditVisibility.ADMIN,
                summary="A team user account was updated",
            ),
            AuditEvent(
                team_id=self.team.id,
                actor_id=None,
                lead_id=None,
                entity_type="team",
                entity_id=None,
                action="public_lead_received",
                visibility=AuditVisibility.TEAM,
                summary="A new website inquiry was received",
            ),
            AuditEvent(
                team_id=self.other_team.id,
                actor_id=self.external_agent_id,
                lead_id=None,
                entity_type="team",
                entity_id=None,
                action="external",
                visibility=AuditVisibility.TEAM,
                summary="Other team's event",
            ),
        ]
        with self.session_factory.begin() as session:
            session.add_all(events)

        agent_feed = self.client.get(
            "/api/v1/audit/events",
            headers=self.headers("agent@example.test"),
        )
        self.assertEqual(agent_feed.status_code, 200, agent_feed.text)
        agent_events = agent_feed.json()["events"]
        agent_summaries = {event["summary"] for event in agent_events}
        self.assertEqual(
            agent_summaries,
            {
                "A follow-up task was updated",
                "Assigned lead changed",
                "Your password was changed",
                "A new website inquiry was received",
            },
        )
        task_event = next(
            event for event in agent_events if event["entity_type"] == "task"
        )
        self.assertEqual(task_event["changes"]["task_title"], "Agent task")
        self.assertGreaterEqual(
            agent_feed.json()["unread_count"],
            3,
            agent_feed.text,
        )

        owner_feed = self.client.get(
            "/api/v1/audit/events",
            headers=self.headers("owner@example.test"),
        )
        self.assertEqual(owner_feed.status_code, 200, owner_feed.text)
        owner_summaries = {
            event["summary"] for event in owner_feed.json()["events"]
        }
        self.assertIn("Other agent lead changed", owner_summaries)
        self.assertIn("A team user account was updated", owner_summaries)
        self.assertNotIn("Other team's event", owner_summaries)

    def test_audit_read_cursor_marks_shared_events_read_without_copying_them(self) -> None:
        created = self.client.post(
            "/api/v1/leads",
            headers=self.headers("owner@example.test"),
            json={
                "full_name": "Audit Feed Lead",
                "source": "manual",
                "status": "new",
                "assigned_to": str(self.agent_id),
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        updated = self.client.patch(
            f"/api/v1/leads/{created.json()['id']}",
            headers=self.headers("owner@example.test"),
            json={
                "email": "private-update@example.test",
                "notes": "private conversation details",
            },
        )
        self.assertEqual(updated.status_code, 200, updated.text)

        feed = self.client.get(
            "/api/v1/audit/events",
            headers=self.headers("agent@example.test"),
        )
        self.assertEqual(feed.status_code, 200, feed.text)
        visible_event = next(
            event
            for event in feed.json()["events"]
            if event["entity_id"] == created.json()["id"]
        )
        self.assertFalse(visible_event["is_read"])
        self.assertNotIn("email", visible_event["changes"])
        self.assertNotIn("phone", visible_event["changes"])
        updated_event = next(
            event
            for event in feed.json()["events"]
            if event["entity_id"] == created.json()["id"]
            and event["action"] == "updated"
        )
        self.assertEqual(
            updated_event["changes"],
            {"changed_fields": ["email", "notes"]},
        )

        marked = self.client.post(
            "/api/v1/audit/read",
            headers=self.headers("agent@example.test"),
        )
        self.assertEqual(marked.status_code, 200, marked.text)
        updated_feed = self.client.get(
            "/api/v1/audit/events",
            headers=self.headers("agent@example.test"),
        )
        self.assertEqual(updated_feed.json()["unread_count"], 0)
        self.assertTrue(
            next(
                event
                for event in updated_feed.json()["events"]
                if event["id"] == visible_event["id"]
            )["is_read"]
        )

        owner_feed = self.client.get(
            "/api/v1/audit/events",
            headers=self.headers("owner@example.test"),
        )
        self.assertFalse(
            next(
                event
                for event in owner_feed.json()["events"]
                if event["id"] == visible_event["id"]
            )["is_read"]
        )

        with self.session_factory() as session:
            self.assertEqual(
                session.scalar(
                    select(func.count(AuditEvent.id)).where(
                        AuditEvent.entity_id == UUID(created.json()["id"]),
                        AuditEvent.action == "created",
                    )
                ),
                1,
            )

    def test_audit_stream_connections_are_capped_per_user(self) -> None:
        class FakeCursor:
            def __init__(self, value: bool) -> None:
                self.value = value

            def fetchone(self) -> tuple[bool]:
                return (self.value,)

        class FakeConnection:
            locks: set[int] = set()

            def __init__(self) -> None:
                self.closed = False
                self.held_locks: set[int] = set()

            def execute(self, query: str, params: tuple[int]) -> FakeCursor:
                key = params[0]
                if "pg_try_advisory_lock" in query:
                    if key in self.locks:
                        return FakeCursor(False)
                    self.locks.add(key)
                    self.held_locks.add(key)
                    return FakeCursor(True)
                self.locks.discard(key)
                self.held_locks.discard(key)
                return FakeCursor(True)

            def close(self) -> None:
                self.locks.difference_update(self.held_locks)
                self.held_locks.clear()
                self.closed = True

        FakeConnection.locks.clear()
        connections: list[FakeConnection] = []

        def connect(*args: object, **kwargs: object) -> FakeConnection:
            del args, kwargs
            connection = FakeConnection()
            connections.append(connection)
            return connection

        with (
            patch.dict(
                os.environ,
                {
                    "AUDIT_STREAMS_GLOBAL_LIMIT": "4",
                    "AUDIT_STREAMS_PER_USER_LIMIT": "2",
                },
            ),
            patch("app.modules.audit.router.get_database_url") as get_url,
            patch("app.modules.audit.router.psycopg.connect", side_effect=connect),
        ):
            get_url.return_value = make_url(
                "postgresql+psycopg://user:password@localhost/test"
            )
            first = _connect_limited_stream(self.agent_id)
            second = _connect_limited_stream(self.agent_id)
            self.assertIs(first, connections[0])
            self.assertIs(second, connections[1])

            with self.assertRaises(HTTPException) as raised:
                _connect_limited_stream(self.agent_id)
            self.assertEqual(raised.exception.status_code, 429)
            first.close()

            third = _connect_limited_stream(self.agent_id)
            self.assertIs(third, connections[3])
            second.close()
            third.close()

    def test_agent_lists_only_assigned_team_leads(self) -> None:
        response = self.client.get(
            "/api/v1/leads", headers=self.headers("agent@example.test")
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {item["id"] for item in response.json()},
            {str(self.lead_id), str(self.second_lead_id)},
        )

    def test_lead_filters_apply_inside_agent_and_manager_scopes(self) -> None:
        response = self.client.get(
            "/api/v1/leads",
            params={"status": "new", "source": "manual", "q": "Lead"},
            headers=self.headers("agent@example.test"),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {item["id"] for item in response.json()},
            {str(self.lead_id), str(self.second_lead_id)},
        )

        forbidden = self.client.get(
            "/api/v1/leads",
            params={"assigned_to": str(self.other_agent_id)},
            headers=self.headers("agent@example.test"),
        )
        self.assertEqual(forbidden.status_code, 403)

        invalid_budget_range = self.client.get(
            "/api/v1/leads",
            params={"budget_min_inr": 9_000_000, "budget_max_inr": 1_000_000},
            headers=self.headers("owner@example.test"),
        )
        self.assertEqual(invalid_budget_range.status_code, 422)

    def test_managers_and_owners_list_their_team_only(self) -> None:
        for email in ("manager@example.test", "owner@example.test"):
            with self.subTest(role=email):
                response = self.client.get(
                    "/api/v1/leads", headers=self.headers(email)
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(len(response.json()), 3)
                self.assertNotIn(
                    str(self.external_lead_id),
                    {item["id"] for item in response.json()},
                )

    def test_direct_id_access_does_not_disclose_unassigned_or_cross_team_leads(self) -> None:
        agent_headers = self.headers("agent@example.test")
        unassigned_response = self.client.get(
            f"/api/v1/leads/{self.other_lead_id}", headers=agent_headers
        )
        self.assertEqual(unassigned_response.status_code, 404)

        manager_headers = self.headers("manager@example.test")
        cross_team_response = self.client.get(
            f"/api/v1/leads/{self.external_lead_id}", headers=manager_headers
        )
        self.assertEqual(cross_team_response.status_code, 404)

    def test_agents_cannot_reassign_leads_but_managers_can_assign_within_team(self) -> None:
        agent_response = self.client.patch(
            f"/api/v1/leads/{self.lead_id}",
            headers=self.headers("agent@example.test"),
            json={"assigned_to": str(self.other_agent_id)},
        )
        self.assertEqual(agent_response.status_code, 403)

        manager_response = self.client.patch(
            f"/api/v1/leads/{self.lead_id}",
            headers=self.headers("manager@example.test"),
            json={"assigned_to": str(self.other_agent_id)},
        )
        self.assertEqual(manager_response.status_code, 200)
        self.assertEqual(manager_response.json()["assigned_to"], str(self.other_agent_id))

        cross_team_response = self.client.patch(
            f"/api/v1/leads/{self.lead_id}",
            headers=self.headers("manager@example.test"),
            json={"assigned_to": str(self.external_agent_id)},
        )
        self.assertEqual(cross_team_response.status_code, 422)

    def test_lead_status_change_adds_audited_activity_and_scopes_timeline(self) -> None:
        response = self.client.patch(
            f"/api/v1/leads/{self.lead_id}",
            headers=self.headers("agent@example.test"),
            json={"status": "contacted"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "contacted")

        timeline = self.client.get(
            f"/api/v1/leads/{self.lead_id}/activities",
            headers=self.headers("agent@example.test"),
        )
        self.assertEqual(timeline.status_code, 200)
        self.assertTrue(
            any(item["type"] == "status_change" for item in timeline.json())
        )

        denied = self.client.get(
            f"/api/v1/leads/{self.other_lead_id}/activities",
            headers=self.headers("agent@example.test"),
        )
        self.assertEqual(denied.status_code, 404)

    def test_agents_only_list_tasks_for_accessible_leads_and_update_their_tasks(self) -> None:
        response = self.client.get(
            "/api/v1/tasks", headers=self.headers("agent@example.test")
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {item["id"] for item in response.json()},
            {str(self.task_id), str(self.other_assigned_task_id)},
        )

        denied = self.client.patch(
            f"/api/v1/tasks/{self.other_assigned_task_id}",
            headers=self.headers("agent@example.test"),
            json={"status": "completed"},
        )
        self.assertEqual(denied.status_code, 404)

        completed = self.client.patch(
            f"/api/v1/tasks/{self.task_id}",
            headers=self.headers("agent@example.test"),
            json={"status": "completed"},
        )
        self.assertEqual(completed.status_code, 200)
        self.assertEqual(completed.json()["status"], "completed")
        self.assertIsNotNone(completed.json()["completed_at"])

        audit_feed = self.client.get(
            "/api/v1/audit/events",
            headers=self.headers("agent@example.test"),
        )
        self.assertEqual(audit_feed.status_code, 200, audit_feed.text)
        task_event = next(
            event
            for event in audit_feed.json()["events"]
            if event["entity_id"] == str(self.task_id)
        )
        self.assertEqual(task_event["changes"]["task_title"], "Agent task")
        self.assertEqual(
            task_event["changes"]["status"],
            {"from": "open", "to": "completed"},
        )

    def test_completed_tasks_can_be_listed_and_task_detail_is_role_scoped(self) -> None:
        headers = self.headers("agent@example.test")
        completed = self.client.patch(
            f"/api/v1/tasks/{self.task_id}",
            headers=headers,
            json={"status": "completed"},
        )
        self.assertEqual(completed.status_code, 200, completed.text)

        completed_list = self.client.get(
            "/api/v1/tasks?status=completed",
            headers=headers,
        )
        self.assertEqual(completed_list.status_code, 200, completed_list.text)
        self.assertEqual(
            {item["id"] for item in completed_list.json()},
            {str(self.task_id)},
        )

        task_detail = self.client.get(
            f"/api/v1/tasks/{self.task_id}",
            headers=headers,
        )
        self.assertEqual(task_detail.status_code, 200, task_detail.text)
        self.assertEqual(task_detail.json()["status"], "completed")

        forbidden_detail = self.client.get(
            f"/api/v1/tasks/{self.other_assigned_task_id}",
            headers=headers,
        )
        self.assertEqual(forbidden_detail.status_code, 404)

        invalid_due_filter = self.client.get(
            "/api/v1/tasks?due=today&status=completed",
            headers=headers,
        )
        self.assertEqual(invalid_due_filter.status_code, 422)

    def test_manager_can_reassign_task_to_active_team_member(self) -> None:
        response = self.client.patch(
            f"/api/v1/tasks/{self.task_id}",
            headers=self.headers("manager@example.test"),
            json={"assigned_to": str(self.other_agent_id)},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["assigned_to"], str(self.other_agent_id))

        with self.session_factory() as session:
            activity = session.query(Activity).one()
            self.assertEqual(activity.actor_id, self.manager_id)
            self.assertEqual(activity.type.value, "assignment_change")

    def test_agent_can_create_task_only_for_accessible_lead(self) -> None:
        response = self.client.post(
            "/api/v1/tasks",
            headers=self.headers("agent@example.test"),
            json={
                "lead_id": str(self.lead_id),
                "title": "Call about site visit",
                "due_at": "2026-11-11T10:00:00+05:30",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["team_id"], str(self.team.id))
        self.assertEqual(response.json()["created_by"], str(self.agent_id))
        self.assertEqual(response.json()["assigned_to"], str(self.agent_id))

        audit_feed = self.client.get(
            "/api/v1/audit/events",
            headers=self.headers("agent@example.test"),
        )
        self.assertEqual(audit_feed.status_code, 200, audit_feed.text)
        task_event = next(
            event
            for event in audit_feed.json()["events"]
            if event["entity_id"] == response.json()["id"]
        )
        self.assertEqual(task_event["changes"]["task_title"], "Call about site visit")

        denied = self.client.post(
            "/api/v1/tasks",
            headers=self.headers("agent@example.test"),
            json={
                "lead_id": str(self.other_lead_id),
                "title": "Unauthorized task",
                "due_at": "2026-11-11T10:00:00+05:30",
            },
        )
        self.assertEqual(denied.status_code, 404)

    def test_activity_and_score_staleness_are_committed_together(self) -> None:
        with self.session_factory.begin() as session:
            session.add(
                LeadScore(
                    team_id=self.team.id,
                    lead_id=self.lead_id,
                    requested_by=self.owner_id,
                    score=75,
                    temperature=LeadTemperature.HOT,
                    reason="Fictional test score",
                    provider="test",
                    model="test",
                    context_hash="a" * 64,
                    is_stale=False,
                )
            )

        response = self.client.post(
            f"/api/v1/leads/{self.lead_id}/activities",
            headers=self.headers("agent@example.test"),
            json={"type": "note", "body": "Spoke to the lead"},
        )
        self.assertEqual(response.status_code, 201, response.text)

        with self.session_factory() as session:
            score = session.query(LeadScore).one()
            activity = session.query(Activity).one()
            self.assertTrue(score.is_stale)
            self.assertEqual(activity.actor_id, self.agent_id)

    def test_lead_creation_uses_authenticated_team_and_actor(self) -> None:
        response = self.client.post(
            "/api/v1/leads",
            headers=self.headers("agent@example.test"),
            json={
                "full_name": " New inquiry ",
                "assigned_to": str(self.agent_id),
                "email": " Person@Example.Test ",
                "budget_min_inr": 5_000_000,
                "budget_max_inr": 8_000_000,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["team_id"], str(self.team.id))
        self.assertEqual(response.json()["created_by"], str(self.agent_id))
        self.assertEqual(response.json()["assigned_to"], str(self.agent_id))
        self.assertEqual(response.json()["email"], "person@example.test")

    def test_health_is_public(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_csv_import_reports_row_errors_and_is_manager_only(self) -> None:
        csv_content = (
            "full_name,email,budget_min_inr,budget_max_inr\n"
            "Imported Person,imported@example.test,5000000,8000000\n"
            ",missing@example.test,5000000,8000000\n"
            "Invalid Budget,budget@example.test,9000000,8000000\n"
        )
        response = self.client.post(
            "/api/v1/leads/import",
            headers=self.headers("manager@example.test"),
            files={"file": ("leads.csv", csv_content, "text/csv")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["created_count"], 1)
        self.assertEqual(response.json()["rejected_count"], 2)
        self.assertEqual(len(response.json()["created_lead_ids"]), 1)
        self.assertEqual({error["row"] for error in response.json()["errors"]}, {3, 4})

        denied = self.client.post(
            "/api/v1/leads/import",
            headers=self.headers("agent@example.test"),
            files={"file": ("leads.csv", csv_content, "text/csv")},
        )
        self.assertEqual(denied.status_code, 403)

    def test_public_lead_intake_creates_unassigned_website_lead_and_activity(self) -> None:
        with patch.dict(os.environ, {"PUBLIC_LEAD_TEAM_ID": str(self.team.id)}):
            response = self.client.post(
                "/api/v1/public/leads",
                json={
                    "full_name": "Website inquiry",
                    "email": "Visitor@Example.Test",
                    "phone": "+91 99999 00000",
                    "budget_min_inr": 4_000_000,
                    "budget_max_inr": 8_000_000,
                    "bhk": 2,
                    "preferred_location": "Baner",
                },
            )
        self.assertEqual(response.status_code, 201, response.text)
        lead = response.json()
        self.assertEqual(lead["team_id"], str(self.team.id))
        self.assertIsNone(lead["created_by"])
        self.assertIsNone(lead["assigned_to"])
        self.assertEqual(lead["source"], "website")
        self.assertEqual(lead["email"], "visitor@example.test")

        with self.session_factory() as session:
            activity = session.query(Activity).filter_by(lead_id=UUID(lead["id"])).one()
            self.assertIsNone(activity.actor_id)
            self.assertIn("public website form", activity.body)

    def test_public_lead_intake_fails_closed_without_configured_team(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PUBLIC_LEAD_TEAM_ID", None)
            response = self.client.post(
                "/api/v1/public/leads",
                json={"full_name": "Website inquiry"},
            )
        self.assertEqual(response.status_code, 503)

    def test_public_lead_rate_limit_is_database_backed_and_hashed(self) -> None:
        with patch.dict(
            os.environ,
            {
                "PUBLIC_LEAD_TEAM_ID": str(self.team.id),
                "PUBLIC_LEAD_RATE_LIMIT": "2",
                "PUBLIC_LEAD_RATE_WINDOW_SECONDS": "600",
            },
        ):
            for name in ("Inquiry One", "Inquiry Two"):
                response = self.client.post(
                    "/api/v1/public/leads",
                    json={"full_name": name},
                )
                self.assertEqual(response.status_code, 201, response.text)

            throttled = self.client.post(
                "/api/v1/public/leads",
                json={"full_name": "Inquiry Three"},
            )
            self.assertEqual(throttled.status_code, 429, throttled.text)
            self.assertGreater(int(throttled.headers["Retry-After"]), 0)

        with self.session_factory() as session:
            bucket = session.scalar(
                select(RateLimitBucket).where(
                    RateLimitBucket.scope == "public_lead_ip"
                )
            )
            assert bucket is not None
            self.assertNotEqual(bucket.key_hash, "testclient")
            self.assertEqual(bucket.hit_count, 3)

    def test_dashboard_and_task_due_filters_use_configured_local_timezone(self) -> None:
        local_now = datetime.now(ZoneInfo("Asia/Kolkata"))
        start_today = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        with self.session_factory.begin() as session:
            session.add_all(
                [
                    Task(
                        team_id=self.team.id,
                        lead_id=self.lead_id,
                        assigned_to=self.agent_id,
                        created_by=self.manager_id,
                        title="Due today",
                        due_at=(start_today + timedelta(hours=12)).astimezone(timezone.utc),
                    ),
                    Task(
                        team_id=self.team.id,
                        lead_id=self.lead_id,
                        assigned_to=self.agent_id,
                        created_by=self.manager_id,
                        title="Overdue",
                        due_at=(start_today - timedelta(hours=2)).astimezone(timezone.utc),
                    ),
                ]
            )

        headers = self.headers("agent@example.test")
        today_response = self.client.get("/api/v1/tasks?due=today", headers=headers)
        overdue_response = self.client.get("/api/v1/tasks?due=overdue", headers=headers)
        dashboard = self.client.get("/api/v1/dashboard/summary", headers=headers)
        owner_tasks = self.client.get(
            "/api/v1/tasks?limit=100",
            headers=self.headers("owner@example.test"),
        )
        self.assertEqual(today_response.status_code, 200)
        self.assertEqual(overdue_response.status_code, 200)
        self.assertEqual(dashboard.status_code, 200, dashboard.text)
        self.assertEqual(owner_tasks.status_code, 200, owner_tasks.text)
        self.assertTrue(any(task["title"] == "Due today" for task in today_response.json()))
        self.assertTrue(any(task["title"] == "Overdue" for task in overdue_response.json()))
        due_today_task = next(
            task for task in today_response.json() if task["title"] == "Due today"
        )
        self.assertEqual(due_today_task["assigned_to_name"], "agent")
        self.assertTrue(
            any(
                task["title"] == "Manager-created task"
                and task["assigned_to_name"] == "other.agent"
                for task in owner_tasks.json()
            )
        )
        self.assertEqual(dashboard.json()["timezone"], "Asia/Kolkata")
        self.assertEqual(dashboard.json()["due_today_count"], 1)
        self.assertEqual(dashboard.json()["overdue_count"], 1)
        self.assertEqual(
            dashboard.json()["due_today"][0]["assigned_to_name"],
            "agent",
        )
        self.assertEqual(
            dashboard.json()["due_today"][0]["assigned_to"],
            str(self.agent_id),
        )

    def test_ai_score_is_scoped_and_persists_structured_score_and_usage(self) -> None:
        ai_result = AIResult(
            value=LeadScoreResult(
                score=82,
                temperature=LeadTemperature.HOT,
                reason="Clear budget and location fit.",
                factors={"budget_fit": "strong"},
            ),
            provider="mock",
            model="mock-structured",
            input_tokens=120,
            output_tokens=30,
            latency_ms=15,
        )
        with patch("app.modules.ai.router.complete_structured", return_value=ai_result):
            response = self.client.post(
                f"/api/v1/leads/{self.lead_id}/ai/score",
                headers=self.headers("agent@example.test"),
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["score"], 82)

        with self.session_factory() as session:
            scores = session.query(LeadScore).order_by(LeadScore.created_at).all()
            usage = session.query(AIUsage).one()
            self.assertEqual(len(scores), 1)
            self.assertEqual(scores[0].temperature, LeadTemperature.HOT)
            self.assertEqual(usage.status, AIUsageStatus.SUCCEEDED)
            self.assertEqual(usage.input_tokens, 120)

        latest = self.client.get(
            f"/api/v1/leads/{self.lead_id}/ai/score",
            headers=self.headers("agent@example.test"),
        )
        self.assertEqual(latest.status_code, 200)
        self.assertEqual(latest.json()["score"], 82)

    def test_ai_endpoints_do_not_call_provider_for_inaccessible_lead(self) -> None:
        with patch("app.modules.ai.router.complete_structured") as complete:
            response = self.client.post(
                f"/api/v1/leads/{self.other_lead_id}/ai/score",
                headers=self.headers("agent@example.test"),
            )
        self.assertEqual(response.status_code, 404)
        complete.assert_not_called()

    def test_message_draft_is_saved_as_draft(self) -> None:
        ai_result = AIResult(
            value=MessageDraftResult(body="Hi, would you like to visit Baner this week?"),
            provider="mock",
            model="mock-message",
            input_tokens=70,
            output_tokens=20,
            latency_ms=10,
        )
        with patch("app.modules.ai.router.complete_structured", return_value=ai_result):
            response = self.client.post(
                f"/api/v1/leads/{self.lead_id}/ai/draft",
                headers=self.headers("agent@example.test"),
                json={"channel": "whatsapp", "tone": "friendly"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "draft")

        with self.session_factory() as session:
            message = session.query(Message).one()
            self.assertEqual(message.channel, MessageChannel.WHATSAPP)
            self.assertEqual(message.status, MessageStatus.DRAFT)

    def test_note_extraction_returns_reviewable_data_and_redacts_contact_details(self) -> None:
        ai_result = AIResult(
            value=NoteExtractionResult(
                budget_min_inr=7_000_000,
                budget_max_inr=9_000_000,
                bhk=2,
                preferred_location="Baner",
                next_task_title="Schedule site visit",
                next_task_due_at=datetime(2026, 11, 14, 11, tzinfo=timezone.utc),
            ),
            provider="mock",
            model="mock-extraction",
            input_tokens=55,
            output_tokens=25,
            latency_ms=8,
        )
        with patch(
            "app.modules.ai.router.complete_structured", return_value=ai_result
        ) as complete:
            response = self.client.post(
                f"/api/v1/leads/{self.lead_id}/ai/extract",
                headers=self.headers("agent@example.test"),
                json={
                    "notes": "2bhk Baner under 90L; call alice@example.test +91 98765 43210"
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["bhk"], 2)
        prompt = complete.call_args.args[0]
        self.assertNotIn("alice@example.test", prompt)
        self.assertNotIn("98765 43210", prompt)
        self.assertIn("[email]", prompt)
        self.assertIn("[phone]", prompt)

        with self.session_factory() as session:
            self.assertEqual(session.query(AIUsage).count(), 1)
            self.assertEqual(session.query(Task).count(), 2)

    def test_ai_provider_failure_is_reported_and_recorded_without_prompt_logging(self) -> None:
        with patch(
            "app.modules.ai.router.complete_structured",
            side_effect=AIServiceError("provider_timeout", timed_out=True),
        ):
            response = self.client.post(
                f"/api/v1/leads/{self.lead_id}/ai/score",
                headers=self.headers("agent@example.test"),
            )
        self.assertEqual(response.status_code, 503)
        with self.session_factory() as session:
            usage = session.query(AIUsage).one()
            self.assertEqual(usage.status, AIUsageStatus.TIMED_OUT)
            self.assertEqual(usage.error_category, "provider_timeout")



if __name__ == "__main__":
    unittest.main()
