"""Employee context-aware HR Assistant chat page."""

import streamlit as st

from authentication.current_user import AuthenticatedUser
from database.session import SessionFactory
from modules.hr_assistant.hr_assistant import HRAssistant, HRAssistantResponse
from modules.smart_ai.portal_ai import SmartPortalAssistant
from services.runtime_connection_service import (
    classify_runtime_connection_issue,
    log_runtime_connection_issue,
)
from ui.components.quick_actions import render_quick_actions
from ui.components.chat_assistant_report import (
    current_assistant_timestamp,
    render_assistant_timestamp,
    render_chat_report,
)
from ui.module_view_navigation import (
    EXACT_VIEW_QUERY_KEYS,
    prime_exact_module_view,
)
from ui.navigation_state import set_navigation_state


CHAT_STATE_PREFIX = "hr_assistant_chat_messages__"
CHAT_INPUT_PREFIX = "hr_assistant_chat_input__"
UNSCOPED_CHAT_STATE_KEYS = {
    "hr_assistant_chat_messages",
    "policy_chat_messages",
}
_ACTION_QUERY_KEYS = {
    "leave_view",
    "announcement_id",
    "leave_request_id",
    "policy_id",
} | EXACT_VIEW_QUERY_KEYS


def _chat_identity(
    current_user: AuthenticatedUser,
) -> str:
    """Return the company-and-user identity for private browser state."""

    return (
        f"company_{current_user.company_id}"
        f"__user_{current_user.user_id}"
    )


def _chat_state_key(
    current_user: AuthenticatedUser,
) -> str:
    """Return the signed-in account's private conversation key."""

    return (
        f"{CHAT_STATE_PREFIX}"
        f"{_chat_identity(current_user)}"
    )


def _chat_input_key(
    current_user: AuthenticatedUser,
) -> str:
    """Return the signed-in account's private chat-input key."""

    return (
        f"{CHAT_INPUT_PREFIX}"
        f"{_chat_identity(current_user)}"
    )


def _remove_unsafe_unscoped_chat_state() -> None:
    """Delete chat values made by older non-private builds."""

    for key in UNSCOPED_CHAT_STATE_KEYS:
        st.session_state.pop(
            key,
            None,
        )


def _source_lines(sources) -> list[str]:
    """Convert approved policy sources into chat-friendly lines."""

    lines = []

    for source in sources:
        effective_date = (
            source.effective_date.isoformat()
            if source.effective_date
            else "Not specified"
        )
        file_label = source.filename or "Manual policy entry"
        page_label = (
            f", page {source.page_number}"
            if source.page_number is not None
            else ""
        )

        lines.append(
            f"{file_label} — {source.title} — {source.section_heading} "
            f"(v{source.version}{page_label}, effective {effective_date})"
        )

    return lines


def _open_action(action: dict) -> None:
    """Navigate to one assistant-recommended employee module."""

    for key in _ACTION_QUERY_KEYS:
        if key in st.query_params:
            del st.query_params[key]

    portal_mode = str(action.get("portal_mode", "employee"))
    page = str(action.get("page", "Dashboard"))
    query_params = {
        str(key): str(value)
        for key, value in dict(action.get("query_params", {})).items()
    }

    prime_exact_module_view(
        portal_mode=portal_mode,
        page=page,
        query_params=query_params,
    )
    set_navigation_state(portal_mode=portal_mode, current_page=page)

    for key, value in query_params.items():
        st.query_params[key] = value

    st.rerun()


def _render_message_actions(
    *,
    current_user: AuthenticatedUser,
    message_index: int,
    actions: list[dict],
) -> None:
    """Render clickable navigation buttons below one assistant answer."""

    if not actions:
        return

    st.markdown("**Open related HR page**")

    for action_index, action in enumerate(actions):
        if st.button(
            str(action.get("label", "Open")),
            width="stretch",
            key=(
                "hr_assistant_action_"
                f"{_chat_identity(current_user)}_"
                f"{message_index}_{action_index}"
            ),
        ):
            _open_action(action)


def _initial_messages() -> list[dict]:
    """Start empty because the welcome message is display-only."""

    return []


