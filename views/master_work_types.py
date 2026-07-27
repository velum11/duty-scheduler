"""기준정보 — 근무형태 관리 (기준정보 3화면 공통 기반 `views.master` 재구현).

Phase4 Lane C. 기능 계약(조회/신규행/편집/선택삭제/저장/새로고침, 코드·이름·약칭·
색상·순서·사용여부 필드, 삭제 정책)을 보존하면서 UI·상태·저장 계약을 공통 기반
(`views/master/*`)과 `design-contract.md` 로 옮긴다.

이 화면만의 고유 요소(디자인 계약 §11·§25 근무형태 예외):
  - **색상 셀**: 스와치 + 대문자 HEX + 네이티브 컬러 피커. **양방향 편집**(피커/텍스트)
    으로 개선하고, 유효하지 않으면 스와치를 대각선 해치로 표시한다. 저장 형식은
    기존과 동일한 ``#RRGGBB`` 를 유지한다. ``work_types.color`` 단일 기준이 근무표
    (월간/전체/개인/대시보드)의 셀 배경·뱃지·범례 색을 구동하는 계약은 불변이다.
  - **저장 전 검증 보강**(Codex 지적): 코드·약칭 필수, HEX ``#RRGGBB`` 형식, 시작/종료
    ``HH:MM`` 형식, 코드 중복(저장 차단)·약칭 중복(소프트 경고)을 검증한다.
  - **삭제**: 근무표에서 참조 중인 코드는 미사용 처리(is_active=False), 참조 없는 코드는
    물리 삭제한다. 항상 2단계 확인.

``code`` 는 근무표 FK 안정키다(rename 주의 — 저장은 upsert 이므로 코드를 바꾸면 신규로
간주된다). 저장 실패 시 편집 draft 는 재적재/리마운트 없이 보존한다.
"""
from __future__ import annotations

# DESIGN.md §0 화면 유형 규약 — 기준정보 편집형.
SCREEN_ARCHETYPE = "EDIT_GRID"

import json
import re

import pandas as pd
import streamlit as st
from st_aggrid import JsCode

from modules import db
from views import master
from views.common import erp
from views.master import (
    ADD,
    CORE_META,
    DELETE,
    REFRESH,
    SAVE,
    MasterGridSpec,
    PersistResult,
    confirm_bar,
    count_strip,
    dirty_total,
    grid_bool,
    ledger_banner,
    live_rows,
    master_grid_height,
    render_master_grid,
    run_save,
    style,
)
from views.master.state import RELOAD, DraftState

PAGE_ID = "master_work_types"

_STATUS = ["사용 중", "사용 안 함", "전체"]
_USER_COLS = ["코드", "명칭", "분류", "약칭", "시작", "종료", "색상", "실근무", "특근수당", "설명", "표시순서", "사용"]
_BOOL_COLS = {"실근무", "특근수당", "사용"}
_ROW_COLS = [*CORE_META, *_USER_COLS]
_GRID_COLUMNS = {c: ("bool" if c in _BOOL_COLS else "text") for c in _USER_COLS}

# 화면 한글 컬럼 ↔ db.WORK_TYPE_COLUMNS 매핑.
_FIELD_BY_COL = {
    "코드": "code", "명칭": "name", "분류": "category", "약칭": "short_label",
    "시작": "start_time", "종료": "end_time", "색상": "color",
    "실근무": "is_work", "특근수당": "affects_allowance", "설명": "description",
    "표시순서": "sort_order", "사용": "is_active",
}

_DEFAULT_COLOR = "#9AA0A6"
_HEX_BODY_RE = re.compile(r"^[0-9a-fA-F]{6}$")
_HEX3_RE = re.compile(r"^[0-9a-fA-F]{3}$")
_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")

# ---- 세션 보조 키(page-scoped, DraftState.key 로 스코프) ----
_BASELINE = "baseline"          # {row_id: {col: 정규화값}} — 기존 변경 감지 기준
_CELL_ERRORS = "cell_errors"    # {row_id: {col: msg}} — 셀 오류 metadata
_SAVE_ERRORS = "save_errors"    # {"errors": [...]} — 검증 실패 오류 배너
_SAVE_LEDGER = "save_ledger"    # PersistResult — 부분성공/결과불명 원장 배너(§22)
_DELETE_ERROR = "delete_error"  # str — 삭제 재시도 확인 바에 표시할 실패 사유(B4)
_LAST_COUNTS = "last_counts"    # (new, changed, sel) — 오류 배너 흡수 문구용


# ---------------------------------------------------------------------------
# 색상 셀 — 스와치 + 대문자 HEX(렌더러) / 네이티브 피커 + 텍스트 양방향(에디터).
# 저장은 #RRGGBB. 유효하지 않은 값은 대각선 해치로 표시(디자인 계약 §11).
# ---------------------------------------------------------------------------
_COLOR_RENDERER = JsCode(
    """
    (class {
      init(p) {
        const v = String(p.value == null ? '' : p.value).trim();
        const valid = /^#([0-9a-fA-F]{6})$/.test(v);
        const g = document.createElement('div');
        g.style.display='flex'; g.style.alignItems='center'; g.style.height='100%'; g.style.gap='8px'; g.style.paddingLeft='6px';
        const sw = document.createElement('span');
        sw.style.width='16px'; sw.style.height='16px'; sw.style.borderRadius='4px';
        sw.style.border='1px solid rgba(0,0,0,0.18)'; sw.style.flex='0 0 auto';
        if (valid) { sw.style.background = v; }
        else { sw.style.background = 'repeating-linear-gradient(45deg,#eee,#eee 3px,#ccc 3px,#ccc 6px)'; }
        g.appendChild(sw);
        const t = document.createElement('span');
        t.textContent = v || '—';
        t.style.fontSize='12px'; t.style.letterSpacing='.02em';
        t.style.color = valid ? '#24262B' : '#908C83';
        t.style.fontVariantNumeric='tabular-nums';
        g.appendChild(t);
        this.eGui = g;
      }
      getGui() { return this.eGui; }
      refresh() { return false; }
    })
    """
)
_COLOR_EDITOR = JsCode(
    """
    (class {
      init(p) {
        const raw = String(p.value == null ? '' : p.value).trim();
        this.value = /^#([0-9a-fA-F]{6})$/.test(raw) ? raw.toUpperCase() : '#9AA0A6';
        const g = document.createElement('div');
        g.style.display='flex'; g.style.alignItems='center'; g.style.height='100%'; g.style.gap='8px'; g.style.paddingLeft='6px';
        const pick = document.createElement('input');
        pick.type='color'; pick.value=this.value;
        pick.style.width='26px'; pick.style.height='22px'; pick.style.border='none';
        pick.style.background='transparent'; pick.style.cursor='pointer'; pick.style.padding='0';
        const hex = document.createElement('input');
        hex.type='text'; hex.value=this.value; hex.maxLength=7;
        hex.style.width='84px'; hex.style.fontSize='12px'; hex.style.padding='2px 4px';
        hex.style.border='1px solid #D4CEC3'; hex.style.borderRadius='4px';
        hex.style.fontVariantNumeric='tabular-nums'; hex.style.textTransform='uppercase';
        const sync = (val, from) => {
          const m = /^#?([0-9a-fA-F]{6})$/.exec(String(val).trim());
          if (m) { this.value = '#' + m[1].toUpperCase(); pick.value = this.value; if (from !== 'hex') hex.value = this.value; }
        };
        pick.addEventListener('input', () => { this.value = pick.value.toUpperCase(); hex.value = this.value; });
        hex.addEventListener('input', () => sync(hex.value, 'hex'));
        g.appendChild(pick); g.appendChild(hex);
        this.eGui = g; this.eHex = hex;
      }
      getGui() { return this.eGui; }
      afterGuiAttached() { this.eHex.focus(); this.eHex.select(); }
      getValue() {
        const m = /^#?([0-9a-fA-F]{6})$/.exec(String(this.eHex.value).trim());
        return m ? ('#' + m[1].toUpperCase()) : String(this.value || '').toUpperCase();
      }
      isPopup() { return false; }
    })
    """
)

