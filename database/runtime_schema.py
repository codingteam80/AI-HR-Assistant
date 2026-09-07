"""Create missing tables and apply safe upgrades at application startup."""

from threading import Lock

from sqlalchemy import Engine, inspect

from database.base import Base
from database.schema_upgrade import upgrade_existing_schema
from database.session import engine


_SCHEMA_LOCK = Lock()
_SCHEMA_READY = False

# These fields are loaded by ``CompanyRepository`` during every login.  A
# partially upgraded database therefore prevents all existing accounts from
# authenticating before password verification is even reached.
_LOGIN_REQUIRED_COMPANY_COLUMNS = {
    "attendance_regular_hours",
    "attendance_lunch_minutes",
    "ot_dinner_break_deduction_hours",
    "shifting_credits_enabled",
    "shifting_credit_block_hours",
    "shifting_credit_required_blocks",
    "shifting_credit_cutoff_day",
    "shifting_credit_additional_vl_threshold_hours",
    "shifting_credit_additional_vl_days",
    "shifting_credit_additional_vl_also_payable",
    "shifting_credit_excluded_positions_json",
    "shifting_credit_availability_cutoffs",
    "shifting_credit_expiration_mode",
    "shifting_credit_expiration_month",
    "shifting_credit_expiration_day",
    "work_monday",
    "work_tuesday",
    "work_wednesday",
    "work_thursday",
    "work_friday",
    "work_saturday",
    "work_sunday",
    "leave_reset_month",
    "leave_reset_day",
    "leave_utilization_enabled",
    "leave_utilization_percentage",
    "manager_vl_retention_limit",
}
_REQUIRED_RUNTIME_TABLES = {
    "companies",
    "company_workdays",
    "attendance_sessions",
    "overtime_requests",
    "shifting_credits",
    "employee_history",
    "onboarding_checklist_items",
    "employee_onboarding_progress",
    "company_benefits",
    "audit_events",
    "hr_contacts",
    "policy_violations",
    "employee_disciplinary_records",
}
_REQUIRED_EMPLOYEE_COLUMNS = {
    "archived_at",
    "archived_by_user_id",
    "edit_version",
    "last_edited_by_user_id",
    "profile_image_filename",
}
_REQUIRED_LEAVE_REQUEST_COLUMNS = {
    "duration_code",
    "reason_code",
    "reason_other",
}
_REQUIRED_ATTENDANCE_RECORD_COLUMNS = {
    "leave_duration_code",
    "leave_hours",
    "undertime_hours",
}
_REQUIRED_ATTENDANCE_SESSION_COLUMNS = {
    "actual_time_in",
    "actual_time_out",
    "rounded_time_in",
    "rounded_time_out",
    "work_status",
}

_REQUIRED_DISCIPLINARY_RECORD_COLUMNS = {
    "archived_at",
    "archived_by_user_id",
}

_REQUIRED_SHIFTING_CREDIT_COLUMNS = {
    "leave_request_id",
}

_REQUIRED_OVERTIME_REQUEST_COLUMNS = {
    "payable_hours",
    "shifting_credit_hours",
    "shifting_credit_restored_hours",
    "shifting_credit_group",
    "additional_vl_days",
    "straight_vl_also_payable",
}


def _has_login_required_schema(database_engine: Engine) -> bool:
    """Return whether an existing database can load the Company model."""

    schema_inspector = inspect(database_engine)

    if "companies" not in schema_inspector.get_table_names():
        return False

    company_columns = {
        column["name"]
        for column in schema_inspector.get_columns("companies")
    }

    return _LOGIN_REQUIRED_COMPANY_COLUMNS.issubset(company_columns)


def _has_runtime_schema(database_engine: Engine) -> bool:
    """Return whether login columns and all current runtime tables exist."""

    schema_inspector = inspect(database_engine)
    table_names = set(schema_inspector.get_table_names())
    if not (
        _REQUIRED_RUNTIME_TABLES.issubset(table_names)
        and _has_login_required_schema(database_engine)
        and {"leave_requests", "attendance_records", "employees"}.issubset(table_names)
    ):
        return False
    leave_columns = {
        column["name"]
        for column in schema_inspector.get_columns("leave_requests")
    }
    attendance_columns = {
        column["name"]
        for column in schema_inspector.get_columns("attendance_records")
    }
    session_columns = {
        column["name"]
        for column in schema_inspector.get_columns("attendance_sessions")
    }
    employee_columns = {
        column["name"]
        for column in schema_inspector.get_columns("employees")
    }
    disciplinary_columns = {
        column["name"]
        for column in schema_inspector.get_columns("employee_disciplinary_records")
    }
    overtime_columns = {
        column["name"]
        for column in schema_inspector.get_columns("overtime_requests")
    }
    shifting_credit_columns = {
        column["name"]
        for column in schema_inspector.get_columns("shifting_credits")
    }
    return (
        _REQUIRED_LEAVE_REQUEST_COLUMNS.issubset(leave_columns)
        and _REQUIRED_ATTENDANCE_RECORD_COLUMNS.issubset(attendance_columns)
        and _REQUIRED_ATTENDANCE_SESSION_COLUMNS.issubset(session_columns)
        and _REQUIRED_EMPLOYEE_COLUMNS.issubset(employee_columns)
        and _REQUIRED_DISCIPLINARY_RECORD_COLUMNS.issubset(disciplinary_columns)
        and _REQUIRED_OVERTIME_REQUEST_COLUMNS.issubset(overtime_columns)
        and _REQUIRED_SHIFTING_CREDIT_COLUMNS.issubset(shifting_credit_columns)
    )


def initialize_runtime_schema() -> None:
    """Create new tables and upgrade older databases once per process."""

    global _SCHEMA_READY

    # Do not trust only the in-memory flag. During Streamlit development the
    # Python process can survive a code update while the SQLite file still has
    # the previous checkpoint's schema. In that state every login fails with a
    # missing-column error. A lightweight inspection keeps existing accounts
    # usable without modifying an already-current database.
    if _SCHEMA_READY and _has_runtime_schema(engine):
        return

    with _SCHEMA_LOCK:
        if _SCHEMA_READY and _has_runtime_schema(engine):
            return

        import models  # noqa: F401

        # New databases receive the complete schema immediately.
        # Existing databases keep all records and receive only missing fields.
        Base.metadata.create_all(bind=engine)
        upgrade_existing_schema(engine)

        if not _has_runtime_schema(engine):
            raise RuntimeError(
                "The database schema upgrade did not complete."
            )

        _SCHEMA_READY = True
