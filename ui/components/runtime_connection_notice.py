"""Streamlit presentation for safe runtime connection warnings."""

from __future__ import annotations

import streamlit as st

from services.runtime_connection_service import RuntimeConnectionIssue


def render_runtime_connection_notice(
    issue: RuntimeConnectionIssue,
    *,
    popup: bool = False,
) -> None:
    """Show an actionable warning without rendering exception details."""

    st.warning(f"**{issue.title}**\n\n{issue.message}")
    if popup:
        st.toast(f"{issue.title}: {issue.message}", icon="⚠️")
