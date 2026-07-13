"""역할별 홈 대시보드.

ADMIN/MANAGER는 등록 현황, USER는 본인 근무 현황을 표시한다.
데이터는 db 파사드를 통해 조회한다 (샘플/Supabase 공통).
"""
from datetime import date
from html import escape

import pandas as pd
import streamlit as st

from modules import db, ui


def render(user: dict) -> None:
    if str(user.get("role", "")).strip().upper() == "USER":
        _render_user(user)
        return

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
        ui.panel_head("오늘 근무 현황", f"{today.month}/{today.day}({ui.weekday_kr(today)})")
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
        ui.panel_head(f"{today.month}월 근무형태 분포")
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


def _render_user(user: dict) -> None:
    """현재 저장 데이터로 계산 가능한 USER 개인 근무 요약."""
    ui.page_title("대시보드", "내 근무 현황을 확인합니다.")
    today = date.today()
    emp_no = str(user.get("emp_no", "")).strip()

    try:
        rows = db.get_user_schedules(emp_no).copy()
        month_rows = db.get_month_schedules(emp_no, today.year, today.month)
        work_types = {
            str(row["code"]): row.to_dict()
            for _, row in db.get_work_types().iterrows()
        }
        rows["date"] = pd.to_datetime(rows["duty_date"], errors="coerce").dt.date
    except Exception:
        st.error("근무 정보를 불러오지 못했습니다. 잠시 후 다시 확인하세요.")
        return

    today_rows = rows[rows["date"] == today] if not rows.empty else rows
    today_code = "미등록" if today_rows.empty else str(today_rows.iloc[0]["work_type_code"])

    future = rows[rows["date"] > today].sort_values("date") if not rows.empty else rows
    if future.empty:
        next_label, next_value = "다음 근무", "데이터 없음"
    else:
        next_row = future.iloc[0]
        next_date = next_row["date"]
        next_label = "내일 근무" if (next_date - today).days == 1 else f"다음 근무 ({next_date.month}/{next_date.day})"
        next_value = str(next_row["work_type_code"])

    counts = {"주간": 0, "야간": 0, "OFF": 0}
    for code, count in month_rows["work_type_code"].value_counts().items():
        group = db.classify_work_group(str(code), work_types.get(str(code), {}))
        if group in counts:
            counts[group] += int(count)

    items = [
        ("오늘 내 근무", today_code),
        (next_label, next_value),
        ("이번 달 주간", f"{counts['주간']}회"),
        ("이번 달 야간", f"{counts['야간']}회"),
        ("이번 달 OFF", f"{counts['OFF']}회"),
    ]
    cards = "".join(
        f"<div class='sum-card'><div class='sum-value'>{escape(value)}</div>"
        f"<div class='sum-label'>{escape(label)}</div></div>"
        for label, value in items
    )
    st.markdown(
        """
<style>
.user-dashboard-grid { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:.6rem; }
.user-dashboard-grid .sum-value { font-size:1.18rem; overflow-wrap:anywhere; }
@media (max-width:768px) {
  .user-dashboard-grid { grid-template-columns:repeat(2,minmax(0,1fr)); gap:.45rem; }
  .user-dashboard-grid .sum-card:first-child { grid-column:span 1; }
  .user-dashboard-grid .sum-value { font-size:1.05rem; }
}
</style>
""" + f"<div class='user-dashboard-grid'>{cards}</div>",
        unsafe_allow_html=True,
    )
