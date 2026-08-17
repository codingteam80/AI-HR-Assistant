"""Regression checks for the v8.8.109 existing-account login repair."""

from pathlib import Path

from sqlalchemy import create_engine, inspect, text

from database.runtime_schema import _has_login_required_schema
from database.schema_upgrade import upgrade_existing_schema


ROOT = Path(__file__).resolve().parents[1]


def test_legacy_company_schema_is_repaired_before_login() -> None:
    """Attendance fields required by Company queries are added safely."""

    engine = create_engine("sqlite+pysqlite:///:memory:")

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE companies (
                    id INTEGER PRIMARY KEY,
                    code VARCHAR(50) NOT NULL,
                    name VARCHAR(200) NOT NULL,
                    theme_primary_color VARCHAR(7) NOT NULL DEFAULT '#4338E8',
                    logo_filename VARCHAR(255),
                    is_active BOOLEAN NOT NULL DEFAULT 1,
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO companies (id, code, name, is_active)
                VALUES (1, 'TSUKIDEN', 'Test Company', 1)
                """
            )
        )

    assert _has_login_required_schema(engine) is False

    upgrade_existing_schema(engine)

    assert _has_login_required_schema(engine) is True
    columns = {
        column["name"]
        for column in inspect(engine).get_columns("companies")
    }
    assert {
        "attendance_regular_hours",
        "attendance_lunch_minutes",
        "work_monday",
        "work_sunday",
    }.issubset(columns)

    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT attendance_regular_hours,
                       attendance_lunch_minutes,
                       work_monday,
                       work_sunday
                FROM companies WHERE id = 1
                """
            )
        ).one()

    assert float(row.attendance_regular_hours) == 8.0
    assert row.attendance_lunch_minutes == 60
    assert bool(row.work_monday) is True
    assert bool(row.work_sunday) is False


def test_checkpoint_version_is_v88109() -> None:
    settings = (ROOT / "config/settings.py").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert 'app_version: str = "0.8.8.' in settings
    assert "v8.8.109 — Existing Account Login Schema Repair" in readme
