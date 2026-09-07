"""Focused static regressions for the v8.8.207 scoped UI update."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_policy_permanent_delete_uses_selected_target_and_checkbox_only() -> None:
    source = _read("ui/pages/admin/policies_page.py")
    block = source.split(
        "def _render_permanent_delete(", 1
    )[1].split(
        "def _render_policy_library(", 1
    )[0]

    assert "Selected target:" in block
    assert "st.checkbox(" in block
    assert "I understand that this policy version and its file" in block
    assert "confirmation_public_id=public_id" in block
    assert "Type the exact Policy ID to confirm" not in block
    assert "st.text_input(" not in block
    assert "disabled=not acknowledged" in block


def test_admin_and_employee_chat_are_fixed_height_scroll_containers() -> None:
    for relative_path in [
        "ui/pages/admin/chat_page.py",
        "ui/pages/user/chat_page.py",
    ]:
        source = _read(relative_path)
        assert "CHAT_CONVERSATION_HEIGHT = 500" in source
        assert "conversation_area = st.container(" in source
        assert "height=CHAT_CONVERSATION_HEIGHT" in source
        assert "border=True" in source
        assert "st.chat_input(" in source


def test_email_and_smtp_inputs_are_arranged_in_rows() -> None:
    source = _read("ui/pages/admin/integrations_page.py")

    assert 'email_columns = st.columns([1.25, 0.95, 1.1], gap="small")' in source
    assert "with email_columns[0]:" in source
    assert "with email_columns[1]:" in source
    assert "with email_columns[2]:" in source
    assert 'smtp_columns = st.columns([1.5, 0.6, 0.9], gap="small")' in source
    assert "with smtp_columns[0]:" in source
    assert "with smtp_columns[1]:" in source
    assert "with smtp_columns[2]:" in source


def test_sms_inputs_are_three_then_two_columns() -> None:
    source = _read("ui/pages/admin/integrations_page.py")

    assert 'sms_primary_columns = st.columns(3, gap="small")' in source
    assert "with sms_primary_columns[0]:" in source
    assert "with sms_primary_columns[1]:" in source
    assert "with sms_primary_columns[2]:" in source
    assert 'sms_secondary_columns = st.columns(2, gap="small")' in source
    assert "with sms_secondary_columns[0]:" in source
    assert "with sms_secondary_columns[1]:" in source


def test_policy_uploader_is_multi_file_and_per_file_transactional() -> None:
    source = _read("ui/pages/admin/policies_page.py")
    block = source.split(
        "def _render_upload(", 1
    )[1].split(
        "def _render_edit_policy_details(", 1
    )[0]

    assert "accept_multiple_files=True" in block
    assert "for file_index, uploaded in enumerate(uploaded_files" in block
    assert "for item in prepared:" in block
    assert "with SessionFactory() as session:" in block
    assert "create_policy_from_upload(" in block
    assert "successes.append(" in block
    assert "failures.append(" in block
    assert "one invalid" in block


def test_version_marker_is_207() -> None:
    assert 'app_version: str = "0.8.8.207"' in _read("config/settings.py")
    assert "APP_VERSION=0.8.8.207" in _read(".env")
    assert "APP_VERSION=0.8.8.207" in _read(".env.example")
