"""근무표 관리 — 전체 근무표 조회 화면.

구조는 공용 중립 키트(``views/common/erp``)를 쓰고, 데이터/권한/스코프/스냅샷
로직(``views/workspace.py::schedule_screen`` — MANAGER fail-closed 재적용,
``_build_month_grid`` 등)은 그대로 유지한다(구조 전용 이관).
"""
# DESIGN.md §0 화면 유형 규약 — 조회형.
SCREEN_ARCHETYPE = "READ_VIEW"

from views import workspace
from views.common import erp


def render(user: dict) -> None:
    # §1-C 읽기 변형: 아이콘 밴드 제거(표준 아이콘 8종은 상단 52px 헤더가 소유 §A-5).
    # 조회/새로고침은 조건 줄 우측 [조회] 버튼(schedule_screen 내부)이 담당한다. 조회조건·
    # run_query 게이트·스코프·스냅샷·스켈레톤 로직은 schedule_screen 소관(데이터 경로 불변).
    erp.screen_frame(
        SCREEN_ARCHETYPE,
        title="월간 근무표",
        desc="부서와 조를 선택하여 월별 근무표를 조회합니다.",
        breadcrumb="근무표 › 월간 근무표",
    )
    workspace.schedule_screen(user, "schedule_view")
