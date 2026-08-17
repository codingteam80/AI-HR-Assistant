"""Regression checks for v8.8.113 native tabs and description boxes."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_dashboard_uses_the_same_native_tabs_as_leave_management() -> None:
    dashboard = _source("ui/pages/user/dashboard_page.py")
    leave_page = _source("ui/pages/user/leave_management_page.py")

    assert "st.segmented_control(" not in dashboard
    assert "return st.tabs(" in dashboard
    assert "tabs = st.tabs(" in leave_page
    assert 'key="employee_leave_management_active_tab"' in leave_page
    assert 'on_change="rerun"' in dashboard
    assert "dashboard_tab.open" in dashboard
    assert "announcements_tab.open" in dashboard


def test_native_announcement_tab_keeps_count_and_unread_shake() -> None:
    dashboard = _source("ui/pages/user/dashboard_page.py")

    assert 'content: " ({unread_count})"' in dashboard
    assert "employeeAnnouncementTabShake" in dashboard
    assert '[data-baseweb="tab-list"] [role="tab"]:nth-child(2)' in dashboard
    assert "prefers-reduced-motion" in dashboard


def test_employee_description_is_always_visible_in_fixed_box() -> None:
    source = _source("ui/pages/user/announcements_page.py")
    card = source.split("def render_announcement_card(", 1)[1].split(
        "def render_employee_announcements_page(", 1
    )[0]

    assert "st.expander(" not in card
    assert 'st.markdown("**Description**")' not in card
    assert "render_announcement_description(" in card
    assert "with st.container(" in card
    assert "border=False" in card
    assert "height=330" in card


def test_admin_description_matches_employee_fixed_box() -> None:
    source = _source("ui/pages/admin/announcements_page.py")
    preview = source.split("def _render_preview(", 1)[1].split(
        "def _selected_index(", 1
    )[0]

    assert "st.expander(" not in preview
    assert 'st.markdown("**Description**")' not in preview
    assert "render_announcement_description(" in preview
    assert "border=False" in preview
    assert "height=330" in preview


def test_checkpoint_keeps_v88113_release_notes() -> None:
    settings = _source("config/settings.py")
    readme = _source("README.md")

    assert 'app_version: str = "0.8.8.' in settings
    assert (
        "v8.8.113 — Native Dashboard Tabs and Fixed Description Panels"
        in readme
    )
