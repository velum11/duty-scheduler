"""WorkOps(구 생산 근무표 관리) — 진입점 (로그인 게이트 + 역할별 App Shell + 화면 라우팅).

- ADMIN/MANAGER: 좌측 2단 메뉴 App Shell
- USER: 상단 정보 + 반응형 3개 메뉴 App Shell
- 설정에서 sample 또는 Supabase 데이터 모드를 명시적으로 선택한다.
"""
import streamlit as st

from modules import auth, db, nav, ui

# 페이지 설정과 공통 CSS를 components.v2 등록보다 먼저 적용한다.
ui.setup_page()

from views import (
    dashboard, login, my_schedule, password_change,
    schedule_edit, schedule_view,
    master_users, master_departments, master_teams, master_org, master_work_types,
    near_miss_submit, near_miss_my, near_miss_evaluate, near_miss_improvement,
    near_miss_view, near_miss_stats,
    lodging_request, lodging_my, lodging_manage, lodging_calendar,
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
    "near_miss_submit": near_miss_submit,
    "near_miss_my": near_miss_my,
    "near_miss_evaluate": near_miss_evaluate,
    "near_miss_improvement": near_miss_improvement,
    "near_miss_view": near_miss_view,
    "near_miss_stats": near_miss_stats,
    "lodging_request": lodging_request,
    "lodging_my": lodging_my,
    "lodging_manage": lodging_manage,
    "lodging_calendar": lodging_calendar,
}


def _caps_for(user: dict) -> set:
    """메뉴/route guard 가 공유하는 능력 집합을 세션 사용자에서 계산한다.

    nav 는 DEPENDENCY-FREE 이므로(auth import 없음) 능력 판정은 여기(호출부)에서 하고
    nav 필터에 caps 로 넘긴다. 아차사고 평가 능력(정적)과 개선조치 접근(배정 기반 동적)을
    각각 판정한다 — 개선조치는 평가자/ADMIN 뿐 아니라 배정된 담당자·지정 확인자도 노출되며,
    판정 facade(has_near_miss_improvement_access)가 평가자/ADMIN 단축·경량 EXISTS·비크래시라
    매 렌더 호출해도 부담이 적다(메뉴는 권한경계 아님 — route guard·facade 가 행단위 재검증).
    """
    caps = set()
    if auth.can_evaluate_near_miss(user):
        caps.add(nav.CAP_EVALUATE_NEAR_MISS)
    if db.has_near_miss_improvement_access(user):
        caps.add(nav.CAP_ACCESS_NEAR_MISS_IMPROVEMENT)
    # 숙소 예약: 저장소가 준비된 배포에서만 메뉴·라우팅을 연다(migration 미적용 배포에서
    # "메뉴는 뜨는데 들어가면 준비 안 됨"을 만들지 않는다). 승인은 그 위에 담당 권한을
    # **함께** 요구한다 — nav 의 admit 은 OR 이므로 AND 는 여기서 계산해 caps 로 넘긴다.
    if db.lodging_schema_ready():
        caps.add(nav.CAP_ACCESS_LODGING)
        if auth.can_approve_lodging(user):
            caps.add(nav.CAP_APPROVE_LODGING)
    return caps


def dispatch(page: str, user: dict) -> None:
    """선택된 메뉴 page id 에 맞는 화면을 렌더링한다.

    화면 전환 시 이전 화면의 잔상이 남지 않도록, 매 호출마다 동일한 위치에
    새 `st.empty()` 자리표시자를 만들어 그 안에만 그린다 — 이전 run 이 이
    위치에 남긴 내용은 이 자리표시자가 그려지는 즉시(본문 로딩 완료를 기다리지
    않고) 교체된다. 로딩 중에는 공통 스피너를 보여준다.
    """
    role = str(user.get("role", "")).strip().upper()
    caps = _caps_for(user)
    if not (nav.allowed(page, role, caps) or (page == "master_org" and role == "ADMIN")):
        page = nav.default_page(role, caps)
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

        # 비밀번호 강제변경 게이트 — app_shell(네비게이션) 앞에 둔다. 사이드바가 그려진
        # 뒤에 막으면 그 자체가 우회 경로가 된다.
        if auth.needs_password_change():
            password_change.render(forced=True)
            return

        role = str(user.get("role", "")).strip().upper()
        page = ui.user_app_shell(user) if role == "USER" else ui.app_shell(user)
        dispatch(page, user)
        ui.sample_mode_banner()
    except db.DATA_SOURCE_ERRORS as exc:
        st.error(str(exc))


main()
