"""Tenure brackets and leave-credit column semantics regression checks."""

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from services.leave_service import LeaveService


ROOT = Path(__file__).resolve().parents[1]


def test_completed_tenure_uses_non_cumulative_credit_brackets() -> None:
    expected = {
        0: "15.00",
        1: "15.00",
        5: "15.00",
        6: "17.00",
        10: "17.00",
        11: "20.00",
        15: "20.00",
        16: "23.00",
        20: "23.00",
        21: "26.00",
        25: "26.00",
        40: "26.00",
    }
    for years, credit in expected.items():
        assert LeaveService.annual_tenure_credit(years) == Decimal(credit)


def test_cash_conversion_is_fixed_before_usage_is_deducted() -> None:
    balance = SimpleNamespace(
        beginning_credit_days=Decimal("30.00"),
        credit_days=Decimal("17.00"),
        adjustment_days=Decimal("0.00"),
        used_days=Decimal("3.00"),
        reserved_days=Decimal("0.00"),
    )
    assert LeaveService._opening_cash_conversion_amount(
        balance=balance,
        retained_limit=Decimal("45.00"),
    ) == Decimal("2.00")


def test_credit_column_excludes_manual_adjustments_in_both_portals() -> None:
    admin = (ROOT / "ui/pages/admin/leave_management_page.py").read_text(
        encoding="utf-8"
    )
    employee = (ROOT / "ui/pages/user/leave_management_page.py").read_text(
        encoding="utf-8"
    )
    assert '"Credit": (\n                    _days(item.credit_days)' in admin
    assert '"Credit": (\n                    _days(balance.credit_days)' in employee
    assert "Decimal(item.credit_days)\n                        + Decimal(item.adjustment_days)" not in admin
    assert "Decimal(balance.credit_days)\n                        + Decimal(balance.adjustment_days)" not in employee


def test_visible_demo_columns_reconcile_without_hidden_adjustments() -> None:
    from scripts.seed_leave_credit_column_demo import DEMO_BALANCES

    vacation = DEMO_BALANCES["VACATION"]
    sick = DEMO_BALANCES["SICK"]
    assert vacation.adjustment == Decimal("0.00")
    assert sick.adjustment == Decimal("0.00")
    assert vacation.available == Decimal("41.00")
    assert sick.available == Decimal("13.00")
