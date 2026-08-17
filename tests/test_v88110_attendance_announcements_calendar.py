"""Regression checks for the v8.8.110 employee workspace refinement."""

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models  # noqa: F401
from config.settings import Settings
from database.base import Base
from models.leave_request import LeaveRequest
from models.leave_type import LeaveType
from schemas.attendance_schema import AttendanceSelfEditInput
from scripts.create_initial_data import seed_initial_data
from services.attendance_service import AttendanceService


ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _future_workday() -> date:
    selected = date.today() + timedelta(days=7)
    while selected.weekday() >= 5:
        selected += timedelta(days=1)
    return selected


def test_future_approved_leave_defaults_then_remains_editable() -> None:
    """Approved VL is initial only; the employee override survives sync."""

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    settings = Settings(
        _env_file=None,
        database_url="sqlite+pysqlite:///:memory:",
        initial_company_code="V88110",
        initial_company_name="V88110 Company",
        initial_admin_username="admin",
        initial_admin_email="admin@v88110.example",
        initial_admin_password=SecretStr("Temporary123!"),
        initial_admin_employee_number="ADMIN-110",
        initial_admin_first_name="System",
        initial_admin_last_name="Administrator",
    )
    future_date = _future_workday()

    with factory() as session:
        seed = seed_initial_data(session, settings)
        leave_type = LeaveType(
            company_id=seed["company"].id,
            code="VL",
            name="Vacation Leave",
            annual_credits=Decimal("15.00"),
            is_paid=True,
            carry_over_limit=Decimal("0.00"),
            requires_attachment=False,
            handover_plan_requirement="optional",
            minimum_notice_days=0,
            is_active=True,
        )
        session.add(leave_type)
        session.flush()
        leave_request = LeaveRequest(
            public_id="LR_110",
            company_id=seed["company"].id,
            employee_id=seed["admin_employee"].id,
            filed_by_employee_id=seed["admin_employee"].id,
            filed_by_user_id=seed["admin_user"].id,
            leave_type_id=leave_type.id,
            start_date=future_date,
            end_date=future_date,
            requested_days=Decimal("1.00"),
            primary_credit_days=Decimal("1.00"),
            reason="Approved future vacation",
            status="approved",
            manager_email="admin@v88110.example",
            to_emails_json="[]",
            cc_emails_json="[]",
            email_status="sent",
            cancellation_status="none",
        )
        session.add(leave_request)
        session.commit()

        service = AttendanceService(session)
        default_record = service.get_daily(
            company_id=seed["company"].id,
            employee_id=seed["admin_employee"].id,
            attendance_date=future_date,
        )
        assert default_record is not None
        assert default_record.work_status == "VL"
        assert default_record.status_source == "approved_leave"

        updated = service.edit_own_daily_attendance(
            AttendanceSelfEditInput(
                company_id=seed["company"].id,
                employee_id=seed["admin_employee"].id,
                user_id=seed["admin_user"].id,
                attendance_date=future_date,
                work_status="WFH",
            )
        )
        assert updated.work_status == "WFH"
        assert updated.status_source == "employee_edit"
        assert updated.leave_request_id == leave_request.id

        refreshed = service.get_daily(
            company_id=seed["company"].id,
            employee_id=seed["admin_employee"].id,
            attendance_date=future_date,
        )
        assert refreshed is not None
        assert refreshed.work_status == "WFH"
        assert refreshed.status_source == "employee_edit"
        assert len(
            service.list_correction_history(
                company_id=seed["company"].id,
            )
        ) == 1


def test_editor_stays_open_and_restores_position_after_save() -> None:
    page = _source("ui/pages/user/attendance_workspace.py")

    assert 'expanded=True' in page
    assert "employee-attendance-editor-anchor" in page
    assert "scrollIntoView" in page
    assert "_EDITOR_SCROLL_STATE_KEY" in page
    assert "max_value=date(2100, 12, 31)" in page


def test_announcements_use_a_dashboard_tab_with_unread_state() -> None:
    constants = _source("core/constants.py")
    layout = _source("ui/layouts/user_layout.py")
    dashboard = _source("ui/pages/user/dashboard_page.py")
    announcements = _source("ui/pages/user/announcements_page.py")

    navigation = constants.split("USER_NAVIGATION = (", 1)[1]
    assert '"Announcements"' not in navigation.split(")", 1)[0]
    assert 'current_page == "Dashboard"' in layout
    assert '"Announcements"' in layout
    assert "render_employee_announcements_page" in dashboard
    assert "employeeAnnouncementTabShake" in dashboard
    assert 'content: " ({unread_count})"' in dashboard
    assert "mark_announcements_read" in announcements


def test_calendar_popup_uses_light_high_contrast_runtime_and_css() -> None:
    theme = _source("ui/theme/theme_loader.py")

    assert "const isCalendar = surface.matches(" in theme
    assert "const surfaceBackground = isCalendar" in theme
    assert "? '#FFFFFF'" in theme
    assert '[data-baseweb="calendar"] [role="columnheader"]' in theme
    assert '[data-baseweb="calendar"] [aria-selected="true"]' in theme
    assert "color: #172033 !important" in theme


def test_checkpoint_keeps_v88110_release_notes() -> None:
    settings = _source("config/settings.py")
    readme = _source("README.md")

    assert 'app_version: str = "0.8.8.' in settings
    assert "v8.8.110 — Editable Future Attendance" in readme
