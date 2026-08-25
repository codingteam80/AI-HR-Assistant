"""Shared Chat Assistant timestamp, report, chart, and export rendering."""

from __future__ import annotations

from datetime import datetime
import json
import re
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from config.settings import get_settings
from modules.reports.chat_assistant_report import (
    build_chat_report_excel,
    build_chat_report_pdf,
)


def current_assistant_timestamp() -> dict[str, str]:
    """Return one timezone-aware timestamp for a completed assistant answer."""

    timezone_name = get_settings().display_timezone
    now = datetime.now(ZoneInfo(timezone_name))
    return {
        "iso": now.isoformat(),
        "display": now.strftime("%Y/%m/%d • %I:%M %p"),
        "timezone": timezone_name,
    }


def _safe_filename(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip()).strip("_")
    return clean or "hr_report"


@st.cache_data(show_spinner=False)
def _cached_exports(report_json: str) -> tuple[bytes, bytes]:
    report = json.loads(report_json)
    return build_chat_report_excel(report), build_chat_report_pdf(report)


def _render_chart(report: dict, *, key_prefix: str) -> None:
    chart = dict(report.get("chart") or {})
    data = list(chart.get("data") or [])
    if not data:
        return

    st.markdown(f"**{chart.get('title', 'Report Chart')}**")
    frame = pd.DataFrame(data)
    chart_type = str(chart.get("type", "bar")).casefold()
    value_label = str(chart.get("value_label", "Value"))
    category_label = str(chart.get("category_label", "Category"))

    if chart_type == "line":
        st.line_chart(
            frame,
            x="label",
            y="value",
            x_label=category_label,
            y_label=value_label,
            width="stretch",
        )
        return

    if chart_type in {"pie", "donut"}:
        mark: dict[str, object] = {"type": "arc", "tooltip": True}
        if chart_type == "donut":
            mark["innerRadius"] = 60
        spec = {
            "data": {"values": data},
            "mark": mark,
            "encoding": {
                "theta": {
                    "field": "value",
                    "type": "quantitative",
                    "title": value_label,
                },
                "color": {
                    "field": "label",
                    "type": "nominal",
                    "title": category_label,
                },
                "tooltip": [
                    {"field": "label", "type": "nominal", "title": category_label},
                    {"field": "value", "type": "quantitative", "title": value_label},
                ],
            },
        }
        st.vega_lite_chart(
            spec=spec,
            width="stretch",
            key=f"{key_prefix}_pie",
        )
        return

    horizontal = len(data) >= 6
    st.bar_chart(
        frame,
        x="value" if horizontal else "label",
        y="label" if horizontal else "value",
        horizontal=horizontal,
        x_label=value_label if horizontal else category_label,
        y_label=category_label if horizontal else value_label,
        width="stretch",
    )


def render_chat_report(report: dict | None, *, key_prefix: str) -> None:
    """Render one deterministic report, chart, detail table, and downloads."""

    if not report:
        return

    _render_chart(report, key_prefix=key_prefix)

    rows = list(report.get("rows") or [])
    columns = list(report.get("columns") or [])
    if rows and columns:
        with st.expander(f"Report Data ({len(rows)} row{'s' if len(rows) != 1 else ''})", expanded=False):
            st.dataframe(
                pd.DataFrame(rows, columns=columns),
                hide_index=True,
                width="stretch",
                height=min(420, 38 + 35 * min(len(rows), 10)),
            )

    report_json = json.dumps(report, sort_keys=True, ensure_ascii=False, default=str)
    excel_bytes, pdf_bytes = _cached_exports(report_json)
    stem = _safe_filename(
        f"{report.get('domain', 'hr')}_{report.get('start_date', '')}_{report.get('end_date', '')}"
    )
    excel_col, pdf_col = st.columns(2)
    with excel_col:
        st.download_button(
            "Download Excel Report",
            data=excel_bytes,
            file_name=f"{stem}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch",
            key=f"{key_prefix}_xlsx",
        )
    with pdf_col:
        st.download_button(
            "Download PDF Report",
            data=pdf_bytes,
            file_name=f"{stem}.pdf",
            mime="application/pdf",
            width="stretch",
            key=f"{key_prefix}_pdf",
        )


def render_assistant_timestamp(timestamp: dict | None) -> None:
    """Render the small accurate date/time line below an assistant answer."""

    if not timestamp:
        return
    display = str(timestamp.get("display", "")).strip()
    timezone_name = str(timestamp.get("timezone", "")).strip()
    if display:
        st.caption(f"{display}{f' · {timezone_name}' if timezone_name else ''}")
