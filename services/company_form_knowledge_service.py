"""Safe searchable-text extraction for authorized Company Form/Documents files."""

from __future__ import annotations

import csv
from io import BytesIO, StringIO
from pathlib import Path
import re

from docx import Document
from openpyxl import load_workbook
from pypdf import PdfReader

from models.company_form import CompanyForm
from modules.documents.company_form_file_storage import CompanyFormFileStorage


class CompanyFormKnowledgeExtractor:
    """Extract bounded text from modern Company Form/Documents formats.

    The extractor is retrieval-only: it never modifies the source file and it
    fails closed (empty text) for unreadable/unsupported files. Old binary
    ``.doc``/``.xls`` files remain downloadable but are not falsely treated as
    text-searchable when no safe parser is available.
    """

    MAX_CHARACTERS = 60_000
    MAX_PDF_PAGES = 120
    MAX_SHEETS = 20
    MAX_ROWS_PER_SHEET = 1_000
    MAX_COLUMNS_PER_SHEET = 60

    def __init__(self, *, storage: CompanyFormFileStorage | None = None) -> None:
        self.storage = storage or CompanyFormFileStorage()

    @staticmethod
    def _clean(value: str) -> str:
        value = (value or "").replace("\r\n", "\n").replace("\r", "\n")
        value = re.sub(r"[ \t]+", " ", value)
        value = re.sub(r"\n{3,}", "\n\n", value)
        return value.strip()

    @classmethod
    def _bounded(cls, value: str) -> str:
        clean = cls._clean(value)
        if len(clean) <= cls.MAX_CHARACTERS:
            return clean
        return clean[: cls.MAX_CHARACTERS].rstrip() + "\n[Content truncated for search safety]"

    @staticmethod
    def _decode_text(data: bytes) -> str:
        for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", errors="replace")

    @classmethod
    def _pdf(cls, data: bytes) -> str:
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted:
            try:
                if reader.decrypt("") == 0:
                    return ""
            except Exception:
                return ""
        pages = []
        for page_number, page in enumerate(reader.pages[: cls.MAX_PDF_PAGES], start=1):
            text = cls._clean(page.extract_text() or "")
            if text:
                pages.append(f"Page {page_number}: {text}")
        return "\n\n".join(pages)

    @classmethod
    def _docx(cls, data: bytes) -> str:
        document = Document(BytesIO(data))
        lines: list[str] = []
        for paragraph in document.paragraphs:
            if paragraph.text.strip():
                lines.append(paragraph.text.strip())
        for table_index, table in enumerate(document.tables, start=1):
            lines.append(f"Table {table_index}")
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                if any(cells):
                    lines.append(" | ".join(cells))
        return "\n".join(lines)

    @classmethod
    def _csv(cls, data: bytes) -> str:
        reader = csv.reader(StringIO(cls._decode_text(data)))
        lines: list[str] = []
        for index, row in enumerate(reader):
            if index >= cls.MAX_ROWS_PER_SHEET:
                break
            values = [str(value).strip() for value in row[: cls.MAX_COLUMNS_PER_SHEET]]
            if any(values):
                lines.append(" | ".join(values))
        return "\n".join(lines)

    @classmethod
    def _xlsx(cls, data: bytes) -> str:
        workbook = load_workbook(BytesIO(data), read_only=True, data_only=True)
        lines: list[str] = []
        try:
            for sheet in workbook.worksheets[: cls.MAX_SHEETS]:
                lines.append(f"Sheet: {sheet.title}")
                for row_index, row in enumerate(
                    sheet.iter_rows(values_only=True), start=1
                ):
                    if row_index > cls.MAX_ROWS_PER_SHEET:
                        break
                    values = [
                        "" if value is None else str(value).strip()
                        for value in row[: cls.MAX_COLUMNS_PER_SHEET]
                    ]
                    if any(values):
                        lines.append(" | ".join(values))
        finally:
            workbook.close()
        return "\n".join(lines)

    def extract(self, form: CompanyForm) -> str:
        """Return searchable source-file text or an empty string safely."""

        extension = (form.file_extension or Path(form.original_filename).suffix).casefold()
        if extension not in {".pdf", ".docx", ".txt", ".csv", ".xlsx"}:
            return ""
        try:
            data = self.storage.read(form.storage_path)
            if extension == ".pdf":
                text = self._pdf(data)
            elif extension == ".docx":
                text = self._docx(data)
            elif extension == ".csv":
                text = self._csv(data)
            elif extension == ".xlsx":
                text = self._xlsx(data)
            else:
                text = self._decode_text(data)
            return self._bounded(text)
        except Exception:
            # Search indexing must never break the Chat page because one local
            # document is damaged, missing, encrypted, or temporarily unreadable.
            return ""
