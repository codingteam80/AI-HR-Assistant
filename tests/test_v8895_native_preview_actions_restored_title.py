"""Regression checks for v8.8.95 native preview actions/restored title."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source() -> str:
    return (ROOT / "ui/components/file_preview.py").read_text(encoding="utf-8")


def test_title_uses_streamlit_native_normal_flow() -> None:
    source = _source()

    assert '@st.dialog(' in source
    assert '"File Preview"' in source
    assert '[slot="title"]' not in source
    assert "centerPreviewTitle" not in source


def test_print_and_download_are_matching_native_secondary_actions() -> None:
    source = _source()
    action_source = source.split(
        "print_column, download_column = st.columns(2)",
        1,
    )[1]

    assert 'print_requested = st.button(' in action_source
    assert '"Print Form"' in action_source
    assert 'st.download_button(' in action_source
    assert '"Download File"' in action_source
    assert action_source.count('type="secondary"') >= 2
    assert "_render_print_button" not in source
    assert "matchDownloadStyle" not in source


def test_native_print_button_launches_hidden_print_component() -> None:
    source = _source()

    assert "if print_requested:" in source
    assert "_launch_print_dialog(print_payload)" in source
    assert "render_browser_bridge(component)" in source
    assert "frame.contentWindow.print()" in source


def test_checkpoint_version_is_v8895() -> None:
    settings = (ROOT / "config/settings.py").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert 'app_version: str = "0.8.8.' in settings
    assert "v8.8.95 — Native Preview Actions and Restored Title" in readme
