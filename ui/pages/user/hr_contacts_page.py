"""Employee-facing published HR contact directory."""

from __future__ import annotations

from html import escape

import streamlit as st

from authentication.current_user import AuthenticatedUser
from database.session import SessionFactory
from services.hr_contact_service import HRContactService
from ui.components.live_search import multi_search_input
from utils.search_utils import matches_search_terms


def _matches_search(contact, search_terms) -> bool:
    return matches_search_terms(
        search_terms,
        (
            contact.name,
            contact.job_title,
            contact.team,
            contact.email,
            contact.phone,
            contact.office_location,
            contact.availability,
            contact.notes,
        ),
    )


def _render_contact_card(contact) -> None:
    """Render one compact, read-only employee HR contact card."""

    role_parts = [value for value in (contact.job_title, contact.team) if value]
    role_text = " · ".join(role_parts)

    detail_rows: list[str] = []
    if contact.email:
        safe_email = escape(contact.email, quote=True)
        detail_rows.append(
            '<div class="hr-contact-detail"><strong>Email:</strong> '
            f'<a href="mailto:{safe_email}">{safe_email}</a></div>'
        )
    if contact.phone:
        safe_phone = escape(contact.phone)
        detail_rows.append(
            '<div class="hr-contact-detail"><strong>Phone / Mobile:</strong> '
            f'{safe_phone}</div>'
        )
    if contact.office_location:
        detail_rows.append(
            '<div class="hr-contact-detail"><strong>Office / Location:</strong> '
            f'{escape(contact.office_location)}</div>'
        )
    if contact.availability:
        detail_rows.append(
            '<div class="hr-contact-detail"><strong>Availability:</strong> '
            f'{escape(contact.availability)}</div>'
        )
    if contact.notes:
        detail_rows.append(
            '<div class="hr-contact-detail hr-contact-notes"><strong>Notes:</strong> '
            f'{escape(contact.notes)}</div>'
        )

    role_html = (
        f'<div class="hr-contact-role">{escape(role_text)}</div>' if role_text else ""
    )
    card_html = (
        '<div class="hr-contact-card-content">'
        f'<div class="hr-contact-name">{escape(contact.name)}</div>'
        f'{role_html}'
        f'{"".join(detail_rows)}'
        '</div>'
    )

    with st.container(border=True):
        st.markdown(card_html, unsafe_allow_html=True)


def render_employee_hr_contacts_page(current_user: AuthenticatedUser) -> None:
    """Show active company HR contacts without employee edit controls."""

    st.markdown(
        """
        <style>
        .hr-contact-card-content {
            padding: 0.05rem 0.05rem 0.10rem;
        }
        .hr-contact-name {
            margin: 0 0 0.22rem;
            font-size: 1.55rem;
            font-weight: 700;
            line-height: 1.18;
        }
        .hr-contact-role {
            margin: 0 0 0.48rem;
            color: var(--text-color-secondary, #6b7280);
            font-size: 0.92rem;
            line-height: 1.28;
        }
        .hr-contact-detail {
            margin: 0.24rem 0;
            line-height: 1.32;
        }
        .hr-contact-notes {
            margin-top: 0.34rem;
        }
        .hr-contact-detail a {
            overflow-wrap: anywhere;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.title("HR Contacts")
    st.caption(
        "Contact the appropriate HR representative using the directory "
        "published by your company administrator."
    )

    with SessionFactory() as session:
        contacts = HRContactService(session).list_contacts(
            current_user.company_id,
            active_only=True,
        )

    if not contacts:
        st.info("No HR contacts are currently published by your company administrator.")
        return

    search_terms = multi_search_input(
        "Search HR Contacts",
        placeholder="Type name, role, team, email, or location, then press Enter…",
        key="employee_hr_contacts_search",
    )
    visible_contacts = [
        contact for contact in contacts if _matches_search(contact, search_terms)
    ]

    st.caption(
        f"Showing {len(visible_contacts)} of {len(contacts)} published HR contact"
        f"{'s' if len(contacts) != 1 else ''}."
    )

    if not visible_contacts:
        st.info("No HR contacts match your search.")
        return

    columns = st.columns(2, gap="medium")
    for index, contact in enumerate(visible_contacts):
        with columns[index % 2]:
            _render_contact_card(contact)
