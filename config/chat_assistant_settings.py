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
    ollama_timeout_seconds: int = 180
    ollama_health_timeout_seconds: float = 5.0
    ollama_retry_timeout_seconds: int = 90
    ollama_timeout_retry_enabled: bool = True

    # Terminal-only retrieval / answer diagnostics. With request logging enabled,
    # stderr stays compact while the full forensic trace is preserved per request
    # under ``terminal_debug_log_dir``. Nothing is rendered in the Streamlit UI.
    terminal_debug_enabled: bool = True
    terminal_debug_top_k: int = 10
    terminal_debug_excerpt_chars: int = 520
    terminal_debug_answer_chars: int = 1800
    terminal_debug_candidate_answer_chars: int = 760
    terminal_debug_log_enabled: bool = True
    terminal_debug_log_dir: str = "logs/chat_assistant"

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

    # Knowledge chunking and document-aware hybrid retrieval.
    # ``chunk_size`` remains as a compatibility fallback for older integrations;
    # policy/company-document content uses the source-specific settings below.
    chunk_size: int = 256
    chunk_overlap: int = 40
    policy_chunk_size: int = 260
    policy_chunk_overlap: int = 48
    company_document_chunk_size: int = 300
    company_document_chunk_overlap: int = 56
    file_top_k: int = 5
    file_candidate_k: int = 10
    max_chunks_per_file: int = 3
    neighbor_chunk_window: int = 1
    bm25_top_k: int = 10
    vector_top_k: int = 10
    final_top_k: int = 6
    evidence_neighbor_reserve: int = 1
    evidence_file_representatives: int = 2
    evidence_min_score_ratio: float = 0.80
    evidence_excerpt_chars: int = 900
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
    def smart_ai_ollama_retry_timeout_seconds(self) -> int:
        return get_chat_assistant_settings().ollama_retry_timeout_seconds

    @property
    def smart_ai_terminal_debug_enabled(self) -> bool:
        return get_chat_assistant_settings().terminal_debug_enabled

    @property
    def smart_ai_chunk_size(self) -> int:
        return get_chat_assistant_settings().chunk_size

    @property
    def smart_ai_chunk_overlap(self) -> int:
        return get_chat_assistant_settings().chunk_overlap

    @property
    def smart_ai_policy_chunk_size(self) -> int:
        return get_chat_assistant_settings().policy_chunk_size

    @property
    def smart_ai_policy_chunk_overlap(self) -> int:
        return get_chat_assistant_settings().policy_chunk_overlap

    @property
    def smart_ai_company_document_chunk_size(self) -> int:
        return get_chat_assistant_settings().company_document_chunk_size

    @property
    def smart_ai_company_document_chunk_overlap(self) -> int:
        return get_chat_assistant_settings().company_document_chunk_overlap

    @property
    def smart_ai_file_top_k(self) -> int:
        return get_chat_assistant_settings().file_top_k

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
