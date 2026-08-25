"""Shared guidance helpers for downloadable Excel import templates.

Header comments expose the application's current accepted choices without
adding noisy visible instruction rows to the user's working sheet.  Inline
Excel dropdowns are used only for small, closed choice sets.  Dynamic/open
references stay documented instead of being incorrectly hard-blocked.
"""

from __future__ import annotations

from collections.abc import Iterable

from openpyxl.comments import Comment
from openpyxl.worksheet.datavalidation import DataValidation


EXCEL_GUIDANCE_AUTHOR = "AI HR Assistant"
EXCEL_COMMENT_SAFE_TEXT_LIMIT = 30_000


def _clean_choices(values: Iterable[object]) -> tuple[str, ...]:
    """Return nonblank choice labels while preserving source order."""

    return tuple(
        text
        for value in values
        if (text := str(value or "").strip())
    )


def add_header_guidance(
    sheet,
    cell_reference: str,
    *,
    requirement: str,
    choices: Iterable[object] = (),
    choices_heading: str = "Complete valid selections:",
    extra: str | None = None,
) -> Comment:
    """Attach one consistent, collapsed Excel header note."""

    choice_values = _clean_choices(choices)
    requirement_text = str(requirement).strip()
    heading_text = str(choices_heading).strip() or "Complete valid selections:"
    extra_text = str(extra).strip() if extra else ""
    parts = [requirement_text]
    if choice_values:
        parts.extend(["", heading_text])
        # Excel comments are not a safe place for an unbounded tenant list.
        # Keep all current values in the comment while it is reasonably sized;
        # for very large companies, preserve workbook compatibility and direct
        # users to the template's company-scoped reference sheet for the full list.
        reserved = len(requirement_text) + len(heading_text) + len(extra_text) + 500
        running = reserved
        truncated = False
        for value in choice_values:
            line = f"- {value}"
            if running + len(line) + 1 > EXCEL_COMMENT_SAFE_TEXT_LIMIT:
                truncated = True
                break
            parts.append(line)
            running += len(line) + 1
        if truncated:
            parts.extend(
                [
                    "- …",
                    "The live selection list is too large for one Excel comment. "
                    "Use the template's company-scoped reference worksheet for the complete current values.",
                ]
            )
    if extra_text:
        parts.extend(["", extra_text])

    text = "\n".join(part for part in parts if part is not None)
    comment = Comment(text, EXCEL_GUIDANCE_AUTHOR)
    comment.width = 520
    comment.height = min(520, max(120, 18 * (text.count("\n") + 3)))
    sheet[cell_reference].comment = comment
    return comment


def add_inline_list_validation(
    sheet,
    cell_range: str,
    choices: Iterable[object],
    *,
    allow_blank: bool,
) -> DataValidation | None:
    """Add a dropdown when the complete closed list fits Excel inline rules."""

    choice_values = _clean_choices(choices)
    if not choice_values:
        return None

    # Inline list formulas are intentionally limited by Excel.  Commas inside
    # values also make the inline representation ambiguous, so skip the
    # dropdown in those cases while keeping the complete header comment.
    if any("," in value for value in choice_values):
        return None
    formula = '"' + ",".join(value.replace('"', '""') for value in choice_values) + '"'
    if len(formula) > 255:
        return None

    validation = DataValidation(
        type="list",
        formula1=formula,
        allow_blank=allow_blank,
    )
    validation.errorTitle = "Invalid selection"
    validation.error = (
        "Choose a value from the dropdown. Hover the column header to view "
        "the complete valid selections."
    )
    validation.promptTitle = "Valid selections"
    validation.prompt = (
        "Choose from the dropdown. Hover the column header for the complete list."
    )
    validation.showInputMessage = True
    validation.showErrorMessage = True
    sheet.add_data_validation(validation)
    validation.add(cell_range)
    return validation


_REFERENCE_MISSING_TOKENS = {"n/a", "na", "none", "null", "-", "—"}


def _display_part(value: object) -> str:
    """Normalize one human-readable reference component."""

    text = " ".join(str(value or "").split()).strip()
    if not text or text.casefold() in _REFERENCE_MISSING_TOKENS:
        return ""
    return text


def employee_reference_label(
    employee_number: object,
    last_name: object,
    first_name: object,
    suffix: object = None,
) -> str:
    """Return the standard Excel employee reference label.

    Format: ``Employee Number - Last Name, First Name Suffix``.
    Middle names are intentionally omitted to match the project-wide import
    reference standard while the stable Employee Number remains authoritative.
    """

    number = _display_part(employee_number)
    last = _display_part(last_name)
    first = _display_part(first_name)
    suffix_text = _display_part(suffix)
    name = f"{last}, {first}".strip(", ")
    if suffix_text:
        name = f"{name} {suffix_text}".strip()
    if number and name:
        return f"{number} - {name}"
    return number or name


def identifier_name_reference(identifier: object, name: object) -> str:
    """Return ``Identifier - Human-readable Name`` for exact Excel references."""

    identifier_text = _display_part(identifier)
    name_text = _display_part(name)
    if identifier_text and name_text:
        return f"{identifier_text} - {name_text}"
    return identifier_text or name_text
