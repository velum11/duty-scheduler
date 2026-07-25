"""생산 근무표 관리 — 진입점 (로그인 게이트 + 역할별 App Shell + 화면 라우팅).

- ADMIN/MANAGER: 좌측 2단 메뉴 App Shell
- USER: 상단 정보 + 반응형 3개 메뉴 App Shell
- 설정에서 sample 또는 Supabase 데이터 모드를 명시적으로 선택한다.
"""
import streamlit as st

from modules import auth, db, nav, ui

# 페이지 설정과 공통 CSS를 components.v2 등록보다 먼저 적용한다.
ui.setup_page()

from views import (
    dashboard, login, my_schedule,
    schedule_edit, schedule_view,
    master_users, master_departments, master_teams, master_org, master_work_types,
)

# 업무 화면 라우팅 테이블 (page id → 화면 모듈)
_PAGES = {
    "schedule_edit": schedule_edit,
    "schedule_view": schedule_view,
    "master_users": master_users,
    "master_org": master_org,
    "master_departments": master_departments,
    "master_teams": master_teams,
    "master_work_types": master_work_types,
}


def dispatch(page: str, user: dict) -> None:
    """선택된 메뉴 page id 에 맞는 화면을 렌더링한다.

    화면 전환 시 이전 화면의 잔상이 남지 않도록, 매 호출마다 동일한 위치에
    새 `st.empty()` 자리표시자를 만들어 그 안에만 그린다 — 이전 run 이 이
    위치에 남긴 내용은 이 자리표시자가 그려지는 즉시(본문 로딩 완료를 기다리지
    않고) 교체된다. 로딩 중에는 공통 스피너를 보여준다.
    """
    role = str(user.get("role", "")).strip().upper()
    if not (nav.allowed(page, role) or (page == "master_org" and role == "ADMIN")):
        page = nav.default_page(role)
        st.session_state.nav_page = page

    body = st.empty()
    with body.container():
        with st.spinner("불러오는 중…"):
            if page == "dashboard":
                dashboard.render(user)
            elif page == "my_schedule":
                my_schedule.render(user)
            elif page in _PAGES:
                _PAGES[page].render(user)
            else:
                ui.page_header(page)
                ui.empty_state("이 화면에 접근할 권한이 없습니다.")


def main() -> None:
    try:
        user = auth.get_current_user()

        # 로그인 게이트
        if not user:
            login.render()
            return

        role = str(user.get("role", "")).strip().upper()
        page = ui.user_app_shell(user) if role == "USER" else ui.app_shell(user)
        dispatch(page, user)
        ui.sample_mode_banner()
    except db.DATA_SOURCE_ERRORS as exc:
        st.error(str(exc))


main()
