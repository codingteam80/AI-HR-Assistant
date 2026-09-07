"""v8.8.213 multi-search BidiComponent JavaScript regression tests."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _assigned_string(name: str) -> str:
    module = ast.parse(_source("ui/components/live_search.py"))
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"Missing assignment: {name}")


def test_multi_search_runtime_js_keeps_regex_on_one_line() -> None:
    js = _assigned_string("_MULTI_SEARCH_JS")
    assert ".split(/[\\n,]+/)" in js
    assert "if (/[\\n,]/.test(input.value)) addDraft();" in js
    assert ".split(/[\n,]+/)" not in js
    assert "if (/[\n,]/.test(input.value))" not in js


def test_multi_search_ui_behavior_is_preserved() -> None:
    source = _source("ui/components/live_search.py")
    assert "event.key === 'Enter' || event.key === ','" in source
    assert "event.key === 'Backspace'" in source
    assert "event.key === 'Escape'" in source
    assert "Clear all search terms" in source
    assert "Results match any chip." in source


def test_version_markers_are_v88213() -> None:
    assert 'app_version: str = "0.8.8.213"' in _source("config/settings.py")
    assert "APP_VERSION=0.8.8.213" in _source(".env")
    assert "APP_VERSION=0.8.8.213" in _source(".env.example")
