"""생산 근무표 관리 — 진입점 (로그인 게이트 + App Shell + 화면 라우팅).

- 모든 로그인 사용자: 좌측 1차 아이콘 바 + 2차 메뉴 패널 + 메인 콘텐츠
- Supabase 미설정 시 data/sample/*.csv 로 동작한다.
"""
from modules import auth, ui

# 페이지 설정과 공통 CSS를 components.v2 등록보다 먼저 적용한다.
ui.setup_page()

from views import (
    dashboard, login, my_schedule,
    schedule_edit, schedule_view,
    master_users, master_departments, master_teams, master_work_types,
)

# 업무 화면 라우팅 테이블 (page id → 화면 모듈)
_PAGES = {
    "schedule_edit": schedule_edit,
    "schedule_view": schedule_view,
    "master_users": master_users,
    "master_departments": master_departments,
    "master_teams": master_teams,
    "master_work_types": master_work_types,
}


def dispatch(page: str, user: dict) -> None:
    """선택된 메뉴 page id 에 맞는 화면을 렌더링한다."""
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
    user = auth.get_current_user()

    # 로그인 게이트
    if not user:
        login.render()
        return

    # 모든 로그인 사용자는 공통 App Shell 안에서 화면을 렌더링한다.
    # 개인 근무표의 폭은 dispatch에서만 별도로 제어한다.
    page = ui.app_shell(user)
    dispatch(page, user)
    ui.sample_mode_banner()


main()
