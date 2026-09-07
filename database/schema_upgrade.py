"""Non-destructive upgrades for databases created by earlier checkpoints."""

import time

from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import OperationalError


_SQLITE_LOCK_RETRY_ATTEMPTS = 8
_SQLITE_LOCK_RETRY_BASE_SECONDS = 0.10


def _is_sqlite_lock_error(engine: Engine, exc: OperationalError) -> bool:
    """Return True only for SQLite's temporary write-lock error."""

    if engine.dialect.name != "sqlite":
        return False

    return "database is locked" in str(exc).lower()


def upgrade_existing_schema(engine: Engine) -> None:
    """Upgrade an existing schema, retrying temporary SQLite write locks.

    Streamlit may briefly overlap database work during a rerun or application
    restart. SQLite allows only one writer at a time, so a safe, idempotent
    schema upgrade is retried instead of crashing the whole application.
    """

    for attempt in range(_SQLITE_LOCK_RETRY_ATTEMPTS):
        try:
            _upgrade_existing_schema_once(engine)
            return
        except OperationalError as exc:
            if not _is_sqlite_lock_error(engine, exc):
                raise

            if attempt >= _SQLITE_LOCK_RETRY_ATTEMPTS - 1:
                raise

            # Drop pooled connections before the next attempt so a stale
            # connection cannot prolong the lock. Every upgrade block is
            # idempotent, therefore restarting the upgrade is safe even when
            # an earlier block already committed.
            engine.dispose()
            time.sleep(
                _SQLITE_LOCK_RETRY_BASE_SECONDS * (attempt + 1)
            )


