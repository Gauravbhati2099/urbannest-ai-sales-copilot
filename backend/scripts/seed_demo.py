from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Activity,
    ActivityType,
    Estate,
    EstateInterest,
    EstateInterestStatus,
    EstateStatus,
    EstateType,
    EstateVisit,
    Lead,
    LeadSource,
    LeadStatus,
    Task,
    Team,
    TaskStatus,
    User,
    UserRole,
)

TEAM_NAME = "UrbanNest Realty - Demo"
DEMO_EMAIL_DOMAIN = "demo.urbannest.example.invalid"
MOCK_PHONE_PREFIX = "+1 (202) 555-01"
ESTATE_TYPES = tuple(EstateType)
ESTATE_STATUSES = tuple(EstateStatus)
ESTATE_BASE_PRICES_INR = {
    EstateType.FLAT: 5_000_000,
    EstateType.PLOT: 3_000_000,
    EstateType.HOUSE: 10_000_000,
    EstateType.COMMERCIAL_LAND: 14_000_000,
    EstateType.FARMLAND: 1_500_000,
    EstateType.FARMHOUSE: 18_000_000,
}
ESTATE_LOCATIONS = (
    ("Baner", "Pune", "Maharashtra", 18.5590, 73.7868),
    ("Wakad", "Pune", "Maharashtra", 18.5975, 73.7638),
    ("Hinjawadi", "Pune", "Maharashtra", 18.5912, 73.7389),
    ("Kharadi", "Pune", "Maharashtra", 18.5514, 73.9420),
    ("Hadapsar", "Pune", "Maharashtra", 18.5089, 73.9260),
    ("Aundh", "Pune", "Maharashtra", 18.5590, 73.8077),
    ("Kothrud", "Pune", "Maharashtra", 18.5074, 73.8077),
    ("Viman Nagar", "Pune", "Maharashtra", 18.5679, 73.9143),
    ("Pashan", "Pune", "Maharashtra", 18.5390, 73.7890),
    ("Pimpri", "Pune", "Maharashtra", 18.6298, 73.7997),
    ("Powai", "Mumbai", "Maharashtra", 19.1176, 72.9060),
    ("Thane West", "Thane", "Maharashtra", 19.2183, 72.9781),
    ("Whitefield", "Bengaluru", "Karnataka", 12.9698, 77.7500),
    ("Sarjapur", "Bengaluru", "Karnataka", 12.9100, 77.6870),
    ("Gachibowli", "Hyderabad", "Telangana", 17.4401, 78.3489),
    ("Kondapur", "Hyderabad", "Telangana", 17.4604, 78.3560),
)


@dataclass(frozen=True)
class DemoUser:
    legacy_email: str
    email: str
    full_name: str
    role: UserRole
    phone: str
    manager_email: str | None


def _demo_user(
    legacy_email: str,
    local_email: str,
    full_name: str,
    role: UserRole,
    phone_number: int,
    manager_local_email: str | None = None,
) -> DemoUser:
    return DemoUser(
        legacy_email=legacy_email,
        email=f"{local_email}@{DEMO_EMAIL_DOMAIN}",
        full_name=full_name,
        role=role,
        phone=f"{MOCK_PHONE_PREFIX}{phone_number:02d}",
        manager_email=(
            f"{manager_local_email}@{DEMO_EMAIL_DOMAIN}"
            if manager_local_email
            else None
        ),
    )


