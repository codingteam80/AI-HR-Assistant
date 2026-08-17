"""Application-wide deprecated component HTML regression checks."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_all_ui_python_uses_supported_iframe_bridge() -> None:
    for path in (ROOT / "ui").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "components.html(" not in source, path
        assert "st.components.v1.html(" not in source, path


def test_view_and_attendance_helpers_use_shared_bridge() -> None:
    view_source = (
        ROOT / "ui/components/view_state_preservation.py"
    ).read_text(encoding="utf-8")
    attendance_source = (
        ROOT / "ui/pages/user/attendance_workspace.py"
    ).read_text(encoding="utf-8")
    for source in (view_source, attendance_source):
        assert "from ui.components.browser_bridge import render_browser_bridge" in source
        assert "render_browser_bridge(" in source


def test_shared_bridge_uses_current_streamlit_iframe_api() -> None:
    source = (ROOT / "ui/components/browser_bridge.py").read_text(
        encoding="utf-8"
    )
    assert "st.iframe(" in source
    assert "width=1" in source
    assert "height=1" in source
    assert "tab_index=-1" in source
