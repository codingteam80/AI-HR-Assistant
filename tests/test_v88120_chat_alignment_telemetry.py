"""Chat layout, input contrast, and Chroma telemetry regression checks."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_user_questions_are_right_aligned_in_both_shared_chat_views() -> None:
    theme = _source("ui/theme/theme_loader.py")
    admin = _source("ui/pages/admin/chat_page.py")
    employee = _source("ui/pages/user/chat_page.py")

    assert '[data-testid="stChatMessageAvatarUser"]' in theme
    assert "margin-left: auto !important;" in theme
    assert "flex-direction: row-reverse !important;" in theme
    assert "st.chat_message(role)" in admin
    assert "st.chat_message(role)" in employee


def test_chat_input_has_dark_surface_and_white_text() -> None:
    theme = _source("ui/theme/theme_loader.py")

    assert '[data-testid="stChatInput"] textarea' in theme
    assert "background-color: #252630 !important;" in theme
    assert "-webkit-text-fill-color: #FFFFFF !important;" in theme
    assert "textarea::placeholder" in theme


def test_chroma_persistent_client_disables_anonymized_telemetry() -> None:
    smart_ai = _source("modules/smart_ai/portal_ai.py")
    env = _source(".env")
    env_example = _source(".env.example")

    assert "from chromadb.config import Settings as ChromaSettings" in smart_ai
    assert "settings=ChromaSettings(anonymized_telemetry=False)" in smart_ai
    assert "ANONYMIZED_TELEMETRY=False" in env
    assert "ANONYMIZED_TELEMETRY=False" in env_example


def test_v88120_release_remains_preserved_after_later_checkpoints() -> None:
    settings = _source("config/settings.py")
    readme = _source("README.md")

    assert 'app_version: str = "0.8.8.' in settings
    assert "v8.8.120 — Right-Aligned User Chat" in readme
