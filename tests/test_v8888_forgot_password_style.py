"""Regression checks for v8.8.88 Forgot Password style restoration."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_forgot_password_button_uses_stable_scoped_styling() -> None:
    source = (
        ROOT / "ui/pages/authentication/login_page.py"
    ).read_text(encoding="utf-8")

    assert 'key="login_forgot_password_button"' in source
    assert ".st-key-login_forgot_password_button button" in source
    assert 'div[class*="st-key-login_forgot_password_button"] button' in source
    assert "background: transparent !important" in source
    assert "color: #53637d !important" in source
    assert "border: 0 !important" in source