DEMO_USERS = (
    _demo_user(
        "owner@demo.urbannest.example.invalid",
        "kavya.rao",
        "Kavya Rao",
        UserRole.OWNER,
        1,
    ),
    _demo_user(
        "manager1@demo.urbannest.example.invalid",
        "rohan.desai",
        "Rohan Desai",
        UserRole.MANAGER,
        2,
    ),
    _demo_user(
        "manager2@demo.urbannest.example.invalid",
        "neha.kapoor",
        "Neha Kapoor",
        UserRole.MANAGER,
        3,
    ),
    _demo_user(
        "agent01@demo.urbannest.example.invalid",
        "ishaan.verma",
        "Ishaan Verma",
        UserRole.AGENT,
        4,
        "rohan.desai",
    ),
    _demo_user(
        "agent02@demo.urbannest.example.invalid",
        "meera.nair",
        "Meera Nair",
        UserRole.AGENT,
        5,
        "rohan.desai",
    ),
    _demo_user(
        "agent03@demo.urbannest.example.invalid",
        "aditi.shah",
        "Aditi Shah",
        UserRole.AGENT,
        6,
        "rohan.desai",
    ),
    _demo_user(
        "agent04@demo.urbannest.example.invalid",
        "kabir.joshi",
        "Kabir Joshi",
        UserRole.AGENT,
        7,
        "rohan.desai",
    ),
    _demo_user(
        "agent05@demo.urbannest.example.invalid",
        "sana.khan",
        "Sana Khan",
        UserRole.AGENT,
        8,
        "neha.kapoor",
    ),
    _demo_user(
        "agent06@demo.urbannest.example.invalid",
        "vivaan.iyer",
        "Vivaan Iyer",
        UserRole.AGENT,
        9,
        "neha.kapoor",
    ),
    _demo_user(
        "agent07@demo.urbannest.example.invalid",
        "tara.menon",
        "Tara Menon",
        UserRole.AGENT,
        10,
        "neha.kapoor",
    ),
    _demo_user(
        "agent08@demo.urbannest.example.invalid",
        "dev.kulkarni",
        "Dev Kulkarni",
        UserRole.AGENT,
        11,
        "neha.kapoor",
    ),
    _demo_user(
        "agent09@demo.urbannest.example.invalid",
        "anaya.bose",
        "Anaya Bose",
        UserRole.AGENT,
        12,
    ),
    _demo_user(
        "agent10@demo.urbannest.example.invalid",
        "reya.patel",
        "Reya Patel",
        UserRole.AGENT,
        13,
    ),
    _demo_user(
        "agent11@demo.urbannest.example.invalid",
        "diya.fernandes",
        "Diya Fernandes",
        UserRole.AGENT,
        14,
    ),
    _demo_user(
        "agent12@demo.urbannest.example.invalid",
        "aarav.sethi",
        "Aarav Sethi",
        UserRole.AGENT,
        15,
    ),
)
LEAD_NAMES = (
    "Aanya Mehta",
    "Vihaan Bhatia",
    "Mira Mukherjee",
    "Arjun Chawla",
    "Zoya Merchant",
    "Neil D'Souza",
    "Ira Banerjee",
    "Advik Malhotra",
    "Naina Reddy",
    "Rehan Qureshi",
    "Myra Pillai",
    "Kian Oberoi",
    "Saanvi Gokhale",
    "Ritvik Anand",
    "Tara Srinivasan",
    "Devika Sood",
    "Aarush Bhalla",
    "Leela Krishnan",
    "Samar Khanna",
    "Kiara Chatterjee",
    "Ishita Rao",
    "Yash Tandon",
    "Anika Deshmukh",
    "Rohan Bedi",
    "Pari Nambiar",
    "Kabir Suri",
    "Aditi Wadhwa",
    "Neil Mathur",
    "Rhea Kamat",
    "Aryan Gill",
    "Misha Arora",
    "Dhruv Menon",
    "Sana Mirza",
    "Ojas Kulkarni",
    "Avni Bansal",
    "Farhan Siddiqui",
    "Esha Purohit",
    "Manav Bhat",
    "Inaya Thomas",
    "Rishabh Narang",
    "Tanishka Sen",
    "Kunal Vora",
    "Aarohi Naidu",
    "Zain Contractor",
    "Sia Kapoor",
    "Nikhil Ahuja",
    "Mahika Iyer",
    "Reyansh Shetty",
    "Simran Kohli",
    "Veer Pradhan",
)
ACTIVITY_TEMPLATES = (
    (
        ActivityType.CALL,
        "Synthetic demo call: discussed {bhk} BHK options around {location} and agreed to review a shortlist.",
    ),
    (
        ActivityType.WHATSAPP,
        "Synthetic demo WhatsApp: shared sample listings near {location}; requested a weekday evening follow-up.",
    ),
    (
        ActivityType.EMAIL,
        "Synthetic demo email: sent a comparison of homes in {location} within the stated budget range.",
    ),
    (
        ActivityType.NOTE,
        "Synthetic demo note: prefers {bhk} BHK homes in {location}; budget flexibility is still to be confirmed.",
    ),
    (
        ActivityType.SITE_VISIT,
        "Synthetic demo site visit: reviewed a sample {bhk} BHK property near {location}; client requested more options.",
    ),
    (
        ActivityType.CALL,
        "Synthetic demo call: {name} asked about possession timelines and nearby transport around {location}.",
    ),
    (
        ActivityType.WHATSAPP,
        "Synthetic demo WhatsApp: confirmed receipt of the property shortlist and asked for floor-plan details.",
    ),
    (
        ActivityType.EMAIL,
        "Synthetic demo email: shared indicative pricing and a checklist of questions for the next property review.",
    ),
    (
        ActivityType.NOTE,
        "Synthetic demo note: comparing {location} with other neighborhoods; no decision or booking has been made.",
    ),
    (
        ActivityType.SITE_VISIT,
        "Synthetic demo site visit: discussed natural light, parking, and a second viewing for the shortlisted home.",
    ),
)
FOLLOW_UP_TEMPLATES = (
    (
        "Send a {bhk} BHK shortlist to {name}",
        "Prepare three to five {bhk} BHK options near {location} within the "
        "indicative INR {budget:,} budget. Confirm listing availability first.",
    ),
    (
        "Coordinate a {location} viewing with {name}",
        "Offer two viewing slots for suitable homes near {location} and confirm "
        "the preferred time before scheduling.",
    ),
    (
        "Compare {location} listings for {name}",
        "Share a side-by-side comparison of shortlisted homes near {location}, "
        "including price, area, and possession timeline.",
    ),
    (
        "Confirm budget range with {name}",
        "Check whether the indicative INR {budget:,} budget is firm and note "
        "any flexibility before recommending more homes.",
    ),
    (
        "Follow up on a second viewing with {name}",
        "Ask whether {name} would like another look at a shortlisted home near "
        "{location}; do not imply a booking has been made.",
    ),
    (
        "Share floor plans for {name}'s {location} shortlist",
        "Send available floor plans for relevant {bhk} BHK homes near {location} "
        "and note any layout questions.",
    ),
    (
        "Check financing questions with {name}",
        "Ask what financing or documentation questions {name} wants answered "
        "for homes in the INR {budget:,} range.",
    ),
    (
        "Review possession timelines with {name}",
        "Confirm the preferred move-in timeline and compare it with available "
        "homes near {location}.",
    ),
    (
        "Reconnect with {name} about {location} options",
        "Share a concise update on new {location} options and confirm whether "
        "the {bhk} BHK preference is unchanged.",
    ),
    (
        "Prepare next steps for {name}'s property search",
        "Summarize the agreed criteria for {location}, confirm the budget, and "
        "record the client's preferred next step.",
    ),
)
LOCAL_TIMEZONE = ZoneInfo("Asia/Kolkata")
LOCALITIES = (
    "Baner",
    "Wakad",
    "Hinjawadi",
    "Kharadi",
    "Hadapsar",
    "Aundh",
    "Kothrud",
    "Viman Nagar",
    "Pimpri",
    "Pashan",
)
SOURCES = tuple(LeadSource)
STATUSES = tuple(LeadStatus)


