"""v8.8.126 monthly workday calendar and OT-span regression checks."""

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import models  # noqa: F401
from database.base import Base
from models.company import Company
from models.company_workday import CompanyWorkday
from schemas.attendance_schema import CompanyAttendanceCalendarInput
from services.attendance_calculations import calculate_attendance_hours
from services.attendance_service import AttendanceService


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def _factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_unpaid_lunch_blocks_ot_until_full_attendance_span() -> None:
    start = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)

    assert calculate_attendance_hours(
        start,
        datetime(2026, 8, 12, 17, 30, tzinfo=timezone.utc),
        scheduled_workday=True,
        regular_hours=Decimal("8"),
        lunch_break_minutes=60,
    ) == (Decimal("8.00"), Decimal("0.00"))
    assert calculate_attendance_hours(
        start,
        datetime(2026, 8, 12, 18, 0, tzinfo=timezone.utc),
        scheduled_workday=True,
        regular_hours=Decimal("8"),
        lunch_break_minutes=60,
    ) == (Decimal("8.00"), Decimal("0.00"))
    assert calculate_attendance_hours(
        start,
        datetime(2026, 8, 12, 19, 0, tzinfo=timezone.utc),
        scheduled_workday=True,
        regular_hours=Decimal("8"),
        lunch_break_minutes=60,
    ) == (Decimal("9.00"), Decimal("1.00"))


def test_month_defaults_to_weekdays_then_saves_date_overrides() -> None:
    factory = _factory()
    with factory() as session:
        company = Company(code="CALENDAR", name="Calendar Company")
        session.add(company)
        session.commit()

        service = AttendanceService(session)
        defaults = service.monthly_workday_map(
            company_id=company.id,
            year=2026,
            month=8,
        )
        assert defaults[date(2026, 8, 10)] is True  # Monday
        assert defaults[date(2026, 8, 15)] is False  # Saturday

        selected = [day for day, enabled in defaults.items() if enabled]
        selected.remove(date(2026, 8, 10))  # Holiday
        selected.append(date(2026, 8, 15))  # Catch-up workday
        service.save_attendance_calendar(
            CompanyAttendanceCalendarInput(
                company_id=company.id,
                year=2026,
                month=8,
                regular_hours=Decimal("8"),
                lunch_break_minutes=60,
                work_dates=selected,
            )
        )

        saved = service.monthly_workday_map(
            company_id=company.id,
            year=2026,
            month=8,
        )
        assert saved[date(2026, 8, 10)] is False
        assert saved[date(2026, 8, 15)] is True
        assert len(
            session.scalars(
                select(CompanyWorkday).where(
                    CompanyWorkday.company_id == company.id
                )
            ).all()
        ) == 31


def test_schedule_panel_moved_to_dashboard_before_correction() -> None:
    company_page = _source("ui/pages/admin/company_page.py")
    dashboard = _source("ui/pages/admin/attendance_dashboard.py")
    render_block = dashboard.split(
        "def render_admin_attendance_dashboard",
        1,
    )[1]

    assert "Attendance Schedule & OT Rules" not in company_page
    assert "Attendance Schedule & OT Rules" in dashboard
    assert render_block.index("_render_attendance_settings(") < render_block.index(
        "_render_correction(current_user, employees)"
    )
    assert render_block.index("_render_correction(current_user, employees)") < (
        render_block.index("_render_correction_history(current_user)")
    )


def test_dtr_shading_uses_saved_schedule_not_fixed_weekends() -> None:
    table = _source("ui/components/attendance_table.py")
    service = _source("services/attendance_service.py")
    runtime = _source("database/runtime_schema.py")

    assert "matrix.scheduled_workdays.get(" in table
    assert "scheduled_workdays=scheduled_workdays" in service
    assert '"company_workdays"' in runtime


def test_v88126_checkpoint_remains_in_the_release_history() -> None:
    settings = _source("config/settings.py")
    readme = _source("README.md")

    assert 'app_version: str = "0.8.8.134"' in settings
    assert "Immediate base checkpoint: 0.8.8.133" in settings
    assert "v8.8.126 — Monthly Workday Calendar and Correct OT Span" in readme