# 불리언 셀(실근무·특근수당·사용) — 공통 native ``cellDataType='boolean'`` 로 표시·편집한다.
# ag-grid 자체 boolean 렌더러/에디터를 쓰므로 별도 JsCode 렌더러를 주입하지 않는다.
# (JsCode 셀 렌더러는 Streamlit Cloud Python 3.14 배포에서 실행되지 않아 체크박스가 사라지는
#  High 회귀가 있었다 — grid.py 의 [LEGACY] BOOL_DISPLAY_RENDERER 주석 참조.)

# ---------------------------------------------------------------------------
# 약칭 셀 — 값 + 라이브 중복 경고칩(공통 `.ms-chip warn`). 활성 행끼리 같은 약칭이
# 둘 이상이면 표시(근무표는 코드로 표시되므로 저장 차단이 아닌 소프트 경고 §11).
# 중복 판정은 저장 검증 `_duplicate_short_labels` 와 동일 규칙(활성·비어있지 않음).
# 다른 행/사용 편집에 반응하도록 grid `onCellValueChanged` 가 이 열을 refresh 한다.
# ---------------------------------------------------------------------------
_SHORT_LABEL_RENDERER = JsCode(
    """
    (class {
      init(p) { this.eGui = document.createElement('div'); this._render(p); }
      _active(d) {
        const removed = String(d._removed == null ? '' : d._removed).trim() === '1';
        const u = d['사용'];
        const use = (u === true || u === 'true' || u === 1 || u === '사용' || u === '재직');
        return !removed && use;
      }
      _render(p) {
        const g = this.eGui; g.innerHTML = '';
        g.style.display = 'flex'; g.style.alignItems = 'center'; g.style.gap = '6px'; g.style.height = '100%';
        const val = String(p.value == null ? '' : p.value).trim();
        const t = document.createElement('span');
        t.textContent = val || '—';
        if (!val) { t.style.color = '#908C83'; }
        g.appendChild(t);
        const d = p.data || {};
        if (val && this._active(d) && p.api) {
          let count = 0;
          const self = this;
          p.api.forEachNode(function(node) {
            const nd = node.data || {};
            if (self._active(nd) && String(nd['약칭'] == null ? '' : nd['약칭']).trim() === val) { count += 1; }
          });
          if (count > 1) {
            const chip = document.createElement('span');
            chip.className = 'ms-chip warn'; chip.textContent = '약칭 중복';
            chip.title = '같은 약칭이 여러 근무형태에 사용 중입니다. 근무표에서는 코드로 표시됩니다.';
            g.appendChild(chip);
          }
        }
      }
      getGui() { return this.eGui; }
      refresh(p) { this._render(p); return true; }
    })
    """
)

# 분류 셀 — 공통 `.ms-chip mute` 로 표시(편집은 더블클릭 시 기본 텍스트 에디터).
_CATEGORY_RENDERER = JsCode(
    """
    (class {
      init(p) { this.eGui = document.createElement('div'); this._render(p); }
      _render(p) {
        const g = this.eGui; g.innerHTML = '';
        g.style.display = 'flex'; g.style.alignItems = 'center'; g.style.height = '100%'; g.style.paddingLeft = '2px';
        const val = String(p.value == null ? '' : p.value).trim();
        if (val) {
          const chip = document.createElement('span');
          chip.className = 'ms-chip mute'; chip.textContent = val;
          g.appendChild(chip);
        } else {
          const t = document.createElement('span'); t.textContent = '—'; t.style.color = '#908C83';
          g.appendChild(t);
        }
      }
      getGui() { return this.eGui; }
      refresh(p) { this._render(p); return true; }
    })
    """
)

# 약칭 중복칩은 다른 행의 약칭/사용 변경에 반응해야 한다 — 해당 셀 변경 시 약칭 열만
# 강제 refresh 한다(paste 는 onGridReady/onCellEditingStopped 를 쓰므로 충돌 없음).
_DUP_REFRESH = JsCode(
    """
    function(e) {
      const col = (e.column && e.column.getColId) ? e.column.getColId()
                  : (e.colDef && e.colDef.field);
      if ((col === '약칭' || col === '사용') && e.api) {
        e.api.refreshCells({ columns: ['약칭'], force: true });
      }
    }
    """
)


# 자연키(코드) 잠금 — org/users 와 동일 계약. 코드는 근무표 스케줄이 참조하는 FK 안정키라
# 저장행에서 편집을 막는다(저장은 upsert 라 코드 변경 = 신규 간주 → 참조 orphan 위험).
# 신규 행에서만 편집 가능하고, 저장행엔 읽기전용 틴트(공통 .ms-cell-readonly)를 켠다.
_EDIT_NEW_ONLY = JsCode("function(p){ return !!(p.data && p.data._row_state === 'new'); }")
_CODE_READONLY_RULES = {"ms-cell-readonly": "data._row_state !== 'new'"}


