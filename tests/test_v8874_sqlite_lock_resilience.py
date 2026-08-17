"""Regression tests for v8.8.74 SQLite lock resilience."""

from pathlib import Path
import sqlite3
import threading
import time

from sqlalchemy import create_engine, text

from database.schema_upgrade import upgrade_existing_schema
from database.session import _build_connect_args


def test_sqlite_connect_args_wait_for_busy_writer() -> None:
    args = _build_connect_args("sqlite:///./data/test.db")

    assert args["check_same_thread"] is False
    assert float(args["timeout"]) >= 30.0


def test_schema_upgrade_retries_temporary_sqlite_lock(tmp_path: Path) -> None:
    database_path = tmp_path / "locked_upgrade.db"
    url = f"sqlite:///{database_path.as_posix()}"
    engine = create_engine(
        url,
        connect_args={"check_same_thread": False, "timeout": 0.01},
    )

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE companies (
                    id INTEGER PRIMARY KEY,
                    code VARCHAR(50) NOT NULL,
                    name VARCHAR(200) NOT NULL,
                    is_active BOOLEAN NOT NULL,
                    theme_primary_color VARCHAR(7),
                    logo_filename VARCHAR(255)
                )
                """
            )
        )
        connection.execute(
            text(
                "INSERT INTO companies "
                "(id, code, name, is_active, theme_primary_color) "
                "VALUES (1, 'LOCK', 'Lock Test', 1, '')"
            )
        )

    blocker = sqlite3.connect(
        database_path,
        timeout=0.01,
        check_same_thread=False,
    )
    blocker.execute("BEGIN EXCLUSIVE")
    blocker.execute("UPDATE companies SET name = name WHERE id = 1")

    errors: list[BaseException] = []

    def _run_upgrade() -> None:
        try:
            upgrade_existing_schema(engine)
        except BaseException as exc:  # pragma: no cover - diagnostic capture
            errors.append(exc)

    worker = threading.Thread(target=_run_upgrade)
    worker.start()

    # Keep the writer lock long enough for at least one retry attempt.
    time.sleep(0.20)
    blocker.commit()
    blocker.close()

    worker.join(timeout=5)

    assert not worker.is_alive()
    assert errors == []

    with engine.connect() as connection:
        value = connection.execute(
            text(
                "SELECT theme_primary_color "
                "FROM companies WHERE id = 1"
            )
        ).scalar_one()

    assert value == "#4338E8"
