"""Administrator company-profile and branding page.

Company ID remains the immutable tenant boundary. Administrators may safely
change the human-facing company code, company name, sidebar logo, and the
company-wide accent color used by both portals.
"""

from __future__ import annotations

import streamlit as st
from ui.components.validation_feedback import render_action_warning
from ui.components.persistent_tabs import persistent_tabs
from pydantic import ValidationError

from authentication.current_user import AuthenticatedUser
from config.settings import get_settings
from core.constants import DEFAULT_COMPANY_THEME_COLOR
from database.session import SessionFactory
from modules.company_branding.company_logo_storage import (
    extract_logo_theme_colors,
)
from schemas.organization_schema import (
    CompanyProfileUpdate,
    CompanyThemeColorUpdate,
)
from services.organization_service import OrganizationService
from ui.components.confirmation_guard import invalidate_confirmation_on_change
from ui.components.operation_feedback import (
    render_operation_feedback,
    set_operation_feedback,
)
from ui.components.responsive_image import prepare_responsive_image
from ui.theme.color_palette import build_accent_palette
from ui.pages.admin.hr_contacts_management import render_hr_contacts_management



def _company_profile_field_key(
    company_id: int,
    field_name: str,
) -> str:
    """Return a reset-safe key for Company Information inputs."""

    nonce_key = f"_company_profile_fields_nonce_{company_id}"
    nonce = int(st.session_state.get(nonce_key, 0))
    return f"company_profile_{field_name}_{company_id}_{nonce}"


def _advance_company_profile_fields(company_id: int) -> None:
    """Remount identity fields after a normalized value is saved."""

    nonce_key = f"_company_profile_fields_nonce_{company_id}"
    st.session_state[nonce_key] = int(st.session_state.get(nonce_key, 0)) + 1

def _logo_uploader_key(company_id: int) -> str:
    """Return a reset-safe company-logo uploader key."""

    nonce_key = f"_company_logo_uploader_nonce_{company_id}"
    nonce = int(st.session_state.get(nonce_key, 0))
    return f"company_logo_upload_{company_id}_{nonce}"


def _advance_logo_uploader(company_id: int) -> None:
    """Remount the uploader after saving or removing a logo."""

    nonce_key = f"_company_logo_uploader_nonce_{company_id}"
    st.session_state[nonce_key] = int(st.session_state.get(nonce_key, 0)) + 1


def _render_logo_preview(
    image_bytes: bytes,
    *,
    empty_message: str = "No company logo is currently configured.",
) -> None:
    """Display a centered preview without stretching or cropping."""

    if not image_bytes:
        st.info(empty_message)
        return

    prepared = prepare_responsive_image(
        image_bytes,
        max_width=420,
        max_height=150,
    )

    if prepared is None:
        st.warning("The selected company logo could not be previewed.")
        return

    left, center, right = st.columns([1, 3, 1], vertical_alignment="center")

    with center:
        st.image(prepared, width=prepared.width)


def _theme_picker_key(company_id: int) -> str:
    """Return a reset-safe company color-picker key."""

    nonce_key = f"_company_theme_picker_nonce_{company_id}"
    nonce = int(st.session_state.get(nonce_key, 0))
    return f"company_theme_color_{company_id}_{nonce}"


def _advance_theme_controls(company_id: int) -> None:
    """Remount the color picker after choosing a suggested/reset color."""

    key = f"_company_theme_picker_nonce_{company_id}"
    st.session_state[key] = int(st.session_state.get(key, 0)) + 1


def _theme_draft_key(company_id: int) -> str:
    """Return the company-scoped unsaved theme selection key."""

    return f"_company_theme_draft_{company_id}"


def _set_theme_draft(company_id: int, color: str) -> None:
    """Store one normalized unsaved accent color."""

    st.session_state[_theme_draft_key(company_id)] = color.strip().upper()