# ---- 컬럼 폭·정렬(디자인 계약 §4·mockup) ----
_COL_WIDTHS = {
    "코드": {"width": 108, "minWidth": 88, "pinned": "left", "cellClass": "md-c-left",
            "editable": _EDIT_NEW_ONLY},
    "명칭": {"width": 118, "minWidth": 96, "cellClass": "md-c-left"},
    "분류": {"width": 96, "minWidth": 76, "cellClass": "md-c-left", "cellRenderer": _CATEGORY_RENDERER},
    "약칭": {"width": 130, "minWidth": 96, "cellClass": "md-c-left", "cellRenderer": _SHORT_LABEL_RENDERER},
    "시작": {"width": 80, "minWidth": 66, "cellClass": "md-c-center ms-num"},
    "종료": {"width": 80, "minWidth": 66, "cellClass": "md-c-center ms-num"},
    "색상": {"width": 156, "minWidth": 130, "cellClass": "md-c-left",
            "cellRenderer": _COLOR_RENDERER, "cellEditor": _COLOR_EDITOR},
    "실근무": {"width": 76, "minWidth": 64, "cellClass": "md-c-center"},
    "특근수당": {"width": 84, "minWidth": 72, "cellClass": "md-c-center"},
    "설명": {"flex": 1, "minWidth": 140, "cellClass": "md-c-left"},
    "표시순서": {"width": 92, "minWidth": 78, "cellClass": "md-c-center ms-num"},
    "사용": {"width": 66, "minWidth": 58, "cellClass": "md-c-center"},
}


def _summary_counts(frame: pd.DataFrame) -> tuple[int, int]:
    """현재 필터결과(표에 로드된 기존 행) 기준 (사용 중, 미사용) 건수.

    사용자관리와 동일하게 '지금 표에 보이는' 결과 기준 분포를 낸다(필터 무관 전체
    카운트가 아님). 신규 행은 아직 저장 전이므로 제외한다.
    """
    if frame is None or frame.empty:
        return 0, 0
    existing = frame[frame["_row_state"] == "existing"] if "_row_state" in frame else frame
    if existing.empty:
        return 0, 0
    active = int(existing["사용"].map(grid_bool).sum())
    return active, len(existing) - active


def _render_summary_chips(frame: pd.DataFrame, params: dict) -> None:
    """상단 요약 스트립 — 좌: 활성 필터 칩, 우: 현재 필터결과의 사용/미사용 분포.

    사용자관리(_render_summary_chips)와 동일한 어휘/배치. 필터가 모두 기본이면 좌측
    칩은 비운다. 결과 0건이어도 활성 필터 칩은 남겨 왜 비었는지 알린다.
    """
    if frame is None:
        return
    filt = ""
    if params.get("active") and params["active"] != "전체":
        filt += master.chip_html(f"사용 여부: {params['active']}", "lock")
    if params.get("search"):
        filt += master.chip_html(f"검색: {params['search']}", "lock")

    active, inactive = _summary_counts(frame)
    cnt = ""
    if active or inactive:
        cnt = master.chip_html(f"사용 중 {active}", "ok")
        if inactive:
            cnt += master.chip_html(f"미사용 {inactive}", "mute")

    if not filt and not cnt:
        return
    st.markdown(
        "<div style='display:flex;justify-content:space-between;align-items:center;"
        "gap:.5rem;margin:.1rem 0 .2rem'>"
        f"<div style='display:flex;gap:.3rem;flex-wrap:wrap'>{filt}</div>"
        f"<div style='display:flex;gap:.3rem;flex:0 0 auto'>{cnt}</div>"
        "</div>",
        unsafe_allow_html=True,
    )


def _col_config() -> dict:
    """컬럼별 폭 + 셀 오류/변경 하이라이트(cellClassRules) + 렌더러/에디터 주입."""
    cfg: dict = {}
    for col in _USER_COLS:
        entry = dict(_COL_WIDTHS.get(col, {"cellClass": "md-c-left"}))
        rules = {**style.cell_error_rule(col), **style.cell_dirty_rule(col)}
        if col == "코드":
            rules.update(_CODE_READONLY_RULES)  # 저장행 코드 읽기전용 어포던스(org/users 계약)
        entry["cellClassRules"] = rules
        cfg[col] = entry
    return cfg