def _lead_email(number: int, full_name: str) -> str:
    name_slug = "".join(
        character.lower() if character.isalnum() else "."
        for character in full_name
    )
    name_slug = ".".join(part for part in name_slug.split(".") if part)
    return f"{name_slug}.{number:03d}@{DEMO_EMAIL_DOMAIN}"


def _lead_phone(number: int) -> str:
    return f"{MOCK_PHONE_PREFIX}{number + 49:02d}"


def _activity_body(number: int, *, name: str, bhk: int, location: str) -> str:
    _, template = ACTIVITY_TEMPLATES[(number - 1) % len(ACTIVITY_TEMPLATES)]
    description = template.removeprefix("Synthetic demo ").format(
        name=name, bhk=bhk, location=location
    )
    return f"Synthetic demo activity {number:03d}: {description}"


def _follow_up_details(
    number: int,
    *,
    name: str,
    bhk: int,
    location: str,
    budget: int,
) -> tuple[str, str]:
    title_template, description_template = FOLLOW_UP_TEMPLATES[
        (number - 1) % len(FOLLOW_UP_TEMPLATES)
    ]
    values = {
        "name": name,
        "bhk": bhk,
        "location": location,
        "budget": budget,
    }
    return title_template.format(**values), (
        "Synthetic demo follow-up: " + description_template.format(**values)
    )


