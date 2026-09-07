"""v8.8.210 company-only document-aware chunking/retrieval regressions."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

from modules.smart_ai import portal_ai
from modules.smart_ai.portal_ai import HybridRetriever, KnowledgeDocument


ROOT = Path(__file__).resolve().parents[1]


def _doc(
    doc_id: str,
    text: str,
    *,
    title: str,
    source_type: str = "policy",
    company_id: int = 1,
    role_scope: str = "shared",
    file_key: str | None = None,
    chunk_index: int = 1,
    section: str = "General",
) -> KnowledgeDocument:
    metadata = {
        "title": title,
        "section": section,
        "chunk_index": chunk_index,
        "filename": f"{title}.pdf",
    }
    if file_key is not None:
        metadata["file_key"] = file_key
    return KnowledgeDocument(
        document_id=doc_id,
        text=text,
        title=title,
        source_type=source_type,
        company_id=company_id,
        role_scope=role_scope,
        metadata=metadata,
    )


def test_sentence_aware_chunking_preserves_rows_and_uses_overlap() -> None:
    text = (
        "Annual leave credits may be carried over when the company rule allows it. "
        "Unused credits remain subject to the configured annual reset.\n\n"
        "Employee | Credits | Status\n"
        "Ana Cruz | 5 | Available\n"
        "Ben Santos | 2 | Used\n\n"
        + " ".join(
            f"Sentence {index} explains another leave condition."
            for index in range(1, 70)
        )
    )
    chunks = portal_ai._split_text(text, 90, 12)
    assert len(chunks) > 1
    assert any("Ana Cruz | 5 | Available" in chunk for chunk in chunks)
    assert any("Ben Santos | 2 | Used" in chunk for chunk in chunks)
    assert all(chunk.strip() for chunk in chunks)
    assert max(len(chunk.split()) for chunk in chunks) <= 90


def test_document_sections_preserve_pages_and_headings() -> None:
    sections = portal_ai._document_sections(
        "Page 1: Intro rule.\nMore details.\n\n"
        "Page 2: Second page rule.\n"
        "## Approval Process\nManager approval is required."
    )
    labels = [label for label, _ in sections]
    assert labels == ["Page 1", "Page 2", "Approval Process"]
    assert "Manager approval" in sections[-1][1]


def test_file_aware_retrieval_filters_company_and_role_and_limits_file_dominance(monkeypatch) -> None:
    retriever = HybridRetriever()
    monkeypatch.setattr(retriever.vector, "search", lambda *_a, **_k: [])
    monkeypatch.setattr(retriever.file_vector, "search", lambda *_a, **_k: [])

    documents = [
        _doc(
            "leave-1",
            "Unused annual leave carry over is allowed under the configured reset rule.",
            title="Annual Leave Policy",
            file_key="policy:leave",
            chunk_index=1,
            section="Carry Over",
        ),
        _doc(
            "leave-2",
            "Carry over limits and forfeiture are described in this section.",
            title="Annual Leave Policy",
            file_key="policy:leave",
            chunk_index=2,
            section="Carry Over",
        ),
        _doc(
            "leave-3",
            "Additional leave administration wording for the same policy file.",
            title="Annual Leave Policy",
            file_key="policy:leave",
            chunk_index=3,
            section="Administration",
        ),
        _doc(
            "attendance-1",
            "Attendance lateness and work schedules are recorded here.",
            title="Attendance Policy",
            file_key="policy:attendance",
            chunk_index=1,
            section="Lateness",
        ),
        # Same query terms but wrong tenant: must be excluded before ranking.
        _doc(
            "rogue-company",
            "Unused annual leave carry over is always unlimited.",
            title="Other Company Leave Policy",
            company_id=2,
            file_key="policy:rogue-company",
        ),
        # Same tenant but wrong private role: must also be excluded.
        _doc(
            "rogue-role",
            "Unused annual leave carry over is unlimited for a private employee.",
            title="Private Employee Note",
            role_scope="employee",
            file_key="policy:rogue-role",
        ),
    ]

    results = retriever.search(
        "Can unused annual leave carry over?",
        documents,
        company_id=1,
        role_scope="admin",
    )
    assert results
    assert all(item.document.company_id == 1 for item in results)
    assert all(item.document.role_scope in {"shared", "admin"} for item in results)
    assert results[0].document.metadata.get("file_key") == "policy:leave"
    counts = Counter(
        item.document.metadata.get("file_key")
        for item in results
        if item.document.metadata.get("file_key")
    )
    assert max(counts.values(), default=0) <= retriever.settings.max_chunks_per_file



def test_file_stage_can_find_rule_near_end_of_large_file(monkeypatch) -> None:
    retriever = HybridRetriever()
    monkeypatch.setattr(retriever.vector, "search", lambda *_a, **_k: [])
    monkeypatch.setattr(retriever.file_vector, "search", lambda *_a, **_k: [])

    documents: list[KnowledgeDocument] = []
    for file_number in range(1, 8):
        for chunk_number in range(1, 9):
            text = (
                f"General procedure for department {file_number}, part {chunk_number}."
            )
            if file_number == 6 and chunk_number == 8:
                text = (
                    "Unused vacation leave carry over is permitted under the annual "
                    "reset rule and remains subject to the configured credit limit."
                )
            documents.append(_doc(
                f"f{file_number}-c{chunk_number}",
                text,
                title=f"Policy {file_number}",
                file_key=f"policy:file:{file_number}",
                chunk_index=chunk_number,
                section="Carry Over" if file_number == 6 else "General",
            ))

    results = retriever.search(
        "Can unused vacation leave carry over?",
        documents,
        company_id=1,
        role_scope="admin",
    )
    assert results
    assert results[0].document.document_id == "f6-c8"


def test_retrieval_settings_are_tuned_for_document_aware_search() -> None:
    settings = retriever_settings = portal_ai.get_chat_assistant_settings()
    assert settings.policy_chunk_size == 260
    assert settings.policy_chunk_overlap == 48
    assert settings.company_document_chunk_size == 300
    assert settings.company_document_chunk_overlap == 56
    assert settings.file_top_k == 5
    assert settings.max_chunks_per_file == 3
    assert settings.neighbor_chunk_window == 1
    assert settings.bm25_top_k == 10
    assert settings.vector_top_k == 10
    assert retriever_settings.final_top_k == 6


def test_company_form_docx_extractor_preserves_heading_marker() -> None:
    source = (ROOT / "services" / "company_form_knowledge_service.py").read_text(
        encoding="utf-8"
    )
    assert "DOCXStructureExtractor.extract" in source
    assert 'f"## {section.heading}\\n{section.text}"' in source
    assert "reliable_heading_count == 0" in source



def test_chroma_query_is_partitioned_to_exact_authorized_snapshot(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    class FakeCollection:
        name = "hr_portal_knowledge"

        def upsert(self, *, ids, documents, embeddings, metadatas):
            captured["ids"] = ids
            captured["metadatas"] = metadatas

        def query(self, *, query_embeddings, n_results, where):
            captured["where"] = where
            return {"ids": [[captured["ids"][0]]], "distances": [[0.1]]}

    class FakeClient:
        def get_or_create_collection(self, **_kwargs):
            return FakeCollection()

    class FakeModel:
        def __init__(self, *_args, **_kwargs):
            pass

        def encode(self, values, normalize_embeddings=True):
            class Encoded(list):
                def tolist(self):
                    return list(self)
            return Encoded([[0.1, 0.2] for _ in values])

    fake_chromadb = ModuleType("chromadb")
    fake_chromadb.PersistentClient = lambda **_kwargs: FakeClient()
    fake_config = ModuleType("chromadb.config")
    fake_config.Settings = lambda **_kwargs: object()
    fake_sentence = ModuleType("sentence_transformers")
    fake_sentence.SentenceTransformer = FakeModel
    monkeypatch.setitem(sys.modules, "chromadb", fake_chromadb)
    monkeypatch.setitem(sys.modules, "chromadb.config", fake_config)
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_sentence)

    retriever = portal_ai.ChromaRetriever()
    retriever.settings.chroma_dir = str(tmp_path)
    retriever._embedding_model = FakeModel()
    documents = [
        _doc(
            "policy-1",
            "Annual leave carry over rule.",
            title="Leave Policy",
            file_key="policy:1",
        )
    ]
    results = retriever.search(
        "carry over",
        documents,
        1,
        access_partition="company:1:role:admin:user:1",
    )
    assert results and results[0].document.document_id == "policy-1"
    assert str(captured["ids"][0]).endswith(":policy-1")
    assert "retrieval_scope" in captured["where"]
    assert captured["metadatas"][0]["retrieval_scope"] == captured["where"]["retrieval_scope"]


def test_smart_assistant_passes_company_and_role_scope_to_retriever() -> None:
    source = (ROOT / "modules" / "smart_ai" / "portal_ai.py").read_text(
        encoding="utf-8"
    )
    assert "company_id=current_user.company_id" in source
    assert "role_scope=role_scope" in source
    assert 'where={"retrieval_scope": retrieval_scope}' in source
    assert "user:{current_user.user_id}" in source
