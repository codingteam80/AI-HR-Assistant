"""Dedicated configuration for the local Chat Assistant.

Purpose:
- Keep Chat Assistant model, generation, retrieval, and quality tuning values
  out of the main application settings module.
- Make AI-specific configuration easy to find and adjust in one place.
- Preserve environment overrides through SMART_AI_* variables in `.env`.

These settings affect only the Admin/Employee Chat Assistant. They do not
change authentication, HR workflows, reports, notifications, or other portal
modules.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class ChatAssistantSettings(BaseSettings):
    """Environment-driven settings used only by the Chat Assistant."""

    # Master switch.
    enabled: bool = True

    # Ollama connection and models.
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"
    quality_ollama_model: str = "qwen2.5:7b"
    ollama_timeout_seconds: int = 120
    ollama_health_timeout_seconds: float = 2.0

    # Grounded generation controls.
    temperature: float = 0.0
    context_window: int = 4096
    standard_max_tokens: int = 320
    quality_max_tokens: int = 480
    keep_alive: str = "30m"
    history_messages: int = 4

    # Decide when the LLM enhancement/quality path is useful.
    min_question_tokens: int = 18
    quality_min_question_tokens: int = 14
    quality_min_retrieved_documents: int = 3

    # Knowledge chunking and hybrid retrieval.
    chunk_size: int = 256
    chunk_overlap: int = 40
    bm25_top_k: int = 8
    vector_top_k: int = 8
    final_top_k: int = 5
    chroma_dir: str = "data/smart_ai/chroma"
    chroma_collection: str = "hr_portal_knowledge"
    embedding_model: str = "intfloat/multilingual-e5-small"

    # Candidate selection / ambiguity tuning.
    reciprocal_rank_constant: int = 60
    candidate_multiplier: int = 3
    candidate_minimum: int = 8
    ambiguity_min_candidates: int = 4
    ambiguity_score_gap: float = 0.006
    complex_query_min_tokens: int = 12

    # Optional CrossEncoder reranker.
    reranker_enabled: bool = False
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="SMART_AI_",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_chat_assistant_settings() -> ChatAssistantSettings:
    """Return one cached Chat Assistant settings object."""

    return ChatAssistantSettings()


class ChatAssistantSettingsCompatibilityMixin:
    """Legacy SMART_AI attribute bridge for the main Settings object.

    New Chat Assistant code should use `get_chat_assistant_settings()`
    directly. These properties preserve older integrations without keeping AI
    configuration fields inside `config/settings.py`.
    """

    @property
    def smart_ai_enabled(self) -> bool:
        return get_chat_assistant_settings().enabled

    @property
    def smart_ai_ollama_base_url(self) -> str:
        return get_chat_assistant_settings().ollama_base_url

    @property
    def smart_ai_ollama_model(self) -> str:
        return get_chat_assistant_settings().ollama_model

    @property
    def smart_ai_quality_ollama_model(self) -> str:
        return get_chat_assistant_settings().quality_ollama_model

    @property
    def smart_ai_ollama_timeout_seconds(self) -> int:
        return get_chat_assistant_settings().ollama_timeout_seconds

    @property
    def smart_ai_ollama_health_timeout_seconds(self) -> float:
        return get_chat_assistant_settings().ollama_health_timeout_seconds

    @property
    def smart_ai_chunk_size(self) -> int:
        return get_chat_assistant_settings().chunk_size

    @property
    def smart_ai_chunk_overlap(self) -> int:
        return get_chat_assistant_settings().chunk_overlap

    @property
    def smart_ai_bm25_top_k(self) -> int:
        return get_chat_assistant_settings().bm25_top_k

    @property
    def smart_ai_vector_top_k(self) -> int:
        return get_chat_assistant_settings().vector_top_k

    @property
    def smart_ai_final_top_k(self) -> int:
        return get_chat_assistant_settings().final_top_k

    @property
    def smart_ai_chroma_dir(self) -> str:
        return get_chat_assistant_settings().chroma_dir

    @property
    def smart_ai_chroma_collection(self) -> str:
        return get_chat_assistant_settings().chroma_collection

    @property
    def smart_ai_embedding_model(self) -> str:
        return get_chat_assistant_settings().embedding_model

    @property
    def smart_ai_reranker_enabled(self) -> bool:
        return get_chat_assistant_settings().reranker_enabled

    @property
    def smart_ai_reranker_model(self) -> str:
        return get_chat_assistant_settings().reranker_model
