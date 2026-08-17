"""Regression checks for v8.8.93 functional Company Form printing."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source() -> str:
    return (ROOT / "ui/components/file_preview.py").read_text(encoding="utf-8")


def test_print_form_precedes_download_file() -> None:
    source = _source()

    columns = "print_column, download_column = st.columns(2)"
    assert columns in source
    action_source = source.split(columns, 1)[1]
    assert action_source.index("with print_column:") < action_source.index(
        "with download_column:"
    )
    assert "Print Form" in source
    assert '"Download File"' in action_source


def test_pdf_print_uses_authorized_bytes_and_native_browser_print() -> None:
    source = _source()

    assert "base64.b64encode(data)" in source
    assert '"mode": "pdf"' in source
    assert "new Blob([bytes]" in source
    assert "frame.contentWindow.print()" in source
    assert "render_browser_bridge(component)" in source


def test_printable_preview_types_are_supported() -> None:
    source = _source()

    assert 'extension == ".docx"' in source
    assert 'extension == ".xlsx"' in source
    assert 'extension == ".csv"' in source
    assert 'extension == ".txt"' in source
    assert "mime_type.startswith(\"image/\")" in source
    assert 'return {"mode": "unsupported"}' in source


def test_checkpoint_version_is_v8893() -> None:
    settings = (ROOT / "config/settings.py").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert 'app_version: str = "0.8.8.' in settings
    assert "v8.8.93 — Functional Company Form Printing" in readme
