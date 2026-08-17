"""Regression checks for personal employee reports and default FAQs."""

from datetime import date
from pathlib import Path

from ui.pages.user.faq_page import DEFAULT_FAQS


ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_employee_reports_are_in_navigation_and_routed() -> None:
    constants = _source("core/constants.py")
    layout = _source("ui/layouts/user_layout.py")
    assert (
        '"Company Policies",\n    "Reports",\n    "Benefits"'
        in constants
    )
    assert 'current_page == "Reports"' in layout
    assert "render_employee_reports_page(current_user)" in layout


def test_personal_report_is_strictly_scoped_to_signed_in_employee() -> None:
    page = _source("ui/pages/user/reports_page.py")
    assert "current_user.employee_id is None" in page
    assert "employee_ids = [employee.id]" in page
    assert "employees=[employee]" in page
    assert "LeaveRequestRepository(session).list_employee(" in page
    assert "employee_ids=employee_ids" in page
    assert "st.selectbox(" not in page
    assert "DTR Logs" in page
    assert "Overtime File" in page
    assert "Leave File" in page


def test_personal_report_period_guard_accepts_only_bounded_ranges() -> None:
    from ui.pages.user.reports_page import _validated_report_period

    assert _validated_report_period((date(2026, 1, 1), date(2026, 12, 31))) == (
        date(2026, 1, 1),
        date(2026, 12, 31),
    )


def test_default_faqs_have_direct_answers_and_useful_links() -> None:
    assert len(DEFAULT_FAQS) >= 10
    assert all(item.question.strip() for item in DEFAULT_FAQS)
    assert all(item.answer.strip() for item in DEFAULT_FAQS)
    assert all(item.link_label and item.page for item in DEFAULT_FAQS)

    destinations = {
        (item.page, tuple(sorted(item.query_params.items())))
        for item in DEFAULT_FAQS
    }
    assert ("Leave Management", (("leave_view", "file"),)) in destinations
    assert ("Leave Management", (("leave_view", "requests"),)) in destinations
    assert (
        "Company Form/Documents",
        (("form_view", "download"),),
    ) in destinations
    assert ("Dashboard", (("dashboard_view", "announcements"),)) in destinations
    assert ("Reports", ()) in destinations


def test_faq_page_replaces_placeholder_and_preserves_exact_navigation() -> None:
    layout = _source("ui/layouts/user_layout.py")
    page = _source("ui/pages/user/faq_page.py")
    assert 'current_page == "FAQ"' in layout
    assert "render_employee_faq_page(current_user)" in layout
    assert "prime_exact_module_view(" in page
    assert "set_navigation_state(" in page
    assert "EXACT_VIEW_QUERY_KEYS" in page


def test_v88151_version_notes_and_warning_safe_new_pages() -> None:
    settings = _source("config/settings.py")
    readme = _source("README.md")
    combined = _source("ui/pages/user/reports_page.py") + _source(
        "ui/pages/user/faq_page.py"
    )
    assert 'app_version: str = "0.8.8.152"' in settings
    assert "Immediate base checkpoint: app_version: str = \"0.8.8.151\"" in settings
    assert "v8.8.151 — Employee Personal Reports and Default FAQ" in readme
    assert "use_container_width" not in combined
    assert "components.v1.html" not in combined
