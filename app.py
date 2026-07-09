"""생산 근무표 관리 — 진입점 (로그인 게이트 + App Shell + 화면 라우팅).

- ADMIN/MANAGER: 좌측 1차 아이콘 바 + 2차 메뉴 패널 + 메인 콘텐츠 (DESIGN.md §2)
- USER: App Shell 없이 모바일 개인 조회 화면 (DESIGN.md §17)
- Supabase 미설정 시 data/sample/*.csv 로 동작한다.
"""
from modules import auth, ui
from views import (
    dashboard, login, my_schedule,
    schedule_edit, schedule_view,
    master_users, master_departments, master_teams, master_work_types,
)

# 페이지 설정 + 공통 스타일 (반드시 다른 st 호출보다 먼저)
ui.setup_page()

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
        # 개인 조회 화면은 관리자 화면에서도 모바일 폭으로 표시
        with ui.centered((1, 1.6, 1)):
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

    # USER: 모바일 개인 조회 (App Shell 미적용)
    if user["role"] == "USER":
        with ui.centered((1, 2, 1)):
            ui.mobile_header(user)
            my_schedule.render(user)
            ui.sample_mode_banner()
        return

    # ADMIN/MANAGER: App Shell (2단 메뉴 + 헤더) + 업무 화면
    page = ui.app_shell(user)
    dispatch(page, user)
    ui.sample_mode_banner()


main()
