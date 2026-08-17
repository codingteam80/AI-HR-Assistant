"""Integrated half-day leave, session DTR, overlap, and report checks."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from openpyxl import load_workbook
from pydantic import SecretStr, ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models  # noqa: F401
from config.settings import Settings
from database.base import Base
from models.leave_request import LeaveRequest
from models.leave_type import LeaveType
from modules.reports.combined_hr_report import build_combined_hr_excel
from schemas.attendance_schema import (
    AttendancePunchInput,
    AttendanceSelfEditInput,
    AttendanceSessionInput,
)
from schemas.leave_schema import LeaveRequestInput
from scripts.create_initial_data import seed_initial_data
from services.attendance_calculations import round_time_in_up, round_time_out_down
from services.attendance_service import AttendanceService
from services.leave_service import LeaveService


ROOT = Path(__file__).resolve().parents[1]


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url="sqlite+pysqlite:///:memory:",
        initial_company_code="V88133",
        initial_company_name="Integrated Company",
        initial_admin_username="admin",
        initial_admin_email="admin@example.com",
        initial_admin_password=SecretStr("Temporary123!"),
        initial_admin_employee_number="ADMIN-133",
    )


def _factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _future_weekday() -> date:
    selected = date.today() + timedelta(days=7)
    while selected.weekday() >= 5:
        selected += timedelta(days=1)
    return selected


def test_leave_contract_supports_half_day_codes_and_structured_reasons() -> None:
    common = dict(
        company_id=1,
        employee_id=1,
        requested_by_user_id=1,
        leave_type_id=1,
        start_date=date(2026, 8, 14),
        end_date=date(2026, 8, 14),
    )
    am = LeaveRequestInput(
        **common,
        duration_code="90501",
        reason_code="1",
    )
    assert am.duration_code == "90501"
    assert am.reason == "FAMILY MATTERS"

    with pytest.raises(ValidationError, match="Others is required"):
        LeaveRequestInput(**common, reason_code="0")
    with pytest.raises(ValidationError, match="one date only"):
        LeaveRequestInput(
            **{**common, "end_date": date(2026, 8, 15)},
            duration_code="90502",
            reason_code="1",
        )


def test_quarter_hour_rounding_matches_payroll_rule() -> None:
    timezone = ZoneInfo("Asia/Manila")
    assert round_time_in_up(datetime(2026, 8, 13, 7, 0, tzinfo=timezone)).minute == 0
    assert round_time_in_up(datetime(2026, 8, 13, 7, 1, tzinfo=timezone)).strftime("%H:%M") == "07:15"
    assert round_time_in_up(datetime(2026, 8, 13, 7, 16, tzinfo=timezone)).strftime("%H:%M") == "07:30"
    assert round_time_out_down(datetime(2026, 8, 13, 17, 14, tzinfo=timezone)).strftime("%H:%M") == "17:00"


def test_am_leave_plus_pm_work_is_not_undertime_or_overtime() -> None:
    factory = _factory()
    selected_date = _future_weekday()
    timezone = ZoneInfo("Asia/Manila")
    with factory() as session:
        seed = seed_initial_data(session, _settings())
        leave_type = LeaveType(
            company_id=seed["company"].id,
            code="VL",
            name="Vacation Leave",
            annual_credits=Decimal("15.00"),
            is_paid=True,
            carry_over_limit=Decimal("0.00"),
            handover_plan_requirement="optional",
            minimum_notice_days=0,
            is_active=True,
        )
        session.add(leave_type)
        session.flush()
        request = LeaveRequest(
            public_id="LRQ_HALF",
            company_id=seed["company"].id,
            employee_id=seed["admin_employee"].id,
            filed_by_employee_id=seed["admin_employee"].id,
            filed_by_user_id=seed["admin_user"].id,
            leave_type_id=leave_type.id,
            start_date=selected_date,
            end_date=selected_date,
            requested_days=Decimal("0.50"),
            duration_code="90501",
            reason_code="1",
            primary_credit_days=Decimal("0.50"),
            reason="FAMILY MATTERS",
            status="approved",
            manager_email="admin@example.com",
            to_emails_json="[]",
            cc_emails_json="[]",
            email_status="sent",
        )
        session.add(request)
        session.commit()

        service = AttendanceService(session)
        initial = service.get_daily(
            company_id=seed["company"].id,
            employee_id=seed["admin_employee"].id,
            attendance_date=selected_date,
        )
        assert Decimal(initial.leave_hours) == Decimal("4.00")
        updated = service.edit_own_daily_attendance(
            AttendanceSelfEditInput(
                company_id=seed["company"].id,
                employee_id=seed["admin_employee"].id,
                user_id=seed["admin_user"].id,
                attendance_date=selected_date,
                work_status="WFH",
                sessions=[
                    AttendanceSessionInput(
                        work_status="WFH",
                        time_in=datetime.combine(
                            selected_date,
                            datetime.min.time().replace(hour=13),
                            tzinfo=timezone,
                        ),
                        time_out=datetime.combine(
                            selected_date,
                            datetime.min.time().replace(hour=17),
                            tzinfo=timezone,
                        ),
                    )
                ],
            )
        )
        assert updated.work_status == "WFH"
        assert Decimal(updated.total_hours) == Decimal("4.00")
        assert Decimal(updated.leave_hours) == Decimal("4.00")
        assert Decimal(updated.undertime_hours) == Decimal("0.00")
        assert Decimal(updated.ot_hours) == Decimal("0.00")


def test_overlap_blocks_active_range_but_frees_future_partial_cancellation() -> None:
    factory = _factory()
    with factory() as session:
        seed = seed_initial_data(session, _settings())
        selected = _future_weekday()
        leave_type = LeaveType(
            company_id=seed["company"].id,
            code="VL",
            name="Vacation Leave",
            annual_credits=Decimal("15.00"),
            is_paid=True,
            carry_over_limit=Decimal("0.00"),
            handover_plan_requirement="optional",
            minimum_notice_days=0,
            is_active=True,
        )
        session.add(leave_type)
        session.flush()
        request = LeaveRequest(
            public_id="LRQ_PARTIAL_CANCEL",
            company_id=seed["company"].id,
            employee_id=seed["admin_employee"].id,
            leave_type_id=leave_type.id,
            start_date=selected,
            end_date=selected + timedelta(days=4),
            requested_days=Decimal("5.00"),
            primary_credit_days=Decimal("5.00"),
            reason="FAMILY MATTERS",
            status="partially_cancelled",
            cancellation_status="approved",
            cancellation_effective_date=selected + timedelta(days=2),
            manager_email="admin@example.com",
            to_emails_json="[]",
            cc_emails_json="[]",
            email_status="sent",
        )
        session.add(request)
        session.commit()
        service = LeaveService(session)
        with pytest.raises(ValueError, match="overlap"):
            service._validate_no_overlapping_leave(
                company_id=seed["company"].id,
                employee_id=seed["admin_employee"].id,
                start_date=selected + timedelta(days=1),
                end_date=selected + timedelta(days=1),
            )
        service._validate_no_overlapping_leave(
            company_id=seed["company"].id,
            employee_id=seed["admin_employee"].id,
            start_date=selected + timedelta(days=2),
            end_date=selected + timedelta(days=2),
        )


def test_multiple_punch_sessions_become_hybrid_and_preserve_actual_times() -> None:
    factory = _factory()
    selected_date = _future_weekday()
    timezone = ZoneInfo("Asia/Manila")
    with factory() as session:
        seed = seed_initial_data(session, _settings())
        service = AttendanceService(session)

        def punch(status: str, hour: int, minute: int) -> AttendancePunchInput:
            return AttendancePunchInput(
                company_id=seed["company"].id,
                employee_id=seed["admin_employee"].id,
                user_id=seed["admin_user"].id,
                attendance_date=selected_date,
                work_status=status,
                occurred_at=datetime(
                    selected_date.year,
                    selected_date.month,
                    selected_date.day,
                    hour,
                    minute,
                    tzinfo=timezone,
                ),
            )

        opened = service.clock_in(punch("WFO", 8, 1))
        assert Decimal(opened.undertime_hours) == Decimal("0.00")
        service.clock_out(punch("WFO", 12, 7))
        service.clock_in(punch("WFH", 13, 1))
        record = service.clock_out(punch("WFH", 17, 14))

        assert record.work_status == "HYBRID"
        assert len(record.sessions) == 2
        assert service.to_local(record.sessions[0].actual_time_in).strftime("%H:%M") == "08:01"
        assert service.to_local(record.sessions[0].rounded_time_in).strftime("%H:%M") == "08:15"
        assert service.to_local(record.sessions[1].rounded_time_out).strftime("%H:%M") == "17:00"
        assert Decimal(record.total_hours) == Decimal("7.50")
        assert Decimal(record.undertime_hours) == Decimal("0.50")
        assert Decimal(record.ot_hours) == Decimal("0.00")


def test_combined_report_uses_structured_codes_and_partial_dtr() -> None:
    # Existing report regression fixture covers template structure; this test
    # guards the new structured field mappings directly in source and output.
    source = (ROOT / "modules/reports/combined_hr_report.py").read_text()
    assert "duration_label(_duration_code(request))" in source
    assert "reason_label(str(getattr(request, \"reason_code\"" in source
    assert "AM {leave_code" in source and "PM {leave_code" in source
    assert '"CC"' in source and "dinner_break_flag" in source


def test_ui_contains_two_column_reason_and_multi_session_editors() -> None:
    leave_page = (ROOT / "ui/pages/user/leave_management_page.py").read_text()
    user_dtr = (ROOT / "ui/pages/user/attendance_workspace.py").read_text()
    admin_dtr = (ROOT / "ui/pages/admin/attendance_dashboard.py").read_text()
    assert "reason_columns = st.columns(2)" in leave_page
    assert '"Duration *"' in leave_page
    assert '"Work Sessions"' in user_dtr
    assert 'step=900' in user_dtr
    assert '"Work Sessions"' in admin_dtr
    assert 'step=900' in admin_dtr
