"""Employee-facing company announcement archive."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import streamlit as st

from authentication.current_user import AuthenticatedUser
from config.settings import get_settings
from database.session import SessionFactory
from ui.components.responsive_image import (
    render_responsive_image,
)
from ui.components.announcement_description import (
    render_announcement_description,
)
from schemas.announcement_schema import (
    ANNOUNCEMENT_CATEGORIES,
)
from services.announcement_service import AnnouncementService
from services.notification_service import NotificationService
from ui.components.live_search import live_search_input


def _target_announcement_id() -> int | None:
    """Return a safe announcement ID opened from a notification."""

    raw_value = st.query_params.get("announcement_id")

    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return None

    return value if value > 0 else None


def _announcement_title(unread_count: int) -> None:
    """Render the standalone heading with an animated unread count."""

    active_class = (
        " announcement-unread-count--active"
        if unread_count > 0
        else ""
    )
    st.markdown(
        """
        <style>
        @keyframes announcementUnreadShake {
            0%, 100% { transform: translateX(0) scale(1); }
            20% { transform: translateX(-2px) scale(1.04); }
            40% { transform: translateX(2px) scale(1.04); }
            60% { transform: translateX(-1px) scale(1.04); }
            80% { transform: translateX(1px) scale(1.04); }
        }
        .announcement-page-title {
            display: flex;
            align-items: center;
            gap: .45rem;
            margin: 0 0 .3rem 0;
            color: var(--hr-text-primary);
            font-size: 2.5rem;
            font-weight: 760;
            line-height: 1.2;
        }
        .announcement-unread-count {
            display: inline-block;
            color: var(--hr-primary-text);
            font-size: .72em;
        }
        .announcement-unread-count--active {
            animation: announcementUnreadShake .7s ease-in-out 3;
            transform-origin: center;
        }
        @media (prefers-reduced-motion: reduce) {
            .announcement-unread-count--active { animation: none; }
        }
        </style>
        """
        f'<h1 class="announcement-page-title">Company Announcements '
        f'<span class="announcement-unread-count{active_class}">'
        f'({unread_count})</span></h1>',
        unsafe_allow_html=True,
    )


def _display_date(value) -> str:
    """Format publication time for employee cards."""

    if value is None:
        return "Published recently"

    if value.tzinfo is None:
        value = value.replace(
            tzinfo=timezone.utc
        )

    return value.astimezone(
        ZoneInfo(get_settings().display_timezone)
    ).strftime("%b %d, %Y")


def _load_announcements(
    current_user: AuthenticatedUser,
    *,
    limit: int | None = None,
):
    """Load visible announcements and private images."""

    with SessionFactory() as session:
        service = AnnouncementService(session)
        service.reconcile_publications(
            company_id=current_user.company_id
        )
        announcements = service.list_visible(
            company_id=current_user.company_id,
            limit=limit,
        )
        images: dict[int, bytes] = {}

        for announcement in announcements:
            if not announcement.image_storage_path:
                continue

            try:
                images[announcement.id] = (
                    service.read_image(announcement)
                )
            except FileNotFoundError:
                continue

    return announcements, images


def load_employee_announcement_state(
    current_user: AuthenticatedUser,
):
    """Load visible announcements, images, and this user's unread count."""

    announcements, images = _load_announcements(current_user)
    announcement_ids = [item.id for item in announcements]
    with SessionFactory() as session:
        unread_count = NotificationService(
            session
        ).unread_announcement_count(
            company_id=current_user.company_id,
            user_id=current_user.user_id,
            announcement_ids=announcement_ids,
        )

    return announcements, images, unread_count


def render_announcement_card(
    announcement,
    *,
    image_bytes: bytes | None,
) -> None:
    """Render one responsive announcement card."""

    with st.container(border=True):
        st.caption(
            f"{announcement.category} · "
            f"{_display_date(announcement.publish_at)}"
        )

        if image_bytes:
            image_column, content_column = st.columns(
                [1.05, 1.35],
                gap="large",
                vertical_alignment="top",
            )
        else:
            image_column = None
            content_column = st.container()

        with content_column:
            st.markdown(f"### {announcement.title}")
            st.write(announcement.summary)

            if announcement.is_pinned:
                st.info("Pinned company update")

            with st.container(
                border=False,
                height=330,
            ):
                render_announcement_description(
                    announcement.content
                )

        if image_column is not None:
            with image_column:
                render_responsive_image(
                    image_bytes,
                    max_width=1200,
                    max_height=780,
                    fill_container=True,
                )


def render_employee_announcements_page(
    current_user: AuthenticatedUser,
    *,
    announcement_state=None,
    show_heading: bool = True,
) -> None:
    """Render searchable active company announcements."""

    if announcement_state is None:
        announcement_state = load_employee_announcement_state(current_user)

    announcements, images, unread_count = announcement_state
    announcement_ids = [item.id for item in announcements]

    if show_heading:
        _announcement_title(unread_count)
        st.caption(
            "Official company information, activities, events, "
            "reminders, and HR updates."
        )

    if not announcements:
        st.info(
            "There is no active company announcement at this time."
        )
        return

    target_id = _target_announcement_id()
    target = next(
        (item for item in announcements if item.id == target_id),
        None,
    )
    if target is not None:
        announcements = [
            target,
            *(item for item in announcements if item.id != target.id),
        ]
        st.info("Opened from Notifications")

    filter_left, filter_right = st.columns(2)

    with filter_left:
        selected_category = st.selectbox(
            "Category",
            options=[
                "All Categories",
                *ANNOUNCEMENT_CATEGORIES,
            ],
        )

    with filter_right:
        search_text = live_search_input(
            "Search Announcements",
            placeholder="Search title, summary, or content...",
            key="employee_announcement_search",
            suggestions=(
                value
                for announcement in announcements
                for value in (
                    announcement.title,
                    announcement.category,
                )
            ),
        )

    normalized_search = search_text.strip().casefold()
    filtered = []

    for announcement in announcements:
        if (
            selected_category != "All Categories"
            and announcement.category
            != selected_category
        ):
            continue

        searchable = (
            f"{announcement.title} "
            f"{announcement.public_id or ''} "
            f"{announcement.category} "
            f"{announcement.summary} "
            f"{announcement.content} "
            f"{announcement.publish_at or announcement.published_at or ''} "
            f"{announcement.expires_at or ''} "
            f"{'Pinned' if announcement.is_pinned else 'Not Pinned'}"
        ).casefold()

        if (
            normalized_search
            and normalized_search not in searchable
        ):
            continue

        filtered.append(announcement)

    st.caption(
        f"{len(filtered)} of {len(announcements)} announcement(s) shown."
    )

    if not filtered:
        st.info(
            "No announcement matches the selected filters."
        )
        return

    for announcement in filtered:
        render_announcement_card(
            announcement,
            image_bytes=images.get(
                announcement.id
            ),
        )

    # Keep the count visible for this completed render. It becomes zero on
    # the next interaction while unread state remains independent per user.
    if unread_count > 0:
        with SessionFactory() as session:
            NotificationService(session).mark_announcements_read(
                company_id=current_user.company_id,
                user_id=current_user.user_id,
                announcement_ids=announcement_ids,
            )
