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
    erp.screen_frame(
        SCREEN_ARCHETYPE,
        title="월간 근무표",
        desc="부서와 조를 선택하여 월별 근무표를 조회합니다.",
        breadcrumb="근무표 › 월간 근무표",
        badges=scaffold.mode_badge(),
    )
    workspace.schedule_screen(user, "schedule_view")