def _local_due_at(days_from_today: int, hour: int) -> datetime:
    local_today = datetime.now(LOCAL_TIMEZONE).date()
    local_due = datetime.combine(
        local_today + timedelta(days=days_from_today),
        time(hour=hour, minute=0),
        tzinfo=LOCAL_TIMEZONE,
    )
    return local_due.astimezone(timezone.utc)


def _estate_title(number: int, estate_type: EstateType, locality: str) -> str:
    type_name = estate_type.value.replace("_", " ").title()
    return f"Synthetic demo estate {number:03d} - {type_name} in {locality}"


def _estate_details(number: int, estate_type: EstateType) -> dict[str, int | float | str]:
    variation = number % 5
    furnishing = ("unfurnished", "semi-furnished", "furnished")[number % 3]
    if estate_type is EstateType.FLAT:
        return {
            "bedrooms": (number % 3) + 1,
            "bathrooms": (number % 2) + 1,
            "built_up_area_sqft": 650 + variation * 125,
            "floor_number": (number % 9) + 1,
            "total_floors": 12,
            "parking_spaces": number % 3,
            "furnishing": furnishing,
        }
    if estate_type is EstateType.PLOT:
        return {
            "plot_area_sqft": 1_200 + variation * 400,
            "frontage_ft": 30 + variation * 5,
            "depth_ft": 40 + variation * 8,
            "zoning": ("residential", "mixed-use")[number % 2],
            "facing": ("north", "east", "south", "west")[number % 4],
        }
    if estate_type is EstateType.HOUSE:
        return {
            "bedrooms": (number % 4) + 2,
            "bathrooms": (number % 3) + 2,
            "built_up_area_sqft": 1_400 + variation * 250,
            "plot_area_sqft": 2_000 + variation * 500,
            "floors": (number % 3) + 1,
            "parking_spaces": (number % 3) + 1,
            "furnishing": furnishing,
        }
    if estate_type is EstateType.COMMERCIAL_LAND:
        return {
            "plot_area_sqft": 4_000 + variation * 1_000,
            "frontage_ft": 50 + variation * 10,
            "zoning": ("commercial", "industrial")[number % 2],
        }
    if estate_type is EstateType.FARMLAND:
        return {
            "land_area_acres": 2.5 + variation * 1.25,
            "water_source": ("borewell", "canal", "rain-fed")[number % 3],
            "soil_type": ("alluvial", "black cotton", "red loam")[number % 3],
        }
    return {
        "bedrooms": (number % 4) + 2,
        "bathrooms": (number % 3) + 2,
        "built_up_area_sqft": 1_800 + variation * 300,
        "land_area_acres": 1.0 + variation * 0.5,
        "parking_spaces": (number % 4) + 1,
        "water_source": ("borewell", "well", "municipal")[number % 3],
        "furnishing": furnishing,
    }


def _estate_location(number: int) -> tuple[str, dict[str, object]]:
    locality, city, state, latitude, longitude = ESTATE_LOCATIONS[
        (number - 1) % len(ESTATE_LOCATIONS)
    ]
    return locality, {
        "display_name": f"{locality}, {city}, {state}, India",
        "city": city,
        "state": state,
        "country": "India",
        "country_code": "IN",
        "latitude": latitude,
        "longitude": longitude,
        "osm_type": None,
        "osm_id": None,
    }


