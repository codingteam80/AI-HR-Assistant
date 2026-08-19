"""Reusable theme-aware wrapped table for administration pages.

Why this exists:
Streamlit's default dataframe grid can keep an internal dark appearance even
when the surrounding application uses the custom light theme. This component
renders safe HTML using the project's design tokens instead.

Security:
Every header and cell value is escaped before rendering.
"""

from html import escape
import re
from typing import Mapping, Sequence

import pandas as pd
import streamlit as st


def _safe_key(value: str) -> str:
    """Return a CSS-safe identifier fragment."""

    normalized = re.sub(
        r"[^a-zA-Z0-9_-]+",
        "-",
        value.strip(),
    ).strip("-")

    return normalized or "table"


def _cell_html(value: object) -> str:
    """Escape one cell and preserve line breaks."""

    if value is None:
        return ""

    return escape(str(value)).replace(
        "\n",
        "<br>",
    )


def _recommended_column_width(header: object) -> int:
    """Return a readable minimum width for one table column.

    The shared table component may be used by pages with many columns.  A
    content-aware minimum keeps labels such as ``Cancellation`` or
    ``Manager`` from collapsing into one-character-per-line columns while the
    table shell can still scroll horizontally.
    """

    label = str(header or "").strip().lower()

    wide_terms = (
        "reason",
        "summary",
        "description",
        "comment",
        "purpose",
        "detail",
        "affected record",
        "credit / lwop",
        "handover",
        "workspace",
        "route",
    )
    medium_terms = (
        "employee",
        "manager",
        "approver",
        "administrator",
        "announcement",
        "cancellation",
        "leave type",
        "leave dates",
        "date / time",
        "filed by",
        "checklist",
    )
    compact_terms = (
        "id",
        "days",
        "hours",
        "status",
        "plan",
        "order",
        "required",
        "pinned",
        "result",
    )

    if any(term in label for term in wide_terms):
        return 220
    if any(term in label for term in medium_terms):
        return 160
    if label in compact_terms or len(label) <= 6:
        return 100
    if len(label) <= 12:
        return 125
    if len(label) <= 18:
        return 150
    return 180


