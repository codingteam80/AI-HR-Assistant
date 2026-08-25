"""v8.8.190 compact fixed-banner flow-spacing regression checks."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def _source(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")

def test_version_bumped():
    assert 'app_version: str = "0.8.8.190"' in _source("config/settings.py")
    assert "APP_VERSION=0.8.8.190" in _source(".env")
    assert "APP_VERSION=0.8.8.190" in _source(".env.example")

def test_desktop_spacer_reduced_only():
    theme = _source("ui/theme/theme_loader.py")
    start = theme.index(".hr-topbar-flow-spacer {{")
    block = theme[start:theme.index("}}", start)]
    assert "height: 3.00rem !important;" in block
    assert "min-height: 3.00rem !important;" in block
    assert "6.25rem" not in block

def test_responsive_spacers_reduced():
    theme = _source("ui/theme/theme_loader.py")
    assert "height: 2.75rem !important;" in theme
    assert "min-height: 2.75rem !important;" in theme
    assert "height: 2.50rem !important;" in theme
    assert "min-height: 2.50rem !important;" in theme

def test_fixed_banner_cover_and_border_fix_preserved():
    theme = _source("ui/theme/theme_loader.py")
    start = theme.index(".st-key-hr_global_topbar_shell,")
    block = theme[start:theme.index("}}", start)]
    assert "position: fixed !important;" in block
    assert "top: 0 !important;" in block
    assert "border-bottom: 0 !important;" in block
    assert "padding: 2.5rem var(--hr-topbar-inline-gutter) 8px !important;" in block

def test_original_card_visuals_preserved():
    theme = _source("ui/theme/theme_loader.py")
    start = theme.index("    .hr-topbar {{", theme.index("Keep the original v8.8.186 card appearance untouched."))
    block = theme[start:theme.index("}}", start)]
    for token in [
        "padding: 14px 18px;",
        "border: 1px solid var(--hr-border);",
        "border-radius: 18px;",
        "box-shadow: var(--hr-shadow);",
    ]:
        assert token in block
    topbar = _source("ui/components/topbar.py")
    assert "[9.1, 0.9]" in topbar
