"""Qwen2.5 shared Chat Assistant wiring regression tests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from config.settings import Settings
from modules.smart_ai.portal_ai import OllamaClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class _FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self) -> bytes:
        return b'{"response": "Grounded answer"}'


def test_qwen25_current_model_is_the_default_for_standard_and_quality_requests():
    settings = Settings(_env_file=None)
    assert settings.smart_ai_ollama_model == "qwen2.5:7b"
    assert settings.smart_ai_quality_ollama_model == "qwen2.5:7b"


def test_ollama_payload_uses_current_qwen25_model_for_both_request_paths():
    client = OllamaClient()
    captured_models: list[str] = []

    def fake_urlopen(request_object, timeout):
        payload = json.loads(request_object.data.decode("utf-8"))
        captured_models.append(payload["model"])
        assert timeout == 120.0
        return _FakeResponse()

    with patch("modules.smart_ai.portal_ai.request.urlopen", side_effect=fake_urlopen):
        assert client.generate("Standard prompt") == "Grounded answer"
        assert client.generate("Quality prompt", quality=True) == "Grounded answer"

    assert captured_models == ["qwen2.5:7b", "qwen2.5:7b"]


def test_admin_and_employee_pages_use_the_shared_smart_ai_service():
    admin = (PROJECT_ROOT / "ui/pages/admin/chat_page.py").read_text(encoding="utf-8")
    employee = (PROJECT_ROOT / "ui/pages/user/chat_page.py").read_text(encoding="utf-8")

    assert "SmartPortalAssistant(session).enhance" in admin
    assert 'role_scope="admin"' in admin
    assert "SmartPortalAssistant(session).enhance" in employee
    assert 'role_scope="employee"' in employee


def test_environment_templates_and_qwen_setup_remain_preserved():
    env = (PROJECT_ROOT / ".env").read_text(encoding="utf-8")
    env_example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    settings = (PROJECT_ROOT / "config/settings.py").read_text(encoding="utf-8")

    for content in (env, env_example):
        assert "SMART_AI_OLLAMA_MODEL=qwen2.5:7b" in content
        assert "SMART_AI_QUALITY_OLLAMA_MODEL=qwen2.5:7b" in content
    assert 'app_version: str = "0.8.8.' in settings
    assert "ollama pull qwen2.5:7b" in (
        PROJECT_ROOT / "README.md"
    ).read_text(encoding="utf-8")
