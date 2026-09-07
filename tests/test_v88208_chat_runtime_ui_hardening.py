"""Focused regressions for v8.8.208 Chat/Ollama and UI hardening."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from urllib import error as urllib_error

import pytest

from modules.hr_assistant.hr_assistant import HRAssistantResponse
from modules.smart_ai import portal_ai
from modules.smart_ai.portal_ai import OllamaClient, SmartPortalAssistant
from services.runtime_connection_service import (
    RuntimeServiceResponseError,
    classify_runtime_connection_issue,
)


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_ollama_http_failure_is_not_mislabeled_as_unavailable() -> None:
    issue = classify_runtime_connection_issue(
        RuntimeServiceResponseError(
            "ollama",
            status_code=500,
            detail="model runner process crashed",
        ),
        service_hint="ollama",
    )
    assert issue is not None
    assert issue.code == "ollama_generation_failed"
    assert issue.title == "AI response generation issue"
    assert "model runner process crashed" not in issue.message


def test_ollama_context_limit_gets_specific_safe_message() -> None:
    issue = classify_runtime_connection_issue(
        RuntimeServiceResponseError(
            "ollama",
            status_code=500,
            detail="prompt too long for context window",
        ),
        service_hint="ollama",
    )
    assert issue is not None
    assert issue.code == "ollama_context_limit"
    assert "safe context limit" in issue.message
    assert "prompt too long" not in issue.message


def test_ollama_client_reads_http_error_body_for_server_log(monkeypatch) -> None:
    client = OllamaClient()
    response_body = BytesIO(b'{"error":"model runner failed to allocate memory"}')
    http_error = urllib_error.HTTPError(
        "http://localhost:11434/api/generate",
        500,
        "Internal Server Error",
        hdrs=None,
        fp=response_body,
    )

    def _raise(*_args, **_kwargs):
        raise http_error

    monkeypatch.setattr(portal_ai.request, "urlopen", _raise)
    with pytest.raises(RuntimeServiceResponseError) as captured:
        client.generate("hello")

    assert captured.value.status_code == 500
    assert "allocate memory" in captured.value.detail


def test_prompt_budget_prioritizes_router_answer_and_bounds_sections() -> None:
    assistant = SmartPortalAssistant.__new__(SmartPortalAssistant)
    assistant.settings = SimpleNamespace(context_window=4096)

    history, router, context = assistant._budget_prompt_sections(
        history_text="H" * 9000,
        router_answer="R" * 14000,
        context="C" * 14000,
    )

    # 4096 * 1.6 = 6553 variable characters, split 56/34/remaining.
    assert len(router) < 3800
    assert len(context) < 2400
    assert len(history) < 1000
    assert "verified portal result remains authoritative" in router
    assert "omitted for safe model input size" in context


def test_enhancement_failure_keeps_verified_yes_no_router_answer(monkeypatch) -> None:
    assistant = SmartPortalAssistant.__new__(SmartPortalAssistant)
    assistant.session = None
    assistant.settings = SimpleNamespace(
        enabled=True,
        history_messages=4,
        min_question_tokens=18,
        quality_min_question_tokens=14,
        quality_min_retrieved_documents=3,
        context_window=4096,
    )
    assistant.retriever = SimpleNamespace(search=lambda *_args, **_kwargs: [])
    assistant.ollama = SimpleNamespace(
        generate=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeServiceResponseError(
                "ollama", status_code=500, detail="runner failed"
            )
        )
    )

    monkeypatch.setattr(portal_ai.PortalKnowledgeBuilder, "build", lambda *_a, **_k: [])
    deterministic = HRAssistantResponse(
        answer="**YES.** Unused leave can be carried over under the configured rule.",
        intent="faq",
    )
    current_user = SimpleNamespace(company_id=1, user_id=1)

    response = assistant.enhance(
        current_user=current_user,
        role_scope="admin",
        question="Can I carry over unused leave?",
        history=[],
        deterministic_response=deterministic,
    )
    assert "YES." in response.answer
    assert "Cannot be determined" not in response.answer
    assert response.runtime_warning_code == "ollama_generation_failed"


def test_clean_url_removes_only_theme_parameter_without_reload() -> None:
    theme_source = _read("ui/theme/theme_loader.py")
    state_source = _read("ui/theme/theme_state.py")

    assert 'currentUrl.searchParams.delete("theme")' in theme_source
    assert "history.replaceState" in theme_source
    assert 'searchParams.set("theme"' not in theme_source.split(
        "def _synchronize_theme_with_browser", 1
    )[1].split("def _enforce_input_value_contrast", 1)[0]
    assert "location.replace" not in theme_source.split(
        "def _synchronize_theme_with_browser", 1
    )[1].split("def _enforce_input_value_contrast", 1)[0]
    assert "st.query_params[THEME_QUERY_KEY]" not in state_source


def test_global_processing_feedback_and_stable_streamlit_background() -> None:
    source = _read("ui/theme/theme_loader.py")
    config = _read(".streamlit/config.toml")

    assert "ai-hr-global-processing" in source
    assert "Signing in…" in source
    assert "Signing out…" in source
    assert "Deleting…" in source
    assert "Saving…" in source
    assert "pointer-events" in source
    assert '[data-testid="stSpinner"]' in source
    assert 'backgroundColor = "#F7F9FC"' in config


def test_login_logout_have_native_spinner_fallbacks() -> None:
    assert 'with st.spinner("Signing in…"):' in _read(
        "ui/pages/authentication/login_page.py"
    )
    assert 'with st.spinner("Signing out…"):' in _read("ui/components/sidebar.py")
    assert 'with st.spinner("Signing out…"):' in _read(
        "ui/components/admin_sidebar.py"
    )


def test_chat_keeps_fixed_scroll_height_without_generic_streamlit_border() -> None:
    theme_source = _read("ui/theme/theme_loader.py")
    for relative_path, key in [
        ("ui/pages/admin/chat_page.py", "admin_chat_conversation"),
        ("ui/pages/user/chat_page.py", "employee_chat_conversation"),
    ]:
        source = _read(relative_path)
        assert "CHAT_CONVERSATION_HEIGHT = 500" in source
        assert "height=CHAT_CONVERSATION_HEIGHT" in source
        assert "border=False" in source
        assert f'key="{key}"' in source
        assert "st.chat_input(" in source

    assert ".st-key-admin_chat_conversation" in theme_source
    assert ".st-key-employee_chat_conversation" in theme_source


def test_v88208_version_markers() -> None:
    assert 'app_version: str = "0.8.8.208"' in _read("config/settings.py")
    assert "APP_VERSION=0.8.8.208" in _read(".env")
    assert "APP_VERSION=0.8.8.208" in _read(".env.example")
