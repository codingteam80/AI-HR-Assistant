"""Run the idempotent January SL/VL annual-accrual batch.

Purpose:
- Add the current year's Vacation Leave and Sick Leave credits.
- Use the completed-tenure bracket on January 1:
  1–5 years = 15, 6–10 = 17, 11–15 = 20, 16–20 = 23, 21+ = 26 days.
- Carry the previous year's unused SL/VL into Beginning Credit.
- Avoid duplicate credits when the command is run more than once.

The Streamlit leave pages call the same processing automatically. This script
is provided for an explicit January batch or Windows Task Scheduler job.

Examples:
    python -m scripts.process_january_leave_accrual
    python -m scripts.process_january_leave_accrual --year 2027
    python -m scripts.process_january_leave_accrual --company-code DEFAULT
"""

from __future__ import annotations

import argparse
from datetime import date

from sqlalchemy import select

from database.runtime_schema import initialize_runtime_schema
from database.session import SessionFactory
from models.company import Company
from services.leave_service import LeaveService


def _company_ids(*, company_code: str | None) -> list[int]:
    """Return the requested company IDs using an isolated read session."""

    with SessionFactory() as session:
        statement = select(Company.id).order_by(Company.id)
        if company_code:
            statement = statement.where(
                Company.code == company_code.strip().upper()
            )
        company_ids = [int(value) for value in session.scalars(statement)]

    if company_code and not company_ids:
        raise ValueError(
            f"Company code '{company_code.strip().upper()}' was not found."
        )
    return company_ids


def main() -> None:
    """Process one year's annual accrual once per employee and leave type."""

    parser = argparse.ArgumentParser(
        description="Process January Vacation and Sick Leave annual credits."
    )
    parser.add_argument(
        "--year",
        type=int,
        default=date.today().year,
        help="Leave year to process; defaults to the current year.",
    )
    parser.add_argument(
        "--company-code",
        help="Optional company code; omit to process every company.",
    )
    args = parser.parse_args()

    if args.year < 2000 or args.year > 2200:
        parser.error("Year must be between 2000 and 2200.")

    initialize_runtime_schema()
    company_ids = _company_ids(company_code=args.company_code)

    for company_id in company_ids:
        with SessionFactory() as session:
            LeaveService(session).ensure_current_year_balances(
                company_id,
                args.year,
            )

    print(
        f"January leave accrual and cash conversion completed for {args.year}. "
        f"Companies processed: {len(company_ids)}."
    )
    print("The batch is idempotent; rerunning it does not duplicate credits.")


if __name__ == "__main__":
    main()
