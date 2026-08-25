"""v8.8.175 sidebar button radius regression checks."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_sidebar_buttons_use_20px_radius() -> None:
    theme = _read("ui/theme/theme_loader.py")
    scoped_rule = 'section[data-testid="stSidebar"] div.stButton > button'
    assert scoped_rule in theme
    start = theme.index(scoped_rule)
    block = theme[start:start + 420]
    assert "border-radius: 20px !important;" in block


def test_sidebar_radius_change_is_scoped_not_global_primary_button_change() -> None:
    theme = _read("ui/theme/theme_loader.py")
    # Existing global button radii remain untouched; the 20px override is scoped
    # to the sidebar so forms/content buttons retain their established styling.
    assert "div.stButton > button {{" in theme
    assert "border-radius: 12px;" in theme
    assert 'button[kind="primary"],' in theme
    assert "border-radius: 10px !important;" in theme


def test_v88175_version_sources() -> None:
    assert "APP_VERSION=0.8.8.175" in _read(".env")
    assert "APP_VERSION=0.8.8.175" in _read(".env.example")
    assert 'app_version: str = "0.8.8.175"' in _read("config/settings.py")
