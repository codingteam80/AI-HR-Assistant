"""Responsive monthly DTR matrix with project-standard table styling."""

from html import escape
from decimal import Decimal

import streamlit as st

from services.attendance_service import (
    ATTENDANCE_COLORS,
    WEEKEND_COLOR,
    AttendanceMatrix,
    AttendanceService,
)


ATTENDANCE_VISIBLE_ROWS = 7
ATTENDANCE_HEADER_HEIGHT = 54
ATTENDANCE_ROW_HEIGHT = 82
ATTENDANCE_DATE_COLUMN_WIDTH = 170
ATTENDANCE_EMPLOYEE_COLUMN_WIDTH = 190
ATTENDANCE_VIEWPORT_HEIGHT = (
    ATTENDANCE_HEADER_HEIGHT
    + (ATTENDANCE_VISIBLE_ROWS * ATTENDANCE_ROW_HEIGHT)
)


def render_attendance_matrix(
    matrix: AttendanceMatrix,
    *,
    service: AttendanceService,
    key: str,
) -> None:
    """Render employee rows and all dates, with sticky identity column."""

    if not matrix.employees:
        st.info("No employee attendance records are available for this view.")
        return

    headers = ["<th class='employee'>Employee Name</th>"]
    for day in matrix.dates:
        scheduled_workday = matrix.scheduled_workdays.get(
            day,
            day.weekday() < 5,
        )
        style = f"background:{WEEKEND_COLOR};" if not scheduled_workday else ""
        headers.append(
            f"<th style='{style}'>{day:%Y/%m/%d}<small>{day:%a}</small></th>"
        )

    body: list[str] = []
    for employee in matrix.employees:
        cells = [f"<td class='employee'>{escape(employee.full_name)}</td>"]
        for day in matrix.dates:
            record = matrix.records.get((employee.id, day))
            scheduled_workday = matrix.scheduled_workdays.get(
                day,
                day.weekday() < 5,
            )
            background = WEEKEND_COLOR if not scheduled_workday else "#FFFFFF"
            content = ""
            if record is not None:
                if record.work_status:
                    background = ATTENDANCE_COLORS.get(record.work_status, background)
                parts = []
                leave_code = (
                    service._leave_code(record.leave_request)
                    if record.leave_request is not None
                    else None
                )
                if record.leave_duration_code in {"90501", "90502"}:
                    half = "AM" if record.leave_duration_code == "90501" else "PM"
                    parts.append(f"<strong>{half} {escape(leave_code or 'LEAVE')}</strong>")
                    background = (
                        "linear-gradient(135deg,#FFCCFF 0%,#FFCCFF 48%,"
                        f"{ATTENDANCE_COLORS.get(record.work_status or '', '#FFFFFF')} 52%,"
                        f"{ATTENDANCE_COLORS.get(record.work_status or '', '#FFFFFF')} 100%)"
                    )
                elif record.work_status:
                    parts.append(f"<strong>{escape(record.work_status)}</strong>")

                for index, attendance_session in enumerate(record.sessions, start=1):
                    rounded_in = service.to_local(attendance_session.rounded_time_in)
                    rounded_out = service.to_local(attendance_session.rounded_time_out)
                    actual_in = service.to_local(attendance_session.actual_time_in)
                    actual_out = service.to_local(attendance_session.actual_time_out)
                    session_text = (
                        f"S{index} {escape(attendance_session.work_status)} "
                        + (f"{rounded_in:%H:%M}–" if rounded_in else "—–")
                        + (f"{rounded_out:%H:%M}" if rounded_out else "OPEN")
                    )
                    if actual_in != rounded_in or actual_out != rounded_out:
                        session_text += (
                            "<small>actual "
                            + (f"{actual_in:%H:%M}–" if actual_in else "—–")
                            + (f"{actual_out:%H:%M}" if actual_out else "OPEN")
                            + "</small>"
                        )
                    parts.append(session_text)
                if record.sessions:
                    parts.append(
                        f"<small>Work {record.total_hours}h · "
                        f"Leave {record.leave_hours}h · OT {record.ot_hours}h"
                        + (
                            f" · UT {record.undertime_hours}h"
                            if Decimal(record.undertime_hours or 0) > 0
                            else ""
                        )
                        + "</small>"
                    )
                content = "<br>".join(parts)
            cells.append(f"<td style='background:{background}'>{content}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")

    css_key = "".join(character for character in key if character.isalnum()) or "dtr"
    st.markdown(
        f"""
        <style>
        .attendance-shell-{css_key} {{
            overflow:auto; max-height:{ATTENDANCE_VIEWPORT_HEIGHT}px;
            border:1px solid var(--hr-border);
            border-radius:14px; background:#fff; box-shadow:var(--hr-shadow);
        }}
        .attendance-{css_key} {{
            border-collapse:separate; border-spacing:0; min-width:max-content;
            color:#10172A; font-size:.78rem;
        }}
        .attendance-{css_key} th, .attendance-{css_key} td {{
            width:{ATTENDANCE_DATE_COLUMN_WIDTH}px;
            min-width:{ATTENDANCE_DATE_COLUMN_WIDTH}px;
            padding:9px 8px; text-align:center;
            border-right:1px solid #D8DEEA; border-bottom:1px solid #D8DEEA;
            vertical-align:middle; line-height:1.35; box-sizing:border-box;
        }}
        .attendance-{css_key} th {{
            position:sticky; top:0; z-index:3; background:#F1F4F9;
            height:{ATTENDANCE_HEADER_HEIGHT}px; font-weight:700;
        }}
        .attendance-{css_key} tbody tr {{
            height:{ATTENDANCE_ROW_HEIGHT}px;
        }}
        .attendance-{css_key} th small, .attendance-{css_key} td small {{
            display:block; margin-top:3px; color:#3F4A61;
        }}
        .attendance-{css_key} .employee {{
            position:sticky; left:0; z-index:2;
            width:{ATTENDANCE_EMPLOYEE_COLUMN_WIDTH}px;
            min-width:{ATTENDANCE_EMPLOYEE_COLUMN_WIDTH}px;
            text-align:left; background:#FFFFFF; font-weight:700;
        }}
        .attendance-{css_key} th.employee {{z-index:4;background:#F1F4F9}}
        </style>
        <div class="attendance-shell-{css_key}">
          <table class="attendance-{css_key}">
            <thead><tr>{''.join(headers)}</tr></thead>
            <tbody>{''.join(body)}</tbody>
          </table>
        </div>
        """,
        unsafe_allow_html=True,
    )
