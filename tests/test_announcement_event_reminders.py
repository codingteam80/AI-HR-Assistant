"""Smart independent admin planning reminder regression tests."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

import models  # noqa: F401
from config.settings import Settings
from database.base import Base
from database.schema_upgrade import upgrade_existing_schema
from models.user import User
from schemas.event_reminder_schema import (
    EventReminderInput,
    automatic_reminder_schedule,
    parse_smart_reminder_entries,
    parse_smart_reminder_entry,
)
from scripts.create_initial_data import seed_initial_data
from services.event_reminder_service import EventReminderService
from services.notification_service import NotificationService


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        database_url="sqlite+pysqlite:///:memory:",
        initial_company_code="EVENTS",
        initial_company_name="Events Company",
        initial_admin_username="admin",
        initial_admin_email="admin@events.example",
        initial_admin_password=SecretStr("Temporary123!"),
        initial_admin_employee_number="ADMIN-001",
        initial_admin_first_name="System",
        initial_admin_last_name="Administrator",
        announcement_upload_dir=str(tmp_path / "announcement_images"),
        display_timezone="Asia/Manila",
    )


def _factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _employee_user(session, seed) -> User:
    user = User(
        company_id=seed["company"].id,
        role_id=seed["admin_user"].role_id,
        clearance=2,
        username="employee-reminder-test",
        email="employee-reminder@events.example",
        password_hash=seed["admin_user"].password_hash,
        is_active=True,
        must_change_password=False,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _reminder_values(
    company_id: int,
    *,
    event_start_at: datetime,
) -> EventReminderInput:
    return EventReminderInput(
        company_id=company_id,
        title="Company Team Building",
        category="Company Event",
        notes=(
            "Prepare the employee announcement, venue guide, transport plan, "
            "and final activity schedule."
        ),
        event_start_at=event_start_at,
    )


def test_smart_entry_extracts_date_title_and_notes() -> None:
    parsed = parse_smart_reminder_entry(
        "2026/02/14 - Valentine's Day\n"
        "Prepare the greeting and employee announcement.\n"
        "Confirm the activity details with HR."
    )

    assert parsed.event_date.isoformat() == "2026-02-14"
    assert parsed.title == "Valentine's Day"
    assert parsed.notes == (
        "Prepare the greeting and employee announcement.\n"
        "Confirm the activity details with HR."
    )


def test_smart_entry_parses_multiple_reminders_from_one_box() -> None:
    parsed = parse_smart_reminder_entries(
        "2026/06/12 - Araw ng Kalayaan\n"
        "Prepare the employee greeting and announcement.\n"
        "Confirm the activity details with HR.\n\n\n"
        "2026/02/14 - Valentine's Day\n"
        "Prepare the employee greeting and announcement.\n"
        "Confirm the activity details with HR.\n\n"
        "2026/02/18 - White Day\n"
        "Prepare the employee greeting and announcement.\n"
        "Confirm the activity details with HR."
    )

    assert [item.event_date.isoformat() for item in parsed] == [
        "2026-06-12",
        "2026-02-14",
        "2026-02-18",
    ]
    assert [item.title for item in parsed] == [
        "Araw ng Kalayaan",
        "Valentine's Day",
        "White Day",
    ]
    assert parsed[0].notes == (
        "Prepare the employee greeting and announcement.\n"
        "Confirm the activity details with HR."
    )


def test_smart_batch_rejects_text_before_first_header() -> None:
    with pytest.raises(ValueError, match="Line 1"):
        parse_smart_reminder_entries(
            "Preparation notes without a dated reminder header.\n"
            "2026/02/14 - Valentine's Day"
        )


def test_smart_batch_identifies_invalid_later_header() -> None:
    with pytest.raises(ValueError, match="Reminder 2"):
        parse_smart_reminder_entries(
            "2026/02/14 - Valentine's Day\n"
            "Prepare the employee greeting.\n\n"
            "2026/02/18 -"
        )


@pytest.mark.parametrize(
    "entry",
    (
        "",
        "Valentine's Day",
        "2026/02/30 - Invalid Date",
        "2026/02/14",
    ),
)
def test_smart_entry_rejects_invalid_first_line(entry: str) -> None:
    with pytest.raises(ValueError):
        parse_smart_reminder_entry(entry)


def test_service_creates_multiple_reminders_in_one_batch(
    tmp_path: Path,
) -> None:
    factory = _factory()

    with factory() as session:
        settings = _settings(tmp_path)
        seed = seed_initial_data(session, settings)
        service = EventReminderService(session, settings=settings)
        values = [
            EventReminderInput(
                company_id=seed["company"].id,
                title="Araw ng Kalayaan",
                category="Holiday / Observance",
                notes="Prepare the employee announcement.",
                event_start_at=datetime(
                    2027, 6, 12, 1, 0, tzinfo=timezone.utc
                ),
            ),
            EventReminderInput(
                company_id=seed["company"].id,
                title="Valentine's Day",
                category="Holiday / Observance",
                notes="Prepare the employee greeting.",
                event_start_at=datetime(
                    2027, 2, 14, 1, 0, tzinfo=timezone.utc
                ),
            ),
            EventReminderInput(
                company_id=seed["company"].id,
                title="White Day",
                category="Holiday / Observance",
                notes="Confirm the activity details with HR.",
                event_start_at=datetime(
                    2027, 3, 14, 1, 0, tzinfo=timezone.utc
                ),
            ),
        ]

        created = service.create_many(
            values,
            actor_user_id=seed["admin_user"].id,
        )

        assert len(created) == 3
        assert [item.public_id for item in created] == [
            "REM_000001",
            "REM_000002",
            "REM_000003",
        ]
        assert [item.title for item in service.list_for_admin(
            seed["company"].id
        )] == [
            "Araw ng Kalayaan",
            "White Day",
            "Valentine's Day",
        ]


def test_three_fixed_milestones_notify_active_admins_only_once_each(
    tmp_path: Path,
) -> None:
    factory = _factory()
    event_start = datetime(2027, 2, 14, 1, 0, tzinfo=timezone.utc)

    with factory() as session:
        settings = _settings(tmp_path)
        seed = seed_initial_data(session, settings)
        employee = _employee_user(session, seed)
        service = EventReminderService(session, settings=settings)

        reminder = service.create(
            _reminder_values(
                seed["company"].id,
                event_start_at=event_start,
            ),
            actor_user_id=seed["admin_user"].id,
        )

        schedule = automatic_reminder_schedule(event_start)
        assert [label for label, _ in schedule] == [
            "1 month before",
            "2 weeks before",
            "1 week before",
        ]

        for _, scheduled_at in schedule:
            assert service.reconcile_due(
                company_id=seed["company"].id,
                at=scheduled_at + timedelta(seconds=1),
            ) == 1
            assert service.reconcile_due(
                company_id=seed["company"].id,
                at=scheduled_at + timedelta(minutes=5),
            ) == 0

        admin_notifications = NotificationService(session).list_recent(
            company_id=seed["company"].id,
            user_id=seed["admin_user"].id,
        )
        employee_notifications = NotificationService(session).list_recent(
            company_id=seed["company"].id,
            user_id=employee.id,
        )

        admin_reminders = [
            item
            for item in admin_notifications
            if item.event_type == "event_planning_reminder"
        ]
        employee_reminders = [
            item
            for item in employee_notifications
            if item.event_type == "event_planning_reminder"
        ]

        assert len(admin_reminders) == 3
        assert {
            item.title.split(":", 1)[0]
            for item in admin_reminders
        } == {
            "1 month before",
            "2 weeks before",
            "1 week before",
        }
        assert all(
            item.related_entity_type == "event_reminder"
            and item.related_entity_id == reminder.id
            for item in admin_reminders
        )
        assert employee_reminders == []


def test_reminder_plan_does_not_require_an_announcement() -> None:
    values = _reminder_values(
        1,
        event_start_at=datetime.now(timezone.utc) + timedelta(days=60),
    )

    assert values.announcement_id is None
    assert len(values.reminder_schedule) == 3


def test_event_end_must_be_after_event_start() -> None:
    now = datetime.now(timezone.utc)

    with pytest.raises(ValidationError):
        EventReminderInput(
            company_id=1,
            title="Invalid Event",
            category="Company Event",
            notes="The event end time is invalid.",
            event_start_at=now + timedelta(days=2),
            event_end_at=now + timedelta(days=1),
        )


def test_move_to_bin_restore_and_permanent_delete(tmp_path: Path) -> None:
    factory = _factory()

    with factory() as session:
        settings = _settings(tmp_path)
        seed = seed_initial_data(session, settings)
        service = EventReminderService(session, settings=settings)
        reminder = service.create(
            _reminder_values(
                seed["company"].id,
                event_start_at=datetime.now(timezone.utc) + timedelta(days=60),
            ),
            actor_user_id=seed["admin_user"].id,
        )

        moved = service.move_to_bin(
            company_id=seed["company"].id,
            reminder_id=reminder.id,
            actor_user_id=seed["admin_user"].id,
        )
        assert moved.archived_at is not None
        assert service.list_for_admin(seed["company"].id) == []
        assert [item.id for item in service.list_archived(seed["company"].id)] == [
            reminder.id
        ]

        restored = service.restore_from_bin(
            company_id=seed["company"].id,
            reminder_id=reminder.id,
            actor_user_id=seed["admin_user"].id,
        )
        assert restored.archived_at is None
        assert [item.id for item in service.list_for_admin(seed["company"].id)] == [
            reminder.id
        ]

        service.move_to_bin(
            company_id=seed["company"].id,
            reminder_id=reminder.id,
            actor_user_id=seed["admin_user"].id,
        )
        service.permanently_delete(
            company_id=seed["company"].id,
            reminder_id=reminder.id,
        )
        assert service.list_archived(seed["company"].id) == []


def test_event_reminders_use_smart_milestone_and_bin_columns() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    table_names = set(inspect(engine).get_table_names())
    columns = {
        column["name"]
        for column in inspect(engine).get_columns("event_reminders")
    }

    assert "event_reminders" in table_names
    assert {
        "public_id",
        "event_start_at",
        "reminder_one_month_sent_at",
        "reminder_two_weeks_sent_at",
        "reminder_one_week_sent_at",
        "archived_at",
        "archived_by_user_id",
        "status",
        "announcement_id",
    }.issubset(columns)



def test_schema_upgrade_adds_smart_reminder_and_bin_columns() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE event_reminders (
                    id INTEGER PRIMARY KEY,
                    public_id VARCHAR(30),
                    company_id INTEGER NOT NULL,
                    created_by_user_id INTEGER NOT NULL,
                    updated_by_user_id INTEGER NOT NULL,
                    title VARCHAR(180) NOT NULL,
                    category VARCHAR(60) NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    event_start_at DATETIME NOT NULL,
                    event_end_at DATETIME,
                    reminder_lead_minutes INTEGER NOT NULL DEFAULT 10080,
                    reminder_at DATETIME NOT NULL,
                    reminder_sent_at DATETIME,
                    status VARCHAR(24) NOT NULL DEFAULT 'planned',
                    announcement_id INTEGER,
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
        )

    upgrade_existing_schema(engine)
    columns = {
        column["name"]
        for column in inspect(engine).get_columns("event_reminders")
    }
    assert {
        "reminder_one_month_sent_at",
        "reminder_two_weeks_sent_at",
        "reminder_one_week_sent_at",
        "archived_at",
        "archived_by_user_id",
    }.issubset(columns)

def test_announcement_ui_uses_smart_entry_year_history_and_bin() -> None:
    page_source = (
        PROJECT_ROOT / "ui/pages/admin/announcements_page.py"
    ).read_text(encoding="utf-8")
    app_source = (PROJECT_ROOT / "app.py").read_text(encoding="utf-8")
    announcement_schema = (
        PROJECT_ROOT / "schemas/announcement_schema.py"
    ).read_text(encoding="utf-8")

    assert '"Reminders"' in page_source
    assert '"Create Reminder"' in page_source
    assert '"Manage Reminders"' in page_source
    assert '"Reminder Bin (' in page_source
    assert '"Entry Box *"' in page_source
    assert '"Save Smart Reminders"' in page_source
    assert "parse_smart_reminder_entries" in page_source
    assert ".create_many(" in page_source
    assert "max_chars=30000" in page_source
    assert '"Reminder History Year"' in page_source
    assert '"Move Selected Reminder to Bin"' in page_source
    assert '"Permanently Delete"' in page_source
    assert "1 month, 2 weeks, and 1 week" in page_source
    assert "max_height=430" in page_source
    assert "max_height=400" in page_source
    assert "overflow-y: scroll" in page_source
    assert "EventReminderService" in app_source
    assert ".reconcile_due(" in app_source
    assert "event_start_at" not in announcement_schema
    assert "reminder_enabled" not in announcement_schema



def test_create_reminder_clears_only_after_success_and_keeps_workspace() -> None:
    page_source = (
        PROJECT_ROOT / "ui/pages/admin/announcements_page.py"
    ).read_text(encoding="utf-8")
    requirements = (PROJECT_ROOT / "requirements.txt").read_text(
        encoding="utf-8"
    )

    assert 'CREATE_REMINDER_FORM_REVISION_KEY' in page_source
    assert 'index=None' in page_source
    assert 'placeholder="Select a category"' in page_source
    assert 'create_smart_reminder_entry_{form_revision}' in page_source
    assert '_remember_reminder_tab("Create Reminder")' in page_source
    assert 'default=reminder_default_tab' in page_source
    assert 'default=announcement_default_tab' in page_source
    assert 'streamlit>=1.61,<2.0' in requirements
