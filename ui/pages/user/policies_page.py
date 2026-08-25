"""Employee browser for published uploaded policy files."""

import html

import streamlit as st

from authentication.current_user import AuthenticatedUser
from database.session import SessionFactory
from modules.policy_qa.policy_assistant import PolicyAssistant
from config.settings import get_settings
from services.policy_service import PolicyService
from ui.components.live_search import live_search_input
from ui.components.persistent_tabs import persistent_tabs
from ui.pages.user.policy_violations import render_employee_policy_violations
from ui.components.disciplinary_records import render_employee_disciplinary_records


def _source_caption(source) -> str:
    """Build a readable file-grounded source caption."""

    parts = [
        source.filename or "Manual policy entry",
        source.title,
        source.section_heading,
        f"Version {source.version}",
    ]

    if source.page_number is not None:
        parts.append(f"Page {source.page_number}")

    if source.uploaded_at:
        parts.append(
            "Uploaded "
            + PolicyService.format_datetime(
                source.uploaded_at,
                get_settings().display_timezone,
            )
        )

    return " · ".join(parts)


def _policy_content_html(value: str) -> str:
    """Escape source text and preserve line breaks on a light surface."""

    escaped = (
        html.escape(value or "")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "<br>")
    )

    return (
        '<div class="hr-employee-policy-content" '
        'role="document">'
        f"{escaped}"
        "</div>"
    )


def _render_employee_policy_library(
    current_user: AuthenticatedUser,
) -> None:
    """Browse and ask questions about approved policy files."""

    st.caption(
        "Only active published files from your company are available. "
        "Versions moved to the Bin are excluded."
    )

    with SessionFactory() as session:
        service = PolicyService(session)
        all_policies = service.list_published(
            current_user.company_id
        )
        document_map = service.get_document_map(
            company_id=current_user.company_id,
            policies=all_policies,
        )

    categories = sorted(
        {
            policy.category
            for policy in all_policies
        }
    )

    filter_columns = st.columns([2, 1])

    with filter_columns[0]:
        search_text = live_search_input(
            "Search Policies",
            placeholder=(
                "Search title, category, or extracted file content..."
            ),
            key="employee_policy_search",
            suggestions=(
                value
                for policy in all_policies
                for value in (policy.title, policy.category)
            ),
        )

    with filter_columns[1]:
        category = st.selectbox(
            "Category",
            options=["All Categories", *categories],
        )

    with SessionFactory() as session:
        filtered_policies = PolicyService(
            session
        ).search_published(
            company_id=current_user.company_id,
            search_text=search_text,
            category=(
                None
                if category == "All Categories"
                else category
            ),
        )

    if not filtered_policies:
        st.info("No matching approved policy files were found.")
    else:
        for policy in filtered_policies:
            document = document_map.get(policy.id)
            source_name = (
                document.original_filename
                if document
                else "Manual policy entry"
            )

            with st.expander(
                f"{policy.title} · v{policy.version}"
            ):
                st.caption(
                    f"Source: {source_name} · "
                    f"Category: {policy.category} · "
                    "Uploaded: "
                    + PolicyService.format_datetime(
                        policy.created_at,
                        get_settings().display_timezone,
                    )
                )

                if policy.summary:
                    st.markdown(
                        f"**Summary:** {policy.summary}"
                    )

                # Display the exact extracted source text safely while
                # preserving line breaks and readable Light Mode contrast.
                with st.container(
                    key=f"employee_policy_content_{policy.id}",
                ):
                    st.markdown(
                        _policy_content_html(
                            policy.content
                        ),
                        unsafe_allow_html=True,
                    )

    st.subheader("Download Approved Source File")

    downloadable = {
        (
            f"{policy.title} v{policy.version} — "
            f"{document_map[policy.id].original_filename}"
        ): policy.id
        for policy in filtered_policies
        if policy.id in document_map
    }

    if downloadable:
        selected_label = st.selectbox(
            "Approved Policy File",
            options=list(downloadable),
        )

        with SessionFactory() as session:
            download = PolicyService(
                session
            ).get_policy_download(
                company_id=current_user.company_id,
                policy_id=downloadable[selected_label],
                published_only=True,
            )

        st.download_button(
            "Download Policy File",
            data=download.data,
            file_name=download.filename,
            mime=download.mime_type,
            width="stretch",
        )
    else:
        st.info(
            "No uploaded source file is available for the "
            "current policy selection."
        )

    st.divider()
    st.subheader("Ask About Company Policies")

    with st.form("employee_policy_question_form"):
        question = st.text_area(
            "Question",
            height=100,
            placeholder=(
                "Example: How many annual leave days "
                "can an employee use?"
            ),
        )

        ask_submitted = st.form_submit_button(
            "Ask Policy Assistant",
            type="primary",
            width="stretch",
        )

    if ask_submitted:
        if len(question.strip()) < 3:
            st.error("Enter a complete policy question.")
            return

        with SessionFactory() as session:
            response = PolicyAssistant(session).answer(
                company_id=current_user.company_id,
                question=question,
            )

        st.markdown("### Answer")

        with st.container(
            key="employee_policy_assistant_answer",
        ):
            st.markdown(response.answer)

        if response.sources:
            st.markdown("**Sources**")

            for source in response.sources:
                st.caption(_source_caption(source))


def render_employee_policies_page(
    current_user: AuthenticatedUser,
) -> None:
    """Render published policies and the read-only violation master list."""

    st.title("Company Policies")
    policy_tab, violation_tab, records_tab = persistent_tabs(
        [
            "Company Policies",
            "Violations & Disciplinary Actions",
            "My Disciplinary Records",
        ],
        key="employee_policies_active_tab",
    )
    with policy_tab:
        _render_employee_policy_library(current_user)
    with violation_tab:
        render_employee_policy_violations(current_user)
    with records_tab:
        render_employee_disciplinary_records(current_user)
