"""v8.8.209 visible-loading removal and rerun-background continuity checks."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_global_processing_pill_and_labels_are_removed() -> None:
    source = _read("ui/theme/theme_loader.py")
    forbidden = [
        "ai-hr-processing-spinner",
        "ai-hr-processing-label",
        "Signing in…",
        "Signing out…",
        "Creating…",
        "Updating…",
        "Deleting…",
        "Restoring…",
        "Loading…",
    ]
    for value in forbidden:
        assert value not in source
    assert 'getElementById(\n                "ai-hr-global-processing"' in source
    assert 'processing.innerHTML' not in source
    assert 'body.appendChild(processing)' not in source


def test_login_and_logout_do_not_add_visible_spinners() -> None:
    assert 'with st.spinner("Signing in…"):' not in _read(
        "ui/pages/authentication/login_page.py"
    )
    assert 'with st.spinner("Signing out…"):' not in _read(
        "ui/components/sidebar.py"
    )
    assert 'with st.spinner("Signing out…"):' not in _read(
        "ui/components/admin_sidebar.py"
    )


def test_rerun_shell_persists_computed_portal_artwork() -> None:
    source = _read("ui/theme/theme_loader.py")
    required = [
        "parentWindow.getComputedStyle(appView)",
        "computedView?.backgroundImage",
        "computedView?.backgroundSize",
        "computedView?.backgroundPosition",
        "computedView?.backgroundRepeat",
        "computedView?.backgroundAttachment",
        'parentDocument.getElementById("root")',
        'surface.style.setProperty(',
        '"background-image"',
        '[data-testid="stMainBlockContainer"]',
        "background-color: transparent !important",
    ]
    for value in required:
        assert value in source


def test_url_cleanup_and_streamlit_chrome_hiding_are_retained() -> None:
    source = _read("ui/theme/theme_loader.py")
    assert 'currentUrl.searchParams.delete("theme")' in source
    assert "parentWindow.history.replaceState" in source
    assert '[data-testid="stToolbar"]' in source
    assert '[data-testid="stStatusWidget"]' in source


def test_duplicate_click_safety_is_non_visual() -> None:
    source = _read("ui/theme/theme_loader.py")
    assert "__aiHrRapidActionGuardInstalled" in source
    assert "WeakMap" in source
    assert "event.stopImmediatePropagation()" in source
    assert 'button.style.setProperty("pointer-events", "none"' not in source


def test_version_is_209() -> None:
    settings = _read("config/settings.py")
    assert 'app_version: str = "0.8.8.209"' in settings
