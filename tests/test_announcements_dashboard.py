"""Announcement publishing, visibility, and dashboard tests."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models  # noqa: F401
from config.settings import Settings
from database.base import Base
from models.user import User
from schemas.announcement_schema import AnnouncementInput
from scripts.create_initial_data import seed_initial_data
from services.announcement_service import AnnouncementService
from services.notification_service import NotificationService


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        database_url="sqlite+pysqlite:///:memory:",
        initial_company_code="ANNOUNCE",
        initial_company_name="Announcement Company",
        initial_admin_username="admin",
        initial_admin_email="admin@announce.example",
        initial_admin_password=SecretStr("Temporary123!"),
        initial_admin_employee_number="ADMIN-001",
        initial_admin_first_name="System",
        initial_admin_last_name="Administrator",
        announcement_upload_dir=str(
            tmp_path / "announcement_images"
        ),
    )


def _factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:"
    )
    Base.metadata.create_all(engine)

    return sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )


def _employee_user(session, seed) -> User:
    user = User(
        company_id=seed["company"].id,
        role_id=seed["admin_user"].role_id,
        clearance=2,
        username="employee",
        email="employee@announce.example",
        password_hash=seed["admin_user"].password_hash,
        is_active=True,
        must_change_password=False,
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    return user


def _values(
    company_id: int,
    *,
    publish_at: datetime,
    expires_at: datetime | None = None,
    title: str = "Quarterly Company Update",
) -> AnnouncementInput:
    return AnnouncementInput(
        company_id=company_id,
        title=title,
        category="Company Announcement",
        summary="Important company information for all employees.",
        content=(
            "This is the complete company announcement with "
            "the details employees need to know."
        ),
        is_pinned=True,
        publish_at=publish_at,
        expires_at=expires_at,
    )


def test_immediate_publication_is_visible_and_notifies_users(
    tmp_path: Path,
) -> None:
    factory = _factory()
    now = datetime.now(timezone.utc)

    with factory() as session:
        settings = _settings(tmp_path)
        seed = seed_initial_data(session, settings)
        employee_user = _employee_user(session, seed)
        service = AnnouncementService(
            session,
            settings=settings,
        )

        announcement = service.create(
            _values(
                seed["company"].id,
                publish_at=now,
            ),
            actor_user_id=seed["admin_user"].id,
            publish=True,
        )

        visible = service.list_visible(
            company_id=seed["company"].id,
            at=now + timedelta(seconds=1),
        )
        recent = NotificationService(
            session
        ).list_recent(
            company_id=seed["company"].id,
            user_id=employee_user.id,
        )

        assert announcement.public_id.startswith("ANN_")
        assert announcement.status == "published"
        assert [item.id for item in visible] == [
            announcement.id
        ]
        assert len(recent) == 1
        assert recent[0].event_type == (
            "announcement_published"
        )
        assert recent[0].title == announcement.title


def test_draft_is_not_visible_and_sends_no_notification(
    tmp_path: Path,
) -> None:
    factory = _factory()
    now = datetime.now(timezone.utc)

    with factory() as session:
        settings = _settings(tmp_path)
        seed = seed_initial_data(session, settings)
        employee_user = _employee_user(session, seed)
        service = AnnouncementService(
            session,
            settings=settings,
        )

        announcement = service.create(
            _values(
                seed["company"].id,
                publish_at=now,
            ),
            actor_user_id=seed["admin_user"].id,
            publish=False,
        )

        assert announcement.status == "draft"
        assert service.list_visible(
            company_id=seed["company"].id,
            at=now,
        ) == []
        assert NotificationService(
            session
        ).list_recent(
            company_id=seed["company"].id,
            user_id=employee_user.id,
        ) == []


def test_scheduled_post_notifies_only_when_due(
    tmp_path: Path,
) -> None:
    factory = _factory()
    now = datetime.now(timezone.utc)
    future = now + timedelta(days=2)

    with factory() as session:
        settings = _settings(tmp_path)
        seed = seed_initial_data(session, settings)
        employee_user = _employee_user(session, seed)
        service = AnnouncementService(
            session,
            settings=settings,
        )

        announcement = service.create(
            _values(
                seed["company"].id,
                publish_at=future,
            ),
            actor_user_id=seed["admin_user"].id,
            publish=True,
        )

        assert AnnouncementService.display_status(
            announcement,
            at=now,
        ) == "Scheduled"
        assert service.reconcile_publications(
            company_id=seed["company"].id,
            at=now,
        ) == 0
        assert service.reconcile_publications(
            company_id=seed["company"].id,
            at=future + timedelta(seconds=1),
        ) == 1
        assert NotificationService(
            session
        ).unread_count(
            company_id=seed["company"].id,
            user_id=employee_user.id,
        ) == 1


def test_expired_post_is_hidden(
    tmp_path: Path,
) -> None:
    factory = _factory()
    now = datetime.now(timezone.utc)

    with factory() as session:
        settings = _settings(tmp_path)
        seed = seed_initial_data(session, settings)
        service = AnnouncementService(
            session,
            settings=settings,
        )

        service.create(
            _values(
                seed["company"].id,
                publish_at=now - timedelta(days=3),
                expires_at=now - timedelta(days=1),
                title="Expired Announcement",
            ),
            actor_user_id=seed["admin_user"].id,
            publish=True,
        )

        assert service.list_visible(
            company_id=seed["company"].id,
            at=now,
        ) == []


def test_valid_png_image_is_stored_and_read(
    tmp_path: Path,
) -> None:
    factory = _factory()
    now = datetime.now(timezone.utc)
    png_bytes = (
        b"\x89PNG\r\n\x1a\n"
        b"test-image-payload"
    )

    with factory() as session:
        settings = _settings(tmp_path)
        seed = seed_initial_data(session, settings)
        service = AnnouncementService(
            session,
            settings=settings,
        )

        announcement = service.create(
            _values(
                seed["company"].id,
                publish_at=now,
            ),
            actor_user_id=seed["admin_user"].id,
            publish=False,
            image_filename="activity.png",
            image_bytes=png_bytes,
            image_mime_type="image/png",
        )

        assert announcement.image_storage_path
        assert service.read_image(
            announcement
        ) == png_bytes


def test_admin_and_employee_routes_include_announcements() -> None:
    admin_layout = (
        PROJECT_ROOT
        / "ui/layouts/admin_layout.py"
    ).read_text(encoding="utf-8")
    user_layout = (
        PROJECT_ROOT
        / "ui/layouts/user_layout.py"
    ).read_text(encoding="utf-8")
    employee_dashboard = (
        PROJECT_ROOT
        / "ui/pages/user/dashboard_page.py"
    ).read_text(encoding="utf-8")

    assert (
        'page == "Announcements"'
        in admin_layout
    )
    assert "render_admin_announcements_page" in admin_layout
    assert '"Dashboard"' in user_layout
    assert '"Announcements"' in user_layout
    assert '"Company Announcements"' in user_layout
    assert "render_employee_dashboard_page" in user_layout
    assert "render_employee_announcements_page" in employee_dashboard


def test_employee_dashboard_is_default_and_first_navigation_item() -> None:
    constants = (
        PROJECT_ROOT
        / "core/constants.py"
    ).read_text(encoding="utf-8")
    login = (
        PROJECT_ROOT
        / "ui/pages/authentication/login_page.py"
    ).read_text(encoding="utf-8")

    assert 'DEFAULT_PAGE = "Dashboard"' in constants
    navigation = constants.split(
        "USER_NAVIGATION = (",
        1,
    )[1]
    assert (
        navigation.index('"Dashboard"')
        < navigation.index('"Chat Assistant"')
    )
    assert (
        'st.session_state.current_page = "Dashboard"'
        in login
    )


def test_announcements_have_a_separate_employee_workspace() -> None:
    source = (
        PROJECT_ROOT / "ui/pages/user/announcements_page.py"
    ).read_text(encoding="utf-8")

    assert "Company Announcements" in source
    assert "Search Announcements" in source
    assert "render_announcement_card" in source


def test_admin_form_supports_image_and_publication_controls() -> None:
    source = (
        PROJECT_ROOT
        / "ui/pages/admin/announcements_page.py"
    ).read_text(encoding="utf-8")

    assert '"Cover Image (Optional)"' in source
    assert '"Save as Draft"' in source
    assert '"Publish / Schedule"' in source
    assert '"Pin on Employee Dashboard"' in source
    assert '"Set Expiry Date"' in source
    assert '"Company Activity"' in (
        PROJECT_ROOT
        / "schemas/announcement_schema.py"
    ).read_text(encoding="utf-8")


def test_notification_center_recognizes_announcement_category() -> None:
    source = (
        PROJECT_ROOT
        / "ui/components/topbar.py"
    ).read_text(encoding="utf-8")

    assert '"announcement"' in source
    assert '"Announcement"' in source
    assert '"📣"' in source



def test_soft_delete_moves_announcement_to_archive(
    tmp_path: Path,
) -> None:
    factory = _factory()
    now = datetime.now(timezone.utc)

    with factory() as session:
        settings = _settings(tmp_path)
        seed = seed_initial_data(session, settings)
        service = AnnouncementService(
            session,
            settings=settings,
        )

        announcement = service.create(
            _values(
                seed["company"].id,
                publish_at=now,
                title="Temporary Announcement",
            ),
            actor_user_id=seed["admin_user"].id,
            publish=True,
        )

        archived = service.move_to_archive(
            company_id=seed["company"].id,
            announcement_id=announcement.id,
            actor_user_id=seed["admin_user"].id,
        )

        assert archived.status == "archived"
        assert archived.archived_at is not None
        assert service.list_visible(
            company_id=seed["company"].id,
            at=now + timedelta(seconds=1),
        ) == []
        assert any(
            item.id == announcement.id
            for item in service.list_for_admin(
                seed["company"].id
            )
        )

        restored = service.restore_archived(
            company_id=seed["company"].id,
            announcement_id=announcement.id,
            actor_user_id=seed["admin_user"].id,
        )

        assert restored.status == "draft"
        assert restored.archived_at is None


def test_admin_delete_is_archive_only() -> None:
    source = (
        PROJECT_ROOT
        / "ui/pages/admin/announcements_page.py"
    ).read_text(encoding="utf-8")

    assert '"Delete Announcement"' in source
    assert "move_to_archive(" in source
    assert "permanently deleted" in source
    assert '"Restore to Draft"' in source
    assert 'f"Archive ({len(archived_announcements)})"' in source


def test_employee_announcements_are_a_dashboard_subtab() -> None:
    constants = (
        PROJECT_ROOT
        / "core/constants.py"
    ).read_text(encoding="utf-8")
    dashboard = (
        PROJECT_ROOT
        / "ui/pages/user/dashboard_page.py"
    ).read_text(encoding="utf-8")

    navigation = constants.split(
        "USER_NAVIGATION = (",
        1,
    )[1].split(
        ")",
        1,
    )[0]

    assert '"Dashboard"' in navigation
    assert '"Company Announcements"' not in navigation
    assert '"Announcements"' not in navigation
    assert "st.tabs(" in dashboard
    assert 'on_change="rerun"' in dashboard
    assert 'content: " ({unread_count})"' in dashboard
    assert "announcement_area, quick_access_area" not in dashboard
    assert "dashboard_announcement_category" not in dashboard
    assert "dashboard_announcement_search" not in dashboard
    assert "render_announcement_card" not in dashboard
