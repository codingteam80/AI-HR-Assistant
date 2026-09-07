"""Shared free-text multi-term search helpers.

The portal's multi-search control returns independent free-text terms. Search
matching is deliberately deterministic and case-insensitive: by default a row
is visible when *any* committed term appears anywhere in its searchable text.
No AI, fuzzy guessing, or cross-record inference is involved.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Literal

SearchMatchMode = Literal["any", "all"]


def normalize_search_terms(terms: Iterable[object] | object | None) -> tuple[str, ...]:
    """Return trimmed, case-preserving, duplicate-free search terms.

    Strings are treated as one term for backward compatibility. Duplicates are
    removed case-insensitively while preserving the first entered spelling.
    """

    if terms is None:
        return ()
    if isinstance(terms, str):
        candidates: Iterable[object] = (terms,)
    else:
        try:
            candidates = iter(terms)  # type: ignore[arg-type]
        except TypeError:
            candidates = (terms,)

    output: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        text = str(candidate or "").strip()
        if not text:
            continue
        normalized = text.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        output.append(text)
    return tuple(output)


def matches_search_terms(
    terms: Iterable[object] | object | None,
    values: Iterable[object],
    *,
    mode: SearchMatchMode = "any",
) -> bool:
    """Return whether searchable values match the committed free-text terms.

    ``mode='any'`` is the project default because multi-search chips represent
    independent requested matches (for example two employee names, or a name
    plus a department). ``mode='all'`` is available for future scoped filters.
    """

    normalized_terms = tuple(term.casefold() for term in normalize_search_terms(terms))
    if not normalized_terms:
        return True

    haystack = " ".join(
        str(value or "").strip()
        for value in values
        if value not in (None, "")
    ).casefold()

    if mode == "all":
        return all(term in haystack for term in normalized_terms)
    return any(term in haystack for term in normalized_terms)


def text_matches_search_terms(
    terms: Iterable[object] | object | None,
    searchable_text: object,
    *,
    mode: SearchMatchMode = "any",
) -> bool:
    """Convenience wrapper for pre-combined searchable text."""

    return matches_search_terms(terms, (searchable_text,), mode=mode)


def visible_row_values(row: Mapping[object, object]) -> tuple[object, ...]:
    """Return only values explicitly present in a rendered row mapping.

    Portal pages should pass the same dict that is rendered in the table/list.
    This keeps project-wide search aligned with user-visible columns and avoids
    accidentally indexing hidden ORM/database fields or action controls.
    """

    return tuple(row.values())


def matches_visible_row(
    terms: Iterable[object] | object | None,
    row: Mapping[object, object],
    *,
    mode: SearchMatchMode = "any",
) -> bool:
    """Match free-text chips against every meaningful value in one visible row."""

    return matches_search_terms(terms, visible_row_values(row), mode=mode)


def filter_aligned_visible_rows(
    items: Iterable[object],
    rows: Iterable[Mapping[object, object]],
    terms: Iterable[object] | object | None,
    *,
    mode: SearchMatchMode = "any",
) -> tuple[list[object], list[Mapping[object, object]]]:
    """Filter records and their rendered rows together without index drift."""

    item_list = list(items)
    row_list = list(rows)
    if len(item_list) != len(row_list):
        raise ValueError("Search rows must stay aligned with their source records.")

    kept_items: list[object] = []
    kept_rows: list[Mapping[object, object]] = []
    for item, row in zip(item_list, row_list, strict=True):
        if matches_visible_row(terms, row, mode=mode):
            kept_items.append(item)
            kept_rows.append(row)
    return kept_items, kept_rows
