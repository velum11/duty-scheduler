"""중립 구조 키트 (KP-standard §0.2) — 레이아웃 컴포넌트만, 도메인 lifecycle 미포함.

DESIGN.md §0 화면 구조 표준의 공용 어휘를 제공한다. 편집 lifecycle(DraftState·run_save·
ReadinessState)은 ``views/master`` 가 계속 소유하며 이 키트는 **구조만** 담당한다:

    screen_frame     화면 헤더(브레드크럼·제목·모드배지) — scaffold 위임 + 영역 순서 진입점
    top_action_bar   페이지 액션(조회·새로고침 등) 상단 고정 위치·어휘
    condition_panel  col-N 우측 인라인 라벨 조건(필터) 패널
    read_grid        AgGrid READ 어댑터(편집 자산 없음 — action열·paste·editable·unsafe_jscode 제거)
    status_region    요약 카드 + readiness 배너

영역 순서(§0.3): title → top actions → conditions → primary(grid) → details → status.
"""
from views.common.erp.kit import (
    Field,
    condition_panel,
    read_grid,
    screen_frame,
    status_region,
    top_action_bar,
)

__all__ = [
    "Field",
    "screen_frame",
    "top_action_bar",
    "condition_panel",
    "read_grid",
    "status_region",
]