def _upgrade_existing_schema_once(engine: Engine) -> None:
    """Add missing columns and normalize legacy values without deleting data."""

    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    if "companies" in table_names:
        company_columns = {
            column["name"]
            for column in inspector.get_columns("companies")
        }

        with engine.begin() as connection:
            if "theme_primary_color" not in company_columns:
                connection.execute(
                    text(
                        "ALTER TABLE companies "
                        "ADD COLUMN theme_primary_color "
                        "VARCHAR(7) NOT NULL DEFAULT '#4338E8'"
                    )
                )

            if "logo_filename" not in company_columns:
                connection.execute(
                    text(
                        "ALTER TABLE companies "
                        "ADD COLUMN logo_filename VARCHAR(255)"
                    )
                )

            attendance_columns = {
                "attendance_regular_hours": "NUMERIC(6, 2) NOT NULL DEFAULT 8.00",
                "attendance_lunch_minutes": "INTEGER NOT NULL DEFAULT 60",
                "ot_dinner_break_deduction_hours": "NUMERIC(5, 2) NOT NULL DEFAULT 0.75",
                "shifting_credits_enabled": "BOOLEAN NOT NULL DEFAULT 1",
                "shifting_credit_block_hours": "NUMERIC(5, 2) NOT NULL DEFAULT 4.00",
                "shifting_credit_required_blocks": "INTEGER NOT NULL DEFAULT 2",
                "shifting_credit_cutoff_day": "INTEGER NOT NULL DEFAULT 15",
                "shifting_credit_additional_vl_threshold_hours": "NUMERIC(5, 2) NOT NULL DEFAULT 8.00",
                "shifting_credit_additional_vl_days": "NUMERIC(5, 2) NOT NULL DEFAULT 0.50",
                "shifting_credit_additional_vl_also_payable": "BOOLEAN NOT NULL DEFAULT 0",
                "shifting_credit_excluded_positions_json": "TEXT NOT NULL DEFAULT '[\"Trainee\", \"Design Engineer I\", \"Design Engineer II\"]'",
                "shifting_credit_availability_cutoffs": "INTEGER NOT NULL DEFAULT 2",
                "shifting_credit_expiration_mode": "VARCHAR(30) NOT NULL DEFAULT 'follow_leave_reset'",
                "shifting_credit_expiration_month": "INTEGER NOT NULL DEFAULT 12",
                "shifting_credit_expiration_day": "INTEGER NOT NULL DEFAULT 31",
                "work_monday": "BOOLEAN NOT NULL DEFAULT 1",
                "work_tuesday": "BOOLEAN NOT NULL DEFAULT 1",
                "work_wednesday": "BOOLEAN NOT NULL DEFAULT 1",
                "work_thursday": "BOOLEAN NOT NULL DEFAULT 1",
                "work_friday": "BOOLEAN NOT NULL DEFAULT 1",
                "work_saturday": "BOOLEAN NOT NULL DEFAULT 0",
                "work_sunday": "BOOLEAN NOT NULL DEFAULT 0",
                "leave_reset_month": "INTEGER NOT NULL DEFAULT 1",
                "leave_reset_day": "INTEGER NOT NULL DEFAULT 1",
                "leave_utilization_enabled": "BOOLEAN NOT NULL DEFAULT 1",
                "leave_utilization_percentage": "NUMERIC(5, 2) NOT NULL DEFAULT 50.00",
                "manager_vl_retention_limit": "NUMERIC(8, 2) NOT NULL DEFAULT 13.00",
            }
            for column_name, column_sql in attendance_columns.items():
                if column_name not in company_columns:
                    connection.execute(
                        text(
                            f"ALTER TABLE companies ADD COLUMN "
                            f"{column_name} {column_sql}"
                        )
                    )

            missing_theme_color = connection.execute(
                text(
                    "SELECT 1 FROM companies "
                    "WHERE theme_primary_color IS NULL "
                    "OR trim(theme_primary_color) = '' "
                    "LIMIT 1"
                )
            ).first()

            # Do not issue a no-op UPDATE on every application startup. Even
            # an UPDATE that changes zero rows requests SQLite's writer lock.
            if missing_theme_color is not None:
                connection.execute(
                    text(
                        "UPDATE companies "
                        "SET theme_primary_color = '#4338E8' "
                        "WHERE theme_primary_color IS NULL "
                        "OR trim(theme_primary_color) = ''"
                    )
                )

    if "overtime_requests" in table_names:
        overtime_columns = {
            column["name"]
            for column in inspector.get_columns("overtime_requests")
        }
        payable_hours_added = "payable_hours" not in overtime_columns
        straight_vl_also_payable_added = (
            "straight_vl_also_payable" not in overtime_columns
        )
        with engine.begin() as connection:
            overtime_additions = {
                "payable_hours": "NUMERIC(8, 2) NOT NULL DEFAULT 0",
                "shifting_credit_hours": "NUMERIC(8, 2) NOT NULL DEFAULT 0",
                "shifting_credit_restored_hours": "NUMERIC(8, 2) NOT NULL DEFAULT 0",
                "shifting_credit_group": "VARCHAR(80)",
                "additional_vl_days": "NUMERIC(8, 2) NOT NULL DEFAULT 0",
                "straight_vl_also_payable": "BOOLEAN NOT NULL DEFAULT 0",
            }
            for column_name, column_sql in overtime_additions.items():
                if column_name not in overtime_columns:
                    connection.execute(
                        text(
                            f"ALTER TABLE overtime_requests ADD COLUMN "
                            f"{column_name} {column_sql}"
                        )
                    )

            # Existing approved/pending requests predate the dinner/shift rule.
            # Preserve their historical submitted amount as payable OT instead
            # of silently turning those rows into zero-hour requests.
            if payable_hours_added:
                connection.execute(
                    text(
                        "UPDATE overtime_requests "
                        "SET payable_hours = estimated_hours "
                        "WHERE payable_hours IS NULL OR payable_hours = 0"
                    )
                )
            if straight_vl_also_payable_added:
                # Before v8.8.203 every historical straight-OT VL grant also
                # remained payable. Preserve that historical behavior per row
                # while the new company default is conversion-only.
                connection.execute(
                    text(
                        "UPDATE overtime_requests "
                        "SET straight_vl_also_payable = 1 "
                        "WHERE additional_vl_days > 0"
                    )
                )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS "
                    "ix_overtime_requests_shifting_credit_group "
                    "ON overtime_requests (shifting_credit_group)"
                )
            )

    if "shifting_credits" in table_names:
        shifting_columns = {
            column["name"]
            for column in inspector.get_columns("shifting_credits")
        }
        with engine.begin() as connection:
            if "leave_request_id" not in shifting_columns:
                connection.execute(
                    text(
                        "ALTER TABLE shifting_credits "
                        "ADD COLUMN leave_request_id INTEGER"
                    )
                )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS "
                    "ix_shifting_credits_leave_request_id "
                    "ON shifting_credits (leave_request_id)"
                )
            )

    if "users" in table_names:
        user_columns = {
            column["name"]
            for column in inspector.get_columns("users")
        }

        if "clearance" not in user_columns:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE users "
                        "ADD COLUMN clearance INTEGER NOT NULL DEFAULT 2"
                    )
                )

                # Convert existing administrator roles to clearance 1.
                # All remaining roles become the standard user clearance.
                if "roles" in table_names:
                    connection.execute(
                        text(
                            """
                            UPDATE users
                            SET clearance = CASE
                                WHEN role_id IN (
                                    SELECT id
                                    FROM roles
                                    WHERE name IN (
                                        'super_admin',
                                        'company_admin',
                                        'hr_admin'
                                    )
                                )
                                THEN 1
                                ELSE 2
                            END
                            """
                        )
                    )

    if "employees" in table_names:
        employee_columns = {
            column["name"]
            for column in inspector.get_columns("employees")
        }

        with engine.begin() as connection:
            if "telephone_mobile_no" not in employee_columns:
                connection.execute(
                    text(
                        "ALTER TABLE employees "
                        "ADD COLUMN telephone_mobile_no VARCHAR(50)"
                    )
                )

            if "profile_image_filename" not in employee_columns:
                connection.execute(
                    text(
                        "ALTER TABLE employees "
                        "ADD COLUMN profile_image_filename VARCHAR(255)"
                    )
                )

            if "leader_id" not in employee_columns:
                connection.execute(
                    text(
                        "ALTER TABLE employees "
                        "ADD COLUMN leader_id INTEGER"
                    )
                )

            if "gender" not in employee_columns:
                connection.execute(
                    text(
                        "ALTER TABLE employees "
                        "ADD COLUMN gender VARCHAR(50)"
                    )
                )

            if "civil_status" not in employee_columns:
                connection.execute(
                    text(
                        "ALTER TABLE employees "
                        "ADD COLUMN civil_status VARCHAR(50)"
                    )
                )

            if "date_of_birth" not in employee_columns:
                connection.execute(
                    text(
                        "ALTER TABLE employees "
                        "ADD COLUMN date_of_birth DATE"
                    )
                )

            datetime_sql = (
                "TIMESTAMP WITH TIME ZONE"
                if engine.dialect.name == "postgresql"
                else "DATETIME"
            )
            if "archived_at" not in employee_columns:
                connection.execute(
                    text(
                        "ALTER TABLE employees "
                        f"ADD COLUMN archived_at {datetime_sql}"
                    )
                )

            if "archived_by_user_id" not in employee_columns:
                connection.execute(
                    text(
                        "ALTER TABLE employees "
                        "ADD COLUMN archived_by_user_id INTEGER"
                    )
                )

            if "edit_version" not in employee_columns:
                connection.execute(
                    text(
                        "ALTER TABLE employees "
                        "ADD COLUMN edit_version INTEGER NOT NULL DEFAULT 1"
                    )
                )

            if "last_edited_by_user_id" not in employee_columns:
                connection.execute(
                    text(
                        "ALTER TABLE employees "
                        "ADD COLUMN last_edited_by_user_id INTEGER"
                    )
                )

            # Earlier versions stored active/inactive. Preserve the records
            # while converting them to the new user-facing terms.
            connection.execute(
                text(
                    """
                    UPDATE employees
                    SET employment_status = 'employed'
                    WHERE lower(employment_status) = 'active'
                    """
                )
            )

            connection.execute(
                text(
                    """
                    UPDATE employees
                    SET employment_status = 'resigned'
                    WHERE lower(employment_status) IN (
                        'inactive',
                        'terminated'
                    )
                    """
                )
            )

            # Existing resigned rows become archived without deleting or
            # rewriting any employee-linked records.
            connection.execute(
                text(
                    "UPDATE employees SET archived_at = COALESCE("
                    "archived_at, updated_at, CURRENT_TIMESTAMP) "
                    "WHERE lower(employment_status) = 'resigned'"
                )
            )
    if "hr_policies" in table_names:
        policy_columns = {
            column["name"]
            for column in inspector.get_columns("hr_policies")
        }

        datetime_sql = (
            "TIMESTAMP WITH TIME ZONE"
            if engine.dialect.name == "postgresql"
            else "DATETIME"
        )

        with engine.begin() as connection:
            if "public_id" not in policy_columns:
                connection.execute(
                    text(
                        "ALTER TABLE hr_policies "
                        "ADD COLUMN public_id VARCHAR(30)"
                    )
                )

            if "trashed_at" not in policy_columns:
                connection.execute(
                    text(
                        "ALTER TABLE hr_policies "
                        f"ADD COLUMN trashed_at {datetime_sql}"
                    )
                )

            if "trashed_by_user_id" not in policy_columns:
                connection.execute(
                    text(
                        "ALTER TABLE hr_policies "
                        "ADD COLUMN trashed_by_user_id INTEGER"
                    )
                )

            rows = connection.execute(
                text(
                    "SELECT id FROM hr_policies "
                    "WHERE public_id IS NULL OR public_id = ''"
                )
            ).all()

            for row in rows:
                connection.execute(
                    text(
                        "UPDATE hr_policies "
                        "SET public_id = :public_id WHERE id = :id"
                    ),
                    {
                        "public_id": f"PID_{int(row.id):03d}",
                        "id": int(row.id),
                    },
                )

            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "ux_hr_policies_public_id "
                    "ON hr_policies (public_id)"
                )
            )


    # Smart reminder milestones and recoverable Reminder Bin.
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    if "event_reminders" in table_names:
        reminder_columns = {
            column["name"]
            for column in inspector.get_columns("event_reminders")
        }
        datetime_sql = (
            "TIMESTAMP WITH TIME ZONE"
            if engine.dialect.name == "postgresql"
            else "DATETIME"
        )

        with engine.begin() as connection:
            for column_name in (
                "reminder_one_month_sent_at",
                "reminder_two_weeks_sent_at",
                "reminder_one_week_sent_at",
                "archived_at",
            ):
                if column_name not in reminder_columns:
                    connection.execute(
                        text(
                            "ALTER TABLE event_reminders "
                            f"ADD COLUMN {column_name} {datetime_sql}"
                        )
                    )

            if "archived_by_user_id" not in reminder_columns:
                connection.execute(
                    text(
                        "ALTER TABLE event_reminders "
                        "ADD COLUMN archived_by_user_id INTEGER"
                    )
                )

            # A legacy reminder already marked sent must not generate three
            # duplicate catch-up notifications after this upgrade.
            connection.execute(
                text(
                    """
                    UPDATE event_reminders
                    SET reminder_one_month_sent_at = reminder_sent_at,
                        reminder_two_weeks_sent_at = reminder_sent_at,
                        reminder_one_week_sent_at = reminder_sent_at
                    WHERE reminder_sent_at IS NOT NULL
                      AND (reminder_one_month_sent_at IS NULL
                           OR reminder_two_weeks_sent_at IS NULL
                           OR reminder_one_week_sent_at IS NULL)
                    """
                )
            )


    # Preserve reminders created in the short-lived announcement-bound design.
    # The new architecture stores planning reminders independently, while an
    # optional announcement link remains available after the post is prepared.
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    if "announcements" in table_names and "event_reminders" in table_names:
        announcement_columns = {
            column["name"]
            for column in inspector.get_columns("announcements")
        }
        legacy_columns = {
            "event_start_at",
            "event_end_at",
            "reminder_enabled",
            "reminder_lead_minutes",
            "reminder_at",
            "reminder_sent_at",
        }

        if legacy_columns.issubset(announcement_columns):
            with engine.begin() as connection:
                legacy_rows = connection.execute(
                    text(
                        """
                        SELECT
                            id, company_id, created_by_user_id,
                            updated_by_user_id, title, category, summary,
                            event_start_at, event_end_at,
                            reminder_lead_minutes, reminder_at,
                            reminder_sent_at
                        FROM announcements
                        WHERE reminder_enabled = 1
                          AND event_start_at IS NOT NULL
                          AND reminder_at IS NOT NULL
                        """
                    )
                ).mappings().all()

                for row in legacy_rows:
                    existing = connection.execute(
                        text(
                            "SELECT id FROM event_reminders "
                            "WHERE announcement_id = :announcement_id"
                        ),
                        {"announcement_id": int(row["id"])},
                    ).first()

                    if existing is not None:
                        continue

                    connection.execute(
                        text(
                            """
                            INSERT INTO event_reminders (
                                public_id, company_id, created_by_user_id,
                                updated_by_user_id, title, category, notes,
                                event_start_at, event_end_at,
                                reminder_lead_minutes, reminder_at,
                                reminder_sent_at, status, announcement_id
                            ) VALUES (
                                :public_id, :company_id, :created_by_user_id,
                                :updated_by_user_id, :title, :category, :notes,
                                :event_start_at, :event_end_at,
                                :reminder_lead_minutes, :reminder_at,
                                :reminder_sent_at, 'announcement_ready',
                                :announcement_id
                            )
                            """
                        ),
                        {
                            "public_id": f"REM_MIG_{int(row['id']):06d}",
                            "company_id": int(row["company_id"]),
                            "created_by_user_id": int(row["created_by_user_id"]),
                            "updated_by_user_id": int(row["updated_by_user_id"]),
                            "title": str(row["title"]),
                            "category": "Company Event",
                            "notes": str(row["summary"] or ""),
                            "event_start_at": row["event_start_at"],
                            "event_end_at": row["event_end_at"],
                            "reminder_lead_minutes": int(
                                row["reminder_lead_minutes"] or 10080
                            ),
                            "reminder_at": row["reminder_at"],
                            "reminder_sent_at": row["reminder_sent_at"],
                            "announcement_id": int(row["id"]),
                        },
                    )


    # Phase 1 leave-credit ledger columns. Existing records are retained and
    # mapped to the clearer Beginning Credit / Credit / Converted to Cash
    # structure only when the new columns are first introduced.
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    if "leave_balances" in table_names:
        balance_columns = {
            column["name"]
            for column in inspector.get_columns("leave_balances")
        }
        phase_one_columns_added = False

        with engine.begin() as connection:
            for column_name in (
                "beginning_credit_days",
                "credit_days",
                "converted_to_cash_days",
            ):
                if column_name not in balance_columns:
                    connection.execute(
                        text(
                            "ALTER TABLE leave_balances "
                            f"ADD COLUMN {column_name} "
                            "NUMERIC(8, 2) NOT NULL DEFAULT 0.00"
                        )
                    )
                    phase_one_columns_added = True

            if phase_one_columns_added:
                # Preserve the numeric meaning of every older balance:
                # carry-over becomes Beginning Credit, automatic allocation
                # becomes Credit, and the existing adjustment column remains
                # the separate administrator correction bucket.
                connection.execute(
                    text(
                        "UPDATE leave_balances "
                        "SET beginning_credit_days = "
                        "COALESCE(carry_over_days, 0), "
                        "credit_days = "
                        "COALESCE(allocated_days, 0), "
                        "converted_to_cash_days = "
                        "COALESCE(converted_to_cash_days, 0)"
                    )
                )

    # Leave approval and date-based credit posting.
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    if "leave_types" in table_names:
        leave_type_columns = {
            column["name"]
            for column in inspector.get_columns("leave_types")
        }

        with engine.begin() as connection:
            if (
                "handover_plan_requirement"
                not in leave_type_columns
            ):
                connection.execute(
                    text(
                        "ALTER TABLE leave_types "
                        "ADD COLUMN handover_plan_requirement "
                        "VARCHAR(20) NOT NULL DEFAULT 'optional'"
                    )
                )
                connection.execute(
                    text(
                        "UPDATE leave_types "
                        "SET handover_plan_requirement = "
                        "CASE "
                        "WHEN upper(code) IN ('VACATION', 'LWOP') "
                        "THEN 'recommended' "
                        "ELSE 'optional' END"
                    )
                )

    if "leave_requests" in table_names:
        request_columns = {
            column["name"]
            for column in inspector.get_columns("leave_requests")
        }
        datetime_sql = (
            "TIMESTAMP WITH TIME ZONE"
            if engine.dialect.name == "postgresql"
            else "DATETIME"
        )
        boolean_sql = (
            "BOOLEAN NOT NULL DEFAULT FALSE"
            if engine.dialect.name == "postgresql"
            else "BOOLEAN NOT NULL DEFAULT 0"
        )
        paid_true_sql = (
            "TRUE"
            if engine.dialect.name == "postgresql"
            else "1"
        )
        added_reservation_tracking = (
            "reservation_posted" not in request_columns
        )

        with engine.begin() as connection:
            additions = (
                (
                    "handover_plan",
                    "TEXT",
                ),
                (
                    "manager_comment",
                    "TEXT",
                ),
                (
                    "reviewed_at",
                    datetime_sql,
                ),
                (
                    "reviewed_by_user_id",
                    "INTEGER",
                ),
                (
                    "approved_at",
                    datetime_sql,
                ),
                (
                    "completed_at",
                    datetime_sql,
                ),
                (
                    "reservation_posted",
                    boolean_sql,
                ),
                (
                    "posted_working_days",
                    "NUMERIC(8, 2) NOT NULL DEFAULT 0",
                ),
                (
                    "fallback_leave_type_id",
                    "INTEGER",
                ),
                (
                    "primary_credit_days",
                    "NUMERIC(8, 2) NOT NULL DEFAULT 0",
                ),
                (
                    "fallback_credit_days",
                    "NUMERIC(8, 2) NOT NULL DEFAULT 0",
                ),
                (
                    "lwop_days",
                    "NUMERIC(8, 2) NOT NULL DEFAULT 0",
                ),
                ("filed_by_employee_id", "INTEGER"),
                ("filed_by_user_id", "INTEGER"),
                ("filed_on_behalf", boolean_sql),
                ("leader_employee_id", "INTEGER"),
                ("current_approver_employee_id", "INTEGER"),
                ("approval_stage", "VARCHAR(30) NOT NULL DEFAULT 'manager'"),
                ("to_emails_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("leader_comment", "TEXT"),
                ("leader_reviewed_at", datetime_sql),
                ("leader_reviewed_by_user_id", "INTEGER"),
                ("cancellation_status", "VARCHAR(30) NOT NULL DEFAULT 'none'"),
                ("cancellation_reason", "TEXT"),
                ("cancellation_requested_at", datetime_sql),
                ("cancellation_requested_by_user_id", "INTEGER"),
                ("cancellation_requested_by_employee_id", "INTEGER"),
                ("cancellation_effective_date", "DATE"),
                ("cancellation_reviewed_at", datetime_sql),
                ("cancellation_reviewed_by_user_id", "INTEGER"),
                ("cancellation_comment", "TEXT"),
                ("cancellation_restored_primary_days", "NUMERIC(8, 2) NOT NULL DEFAULT 0"),
                ("cancellation_restored_fallback_days", "NUMERIC(8, 2) NOT NULL DEFAULT 0"),
                ("cancellation_removed_lwop_days", "NUMERIC(8, 2) NOT NULL DEFAULT 0"),
                ("duration_code", "VARCHAR(10) NOT NULL DEFAULT '90503'"),
                ("reason_code", "VARCHAR(10) NOT NULL DEFAULT '0'"),
                ("reason_other", "TEXT"),
            )

            for column_name, column_sql in additions:
                if column_name not in request_columns:
                    connection.execute(
                        text(
                            "ALTER TABLE leave_requests "
                            f"ADD COLUMN {column_name} "
                            f"{column_sql}"
                        )
                    )

            connection.execute(
                text(
                    "UPDATE leave_requests "
                    "SET filed_by_employee_id = employee_id "
                    "WHERE filed_by_employee_id IS NULL"
                )
            )
            connection.execute(
                text(
                    "UPDATE leave_requests "
                    "SET duration_code = '90503' "
                    "WHERE duration_code IS NULL OR trim(duration_code) = ''"
                )
            )
            connection.execute(
                text(
                    "UPDATE leave_requests "
                    "SET reason_code = '0' "
                    "WHERE reason_code IS NULL OR trim(reason_code) = ''"
                )
            )
            connection.execute(
                text(
                    "UPDATE leave_requests "
                    "SET reason_other = reason "
                    "WHERE reason_other IS NULL AND reason IS NOT NULL"
                )
            )
            connection.execute(
                text(
                    "UPDATE leave_requests "
                    "SET current_approver_employee_id = manager_employee_id "
                    "WHERE current_approver_employee_id IS NULL"
                )
            )
            connection.execute(
                text(
                    "UPDATE leave_requests "
                    "SET approval_stage = 'manager' "
                    "WHERE approval_stage IS NULL OR trim(approval_stage) = ''"
                )
            )
            connection.execute(
                text(
                    "UPDATE leave_requests "
                    "SET cancellation_status = 'none' "
                    "WHERE cancellation_status IS NULL "
                    "OR trim(cancellation_status) = ''"
                )
            )

            # Existing requests predate the paid-credit/LWOP split. Preserve
            # their previous behavior by assigning all paid requests to the
            # primary leave type and all non-paid requests to LWOP.
            connection.execute(
                text(
                    f"""
                    UPDATE leave_requests
                    SET primary_credit_days = CASE
                            WHEN leave_type_id IN (
                                SELECT id FROM leave_types
                                WHERE is_paid = {paid_true_sql}
                                  AND annual_credits > 0
                            )
                            THEN requested_days ELSE 0 END,
                        fallback_credit_days = 0,
                        lwop_days = CASE
                            WHEN leave_type_id IN (
                                SELECT id FROM leave_types
                                WHERE is_paid = {paid_true_sql}
                                  AND annual_credits > 0
                            )
                            THEN 0 ELSE requested_days END
                    WHERE COALESCE(primary_credit_days, 0) = 0
                      AND COALESCE(fallback_credit_days, 0) = 0
                      AND COALESCE(lwop_days, 0) = 0
                    """
                )
            )

            # v8.5.x reserved credits immediately on submission. When this
            # tracking field is first introduced, release those pending
            # reservations and convert the request to the new workflow.
            if added_reservation_tracking:
                legacy_rows = connection.execute(
                    text(
                        "SELECT id, company_id, employee_id, "
                        "leave_type_id, start_date, requested_days "
                        "FROM leave_requests "
                        "WHERE status = 'sent_to_manager'"
                    )
                ).mappings().all()

                for row in legacy_rows:
                    start_year = int(
                        str(row["start_date"])[:4]
                    )
                    connection.execute(
                        text(
                            "UPDATE leave_balances "
                            "SET reserved_days = CASE "
                            "WHEN reserved_days >= :days "
                            "THEN reserved_days - :days "
                            "ELSE 0 END "
                            "WHERE company_id = :company_id "
                            "AND employee_id = :employee_id "
                            "AND leave_type_id = :leave_type_id "
                            "AND year = :year"
                        ),
                        {
                            "days": row["requested_days"],
                            "company_id": row["company_id"],
                            "employee_id": row["employee_id"],
                            "leave_type_id": row["leave_type_id"],
                            "year": start_year,
                        },
                    )

                connection.execute(
                    text(
                        "UPDATE leave_requests "
                        "SET status = 'pending_manager_approval', "
                        "reservation_posted = "
                        + (
                            "FALSE"
                            if engine.dialect.name == "postgresql"
                            else "0"
                        )
                        + ", posted_working_days = 0 "
                        "WHERE status = 'sent_to_manager'"
                    )
                )

    # Attendance sessions preserve actual punches and quarter-hour payroll
    # values while retaining the legacy daily summary columns.
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if "attendance_records" in table_names:
        attendance_columns = {
            column["name"]
            for column in inspector.get_columns("attendance_records")
        }
        with engine.begin() as connection:
            for column_name, column_sql in (
                ("leave_duration_code", "VARCHAR(10)"),
                ("leave_hours", "NUMERIC(8, 2) NOT NULL DEFAULT 0.00"),
                ("undertime_hours", "NUMERIC(8, 2) NOT NULL DEFAULT 0.00"),
            ):
                if column_name not in attendance_columns:
                    connection.execute(
                        text(
                            "ALTER TABLE attendance_records "
                            f"ADD COLUMN {column_name} {column_sql}"
                        )
                    )

    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if "attendance_sessions" in table_names and "attendance_records" in table_names:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO attendance_sessions (
                        company_id, attendance_record_id, sequence_number,
                        work_status, actual_time_in, actual_time_out,
                        rounded_time_in, rounded_time_out, source,
                        created_at, updated_at
                    )
                    SELECT ar.company_id, ar.id, 1,
                           CASE WHEN ar.work_status IN ('WFO', 'WFH')
                                THEN ar.work_status ELSE 'WFO' END,
                           ar.time_in, ar.time_out, ar.time_in, ar.time_out,
                           'legacy_migration', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    FROM attendance_records ar
                    WHERE ar.time_in IS NOT NULL
                      AND NOT EXISTS (
                          SELECT 1 FROM attendance_sessions session
                          WHERE session.attendance_record_id = ar.id
                      )
                    """
                )
            )
    # Recoverable archive/bin for employee disciplinary records.
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if "employee_disciplinary_records" in table_names:
        disciplinary_columns = {
            column["name"]
            for column in inspector.get_columns("employee_disciplinary_records")
        }
        datetime_sql = (
            "TIMESTAMP WITH TIME ZONE"
            if engine.dialect.name == "postgresql"
            else "DATETIME"
        )
        with engine.begin() as connection:
            if "archived_at" not in disciplinary_columns:
                connection.execute(
                    text(
                        "ALTER TABLE employee_disciplinary_records "
                        f"ADD COLUMN archived_at {datetime_sql}"
                    )
                )
            if "archived_by_user_id" not in disciplinary_columns:
                connection.execute(
                    text(
                        "ALTER TABLE employee_disciplinary_records "
                        "ADD COLUMN archived_by_user_id INTEGER"
                    )
                )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS "
                    "ix_employee_disciplinary_records_archived_at "
                    "ON employee_disciplinary_records (archived_at)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS "
                    "ix_employee_disciplinary_records_archived_by_user_id "
                    "ON employee_disciplinary_records (archived_by_user_id)"
                )
            )

