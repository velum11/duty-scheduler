"""WorkOps MES 목업 — Streamlit 구현 가능성 판정 데모.

    streamlit run demo/app.py

목적은 기능이 아니라 **판정**이다. `docs/mockup/WorkOps 최종 목업.dc.html` 을
Streamlit 으로 얼마나 재현할 수 있는지 셸 + 3화면으로 재 본다.

- 근무 현황   DASHBOARD   지표 표 + 명단 표
- 근무표 편성 MATRIX_EDIT 31일 격자 · sticky 신원 열  ← 가장 어려운 화면
- 사용자 관리 EDIT_GRID   기준정보 12열 표

운영 앱(`app.py`)과 완전히 분리돼 있다. DB 를 붙이지 않고 `demo/data.py` 의
목업 표본만 쓴다.
"""
import streamlit as st

import screens
import ui


def main() -> None:
    ui.page_setup()
    ui.inject_css()

    page = ui.sidebar_nav()
    ui.top_bars(ui.TITLES.get(page, page))

    render = screens.RENDERERS.get(page)
    if render is None:
        ui.placeholder(ui.TITLES.get(page, page))
    else:
        render()


main()
