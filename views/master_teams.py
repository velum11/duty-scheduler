"""기준정보 — 조 관리 화면."""
import pandas as pd
import streamlit as st

from modules import db, ui
from views.workspace import ALL, grid_height, master_download, run_query


def render(user: dict) -> None:
    ui.page_header("master_teams")

    depts = db.get_departments()
    users = db.get_users()
    dept_names = {r["dept_code"]: r["dept_name"] for _, r in depts.iterrows()}

    with ui.card():
        c1, c2 = st.columns([1.6, 0.9], vertical_alignment="bottom")
        dept = c1.selectbox(
            "부서", [ALL] + list(dept_names), format_func=lambda c: dept_names.get(c, c),
            key="mt_dept",
        )
        clicked = c2.button("조회", key="mt_go", type="primary", width="stretch")

    q = run_query("master_teams", clicked, {"dept": dept})
    if not q:
        ui.empty_state("조회 조건을 선택한 후 조회하세요.")
        return

    df = db.get_teams()
    if q["dept"] != ALL:
        df = df[df["dept_code"] == q["dept"]]
    active_users = users[users["is_active"]]
    headcount = active_users.groupby(["dept_code", "team_code"]).size()

    ui.summary_cards([
        ("조", f"{len(df)}개"),
        ("부서", f"{df['dept_code'].nunique()}개"),
        ("소속 인원", f"{int(sum(headcount.get((d, t), 0) for d, t in zip(df['dept_code'], df['team_code'])))}명"),
    ])
    st.write("")

    view = pd.DataFrame({
        "부서": df["dept_code"].map(db.dept_name),
        "조코드": df["team_code"],
        "조명": df["team_name"],
        "표시순서": df["sort_order"],
        "소속 인원": [int(headcount.get((d, t), 0)) for d, t in zip(df["dept_code"], df["team_code"])],
        "사용": df["is_active"].map({True: "사용", False: "미사용"}),
    })
    st.dataframe(view, width="stretch", hide_index=True, height=grid_height(len(view)))
    master_download(view, "조목록", "mt_dl")
