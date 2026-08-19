"""v8.7.7 clickable notification and title-first layout tests."""

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models  # noqa: F401
from database.base import Base
from models.notification import Notification
from repositories.notification_repository import NotificationRepository


ROOT = Path(__file__).resolve().parents[1]


def test_notification_repository_marks_one_item_read() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:"
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )

    with factory() as session:
        notification = Notification(
            company_id=1,
            user_id=2,
            event_type="announcement_published",
            title="Company Update",
            message="Read the announcement.",
            related_entity_type="announcement",
            related_entity_id=8,
            is_read=False,
        )
        session.add(notification)
        session.commit()

        changed = NotificationRepository(
            session
        ).mark_read(
            company_id=1,
            user_id=2,
            notification_id=notification.id,
        )
        session.refresh(notification)

        assert changed == 1
        assert notification.is_read is True
        assert notification.read_at is not None


def test_notification_items_are_clickable_and_routed() -> None:
    source = (
        ROOT / "ui/components/topbar.py"
    ).read_text(encoding="utf-8")

    assert "def _notification_destination(" in source
    assert "def _open_notification(" in source
    assert "set_navigation_state(" in source
    assert 'key=f"open_notification_{item.id}"' in source
    assert "mark_read(" in source
    assert '"Announcements"' in source
    assert '"Leave Management"' in source
    assert '"Company Policies"' in source
    assert '"Employees"' in source
    assert '"Audit Trail"' in source


def test_notification_panel_is_wide_and_positioned_below_bell() -> None:
    source = (
        ROOT / "ui/theme/theme_loader.py"
    ).read_text(encoding="utf-8")

    block = source.split(
        "WIDE CLICKABLE NOTIFICATIONS — v8.7.7",
        1,
    )[1]

    assert "width: min(460px" in block
    assert "position: fixed !important;" in block
    assert "const positionNotificationDropdown = () =>" in source
    assert "buttonRect.bottom + 8" in source
    assert "buttonRect.right - panelWidth" in source


def test_notification_card_text_wraps_normally() -> None:
    source = (
        ROOT / "ui/theme/theme_loader.py"
    ).read_text(encoding="utf-8")

    block = source.split(
        "WIDE CLICKABLE NOTIFICATIONS — v8.7.7",
        1,
    )[1]

    assert "white-space: pre-wrap !important;" in block
    assert "overflow-wrap: anywhere !important;" in block
    assert "word-break: normal !important;" in block
    assert "text-align: left !important;" in block


def test_employee_announcement_title_precedes_image() -> None:
    source = (
        ROOT / "ui/pages/user/announcements_page.py"
    ).read_text(encoding="utf-8")
    card = source.split(
        "def render_announcement_card(",
        1,
    )[1].split(
        "def render_employee_announcements_page(",
        1,
    )[0]

    assert card.index('st.markdown(f"### {announcement.title}")') < card.index(
        "render_responsive_image("
    )


def test_admin_announcement_title_precedes_image() -> None:
    source = (
        ROOT / "ui/pages/admin/announcements_page.py"
    ).read_text(encoding="utf-8")
    preview = source.split(
        "def _render_preview(",
        1,
    )[1].split(
        "def _render_overview(",
        1,
    )[0]

    assert preview.index('st.markdown(f"### {announcement.title}")') < preview.index(
        "render_responsive_image("
    )


def test_announcement_workspace_prioritizes_notification_target() -> None:
    source = (
        ROOT / "ui/pages/user/announcements_page.py"
    ).read_text(encoding="utf-8")

    assert "def _target_announcement_id(" in source
    assert 'st.query_params.get("announcement_id")' in source
    assert '"Opened from Notifications"' in source