def _pixel_width(value: object) -> int | None:
    """Return the integer part of a simple CSS pixel width when available."""

    match = re.fullmatch(r"\s*(\d+)px\s*", str(value or ""), flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def render_admin_table(
    rows: Sequence[Mapping[str, object]],
    *,
    key: str,
    min_width: int = 900,
    column_widths: Sequence[str] | None = None,
    compact: bool = False,
    max_height: int | None = None,
) -> None:
    """Render a responsive wrapped table using HR theme variables.

    Args:
        rows: Ordered dictionaries containing table values.
        key: Unique page/table identifier used only for CSS scoping.
        min_width: Minimum table width before horizontal scrolling.
        column_widths: Optional CSS widths matching the column order.
        compact: Use slightly smaller padding for metadata tables.
        max_height: Optional fixed scroll-box height for long tables.
    """

    if not rows:
        return

    table_class = (
        "hr-admin-table-"
        + _safe_key(key)
    )
    shell_class = (
        "hr-admin-table-shell-"
        + _safe_key(key)
    )

    headers = list(rows[0].keys())

    header_html = "".join(
        f"<th>{escape(str(header))}</th>"
        for header in headers
    )

    body_html = "".join(
        "<tr>"
        + "".join(
            f"<td>{_cell_html(row.get(header, ''))}</td>"
            for header in headers
        )
        + "</tr>"
        for row in rows
    )

    # Every column receives a readable minimum width.  Explicit widths remain
    # preferred hints, while omitted widths fall back to a header-aware value.
    # This is especially important when a caller supplies widths for only the
    # first few columns of a wider table.
    preferred_widths = list(column_widths or ())
    column_minimums: list[int] = []
    rules: list[str] = []

    for index, header in enumerate(headers, start=1):
        fallback_width = _recommended_column_width(header)
        explicit_width = (
            preferred_widths[index - 1]
            if index - 1 < len(preferred_widths)
            else None
        )
        explicit_pixels = _pixel_width(explicit_width)
        minimum_pixels = max(
            fallback_width,
            explicit_pixels or 0,
        )
        column_minimums.append(minimum_pixels)

        width_declaration = (
            f"width: {escape(str(explicit_width))};"
            if explicit_width is not None
            else ""
        )
        rules.append(
            f"""
            .{table_class} th:nth-child({index}),
            .{table_class} td:nth-child({index}) {{
                {width_declaration}
                min-width: {minimum_pixels}px;
            }}
            """
        )

    width_rules = "\n".join(rules)
    effective_min_width = max(
        int(min_width),
        sum(column_minimums),
    )

    vertical_padding = "9px" if compact else "12px"
    horizontal_padding = "11px" if compact else "14px"
    font_size = "0.84rem" if compact else "0.88rem"

    vertical_scroll_rules = ""

    if max_height is not None:
        safe_height = max(160, int(max_height))
        vertical_scroll_rules = f"""
            max-height: {safe_height}px;
            overflow-y: scroll;
            scrollbar-gutter: stable;
            scrollbar-width: auto;
            scrollbar-color: var(--hr-primary) #E5EAF2;
        """

    html = f"""
    <style>
        .{shell_class} {{
            width: 100%;
            max-width: 100%;
            overflow-x: auto;
            {vertical_scroll_rules}
            border: 1px solid var(--hr-border);
            border-radius: 14px;
            background: var(--hr-surface);
            box-shadow: var(--hr-shadow);
        }}

        .{shell_class}::-webkit-scrollbar {{
            width: 12px;
            height: 12px;
        }}

        .{shell_class}::-webkit-scrollbar-track {{
            background: #E5EAF2;
            border-radius: 999px;
        }}

        .{shell_class}::-webkit-scrollbar-thumb {{
            min-height: 44px;
            background: var(--hr-primary);
            border: 2px solid #E5EAF2;
            border-radius: 999px;
        }}

        .{shell_class}::-webkit-scrollbar-thumb:hover {{
            background: var(--hr-primary-hover);
        }}

        .{shell_class}::-webkit-scrollbar-corner {{
            background: #E5EAF2;
        }}

        .{table_class} {{
            width: 100%;
            min-width: {effective_min_width}px;
            border-collapse: separate;
            border-spacing: 0;
            table-layout: auto;
            color: var(--hr-text-primary);
            background: var(--hr-surface);
            font-size: {font_size};
        }}

        .{table_class} th {{
            position: sticky;
            top: 0;
            z-index: 2;
            padding: {vertical_padding} {horizontal_padding};
            color: var(--hr-text-primary);
            background: var(--hr-surface-secondary);
            border-right: 1px solid var(--hr-border);
            border-bottom: 1px solid var(--hr-border);
            text-align: left;
            vertical-align: top;
            white-space: normal;
            overflow-wrap: break-word;
            word-break: normal;
            line-height: 1.35;
            font-weight: 700;
        }}

        .{table_class} td {{
            padding: {vertical_padding} {horizontal_padding};
            color: var(--hr-text-secondary);
            background: var(--hr-surface);
            border-right: 1px solid var(--hr-border);
            border-bottom: 1px solid var(--hr-border);
            text-align: left;
            vertical-align: top;
            white-space: normal;
            overflow-wrap: break-word;
            word-break: normal;
            line-height: 1.45;
            transition:
                color 0.14s ease,
                background-color 0.14s ease;
        }}

        .{table_class} th:last-child,
        .{table_class} td:last-child {{
            border-right: 0;
        }}

        .{table_class} tbody tr:last-child td {{
            border-bottom: 0;
        }}

        .{table_class} tbody tr:hover td {{
            color: var(--hr-text-primary);
            background: var(--hr-primary-soft);
        }}

        {width_rules}
    </style>

    <div class="{shell_class}">
        <table class="{table_class}">
            <thead>
                <tr>{header_html}</tr>
            </thead>
            <tbody>
                {body_html}
            </tbody>
        </table>
    </div>
    """

    st.markdown(
        html,
        unsafe_allow_html=True,
    )



def render_selectable_admin_table(
    rows: Sequence[Mapping[str, object]],
    *,
    key: str,
    height: int = 320,
) -> int | None:
    """Render a fixed-height whole-row clickable table.

    Clicking anywhere on a data row selects that row and returns its index.
    This native selectable table is used only where a row click must trigger
    an in-app action such as a secure file-preview dialog. Other administration
    tables continue to use ``render_admin_table`` for the custom HTML layout.
    """

    if not rows:
        return None

    frame = pd.DataFrame(list(rows))
    scoped_key = _safe_key(key)

    # Keep selectable grids visually aligned with the custom HR tables.
    # Streamlit supports pandas Styler cell colors and font weights. The
    # scoped CSS below matches the surrounding border, radius, and shadow
    # without overriding the application's centralized runtime theme.
    st.markdown(
        f"""
        <style>
            div[class*="st-key-{scoped_key}"] [data-testid="stDataFrame"] {{
                overflow: hidden !important;
                border: 1px solid var(--hr-border) !important;
                border-radius: 14px !important;
                background: var(--hr-surface) !important;
                box-shadow: var(--hr-shadow) !important;
            }}

            /* Streamlit renders the selectable grid on a canvas. A pointer
               cursor makes the whole-row preview action discoverable without
               changing its built-in keyboard and row-selection behavior. */
            div[class*="st-key-{scoped_key}"] [data-testid="stDataFrame"],
            div[class*="st-key-{scoped_key}"] [data-testid="stDataFrame"] canvas,
            div[class*="st-key-{scoped_key}"] [data-testid="stDataFrame"] [role="grid"],
            div[class*="st-key-{scoped_key}"] [data-testid="stDataFrame"] [role="gridcell"] {{
                cursor: pointer !important;
            }}
        </style>
        """,
        unsafe_allow_html=True,
    )

    styled_frame = (
        frame.style
        .set_properties(
            **{
                "background-color": "#FFFFFF",
                "color": "#5C6680",
                "border-color": "#E3E7F0",
            }
        )
        .set_table_styles(
            [
                {
                    "selector": "th",
                    "props": [
                        ("background-color", "#F3F5FA"),
                        ("color", "#10172A"),
                        ("font-weight", "700"),
                        ("border-color", "#E3E7F0"),
                    ],
                }
            ]
        )
    )

    visible_height = min(
        max(96, int(height)),
        44 + (len(frame) * 42),
    )

    event = st.dataframe(
        styled_frame,
        key=key,
        hide_index=True,
        width="stretch",
        height=visible_height,
        row_height=42,
        on_select="rerun",
        # Streamlit's single-row mode selects a row when any of its data cells
        # is clicked; the selector at the left is only a visible state marker.
        selection_mode="single-row",
    )

    selection = getattr(event, "selection", None)
    selected_rows = getattr(selection, "rows", []) if selection else []

    if not selected_rows and isinstance(event, dict):
        selected_rows = event.get("selection", {}).get("rows", [])

    if not selected_rows:
        return None

    selected_index = int(selected_rows[0])
    return selected_index if 0 <= selected_index < len(rows) else None
