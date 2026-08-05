"""비밀번호 변경 화면 (강제변경 게이트 + 자발적 변경).

로그인은 됐지만 아직 비밀번호를 설정하지 않은 사용자(초기 비밀번호 = 사번)나 ADMIN 이
초기화한 사용자는 이 화면을 지나기 전에는 어떤 업무 화면에도 갈 수 없다. 그래서 이
화면은 app_shell(사이드바·네비게이션) **밖에서** 렌더된다 — 네비게이션이 보이면
게이트를 우회할 경로가 생긴다.
"""
import streamlit as st

from modules import auth, config, passwords, ui


def render(*, forced: bool = True) -> None:
    user = st.session_state.get("user") or {}
    emp_no = str(user.get("emp_no") or "")
    name = str(user.get("name") or "")

    with ui.centered((1, 1.4, 1)):
        st.write("")
        st.write("")
        with st.container(border=True):
            st.markdown(
                f"<div class='page-title' style='color:#1E3A6E'>비밀번호 변경</div>"
                f"<div class='page-desc'>{name}({emp_no}) 님의 비밀번호를 설정합니다.</div>",
                unsafe_allow_html=True,
            )

            if forced:
                st.warning(
                    "처음 로그인했거나 관리자가 비밀번호를 초기화했습니다. "
                    "계속하려면 새 비밀번호를 설정하세요."
                )

            st.caption(
                f"최소 {passwords.MIN_LENGTH}자 이상, 사번과 다른 값이어야 합니다."
            )

            with st.form("password_change_form"):
                current = st.text_input(
                    "현재 비밀번호",
                    type="password",
                    help="아직 비밀번호를 설정하지 않았다면 사번을 입력하세요.",
                )
                new = st.text_input("새 비밀번호", type="password")
                confirm = st.text_input("새 비밀번호 확인", type="password")
                submitted = st.form_submit_button(
                    "변경", width="stretch", type="primary"
                )

            if submitted:
                ok, err = auth.change_password(current, new, confirm)
                if ok:
                    st.success("비밀번호를 변경했습니다. 다른 기기의 로그인은 해제됩니다.")
                    st.rerun()
                else:
                    st.error(err)

            if forced:
                # 강제변경 중에도 로그아웃 경로는 남긴다 — 사번을 잘못 알고 들어온
                # 사용자가 화면에 갇히지 않게 한다.
                if st.button("로그아웃", width="stretch"):
                    auth.logout()
                    st.rerun()
