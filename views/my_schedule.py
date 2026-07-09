"""내 근무표 (개인 조회, 모바일 폭 기준).

본인 근무표를 월 단위 달력으로 조회 + 오늘 근무 강조 + 월간 집계 (DESIGN.md §17).
"""
import calendar
from datetime import date
from html import escape

import pandas as pd
import streamlit as st

from modules import db, ui


def _month_label(ym) -> str:
    return f"{ym[0]}.{ym[1]:02d}"


def _work_label(code: str, short_labels: dict) -> str:
    if code in ("주", "야", "OFF"):
        return code
    short_label = short_labels.get(code)
    if pd.notna(short_label) and str(short_label).strip():
        return str(short_label)
    return str(code)


def _calendar_html(month_df: pd.DataFrame, ym: tuple, wt: dict, short_labels: dict) -> str:
    year, month = ym
    first_weekday, days_in_month = calendar.monthrange(year, month)
    duty_by_date = {
        r["d"]: r["work_type_code"]
        for _, r in month_df.drop_duplicates("d", keep="first").iterrows()
    }

    cells = []
    for _ in range(first_weekday):
        cells.append("<div class='my-cal-cell my-cal-empty'></div>")

    today = date.today()
    for day in range(1, days_in_month + 1):
        d = date(year, month, day)
        code = duty_by_date.get(d)
        info = wt.get(code, {}) if code else {}
        color = str(info.get("color") or "#9AA0A6")
        label = escape(_work_label(code, short_labels)) if code else ""
        classes = ["my-cal-cell"]
        if d == today:
            classes.append("is-today")
        if d.weekday() == 5:
            classes.append("is-sat")
        elif d.weekday() == 6:
            classes.append("is-sun")

        duty_html = (
            f"<div class='my-cal-duty' style='background:{escape(color)}'>{label}</div>"
            if code
            else "<div class='my-cal-duty is-empty'>&nbsp;</div>"
        )
        cells.append(
            f"<div class='{' '.join(classes)}'>"
            f"<div class='my-cal-day'>{day}</div>"
            f"{duty_html}"
            "</div>"
        )

    while len(cells) % 7:
        cells.append("<div class='my-cal-cell my-cal-empty'></div>")

    weekdays = "".join(f"<div class='my-cal-weekday'>{w}</div>" for w in ["월", "화", "수", "목", "금", "토", "일"])
    return f"""
<style>
.my-schedule-calendar {{
    width: 100%;
    overflow: hidden;
}}
.my-cal-grid {{
    display: grid;
    grid-template-columns: repeat(7, minmax(0, 1fr));
    gap: 3px;
}}
.my-cal-weekday {{
    text-align: center;
    font-size: 0.76rem;
    font-weight: 700;
    color: #5F6368;
    padding: 2px 0 4px;
}}
.my-cal-weekday:nth-child(6) {{ color: #1E6FD9; }}
.my-cal-weekday:nth-child(7) {{ color: #D93025; }}
.my-cal-cell {{
    min-width: 0;
    min-height: 48px;
    border: 1px solid #E5E7EB;
    border-radius: 6px;
    background: #FFFFFF;
    padding: 4px 3px;
    text-align: center;
}}
.my-cal-empty {{
    border-color: transparent;
    background: transparent;
}}
.my-cal-day {{
    font-size: 0.72rem;
    line-height: 1;
    color: #26282B;
    margin-bottom: 4px;
}}
.my-cal-cell.is-sat .my-cal-day {{ color: #1E6FD9; }}
.my-cal-cell.is-sun .my-cal-day {{ color: #D93025; }}
.my-cal-cell.is-today {{
    border: 2px solid #111827;
    padding: 3px 2px;
}}
.my-cal-duty {{
    width: 100%;
    min-height: 20px;
    border-radius: 999px;
    color: #FFFFFF;
    font-size: 0.68rem;
    font-weight: 700;
    line-height: 20px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}}
.my-cal-duty.is-empty {{
    background: transparent;
}}
</style>
<div class='my-schedule-calendar'>
  <div class='my-cal-grid my-cal-head'>{weekdays}</div>
  <div class='my-cal-grid'>{''.join(cells)}</div>
</div>
"""


def render(user: dict) -> None:
    ui.page_title(f"{user['name']}님의 근무표", "본인 근무를 월 단위로 확인하세요.")

    sched = db.get_user_schedules(user["emp_no"])
    if sched.empty:
        with ui.card():
            st.info("등록된 근무가 없습니다.")
        return

    wt = db.work_types_map()
    work_types_df = db.get_work_types()
    short_labels = dict(zip(work_types_df["code"], work_types_df["short_label"])) if not work_types_df.empty else {}
    sched = sched.copy()
    sched["d"] = pd.to_datetime(sched["duty_date"]).dt.date

    months = sorted({(d.year, d.month) for d in sched["d"]})
    if st.session_state.get("my_month") not in months:
        st.session_state.my_month = months[-1]  # 데이터가 있는 최신 월
    ym = st.session_state.my_month
    idx = months.index(ym)

    # 월 이동 (◀ 2026.07 ▶)
    c_prev, c_mid, c_next = st.columns([1, 3, 1])
    if c_prev.button("◀", width="stretch", disabled=idx == 0):
        st.session_state.my_month = months[idx - 1]
        st.rerun()
    c_mid.markdown(
        f"<h4 style='text-align:center;margin:0'>{_month_label(ym)}</h4>",
        unsafe_allow_html=True,
    )
    if c_next.button("▶", width="stretch", disabled=idx == len(months) - 1):
        st.session_state.my_month = months[idx + 1]
        st.rerun()

    month_df = sched[[(d.year, d.month) == ym for d in sched["d"]]].sort_values("d")

    # 오늘 근무 강조 카드
    today = date.today()
    trow = month_df[month_df["d"] == today]
    with ui.card():
        head = f"오늘 {today.month}/{today.day}({ui.weekday_kr(today)})"
        if not trow.empty:
            code = trow.iloc[0]["work_type_code"]
            info = wt.get(code, {})
            st.markdown(
                f"**{head}**&nbsp;&nbsp;" + ui.badge_html(code, info.get("color"), info.get("name")),
                unsafe_allow_html=True,
            )
        else:
            st.markdown(f"**{head}** — 오늘 등록된 근무가 없습니다.")

    # 월간 달력
    st.markdown("##### 이달 근무")
    st.markdown(_calendar_html(month_df, ym, wt, short_labels), unsafe_allow_html=True)

    # 월간 집계
    counts = month_df["work_type_code"].value_counts()
    agg = " · ".join(f"{code} {n}" for code, n in counts.items())
    st.markdown("##### 이달 집계")
    st.caption(agg)