def seed_demo_data(session: Session) -> tuple[list[str], str | None]:
    password_hash = PasswordHash.recommended()

    teams = session.scalars(select(Team).where(Team.name == TEAM_NAME)).all()
    if len(teams) > 1:
        raise RuntimeError(f"Multiple teams named {TEAM_NAME!r}; refusing ambiguous seed")
    team = teams[0] if teams else Team(name=TEAM_NAME)
    if not teams:
        session.add(team)
        session.flush()

    expected_emails = {
        email
        for demo_user in DEMO_USERS
        for email in (demo_user.legacy_email, demo_user.email)
    }
    found_users = session.scalars(
        select(User).where(User.email.in_(expected_emails))
    ).all()
    users_by_existing_email = {user.email: user for user in found_users}
    existing_users: dict[str, User | None] = {}
    found_user_ids: set[UUID] = set()
    for demo_user in DEMO_USERS:
        matches = [
            user
            for email in (demo_user.legacy_email, demo_user.email)
            if (user := users_by_existing_email.get(email)) is not None
        ]
        if len(matches) > 1:
            raise RuntimeError(
                f"Multiple accounts match demo user {demo_user.full_name!r}; "
                "refusing ambiguous seed"
            )
        user = matches[0] if matches else None
        if user is not None:
            if user.id in found_user_ids:
                raise RuntimeError("Demo account email mapping is ambiguous")
            found_user_ids.add(user.id)
            if user.team_id != team.id or user.role != demo_user.role:
                raise RuntimeError(
                    f"Existing demo user {demo_user.legacy_email!r} has unexpected "
                    "team or role; refusing to overwrite"
                )
        existing_users[demo_user.email] = user

    existing_count = sum(user is not None for user in existing_users.values())
    if 0 < existing_count < len(DEMO_USERS):
        raise RuntimeError(
            "Partial demo user set exists; inspect users before continuing the seed"
        )

    demo_password = secrets.token_urlsafe(24) if existing_count == 0 else None
    users_by_email: dict[str, User] = {}
    new_emails: list[str] = []
    for demo_user in DEMO_USERS:
        user = existing_users[demo_user.email]
        if user is None:
            if demo_password is None:
                raise RuntimeError("Demo password was not initialized")
            user = User(
                team_id=team.id,
                full_name=demo_user.full_name,
                email=demo_user.email,
                phone=demo_user.phone,
                password_hash=password_hash.hash(demo_password),
                role=demo_user.role,
                is_active=True,
            )
            session.add(user)
            new_emails.append(demo_user.email)
        else:
            user.email = demo_user.email
            user.full_name = demo_user.full_name
            user.phone = demo_user.phone
        users_by_email[demo_user.email] = user

    session.flush()
    owner = users_by_email[DEMO_USERS[0].email]
    managers = [users_by_email[DEMO_USERS[index].email] for index in (1, 2)]
    for demo_user in DEMO_USERS:
        user = users_by_email[demo_user.email]
        if demo_user.manager_email is None:
            user.manager_id = None
            continue
        if demo_user.role is not UserRole.AGENT:
            raise RuntimeError("Only demo agents can be assigned a demo manager")
        manager = users_by_email.get(demo_user.manager_email)
        if manager is None or manager.role is not UserRole.MANAGER:
            raise RuntimeError(
                f"Demo manager {demo_user.manager_email!r} is missing or has an unexpected role"
            )
        user.manager_id = manager.id
    agents = [
        users_by_email[demo_user.email]
        for demo_user in DEMO_USERS
        if demo_user.role is UserRole.AGENT
    ]

    for number in range(1, 51):
        full_name = LEAD_NAMES[number - 1]
        lead_email = _lead_email(number, full_name)
        legacy_lead_email = f"lead{number:03d}@{DEMO_EMAIL_DOMAIN}"
        lead_matches = session.scalars(
            select(Lead).where(
                Lead.email.in_((legacy_lead_email, lead_email))
            )
        ).all()
        if len(lead_matches) > 1:
            raise RuntimeError(
                f"Multiple leads match seeded demo lead {number:03d}; "
                "refusing ambiguous seed"
            )
        lead = lead_matches[0] if lead_matches else None
        if lead is not None and lead.team_id != team.id:
            raise RuntimeError(
                f"Demo lead {number:03d} belongs to another team; refusing to overwrite"
            )

        budget_floor = 4_500_000 + (number % 8) * 1_000_000
        bhk = (number % 3) + 1
        location = LOCALITIES[(number - 1) % len(LOCALITIES)]
        assigned_agent = agents[(number - 1) % len(agents)]
        source = SOURCES[(number - 1) % len(SOURCES)]
        status = STATUSES[(number - 1) % len(STATUSES)]
        lead_notes = (
            f"Synthetic demo inquiry: exploring {bhk} BHK homes in {location} "
            f"with an indicative budget of INR {budget_floor:,}–"
            f"{budget_floor + 1_500_000:,}. Contact details are fictional."
        )
        if lead is None:
            lead = Lead(
                team_id=team.id,
                assigned_to=assigned_agent.id,
                created_by=owner.id,
                full_name=full_name,
                email=lead_email,
                phone=_lead_phone(number),
                source=source,
                status=status,
                budget_min_inr=budget_floor,
                budget_max_inr=budget_floor + 1_500_000,
                bhk=bhk,
                preferred_location=location,
                notes=lead_notes,
            )
            session.add(lead)
            session.flush()
        else:
            lead.full_name = full_name
            lead.email = lead_email
            lead.phone = _lead_phone(number)
            lead.assigned_to = assigned_agent.id
            lead.created_by = owner.id
            lead.source = source
            lead.status = status
            lead.budget_min_inr = budget_floor
            lead.budget_max_inr = budget_floor + 1_500_000
            lead.bhk = bhk
            lead.preferred_location = location
            lead.notes = lead_notes

        activity_body = _activity_body(
            number, name=full_name, bhk=bhk, location=location
        )
        legacy_activity_marker = (
            f"Seeded fictional demo activity for lead {number:03d}"
        )
        activities = session.scalars(
            select(Activity).where(
                Activity.team_id == team.id,
                Activity.lead_id == lead.id,
                Activity.body.in_((legacy_activity_marker, activity_body)),
            )
        ).all()
        if len(activities) > 1:
            raise RuntimeError(
                f"Multiple seeded activities found for demo lead {number:03d}; "
                "refusing ambiguous seed"
            )
        activity_type = ACTIVITY_TEMPLATES[(number - 1) % len(ACTIVITY_TEMPLATES)][0]
        if not activities:
            session.add(
                Activity(
                    team_id=team.id,
                    lead_id=lead.id,
                    actor_id=assigned_agent.id,
                    type=activity_type,
                    body=activity_body,
                    occurred_at=datetime.now(timezone.utc)
                    - timedelta(days=number % 20),
                )
            )
        else:
            activity = activities[0]
            activity.actor_id = assigned_agent.id
            activity.type = activity_type
            activity.body = activity_body

        legacy_task_title = f"Demo follow-up {number:03d}"
        task_title, task_description = _follow_up_details(
            number,
            name=full_name,
            bhk=bhk,
            location=location,
            budget=budget_floor,
        )
        tasks = session.scalars(
            select(Task).where(
                Task.team_id == team.id,
                Task.title.in_((legacy_task_title, task_title)),
            )
        ).all()
        if len(tasks) > 1:
            raise RuntimeError(
                f"Multiple tasks match seeded demo lead {number:03d}; "
                "refusing ambiguous seed"
            )
        task = tasks[0] if tasks else None
        if task is None:
            if number % 3 == 1:
                due_at = _local_due_at(-2, 10)
            elif number % 3 == 2:
                due_at = _local_due_at(0, 15)
            else:
                due_at = _local_due_at(2, 11)
            session.add(
                Task(
                    team_id=team.id,
                    lead_id=lead.id,
                    assigned_to=assigned_agent.id,
                    created_by=managers[(number - 1) % len(managers)].id,
                    title=task_title,
                    description=task_description,
                    due_at=due_at,
                    status=TaskStatus.OPEN,
                )
            )
        else:
            if task.lead_id != lead.id:
                raise RuntimeError(
                    f"Seeded task for demo lead {number:03d} is linked to "
                    "another lead; refusing to overwrite"
                )
            task.assigned_to = assigned_agent.id
            task.created_by = managers[(number - 1) % len(managers)].id
            task.title = task_title
            task.description = task_description

    seeded_lead_emails = {
        _lead_email(number, LEAD_NAMES[number - 1])
        for number in range(1, 51)
    }
    seeded_leads = session.scalars(
        select(Lead).where(
            Lead.team_id == team.id,
            Lead.email.in_(seeded_lead_emails),
        )
    ).all()
    leads_by_email = {lead.email: lead for lead in seeded_leads}
    if len(leads_by_email) != 50:
        raise RuntimeError("Expected 50 seeded demo leads before adding estate data")

    now = datetime.now(timezone.utc)
    estate_seeds: list[
        tuple[int, Estate, Lead, User, EstateType, EstateStatus, EstateInterestStatus]
    ] = []
    for number in range(1, 51):
        estate_type = ESTATE_TYPES[(number - 1) % len(ESTATE_TYPES)]
        estate_status = ESTATE_STATUSES[(number - 1) % len(ESTATE_STATUSES)]
        interest_status = {
            EstateStatus.AVAILABLE: (
                EstateInterestStatus.INTERESTED
                if (number // len(ESTATE_STATUSES)) % 2 == 0
                else EstateInterestStatus.SITE_VISIT
            ),
            EstateStatus.UNDER_OFFER: EstateInterestStatus.NEGOTIATION,
            EstateStatus.SOLD: EstateInterestStatus.WON,
            EstateStatus.WITHDRAWN: EstateInterestStatus.LOST,
        }[estate_status]
        locality, location = _estate_location(number)
        title = _estate_title(number, estate_type, locality)
        description_marker = f"Synthetic demo estate {number:03d}:"
        description = (
            f"{description_marker} fictional listing with sample ownership and "
            f"condition details for {locality}. Not a real property."
        )
        matches = session.scalars(
            select(Estate).where(Estate.team_id == team.id, Estate.title == title)
        ).all()
        if len(matches) > 1:
            raise RuntimeError(
                f"Multiple estates match seeded demo estate {number:03d}; "
                "refusing ambiguous seed"
            )
        estate = matches[0] if matches else None
        if estate is not None and not (estate.description or "").startswith(
            description_marker
        ):
            raise RuntimeError(
                f"Estate title for demo estate {number:03d} is already in use; "
                "refusing to overwrite"
            )

        lead_email = _lead_email(number, LEAD_NAMES[number - 1])
        lead = leads_by_email[lead_email]
        assigned_agent = agents[(number - 1) % len(agents)]
        estate_values = {
            "team_id": team.id,
            "assigned_to": assigned_agent.id,
            "title": title,
            "estate_type": estate_type,
            "status": estate_status,
            "location": location,
            "asking_price_inr": ESTATE_BASE_PRICES_INR[estate_type]
            + (number % 9) * 250_000,
            "description": description,
            "details": _estate_details(number, estate_type),
        }
        if estate is None:
            estate = Estate(
                **estate_values,
                created_at=now - timedelta(days=120 + (number * 7) % 180),
            )
            session.add(estate)
        else:
            for field, value in estate_values.items():
                setattr(estate, field, value)
        estate_seeds.append(
            (number, estate, lead, assigned_agent, estate_type, estate_status, interest_status)
        )

    session.flush()
    for number, estate, lead, assigned_agent, _, _, interest_status in estate_seeds:
        interests = session.scalars(
            select(EstateInterest).where(
                EstateInterest.team_id == team.id,
                EstateInterest.estate_id == estate.id,
                EstateInterest.lead_id == lead.id,
            )
        ).all()
        if len(interests) > 1:
            raise RuntimeError(
                f"Multiple seeded interests found for demo estate {number:03d}; "
                "refusing ambiguous seed"
            )
        if interests:
            interest = interests[0]
            interest.created_by = owner.id
            interest.status = interest_status
        else:
            session.add(
                EstateInterest(
                    team_id=team.id,
                    estate_id=estate.id,
                    lead_id=lead.id,
                    created_by=owner.id,
                    status=interest_status,
                )
            )

        visit_count = 1 + (number - 1) % 3
        for visit_number in range(1, visit_count + 1):
            marker = (
                f"Synthetic demo estate visit {number:03d}-{visit_number:02d}: "
                f"{lead.full_name} viewed {estate.title}."
            )
            visits = session.scalars(
                select(EstateVisit).where(
                    EstateVisit.team_id == team.id,
                    EstateVisit.estate_id == estate.id,
                    EstateVisit.notes == marker,
                )
            ).all()
            if len(visits) > 1:
                raise RuntimeError(
                    f"Multiple seeded visits found for demo estate {number:03d}; "
                    "refusing ambiguous seed"
                )
            if visits:
                visit = visits[0]
                visit.lead_id = lead.id
                visit.visited_by = assigned_agent.id
            else:
                days_ago = (
                    12
                    + number % 45
                    + (visit_count - visit_number) * 5
                )
                session.add(
                    EstateVisit(
                        team_id=team.id,
                        estate_id=estate.id,
                        lead_id=lead.id,
                        visited_by=assigned_agent.id,
                        occurred_at=now
                        - timedelta(
                            days=days_ago,
                            hours=(number * 3 + visit_number) % 24,
                        ),
                        notes=marker,
                    )
                )

    session.flush()
    return new_emails, demo_password


def main() -> None:
    from app.db.session import SessionLocal

    with SessionLocal.begin() as session:
        _, demo_password = seed_demo_data(session)

    print("Synthetic demo account emails:")
    for demo_user in DEMO_USERS:
        print(f"{demo_user.full_name} ({demo_user.role.value}): {demo_user.email}")
    if demo_password:
        print(f"Shared demo password: {demo_password}")
    else:
        print("Existing account passwords were not changed.")
    print("Synthetic profile, lead, activity, task, and estate data are ready.")


if __name__ == "__main__":
    main()