# ===========================================================================
# 화면
# ===========================================================================
def render(user: dict) -> None:
    state = DraftState(PAGE_ID)

    sample = db.is_sample_mode()
    mode_badge = style.mode_badge_html(connected=not sample, sample=sample)
    # toolbar=True: 헤더 파랑 밴드에 실제 액션 버튼(추가·삭제·저장·새로고침) 슬롯을 만들고
    # 핸들을 받는다. 버튼은 그리드 뒤 건수 계산 후 band.render 로 채운다(사용자 관리와 동일).
    band = erp.screen_frame(
        SCREEN_ARCHETYPE,
        title="근무형태 관리",
        desc="근무형태(코드·명칭·약칭·색상)를 표에서 직접 편집하고 [저장]으로 일괄 반영합니다.",
        breadcrumb="기준정보 › 근무형태 관리",
        badges=mode_badge,
        toolbar=True,
    )
    st.markdown(_EXTRA_CSS, unsafe_allow_html=True)  # 미리보기·오류 목록 보조 스타일(항상 주입)

    # ---- 조건 패널(우측 인라인 라벨, KP-standard) — 위젯 key 는 기존 DraftState 스코프
    #      키(state.key("f_active")/"f_search")를 widget_key 로 그대로 지정해 세션 상태를
    #      보존한다(구조만 이전, 조회/재적재 로직 불변). ----
    cond = erp.condition_panel(
        PAGE_ID,
        [
            erp.Field(key="active", label="사용 여부", kind="select", options=_STATUS,
                     widget_key=state.key("f_active")),
            erp.Field(key="search", label="검색", kind="text",
                     widget_key=state.key("f_search"), placeholder="코드·명칭·약칭 검색"),
        ],
        cols=2,
    )
    params = {"active": cond["active"], "search": str(cond["search"]).strip()}

    # ---- 재적재 결정(dirty 무경고 소실 금지, §17) ----
    decision = state.resolve_reload(params, refresh=False, dirty=state.is_dirty())
    if decision == RELOAD:
        _load_editor(state, params)
    # CONFIRM → banner_slot 폐기 확인 바에서 처리 / KEEP → 현재 draft 유지

    # ---- 표 위 슬롯(§7): 액션바 → 배너 → 표 순서 확정. 건수는 그리드 후 계산하므로
    #      슬롯을 먼저 확보하고 나중에 채운다(사용자·조직 화면과 동일 배치). ----
    summary_slot = st.container()  # 요약 칩(필터결과 사용/미사용 분포) — 표 위 최상단
    banner_slot = st.container()  # 배너(삭제 확인/폐기 확인/원장/오류/flash 중 1개)

    # ---- 그리드 ----
    frame = _render_frame(state)
    with summary_slot:
        _render_summary_chips(frame, params)
    spec = MasterGridSpec(
        page_id=PAGE_ID, columns=_GRID_COLUMNS, order=_USER_COLS,
        col_config=_col_config(), select_all=True,
        height=master_grid_height(len(frame)),
        grid_options={"onCellValueChanged": _DUP_REFRESH},
    )
    grid_df = render_master_grid(spec, frame, key=state.grid_key())

    # ---- 실시간 건수(§20) — dirty 단일 기준은 액션바 카운터 ----
    live = live_rows(grid_df)
    existing = live[live["_row_state"] == "existing"]
    new_rows = live[live["_row_state"] != "existing"]
    new_count = int(len(new_rows))
    changed_count = _changed_existing_count(state, existing)
    sel_count = int(existing["_sel"].map(grid_bool).sum()) if not existing.empty else 0
    dtotal = dirty_total(new_count, changed_count)
    state.set_dirty(dtotal > 0)
    st.session_state[state.key(_LAST_COUNTS)] = (new_count, changed_count, sel_count)

    # ---- 액션 밴드 채움(상단 파랑 밴드 슬롯에 실제 버튼 지연 채움) ----
    # 활성/비활성·변경 배지·툴팁 사유는 인페이지 액션바(master_action_bar)와 동일 규칙
    # (page_action_specs). 클릭은 band.render 가 state.action_requester(role) on_click
    # 플래그로 남겨 아래 take_actions 가 소비한다(저장/삭제/추가/새로고침 경로 무변경).
    if band is not None:
        band.render(state, master.page_action_specs(
            sel_count=sel_count, dirty_total=dtotal, can_save=True))

    # ---- 배너(표 위 슬롯, 단일 우선순위: 삭제확인 > 폐기확인 > 저장원장/오류 > flash) ----
    with banner_slot:
        _render_banners(state, params)

    # ---- 상태 스트립(§20, 표 하단) + 근무표 미리보기 ----
    count_strip(int(len(existing)), new_count, changed_count, sel_count)
    _render_preview(live)

    # ---- 액션 소비(commit handshake: 최신 grid_df 수신 후에 flag 소비) ----
    actions = master.take_actions(state)
    if actions[SAVE]:
        _save(state, grid_df, params)
    if actions[DELETE]:
        _request_delete(state, grid_df)
    if actions[ADD]:
        _add_row(state, grid_df)
    if actions[REFRESH]:
        _refresh(state, params)

    if _normalize(state, grid_df):
        st.rerun()


# ---------------------------------------------------------------------------
# 표 위 배너 — 한 시점에 최대 1개(§17 우선순위). 슬롯 안에서 렌더한다.
# ---------------------------------------------------------------------------
def _render_banners(state: DraftState, params: dict) -> None:
    plan = st.session_state.get(state.delete_plan_key)
    if plan:
        _confirm_delete(state, plan, params)
        return
    if state.has_pending_reload():
        gate = master.discard_confirm_bar(state)
        if gate == "discard":
            new_params = state.apply_pending_reload()
            _load_editor(state, new_params if new_params is not None else params)
            st.rerun()
        elif gate == "cancel":
            state.cancel_pending_reload()
            st.rerun()
        return
    if _render_save_ledger(state):
        return
    master.show_flash(state)


# ---------------------------------------------------------------------------
# 렌더 프레임 — 세션 rows(CORE_META+user) 에 view-model 메타를 채워 그리드에 넘긴다.
# ---------------------------------------------------------------------------
def _render_frame(state: DraftState) -> pd.DataFrame:
    rows = state.get_rows()
    if rows is None:
        rows = pd.DataFrame(columns=_ROW_COLS)
    frame = rows.copy().reset_index(drop=True)
    for col in _ROW_COLS:
        if col not in frame:
            frame[col] = (col == "사용") if col in _BOOL_COLS else ""
    baseline = st.session_state.get(state.key(_BASELINE), {})
    cell_errors = st.session_state.get(state.key(_CELL_ERRORS), {})

    inactive, dirty_fields, error_meta = [], [], []
    for _, row in frame.iterrows():
        rid = str(row.get("_row_id") or "")
        is_existing = row.get("_row_state") == "existing"
        inactive.append("1" if (is_existing and not grid_bool(row.get("사용"))) else "")
        dirty_fields.append(_dirty_fields_json(row, baseline.get(rid)))
        errs = cell_errors.get(rid)
        error_meta.append(json.dumps(errs, ensure_ascii=False) if errs else "")
    frame["_inactive"] = inactive
    frame["_dirty_fields"] = dirty_fields
    frame["_error"] = error_meta
    return frame


def _dirty_fields_json(row, base) -> str:
    """기존 행이 baseline 대비 바뀐 필드명 JSON. 신규 행/미로드는 빈 문자열."""
    if row.get("_row_state") != "existing" or not base:
        return ""
    changed = [col for col in _USER_COLS if _norm_field(col, row.get(col)) != base.get(col)]
    return json.dumps(changed, ensure_ascii=False) if changed else ""


def _norm_field(col: str, value):
    if col in _BOOL_COLS:
        return bool(grid_bool(value))
    if col == "표시순서":
        return str(value if value is not None else "").strip()
    return str(value if value is not None else "").strip()


def _row_tuple(row) -> dict:
    return {col: _norm_field(col, row.get(col)) for col in _USER_COLS}


def _changed_existing_count(state: DraftState, existing: pd.DataFrame) -> int:
    baseline = st.session_state.get(state.key(_BASELINE), {})
    if existing.empty or not baseline:
        return 0
    n = 0
    for _, row in existing.iterrows():
        base = baseline.get(str(row.get("_row_id") or ""))
        if base is not None and _row_tuple(row) != base:
            n += 1
    return n


