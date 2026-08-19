"""Regression checks for compact Admin sidebar separator spacing."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_admin_sidebar_uses_compact_custom_account_divider() -> None:
    source = _read("ui/components/admin_sidebar.py")

    assert "hr-admin-account-divider" in source
    assert "st.sidebar.divider()" not in source
    assert '"Employee Portal"' in source
    assert '"Audit Trail"' in source


def test_compact_divider_has_no_extra_vertical_margin() -> None:
    theme = _read("ui/theme/theme_loader.py")
    block = theme.split(".hr-admin-account-divider {{", 1)[1].split("}}", 1)[0]

    assert "height: 1px" in block
    assert "min-height: 1px" in block
    assert "margin: 0" in block
    assert "padding: 0" in block
    assert "background: var(--hr-border)" in block


def test_existing_sidebar_vertical_gap_is_preserved() -> None:
    theme = _read("ui/theme/theme_loader.py")
    block = theme.split(
        '[data-testid="stSidebarUserContent"] [data-testid="stVerticalBlock"] {{',
        1,
    )[1].split("}}", 1)[0]

    assert "gap: 0.55rem !important" in block


def test_version_is_incremented_without_touching_readme_release_history() -> None:
    settings = _read("config/settings.py")
    env_example = _read(".env.example")
    readme = _read("README.md")

    assert 'app_version: str = "0.8.8.164.' in settings
    assert "APP_VERSION=0.8.8.164." in env_example
    assert "v8.8.164" not in readme
