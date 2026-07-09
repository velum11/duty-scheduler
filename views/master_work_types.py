"""기준정보 — 근무형태 관리 화면."""
import pandas as pd
import streamlit as st

from modules import db, ui
from views.workspace import grid_height, master_download, run_query


def render(user: dict) -> None:
    ui.page_header("master_work_types")

    with ui.card():
        c1, c2 = st.columns([1.4, 0.9], vertical_alignment="bottom")
        active = c1.selectbox("사용 여부", ["사용 중", "전체"], key="mw_active")
        clicked = c2.button("조회", key="mw_go", type="primary", width="stretch")

    q = run_query("master_work_types", clicked, {"active": active})
    if not q:
        ui.empty_state("조회 조건을 선택한 후 조회하세요.")
        return

    df = db.get_work_types()
    if q["active"] == "사용 중":
        df = df[df["is_active"]]

    ui.summary_cards([
        ("근무형태", f"{len(df)}개"),
        ("실근무 코드", f"{int(df['is_work'].sum())}개"),
        ("휴무·휴가 코드", f"{int((~df['is_work']).sum())}개"),
    ])
    st.write("")

    view = pd.DataFrame({
        "코드": df["code"],
        "명칭": df["name"],
        "시작": df["start_time"],
        "종료": df["end_time"],
        "색상": df["color"],
        "실근무": df["is_work"].map({True: "실근무", False: "휴무성"}),
        "표시순서": df["sort_order"],
        "사용": df["is_active"].map({True: "사용", False: "미사용"}),
    })
    st.dataframe(view, width="stretch", hide_index=True, height=grid_height(len(view)))

    badges = "".join(ui.badge_html(r["code"], r["color"]) for _, r in df.iterrows())
    st.markdown(f"<div class='duty-legend'>{badges}</div>", unsafe_allow_html=True)
    master_download(view, "근무형태목록", "mw_dl")