# ---------------------------------------------------------------------------
# 구조 변경(붙여넣기 신규 행 / − 제거) 권위 반영 — grid.py 대신 controller 몫.
# ---------------------------------------------------------------------------
def _normalize(state: DraftState, grid_df: pd.DataFrame) -> bool:
    if grid_df is None or grid_df.empty or "_row_id" not in grid_df.columns:
        return False
    removed = (grid_df["_removed"].fillna("").astype(str).str.strip() == "1"
               if "_removed" in grid_df else pd.Series(False, index=grid_df.index))
    live = grid_df[~removed].copy()
    rid = live["_row_id"].fillna("").astype(str).str.strip()
    needs_id = rid == ""
    if not (removed.any() or needs_id.any()):
        return False
    live["_row_id"] = rid
    for idx in live.index[needs_id]:
        live.at[idx, "_row_id"] = state.next_rid()
        live.at[idx, "_row_state"] = "new"
        live.at[idx, "_sel"] = False
    live["_row_state"] = live["_row_state"].fillna("").astype(str).replace("", "new")
    state.set_rows(live[_ROW_COLS].reset_index(drop=True))
    state.bump_nonce()
    return True


def _next_order(rows: pd.DataFrame) -> int:
    orders = pd.to_numeric(rows.get("표시순서"), errors="coerce").dropna()
    return int(orders.max()) + 1 if len(orders) else 1


def _new_row(state: DraftState, order_val: int) -> dict:
    row = {"_row_id": state.next_rid(), "_row_state": "new", "_sel": False, "_removed": ""}
    for c in _USER_COLS:
        row[c] = (c == "사용") if c in _BOOL_COLS else ""
    row["색상"] = _DEFAULT_COLOR
    row["표시순서"] = str(order_val)
    return row


def _add_row(state: DraftState, grid_df: pd.DataFrame) -> None:
    live = live_rows(grid_df)
    combined = pd.concat(
        [live[_ROW_COLS], pd.DataFrame([_new_row(state, _next_order(live))])],
        ignore_index=True,
    )[_ROW_COLS]
    state.set_rows(combined)
    state.bump_nonce()
    st.rerun()


def _refresh(state: DraftState, params: dict) -> None:
    if state.is_dirty():
        st.session_state[state.pending_query_key] = params
    else:
        _load_editor(state, params)
    st.rerun()


# ---------------------------------------------------------------------------
# 삭제 (기존 저장 행 전용) — 참조 있으면 미사용, 없으면 물리 삭제. 2단계 확인.
# ---------------------------------------------------------------------------
def _request_delete(state: DraftState, grid_df: pd.DataFrame) -> None:
    live = live_rows(grid_df)
    sel = live[(live["_row_state"] == "existing") & live["_sel"].map(grid_bool)]
    codes = sorted({str(c).strip() for c in sel["코드"] if str(c).strip()})
    if not codes:
        state.set_flash("warning", "삭제할 기존 근무형태를 선택하세요.")
        st.rerun()
    plan = {"delete": [], "deactivate": []}
    for code in codes:
        refs = db.work_type_reference_counts(code)
        item = {"code": code, "refs": refs}
        (plan["deactivate"] if sum(refs.values()) > 0 else plan["delete"]).append(item)
    st.session_state[state.delete_plan_key] = plan
    st.rerun()


def _confirm_delete(state: DraftState, plan: dict, params: dict) -> None:
    retry_err = st.session_state.get(state.key(_DELETE_ERROR))
    lines = []
    if retry_err:
        lines.append("이전 시도 실패(재시도 가능): " + retry_err)
    if plan["delete"]:
        lines.append("완전 삭제: " + ", ".join(it["code"] for it in plan["delete"]))
    for it in plan["deactivate"]:
        lines.append(f"미사용 처리: {it['code']} — 근무표 {it['refs'].get('schedules', 0)}건 사용 중")
    result = confirm_bar(
        state,
        title="선택한 근무형태를 다음과 같이 처리합니다.",
        lines=lines, confirm_label="재시도" if retry_err else "실행", scope="del",
    )
    if result == "confirm":
        st.session_state.pop(state.key(_DELETE_ERROR), None)
        _execute_delete(state, plan, params)
    elif result == "cancel":
        st.session_state.pop(state.delete_plan_key, None)
        st.session_state.pop(state.key(_DELETE_ERROR), None)
        st.rerun()


def _execute_delete(state: DraftState, plan: dict, params: dict) -> None:
    """삭제/비활성 write 를 대상별로 실행하고 실패를 controller 경계에서 흡수한다(B4).

    - 물리 삭제(참조 0)와 미사용 처리(참조>0)를 각각 실행하고 성공/실패를 판정한다.
    - 성공분만 재조회(_load_editor)하고, 실패분은 재시도 가능한 삭제 계획으로 남긴다.
    - ``DATA_SOURCE_ERRORS``(supabase 통신/제약) 는 사용자용 배너 문구로 변환한다.
    2단계 확인·참조 시 비활성/미참조 시 물리삭제 계약은 유지한다.
    """
    done_del, done_deact, failed = [], [], []

    # 참조 없는 코드 — 물리 삭제(대상별로 실패 격리).
    for it in plan["delete"]:
        try:
            db.delete_work_type(it["code"])
            done_del.append(it["code"])
        except db.DATA_SOURCE_ERRORS as exc:
            failed.append({"item": it, "bucket": "delete", "reason": _err_text(exc)})

    # 참조 있는 코드 — is_active=False 소프트삭제. 원장 API 로 부분성공을 판정한다.
    deact = list(plan["deactivate"])
    if deact:
        codes = [it["code"] for it in deact]
        try:
            store = db.get_work_types().copy()
            mask = store["code"].astype(str).isin(codes)
            store.loc[mask, "is_active"] = False
            report = db.save_work_types_report(store[db.WORK_TYPE_COLUMNS])
        except db.DATA_SOURCE_ERRORS as exc:
            for it in deact:
                failed.append({"item": it, "bucket": "deactivate", "reason": _err_text(exc)})
        else:
            saved = {_key_str(k) for k in report.saved_keys}
            failed_k = {_key_str(k) for k in report.failed_keys}
            for it in deact:
                c = it["code"]
                if report.ok or c in saved:
                    done_deact.append(c)
                elif report.unknown:
                    failed.append({"item": it, "bucket": "deactivate",
                                   "reason": report.error or "결과 불명 · 재조회 필요"})
                elif c in failed_k:
                    failed.append({"item": it, "bucket": "deactivate",
                                   "reason": report.error or "저장 실패"})
                else:  # 보고에 없으면 보수적으로 실패로 남겨 재시도 대상에 둔다.
                    failed.append({"item": it, "bucket": "deactivate",
                                   "reason": report.error or "결과를 확인할 수 없습니다."})

    st.session_state.pop(state.delete_plan_key, None)

    if done_del or done_deact:
        _load_editor(state, params)  # 성공분만 반영(재조회)

    parts = []
    if done_del:
        parts.append(f"{len(done_del)}개 삭제")
    if done_deact:
        parts.append(f"{len(done_deact)}개 미사용 처리")

    if failed:
        # 실패분은 재시도 가능한 계획으로 남기고, 사유를 재시도 확인 바에 노출한다.
        st.session_state[state.delete_plan_key] = {
            "delete": [f["item"] for f in failed if f["bucket"] == "delete"],
            "deactivate": [f["item"] for f in failed if f["bucket"] == "deactivate"],
        }
        done_txt = ("처리 완료 " + ", ".join(parts) + "; ") if parts else ""
        reasons = " / ".join(f"{f['item']['code']}: {f['reason']}" for f in failed)
        st.session_state[state.key(_DELETE_ERROR)] = f"{done_txt}실패 {len(failed)}건 — {reasons}"
        st.rerun()

    msg = "근무형태를 " + ", ".join(parts) + "했습니다." if parts else "처리할 근무형태가 없습니다."
    state.set_flash("success" if parts else "warning", msg)
    st.rerun()


