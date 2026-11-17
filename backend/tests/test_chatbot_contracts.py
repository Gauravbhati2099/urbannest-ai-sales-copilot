from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from pydantic import ValidationError

from app.db.models import (
    EstateStatus,
    EstateType,
    LeadSource,
    LeadStatus,
    TaskStatus,
)
from app.modules.chatbot.contracts import (
    EstateDetail,
    GetEstateDetailsInput,
    GetLeadSummaryInput,
    ListTasksInput,
    SearchEstatesInput,
    SearchLeadsInput,
    build_page,
    project_estate_detail,
    project_lead_summary,
    project_task_summary,
)
from app.modules.estates.schemas import EstateRead
from app.modules.leads.schemas import LeadRead, LocationSelection
from app.modules.tasks.schemas import TaskRead


class ChatbotContractTests(unittest.TestCase):
    def test_tool_inputs_reject_identity_and_assignment_fields(self) -> None:
        valid_inputs = [
            (SearchLeadsInput, {"q": "Aditi"}),
            (GetLeadSummaryInput, {"lead_id": str(uuid4())}),
            (ListTasksInput, {"due": "overdue"}),
            (SearchEstatesInput, {"q": "Bengaluru"}),
            (GetEstateDetailsInput, {"estate_id": str(uuid4())}),
        ]
        for model, payload in valid_inputs:
            for forbidden_field in (
                "user_id",
                "team_id",
                "role",
                "assigned_to",
            ):
                with self.subTest(model=model.__name__, field=forbidden_field):
                    with self.assertRaises(ValidationError):
                        model.model_validate(
                            {**payload, forbidden_field: str(uuid4())}
                        )

    def test_search_leads_validates_budget_range_and_bounds(self) -> None:
        with self.assertRaises(ValidationError):
            SearchLeadsInput(budget_min_inr=2_000_000, budget_max_inr=1_000_000)
        with self.assertRaises(ValidationError):
            SearchLeadsInput(limit=21)

    def test_task_due_filter_only_allows_open_tasks(self) -> None:
        self.assertEqual(ListTasksInput(due="today").status, None)
        with self.assertRaises(ValidationError):
            ListTasksInput(due="overdue", status=TaskStatus.COMPLETED)

    def test_lead_projection_excludes_contacts_and_notes(self) -> None:
        now = datetime.now(timezone.utc)
        lead = LeadRead(
            id=uuid4(),
            team_id=uuid4(),
            assigned_to=uuid4(),
            created_by=uuid4(),
            full_name="Aditi Rao",
            email="aditi@example.test",
            phone="+91 98765 43210",
            phone_country_code="+91",
            phone_region="IN",
            phone_national_number="9876543210",
            source=LeadSource.MANUAL,
            status=LeadStatus.NEW,
            budget_min_inr=10_000_000,
            budget_max_inr=15_000_000,
            bhk=3,
            preferred_location="Bengaluru",
            location=None,
            notes="Private follow-up note",
            created_at=now,
            updated_at=now,
        )

        projection = project_lead_summary(lead).model_dump()
        self.assertEqual(projection["full_name"], "Aditi Rao")
        self.assertNotIn("email", projection)
        self.assertNotIn("phone", projection)
        self.assertNotIn("notes", projection)
        self.assertNotIn("team_id", projection)
        self.assertNotIn("assigned_to", projection)

    def test_task_projection_excludes_description_and_user_ids(self) -> None:
        now = datetime.now(timezone.utc)
        task = TaskRead(
            id=uuid4(),
            team_id=uuid4(),
            lead_id=uuid4(),
            assigned_to=uuid4(),
            assigned_to_name="Sales Agent",
            created_by=uuid4(),
            title="Schedule a viewing",
            description="Internal task description",
            due_at=now + timedelta(days=1),
            status=TaskStatus.OPEN,
            completed_at=None,
            created_at=now,
            updated_at=now,
        )

        projection = project_task_summary(task).model_dump()
        self.assertEqual(projection["title"], "Schedule a viewing")
        self.assertNotIn("description", projection)
        self.assertNotIn("assigned_to", projection)
        self.assertNotIn("created_by", projection)
        self.assertNotIn("team_id", projection)

    def test_estate_projection_excludes_coordinates_description_and_unknown_facts(
        self,
    ) -> None:
        now = datetime.now(timezone.utc)
        estate = EstateRead(
            id=uuid4(),
            team_id=uuid4(),
            assigned_to=uuid4(),
            assigned_to_name="Sales Agent",
            title="Cedar Grove Residences",
            estate_type=EstateType.FLAT,
            status=EstateStatus.AVAILABLE,
            location=LocationSelection(
                display_name="Whitefield, Bengaluru",
                country="India",
                country_code="IN",
                latitude=12.9698,
                longitude=77.75,
            ),
            asking_price_inr=12_000_000,
            description="Untrusted listing description",
            details={
                "bedrooms": 3,
                "furnishing": "semi-furnished",
                "unapproved_internal_field": "not for the model",
            },
            created_at=now,
            updated_at=now,
        )

        projection = project_estate_detail(estate)
        self.assertIsInstance(projection, EstateDetail)
        payload = projection.model_dump()
        self.assertEqual(payload["location"], "Whitefield, Bengaluru")
        self.assertEqual(payload["property_facts"]["bedrooms"], 3)
        self.assertNotIn("latitude", payload)
        self.assertNotIn("longitude", payload)
        self.assertNotIn("description", payload)
        self.assertNotIn("team_id", payload)
        self.assertNotIn("unapproved_internal_field", payload["property_facts"])

    def test_page_uses_overfetch_to_compute_next_offset(self) -> None:
        result = build_page(["one", "two", "three"], limit=2, offset=4)
        self.assertEqual(result.items, ["one", "two"])
        self.assertTrue(result.has_more)
        self.assertEqual(result.next_offset, 6)

        final_page = build_page(["one"], limit=2, offset=6)
        self.assertFalse(final_page.has_more)
        self.assertIsNone(final_page.next_offset)


if __name__ == "__main__":
    unittest.main()
