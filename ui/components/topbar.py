"""Reusable authenticated top bar and global notification center."""

from html import escape
from zoneinfo import ZoneInfo

import streamlit as st

from authentication.current_user import AuthenticatedUser
from config.settings import get_settings
from database.session import SessionFactory
from services.notification_service import NotificationService
from ui.navigation_state import set_navigation_state


_NOTIFICATION_CATEGORY_RULES: tuple[
    tuple[tuple[str, ...], str, str],
    ...,
] = (
    (
        (
            "event_planning_reminder",
            "event_reminder",
        ),
        "📅",
        "Planning Reminder",
    ),
    (
        (
            "announcement",
            "company_activity",
        ),
        "📣",
        "Announcement",
    ),
    (
        ("leave",),
        "🗓️",
        "Leave",
    ),
    (
        ("company_form", "form_submitted", "form_status"),
        "📝",
        "Company Form",
    ),
    (
        ("policy", "document"),
        "📘",
        "Policy",
    ),
    (
        ("training", "course"),
        "🎓",
        "Training",
    ),
    (
        ("employee", "account", "user"),
        "👤",
        "Employee",
    ),
    (
        ("password", "security", "login", "session"),
        "🔐",
        "Security",
    ),
    (
        ("integration", "email", "system"),
        "⚙️",
        "System",
    ),
)


def _format_time(value) -> str:
    """Format notification time using the configured display timezone."""

    if value is None:
        return ""

    if value.tzinfo is None:
        value = value.replace(
            tzinfo=ZoneInfo("UTC")
        )

    return value.astimezone(
        ZoneInfo(get_settings().display_timezone)
    ).strftime("%b %d, %Y · %I:%M %p")


def _notification_category(
    event_type: str,
) -> tuple[str, str]:
    """Map a generic event type to a readable category and icon."""

    normalized = (event_type or "").strip().casefold()

    for keywords, icon, label in _NOTIFICATION_CATEGORY_RULES:
        if any(
            keyword in normalized
            for keyword in keywords
        ):
            return icon, label

    return "🔔", "General"


def _notification_card(item) -> str:
    """Return one compact card without Markdown-indented HTML."""

    icon, category = _notification_category(
        item.event_type
    )
    state_class = (
        "hr-notification-card-unread"
        if not item.is_read
        else "hr-notification-card-read"
    )
    unread_dot = (
        '<span class="hr-notification-unread-dot" '
        'title="Unread notification"></span>'
        if not item.is_read
        else ""
    )

    # Keep this HTML unindented and contiguous. Markdown interprets lines
    # beginning with four spaces as code blocks, which previously exposed
    # raw </div> tags after Mark All as Read triggered a rerun.
    return (
        f'<div class="hr-notification-card {state_class}">'
        f'<div class="hr-notification-card-icon" '
        f'aria-hidden="true">{escape(icon)}</div>'
        f'<div class="hr-notification-card-content">'
        f'<div class="hr-notification-card-meta">'
        f'<span class="hr-notification-category">'
        f'{escape(category)}</span>{unread_dot}</div>'
        f'<div class="hr-notification-title">'
        f'{escape(item.title)}</div>'
        f'<div class="hr-notification-message">'
        f'{escape(item.message)}</div>'
        f'<div class="hr-notification-time">'
        f'{escape(_format_time(item.created_at))}</div>'
        f'</div></div>'
    )


def _notification_list_html(items) -> str:
    """Render all notification cards through one HTML block."""

    cards = "".join(
        _notification_card(item)
        for item in items
    )

    return (
        '<div class="hr-notification-list">'
        f'{cards}'
        '</div>'
    )


_NOTIFICATION_PANEL_KEY = "_global_notification_panel_open"
_NOTIFICATION_CONTEXT_QUERY_KEYS = (
    "announcement_id",
    "reminder_id",
    "leave_request_id",
    "leave_view",
    "policy_id",
    "company_form_id",
    "form_submission_id",
    "form_view",
    "employee_id",
)


def _notification_destination(
    item,
    *,
    portal_mode: str,
) -> tuple[str, str]:
    """Return the correct portal/page for one notification category."""

    entity = (
        item.related_entity_type
        or item.event_type
        or ""
    ).strip().casefold()

    if portal_mode == "admin":
        if "event_reminder" in entity or "planning_reminder" in entity:
            return "admin", "Announcements"
        if "announcement" in entity:
            return "admin", "Announcements"
        if "leave" in entity:
            return "admin", "Leave Management"
        if "company_form" in entity or "form_submission" in entity:
            return "admin", "Company Form/Documents"
        if any(
            value in entity
            for value in ("policy", "document")
        ):
            return "admin", "Policies"
        if any(
            value in entity
            for value in ("employee", "account", "user")
        ):
            return "admin", "Employees"
        if any(
            value in entity
            for value in ("integration", "email", "system")
        ):
            return "admin", "Audit Trail"
        if any(
            value in entity
            for value in ("security", "password", "login", "session")
        ):
            return "admin", "Company Profile"

        return "admin", "Admin Dashboard"

    if "announcement" in entity:
        return "employee", "Dashboard"
    if "leave" in entity:
        return "employee", "Leave Management"
    if "company_form" in entity or "form_submission" in entity:
        return "employee", "Company Form/Documents"
    if any(
        value in entity
        for value in ("policy", "document")
    ):
        return "employee", "Company Policies"
    if any(
        value in entity
        for value in ("training", "course", "onboarding", "benefit")
    ):
        return "employee", "Onboarding"

    return "employee", "Dashboard"