def _err_text(exc: Exception) -> str:
    text = str(exc).strip()
    return text or "데이터 저장 중 오류가 발생했습니다."


def _key_str(key) -> str:
    if isinstance(key, (tuple, list)):
        return "/".join(str(k) for k in key)
    return str(key)


# ---------------------------------------------------------------------------
# 적재 / 저장
# ---------------------------------------------------------------------------
def _load_editor(state: DraftState, q: dict) -> None:
    df = db.get_work_types().copy()
    if q["active"] == "사용 중":
        df = df[df["is_active"].astype(bool)]
    elif q["active"] == "사용 안 함":
        df = df[~df["is_active"].astype(bool)]
    term = str(q.get("search", "")).strip()
    if term:
        hit = (
            df["code"].astype(str).str.contains(term, case=False, na=False, regex=False)
            | df["name"].astype(str).str.contains(term, case=False, na=False, regex=False)
            | df["short_label"].astype(str).str.contains(term, case=False, na=False, regex=False)
        )
        df = df[hit]
    df = df.sort_values("sort_order").reset_index(drop=True)
    order = pd.to_numeric(df["sort_order"], errors="coerce").fillna(0).astype("int64")

    if df.empty:
        rows = pd.DataFrame(columns=_ROW_COLS)
    else:
        rows = pd.DataFrame({
            "_row_id": "e:" + df["code"].astype(str),
            "_row_state": "existing", "_sel": False, "_removed": "",
            "코드": df["code"].fillna("").astype("string"),
            "명칭": df["name"].fillna("").astype("string"),
            "분류": df["category"].fillna("").astype("string"),
            "약칭": df["short_label"].fillna("").astype("string"),
            "시작": df["start_time"].fillna("").astype("string"),
            "종료": df["end_time"].fillna("").astype("string"),
            "색상": df["color"].fillna("").astype("string"),
            "실근무": df["is_work"].fillna(False).astype(bool),
            "특근수당": df["affects_allowance"].fillna(False).astype(bool),
            "설명": df["description"].fillna("").astype("string"),
            "표시순서": order.astype(str).astype("string"),
            "사용": df["is_active"].fillna(True).astype(bool),
        })[_ROW_COLS]

    state.set_rows(rows)
    st.session_state[state.key(_BASELINE)] = {
        str(r["_row_id"]): _row_tuple(r) for _, r in rows.iterrows()
    }
    st.session_state.pop(state.key(_CELL_ERRORS), None)
    st.session_state.pop(state.key(_SAVE_ERRORS), None)
    st.session_state.pop(state.key(_SAVE_LEDGER), None)
    st.session_state.pop(state.key(_DELETE_ERROR), None)
    state.set_dirty(False)
    state.bump_nonce()


def _save(state: DraftState, grid_df: pd.DataFrame, q: dict) -> None:
    live = live_rows(grid_df)
    st.session_state.pop(state.key(_SAVE_ERRORS), None)
    st.session_state.pop(state.key(_SAVE_LEDGER), None)
    counts: dict = {}

    def validate():
        records, errors, emap = _validate_detailed(live)
        st.session_state[state.key(_CELL_ERRORS)] = emap
        return records, errors

    def build_candidate(records):
        store = db.get_work_types()
        merged, dup, n_c, n_u, _n_d = db.upsert_records(
            store, records, set(), ["code"], "is_active", db.WORK_TYPE_COLUMNS,
        )
        errs = []
        if dup:
            errs.append("근무형태 코드가 중복되었습니다: " + ", ".join(k[0] for k in dup))
        counts["c"], counts["u"], counts["records"] = n_c, n_u, records
        return merged, errs

    def persist(merged, records):
        # B2: void save_work_types 대신 원장 반환 API 를 호출해 batch 부분성공을
        # controller 까지 전달한다(PersistResult 로 그대로 매핑).
        report = db.save_work_types_report(merged)
        return PersistResult(page_id=state.page_id, **report.to_persist_kwargs())

    outcome = run_save(state, validate=validate, build_candidate=build_candidate, persist=persist)

    if outcome.status == "saved":
        _load_editor(state, q)
        state.set_flash(*_success_flash(counts))
        st.rerun()

    if outcome.status in ("partial", "unknown") and outcome.result is not None:
        # §22: 성공 자연키만 baseline 에 reconcile(더 이상 dirty 아님), 실패 key 의
        # draft·cell error·재시도 affordance 는 보존. 재적재/리마운트하지 않는다.
        _reconcile_partial(state, outcome.result, live)
        st.session_state[state.key(_SAVE_LEDGER)] = outcome.result
        st.rerun()

    # invalid / failed — draft 를 재적재/리마운트 없이 보존하고 표 위 오류 배너만 갱신.
    st.session_state[state.key(_SAVE_ERRORS)] = {"errors": list(outcome.errors) or _result_errors(outcome)}
    st.rerun()


