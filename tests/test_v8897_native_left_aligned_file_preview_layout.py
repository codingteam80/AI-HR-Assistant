"""Regression checks for v8.8.97 native left-aligned preview layout."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source() -> str:
    return (ROOT / "ui/components/file_preview.py").read_text(encoding="utf-8")


def test_preview_title_uses_unmodified_native_dialog_layout() -> None:
    source = _source()

    assert '@st.dialog(' in source
    assert '"File Preview"' in source
    assert 'dismissible=True' in source
    assert '[slot="title"]' not in source
    assert '[data-testid="stDialog"] h2' not in source
    assert "centerPreviewTitle" not in source


def test_reference_preview_structure_and_actions_are_preserved() -> None:
    source = _source()

    assert "st.subheader(filename)" in source
    assert 'key="company_file_preview_content"' in source
    actions = source.split(
        "print_column, download_column = st.columns(2)",
        1,
    )[1]
    assert '"Print Form"' in actions
    assert '"Download File"' in actions
    assert actions.count('type="secondary"') >= 2


def test_checkpoint_version_is_v8897() -> None:
    settings = (ROOT / "config/settings.py").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert 'app_version: str = "0.8.8.' in settings
    assert "v8.8.97 — Native Left-Aligned File Preview Layout" in readme
