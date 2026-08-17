"""Safe announcement description rendering with preserved line breaks."""

from html import escape


def build_announcement_description_html(content: str | None) -> str:
    """Return safe HTML that preserves entered lines and wraps long text."""

    safe_content = escape(str(content or ""))
    return (
        '<div class="announcement-description-content">'
        f"{safe_content}"
        "</div>"
        "<style>"
        ".announcement-description-content {"
        "white-space: pre-wrap;"
        "width: 100%;"
        "max-width: 100%;"
        "overflow-x: hidden;"
        "overflow-y: visible;"
        "overflow-wrap: anywhere;"
        "word-break: break-word;"
        "line-height: 1.55;"
        "color: var(--hr-text-primary);"
        "font-family: inherit;"
        "background: transparent;"
        "}"
        "</style>"
    )


def render_announcement_description(content: str | None) -> None:
    """Render description text exactly as entered inside its parent box."""

    import streamlit as st

    st.markdown(
        build_announcement_description_html(content),
        unsafe_allow_html=True,
    )
