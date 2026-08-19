"""Regression checks for v8.8.168 Chat Assistant prompt/settings refactor."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from config.chat_assistant_settings import ChatAssistantSettings
from config.settings import Settings
from modules.smart_ai.portal_ai import OllamaClient
from modules.smart_ai.prompts.hr_assistant_prompt import build_hr_assistant_prompt


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class _FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self) -> bytes:
        return b'{"response":"- One\\n- Two"}'


def test_chat_settings_are_centralized_in_dedicated_module() -> None:
    source = (PROJECT_ROOT / "config/chat_assistant_settings.py").read_text(encoding="utf-8")
    main = (PROJECT_ROOT / "config/settings.py").read_text(encoding="utf-8")

    assert 'ollama_model: str = "qwen2.5:7b"' in source
    assert 'context_window: int = 4096' in source
    assert 'standard_max_tokens: int = 320' in source
    assert 'quality_max_tokens: int = 480' in source
    assert 'bm25_top_k: int = 8' in source
    assert 'reranker_enabled: bool = False' in source
    assert "Chat Assistant model/generation/retrieval settings live" in main
    assert 'smart_ai_ollama_model: str = "qwen2.5:7b"' not in main


def test_main_settings_keep_backwards_compatible_chat_accessors() -> None:
    settings = Settings(_env_file=None)
    assert settings.smart_ai_ollama_model == "qwen2.5:7b"
    assert settings.smart_ai_quality_ollama_model == "qwen2.5:7b"
    assert settings.smart_ai_final_top_k == 5


def test_prompt_is_dedicated_and_preserves_grounded_list_rules() -> None:
    prompt = build_hr_assistant_prompt(
        role_rule="Use only authorized records.",
        history_text="User: hello",
        question="List my leave options",
        router_answer="Vacation Leave and Sick Leave",
        context="Vacation Leave. Sick Leave.",
    )
    assert "Never use outside knowledge, guesses, or assumptions." in prompt
    assert "use a Markdown bullet list, one item per line" in prompt
    assert "A procedure or ordered workflow" in prompt
    assert "List my leave options" in prompt


def test_ollama_payload_reads_generation_values_from_dedicated_settings() -> None:
    client = OllamaClient()
    custom = ChatAssistantSettings(
        _env_file=None,
        ollama_model="qwen2.5:7b",
        quality_ollama_model="qwen2.5:7b",
        temperature=0.0,
        context_window=5000,
        standard_max_tokens=333,
        quality_max_tokens=555,
        keep_alive="20m",
        ollama_timeout_seconds=77,
    )
    client.settings = custom
    payloads: list[dict] = []

    def fake_urlopen(request_object, timeout):
        payloads.append(json.loads(request_object.data.decode("utf-8")))
        assert timeout == 77.0
        return _FakeResponse()

    with patch("modules.smart_ai.portal_ai.request.urlopen", side_effect=fake_urlopen):
        assert client.generate("Standard") == "- One\n- Two"
        assert client.generate("Quality", quality=True) == "- One\n- Two"

    assert payloads[0]["options"]["num_ctx"] == 5000
    assert payloads[0]["options"]["num_predict"] == 333
    assert payloads[1]["options"]["num_predict"] == 555
    assert payloads[0]["keep_alive"] == "20m"


def test_env_template_exposes_chat_tuning_without_business_logic_edits() -> None:
    env_example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    for item in (
        "SMART_AI_CONTEXT_WINDOW=4096",
        "SMART_AI_STANDARD_MAX_TOKENS=320",
        "SMART_AI_QUALITY_MAX_TOKENS=480",
        "SMART_AI_HISTORY_MESSAGES=4",
        "SMART_AI_MIN_QUESTION_TOKENS=18",
        "SMART_AI_BM25_TOP_K=8",
        "SMART_AI_VECTOR_TOP_K=8",
        "SMART_AI_FINAL_TOP_K=5",
        "SMART_AI_RERANKER_ENABLED=false",
    ):
        assert item in env_example


def test_current_version_is_v88168() -> None:
    settings = Settings(_env_file=None)
    assert settings.app_version == "0.8.8.168"
