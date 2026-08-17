"""Regression checks for v8.8.96 exact native preview-title centering."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source() -> str:
    return (ROOT / "ui/components/file_preview.py").read_text(encoding="utf-8")


def test_streamlit_native_title_is_preserved_without_overrides() -> None:
    source = _source()

    assert '@st.dialog(' in source
    assert '"File Preview"' in source
    assert '[slot="title"]' not in source
    assert '[data-testid="stDialog"] h2' not in source


def test_matching_native_preview_actions_are_preserved() -> None:
    source = _source()
    actions = source.split(
        "print_column, download_column = st.columns(2)",
        1,
    )[1]

    assert 'print_requested = st.button(' in actions
    assert 'st.download_button(' in actions
    assert actions.count('type="secondary"') >= 2


def test_checkpoint_version_is_v8896() -> None:
    settings = (ROOT / "config/settings.py").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert 'app_version: str = "0.8.8.' in settings
    assert "v8.8.96 — Exact Native Preview Title Centering" in readme