def _reconcile_partial(state: DraftState, result, live: pd.DataFrame) -> None:
    """부분성공/결과불명: 성공 key 는 baseline 갱신(clean), 실패 key 는 셀 오류 표기."""
    by_code: dict = {}
    for _, row in live.iterrows():
        by_code.setdefault(str(row.get("코드") or "").strip(), []).append(row)
    baseline = dict(st.session_state.get(state.key(_BASELINE), {}))
    cell_errors = dict(st.session_state.get(state.key(_CELL_ERRORS), {}))
    for key in result.succeeded_keys:
        for row in by_code.get(_key_str(key), []):
            rid = str(row.get("_row_id") or "")
            if row.get("_row_state") == "existing":
                baseline[rid] = _row_tuple(row)  # 저장됨 → 더 이상 변경 아님
            cell_errors.pop(rid, None)
    for key in result.failed_keys:
        for row in by_code.get(_key_str(key), []):
            rid = str(row.get("_row_id") or "")
            cell_errors.setdefault(rid, {})["코드"] = result.error or "저장 실패"
    st.session_state[state.key(_BASELINE)] = baseline
    st.session_state[state.key(_CELL_ERRORS)] = cell_errors


def _success_flash(counts: dict):
    n_c, n_u = counts.get("c", 0), counts.get("u", 0)
    msg = f"근무형태를 저장했습니다. (신규 {n_c} · 수정 {n_u})"
    dup = _duplicate_short_labels(counts.get("records", []))
    if dup:
        return "warning", (msg + f" 다만 약칭 {', '.join(dup)} 이(가) 여러 코드에 걸려 "
                           "근무표에서 코드로 표시됩니다.")
    return "success", msg


def _result_errors(outcome) -> list:
    if outcome.result is not None and outcome.result.error:
        return [outcome.result.error]
    return ["저장하지 못했습니다."]


def _duplicate_short_labels(records) -> list:
    seen, dup = {}, set()
    for rec in records:
        if not rec.get("is_active"):
            continue
        label = str(rec.get("short_label") or "").strip()
        if not label:
            continue
        if label in seen:
            dup.add(label)
        seen[label] = True
    return sorted(dup)


def _render_save_ledger(state: DraftState) -> bool:
    """§22 저장 결과 원장(부분성공/결과불명) 또는 검증 실패 배너. 렌더 시 True."""
    ledger = st.session_state.get(state.key(_SAVE_LEDGER))
    if ledger is not None:
        ledger_banner(ledger)  # 성공/실패 키 칩 · 결과 불명 분리(재조회 필요)
        return True
    payload = st.session_state.get(state.key(_SAVE_ERRORS))
    if payload:
        errors = payload.get("errors", [])
        new_c, changed_c, _sel = st.session_state.get(state.key(_LAST_COUNTS), (0, 0, 0))
        items = "".join(f"<li>{style.escape(e)}</li>" for e in errors)
        absorb = ""
        if new_c or changed_c:
            absorb = (f"<div class='ms-absorb'>· 미저장 {new_c + changed_c}건"
                      f"(신규 {new_c} · 기존 변경 {changed_c})은 그대로 유지됩니다.</div>")
        style.banner(
            "danger", f"{len(errors)}개 항목에 오류가 있어 저장하지 못했습니다.",
            extra=f"<ul class='ms-errlist'>{items}</ul>{absorb}",
        )
        return True
    return False


# ---------------------------------------------------------------------------
# 저장 전 검증 — (records, errors) 는 기존 계약 유지. detailed 는 셀 오류 맵 추가.
# ---------------------------------------------------------------------------
def _validate(live: pd.DataFrame):
    """표시형 편집 프레임을 저장형 records 로 변환하고 행 오류를 수집한다.

    반환 ``(records, errors)`` — 기존 계약(scripts/test_master_and_views 등)과 동일.
    """
    records, errors, _emap = _validate_detailed(live)
    return records, errors


def _validate_detailed(live: pd.DataFrame):
    records, errors, emap = [], [], {}
    for i, (_, row) in enumerate(live.iterrows(), start=1):
        rid = str(row.get("_row_id") or "")
        code = str(row.get("코드") or "").strip()
        name = str(row.get("명칭") or "").strip()
        category = str(row.get("분류") or "").strip()
        short_label = str(row.get("약칭") or "").strip()
        if not any([code, name, category, short_label]):
            continue  # 완전 빈 행은 저장 대상에서 제외

        tag = f"{i}행" + (f"({code})" if code else "")
        row_errs: dict = {}
        if not code:
            errors.append(f"{i}행: 근무형태 코드를 입력하세요.")
            row_errs["코드"] = "코드를 입력하세요."
        if not name:
            errors.append(f"{tag}: 근무형태명을 입력하세요.")
            row_errs["명칭"] = "명칭을 입력하세요."
        if not short_label:
            errors.append(f"{tag}: 약칭을 입력하세요.")
            row_errs["약칭"] = "약칭을 입력하세요."
        if not category:
            errors.append(f"{tag}: 분류를 입력하세요.")
            row_errs["분류"] = "분류를 입력하세요."

        # 표시순서 — 숫자.
        try:
            order_val = int(row.get("표시순서")) if str(row.get("표시순서")).strip() != "" else 0
        except (TypeError, ValueError):
            order_val = 0
            errors.append(f"{tag}: 표시순서는 숫자여야 합니다.")
            row_errs["표시순서"] = "숫자만 입력하세요."

        # 색상 — 빈 값은 기본색, 비어있지 않으면 #RRGGBB 검증(3자리/누락 # 보정).
        color_raw = str(row.get("색상") or "").strip()
        if color_raw == "":
            color = _DEFAULT_COLOR
        else:
            norm = _normalize_hex(color_raw)
            if norm is None:
                errors.append(f"{tag}: 색상 형식 오류 — #RRGGBB 6자리로 입력하세요 (예: #2E9E5B)")
                row_errs["색상"] = "올바른 #RRGGBB 형식이 아닙니다."
                color = color_raw
            else:
                color = norm

        # 시간 — 빈 값 허용, 있으면 HH:MM.
        start_time = _check_time(str(row.get("시작") or "").strip(), tag, "시작", errors, row_errs)
        end_time = _check_time(str(row.get("종료") or "").strip(), tag, "종료", errors, row_errs)

        if row_errs and rid:
            emap[rid] = row_errs

        records.append({
            "code": code, "name": name, "category": category, "short_label": short_label,
            "start_time": start_time, "end_time": end_time, "color": color,
            "is_work": grid_bool(row.get("실근무")),
            "affects_allowance": grid_bool(row.get("특근수당")),
            "description": str(row.get("설명") or "").strip(),
            "sort_order": order_val,
            "is_active": grid_bool(row.get("사용")),
        })
    return records, errors, emap


