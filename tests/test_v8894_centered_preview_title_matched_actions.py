"""Regression checks for v8.8.94 preview title and action styling."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source() -> str:
    return (ROOT / "ui/components/file_preview.py").read_text(encoding="utf-8")


def test_actual_file_preview_heading_uses_native_layout() -> None:
    source = _source()

    assert '@st.dialog(' in source
    assert '"File Preview"' in source
    assert '[slot="title"]' not in source
    assert "centerPreviewTitle" not in source


def test_print_form_and_download_share_native_button_style() -> None:
    source = _source()

    assert 'print_requested = st.button(' in source
    assert 'st.download_button(' in source
    assert source.count('type="secondary"') >= 2


def test_checkpoint_version_is_v8894() -> None:
    settings = (ROOT / "config/settings.py").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert 'app_version: str = "0.8.8.' in settings
    assert "v8.8.94 — Centered Preview Title and Matched Actions" in readme
