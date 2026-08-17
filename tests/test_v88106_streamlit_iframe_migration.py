"""Regression checks for the Streamlit 1.61 iframe migration."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACTIVE_BRIDGE_FILES = (
    "ui/theme/theme_loader.py",
    "ui/auth_persistence.py",
    "ui/components/file_preview.py",
    "ui/pages/admin/leave_management_page.py",
    "ui/pages/user/leave_management_page.py",
)


def _source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_active_code_no_longer_uses_deprecated_v1_html() -> None:
    active_files = {
        ROOT / relative_path for relative_path in ACTIVE_BRIDGE_FILES
    }
    active_files.update((ROOT / "ui").rglob("*.py"))
    for path in sorted(active_files):
        source = path.read_text(encoding="utf-8")
        assert "streamlit.components.v1" not in source
        assert "components.html(" not in source


def test_supported_iframe_bridge_preserves_zero_space_layout() -> None:
    source = _source("ui/components/browser_bridge.py")
    assert "st.iframe(" in source
    assert "width=1" in source
    assert "height=1" in source
    assert "tab_index=-1" in source
    assert "stElementContainer" in source
    assert "setProperty('display', 'none', 'important')" in source


def test_existing_browser_behaviors_use_the_shared_bridge() -> None:
    theme = _source("ui/theme/theme_loader.py")
    assert theme.count("render_browser_bridge(script)") == 3
    assert "render_browser_bridge(script)" in _source("ui/auth_persistence.py")
    assert "render_browser_bridge(component)" in _source(
        "ui/components/file_preview.py"
    )
    assert "render_browser_bridge(script)" in _source(
        "ui/pages/admin/leave_management_page.py"
    )
    assert "render_browser_bridge(script)" in _source(
        "ui/pages/user/leave_management_page.py"
    )


def test_checkpoint_version_retains_v88106_compatibility() -> None:
    settings = _source("config/settings.py")
    assert 'app_version: str = "0.8.8.' in settings
