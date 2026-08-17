"""Regression checks for date edits, history, and announcement unread state."""

from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models  # noqa: F401
from config.settings import Settings
from database.base import Base
from models.notification import Notification
from schemas.attendance_schema import AttendanceSelfEditInput
from scripts.create_initial_data import seed_initial_data
from services.attendance_service import AttendanceService
from services.notification_service import NotificationService


ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_employee_selects_date_and_edits_status_and_times() -> None:
    page = _source("ui/pages/user/attendance_workspace.py")
    service = _source("services/attendance_service.py")
    assert '"Today\'s Work Status"' in page
    assert '"Today\'s Work / Leave Status"' not in page
    assert '"Attendance Date"' in page
    assert "max_value=date(2100, 12, 31)" in page
    assert '"Work Status"' in page
    assert "attendance_date=edit_date" in page
    assert "values.attendance_date > local_today" not in service
    assert "_require_employee_owner" in service


def test_admin_history_exposes_before_and_after_values() -> None:
    service = _source("services/attendance_service.py")
    page = _source("ui/pages/admin/attendance_dashboard.py")
    assert "class AttendanceHistoryEntry" in service
    assert "def list_correction_history" in service
    assert '"Employee Edit"' in service
    assert '"Admin Correction"' in service
    assert '"Attendance Edit History"' in page
    for column in (
        "Attendance Date",
        "Edited By",
        "Previous Time In",
        "New Time In",
        "Previous Time Out",
        "New Time Out",
        "Previous Status",
        "New Status",
    ):
        assert column in page


def test_unread_announcement_count_is_per_user_and_animated() -> None:
    repository = _source("repositories/notification_repository.py")
    announcements = _source("ui/pages/user/announcements_page.py")
    dashboard = _source("ui/pages/user/dashboard_page.py")
    assert "def unread_announcement_count" in repository
    assert "Notification.user_id == user_id" in repository
    assert 'Notification.event_type == "announcement_published"' in repository
    assert "announcementUnreadShake" in announcements
    assert "prefers-reduced-motion" in announcements
    assert "mark_announcements_read" in announcements
    assert "employeeAnnouncementTabShake" in dashboard


def test_checkpoint_version_is_v88108() -> None:
    settings = _source("config/settings.py")
    assert 'app_version: str = "0.8.8.' in settings


def test_past_self_edit_history_and_per_user_announcement_read_state() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    settings = Settings(
        _env_file=None,
        database_url="sqlite+pysqlite:///:memory:",
        initial_company_code="V88108",
        initial_company_name="V88108 Company",
        initial_admin_username="admin",
        initial_admin_email="admin@v88108.example",
        initial_admin_password=SecretStr("Temporary123!"),
        initial_admin_employee_number="ADMIN-108",
        initial_admin_first_name="System",
        initial_admin_last_name="Administrator",
    )
    manila = ZoneInfo("Asia/Manila")
    past_date = date.today() - timedelta(days=2)

    with factory() as session:
        seed = seed_initial_data(session, settings)
        company_id = seed["company"].id
        user_id = seed["admin_user"].id
        employee_id = seed["admin_employee"].id
        service = AttendanceService(session)
        updated = service.edit_own_daily_attendance(
            AttendanceSelfEditInput(
                company_id=company_id,
                employee_id=employee_id,
                user_id=user_id,
                attendance_date=past_date,
                work_status="WFH",
                time_in=datetime.combine(
                    past_date, time(8, 30), tzinfo=manila
                ),
                time_out=datetime.combine(
                    past_date, time(18, 0), tzinfo=manila
                ),
            )
        )
        assert updated.work_status == "WFH"
        history = service.list_correction_history(company_id=company_id)
        assert len(history) == 1
        assert history[0].employee_name == "System Administrator"
        assert history[0].edited_by == "admin"
        assert history[0].attendance_date == past_date
        assert history[0].new_time_in == "08:30"
        assert history[0].new_time_out == "18:00"
        assert history[0].new_status == "WFH"

        notification = Notification(
            company_id=company_id,
            user_id=user_id,
            event_type="announcement_published",
            title="Unread update",
            message="Unread update",
            related_entity_type="announcement",
            related_entity_id=108,
            is_read=False,
        )
        session.add(notification)
        session.commit()
        notification_service = NotificationService(session)
        assert notification_service.unread_announcement_count(
            company_id=company_id,
            user_id=user_id,
            announcement_ids=[108],
        ) == 1
        assert notification_service.mark_announcements_read(
            company_id=company_id,
            user_id=user_id,
            announcement_ids=[108],
        ) == 1
        assert notification_service.unread_announcement_count(
            company_id=company_id,
            user_id=user_id,
            announcement_ids=[108],
        ) == 0
