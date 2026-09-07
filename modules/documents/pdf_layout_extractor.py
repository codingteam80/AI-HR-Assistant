"""Layout-aware, text-only PDF extraction for company knowledge files.

This module uses the modern ``pymupdf`` import and intentionally performs no
OCR. It reconstructs visual lines from spans, removes repeated page furniture,
uses font/bold/position signals to detect likely headings, and returns ordered,
page-aware semantic sections. Downstream chunk sizing, overlap, retrieval,
permission filtering, and LLM prompting remain separate concerns.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re
from typing import Iterable

import pymupdf


class PDFLayoutExtractionError(ValueError):
    """Base error for controlled layout-extraction failures."""


class PDFLayoutEncryptedError(PDFLayoutExtractionError):
    """Raised when a PDF requires a password that was not supplied."""


@dataclass(frozen=True, slots=True)
class PDFLayoutSection:
    """One ordered semantic section extracted from a PDF page."""

    heading: str
    text: str
    page_number: int


@dataclass(frozen=True, slots=True)
class PDFLayoutExtraction:
    """Clean full text plus semantic page-aware sections."""

    full_text: str
    sections: list[PDFLayoutSection]
    page_count: int


@dataclass(frozen=True, slots=True)
class _LayoutLine:
    """Internal visual line with the signals needed for classification."""

    text: str
    page_number: int
    font_size: float
    bold_ratio: float
    bbox: tuple[float, float, float, float]
    page_height: float


class PDFLayoutExtractor:
    """Extract readable semantic sections from text-based PDFs."""

    _SEMANTIC_HEADING = re.compile(
        r"^(?:rule|directive|dir\.?|section|article|part|chapter|appendix|annex)"
        r"\s+[A-Z0-9]+(?:[.\-][A-Z0-9]+)*(?:\s*[:.)\-]?\s+.*)?$",
        flags=re.IGNORECASE,
    )
    _NUMBERED_HEADING = re.compile(
        r"^(?:\d+(?:\.\d+)*|[A-Z]\.(?:\d+\.?)+)[.)]?\s+\S+",
        flags=re.IGNORECASE,
    )
    _PAGE_NUMBER = re.compile(
        r"^(?:page\s*)?\d+(?:\s+(?:of|/)\s*\d+)?$",
        flags=re.IGNORECASE,
    )

    @staticmethod
    def _clean_text(value: str) -> str:
        value = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
        value = re.sub(r"[ \t]+", " ", value)
        return value.strip()

    @staticmethod
    def _weighted_median(values: Iterable[tuple[float, int]]) -> float:
        prepared = sorted(
            (float(size), max(1, int(weight)))
            for size, weight in values
            if float(size) > 0
        )
        if not prepared:
            return 10.0
        total = sum(weight for _, weight in prepared)
        midpoint = total / 2
        running = 0
        for size, weight in prepared:
            running += weight
            if running >= midpoint:
                return size
        return prepared[-1][0]

    @classmethod
    def _line_from_spans(
        cls,
        *,
        spans: list[dict[str, object]],
        line_bbox: tuple[float, float, float, float],
        page_number: int,
        page_height: float,
    ) -> _LayoutLine | None:
        usable: list[dict[str, object]] = []
        for span in spans:
            text = cls._clean_text(str(span.get("text", "")))
            if not text:
                continue
            copy = dict(span)
            copy["text"] = text
            usable.append(copy)
        if not usable:
            return None

        usable.sort(key=lambda item: float(tuple(item.get("bbox", (0, 0, 0, 0)))[0]))
        size_weights: list[tuple[float, int]] = []
        bold_characters = 0
        total_characters = 0
        pieces: list[str] = []
        previous_x1: float | None = None

        for span in usable:
            text = str(span["text"])
            bbox = tuple(float(value) for value in span.get("bbox", line_bbox))
            size = float(span.get("size", 0) or 0)
            flags = int(span.get("flags", 0) or 0)
            font_name = str(span.get("font", "") or "").casefold()
            weight = max(1, len(re.sub(r"\s+", "", text)))
            size_weights.append((size, weight))
            total_characters += weight
            is_bold = bool(flags & 16) or any(
                marker in font_name
                for marker in ("bold", "semibold", "demi", "black", "heavy")
            )
            if is_bold:
                bold_characters += weight

            if pieces:
                gap = max(0.0, bbox[0] - (previous_x1 or bbox[0]))
                reference_size = max(6.0, size)
                if gap >= reference_size * 1.8:
                    pieces.append(" | ")
                elif gap >= 1.2 and not pieces[-1].endswith((" ", "-", "/")):
                    pieces.append(" ")
            pieces.append(text)
            previous_x1 = bbox[2]

        joined = cls._clean_text("".join(pieces))
        if not joined:
            return None
        return _LayoutLine(
            text=joined,
            page_number=page_number,
            font_size=cls._weighted_median(size_weights),
            bold_ratio=(bold_characters / total_characters) if total_characters else 0.0,
            bbox=tuple(float(value) for value in line_bbox),
            page_height=float(page_height),
        )

    @classmethod
    def _page_lines(cls, page: pymupdf.Page, page_number: int) -> list[_LayoutLine]:
        page_dict = page.get_text("dict", sort=True)
        page_height = float(page.rect.height)
        lines: list[_LayoutLine] = []
        for block in page_dict.get("blocks", []):
            if int(block.get("type", 0) or 0) != 0:
                continue
            for raw_line in block.get("lines", []):
                bbox = tuple(float(value) for value in raw_line.get("bbox", (0, 0, 0, 0)))
                line = cls._line_from_spans(
                    spans=list(raw_line.get("spans", [])),
                    line_bbox=bbox,
                    page_number=page_number,
                    page_height=page_height,
                )
                if line is not None:
                    lines.append(line)
        lines.sort(key=lambda item: (item.bbox[1], item.bbox[0]))
        return lines

    @staticmethod
    def _decoration_signature(value: str) -> str:
        normalized = re.sub(r"\s+", " ", str(value or "")).strip().casefold()
        return normalized[:180]

    @classmethod
    def _repeated_decorations(cls, pages: list[list[_LayoutLine]]) -> set[str]:
        if len(pages) < 2:
            return set()
        page_occurrences: Counter[str] = Counter()
        for lines in pages:
            seen: set[str] = set()
            for line in lines:
                top_band = line.bbox[1] <= line.page_height * 0.12
                bottom_band = line.bbox[3] >= line.page_height * 0.88
                if not (top_band or bottom_band) or len(line.text) > 140:
                    continue
                signature = cls._decoration_signature(line.text)
                if signature:
                    seen.add(signature)
            page_occurrences.update(seen)
        minimum_pages = max(2, int(len(pages) * 0.6 + 0.999))
        return {
            signature
            for signature, count in page_occurrences.items()
            if count >= minimum_pages
        }

    @classmethod
    def _is_page_decoration(cls, line: _LayoutLine, repeated: set[str]) -> bool:
        text = line.text.strip()
        if cls._PAGE_NUMBER.fullmatch(text):
            return True
        in_margin = (
            line.bbox[1] <= line.page_height * 0.12
            or line.bbox[3] >= line.page_height * 0.88
        )
        return in_margin and cls._decoration_signature(text) in repeated

    @staticmethod
    def _uppercase_ratio(value: str) -> float:
        letters = [character for character in value if character.isalpha()]
        if not letters:
            return 0.0
        return sum(character.isupper() for character in letters) / len(letters)

    @classmethod
    def _looks_like_heading(cls, line: _LayoutLine, body_size: float) -> bool:
        text = line.text.strip().strip("|").strip()
        if not text or len(text) > 180:
            return False
        if text.startswith(("- ", "* ", "• ")):
            return False
        if cls._SEMANTIC_HEADING.match(text):
            return True
        if cls._NUMBERED_HEADING.match(text) and len(text) <= 140:
            return True
        if text.endswith(":") and len(text) <= 120:
            return True

        size_ratio = line.font_size / max(1.0, body_size)
        visually_large = line.font_size >= body_size + 1.0 or size_ratio >= 1.12
        mostly_bold = line.bold_ratio >= 0.55
        uppercase_title = cls._uppercase_ratio(text) >= 0.85 and len(text) >= 4
        word_count = len(text.split())

        if visually_large and word_count <= 20:
            return True
        if mostly_bold and word_count <= 14 and len(text) <= 120:
            return True
        if uppercase_title and word_count <= 18:
            return True
        return False

    @classmethod
    def extract(
        cls,
        data: bytes,
        *,
        max_pages: int | None = None,
    ) -> PDFLayoutExtraction:
        """Return clean full text and page-aware semantic sections.

        ``max_pages`` is a retrieval-safety cap for document libraries. Policy
        uploads can omit it so their existing upload-size policy remains the
        controlling bound.
        """

        if not data:
            raise PDFLayoutExtractionError("The PDF file is empty.")
        try:
            document = pymupdf.open(stream=data, filetype="pdf")
        except Exception as error:  # pragma: no cover - library-specific detail
            raise PDFLayoutExtractionError("The PDF file is damaged or unreadable.") from error

        try:
            if document.needs_pass and not document.authenticate(""):
                raise PDFLayoutEncryptedError("Encrypted PDF files are not supported.")

            page_count = int(document.page_count)
            page_limit = page_count
            if max_pages is not None:
                page_limit = min(page_count, max(0, int(max_pages)))

            raw_pages = [
                cls._page_lines(document[index], index + 1)
                for index in range(page_limit)
            ]
        except PDFLayoutExtractionError:
            raise
        except Exception as error:
            raise PDFLayoutExtractionError("The PDF text layout could not be read.") from error
        finally:
            document.close()

        repeated = cls._repeated_decorations(raw_pages)
        clean_pages: list[list[_LayoutLine]] = [
            [line for line in lines if not cls._is_page_decoration(line, repeated)]
            for lines in raw_pages
        ]

        size_weights = [
            (line.font_size, max(1, len(re.sub(r"\s+", "", line.text))))
            for lines in clean_pages
            for line in lines
            if line.text.strip()
        ]
        body_size = cls._weighted_median(size_weights)

        full_pages: list[str] = []
        sections: list[PDFLayoutSection] = []
        active_heading: str | None = None

        for page_number, lines in enumerate(clean_pages, start=1):
            visible_lines = [line.text for line in lines if line.text.strip()]
            if visible_lines:
                full_pages.append(f"[Page {page_number}]\n" + "\n".join(visible_lines))

            page_section_start = len(sections)
            body: list[str] = []
            current_heading = active_heading or f"Page {page_number}"

            def flush() -> None:
                nonlocal body
                text = cls._clean_text("\n".join(body))
                if text:
                    sections.append(PDFLayoutSection(
                        heading=current_heading[:250],
                        text=text,
                        page_number=page_number,
                    ))
                body = []

            for line in lines:
                if cls._looks_like_heading(line, body_size):
                    flush()
                    current_heading = line.text.strip().strip("|").strip().rstrip(":") or f"Page {page_number}"
                    active_heading = current_heading
                    continue
                body.append(line.text)
            flush()

            # A page containing only a visually detected title still needs a
            # searchable unit instead of silently losing all of its text.
            if len(sections) == page_section_start and visible_lines:
                sections.append(PDFLayoutSection(
                    heading=(active_heading or f"Page {page_number}")[:250],
                    text=cls._clean_text("\n".join(visible_lines)),
                    page_number=page_number,
                ))

        return PDFLayoutExtraction(
            full_text="\n\n".join(full_pages).strip(),
            sections=sections,
            page_count=page_count,
        )
