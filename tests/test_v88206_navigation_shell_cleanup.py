"""v8.8.206 rerun-shell and Streamlit viewer-chrome regression checks."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_persistent_shell_style_survives_streamlit_reruns() -> None:
    source = _source("ui/theme/theme_loader.py")

    assert "ai-hr-persistent-streamlit-shell" in source
    assert "parentDocument.head.appendChild(shellStyle);" in source
    assert 'parentDocument.documentElement.style.setProperty(' in source
    assert '.replace("__BACKGROUND__", background_color)' in source
    assert 'tokens["background"]' in source


def test_streamlit_viewer_toolbar_is_hidden_without_hiding_header_shell() -> None:
    source = _source("ui/theme/theme_loader.py")

    for selector in [
        '#MainMenu',
        '[data-testid=\"stToolbar\"]',
        '[data-testid=\"stHeaderActionElements\"]',
        '[data-testid=\"stStatusWidget\"]',
    ]:
        assert selector in source

    header_block = source.split('[data-testid="stHeader"] {{', 1)[1].split('}}', 1)[0]
    assert "display: none" not in header_block
    assert "background: transparent" in header_block


def test_existing_browser_bridge_count_is_preserved() -> None:
    source = _source("ui/theme/theme_loader.py")
    assert source.count("render_browser_bridge(script)") == 3


def test_existing_streamlit_toolbar_mode_is_not_changed() -> None:
    config = _source(".streamlit/config.toml")
    assert 'toolbarMode = "viewer"' in config


def test_v88206_version_markers_are_current() -> None:
    assert 'app_version: str = "0.8.8.206"' in _source("config/settings.py")
    assert "APP_VERSION=0.8.8.206" in _source(".env")
    assert "APP_VERSION=0.8.8.206" in _source(".env.example")
