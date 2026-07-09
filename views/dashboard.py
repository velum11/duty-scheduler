"""홈 대시보드 (ADMIN).

요약 카드(등록 현황) + 오늘 근무 현황 + 이달 근무형태 분포.
데이터는 db 파사드를 통해 조회한다 (샘플/Supabase 공통).
"""
from datetime import date

import pandas as pd
import streamlit as st

from modules import db, ui


def render(user: dict) -> None:
    ui.page_header("dashboard")

    users = db.get_users()
    active_users = users[users["is_active"]]
    depts = db.get_departments()
    wt = db.work_types_map()
    scheds = db.get_schedules()

    today = date.today()
    prefix = today.strftime("%Y-%m")
    month_rows = (
        scheds[scheds["duty_date"].str.startswith(prefix)] if not scheds.empty else scheds
    )

    ui.summary_cards([
        ("등록 인원", f"{len(active_users)}명"),
        ("부서", f"{int(depts['is_active'].sum())}개"),
        ("근무형태", f"{len(wt)}개"),
        (f"{today.month}월 근무 데이터", f"{len(month_rows)}건"),
    ])
    st.write("")

    left, right = st.columns([2, 1])

    # 오늘 근무 현황
    with left, ui.card():
        st.markdown(
            f"<b>오늘 근무 현황</b> <span class='duty-name'>{today.month}/{today.day}({ui.weekday_kr(today)})</span>",
            unsafe_allow_html=True,
        )
        today_rows = (
            scheds[scheds["duty_date"] == today.isoformat()] if not scheds.empty else scheds
        )
        if today_rows.empty:
            st.markdown(
                "<div class='duty-name' style='padding:1.4rem 0'>오늘 등록된 근무가 없습니다.</div>",
                unsafe_allow_html=True,
            )
        else:
            merged = today_rows.merge(users, on="emp_no", how="left")
            merged = merged.sort_values(["dept_code", "team_code", "emp_no"])
            view = pd.DataFrame({
                "성명": merged["name"],
                "부서": merged["dept_code"].map(db.dept_name),
                "조/팀": [db.team_name(d, t) for d, t in zip(merged["dept_code"], merged["team_code"])],
                "근무": merged["work_type_code"],
            })
            styled = view.style.map(
                lambda v: (
                    f"background-color:{wt[str(v).strip()]['color']}26; font-weight:600"
                    if str(v).strip() in wt else ""
                ),
                subset=["근무"],
            )
            st.dataframe(styled, width="stretch", hide_index=True,
                         height=min(38 * len(view) + 40, 420))

    # 이달 근무형태 분포
    with right, ui.card():
        st.markdown(f"<b>{today.month}월 근무형태 분포</b>", unsafe_allow_html=True)
        if month_rows.empty:
            st.markdown(
                "<div class='duty-name' style='padding:1.4rem 0'>이달 등록된 근무가 없습니다.</div>",
                unsafe_allow_html=True,
            )
        else:
            counts = month_rows["work_type_code"].value_counts()
            lines = "".join(
                "<div style='display:flex;justify-content:space-between;align-items:center;"
                "padding:0.28rem 0.1rem;border-bottom:1px solid #F0F2F5'>"
                + ui.badge_html(code, wt.get(code, {}).get("color"), wt.get(code, {}).get("name"))
                + f"<span style='font-weight:600;color:#26282B'>{n}건</span></div>"
                for code, n in counts.items()
            )
            st.markdown(lines, unsafe_allow_html=True)
