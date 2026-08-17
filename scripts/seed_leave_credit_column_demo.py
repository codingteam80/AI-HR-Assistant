"""Seed clear leave-credit column examples for one test employee.

This utility changes only the selected employee's Vacation and Sick Leave
balances for one year. It preserves employees, leave requests, approvals,
notifications, attachments, and every other employee's balances.

Run from the project root after stopping Streamlit:

    python -m scripts.seed_leave_credit_column_demo --confirm

The default target is employee number 191220 (Lander Garcia) for the current
year. Use ``--employee-number`` or ``--year`` to select another test record.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
import sqlite3

from sqlalchemy import select
from sqlalchemy.engine import make_url

from config.settings import Settings, get_settings
from database.runtime_schema import initialize_runtime_schema
from database.session import SessionFactory
from models.employee import Employee
from models.leave_balance import LeaveBalance
from models.leave_credit_transaction import LeaveCreditTransaction
from models.leave_type import LeaveType
from services.leave_service import LeaveService


@dataclass(frozen=True, slots=True)
class DemoBalance:
    """One policy-safe test ledger snapshot."""

    beginning: Decimal
    credit: Decimal
    adjustment: Decimal
    used: Decimal
    reserved: Decimal
    converted: Decimal

    @property
    def available(self) -> Decimal:
        return (
            self.beginning
            + self.credit
            + self.adjustment
            - self.used
            - self.reserved
            - self.converted
        )


DEMO_BALANCES = {
    "VACATION": DemoBalance(
        beginning=Decimal("30.00"),
        credit=Decimal("17.00"),
        adjustment=Decimal("0.00"),
        used=Decimal("4.00"),
        reserved=Decimal("0.00"),
        converted=Decimal("2.00"),
    ),
    "SICK": DemoBalance(
        beginning=Decimal("8.00"),
        credit=Decimal("17.00"),
        adjustment=Decimal("0.00"),
        used=Decimal("2.00"),
        reserved=Decimal("0.00"),
        converted=Decimal("10.00"),
    ),
}


def _sqlite_database_path(settings: Settings) -> Path | None:
    """Resolve the configured SQLite database without assuming the CWD."""

    url = make_url(settings.database_url)
    if not url.drivername.startswith("sqlite"):
        return None
    if not url.database or url.database == ":memory:":
        return None
    path = Path(url.database)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def _backup_sqlite_database(settings: Settings) -> Path | None:
    """Create a consistent, recoverable backup before seeding test data."""

    source_path = _sqlite_database_path(settings)
    if source_path is None or not source_path.exists():
        return None
    backup_dir = source_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / (
        f"hr_assistant_before_lander_credit_demo_{timestamp}.db"
    )
    with sqlite3.connect(source_path) as source:
        with sqlite3.connect(backup_path) as destination:
            source.backup(destination)
    return backup_path


def _seed_employee(
    *,
    employee_number: str,
    year: int,
) -> list[tuple[str, DemoBalance]]:
    """Apply the two demo snapshots and record an auditable change."""

    with SessionFactory() as session:
        employee = session.scalar(
            select(Employee).where(
                Employee.employee_number == employee_number,
            )
        )
        if employee is None:
            raise ValueError(
                f"Employee number '{employee_number}' was not found."
            )

        service = LeaveService(session)
        service.ensure_current_year_balances(employee.company_id, year)
        leave_types = {
            (item.code or "").strip().upper(): item
            for item in session.scalars(
                select(LeaveType).where(
                    LeaveType.company_id == employee.company_id,
                    LeaveType.is_active.is_(True),
                )
            ).all()
        }
        applied: list[tuple[str, DemoBalance]] = []

        for code, demo in DEMO_BALANCES.items():
            leave_type = leave_types.get(code)
            if leave_type is None:
                raise ValueError(f"Active {code} leave type was not found.")

            # Beginning Credit is intentionally derived by the application
            # from the prior year's post-conversion available balance. Seed
            # that source ledger too, otherwise the normal January sync would
            # correctly replace a current-year-only demo value.
            prior_balance = session.scalar(
                select(LeaveBalance).where(
                    LeaveBalance.company_id == employee.company_id,
                    LeaveBalance.employee_id == employee.id,
                    LeaveBalance.leave_type_id == leave_type.id,
                    LeaveBalance.year == year - 1,
                )
            )
            if prior_balance is None:
                prior_balance = LeaveBalance(
                    company_id=employee.company_id,
                    employee_id=employee.id,
                    leave_type_id=leave_type.id,
                    year=year - 1,
                    allocated_days=demo.beginning,
                    carry_over_days=Decimal("0.00"),
                    adjustment_days=Decimal("0.00"),
                    used_days=Decimal("0.00"),
                    reserved_days=Decimal("0.00"),
                    beginning_credit_days=Decimal("0.00"),
                    credit_days=demo.beginning,
                    converted_to_cash_days=Decimal("0.00"),
                )
                session.add(prior_balance)
                session.flush()
                prior_changed = True
            else:
                prior_changed = (
                    Decimal(prior_balance.allocated_days) != demo.beginning
                    or Decimal(prior_balance.carry_over_days) != Decimal("0.00")
                    or Decimal(prior_balance.adjustment_days) != Decimal("0.00")
                    or Decimal(prior_balance.used_days) != Decimal("0.00")
                    or Decimal(prior_balance.reserved_days) != Decimal("0.00")
                    or Decimal(prior_balance.beginning_credit_days)
                    != Decimal("0.00")
                    or Decimal(prior_balance.credit_days) != demo.beginning
                    or Decimal(prior_balance.converted_to_cash_days)
                    != Decimal("0.00")
                )
                prior_balance.allocated_days = demo.beginning
                prior_balance.carry_over_days = Decimal("0.00")
                prior_balance.adjustment_days = Decimal("0.00")
                prior_balance.used_days = Decimal("0.00")
                prior_balance.reserved_days = Decimal("0.00")
                prior_balance.beginning_credit_days = Decimal("0.00")
                prior_balance.credit_days = demo.beginning
                prior_balance.converted_to_cash_days = Decimal("0.00")

            if prior_changed:
                session.add(
                    LeaveCreditTransaction(
                        company_id=employee.company_id,
                        employee_id=employee.id,
                        leave_type_id=leave_type.id,
                        leave_balance_id=prior_balance.id,
                        created_by_user_id=None,
                        transaction_type="demo_beginning_credit_source",
                        amount_days=demo.beginning,
                        note=(
                            f"Test-only {year} Beginning Credit source: "
                            f"{demo.beginning} unused day(s) from {year - 1}."
                        ),
                    )
                )

            balance = session.scalar(
                select(LeaveBalance).where(
                    LeaveBalance.company_id == employee.company_id,
                    LeaveBalance.employee_id == employee.id,
                    LeaveBalance.leave_type_id == leave_type.id,
                    LeaveBalance.year == year,
                )
            )
            if balance is None:
                raise ValueError(
                    f"The {year} {leave_type.name} balance is unavailable."
                )

            previous_available = Decimal(balance.available_credits)
            current_changed = (
                Decimal(balance.carry_over_days) != demo.beginning
                or Decimal(balance.beginning_credit_days) != demo.beginning
                or Decimal(balance.allocated_days) != demo.credit
                or Decimal(balance.credit_days) != demo.credit
                or Decimal(balance.adjustment_days) != demo.adjustment
                or Decimal(balance.used_days) != demo.used
                or Decimal(balance.reserved_days) != demo.reserved
                or Decimal(balance.converted_to_cash_days) != demo.converted
            )
            balance.carry_over_days = demo.beginning
            balance.beginning_credit_days = demo.beginning
            balance.allocated_days = demo.credit
            balance.credit_days = demo.credit
            balance.adjustment_days = demo.adjustment
            balance.used_days = demo.used
            balance.reserved_days = demo.reserved
            balance.converted_to_cash_days = demo.converted

            if current_changed:
                session.add(
                    LeaveCreditTransaction(
                        company_id=employee.company_id,
                        employee_id=employee.id,
                        leave_type_id=leave_type.id,
                        leave_balance_id=balance.id,
                        created_by_user_id=None,
                        transaction_type="demo_credit_column_seed",
                        amount_days=demo.available - previous_available,
                        note=(
                            "Test-only leave-credit column demo. "
                            f"Beginning {demo.beginning}; Credit {demo.credit}; "
                            f"Adjustment {demo.adjustment}; Used {demo.used}; "
                            f"Reserved {demo.reserved}; Converted {demo.converted}; "
                            f"Available {demo.available}."
                        ),
                    )
                )
            applied.append((leave_type.name, demo))

        session.commit()

        verified_rows = {
            (item.leave_type.code or "").strip().upper(): item
            for item in service.credit_table_rows(
                company_id=employee.company_id,
                employee_id=employee.id,
                year=year,
            )
        }
        for code, demo in DEMO_BALANCES.items():
            row = verified_rows[code]
            actual = (
                Decimal(row.beginning_credit_days),
                Decimal(row.credit_days),
                Decimal(row.used_days),
                Decimal(row.reserved_days),
                Decimal(row.available_credits),
                Decimal(row.converted_to_cash_days),
            )
            expected = (
                demo.beginning,
                demo.credit,
                demo.used,
                demo.reserved,
                demo.available,
                demo.converted,
            )
            if actual != expected:
                raise RuntimeError(
                    f"{code} demo verification failed: "
                    f"expected {expected}, received {actual}."
                )
            if code == "VACATION":
                utilization = row.leave_utilization
                if utilization is None:
                    raise RuntimeError(
                        "Vacation Leave utilization demo is unavailable."
                    )
                expected_required = service._round_to_half_day(
                    demo.credit / Decimal("2")
                )
                expected_remaining = max(
                    Decimal("0.00"),
                    expected_required - demo.used,
                )
                utilization_actual = (
                    Decimal(utilization.required_days),
                    Decimal(utilization.used_days),
                    Decimal(utilization.remaining_days),
                )
                utilization_expected = (
                    expected_required,
                    demo.used,
                    expected_remaining,
                )
                if utilization_actual != utilization_expected:
                    raise RuntimeError(
                        "Vacation Leave utilization demo verification "
                        f"failed: expected {utilization_expected}, "
                        f"received {utilization_actual}."
                    )
        return applied


def main() -> None:
    """Back up the database and seed the requested test employee."""

    parser = argparse.ArgumentParser(
        description="Seed visible VL/SL leave-credit column test values."
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required confirmation before changing the test database.",
    )
    parser.add_argument(
        "--employee-number",
        default="191220",
        help="Target employee number; defaults to Lander Garcia (191220).",
    )
    parser.add_argument(
        "--year",
        type=int,
        default=datetime.now().year,
        help="Leave year to seed; defaults to the current year.",
    )
    args = parser.parse_args()
    if not args.confirm:
        parser.error("Seeding cancelled. Re-run with --confirm.")
    if args.year < 2000 or args.year > 2100:
        parser.error("Year must be between 2000 and 2100.")

    settings = get_settings()
    initialize_runtime_schema()
    backup_path = _backup_sqlite_database(settings)
    if backup_path is not None:
        print(f"SQLite backup created: {backup_path}")
    elif settings.database_url.startswith("sqlite"):
        raise FileNotFoundError("The configured SQLite database was not found.")
    else:
        print("Non-SQLite database detected; use an external backup first.")

    applied = _seed_employee(
        employee_number=args.employee_number.strip(),
        year=args.year,
    )
    print(
        f"Leave-credit column demo seeded for employee "
        f"{args.employee_number.strip()} ({args.year})."
    )
    for leave_name, demo in applied:
        print(
            f"- {leave_name}: Beginning={demo.beginning}, "
            f"Credit={demo.credit}, Used={demo.used}, "
            f"Reserved={demo.reserved}, Available={demo.available}, "
            f"Converted={demo.converted}"
        )


if __name__ == "__main__":
    main()
