"""Focused checks for the recoverable leave-credit column demo seeder."""

from decimal import Decimal
from pathlib import Path

from scripts.seed_leave_credit_column_demo import DEMO_BALANCES


ROOT = Path(__file__).resolve().parents[1]


def test_demo_targets_only_regular_vl_and_sl_ledgers() -> None:
    assert set(DEMO_BALANCES) == {"VACATION", "SICK"}


def test_demo_values_make_every_requested_column_verifiable() -> None:
    vacation = DEMO_BALANCES["VACATION"]
    sick = DEMO_BALANCES["SICK"]
    assert vacation.available == Decimal("41.00")
    assert sick.available == Decimal("13.00")
    assert vacation.beginning > 0 and sick.beginning > 0
    assert vacation.converted > 0 and sick.converted > 0
    assert vacation.used > 0 and sick.used > 0


def test_seeder_is_confirmed_backed_up_and_employee_scoped() -> None:
    source = (
        ROOT / "scripts/seed_leave_credit_column_demo.py"
    ).read_text(encoding="utf-8")
    assert '"--confirm"' in source
    assert "source.backup(destination)" in source
    assert "Employee.employee_number == employee_number" in source
    assert "demo_beginning_credit_source" in source
    assert "demo_credit_column_seed" in source
