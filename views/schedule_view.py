"""근무표 관리 — 전체 근무표 조회 화면.

구조는 공용 중립 키트(``views/common/erp``)를 쓰고, 데이터/권한/스코프/스냅샷
로직(``views/workspace.py::schedule_screen`` — MANAGER fail-closed 재적용,
``_build_month_grid`` 등)은 그대로 유지한다(구조 전용 이관).
"""
# DESIGN.md §0 화면 유형 규약 — 조회형.
SCREEN_ARCHETYPE = "READ_VIEW"

from views import workspace
from views.common import erp
from views.common import scaffold


def render(user: dict) -> None:
    # toolbar="icons": 상단 파랑 밴드에 KPtech 아이콘 전용 툴바(근무표 편성·사용자 관리와
    # 동일 표준). 밴드 핸들을 schedule_screen 으로 넘겨 조회/새로고침을 아이콘으로 채운다
    # (인페이지 pill 제거). 조회조건·run_query 게이트·스켈레톤 로직은 schedule_screen 소관.
    band = erp.screen_frame(
        SCREEN_ARCHETYPE,
        title="월간 근무표",
        desc="부서와 조를 선택하여 월별 근무표를 조회합니다.",
        breadcrumb="근무표 › 월간 근무표",
        badges=scaffold.mode_badge(),
        toolbar="icons",
    )
    workspace.schedule_screen(user, "schedule_view", band=band)
