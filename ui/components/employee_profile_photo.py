"""Reusable private employee profile-photo UI.

This component never exposes filesystem paths. It loads authorized image
bytes through the service layer and falls back to an initials avatar when no
photo is stored or a private file is unavailable.
"""

from __future__ import annotations

import base64
from html import escape

import streamlit as st

from authentication.current_user import AuthenticatedUser
from database.session import SessionFactory
from config.settings import get_settings
from services.employee_profile_image_service import EmployeeProfileImageService


def employee_initials(display_name: str | None, fallback: str = "U") -> str:
    """Return at most two readable initials for a default avatar."""

    parts = [part for part in str(display_name or "").strip().split() if part]
    if not parts:
        parts = [part for part in str(fallback or "U").strip().split() if part]
    if not parts:
        return "U"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return f"{parts[0][0]}{parts[-1][0]}".upper()


def load_profile_photo_bytes(
    *,
    current_user: AuthenticatedUser,
    employee_id: int | None,
) -> bytes | None:
    """Load a private image defensively after company/user authorization."""

    if employee_id is None:
        return None
    try:
        with SessionFactory() as session:
            return EmployeeProfileImageService(session).get_profile_image_bytes(
                company_id=current_user.company_id,
                employee_id=employee_id,
                actor_user_id=current_user.user_id,
                actor_clearance=current_user.clearance,
            )
    except Exception:
        return None


def profile_avatar_html(
    *,
    image_bytes: bytes | None,
    display_name: str | None,
    fallback: str = "U",
    css_class: str = "hr-profile-avatar",
) -> str:
    """Return safe HTML for a PNG data-URI avatar or initials placeholder."""

    accessible_name = escape(str(display_name or "Employee"), quote=True)
    safe_class = escape(css_class, quote=True)
    if image_bytes:
        encoded = base64.b64encode(image_bytes).decode("ascii")
        return (
            f'<span class="{safe_class}">'
            '<img src="data:image/png;base64,'
            f'{encoded}" alt="{accessible_name} profile photo">'
            "</span>"
        )

    initials = escape(employee_initials(display_name, fallback))
    return (
        f'<span class="{safe_class} hr-profile-avatar-initials" '
        f'aria-label="{accessible_name} profile avatar">{initials}</span>'
    )


def _render_large_avatar(
    *,
    image_bytes: bytes | None,
    display_name: str,
    fallback: str,
) -> None:
    """Render the current image/default avatar without exposing a file path."""

    if image_bytes:
        st.image(image_bytes, width=124)
        return

    initials = escape(employee_initials(display_name, fallback))
    safe_name = escape(display_name, quote=True)
    st.markdown(
        (
            '<div class="hr-profile-photo-large hr-profile-avatar-initials" '
            f'aria-label="{safe_name} default profile avatar">'
            f'{initials}</div>'
        ),
        unsafe_allow_html=True,
    )


