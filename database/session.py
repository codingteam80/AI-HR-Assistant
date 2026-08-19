"""Database engine and SQLAlchemy session factory.

Purpose:
- Build the SQLAlchemy engine from DATABASE_URL.
- Apply database-specific connection options.
- Provide reusable sessions to repositories and services.
"""

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from config.settings import get_settings


def _build_connect_args(database_url: str) -> dict[str, object]:
    """Return connection arguments required by the selected database."""

    # SQLite normally restricts a connection to one thread.
    # Streamlit can use multiple execution contexts, so this is disabled.
    if database_url.startswith("sqlite"):
        return {
            "check_same_thread": False,
            # Give concurrent Streamlit requests time to finish their write
            # transaction instead of failing immediately with
            # ``sqlite3.OperationalError: database is locked``.
            "timeout": 30.0,
        }

    # PostgreSQL and other engines do not need the SQLite option.
    return {}


def create_database_engine(database_url: str | None = None) -> Engine:
    """Create an SQLAlchemy engine.

    A custom URL is useful in tests. When omitted, the value from `.env`
    is used.
    """

    settings = get_settings()
    selected_url = database_url or settings.database_url

    database_engine = create_engine(
        selected_url,
        connect_args=_build_connect_args(selected_url),
        pool_pre_ping=True,  # Check stale pooled connections before use.
        future=True,
    )

    if selected_url.startswith("sqlite"):
        @event.listens_for(database_engine, "connect")
        def _configure_sqlite_connection(
            dbapi_connection,
            _connection_record,
        ) -> None:
            # SQLite accepts only one writer at a time. ``busy_timeout`` makes
            # each connection wait for a short-lived writer to finish.
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA busy_timeout = 30000")
                cursor.execute("PRAGMA foreign_keys = ON")
            finally:
                cursor.close()

    return database_engine


# Shared application engine.
engine = create_database_engine()

# SessionFactory creates independent Session objects for each operation.
SessionFactory = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    class_=Session,
)

# The listener writes audit rows inside the same successful transaction, so a
# rollback never leaves a false "successful" event behind.
from database.audit_listener import install_audit_listener

install_audit_listener()


def get_session() -> Generator[Session, None, None]:
    """Yield a session and always close it afterward.

    This helper can later be used by APIs, services, or dependency systems.
    """

    session = SessionFactory()

    try:
        yield session
    finally:
        session.close()