def _render_theme_preview(selected_color: str) -> None:
    """Display accessible derived accent states before saving."""

    palette = build_accent_palette(selected_color)
    st.markdown(
        f"""
        <div style="
            border:1px solid #D8DEEA;
            border-radius:14px;
            padding:16px;
            background:#FFFFFF;
            margin:0;
        ">
            <div style="color:#10172A;font-weight:700;margin-bottom:10px;">
                Theme Preview
            </div>
            <div style="display:flex;flex-wrap:wrap;gap:10px;align-items:center;">
                <div style="min-width:120px;padding:10px 12px;border-radius:10px;
                    background:{palette['primary']};color:{palette['on_primary']};
                    font-weight:700;text-align:center;">Primary Action</div>
                <div style="min-width:120px;padding:10px 12px;border-radius:10px;
                    background:{palette['primary_hover']};
                    color:{palette['on_primary_hover']};font-weight:700;
                    text-align:center;">Hover State</div>
                <div style="min-width:120px;padding:10px 12px;border-radius:10px;
                    background:{palette['primary_soft']};
                    color:{palette['primary_text']};
                    border:1px solid {palette['primary']};font-weight:700;
                    text-align:center;">Soft Accent</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _swatch_css_rule(key: str, color: str, selected: bool) -> str:
    """Return scoped CSS for one Streamlit color-swatch button."""

    border = "3px solid #111827" if selected else "1px solid #CBD5E1"
    return f"""
    div.st-key-{key} button {{
        background:{color} !important;
        border:{border} !important;
        min-height:34px !important;
        height:34px !important;
        padding:0 !important;
        border-radius:4px !important;
        box-shadow:none !important;
    }}
    div.st-key-{key} button p {{
        font-size:0 !important;
        line-height:0 !important;
    }}
    """


def _render_logo_color_suggestions(
    company_id: int,
    image_bytes: bytes,
    selected_color: str,
) -> None:
    """Render accent suggestions extracted from the current/uploaded logo."""

    suggestions = extract_logo_theme_colors(image_bytes, max_colors=3)
    st.markdown("**Suggested From Company Logo**")

    if not suggestions:
        st.caption(
            "Upload or save a logo with a visible brand color to generate "
            "automatic theme suggestions."
        )
        return

    css_rules: list[str] = []
    keys: list[str] = []

    for index, color in enumerate(suggestions):
        key = f"company_logo_theme_swatch_{company_id}_{index}"
        keys.append(key)
        css_rules.append(
            _swatch_css_rule(
                key,
                color,
                color.upper() == selected_color.upper(),
            )
        )

    st.markdown(f"<style>{''.join(css_rules)}</style>", unsafe_allow_html=True)
    columns = st.columns(len(suggestions), gap="small")

    for index, color in enumerate(suggestions):
        with columns[index]:
            if st.button(
                color,
                key=keys[index],
                help=f"Use logo color {color}",
                width="stretch",
            ):
                _set_theme_draft(company_id, color)
                _advance_theme_controls(company_id)
                st.rerun()
            st.caption(color)


def _render_company_information_tab(
    current_user: AuthenticatedUser,
    *,
    company_code: str,
    company_name: str,
) -> None:
    """Render editable company identity fields."""

    st.subheader("Company Information")
    code_column, name_column = st.columns(2, gap="medium")

    with code_column:
        new_company_code = st.text_input(
            "Company Code",
            value=company_code,
            max_chars=50,
            help=(
                "Employees use this code when signing in. Letters are saved in "
                "uppercase; numbers, hyphens, and underscores are allowed."
            ),
            key=_company_profile_field_key(
                current_user.company_id,
                "code",
            ),
        )

    with name_column:
        new_company_name = st.text_input(
            "Company Name",
            value=company_name,
            max_chars=200,
            key=_company_profile_field_key(
                current_user.company_id,
                "name",
            ),
        )

    normalized_code = new_company_code.strip().upper()
    code_changed = normalized_code != company_code.strip().upper()
    confirm_code_change = True

    if code_changed:
        st.warning(
            "Changing the Company Code will change the code employees use "
            "to sign in. Existing company records remain linked to the same "
            "internal Company ID."
        )
        confirmation_key = _company_profile_field_key(
            current_user.company_id,
            "confirm_code_change",
        )
        invalidate_confirmation_on_change(
            confirmation_key=confirmation_key,
            dependencies={"company_code": normalized_code},
        )
        confirm_code_change = st.checkbox(
            "I understand that employees must use the new Company Code to sign in.",
            key=confirmation_key,
        )

    submitted = st.button(
        "Save Company Information",
        type="primary",
        width="stretch",
        key="save_company_information",
    )

    if not submitted:
        return

    if code_changed and not confirm_code_change:
        st.error("Confirm the Company Code change before saving.")
        return

    try:
        request = CompanyProfileUpdate(
            company_id=current_user.company_id,
            code=new_company_code,
            name=new_company_name,
        )

        with st.spinner("Saving company information…"):
            with SessionFactory() as session:
                updated_company = OrganizationService(
                    session
                ).update_company_profile(request)

        session_user = current_user.to_session_dict()
        session_user["company_code"] = updated_company.code
        session_user["company_name"] = updated_company.name
        st.session_state.authenticated_user = session_user
        st.session_state["public_company_code"] = updated_company.code
        _advance_company_profile_fields(current_user.company_id)

        set_operation_feedback(
            "Company information updated successfully.",
            namespace="company",
        )
        st.rerun()

    except ValidationError as error:
        render_action_warning(error)
    except ValueError as error:
        render_action_warning(error)
    except Exception:
        st.error("The company profile could not be updated.")


def _render_branding_sections(
    current_user: AuthenticatedUser,
    *,
    company_logo_filename: str | None,
    company_logo_bytes: bytes | None,
    company_theme_color: str,
) -> None:
    """Render clearly separated logo and theme customization sections."""

    settings = get_settings()
    st.subheader("Company Logo")
    st.caption(
        "Upload a PNG, JPG, JPEG, or WEBP logo. It appears centered at the "
        "top of both fixed sidebars and keeps its original aspect ratio."
    )

    with st.container(border=True):
        upload_column, preview_column = st.columns(
            [1.45, 1.05],
            gap="large",
            vertical_alignment="top",
        )

        with upload_column:
            st.markdown("**Upload or Replace Logo**")
            uploaded_logo = st.file_uploader(
                "Company Logo File",
                type=["png", "jpg", "jpeg", "webp"],
                key=_logo_uploader_key(current_user.company_id),
                label_visibility="collapsed",
                help=(
                    "Maximum size: "
                    f"{settings.company_logo_upload_max_mb} MB. "
                    "The saved image is normalized to a safe PNG."
                ),
            )
            uploaded_logo_bytes = (
                uploaded_logo.getvalue() if uploaded_logo is not None else b""
            )
            save_logo_column, remove_logo_column = st.columns(2, gap="small")

            with save_logo_column:
                save_logo = st.button(
                    "Save Company Logo",
                    type="primary",
                    width="stretch",
                    disabled=uploaded_logo is None,
                    key="save_company_logo",
                )

            with remove_logo_column:
                remove_logo = st.button(
                    "Remove Company Logo",
                    width="stretch",
                    disabled=not bool(company_logo_filename),
                    key="remove_company_logo",
                )

        with preview_column:
            preview_bytes = uploaded_logo_bytes or company_logo_bytes or b""
            st.markdown(
                "**New Logo Preview**"
                if uploaded_logo_bytes
                else "**Current Sidebar Logo**"
            )
            _render_logo_preview(preview_bytes)
            st.caption(
                "Ready to save"
                if uploaded_logo_bytes
                else (
                    "Configured"
                    if company_logo_filename
                    else "Using the default Company Logo placeholder"
                )
            )

    if save_logo and uploaded_logo is not None:
        try:
            with st.spinner("Saving company logo…"):
                with SessionFactory() as session:
                    OrganizationService(session).update_company_logo(
                        company_id=current_user.company_id,
                        file_name=uploaded_logo.name,
                        content=uploaded_logo_bytes,
                        content_type=uploaded_logo.type,
                    )

            _advance_logo_uploader(current_user.company_id)
            set_operation_feedback(
                "Company logo updated successfully.",
                namespace="company",
            )
            st.rerun()
        except ValueError as error:
            render_action_warning(error)
        except Exception:
            st.error("The company logo could not be updated.")
    elif save_logo:
        # A rerun can clear the uploader between the button event and this
        # branch. Keep that race recoverable instead of reading `.name` or
        # `.type` from None.
        st.error("Select a company logo file before saving.")

    if remove_logo:
        try:
            with st.spinner("Removing company logo…"):
                with SessionFactory() as session:
                    OrganizationService(session).remove_company_logo(
                        current_user.company_id
                    )

            _advance_logo_uploader(current_user.company_id)
            set_operation_feedback(
                "Company logo removed. The sidebar placeholder is active.",
                namespace="company",
            )
            st.rerun()
        except ValueError as error:
            render_action_warning(error)
        except Exception:
            st.error("The company logo could not be removed.")

    st.divider()
    st.subheader("Company Theme Color")
    st.caption(
        "Use a suggested color from the company logo or choose any custom "
        "color. The system derives readable hover, soft accent, and text "
        "colors automatically."
    )

    draft_key = _theme_draft_key(current_user.company_id)
    if draft_key not in st.session_state:
        st.session_state[draft_key] = company_theme_color.upper()

    selected_color = str(st.session_state[draft_key]).upper()

    logo_color_source = uploaded_logo_bytes or company_logo_bytes or b""
    _render_logo_color_suggestions(
        current_user.company_id,
        logo_color_source,
        selected_color,
    )

    custom_color_column, preview_column = st.columns(
        [1.15, 3.85],
        gap="medium",
        vertical_alignment="top",
    )

    with custom_color_column:
        st.markdown("**Custom Color**")
        picker_key = _theme_picker_key(current_user.company_id)
        picked_color = st.color_picker(
            "Color Picker",
            value=selected_color,
            key=picker_key,
            help="Choose any custom primary accent color.",
        ).upper()

        if picked_color != selected_color:
            _set_theme_draft(current_user.company_id, picked_color)
            selected_color = picked_color

        selected_color = str(
            st.session_state[_theme_draft_key(current_user.company_id)]
        ).upper()
        st.caption(f"Selected accent: {selected_color}")

    with preview_column:
        _render_theme_preview(selected_color)

    save_column, reset_column = st.columns(2, gap="small")

    with save_column:
        save_theme = st.button(
            "Save Theme Color",
            type="primary",
            width="stretch",
            key="save_company_theme_color",
        )

    with reset_column:
        reset_theme = st.button(
            "Reset to Default Violet",
            width="stretch",
            key="reset_company_theme_color",
        )

    if not (save_theme or reset_theme):
        return

    target_color = (
        DEFAULT_COMPANY_THEME_COLOR if reset_theme else selected_color
    )

    try:
        request = CompanyThemeColorUpdate(
            company_id=current_user.company_id,
            primary_color=target_color,
        )

        with st.spinner("Applying company theme…"):
            with SessionFactory() as session:
                updated_company = OrganizationService(
                    session
                ).update_company_theme_color(request)

        _set_theme_draft(
            current_user.company_id,
            updated_company.theme_primary_color,
        )
        _advance_theme_controls(current_user.company_id)
        set_operation_feedback(
            "Company theme reset to default violet."
            if reset_theme
            else (
                "Company theme color updated to "
                f"{updated_company.theme_primary_color}."
            ),
            namespace="company",
        )
        st.rerun()

    except ValidationError as error:
        render_action_warning(error)
    except ValueError as error:
        render_action_warning(error)
    except Exception:
        st.error("The company theme could not be updated.")


def render_company_page(current_user: AuthenticatedUser) -> None:
    """Display and update company profile and branding."""

    st.title("Company Profile")
    st.caption(
        "Manage company information, visual branding, and the HR contact "
        "directory used throughout the Administration and Employee portals."
    )
    render_operation_feedback(namespace="company")

    with SessionFactory() as session:
        service = OrganizationService(session)
        company = service.get_company(current_user.company_id)
        company_code = company.code
        company_name = company.name
        company_theme_color = (
            company.theme_primary_color or DEFAULT_COMPANY_THEME_COLOR
        )
        company_logo_filename = company.logo_filename
        company_logo_bytes = service.get_company_logo_bytes(
            current_user.company_id
        )
        company_status = "Active" if company.is_active else "Inactive"

    metric_columns = st.columns(3)

    with metric_columns[0]:
        st.metric("Tenant ID", current_user.company_id)

    with metric_columns[1]:
        st.metric("Status", company_status)

    with metric_columns[2]:
        st.metric("Company Code", company_code)

    pending_tab = st.session_state.pop("company_profile_pending_active_tab", None)
    company_tabs = {"Company Information", "Branding", "HR Contacts"}
    if pending_tab in company_tabs:
        st.session_state["company_profile_active_tab"] = pending_tab

    information_tab, branding_tab, hr_contacts_tab = persistent_tabs(
        ["Company Information", "Branding", "HR Contacts"],
        key="company_profile_active_tab",
    )

    with information_tab:
        _render_company_information_tab(
            current_user,
            company_code=company_code,
            company_name=company_name,
        )

    with branding_tab:
        _render_branding_sections(
            current_user,
            company_logo_filename=company_logo_filename,
            company_logo_bytes=company_logo_bytes,
            company_theme_color=company_theme_color,
        )

    with hr_contacts_tab:
        render_hr_contacts_management(current_user)
