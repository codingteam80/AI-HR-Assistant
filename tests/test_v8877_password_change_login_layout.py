"""Regression tests for v8.8.77 password-change/login layout alignment."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_password_change_reuses_login_page_composition() -> None:
    source = _read("ui/pages/authentication/change_password_page.py")

    assert "_render_login_page_styles()" in source
    assert 'class="hr-login-hero"' in source
    assert 'class="hr-login-title">Change Your Password' in source
    assert 'class="hr-login-subtitle"' in source
    assert 'class="hr-login-card-heading">Account Security' in source
    assert "hr-password-change-note" in source
    assert "justify-content: center !important" in source
    assert "Replace it with a password only you know." in source
    assert 'class="hr-login-card-copy"' not in source


def test_login_composition_is_centered_in_the_viewport() -> None:
    source = _read("ui/pages/authentication/login_page.py")

    assert "min-height: 100vh !important" in source
    assert "display: flex !important" in source
    assert "flex-direction: column !important" in source
    assert "justify-content: center !important" in source
    assert (
        "transform: translateY(clamp(-52px, -5vh, -36px)) !important"
        in source
    )
    assert "@media (max-height: 760px)" in source


def test_password_change_layout_does_not_render_auth_sidebar() -> None:
    source = _read("ui/layouts/auth_layout.py")
    block = source.split(
        "def render_password_change_layout",
        1,
    )[1].split(
        "def render_forgot_password_layout",
        1,
    )[0]

    assert "render_auth_sidebar(" not in block
    assert "render_change_password_page(current_user)" in block


def test_password_change_fields_and_submit_behavior_are_preserved() -> None:
    source = _read("ui/pages/authentication/change_password_page.py")

    assert '"Current Password"' in source
    assert '"New Password"' in source
    assert '"Confirm New Password"' in source
    assert '"Update Password"' in source
    assert "AuthService(" in source
    assert ".change_password(" in source
    assert "AuthSessionManager.complete_password_change(" in source
