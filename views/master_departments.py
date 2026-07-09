"""기준정보 — 부서 관리 화면."""
import pandas as pd
import streamlit as st

from modules import db, ui
from views.workspace import grid_height, master_download, run_query


def render(user: dict) -> None:
    ui.page_header("master_departments")

    users = db.get_users()
    with ui.card():
        c1, c2 = st.columns([1.4, 0.9], vertical_alignment="bottom")
        active = c1.selectbox("사용 여부", ["사용 중", "전체"], key="md_active")
        clicked = c2.button("조회", key="md_go", type="primary", width="stretch")

    q = run_query("master_departments", clicked, {"active": active})
    if not q:
        ui.empty_state("조회 조건을 선택한 후 조회하세요.")
        return

    df = db.get_departments()
    if q["active"] == "사용 중":
        df = df[df["is_active"]]
    headcount = users[users["is_active"]].groupby("dept_code").size()

    ui.summary_cards([
        ("부서", f"{len(df)}개"),
        ("사용 중", f"{int(df['is_active'].sum())}개"),
        ("소속 인원", f"{int(headcount.reindex(df['dept_code']).fillna(0).sum())}명"),
    ])
    st.write("")

    view = pd.DataFrame({
        "부서코드": df["dept_code"],
        "부서명": df["dept_name"],
        "표시순서": df["sort_order"],
        "소속 인원": df["dept_code"].map(headcount).fillna(0).astype(int),
        "사용": df["is_active"].map({True: "사용", False: "미사용"}),
    })
    st.dataframe(view, width="stretch", hide_index=True, height=grid_height(len(view)))
    master_download(view, "부서목록", "md_dl")
