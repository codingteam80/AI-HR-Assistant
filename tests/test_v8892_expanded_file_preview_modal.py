"""Regression checks for v8.8.92 expanded File Preview modal."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source() -> str:
    return (ROOT / "ui/components/file_preview.py").read_text(encoding="utf-8")


def test_preview_modal_uses_balanced_viewport_height() -> None:
    source = _source()

    assert "_PREVIEW_CONTENT_HEIGHT = 600" in source
    assert "_PREVIEW_WIDGET_HEIGHT = 560" in source
    assert "height: calc(100dvh - 96px) !important" in source
    assert "calc(100dvh - 344px)" in source


def test_preview_title_is_native_and_redundant_caption_is_removed() -> None:
    source = _source()

    assert '@st.dialog(' in source
    assert '"File Preview"' in source
    assert '[slot="title"]' not in source
    assert "Preview only. The stored company file is not modified." not in source


def test_preview_actions_use_two_compact_columns() -> None:
    source = _source()

    assert "print_column, download_column = st.columns(2)" in source
    assert "with print_column:" in source
    assert "with download_column:" in source
    assert '"Download File"' in source


def test_checkpoint_version_is_v8892() -> None:
    settings = (ROOT / "config/settings.py").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert 'app_version: str = "0.8.8.' in settings
    assert "v8.8.92 — Expanded File Preview Modal" in readme
