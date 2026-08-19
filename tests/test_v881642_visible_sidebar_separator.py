"""Regression checks for v8.8.164.2 visible sidebar separator fix."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_admin_sidebar_uses_actual_hr_separator() -> None:
    source = _read("ui/components/admin_sidebar.py")
    assert "<hr class='hr-admin-account-divider'" in source
    assert "st.sidebar.divider()" not in source
    assert '"Audit Trail"' in source
    assert '"Employee Portal"' in source


def test_separator_is_visibly_drawn_not_only_spaced() -> None:
    theme = _read("ui/theme/theme_loader.py")
    block = theme.split(".hr-admin-account-divider {{", 1)[1].split("}}", 1)[0]
    assert "height: 1px" in block
    assert "min-height: 1px" in block
    assert "margin: 0" in block
    assert "background: var(--hr-border)" in block
    assert "border-top: 1px solid rgba(100, 116, 139, 0.88)" in block
    assert "opacity: 0.52" in block


def test_separator_spacing_is_compact_but_not_collapsed() -> None:
    theme = _read("ui/theme/theme_loader.py")
    assert ":has(.hr-admin-account-divider)" in theme
    assert "margin-top: -0.275rem !important" in theme
    assert "margin-bottom: -0.275rem !important" in theme
    assert "gap: 0.55rem !important" in theme


def test_patch_version_is_164_2() -> None:
    settings = _read("config/settings.py")
    env_example = _read(".env.example")
    assert 'app_version: str = "0.8.8.164.' in settings
    assert "APP_VERSION=0.8.8.164." in env_example
