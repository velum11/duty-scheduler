"""로그인 화면 (공통) — 사번 + 비밀번호.

초기 비밀번호는 사번이며, 로그인 직후 변경 화면(views/password_change)으로 강제
이동한다. 그 게이트는 app.py 가 app_shell 앞에서 건다.
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
                "<div class='page-desc'>사번과 비밀번호를 입력해 로그인하세요.</div>",
                unsafe_allow_html=True,
            )

            with st.form("login_form"):
                emp_no = st.text_input("사번", placeholder="예: 1001")
                password = st.text_input("비밀번호", type="password")
                submitted = st.form_submit_button("로그인", width="stretch", type="primary")

            if submitted:
                user, err = auth.login(emp_no, password)
                if err:
                    st.error(err)
                else:
                    st.rerun()

            if config.BETA_SKIP_FORCED_PASSWORD_CHANGE:
                st.caption("비밀번호는 본인 사번과 같습니다.")
            else:
                st.caption(
                    "처음 로그인하거나 비밀번호를 초기화한 경우, 비밀번호는 사번과 같습니다. "
                    "로그인 후 바로 변경해야 합니다."
                )

        if db.is_sample_mode():
            st.caption("로컬 데이터 모드 접속 사번 — 1001: 관리자 · 1002: 조장 · 1003: 사원")