def _leave_notification_view(
    item,
    *,
    portal_mode: str,
) -> str:
    """Return the exact leave workspace required by one notification."""

    if portal_mode == "admin":
        return "requests"

    event_type = str(
        item.event_type or ""
    ).strip().casefold()
    title = str(
        item.title or ""
    ).strip().casefold()

    if (
        event_type in {
            "leave_request_submitted",
            "leave_cancellation_requested",
        }
        and "needs approval" in title
    ):
        return "pending"

    if (
        event_type
        in {
            "leave_request_approved",
            "leave_request_rejected",
        }
        and "decision recorded" in title
    ):
        return "reviewed"

    return "requests"


def _notification_entity_query_key(item) -> str | None:
    """Map a related entity to a refresh-safe URL context key."""

    entity = (
        item.related_entity_type
        or ""
    ).strip().casefold()

    if "event_reminder" in entity or "planning_reminder" in entity:
        return "reminder_id"
    if "announcement" in entity:
        return "announcement_id"
    if "leave_balance" in entity:
        return None
    if "leave" in entity:
        return "leave_request_id"
    if "company_form_submission" in entity or "form_submission" in entity:
        return "form_submission_id"
    if "company_form" in entity:
        return "company_form_id"
    if "policy" in entity or "document" in entity:
        return "policy_id"
    if any(
        value in entity
        for value in ("employee", "account", "user")
    ):
        return "employee_id"

    return None


def _open_notification(
    item,
    *,
    current_user: AuthenticatedUser,
) -> None:
    """Mark a notification read and navigate to its related module."""

    with SessionFactory() as session:
        NotificationService(session).mark_read(
            company_id=current_user.company_id,
            user_id=current_user.user_id,
            notification_id=item.id,
        )

    portal_mode = str(
        st.session_state.get(
            "portal_mode",
            "employee",
        )
    )
    target_portal, target_page = (
        _notification_destination(
            item,
            portal_mode=portal_mode,
        )
    )

    # Employee form submissions are administrator work items even when an
    # administrator happens to be browsing the Employee Portal.
    normalized_event_type = str(item.event_type or "").strip().casefold()
    if (
        normalized_event_type == "company_form_submitted"
        and current_user.clearance == 1
    ):
        target_portal = "admin"
        target_page = "Company Form/Documents"

    for query_key in _NOTIFICATION_CONTEXT_QUERY_KEYS:
        if query_key in st.query_params:
            del st.query_params[query_key]

    context_key = _notification_entity_query_key(item)

    entity = str(item.related_entity_type or "").strip().casefold()
    if "leave_balance" in entity:
        st.query_params["leave_view"] = "overview"
        if target_portal == "admin":
            st.session_state["admin_leave_management_active_tab"] = (
                "Employee Leave Accounts"
            )
        else:
            st.session_state["employee_leave_management_active_tab"] = (
                "My Leave Overview"
            )

    if (
        context_key is not None
        and item.related_entity_id is not None
    ):
        st.query_params[context_key] = str(
            item.related_entity_id
        )

        entity = str(
            item.related_entity_type or ""
        ).strip().casefold()

        if "leave" in entity:
            st.query_params["leave_view"] = (
                _leave_notification_view(
                    item,
                    portal_mode=target_portal,
                )
            )

        st.session_state[
            "notification_related_entity_type"
        ] = item.related_entity_type
        st.session_state[
            "notification_related_entity_id"
        ] = item.related_entity_id

    entity = str(item.related_entity_type or item.event_type or "").strip().casefold()
    if target_portal == "employee" and "announcement" in entity:
        st.session_state["employee_dashboard_active_tab"] = "Announcements"
    if "company_form" in entity or "form_submission" in entity:
        if target_portal == "admin":
            st.session_state["company_forms_next_tab"] = "Overview"
        else:
            employee_target = (
                "My Documents"
                if "form_submission" in entity
                else "View"
            )
            st.session_state[
                "employee_company_forms_next_tab"
            ] = employee_target
            st.session_state[
                "employee_company_forms_active_tab"
            ] = employee_target
            st.query_params["form_view"] = (
                "documents" if employee_target == "My Documents" else "view"
            )

    st.session_state[_NOTIFICATION_PANEL_KEY] = False
    set_navigation_state(
        portal_mode=target_portal,
        current_page=target_page,
    )
    st.rerun()


def _notification_button_label(item) -> str:
    """Build a readable multi-line label for one clickable card."""

    icon, category = _notification_category(
        item.event_type
    )

    return (
        f"{icon}  {category} · {item.title}\n"
        f"{item.message}\n"
        f"{_format_time(item.created_at)}"
    )


