"""로그인 화면 (공통) — 사번만 입력 (screens.md §1).

보안 한계: 사번 단독 로그인은 타인 사번을 아는 누구나 로그인할 수 있다.
사내 구성원 대상으로 수용하며, 추후 사번+이름 확인 또는 PIN 으로 보완한다.
"""
import streamlit as st

from modules import auth, config, db, ui


def render() -> None:
    with ui.centered((1, 1.4, 1)):
        st.write("")
        st.write("")
        with st.container(border=True):
            st.markdown(
                f"<div class='page-title' style='color:#1E3A6E'>{config.APP_NAME}</div>"
                "<div class='page-desc'>사번을 입력해 로그인하세요.</div>",
                unsafe_allow_html=True,
            )

            with st.form("login_form"):
                emp_no = st.text_input("사번", placeholder="예: 1001")
                submitted = st.form_submit_button("로그인", width="stretch", type="primary")

            if submitted:
                user, err = auth.login(emp_no)
                if err:
                    st.error(err)
                else:
                    st.rerun()

        if db.is_sample_mode():
            st.caption("로컬 데이터 모드 접속 사번 — 1001: 관리자 · 1002: 조장 · 1003: 사원")