def render_chat_page(current_user: AuthenticatedUser) -> None:
    """Answer HR questions using live records and approved policies."""

    main, side = st.columns([3, 1], gap="large")

    with main:
        st.title("HR Assistant")
        st.caption(
            "Uses your live HR records, configured HR modules, and approved "
            "company policies. It does not guess."
        )

        _remove_unsafe_unscoped_chat_state()

        chat_state_key = _chat_state_key(
            current_user
        )
        chat_input_key = _chat_input_key(
            current_user
        )

        if chat_state_key not in st.session_state:
            st.session_state[
                chat_state_key
            ] = _initial_messages()

        messages = st.session_state[
            chat_state_key
        ]

        # Remove the persisted welcome used by earlier checkpoints while
        # preserving every real user and assistant message.
        while messages and messages[0].get("intent") == "welcome":
            messages.pop(0)

        # Reserve the complete conversation area before the input. Re-entering
        # this container after a submission keeps the pending user message,
        # loading state, and final history above the chat input.
        conversation_area = st.container()
        welcome_placeholder = None

        with conversation_area:
            if not messages:
                welcome_placeholder = st.empty()
                with welcome_placeholder.container():
                    with st.chat_message("assistant"):
                        st.markdown("Good day, how can I assist you today?")

            for message_index, message in enumerate(messages):
                role = str(message.get("role", "assistant"))
                message_key = (
                    "hr_assistant_message_"
                    f"{_chat_identity(current_user)}_"
                    f"{role}_{message_index}"
                )

                with st.chat_message(role):
                    # Stable wrapper for Light Mode contrast and Markdown lists.
                    with st.container(key=message_key):
                        if role == "assistant" and message.get("runtime_warning"):
                            warning_title = str(message.get("runtime_warning_title") or "Service warning")
                            st.warning(
                                f"**{warning_title}**\n\n{message['runtime_warning']}"
                            )
                        st.markdown(
                            str(message.get("content", ""))
                        )

                        if role == "assistant":
                            render_chat_report(
                                message.get("report"),
                                key_prefix=f"{message_key}_report",
                            )

                        if message.get("sources"):
                            st.markdown(
                                "**Approved policy sources**"
                            )
                            for source_line in message["sources"]:
                                st.caption(source_line)

                        _render_message_actions(
                            current_user=current_user,
                            message_index=message_index,
                            actions=message.get("actions", []),
                        )

                        if role == "assistant":
                            render_assistant_timestamp(message.get("timestamp"))

        question = st.chat_input(
            "Ask an HR question, e.g. 'Ilan na lang VL ko?'",
            key=chat_input_key,
        )

        if question:
            previous_history = list(messages)
            messages.append(
                {
                    "role": "user",
                    "content": question,
                    "sources": [],
                    "actions": [],
                }
            )

            # The display-only welcome must disappear as soon as the first
            # question is accepted, including while the answer is loading.
            if welcome_placeholder is not None:
                welcome_placeholder.empty()

            with conversation_area:
                with st.chat_message("user"):
                    st.markdown(question)

                with st.chat_message("assistant"):
                    with st.spinner(
                        "Searching your authorized HR records and company information…"
                    ):
                        try:
                            with SessionFactory() as session:
                                response = HRAssistant(session).answer(
                                    current_user=current_user,
                                    question=question,
                                    history=previous_history,
                                )
                                smart_assistant = SmartPortalAssistant(session)
                                preflight_issue = smart_assistant.preflight_connection_issue(
                                    role_scope="employee",
                                )
                                if preflight_issue is None:
                                    response = smart_assistant.enhance(
                                        current_user=current_user,
                                        role_scope="employee",
                                        question=question,
                                        history=previous_history,
                                        deterministic_response=response,
                                    )
                                else:
                                    response.runtime_warning = preflight_issue.message
                                    response.runtime_warning_title = preflight_issue.title
                                    response.runtime_warning_code = preflight_issue.code
                        except Exception as exc:
                            issue = classify_runtime_connection_issue(exc)
                            if issue is None:
                                raise
                            log_runtime_connection_issue(
                                exc, issue, context="employee_chat_request"
                            )
                            response = HRAssistantResponse(
                                answer=(
                                    "I could not complete that HR request while the "
                                    "required connection is unavailable."
                                ),
                                intent="runtime_connection_error",
                                runtime_warning=issue.message,
                                runtime_warning_title=issue.title,
                                runtime_warning_code=issue.code,
                            )

            if response.runtime_warning:
                st.toast(
                    f"{response.runtime_warning_title or 'Service warning'}: "
                    f"{response.runtime_warning}",
                    icon="⚠️",
                )

            messages.append(
                {
                    "role": "assistant",
                    "content": response.answer,
                    "runtime_warning": response.runtime_warning,
                    "runtime_warning_title": response.runtime_warning_title,
                    "runtime_warning_code": response.runtime_warning_code,
                    "sources": _source_lines(response.sources),
                    "actions": [
                        {
                            "label": action.label,
                            "page": action.page,
                            "portal_mode": action.portal_mode,
                            "query_params": dict(action.query_params),
                        }
                        for action in response.actions
                    ],
                    "intent": response.intent,
                    "report": response.report,
                    "timestamp": current_assistant_timestamp(),
                }
            )
            st.rerun()

        st.caption(
            "Verify sensitive or exceptional cases with HR when required."
        )

    with side:
        if st.button(
            "New HR Conversation",
            width="stretch",
            key=(
                "new_hr_assistant_conversation__"
                f"{_chat_identity(current_user)}"
            ),
        ):
            st.session_state[
                _chat_state_key(current_user)
            ] = _initial_messages()
            st.session_state.pop(
                _chat_input_key(current_user),
                None,
            )
            st.rerun()

        render_quick_actions()

        st.subheader("Answer Sources")
        st.markdown(
            """
            <div class="hr-card">
                <div class="hr-title">Live Data + Approved Policies</div>
                <div class="hr-muted">
                    Personal balances and requests come from live company
                    records. Policy answers come only from published and
                    currently effective policy files.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
