"""중립 구조 키트 (KP-standard §0.2) — 레이아웃 컴포넌트만, 도메인 lifecycle 미포함.

DESIGN.md §0 화면 구조 표준의 공용 어휘를 제공한다. 편집 lifecycle(DraftState·run_save·
ReadinessState)은 ``views/master`` 가 계속 소유하며 이 키트는 **구조만** 담당한다:

    screen_frame     화면 헤더(브레드크럼·제목·모드배지) — scaffold 위임 + 영역 순서 진입점
    top_action_bar   페이지 액션(조회·새로고침 등) 상단 고정 위치·어휘
    form_submit      FORM_ENTRY 제출 앵커(st.form_submit_button 래퍼, 상단바 대체)
    condition_panel  col-N 우측 인라인 라벨 조건(필터) 패널
    read_grid        AgGrid READ 어댑터(편집 자산 없음 — action열·paste·editable·unsafe_jscode 제거)
    select_grid      AgGrid 단일 선택 목록 어댑터(read_grid 와 별개 capability, 자연키 반환)
    status_region    요약 카드 + readiness 배너
    status_badge_html/meta_col_html/field_block  MASTER_DETAIL 상세 순수 표시 primitive(도메인 무지)

영역 순서(§0.3): title → top actions → conditions → primary(grid) → details → status.
"""
from views.common.erp.kit import (
    Field,
    attention_strip,
    condition_panel,
    detail_actions,
    detail_empty,
    field_block,
    form_submit,
    grade_mark_html,
    grid_shell,
    grid_skeleton_html,
    master_detail_frame,
    meta_col_html,
    metadata_strip,
    read_grid,
    screen_frame,
    select_grid,
    status_badge_html,
    status_region,
    metric_strip,
    top_action_bar,
)

__all__ = [
    "Field",
    "screen_frame",
    "top_action_bar",
    "form_submit",
    "condition_panel",
    "read_grid",
    "select_grid",
    "grid_shell",
    "grid_skeleton_html",
    "status_region",
    "metric_strip",
    "master_detail_frame",
    "detail_empty",
    "detail_actions",
    "status_badge_html",
    "meta_col_html",
    "field_block",
    "grade_mark_html",
    "metadata_strip",
    "attention_strip",
]