def render_profile_photo_manager(
    *,
    current_user: AuthenticatedUser,
    employee_id: int,
    employee_display_name: str,
    employee_number: str | None,
    key_prefix: str,
    admin_mode: bool,
) -> None:
    """Render upload/replace/remove controls for an authorized employee photo."""

    feedback_key = f"_{key_prefix}_profile_photo_feedback"
    generation_key = f"_{key_prefix}_profile_photo_uploader_generation"
    generation = int(st.session_state.get(generation_key, 0))
    max_mb = max(1, int(get_settings().employee_profile_image_max_mb))

    feedback = st.session_state.pop(feedback_key, None)
    if isinstance(feedback, dict):
        message = str(feedback.get("message") or "").strip()
        if message:
            if feedback.get("level") == "error":
                st.error(message)
            else:
                st.success(message)

    image_bytes = load_profile_photo_bytes(
        current_user=current_user,
        employee_id=employee_id,
    )

    help_text = (
        f"JPG/JPEG/PNG only. Maximum file size: {max_mb} MB. "
        "The image is automatically centered/cropped and processed to 512×512 PNG. "
        "The file is validated by its actual image content before saving."
    )
    if admin_mode:
        help_text += (
            " Save Photo and Remove Photo are independent of the Employee Master "
            "form below; saving/removing a photo does not submit employee master changes."
        )

    with st.container(key=f"{key_prefix}_profile_photo_compact"):
        current_column, upload_column = st.columns(
            [0.85, 2.15],
            vertical_alignment="top",
        )
        with current_column:
            st.markdown("**Current Photo**" if image_bytes else "**Default Avatar**")
            _render_large_avatar(
                image_bytes=image_bytes,
                display_name=employee_display_name,
                fallback=employee_number or current_user.username,
            )

        with upload_column:
            uploaded_file = st.file_uploader(
                "Upload / Replace Photo",
                type=["jpg", "jpeg", "png"],
                accept_multiple_files=False,
                key=f"{key_prefix}_profile_photo_upload_{generation}",
                help=help_text,
            )

            prepared_preview: bytes | None = None
            preview_error: str | None = None
            if uploaded_file is not None:
                try:
                    if uploaded_file.size > max_mb * 1024 * 1024:
                        raise ValueError(
                            f"The profile photo must not exceed {max_mb} MB."
                        )
                    with SessionFactory() as session:
                        prepared_preview = EmployeeProfileImageService(
                            session
                        ).prepare_preview(
                            file_name=uploaded_file.name,
                            content=uploaded_file.getvalue(),
                            content_type=uploaded_file.type,
                        )
                    st.markdown("**New Photo Preview**")
                    st.image(prepared_preview, width=124)
                except ValueError as error:
                    preview_error = str(error)
                    st.error(preview_error)
                except Exception:
                    preview_error = "The selected profile photo could not be validated."
                    st.error(preview_error)

            save_column, remove_column = st.columns(2)
            with save_column:
                save_clicked = st.button(
                    "Save Photo",
                    type="primary",
                    width="stretch",
                    disabled=(
                        uploaded_file is None
                        or prepared_preview is None
                        or preview_error is not None
                    ),
                    key=f"{key_prefix}_profile_photo_save",
                )
            with remove_column:
                remove_clicked = st.button(
                    "Remove Photo",
                    width="stretch",
                    disabled=image_bytes is None,
                    key=f"{key_prefix}_profile_photo_remove",
                )

            if save_clicked and uploaded_file is not None and prepared_preview is not None:
                try:
                    with st.spinner("Saving profile photo…"):
                        with SessionFactory() as session:
                            EmployeeProfileImageService(session).save_profile_image(
                                company_id=current_user.company_id,
                                employee_id=employee_id,
                                actor_user_id=current_user.user_id,
                                actor_clearance=current_user.clearance,
                                file_name=uploaded_file.name,
                                content=uploaded_file.getvalue(),
                                content_type=uploaded_file.type,
                            )
                    st.session_state[feedback_key] = {
                        "message": (
                            f"Profile photo saved for {employee_display_name}."
                            if admin_mode
                            else "Your profile photo was saved successfully."
                        ),
                        "level": "success",
                    }
                    st.session_state[generation_key] = generation + 1
                    st.rerun()
                except (ValueError, PermissionError) as error:
                    st.error(str(error))
                except Exception:
                    st.error(
                        "The profile photo could not be saved. No database change was completed."
                    )

            if remove_clicked:
                try:
                    with st.spinner("Removing profile photo…"):
                        with SessionFactory() as session:
                            removed = EmployeeProfileImageService(session).remove_profile_image(
                                company_id=current_user.company_id,
                                employee_id=employee_id,
                                actor_user_id=current_user.user_id,
                                actor_clearance=current_user.clearance,
                            )
                    st.session_state[feedback_key] = {
                        "message": (
                            (
                                f"Profile photo removed for {employee_display_name}."
                                if admin_mode
                                else "Your profile photo was removed; the default initials avatar is active."
                            )
                            if removed
                            else "No stored profile photo was found."
                        ),
                        "level": "success",
                    }
                    st.session_state[generation_key] = generation + 1
                    st.rerun()
                except (ValueError, PermissionError) as error:
                    st.error(str(error))
                except Exception:
                    st.error(
                        "The profile photo could not be removed. No database change was completed."
                    )
