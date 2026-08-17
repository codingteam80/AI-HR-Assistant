"""Administrator announcement publishing and independent reminder planning."""

from datetime import date, datetime, time, timezone
from html import escape
from zoneinfo import ZoneInfo

from pydantic import ValidationError
import streamlit as st
from ui.components.validation_feedback import render_action_warning

from authentication.current_user import AuthenticatedUser
from config.settings import get_settings
from database.session import SessionFactory
from schemas.announcement_schema import (
    ANNOUNCEMENT_CATEGORIES,
    AnnouncementInput,
)
from schemas.event_reminder_schema import (
    EVENT_REMINDER_CATEGORIES,
    EventReminderInput,
    automatic_reminder_schedule,
    parse_smart_reminder_entries,
    parse_smart_reminder_entry,
)
from services.announcement_service import AnnouncementService
from services.event_reminder_service import EventReminderService
from ui.components.data_table import render_admin_table
from ui.components.operation_feedback import (
    render_operation_feedback,
    set_operation_feedback,
)
from ui.components.responsive_image import render_responsive_image
from ui.components.announcement_description import (
    render_announcement_description,
)


REMINDER_STATUS_LABELS = {
    "planned": "Planned",
    "announcement_ready": "Announcement Ready",
    "completed": "Completed",
    "cancelled": "Cancelled",
}

# One-shot tab targets preserve the user's current workspace after a
# successful action triggers ``st.rerun()``.
ANNOUNCEMENTS_NEXT_TAB_KEY = "announcements_next_tab"
REMINDERS_NEXT_TAB_KEY = "reminders_next_tab"
CREATE_REMINDER_FORM_REVISION_KEY = "create_reminder_form_revision"


def _consume_tab_target(state_key: str, labels: list[str]) -> str | None:
    """Return and clear one valid tab target stored for the next rerun."""

    target = st.session_state.pop(state_key, None)
    return target if target in labels else None


def _remember_reminder_tab(tab_label: str) -> None:
    """Keep the Announcements and reminder sub-tabs active after rerun."""

    st.session_state[ANNOUNCEMENTS_NEXT_TAB_KEY] = "Reminders"
    st.session_state[REMINDERS_NEXT_TAB_KEY] = tab_label


def _display_zone() -> ZoneInfo:
    """Return the company display timezone."""

    return ZoneInfo(get_settings().display_timezone)


def _local_today() -> date:
    """Return today's date in the configured display timezone."""

    return datetime.now(_display_zone()).date()


def _local_datetime(
    selected_date: date,
    *,
    selected_time: time | None = None,
    end_of_day: bool = False,
) -> datetime:
    """Convert a local calendar date/time into an aware UTC timestamp."""

    local_time = selected_time or (
        time(23, 59, 59) if end_of_day else time(0, 0, 0)
    )
    local_value = datetime.combine(
        selected_date,
        local_time,
        tzinfo=_display_zone(),
    )

    return local_value.astimezone(timezone.utc)


def _local_date(
    value: datetime | None,
    *,
    fallback: date,
) -> date:
    """Convert a stored UTC timestamp into a local calendar date."""

    if value is None:
        return fallback

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    return value.astimezone(_display_zone()).date()


def _local_time(
    value: datetime | None,
    *,
    fallback: time,
) -> time:
    """Convert a stored UTC timestamp into a local clock time."""

    if value is None:
        return fallback

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    local_value = value.astimezone(_display_zone())

    return time(
        local_value.hour,
        local_value.minute,
    )


def _display_datetime(value: datetime | None) -> str:
    """Format an announcement, event, or reminder timestamp."""

    if value is None:
        return "—"

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    return value.astimezone(_display_zone()).strftime(
        "%Y-%m-%d %I:%M %p"
    )


def _planning_schedule_text(reminder) -> str:
    """Return the event date used by the smart entry."""

    return _local_date(
        reminder.event_start_at,
        fallback=_local_today(),
    ).strftime("%Y/%m/%d")


def _smart_entry_text(reminder) -> str:
    """Rebuild the one-box smart entry for editing and preview."""

    first_line = f"{_planning_schedule_text(reminder)} - {reminder.title}"
    return f"{first_line}\n{reminder.notes}".rstrip()


