"""v8.8.67 Company Form/Documents navigation regression tests."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_company_forms_documents_replaces_audit_logs_in_sidebar() -> None:
    source = _read("ui/components/admin_sidebar.py")
    navigation = source.split("ADMIN_NAVIGATION =", 1)[1].split(
        "def render_admin_sidebar", 1
    )[0]

    assert '"Company Form/Documents"' in navigation
    assert '"Audit Logs"' not in navigation


def test_company_forms_documents_is_after_announcements_in_current_sidebar() -> None:
    source = _read("ui/components/admin_sidebar.py")
    navigation = source.split("ADMIN_NAVIGATION =", 1)[1].split(
        "def render_admin_sidebar", 1
    )[0]

    reports = navigation.index('"Reports"')
    announcements = navigation.index('"Announcements"')
    company_documents = navigation.index('"Company Form/Documents"')
    policies = navigation.index('"Policies"')

    assert reports < announcements < company_documents < policies


def test_company_forms_documents_has_dedicated_admin_route() -> None:
    layout = _read("ui/layouts/admin_layout.py")
    page = _read("ui/pages/admin/company_forms_documents_page.py")

    assert 'page == "Company Form/Documents"' in layout
    assert "render_company_forms_documents_page" in layout
    assert 'st.title("Company Form/Documents")' in page


def test_legacy_audit_logs_bookmark_redirects_to_new_workspace() -> None:
    sidebar = _read("ui/components/admin_sidebar.py")

    assert 'current_page == "Audit Logs"' in sidebar
    assert 'current_page="Audit Trail"' in sidebar


def test_release_history_is_not_kept_as_root_release_files() -> None:
    assert not list(PROJECT_ROOT.glob("RELEASE_*.md"))
