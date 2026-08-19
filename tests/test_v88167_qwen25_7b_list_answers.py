"""Regression checks for v8.8.167 Qwen2.5 7B structured answers."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from config.settings import Settings
from modules.smart_ai.portal_ai import OllamaClient, _clean_model_answer, _organize_answer


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class _FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self) -> bytes:
        return json.dumps({
            "response": "Here are the items:\n\n- First item\n- Second item"
        }).encode("utf-8")


def test_qwen25_7b_is_the_current_default_model() -> None:
    settings = Settings(_env_file=None)
    assert settings.smart_ai_ollama_model == "qwen2.5:7b"
    assert settings.smart_ai_quality_ollama_model == "qwen2.5:7b"


def test_ollama_payload_uses_7b_and_larger_grounded_context() -> None:
    client = OllamaClient()
    payloads: list[dict] = []

    def fake_urlopen(request_object, timeout):
        payloads.append(json.loads(request_object.data.decode("utf-8")))
        assert timeout == 120.0
        return _FakeResponse()

    with patch("modules.smart_ai.portal_ai.request.urlopen", side_effect=fake_urlopen):
        standard = client.generate("Standard prompt")
        quality = client.generate("Quality prompt", quality=True)

    assert standard == "Here are the items:\n\n- First item\n- Second item"
    assert quality == standard
    assert [item["model"] for item in payloads] == ["qwen2.5:7b", "qwen2.5:7b"]
    assert payloads[0]["options"]["num_ctx"] == 4096
    assert payloads[0]["options"]["num_predict"] == 320
    assert payloads[1]["options"]["num_predict"] == 480


def test_model_answer_cleaner_preserves_markdown_lists() -> None:
    raw = "FINAL ANSWER:\r\n\r\n-  First fact  \r\n- Second fact\r\n"
    assert _clean_model_answer(raw) == "- First fact\n- Second fact"


def test_multi_line_plain_answer_is_organized_as_bullets() -> None:
    answer = _organize_answer("Available items:\nVacation Leave\nSick Leave\nEmergency Leave")
    assert answer == (
        "Available items:\n\n"
        "- Vacation Leave\n"
        "- Sick Leave\n"
        "- Emergency Leave"
    )


def test_prompt_explicitly_requires_lists_for_multiple_items() -> None:
    source = (PROJECT_ROOT / "modules/smart_ai/prompts/hr_assistant_prompt.py").read_text(encoding="utf-8")
    assert "Two or more distinct facts, options, records, requirements, or reasons" in source
    assert "use a Markdown bullet list, one item per line" in source
    assert "A procedure or ordered workflow: use a Markdown numbered list" in source
    assert "Never compress multiple distinct items into one long paragraph" in source


def test_environment_and_readme_use_qwen25_7b() -> None:
    env = (PROJECT_ROOT / ".env").read_text(encoding="utf-8")
    env_example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    settings = (PROJECT_ROOT / "config/settings.py").read_text(encoding="utf-8")

    for content in (env, env_example):
        assert "SMART_AI_OLLAMA_MODEL=qwen2.5:7b" in content
        assert "SMART_AI_QUALITY_OLLAMA_MODEL=qwen2.5:7b" in content
    assert "ollama pull qwen2.5:7b" in readme
    assert 'app_version: str = "0.8.8.' in settings
    assert "APP_VERSION=0.8.8." in env_example