def _planning_reminder_status(reminder) -> str:
    """Return all three automatic notification statuses."""

    lines: list[str] = []
    sent_fields = (
        "reminder_one_month_sent_at",
        "reminder_two_weeks_sent_at",
        "reminder_one_week_sent_at",
    )
    now = datetime.now(timezone.utc)
    for (label, scheduled_at), sent_field in zip(
        automatic_reminder_schedule(reminder.event_start_at),
        sent_fields,
    ):
        sent_at = getattr(reminder, sent_field, None)
        scheduled_value = scheduled_at
        if scheduled_value.tzinfo is None:
            scheduled_value = scheduled_value.replace(tzinfo=timezone.utc)
        if sent_at is not None:
            lines.append(f"{label}: Sent {_display_datetime(sent_at)}")
        elif scheduled_value < now:
            lines.append(f"{label}: Missed ({_display_datetime(scheduled_at)})")
        else:
            lines.append(f"{label}: {_display_datetime(scheduled_at)}")
    return "\n".join(lines)


def _render_reminder_preview_box(reminder, *, key: str) -> None:
    """Render one fixed-height preview with an always-visible scrollbar."""

    safe_key = "".join(
        character if character.isalnum() else "-"
        for character in key
    )
    notes_html = escape(reminder.notes or "No preparation notes.").replace(
        "\n",
        "<br>",
    )
    notification_html = "<br>".join(
        escape(line)
        for line in _planning_reminder_status(reminder).splitlines()
    )
    html = f"""
    <style>
        .reminder-preview-{safe_key} {{
            max-height: 310px;
            overflow-y: scroll;
            scrollbar-gutter: stable;
            scrollbar-width: auto;
            scrollbar-color: var(--hr-primary) #E5EAF2;
            padding: 18px;
            border: 1px solid var(--hr-border);
            border-radius: 14px;
            background: var(--hr-surface);
            color: var(--hr-text-secondary);
            line-height: 1.55;
        }}
        .reminder-preview-{safe_key}::-webkit-scrollbar {{
            width: 12px;
        }}
        .reminder-preview-{safe_key}::-webkit-scrollbar-track {{
            background: #E5EAF2;
            border-radius: 999px;
        }}
        .reminder-preview-{safe_key}::-webkit-scrollbar-thumb {{
            min-height: 44px;
            background: var(--hr-primary);
            border: 2px solid #E5EAF2;
            border-radius: 999px;
        }}
        .reminder-preview-{safe_key} h4 {{
            margin: 0 0 8px 0;
            color: var(--hr-text-primary);
        }}
        .reminder-preview-{safe_key} .meta {{
            margin-bottom: 14px;
            color: var(--hr-text-muted);
            font-size: 0.9rem;
        }}
        .reminder-preview-{safe_key} .section-title {{
            margin-top: 16px;
            color: var(--hr-text-primary);
            font-weight: 700;
        }}
    </style>
    <div class="reminder-preview-{safe_key}">
        <h4>{escape(reminder.title)}</h4>
        <div class="meta">
            {escape(reminder.public_id or "Reminder")} ·
            {escape(reminder.category)} ·
            {escape(_planning_schedule_text(reminder))} ·
            {escape(REMINDER_STATUS_LABELS.get(reminder.status, reminder.status))}
        </div>
        <div class="section-title">Preparation Notes</div>
        <div>{notes_html}</div>
        <div class="section-title">Automatic Admin Notifications</div>
        <div>{notification_html}</div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


def _target_reminder_id() -> int | None:
    """Return a safe reminder ID opened from the notification bell."""

    raw_value = st.query_params.get("reminder_id")

    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return None

    return value if value > 0 else None


def _target_announcement_id() -> int | None:
    """Return a safe announcement ID opened from the notification bell."""

    raw_value = st.query_params.get("announcement_id")

    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return None

    return value if value > 0 else None


def _announcement_input(
    *,
    current_user: AuthenticatedUser,
    title: str,
    category: str,
    summary: str,
    content: str,
    is_pinned: bool,
    publish_date: date,
    expiry_enabled: bool,
    expiry_date: date,
) -> AnnouncementInput:
    """Build validated announcement values from the form."""

    return AnnouncementInput(
        company_id=current_user.company_id,
        title=title,
        category=category,
        summary=summary,
        content=content,
        is_pinned=is_pinned,
        publish_at=_local_datetime(publish_date),
        expires_at=(
            _local_datetime(
                expiry_date,
                end_of_day=True,
            )
            if expiry_enabled
            else None
        ),
    )


def _reminder_input(
    *,
    current_user: AuthenticatedUser,
    category: str,
    entry_text: str,
    status: str = "planned",
    announcement_id: int | None = None,
) -> EventReminderInput:
    """Parse one smart entry box into validated reminder values."""

    parsed = parse_smart_reminder_entry(entry_text)
    return EventReminderInput(
        company_id=current_user.company_id,
        title=parsed.title,
        category=category,
        notes=parsed.notes,
        event_start_at=_local_datetime(
            parsed.event_date,
            selected_time=time(9, 0),
        ),
        event_end_at=None,
        status=status,
        announcement_id=announcement_id,
    )


def _reminder_inputs(
    *,
    current_user: AuthenticatedUser,
    category: str,
    entry_text: str,
) -> list[EventReminderInput]:
    """Parse and validate every reminder block before batch persistence."""

    parsed_entries = parse_smart_reminder_entries(entry_text)
    return [
        EventReminderInput(
            company_id=current_user.company_id,
            title=parsed.title,
            category=category,
            notes=parsed.notes,
            event_start_at=_local_datetime(
                parsed.event_date,
                selected_time=time(9, 0),
            ),
            event_end_at=None,
            status="planned",
            announcement_id=None,
        )
        for parsed in parsed_entries
    ]


def _read_image_map(
    current_user: AuthenticatedUser,
    announcements,
) -> dict[int, bytes]:
    """Load available images while handling missing local files safely."""

    images: dict[int, bytes] = {}

    with SessionFactory() as session:
        service = AnnouncementService(session)

        for announcement in announcements:
            if not announcement.image_storage_path:
                continue

            try:
                images[announcement.id] = service.read_image(
                    announcement
                )
            except FileNotFoundError:
                continue

    return images


def _render_preview(
    announcement,
    *,
    image_bytes: bytes | None,
) -> None:
    """Render one complete admin preview using the employee layout."""

    with st.container(border=True):
        st.caption(
            f"{announcement.category} · "
            f"{AnnouncementService.display_status(announcement)} · "
            f"{_display_datetime(announcement.publish_at)}"
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
                st.info(
                    "Pinned announcement — this receives priority "
                    "on the employee dashboard."
                )

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
                    caption=(
                        announcement.image_original_filename
                        or "Announcement cover image"
                    ),
                    max_width=1200,
                    max_height=780,
                    fill_container=True,
                )


def _selected_index(items, target_id: int | None) -> int:
    """Return a safe selectbox index for a notification target."""

    if target_id is None:
        return 0

    for index, item in enumerate(items):
        if item.id == target_id:
            return index

    return 0


def _render_overview(
    current_user: AuthenticatedUser,
    announcements,
) -> None:
    """Render lifecycle metrics, scrollable table, and preview."""

    statuses = [
        AnnouncementService.display_status(item)
        for item in announcements
    ]
    metrics = (
        ("Total", len(announcements)),
        ("Published", statuses.count("Published")),
        ("Scheduled", statuses.count("Scheduled")),
        ("Drafts", statuses.count("Draft")),
    )

    for column, (label, value) in zip(st.columns(4), metrics):
        with column:
            st.metric(label, value)

    if not announcements:
        st.info("No company announcement has been created yet.")
        return

    render_admin_table(
        [
            {
                "Announcement ID": item.public_id,
                "Title": item.title,
                "Category": item.category,
                "Status": AnnouncementService.display_status(item),
                "Pinned": "Yes" if item.is_pinned else "No",
                "Publish Date": _display_datetime(item.publish_at),
                "Expiry": _display_datetime(item.expires_at),
            }
            for item in announcements
        ],
        key="admin-announcement-overview",
        min_width=1250,
        column_widths=(
            "140px",
            "300px",
            "180px",
            "130px",
            "90px",
            "190px",
            "190px",
        ),
        max_height=430,
    )

    options = {
        item.id: f"{item.public_id} · {item.title}"
        for item in announcements
    }
    target_id = _target_announcement_id()
    selected_id = st.selectbox(
        "Preview Announcement",
        options=list(options),
        index=_selected_index(announcements, target_id),
        format_func=lambda value: options[value],
        key="announcement_preview_selector",
    )
    selected = next(
        item for item in announcements if item.id == selected_id
    )
    image_map = _read_image_map(current_user, [selected])

    if target_id == selected.id:
        st.info("Opened from Notifications")

    _render_preview(
        selected,
        image_bytes=image_map.get(selected.id),
    )


def _render_create(current_user: AuthenticatedUser) -> None:
    """Create a draft or publish/schedule a new post."""

    settings = get_settings()
    today = _local_today()
    st.info(
        "Create and publish official employee-facing announcements here. "
        "Future events that do not yet have an announcement belong in the "
        "separate Reminders tab."
    )

    with st.form(
        "create_announcement_form",
        clear_on_submit=False,
    ):
        title = st.text_input(
            "Announcement Title *",
            max_chars=180,
        )
        category = st.selectbox(
            "Category *",
            options=ANNOUNCEMENT_CATEGORIES,
        )
        summary = st.text_area(
            "Short Summary *",
            max_chars=500,
            height=110,
            help=(
                "This appears in the employee dashboard card "
                "and notification center."
            ),
        )
        content = st.text_area(
            "Full Announcement *",
            max_chars=20000,
            height=260,
            help=(
                "Basic Markdown such as headings, bullets, and "
                "numbered steps is supported."
            ),
        )
        cover_image = st.file_uploader(
            "Cover Image (Optional)",
            type=["jpg", "jpeg", "png", "webp"],
            help=(
                f"Maximum {settings.announcement_upload_max_mb} MB."
            ),
        )

        date_left, date_right = st.columns(2)

        with date_left:
            publish_date = st.date_input(
                "Publish Date",
                value=today,
                min_value=today,
            )

        with date_right:
            expiry_enabled = st.checkbox(
                "Set Expiry Date",
                value=False,
            )
            expiry_date = st.date_input(
                "Expiry Date",
                value=max(today, publish_date),
                min_value=publish_date,
                disabled=not expiry_enabled,
            )


        is_pinned = st.checkbox(
            "Pin on Employee Dashboard",
            value=False,
            help="Pinned posts are shown before normal announcements.",
        )

        draft_clicked = st.form_submit_button(
            "Save as Draft",
            width="stretch",
        )
        publish_clicked = st.form_submit_button(
            "Publish / Schedule",
            type="primary",
            width="stretch",
        )

    if not draft_clicked and not publish_clicked:
        return

    try:
        values = _announcement_input(
            current_user=current_user,
            title=title,
            category=category,
            summary=summary,
            content=content,
            is_pinned=is_pinned,
            publish_date=publish_date,
            expiry_enabled=expiry_enabled,
            expiry_date=expiry_date,
        )

        with st.spinner("Saving company announcement…"):
            with SessionFactory() as session:
                announcement = AnnouncementService(session).create(
                    values,
                    actor_user_id=current_user.user_id,
                    publish=publish_clicked,
                    image_filename=(
                        cover_image.name if cover_image else None
                    ),
                    image_bytes=(
                        cover_image.getvalue() if cover_image else None
                    ),
                    image_mime_type=(
                        cover_image.type if cover_image else None
                    ),
                )

        status = AnnouncementService.display_status(announcement)
        set_operation_feedback(
            f"{announcement.public_id} saved as {status}.",
            namespace="announcements",
        )
        st.rerun()

    except (ValidationError, ValueError) as error:
        render_action_warning(error)


def _render_manage(
    current_user: AuthenticatedUser,
    announcements,
) -> None:
    """Edit, publish, archive, or restore an existing post."""

    if not announcements:
        st.info(
            "Create an announcement before opening management controls."
        )
        return

    settings = get_settings()
    today = _local_today()
    options = {
        item.id: (
            f"{item.public_id} · {item.title} · "
            f"{AnnouncementService.display_status(item)}"
        )
        for item in announcements
    }
    target_id = _target_announcement_id()
    selected_id = st.selectbox(
        "Select Announcement",
        options=list(options),
        index=_selected_index(announcements, target_id),
        format_func=lambda value: options[value],
        key="manage_announcement_selector",
    )
    selected = next(
        item for item in announcements if item.id == selected_id
    )

    image_map = _read_image_map(current_user, [selected])
    existing_image = image_map.get(selected.id)

    if existing_image:
        render_responsive_image(
            existing_image,
            caption=(
                selected.image_original_filename or "Current cover image"
            ),
            max_width=520,
            max_height=320,
        )

    publish_date_default = _local_date(
        selected.publish_at,
        fallback=today,
    )
    expiry_enabled_default = selected.expires_at is not None
    expiry_date_default = _local_date(
        selected.expires_at,
        fallback=max(today, publish_date_default),
    )

    with st.form(f"manage_announcement_form_{selected.id}"):
        title = st.text_input(
            "Announcement Title *",
            value=selected.title,
            max_chars=180,
        )
        category = st.selectbox(
            "Category *",
            options=ANNOUNCEMENT_CATEGORIES,
            index=ANNOUNCEMENT_CATEGORIES.index(
                selected.category
                if selected.category in ANNOUNCEMENT_CATEGORIES
                else ANNOUNCEMENT_CATEGORIES[0]
            ),
        )
        summary = st.text_area(
            "Short Summary *",
            value=selected.summary,
            max_chars=500,
            height=110,
        )
        content = st.text_area(
            "Full Announcement *",
            value=selected.content,
            max_chars=20000,
            height=260,
        )
        replacement_image = st.file_uploader(
            "Replace Cover Image",
            type=["jpg", "jpeg", "png", "webp"],
            help=(
                f"Maximum {settings.announcement_upload_max_mb} MB."
            ),
        )
        remove_image = st.checkbox(
            "Remove Current Cover Image",
            value=False,
            disabled=not bool(selected.image_storage_path),
        )

        date_left, date_right = st.columns(2)

        with date_left:
            publish_date = st.date_input(
                "Publish Date",
                value=publish_date_default,
            )

        with date_right:
            expiry_enabled = st.checkbox(
                "Set Expiry Date",
                value=expiry_enabled_default,
            )
            expiry_date = st.date_input(
                "Expiry Date",
                value=max(expiry_date_default, publish_date),
                min_value=publish_date,
                disabled=not expiry_enabled,
            )


        is_pinned = st.checkbox(
            "Pin on Employee Dashboard",
            value=selected.is_pinned,
        )

        save_clicked = st.form_submit_button(
            "Save Changes",
            width="stretch",
        )
        publish_clicked = st.form_submit_button(
            "Publish / Schedule",
            type="primary",
            width="stretch",
        )

    st.divider()
    delete_confirmed = st.checkbox(
        "I understand that Delete moves this announcement to Archive.",
        value=False,
        key=f"confirm_delete_announcement_{selected.id}",
        help=(
            "The announcement is retained in the database and can be "
            "restored later from the Archive tab."
        ),
    )
    delete_clicked = st.button(
        "Delete Announcement",
        width="stretch",
        disabled=not delete_confirmed,
        key=f"delete_announcement_{selected.id}",
    )

    if not any((save_clicked, publish_clicked, delete_clicked)):
        return

    try:
        values = _announcement_input(
            current_user=current_user,
            title=title,
            category=category,
            summary=summary,
            content=content,
            is_pinned=is_pinned,
            publish_date=publish_date,
            expiry_enabled=expiry_enabled,
            expiry_date=expiry_date,
        )

        with st.spinner("Updating company announcement…"):
            with SessionFactory() as session:
                service = AnnouncementService(session)

                if delete_clicked:
                    announcement = service.move_to_archive(
                        company_id=current_user.company_id,
                        announcement_id=selected.id,
                        actor_user_id=current_user.user_id,
                    )
                else:
                    announcement = service.update(
                        announcement_id=selected.id,
                        values=values,
                        actor_user_id=current_user.user_id,
                        publish=publish_clicked,
                        replacement_filename=(
                            replacement_image.name
                            if replacement_image
                            else None
                        ),
                        replacement_bytes=(
                            replacement_image.getvalue()
                            if replacement_image
                            else None
                        ),
                        replacement_mime_type=(
                            replacement_image.type
                            if replacement_image
                            else None
                        ),
                        remove_image=remove_image,
                    )

        feedback_message = (
            f"{announcement.public_id} moved to Archive. "
            "It is no longer displayed to employees and was not "
            "permanently deleted."
            if delete_clicked
            else (
                f"{announcement.public_id} updated. Status: "
                f"{AnnouncementService.display_status(announcement)}."
            )
        )
        set_operation_feedback(
            feedback_message,
            namespace="announcements",
        )
        st.rerun()

    except (ValidationError, ValueError) as error:
        render_action_warning(error)


def _render_reminders(
    current_user: AuthenticatedUser,
    reminders,
    archived_reminders,
) -> None:
    """Render smart one-box planning, year history, and Reminder Bin."""

    st.info(
        "Record future events or activities before an announcement exists. "
        "Every YYYY/MM/DD - Title line starts a separate reminder, and the "
        "following lines become its preparation notes. Admin notifications "
        "are automatic at 1 month, 2 weeks, and 1 week before each event."
    )

    reminder_tab_labels = [
        "Create Reminder",
        "Manage Reminders",
        f"Reminder Bin ({len(archived_reminders)})",
    ]
    reminder_default_tab = _consume_tab_target(
        REMINDERS_NEXT_TAB_KEY,
        reminder_tab_labels,
    )
    create_tab, manage_tab, bin_tab = st.tabs(
        reminder_tab_labels,
        default=reminder_default_tab,
    )

    with create_tab:
        form_revision = int(
            st.session_state.get(CREATE_REMINDER_FORM_REVISION_KEY, 0)
        )
        with st.form(
            f"create_smart_event_reminder_form_{form_revision}"
        ):
            category = st.selectbox(
                "Category *",
                options=EVENT_REMINDER_CATEGORIES,
                index=None,
                placeholder="Select a category",
                key=f"create_smart_reminder_category_{form_revision}",
            )
            entry_text = st.text_area(
                "Entry Box *",
                height=330,
                max_chars=30000,
                placeholder=(
                    "2026/06/12 - Araw ng Kalayaan\n"
                    "Prepare the employee greeting and announcement.\n"
                    "Confirm the activity details with HR.\n\n"
                    "2026/02/14 - Valentine's Day\n"
                    "Prepare the employee greeting and announcement.\n"
                    "Confirm the activity details with HR."
                ),
                help=(
                    "Each YYYY/MM/DD - Event or Activity Title line starts "
                    "a new reminder. Add its preparation notes below it. "
                    "The selected Category applies to every entry in the batch."
                ),
                key=f"create_smart_reminder_entry_{form_revision}",
            )
            st.caption(
                "Save one or many entries at once. Automatic notifications: "
                "1 month, 2 weeks, and 1 week before every event or activity."
            )
            create_clicked = st.form_submit_button(
                "Save Smart Reminders",
                type="primary",
                width="stretch",
            )

        if create_clicked:
            try:
                values_list = _reminder_inputs(
                    current_user=current_user,
                    category=category,
                    entry_text=entry_text,
                )
                with SessionFactory() as session:
                    created_reminders = EventReminderService(
                        session
                    ).create_many(
                        values_list,
                        actor_user_id=current_user.user_id,
                    )

                if len(created_reminders) == 1:
                    created = created_reminders[0]
                    feedback_message = (
                        f"{created.public_id} saved for "
                        f"{_planning_schedule_text(created)}."
                    )
                else:
                    feedback_message = (
                        f"{len(created_reminders)} reminders saved "
                        f"({created_reminders[0].public_id} to "
                        f"{created_reminders[-1].public_id})."
                    )

                set_operation_feedback(
                    (
                        f"{feedback_message} Admin reminders were scheduled "
                        "automatically for 1 month, 2 weeks, and 1 week "
                        "before each event."
                    ),
                    namespace="announcements",
                )
                # A new key generation creates genuinely empty widgets only
                # after a successful save. Validation errors keep the user's
                # current values so they can be corrected.
                st.session_state[CREATE_REMINDER_FORM_REVISION_KEY] = (
                    form_revision + 1
                )
                _remember_reminder_tab("Create Reminder")
                st.rerun()
            except (ValidationError, ValueError) as error:
                render_action_warning(error)

    with manage_tab:
        if not reminders:
            st.info("Create a reminder before opening the year history.")
        else:
            target_id = _target_reminder_id()
            target = next(
                (item for item in reminders if item.id == target_id),
                None,
            )
            available_years = sorted(
                {
                    _local_date(
                        item.event_start_at,
                        fallback=_local_today(),
                    ).year
                    for item in reminders
                },
                reverse=True,
            )
            preferred_year = (
                _local_date(
                    target.event_start_at,
                    fallback=_local_today(),
                ).year
                if target is not None
                else (
                    _local_today().year
                    if _local_today().year in available_years
                    else available_years[0]
                )
            )
            selected_year = st.selectbox(
                "Reminder History Year",
                options=available_years,
                index=available_years.index(preferred_year),
                key="manage_reminder_history_year",
            )
            year_items = [
                item
                for item in reminders
                if _local_date(
                    item.event_start_at,
                    fallback=_local_today(),
                ).year == selected_year
            ]

            st.markdown(f"#### {selected_year} Reminder History")
            render_admin_table(
                [
                    {
                        "Reminder ID": item.public_id,
                        "Event Date": _planning_schedule_text(item),
                        "Event / Activity": item.title,
                        "Category": item.category,
                        "Status": REMINDER_STATUS_LABELS.get(
                            item.status,
                            item.status,
                        ),
                        "Automatic Notifications": _planning_reminder_status(item),
                    }
                    for item in year_items
                ],
                key=f"event-reminder-history-{selected_year}",
                min_width=1500,
                column_widths=(
                    "150px",
                    "150px",
                    "310px",
                    "190px",
                    "180px",
                    "520px",
                ),
                max_height=430,
            )

            options = {
                item.id: f"{item.public_id} · {_planning_schedule_text(item)} · {item.title}"
                for item in year_items
            }
            target_for_year = (
                target.id
                if target is not None and target.id in options
                else None
            )
            option_ids = list(options)
            selected_id = st.selectbox(
                "Select Reminder",
                options=option_ids,
                index=(
                    option_ids.index(target_for_year)
                    if target_for_year in option_ids
                    else 0
                ),
                format_func=lambda value: options[value],
                key=f"manage_event_reminder_selector_{selected_year}",
            )
            selected = next(
                item for item in year_items if item.id == selected_id
            )

            st.markdown("#### Reminder Preview")
            _render_reminder_preview_box(
                selected,
                key=f"manage-{selected.id}",
            )

            with st.form(f"manage_smart_reminder_form_{selected.id}"):
                category = st.selectbox(
                    "Category *",
                    options=EVENT_REMINDER_CATEGORIES,
                    index=EVENT_REMINDER_CATEGORIES.index(
                        selected.category
                        if selected.category in EVENT_REMINDER_CATEGORIES
                        else EVENT_REMINDER_CATEGORIES[0]
                    ),
                    key=f"manage_smart_reminder_category_{selected.id}",
                )
                entry_text = st.text_area(
                    "Entry Box *",
                    value=_smart_entry_text(selected),
                    height=220,
                    max_chars=5400,
                    help=(
                        "Update the date and title on the first line. "
                        "Changing the event date resets the automatic "
                        "notification milestones."
                    ),
                    key=f"manage_smart_reminder_entry_{selected.id}",
                )
                status_values = list(REMINDER_STATUS_LABELS)
                status = st.selectbox(
                    "Planning Status",
                    options=status_values,
                    index=status_values.index(
                        selected.status
                        if selected.status in status_values
                        else "planned"
                    ),
                    format_func=lambda value: REMINDER_STATUS_LABELS[value],
                    key=f"manage_smart_reminder_status_{selected.id}",
                )
                save_clicked = st.form_submit_button(
                    "Save Reminder Changes",
                    type="primary",
                    width="stretch",
                )

            move_confirmed = st.checkbox(
                "I confirm that the selected reminder should move to the Reminder Bin.",
                value=False,
                key=f"confirm_bin_event_reminder_{selected.id}",
            )
            move_clicked = st.button(
                "Move Selected Reminder to Bin",
                width="stretch",
                disabled=not move_confirmed,
                key=f"bin_event_reminder_{selected.id}",
            )

            if save_clicked or move_clicked:
                try:
                    with SessionFactory() as session:
                        service = EventReminderService(session)
                        if move_clicked:
                            moved = service.move_to_bin(
                                company_id=current_user.company_id,
                                reminder_id=selected.id,
                                actor_user_id=current_user.user_id,
                            )
                            message = f"{moved.public_id} moved to Reminder Bin."
                        else:
                            values = _reminder_input(
                                current_user=current_user,
                                category=category,
                                entry_text=entry_text,
                                status=status,
                                announcement_id=selected.announcement_id,
                            )
                            updated = service.update(
                                reminder_id=selected.id,
                                values=values,
                                actor_user_id=current_user.user_id,
                            )
                            message = f"{updated.public_id} updated."
                    set_operation_feedback(
                        message,
                        namespace="announcements",
                    )
                    _remember_reminder_tab("Manage Reminders")
                    st.rerun()
                except (ValidationError, ValueError) as error:
                    render_action_warning(error)

    with bin_tab:
        st.caption(
            "Reminder plans moved here are excluded from active history and "
            "automatic notifications. Restore them or permanently delete them."
        )
        if not archived_reminders:
            st.info("The Reminder Bin is empty.")
        else:
            render_admin_table(
                [
                    {
                        "Reminder ID": item.public_id,
                        "Event Date": _planning_schedule_text(item),
                        "Event / Activity": item.title,
                        "Category": item.category,
                        "Archived At": _display_datetime(item.archived_at),
                    }
                    for item in archived_reminders
                ],
                key="archived-event-reminder-table",
                min_width=1100,
                column_widths=(
                    "150px",
                    "150px",
                    "330px",
                    "190px",
                    "220px",
                ),
                max_height=400,
            )
            archived_options = {
                item.id: f"{item.public_id} · {_planning_schedule_text(item)} · {item.title}"
                for item in archived_reminders
            }
            archived_id = st.selectbox(
                "Select Reminder in Bin",
                options=list(archived_options),
                format_func=lambda value: archived_options[value],
                key="archived_event_reminder_selector",
            )
            archived = next(
                item for item in archived_reminders if item.id == archived_id
            )
            st.markdown("#### Archived Reminder Preview")
            _render_reminder_preview_box(
                archived,
                key=f"bin-{archived.id}",
            )

            restore_column, delete_column = st.columns(2)
            with restore_column:
                restore_clicked = st.button(
                    "Restore Reminder",
                    type="primary",
                    width="stretch",
                    key=f"restore_event_reminder_{archived.id}",
                )
            with delete_column:
                permanent_confirmed = st.checkbox(
                    "Confirm permanent deletion",
                    value=False,
                    key=f"confirm_permanent_event_reminder_{archived.id}",
                )
                permanent_clicked = st.button(
                    "Permanently Delete",
                    width="stretch",
                    disabled=not permanent_confirmed,
                    key=f"permanent_delete_event_reminder_{archived.id}",
                )

            if restore_clicked or permanent_clicked:
                try:
                    with SessionFactory() as session:
                        service = EventReminderService(session)
                        if restore_clicked:
                            restored = service.restore_from_bin(
                                company_id=current_user.company_id,
                                reminder_id=archived.id,
                                actor_user_id=current_user.user_id,
                            )
                            message = f"{restored.public_id} restored."
                        else:
                            service.permanently_delete(
                                company_id=current_user.company_id,
                                reminder_id=archived.id,
                            )
                            message = f"{archived.public_id} permanently deleted."
                    set_operation_feedback(
                        message,
                        namespace="announcements",
                    )
                    _remember_reminder_tab(
                        f"Reminder Bin ({len(archived_reminders)})"
                    )
                    st.rerun()
                except ValueError as error:
                    render_action_warning(error)


def _render_archive(
    current_user: AuthenticatedUser,
    archived_announcements,
) -> None:
    """Display soft-deleted announcements and allow draft restoration."""

    st.caption(
        "Deleted announcements are retained here. They are hidden from "
        "employees and can be restored as drafts."
    )

    if not archived_announcements:
        st.info("The announcement Archive is empty.")
        return

    render_admin_table(
        [
            {
                "Announcement ID": item.public_id,
                "Title": item.title,
                "Category": item.category,
                "Archived At": _display_datetime(item.archived_at),
                "Original Publish Date": _display_datetime(
                    item.publish_at
                ),
            }
            for item in archived_announcements
        ],
        key="archived-announcement-table",
        min_width=1050,
        column_widths=(
            "150px",
            "300px",
            "180px",
            "190px",
            "210px",
        ),
        max_height=400,
    )

    options = {
        item.id: f"{item.public_id} · {item.title}"
        for item in archived_announcements
    }
    selected_id = st.selectbox(
        "Select Archived Announcement",
        options=list(options),
        format_func=lambda value: options[value],
        key="archived_announcement_selector",
    )
    selected = next(
        item for item in archived_announcements if item.id == selected_id
    )
    image_map = _read_image_map(current_user, [selected])

    _render_preview(
        selected,
        image_bytes=image_map.get(selected.id),
    )

    if st.button(
        "Restore to Draft",
        type="primary",
        width="stretch",
        key=f"restore_archived_announcement_{selected.id}",
    ):
        try:
            with st.spinner("Restoring announcement as draft…"):
                with SessionFactory() as session:
                    restored = AnnouncementService(
                        session
                    ).restore_archived(
                        company_id=current_user.company_id,
                        announcement_id=selected.id,
                        actor_user_id=current_user.user_id,
                    )

            set_operation_feedback(
                (
                    f"{restored.public_id} restored as Draft. "
                    "Review and publish it when ready."
                ),
                namespace="announcements",
            )
            st.rerun()

        except ValueError as error:
            render_action_warning(error)


def render_admin_announcements_page(
    current_user: AuthenticatedUser,
) -> None:
    """Render announcements and the separate admin planning reminders."""

    st.title("Announcements")
    st.caption(
        "Publish formal information, recent company activities, events, "
        "reminders, and urgent notices to the Employee Portal."
    )
    render_operation_feedback(namespace="announcements")

    with SessionFactory() as session:
        service = AnnouncementService(session)
        service.reconcile_publications(
            company_id=current_user.company_id
        )
        announcements = service.list_for_admin(
            current_user.company_id
        )

    with SessionFactory() as session:
        reminder_service = EventReminderService(session)
        reminder_service.reconcile_due(
            company_id=current_user.company_id
        )
        reminders = reminder_service.list_for_admin(
            current_user.company_id
        )
        archived_reminders = reminder_service.list_archived(
            current_user.company_id
        )

    active_announcements = [
        item for item in announcements if item.status != "archived"
    ]
    archived_announcements = [
        item for item in announcements if item.status == "archived"
    ]

    announcement_tab_labels = [
        "Overview",
        "Create Announcement",
        "Manage Announcements",
        "Reminders",
        f"Archive ({len(archived_announcements)})",
    ]
    announcement_default_tab = _consume_tab_target(
        ANNOUNCEMENTS_NEXT_TAB_KEY,
        announcement_tab_labels,
    )
    (
        overview_tab,
        create_tab,
        manage_tab,
        calendar_tab,
        archive_tab,
    ) = st.tabs(
        announcement_tab_labels,
        default=announcement_default_tab,
        key="announcements_active_tab",
        on_change="rerun",
    )

    with overview_tab:
        _render_overview(
            current_user,
            active_announcements,
        )

    with create_tab:
        _render_create(current_user)

    with manage_tab:
        _render_manage(
            current_user,
            active_announcements,
        )

    with calendar_tab:
        _render_reminders(
            current_user,
            reminders,
            archived_reminders,
        )

    with archive_tab:
        _render_archive(
            current_user,
            archived_announcements,
        )