def _check_time(value: str, tag: str, label: str, errors: list, row_errs: dict) -> str:
    if value and not _TIME_RE.match(value):
        errors.append(f"{tag}: {label} 시간 형식 오류 — HH:MM 으로 입력하세요 (예: 08:00)")
        row_errs[label] = "HH:MM 형식으로 입력하세요."
    return value


def _normalize_hex(value: str):
    """``#RRGGBB`` 대문자로 정규화. 3자리 확장·누락 # 보정. 실패 시 None."""
    s = str(value or "").strip()
    if not s:
        return ""
    body = s[1:] if s.startswith("#") else s
    if _HEX3_RE.match(body):
        body = "".join(ch * 2 for ch in body)
    if _HEX_BODY_RE.match(body):
        return "#" + body.upper()
    return None


def _text_on(color: str) -> str:
    """solid 배경색 ``#RRGGBB`` 위에서 4.5:1 이상을 보장하는 텍스트색(흰/검) 선택.

    WCAG 상대명도를 계산해 흰색(#FFFFFF)과 순수 검정(#000000) 중 대비가 큰 쪽을 고른다.
    두 후보의 대비 최댓값은 배경 명도 전 구간에서 ≈4.58:1 이상이라 본문 대비를 항상 만족한다
    (미리보기 배지 저대비 §8 보수). 어두운 쪽을 #111 등으로 완화하면 크로스오버 근처에서
    4.5 밑으로 떨어지므로 순수 검정을 사용한다.
    """
    try:
        r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
    except (ValueError, IndexError):
        return "#FFFFFF"

    def _lin(v: int) -> float:
        c = v / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    lum = 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)
    contrast_white = 1.05 / (lum + 0.05)
    contrast_black = (lum + 0.05) / 0.05
    return "#FFFFFF" if contrast_white >= contrast_black else "#000000"


# ---------------------------------------------------------------------------
# 근무표 미리보기 — color/약칭 단일 기준이 근무표·대시보드·개인 화면 색을 구동함을 시연.
# ---------------------------------------------------------------------------
_PREVIEW_CAP = 40  # 미리보기 스와치 상한(초과분은 '외 N개' 표식으로 알린다)


def _preview_html(live: pd.DataFrame) -> str:
    """근무표/대시보드 색·약칭 미리보기 HTML(순수, DESIGN.md §150 계약) — 조밀 한 줄.

    색상 스와치 + 약칭이 근무표·대시보드·개인 화면에 그대로 적용됨을 미리 보인다.
    편집 그리드와 겹치는 명칭·시간은 반복하지 않고 계약 정보(색·약칭)만 조밀하게 노출한다.
    약칭 셀은 근무표 렌더처럼 근무형태 색을 입혀(틴트 배경+색 텍스트) 적용 결과를 시연한다.
    약칭이 비면 코드로 대체한다(색은 코드에 귀속). 표시 대상이 상한을 넘으면 마지막에
    '외 N개' 표식(전체 건수 tooltip)을 붙여 잘림을 알린다. 대상이 없으면 빈 문자열.
    """
    if live is None or live.empty:
        return ""
    sws, total = [], 0
    for _, row in live.iterrows():
        if not grid_bool(row.get("사용")):
            continue
        color = _normalize_hex(str(row.get("색상") or ""))
        if not color:
            continue
        code = str(row.get("코드") or "").strip()
        label = str(row.get("약칭") or "").strip() or code
        if not label:
            continue
        total += 1
        if len(sws) >= _PREVIEW_CAP:
            continue  # 계속 세되(전체 건수), 렌더는 상한까지만
        name = str(row.get("명칭") or "").strip()
        title = " · ".join(x for x in (code, name) if x) or label
        # 실제 근무표 배지(.duty-badge)처럼 solid 색 배경으로 시연하되, 텍스트색은 배경
        # 명도에 따라 흰/검을 자동 선택해 밝은 색에서도 4.5:1 이상을 보장한다(§8 대비 보수).
        sws.append(
            f"<span class='ms-sw' title='{style.escape(title)}'>"
            f"<span class='c' style='background:{color};color:{_text_on(color)};'>"
            f"{style.escape(label)}</span>"
            f"</span>"
        )
    if not sws:
        return ""
    shown = len(sws)
    more = total - shown
    if more > 0:
        sws.append(
            f"<span class='ms-sw more' title='전체 {total}개 중 {shown}개 표시 · {more}개 더 있음'>"
            f"<span class='c'>외 {more}개</span></span>"
        )
    return (
        "<div class='ms-preview'>"
        "<span class='ms-preview-t'>근무표 색·약칭 미리보기</span>"
        f"<span class='ms-sws'>{''.join(sws)}</span></div>"
    )


def _render_preview(live: pd.DataFrame) -> None:
    html = _preview_html(live)
    if html:
        st.markdown(html, unsafe_allow_html=True)


_EXTRA_CSS = """
<style>
.ms-preview { margin-top:.5rem; display:flex; align-items:center; gap:.5rem; flex-wrap:wrap;
  background:var(--ms-surface); border:1px solid var(--ms-line); border-radius:8px;
  padding:.38rem .6rem; }
.ms-preview-t { flex:0 0 auto; font-size:.72rem; font-weight:700; color:var(--ms-ink-2);
  letter-spacing:-.01em; }
.ms-sws { display:flex; flex-wrap:wrap; gap:.26rem; }
.ms-sw { display:inline-flex; align-items:center; padding:.12rem; flex:0 0 auto;
  background:var(--ms-surface-2); border:1px solid var(--ms-line); border-radius:5px; }
.ms-sw .c { font-size:.7rem; font-weight:700; line-height:1; padding:.14rem .4rem;
  border-radius:4px; font-variant-numeric:tabular-nums; letter-spacing:.01em;
  border:1px solid rgba(0,0,0,.12); }
.ms-sw.more { border-style:dashed; }
.ms-sw.more .c { color:var(--ms-ink-3); font-weight:600; padding:.12rem .2rem; }
.ms-errlist { margin:.25rem 0 0; padding-left:1.1rem; font-size:.76rem; color:var(--ms-ink-2); }
.ms-absorb { color:var(--ms-ink-2); font-size:.72rem; margin-top:.3rem; }
</style>
"""
