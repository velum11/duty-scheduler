"""기준정보 3화면 공통 기반 패키지 (Phase4 Lane A).

사용자/조직/근무형태 관리 화면(B/C/D)이 공유하는 디자인·상태·그리드·저장 계약을
한 곳에서 제공한다. 화면별 controller/validator/renderer/삭제정책은 각 화면이 소유하고,
이 패키지는 그 위의 골격만 담당한다(공통화 대상만 — Phase2 §2·§3 경계 준수).

공개 API 요약 (B/C/D 가 쓰는 시그니처):

  상태 (state):
    DraftState(page_id)                        page-scoped key factory + dirty 정책
      .action_requester(name) / .take_action(name) / take/clear
      .get_rows/.set_rows/.nonce/.bump_nonce/.grid_key/.next_rid
      .resolve_reload(params, refresh=, dirty=) -> RELOAD|CONFIRM|KEEP
      .apply_pending_reload()/.cancel_pending_reload()
      .set_flash(kind, text)/.pop_flash()
    RELOAD, CONFIRM, KEEP

  그리드 (grid):
    MasterGridSpec(page_id, columns, order, col_config=, select_all=,
                   row_class_rules=, grid_options=, height=,
                   include_group_rows=, include_linked_rows=)
    render_master_grid(spec, frame, key=) -> DataFrame(메타 포함)
    live_rows(df) / grid_bool(v) / master_grid_height(n)
    CORE_META, VIEW_META, META_COLUMNS

  액션 (actions):
    master_action_bar(state, sel_count=, dirty_total=, can_save=, busy=, ...)
    take_actions(state) -> {add,delete,save,refresh: bool}
    count_strip(existing, new, changed, sel, groups=None)
    dirty_total(new, changed)
    discard_confirm_bar(state) -> 'discard'|'cancel'|None
    confirm_bar(state, title=, lines=, confirm_enabled=, scope=) -> 'confirm'|'cancel'|None
    상수: ADD, ADD_GROUP, DELETE, SAVE, REFRESH

  저장/lifecycle (lifecycle):
    run_save(state, validate=, build_candidate=, persist=) -> SaveOutcome
    PersistResult.success/failure/unresolved ; .ok/.partial
    ledger_banner(result)
    Readiness / ReadinessState(.ready/.not_ready/.probe_error/.from_ready_flag)
      .write_enabled/.show_ledger/.banner()/.badge_html()

  스타일 (style):
    inject_page_styles()
    master_screen_head(...)  # 아래 얇은 래퍼
    banner(kind, text, extra) / banner_html(...)
    chip_html(text, kind) / mode_badge_html(connected=, sample=)
    master_row_class_rules(...) / cell_error_rule(field) / cell_dirty_rule(field)
    SELECT_CELL_RULE / GRID_CSS / TOKENS / token(name)
"""
from __future__ import annotations

from html import escape

import streamlit as st

from views.master import actions, grid, lifecycle, paste, state, style
from views.master.actions import (
    ADD,
    ADD_GROUP,
    DELETE,
    REFRESH,
    SAVE,
    confirm_bar,
    count_strip,
    dirty_total,
    discard_confirm_bar,
    master_action_bar,
    take_actions,
)
from views.master.grid import (
    CORE_META,
    META_COLUMNS,
    VIEW_META,
    MasterGridSpec,
    grid_bool,
    live_rows,
    master_grid_height,
    render_master_grid,
)
from views.master.lifecycle import (
    PersistResult,
    Readiness,
    ReadinessState,
    SaveOutcome,
    ledger_banner,
    run_save,
)
from views.master.state import CONFIRM, KEEP, RELOAD, DraftState
from views.master.style import (
    GRID_CSS,
    SELECT_CELL_RULE,
    TOKENS,
    banner,
    banner_html,
    cell_dirty_rule,
    cell_error_rule,
    chip_html,
    inject_page_styles,
    master_row_class_rules,
    mode_badge_html,
    readiness_badge_html,
    token,
)


def master_screen_head(
    title: str,
    desc: str,
    *,
    breadcrumb: str | None = None,
    mode_badge: str | None = None,
) -> None:
    """§5 페이지 제목 헤더 — 공용 CSS 주입 + breadcrumb + 제목/설명 + 모드 배지.

    ``mode_badge`` 는 ``style.mode_badge_html(...)`` 결과(신뢰된 HTML)를 넘긴다.
    데이터 모드 신호 전용이며 readiness/health 를 섞지 않는다(§5).
    """
    inject_page_styles()
    crumb = f"<div class='ms-crumb'>{escape(breadcrumb)}</div>" if breadcrumb else ""
    right = mode_badge or ""
    st.markdown(
        "<div class='ms-head'><div>"
        f"{crumb}<div class='ms-title'>{escape(title)}</div>"
        f"<div class='ms-desc'>{escape(desc)}</div>"
        f"</div><div>{right}</div></div>",
        unsafe_allow_html=True,
    )


def show_flash(state: DraftState) -> None:
    """§21 flash 를 배너로 1회 표시한다. kind: success|warning|error|info."""
    msg = state.pop_flash()
    if not msg:
        return
    kind, text = msg
    mapping = {"success": "success", "warning": "warn", "error": "danger", "info": "info"}
    banner(mapping.get(kind, "info"), text)


__all__ = [
    # submodules
    "actions", "grid", "lifecycle", "paste", "state", "style",
    # state
    "DraftState", "RELOAD", "CONFIRM", "KEEP",
    # grid
    "MasterGridSpec", "render_master_grid", "live_rows", "grid_bool",
    "master_grid_height", "CORE_META", "VIEW_META", "META_COLUMNS",
    # actions
    "master_action_bar", "take_actions", "count_strip", "dirty_total",
    "discard_confirm_bar", "confirm_bar",
    "ADD", "ADD_GROUP", "DELETE", "SAVE", "REFRESH",
    # lifecycle
    "run_save", "SaveOutcome", "PersistResult", "ledger_banner",
    "Readiness", "ReadinessState",
    # style
    "inject_page_styles", "master_screen_head", "show_flash",
    "banner", "banner_html", "chip_html", "mode_badge_html", "readiness_badge_html",
    "master_row_class_rules", "cell_error_rule", "cell_dirty_rule",
    "SELECT_CELL_RULE", "GRID_CSS", "TOKENS", "token",
]
