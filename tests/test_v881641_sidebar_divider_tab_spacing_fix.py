"""Regression checks for v8.8.164.1 sidebar divider/tab spacing patch."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_admin_sidebar_keeps_visible_custom_separator() -> None:
    source = _read("ui/components/admin_sidebar.py")
    theme = _read("ui/theme/theme_loader.py")

    assert "hr-admin-account-divider" in source
    assert "st.sidebar.divider()" not in source
    assert '"Audit Trail"' in source
    assert '"Employee Portal"' in source

    block = theme.split(".hr-admin-account-divider {{", 1)[1].split("}}", 1)[0]
    assert "height: 1px" in block
    assert "background: var(--hr-border)" in block
    assert "box-shadow:" in block
    assert "var(--hr-text-muted)" in block
    assert "opacity: 0.52" in block


def test_divider_wrapper_offsets_half_sidebar_gap_on_each_side() -> None:
    theme = _read("ui/theme/theme_loader.py")

    assert ':has(.hr-admin-account-divider)' in theme
    assert "margin-top: -0.275rem !important" in theme
    assert "margin-bottom: -0.275rem !important" in theme
    assert "gap: 0.55rem !important" in theme


def test_patch_version_is_distinct_from_held_next_branch() -> None:
    settings = _read("config/settings.py")
    env_example = _read(".env.example")
    readme = _read("README.md")

    assert 'app_version: str = "0.8.8.164.' in settings
    assert "APP_VERSION=0.8.8.164." in env_example
    assert "v8.8.164.1" not in readme
