"""내 근무표 (개인 조회, 모바일 폭 기준).

본인 근무표를 월 단위 리스트로 조회 + 오늘 근무 강조 + 월간 집계 (DESIGN.md §17).
"""
from datetime import date

import pandas as pd
import streamlit as st

from modules import db, ui


def _month_label(ym) -> str:
    return f"{ym[0]}.{ym[1]:02d}"


def render(user: dict) -> None:
    ui.page_title(f"{user['name']}님의 근무표", "본인 근무를 월 단위로 확인하세요.")

    sched = db.get_user_schedules(user["emp_no"])
    if sched.empty:
        with ui.card():
            st.info("등록된 근무가 없습니다.")
        return

    wt = db.work_types_map()
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

    # 일자별 리스트
    st.markdown("##### 이달 근무")
    for _, r in month_df.iterrows():
        d = r["d"]
        code = r["work_type_code"]
        info = wt.get(code, {})
        col_date, col_badge = st.columns([1, 2])
        col_date.markdown(
            f"<span style='color:{ui.weekend_color(d)}'>{d.month}/{d.day}({ui.weekday_kr(d)})</span>",
            unsafe_allow_html=True,
        )
        col_badge.markdown(
            ui.badge_html(code, info.get("color"), info.get("name")),
            unsafe_allow_html=True,
        )

    # 월간 집계
    counts = month_df["work_type_code"].value_counts()
    agg = " · ".join(f"{code} {n}" for code, n in counts.items())
    st.markdown("##### 이달 집계")
    st.caption(agg)
