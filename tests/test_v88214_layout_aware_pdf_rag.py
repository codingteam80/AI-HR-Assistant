"""v8.8.214 layout-aware PDF extraction and RAG integration regressions."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from modules.documents.pdf_layout_extractor import PDFLayoutExtractor
from modules.documents.policy_file_parser import PolicyFileParser
from services.company_form_knowledge_service import CompanyFormKnowledgeExtractor


ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 2 * 1024 * 1024


def _layout_pdf() -> bytes:
    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=letter)
    for page_number in (1, 2):
        pdf.setFont("Helvetica", 8)
        pdf.drawString(72, 775, "CONFIDENTIAL HR POLICY")

        if page_number == 1:
            pdf.setFont("Helvetica-Bold", 18)
            pdf.drawString(72, 730, "EMPLOYEE CONDUCT POLICY")
            pdf.setFont("Helvetica", 10)
            pdf.drawString(
                72,
                700,
                "Employees must follow the approved company procedure.",
            )
        else:
            pdf.setFont("Helvetica-Bold", 13)
            pdf.drawString(72, 730, "Rule 7.4 Carry Over Limits")
            pdf.setFont("Helvetica", 10)
            pdf.drawString(
                72,
                700,
                "Unused credits are subject to the configured annual reset rule.",
            )

        pdf.setFont("Helvetica", 8)
        pdf.drawCentredString(306, 20, f"Page {page_number}")
        pdf.showPage()
    pdf.save()
    return output.getvalue()


def test_layout_extractor_detects_visual_and_semantic_headings() -> None:
    extracted = PDFLayoutExtractor.extract(_layout_pdf())
    assert extracted.page_count == 2
    headings = [section.heading for section in extracted.sections]
    assert "EMPLOYEE CONDUCT POLICY" in headings
    assert "Rule 7.4 Carry Over Limits" in headings
    assert any(section.page_number == 2 for section in extracted.sections)
    assert "annual reset rule" in extracted.full_text


def test_layout_extractor_removes_repeated_page_furniture() -> None:
    extracted = PDFLayoutExtractor.extract(_layout_pdf())
    assert "CONFIDENTIAL HR POLICY" not in extracted.full_text
    assert "\nPage 1\n" not in extracted.full_text
    assert "\nPage 2\n" not in extracted.full_text


def test_policy_parser_uses_layout_sections_without_replacing_current_chunking() -> None:
    parsed = PolicyFileParser.parse(
        filename="Conduct Policy.pdf",
        file_bytes=_layout_pdf(),
        maximum_size_bytes=MAX_BYTES,
        supplied_mime_type="application/pdf",
    )
    assert parsed.page_count == 2
    assert any(
        section.heading == "Rule 7.4 Carry Over Limits"
        and section.page_number == 2
        and "configured annual reset rule" in section.text
        for section in parsed.sections
    )


def test_company_document_pdf_emits_page_and_heading_markers_for_existing_rag() -> None:
    text = CompanyFormKnowledgeExtractor._pdf(_layout_pdf())
    assert "## Page 1 — EMPLOYEE CONDUCT POLICY" in text
    assert "## Page 2 — Rule 7.4 Carry Over Limits" in text
    assert "configured annual reset rule" in text


def test_pdf_layout_enhancement_keeps_current_retrieval_architecture() -> None:
    portal_source = (ROOT / "modules" / "smart_ai" / "portal_ai.py").read_text(
        encoding="utf-8"
    )
    assert "_split_text(" in portal_source
    assert "self.settings.policy_chunk_size" in portal_source
    assert "self.settings.policy_chunk_overlap" in portal_source
    assert "self.settings.company_document_chunk_size" in portal_source
    assert "self.settings.company_document_chunk_overlap" in portal_source
    assert "class BM25Retriever" in portal_source
    assert "class ChromaRetriever" in portal_source
    assert "class HybridRetriever" in portal_source
    assert "role_scope=role_scope" in portal_source
    assert "company_id=current_user.company_id" in portal_source


def test_pdf_layout_uses_modern_pymupdf_import_and_existing_dependency_pin() -> None:
    layout_source = (
        ROOT / "modules" / "documents" / "pdf_layout_extractor.py"
    ).read_text(encoding="utf-8")
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "import pymupdf" in layout_source
    assert "import fitz" not in layout_source
    assert "PyMuPDF>=1.26.7,<1.27.0" in requirements


def test_v88214_version_markers() -> None:
    assert 'app_version: str = "0.8.8.214"' in (
        ROOT / "config" / "settings.py"
    ).read_text(encoding="utf-8")
    assert "APP_VERSION=0.8.8.214" in (ROOT / ".env").read_text(encoding="utf-8")
    assert "APP_VERSION=0.8.8.214" in (ROOT / ".env.example").read_text(encoding="utf-8")
