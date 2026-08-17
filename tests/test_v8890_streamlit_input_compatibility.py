"""Regression checks for v8.8.90 Streamlit input style compatibility."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_streamlit_161_controls_restore_dark_surfaces_globally() -> None:
    source = (ROOT / "ui/theme/theme_loader.py").read_text(encoding="utf-8")
    block = source.split(
        "STREAMLIT 1.61 INPUT SURFACE COMPATIBILITY — v8.8.90",
        1,
    )[1].split(
        "NATIVE-LOOK PERSISTENT ADMIN TABS — v8.8.85",
        1,
    )[0]

    assert '[data-testid="stTextInput"] input' in block
    assert '[data-testid="stNumberInput"] input' in block
    assert '[data-testid="stDateInput"] input' in block
    assert '[data-testid="stTimeInput"] input' in block
    assert '[data-testid="stTextArea"] textarea' in block
    assert '[data-testid="stSelectbox"] [role="combobox"]' in block
    assert '[data-testid="stMultiSelect"] [role="combobox"]' in block
    assert "div:has(> input)" in block
    assert "div:has(> textarea)" in block
    assert "background: #252630 !important" in block
    assert "-webkit-text-fill-color: #FFFFFF !important" in block
    assert ":disabled" in block
    assert ":focus-within" in block
