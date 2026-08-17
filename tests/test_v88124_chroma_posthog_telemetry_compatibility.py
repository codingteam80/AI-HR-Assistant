"""v8.8.124 Chroma/PostHog telemetry compatibility regression checks."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_process_telemetry_flag_is_set_before_lazy_chroma_import() -> None:
    smart_ai = _source("modules/smart_ai/portal_ai.py")

    process_flag = smart_ai.index('os.environ["ANONYMIZED_TELEMETRY"] = "False"')
    lazy_import = smart_ai.index("import chromadb")
    assert process_flag < lazy_import
    assert 'logging.getLogger("chromadb.telemetry.product.posthog").disabled = True' in smart_ai
    assert "settings=ChromaSettings(anonymized_telemetry=False)" in smart_ai


def test_chroma_and_compatible_posthog_are_pinned() -> None:
    requirements = _source("requirements.txt")

    assert "chromadb>=1.0.15,<2.0" in requirements
    assert "posthog>=2.4,<6.0.0" in requirements


def test_telemetry_fix_does_not_disable_vector_or_bm25_retrieval() -> None:
    smart_ai = _source("modules/smart_ai/portal_ai.py")

    assert "self.bm25.search" in smart_ai
    assert "self.vector.search" in smart_ai
    assert "collection.query" in smart_ai
    assert "smart_ai_enabled" in smart_ai


def test_v88124_checkpoint_is_documented() -> None:
    readme = _source("README.md")

    assert "v8.8.124 — Chroma/PostHog Telemetry Compatibility Fix" in readme
