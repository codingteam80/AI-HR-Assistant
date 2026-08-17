"""Regression coverage for v8.8.144 dashboard, leave, and search updates."""

from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models  # noqa: F401
from database.base import Base
from models.company import Company
from models.company_workday import CompanyWorkday
from models.employee import Employee
from models.leave_balance import LeaveBalance
from models.leave_credit_transaction import LeaveCreditTransaction
from models.leave_type import LeaveType
from models.role import Role
from models.user import User
from services.leave_service import LeaveService


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_admin_dashboard_metrics_move_and_duplicate_reports_tab_is_removed() -> None:
    dashboard = _source("ui/pages/admin/admin_dashboard_page.py")
    attendance = _source("ui/pages/admin/attendance_dashboard.py")
    employees = _source("ui/pages/admin/employees_page.py")

    assert "User Accounts" not in dashboard
    assert "Active Accounts" not in dashboard
    assert 'st.tabs(["Monthly DTR", "Reports"])' not in attendance
    assert '("User Accounts", len(users))' in employees
    assert '("Active Accounts", sum(1 for user in users if user.is_active))' in employees
    assert 'def _render_employee_list(\n    current_user:' in employees


def test_leave_overview_history_layout_and_all_column_search_are_present() -> None:
    admin_leave = _source("ui/pages/admin/leave_management_page.py")
    attendance = _source("ui/pages/admin/attendance_dashboard.py")

    assert 'st.markdown("### Pending Leave Request")' in admin_leave
    assert "max_height=170" in admin_leave
    assert "max_height=205" in admin_leave
    assert '"History",' in admin_leave
    assert "def _render_leave_history(" in admin_leave
    assert '"Search Leave Requests"' in admin_leave
    assert "LeaveService.allocation_breakdown(request)" in admin_leave
    assert '"Search Employee / Attendance / DTR / OT"' in attendance
    assert "employee.employment_status" in attendance

    account_block = admin_leave.split("def _render_employee_accounts(", 1)[1]
    metrics_position = account_block.index("_render_employee_account_summary(")
    heading_position = account_block.index("_render_employee_account_identity(")
    selectors_position = account_block.index('st.selectbox(\n            "Department"')
    assert metrics_position < heading_position < selectors_position


def test_company_regular_workdays_exclude_saved_holiday_and_include_catchup_day() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    with factory() as session:
        company = Company(code="WORKDAY", name="Workday Company")
        session.add(company)
        session.flush()
        session.add_all(
            [
                CompanyWorkday(
                    company_id=company.id,
                    work_date=date(2026, 8, 19),
                    is_workday=False,
                ),
                CompanyWorkday(
                    company_id=company.id,
                    work_date=date(2026, 8, 22),
                    is_workday=True,
                ),
            ]
        )
        session.commit()

        service = LeaveService(session)
        assert service.company_working_days(
            company_id=company.id,
            start_date=date(2026, 8, 17),
            end_date=date(2026, 8, 20),
        ) == Decimal("3.00")
        assert service.company_working_days(
            company_id=company.id,
            start_date=date(2026, 8, 22),
            end_date=date(2026, 8, 22),
        ) == Decimal("1.00")
        assert service._requested_days_for_duration(
            company_id=company.id,
            start_date=date(2026, 8, 17),
            end_date=date(2026, 8, 20),
            duration_code="90503",
        ) == Decimal("3.00")


def test_lwop_warnings_are_visible_to_employee_approver_and_admin() -> None:
    employee_leave = _source("ui/pages/user/leave_management_page.py")
    admin_leave = _source("ui/pages/admin/leave_management_page.py")
    service = _source("services/leave_service.py")

    assert "All countable Regular Workdays" in employee_leave
    assert "This employee has no available" in employee_leave
    assert "No available {request.leave_type.name} credits" in admin_leave
    assert "Leave Without Pay (LWP)" in service
    assert "Credit/LWP Split:" in service
    assert "company_working_days(" in service
    assert "request.requested_days = requested_days" in service


def test_company_leave_history_loads_credit_transaction_relations() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        company = Company(code="HISTORY", name="History Company")
        role = Role(company=company, name="Admin", is_system_role=True, is_active=True)
        session.add_all([company, role])
        session.flush()
        user = User(
            company=company,
            role=role,
            clearance=1,
            username="admin",
            email="admin@history.test",
            password_hash="test",
            is_active=True,
            must_change_password=False,
        )
        session.add(user)
        session.flush()
        employee = Employee(
            company=company,
            user=user,
            employee_number="H-001",
            first_name="History",
            last_name="Admin",
            employment_status="employed",
        )
        leave_type = LeaveType(
            company_id=company.id,
            code="VACATION",
            name="Vacation Leave",
            annual_credits=Decimal("15.00"),
            is_paid=True,
            carry_over_limit=Decimal("0.00"),
            requires_attachment=False,
            handover_plan_requirement="optional",
            minimum_notice_days=0,
            is_active=True,
        )
        session.add_all([employee, leave_type])
        session.flush()
        balance = LeaveBalance(
            company_id=company.id,
            employee_id=employee.id,
            leave_type_id=leave_type.id,
            year=2026,
            allocated_days=Decimal("15.00"),
        )
        session.add(balance)
        session.flush()
        session.add(
            LeaveCreditTransaction(
                company_id=company.id,
                employee_id=employee.id,
                leave_type_id=leave_type.id,
                leave_balance_id=balance.id,
                created_by_user_id=user.id,
                transaction_type="annual_accrual",
                amount_days=Decimal("15.00"),
                note="2026 annual allocation",
            )
        )
        session.commit()

        rows = LeaveService(session).list_company_credit_history(company.id, 2026)
        assert len(rows) == 1
        assert rows[0].employee.employee_number == "H-001"
        assert rows[0].leave_type.name == "Vacation Leave"
        assert rows[0].created_by.username == "admin"


def test_production_sources_keep_deprecated_streamlit_calls_out() -> None:
    files = [
        path
        for path in PROJECT_ROOT.rglob("*.py")
        if "tests" not in path.parts
        and ".venv" not in path.parts
        and "venv" not in path.parts
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in files)
    assert "st.components.v1.html" not in source
    assert "components.html" not in source
    assert "use_container_width" not in source