def _render_notification_dropdown(
    current_user: AuthenticatedUser,
) -> None:
    """Render the global notification panel directly below the bell."""

    with SessionFactory() as session:
        service = NotificationService(session)
        unread = service.unread_count(
            company_id=current_user.company_id,
            user_id=current_user.user_id,
        )
        recent = service.list_recent(
            company_id=current_user.company_id,
            user_id=current_user.user_id,
            limit=10,
        )

    with st.container(
        key="notification_dropdown_panel",
    ):
        header_html = (
            '<section class="hr-notification-panel">'
            '<header class="hr-notification-header">'
            '<div>'
            '<div class="hr-notification-heading">'
            'Notifications'
            '</div>'
            '<div class="hr-notification-subheading">'
            'System-wide alerts for your account'
            '</div>'
            '</div>'
            f'<span class="hr-notification-count">'
            f'{unread} unread'
            '</span>'
            '</header>'
            '</section>'
        )
        st.markdown(
            header_html,
            unsafe_allow_html=True,
        )

        notification_list_height = min(
            430,
            max(150, 44 + (len(recent) * 116)),
        )
        with st.container(
            key="notification_scroll_area",
            height=notification_list_height,
            border=False,
        ):
            if not recent:
                st.markdown(
                    (
                        '<div class="hr-notification-empty">'
                        '<div class="hr-notification-empty-icon">🔔</div>'
                        '<div class="hr-notification-empty-title">'
                        'No notifications yet'
                        '</div>'
                        '<div class="hr-notification-empty-message">'
                        'New HR, account, policy, training, leave, '
                        'announcement, and system updates will appear here.'
                        '</div>'
                        '</div>'
                    ),
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    '<div class="hr-notification-list-label">'
                    'Most recent'
                    '</div>',
                    unsafe_allow_html=True,
                )

                for item in recent:
                    state_label = (
                        "unread"
                        if not item.is_read
                        else "read"
                    )

                    with st.container(
                        key=(
                            f"notification_item_{state_label}_{item.id}"
                        ),
                    ):
                        if st.button(
                            _notification_button_label(item),
                            width="stretch",
                            key=f"open_notification_{item.id}",
                            help="Open the related HR module",
                        ):
                            _open_notification(
                                item,
                                current_user=current_user,
                            )

        with st.container(
            key="notification_action_footer",
        ):
            action_left, action_right = st.columns(2)

            with action_left:
                if unread and st.button(
                    "Mark All as Read",
                    width="stretch",
                    key="notification_dropdown_mark_all_read",
                ):
                    with SessionFactory() as session:
                        NotificationService(
                            session
                        ).mark_all_read(
                            company_id=current_user.company_id,
                            user_id=current_user.user_id,
                        )

                    st.session_state[
                        _NOTIFICATION_PANEL_KEY
                    ] = True
                    st.rerun()

            with action_right:
                if st.button(
                    "Close",
                    width="stretch",
                    key="notification_dropdown_close",
                ):
                    st.session_state[
                        _NOTIFICATION_PANEL_KEY
                    ] = False
                    st.rerun()


def _render_notification_bell(
    current_user: AuthenticatedUser,
) -> None:
    """Render a visible button and anchored dropdown notification panel."""

    with SessionFactory() as session:
        unread = NotificationService(
            session
        ).unread_count(
            company_id=current_user.company_id,
            user_id=current_user.user_id,
        )

    if _NOTIFICATION_PANEL_KEY not in st.session_state:
        st.session_state[
            _NOTIFICATION_PANEL_KEY
        ] = False

    with st.container(
        key="notification_menu_wrapper",
    ):
        # Company-colored primary button; count is visible before hover.
        label = f"🔔 {unread}"

        if st.button(
            label,
            type="primary",
            width="stretch",
            key="global_notification_button",
            help=(
                f"{unread} unread notification"
                f"{'' if unread == 1 else 's'}"
            ),
        ):
            st.session_state[
                _NOTIFICATION_PANEL_KEY
            ] = not st.session_state[
                _NOTIFICATION_PANEL_KEY
            ]

        if st.session_state[
            _NOTIFICATION_PANEL_KEY
        ]:
            _render_notification_dropdown(
                current_user
            )


def render_topbar(
    company_name: str,
    current_user: AuthenticatedUser,
    section_name: str = "Employee HR Services",
    display_name_override: str | None = None,
) -> None:
    """Display company, portal section, identity, and notifications."""

    display_name = (
        display_name_override
        or current_user.employee_name
        or current_user.username
    )
    access_label = (
        "Admin"
        if current_user.clearance == 1
        else "User"
    )

    content, bell = st.columns(
        [9.1, 0.9],
        vertical_alignment="center",
    )

    with content:
        st.markdown(
            f"""
            <div class="hr-topbar">
                <div>
                    <div class="hr-brand">
                        {escape(company_name)}
                    </div>
                    <div class="hr-muted">
                        {escape(section_name)}
                    </div>
                </div>
                <div class="hr-muted">
                    {escape(display_name)} · {access_label}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with bell:
        _render_notification_bell(current_user)
