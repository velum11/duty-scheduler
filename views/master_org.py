"""기준정보 — 조직 관리: 가로 3시트 [그룹][부서][조] 드릴다운 화면.

부서 관리·조 관리 메뉴는 모두 이 화면을 연다 (사이드바 메뉴 구조는 무변경).
데이터 계층(migration 004)은 그룹(organization_groups) → 부서(departments.group_id)
→ 조(teams.department_id)를 전부 group_code/dept_code(내부 FK)로 조회·저장한다.
이 화면은 트리 UI 를 쓰지 않고, 세 개의 독립 시트를 가로로 배치해 상위 시트의 **행을
직접 클릭**하면 하위 시트가 열리는 마스터-디테일 드릴다운으로 구성한다(별도 상위 선택
selectbox/드롭다운 없음). 상위→하위로 진행되는 활성 체인은 단계 배지·커넥터·비선택 하위
디엠퍼시스로 시각화한다.

각 시트는 공통 컬럼(코드 / 코드명 / 순서 / 비고 / 사용)을 가지며, 조 시트만 유형
(교대=SHIFT / 일반=GENERAL)을 추가한다. 세 시트는 각각 독립 저장 계약을 가진다:
  - 그룹 시트 = ``org_group``(_GRP), 부서 시트 = ``org_dept``(_OD),
    조 시트 = ``org_unit``(_OU). page-scoped DraftState 로 편집 상태를 고립한다.
  - 상위(그룹/부서)의 저장된 행을 클릭하면 그 상위가 선택된다 — 미저장 상위 행에는
    하위를 추가할 수 없다(저장 후 존재하는 행만 클릭 드릴다운 대상이 됨).
  - 상위 미선택이면 하위 시트를 잠근다(sheet_locked + 모든 write control 비활성).
  - 상위 선택을 바꿀 때 하위에 미저장 draft 가 있으면 폐기/계속 게이트를 태운다.
  - 저장된 코드는 수정 불가(신규 등록 시에만 입력), 저장 실패 시 draft 를 보존한다.
  - 저장 전 신규행 삭제 = 즉시 제거, 저장행 삭제 = 참조 확인 후 미사용/삭제.
  - ADMIN 그룹·부서는 코드수정·미사용처리 등 화면 보호(_protected).

공통 기반 패키지(``views/master``)의 계약(DraftState/MasterGridSpec/run_save/
ReadinessState/master_action_bar/ledger_banner/sheet_head/sheet_locked/
drilldown_context/공통 style)을 그대로 사용하고, migration 004 미적용 시 저장을
차단(UI + repository 이중 방어)한다.

순수·도메인 함수(``build_group_rows``/``build_dept_rows``/``build_team_rows``/
``_validate_groups``/``_validate_depts``/``_validate_units``/``_unit_structure_errors``/
``_group_structure_errors``)는 계약 테스트 대상이라 UI 없이 단위 검증 가능하다.
그중 ``_validate_units``/``_unit_structure_errors``/``_group_structure_errors`` 는
교차 화면 회귀 테스트가 참조하는 시그니처라 보존한다.
"""
from html import escape

import pandas as pd
import streamlit as st
from st_aggrid import JsCode

from modules import db
from views.master import (
    ADD,
    DELETE,
    REFRESH,
    RELOAD,
    SAVE,
    DraftState,
    MasterGridSpec,
    PersistResult,
    Readiness,
    ReadinessState,
    banner,
    chip_html,
    confirm_bar,
    count_strip,
    dirty_total,
    discard_confirm_bar,
    drilldown_context,
    empty_state,
    grid_bool,
    ledger_banner,
    live_rows,
    master_action_bar,
    master_grid_height,
    master_screen_head,
    mode_badge_html,
    render_master_grid,
    run_save,
    sheet_head,
    sheet_locked,
    show_flash,
)

_STATUS = ["사용 중", "사용 안 함", "전체"]

# 세 시트의 page-scoped 편집 상태. page_id 는 공통 액션바 버튼 키(`{page_id}__{role}`)와
# 공용 CSS 부분일치 선택자(`[class*="__save"]` 등)의 스코프이기도 하다. 부서=org_dept,
# 조=org_unit 은 기존 교차 화면 계약(버튼 키·소스 심볼)을 그대로 유지하는 이름이다.
_GRP = DraftState("org_group")  # 그룹(organization_groups)
_OD = DraftState("org_dept")    # 부서(선택 그룹의 departments)
_OU = DraftState("org_unit")    # 조(선택 부서의 teams = 운영단위)

# migration 004 미적용/probe 실패 배너 문구(계약: 소스에 1회).
_NOT_READY_MSG = "조직 스키마(migration 004) 적용 전 — 조회만 가능하며 저장은 차단됩니다."
_PROBE_ERROR_MSG = "조직 스키마 상태 확인 실패 — 재확인이 필요합니다 (조회만 가능하며 저장은 차단됩니다)."

_SYSTEM_CODES = {"ADMIN"}  # 화면 보호 대상(코드수정·미사용·삭제 차단)

# 공통 컬럼(그룹·부서 시트). field 명이 곧 표시 헤더다.
_GROUP_COLS = ["코드", "코드명", "순서", "비고", "사용"]
_GROUP_ROW_COLS = ["_row_id", "_row_state", "_sel", *_GROUP_COLS]
_GROUP_GRID_COLUMNS = {"코드": "text", "코드명": "text", "순서": "text", "비고": "text", "사용": "bool"}

_DEPT_COLS = ["코드", "코드명", "순서", "비고", "사용"]
_DEPT_ROW_COLS = ["_row_id", "_row_state", "_sel", *_DEPT_COLS]
_DEPT_GRID_COLUMNS = {"코드": "text", "코드명": "text", "순서": "text", "비고": "text", "사용": "bool"}

# 조 시트 — field 명은 교차 화면 테스트가 참조하는 ``_validate_units`` 의 키(명칭/표시순서)를
# 유지하고, 표시 헤더만 다른 시트와 통일(코드명/순서)한다. 유형 컬럼이 추가된다.
_UNIT_COLS = ["코드", "명칭", "유형", "표시순서", "비고", "사용"]
_UNIT_ROW_COLS = ["_row_id", "_row_state", "_sel", *_UNIT_COLS]
_UNIT_GRID_COLUMNS = {
    "코드": "text", "명칭": "text", "유형": "text", "표시순서": "text", "비고": "text", "사용": "bool",
}

# 유형 입력 정규화 — 화면 표시값(교대/일반)과 내부값(SHIFT/GENERAL) 모두 허용.
_UNIT_TYPE_OF = {"교대": "SHIFT", "일반": "GENERAL", "SHIFT": "SHIFT", "GENERAL": "GENERAL"}

# 저장된 코드는 수정 불가 — 신규 행에서만 코드 입력을 허용한다.
_EDIT_NEW_ONLY = JsCode("function(p){ return !!(p.data && p.data._row_state === 'new'); }")
# 보호 행(ADMIN)은 코드 외 셀도 편집 불가(미사용·재귀속 차단, 화면 보호).
_EDIT_UNLESS_PROTECTED = JsCode(
    "function(p){ return !(p.data && (p.data._protected === '1' || p.data._protected === 1)); }"
)
# 선택된 상위 행은 공통 ``ms-row-linked`` 행 강조(네이비 틴트)로만 표시한다 — 코드명 옆
# 코드명 옆에 붙던 별도 '열림' 표시 칩은 상단 브레드크럼·헤더 컨텍스트와 중복돼 제거한다(ERP).
# 행 강조는 spec ``include_linked_rows`` + ``_linked`` 플래그로 구동되므로 칩 없이도 유지된다.

# 조직 전용 페이지 크롬 — 공통 크롬(views/master/style)을 소비만 하고, 이 화면 고유의
# Wave B 폴리시만 페이지 스코프로 얹는다:
#   (1) 선택 컨텍스트·계층(그룹›부서›조) 통합 브레드크럼 강조(.ms-ctx),
#   (2) 활성/잠김 상태 표시(활성 시트 상단 네이비 액센트 + 잠긴 시트 디엠퍼시스) —
#       계층 순서는 (1) 브레드크럼이 표현하므로 단계 배지·커넥터 장식은 두지 않는다,
#   (3) 잠김 상태 밀도 완화(슬림 플레이스홀더 + 잠긴 시트의 비활성 액션바 숨김 →
#       시트별 액션바 반복 소음 축소), (4) 저장코드 읽기전용 어포던스는 공통 .ms-cell-readonly
#       클래스를 col_config cellClassRules 로 소비.
# 3시트 세로 스택(≤1100px)은 공통 style 의 `stHorizontalBlock:has([class*="__sheet"])` 규칙.
_ORG_PAGE_CSS = """
<style>
/* 시트 액션바 버튼은 절대 세로로 줄바꿈하지 않는다(좁은 폭에서도 눌림 방지). */
.st-key-org_group__sheet div.stButton > button,
.st-key-org_dept__sheet div.stButton > button,
.st-key-org_unit__sheet div.stButton > button {
  white-space:nowrap; min-width:0; overflow:hidden; text-overflow:ellipsis; }

/* ── (1) 선택 컨텍스트·계층 통합 브레드크럼 — 상단 .ms-ctx 를 스텝 경로로 강조 ── */
.ms-ctx { padding:.5rem .8rem; font-size:.8rem; box-shadow:0 1px 0 rgba(0,0,0,.02); }
.ms-ctx > span:first-child { font-weight:700; letter-spacing:.03em; text-transform:uppercase;
  font-size:.66rem; color:var(--ms-ink-3); }
.ms-ctx b { padding:.04rem .45rem; border-radius:5px; background:#E5EAF2; border:1px solid #C6D2E4;
  color:var(--ms-navy); }
.ms-ctx b.pin { background:var(--ms-navy); color:#FFF; border-color:var(--ms-navy); }
.ms-ctx .arw { font-size:.92rem; color:var(--ms-line-strong); }
.ms-ctx .none { font-style:normal; color:var(--ms-ink-3); }

/* ── (2) 활성/잠김 상태 표시 — 지금 편집 가능한 시트를 즉시 식별(편집 안전성) ──
   계층 순서(그룹›부서›조)는 상단 .ms-ctx 브레드크럼이 이미 표현하므로 단계 배지·시트
   커넥터 같은 장식은 두지 않는다(ERP: 정보 중복·장식 배제). 여기서는 어느 시트가 활성
   이고 어느 시트가 아직 잠겼는지만 상태로 알린다. */
/* 활성 시트(잠기지 않음 = 상위 선택돼 열린 시트) — 상단 네이비 액센트 */
.st-key-org_group__sheet:not(:has(.ms-locked)),
.st-key-org_dept__sheet:not(:has(.ms-locked)),
.st-key-org_unit__sheet:not(:has(.ms-locked)) { border-top:2px solid var(--ms-navy); }
/* 비활성(잠긴) 하위 시트 — 디엠퍼시스로 아직 진행 전임을 표현 */
.st-key-org_dept__sheet:has(.ms-locked),
.st-key-org_unit__sheet:has(.ms-locked) { opacity:.72; }

/* ── (3) 잠김 상태 밀도 완화 ──
   ① 잠긴 하위 시트의 큰 빈 플레이스홀더를 슬림하게(높이·여백 축소),
   ② 잠긴 시트의 비활성 액션바(저장 버튼을 품은 행)는 숨겨 헤더+슬림 안내만 남긴다 →
      3개 시트 액션바 반복의 시각 소음을 줄이고 '아직 못 여는' 상태를 가볍게 표현한다.
      버튼 위젯 자체는 DOM 에 남아(page-scoped 키·비활성 계약 보존) 접근성·회귀에 영향 없다. */
.st-key-org_dept__sheet .ms-locked,
.st-key-org_unit__sheet .ms-locked { min-height:118px; padding:1.25rem 1rem; gap:.35rem; }
.st-key-org_dept__sheet .ms-locked .glyph,
.st-key-org_unit__sheet .ms-locked .glyph { font-size:1.1rem; }
.st-key-org_dept__sheet:has(.ms-locked) div[data-testid="stHorizontalBlock"]:has(.st-key-org_dept__save),
.st-key-org_unit__sheet:has(.ms-locked) div[data-testid="stHorizontalBlock"]:has(.st-key-org_unit__save) {
  display:none !important; }
</style>
"""

# 행 클릭 드릴다운 — 데이터 셀 클릭 시 저장된 상위 행을 단일 선택(_linked)으로 표시한다.
# _action 열(선택 체크박스/− 제거)의 기존 동작은 그대로 보존하고, 데이터 셀 클릭에서만
# 이 행을 '열린 상위'로 표시한다: 다른 노드의 _linked 를 지우고 클릭 노드에 '1' 을 쓴다
# → cellValueChanged 가 발생해 Python 이 안정 코드키(코드 컬럼)를 읽어 선택을 갱신한다.
# 신규/draft 행·편집 중·이미 선택된 행은 양보해(편집·붙여넣기와 충돌 없음) rerun 을
# 유발하지 않는다.
_DRILL_CLICK = JsCode(
    """
    function(e) {
      var colId = e.colDef && e.colDef.field;
      var d = (e.node && e.node.data) || {};
      var t = e.event && e.event.target;
      if (colId === '_action') {                       // 선택/제거 열 — 기존 동작 보존
        if (!t || !t.classList) { return; }
        if (t.classList.contains('md-act-rm')) {
          e.node.setDataValue('_removed', '1');
        } else if (t.classList.contains('md-act-cb')) {
          if (d._protected === '1' || d._protected === 1) { return; }
          e.node.setDataValue('_sel', !!t.checked);
        }
        return;
      }
      if (d._row_state !== 'existing') { return; }      // 신규/draft 행은 드릴다운 대상 아님
      if (e.api.getEditingCells && e.api.getEditingCells().length > 0) { return; }  // 편집 중 양보
      if (d._linked === '1' || d._linked === 1) { return; }  // 이미 선택된 행 → 무변경
      e.api.forEachNode(function(node) {
        var nd = node.data || {};
        var want = (node === e.node) ? '1' : '';
        if (String(nd._linked || '') !== want) { node.setDataValue('_linked', want); }
      });
    }
    """
)


def render(user: dict) -> None:
    master_screen_head(
        "조직 관리",
        "그룹 → 부서 → 조(운영단위)를 가로 3단 시트로 관리합니다. 상위를 선택하면 하위가 열립니다.",
        breadcrumb="기준정보 › 조직 관리",
        mode_badge=_head_badges(),
    )
    st.markdown(_ORG_PAGE_CSS, unsafe_allow_html=True)

    readiness = _readiness()
    readiness.banner()  # NOT_READY/PROBE_ERROR 만 배너, READY 는 모드/스키마 배지로만.
    if readiness.state is Readiness.PROBE_ERROR:
        if st.button("스키마 재확인", key="org__recheck", icon=":material/refresh:"):
            db.reset_org_schema_cache()
            st.rerun()

    # 새로고침 의도는 렌더 시작에서 소비(재적재 판단). 나머지 액션은 그리드 렌더 뒤 소비.
    refresh_group = _GRP.take_action(REFRESH)
    refresh_dept = _OD.take_action(REFRESH)
    refresh_unit = _OU.take_action(REFRESH)

    with st.container(key="org__filter"):
        f1, f2, _sp = st.columns([1.4, 3.0, 5.6], vertical_alignment="bottom")
        active = f1.selectbox("사용 여부", _STATUS, key="og_active", label_visibility="collapsed")
        search = f2.text_input(
            "검색", key="og_search", placeholder="코드·명칭 검색", label_visibility="collapsed",
        )
    filt = {"active": active, "search": search.strip()}

    # 드릴다운 선택 상태 — 상단 selectbox 없이 표 안의 행 클릭으로만 정한다. 선택은 안정
    # 코드키(group_code/dept_code)로 session_state 에 보관하고, 저장된 행이 사라지면 해제한다.
    group_code, group_name = _resolve_group_selection()
    dept_code, dept_name = _resolve_dept_selection(group_code)
    drilldown_context([("그룹", group_name or None), ("부서", dept_name or None), ("조", None)])

    # 그룹 로드(필터 변경/새로고침/최초). dirty draft 는 폐기 확인 게이트를 탄다.
    g_params = dict(filt)
    if _GRP.resolve_reload(g_params, refresh=refresh_group, dirty=_GRP.is_dirty()) == RELOAD:
        st.session_state.pop(_GRP.delete_plan_key, None)
        _load_groups(g_params)

    # 부서 로드(선택 그룹 종속). 권위 컨텍스트 키는 persisted group_code.
    d_params = {**filt, "group": group_code}
    if group_code and _OD.resolve_reload(d_params, refresh=refresh_dept, dirty=_OD.is_dirty()) == RELOAD:
        st.session_state.pop(_OD.delete_plan_key, None)
        _load_depts(d_params)

    # 조 로드(선택 부서 종속). 권위 컨텍스트 키는 persisted dept_code.
    t_params = {**filt, "dept": dept_code}
    if dept_code and _OU.resolve_reload(t_params, refresh=refresh_unit, dirty=_OU.is_dirty()) == RELOAD:
        st.session_state.pop(_OU.delete_plan_key, None)
        _load_units(dept_code, filt)

    with st.container(key="org__sheets"):
        c_grp, c_dept, c_unit = st.columns(3, gap="medium")
        with c_grp:
            with st.container(key="org_group__sheet"):
                grp_grid = _render_group_sheet(g_params, readiness, group_code)
        with c_dept:
            with st.container(key="org_dept__sheet"):
                dept_grid = _render_dept_sheet(d_params, readiness, group_code, group_name, dept_code)
        with c_unit:
            with st.container(key="org_unit__sheet"):
                unit_grid = _render_unit_sheet(t_params, readiness, dept_code, dept_name)

    # 행 클릭 드릴다운 — 그룹/부서 표에서 클릭된(=_linked) 상위를 읽어 선택을 갱신한다.
    # 그룹 변경 시 부서·조 선택을 함께 초기화하고, 부서 변경 시 조(하위 표)가 재적재된다.
    # 클릭이 없거나 이미 선택된 행이면 picked == 현재 선택이라 재실행이 없다(무한 루프 없음).
    picked_group = _picked_code(grp_grid)
    if picked_group is not None and picked_group != group_code:
        st.session_state["og_group_sel"] = picked_group
        st.session_state.pop("og_dept_sel", None)  # 상위(그룹) 변경 → 부서·조 선택 초기화
        st.rerun()
    if dept_grid is not None:
        picked_dept = _picked_code(dept_grid)
        if picked_dept is not None and picked_dept != dept_code:
            st.session_state["og_dept_sel"] = picked_dept  # 부서 변경 → 조 표 재적재
            st.rerun()

    # 버튼 클릭 처리 (최신 grid 데이터 기준 — 시트 렌더 이후, page-scoped flag).
    if _GRP.take_action(ADD):
        _add_group_row(grp_grid)
    if _GRP.take_action(DELETE):
        _plan_group_delete(grp_grid)
    if _GRP.take_action(SAVE):
        _save_groups(grp_grid, g_params)
    # 상위 전환 중 폐기 게이트가 열려 있으면(자식 draft + 상위 선택 변경) 하위 write 를
    # 처리하지 않는다 — 아직 렌더된 옛 행이 새 상위에 오귀속되는 것을 원천 차단한다.
    # (게이트는 시트에서 discard/취소로만 해소되며, 그동안 add/삭제/저장 버튼도 비활성이다.)
    if group_code and dept_grid is not None and not _OD.has_pending_reload():
        if _OD.take_action(ADD):
            _add_dept_row(dept_grid, group_code)
        if _OD.take_action(DELETE):
            _plan_dept_delete(dept_grid, d_params)
        if _OD.take_action(SAVE):
            _save_depts(dept_grid, d_params, group_code)
    if dept_code and unit_grid is not None and not _OU.has_pending_reload():
        if _OU.take_action(ADD):
            _add_unit_row(unit_grid, dept_code)
        if _OU.take_action(DELETE):
            _plan_unit_delete(unit_grid, dept_code)
        if _OU.take_action(SAVE):
            _save_units(unit_grid, dept_code)

    changed = _sync_rows(_GRP, grp_grid, _GROUP_ROW_COLS)
    if dept_grid is not None:
        changed = _sync_rows(_OD, dept_grid, _DEPT_ROW_COLS) or changed
    if unit_grid is not None:
        changed = _sync_rows(_OU, unit_grid, _UNIT_ROW_COLS) or changed
    if changed:
        st.rerun()


# ---------- 헤더 배지 · readiness ----------
def _head_badges() -> str:
    """§5 모드 배지(데이터 연결) + §25 readiness 배지(스키마 준비) — 색·의미 분리."""
    readiness = _readiness()
    badges = ""
    if not readiness.write_enabled:
        badges += readiness.badge_html()
    badges += mode_badge_html(connected=True, sample=db.is_sample_mode())
    return badges


def _readiness() -> ReadinessState:
    """migration 004 적용 상태를 3-state(READY/NOT_READY/PROBE_ERROR)로 매핑한다."""
    state = db.org_schema_readiness()
    if state == db.READINESS_READY:
        return ReadinessState.ready()
    if state == db.READINESS_PROBE_ERROR:
        return ReadinessState.probe_error(_PROBE_ERROR_MSG)
    return ReadinessState.not_ready(_NOT_READY_MSG)


# ---------- 행 클릭 드릴다운 선택(안정 코드키, 저장된 행만) ----------
# 선택은 상단 컨트롤이 아니라 표 행 클릭으로 정하며, 안정 코드키로 아래 session_state
# 에 보관한다(행 인덱스·표시명 키 금지). 저장된 행이 사라지면(삭제·필터) 자동 해제한다.
_GROUP_SEL_KEY = "og_group_sel"
_DEPT_SEL_KEY = "og_dept_sel"


def _name_by_code(df: pd.DataFrame, code_col: str, name_col: str, code: str) -> str | None:
    """저장 프레임에서 코드로 표시명을 찾는다. 없으면 None(=선택 해제 신호)."""
    if df is None or df.empty:
        return None
    match = df[df[code_col].astype(str).str.strip() == str(code).strip()]
    if match.empty:
        return None
    return str(match.iloc[0][name_col])


def _resolve_group_selection() -> tuple[str, str]:
    """행 클릭으로 정한 그룹 선택을 저장된 그룹과 대조해 (코드, 이름)으로 확정한다.

    선택된 그룹이 더 이상 존재하지 않으면(삭제 등) 선택과 하위(부서) 선택을 함께 비운다.
    """
    code = str(st.session_state.get(_GROUP_SEL_KEY, "") or "").strip()
    if not code:
        return "", ""
    name = _name_by_code(db.get_org_groups(), "group_code", "group_name", code)
    if name is None:
        st.session_state.pop(_GROUP_SEL_KEY, None)
        st.session_state.pop(_DEPT_SEL_KEY, None)
        return "", ""
    return code, name


def _resolve_dept_selection(group_code: str) -> tuple[str, str]:
    """선택 그룹에 종속된 부서 선택을 확정한다. 그룹 미선택이면 부서 선택을 비운다.

    선택된 부서가 현재 그룹의 부서가 아니면(그룹 변경·삭제) 부서 선택을 해제한다.
    """
    if not group_code:
        st.session_state.pop(_DEPT_SEL_KEY, None)
        return "", ""
    code = str(st.session_state.get(_DEPT_SEL_KEY, "") or "").strip()
    if not code:
        return "", ""
    name = _name_by_code(db.get_org_departments(group_code=group_code), "dept_code", "dept_name", code)
    if name is None:
        st.session_state.pop(_DEPT_SEL_KEY, None)
        return "", ""
    return code, name


def _picked_code(grid_df: pd.DataFrame) -> str | None:
    """그룹/부서 그리드 반환에서 클릭으로 열린(=_linked) 저장 행의 코드를 읽는다.

    행 클릭 시 _DRILL_CLICK 이 클릭 노드에만 _linked='1' 을 쓰고 나머지를 지운다. 여기서
    그 안정 코드키(코드 컬럼)를 돌려준다 — 클릭·선택이 없으면 None. 클릭이 없을 때는
    Python 이 현재 선택 행에 계산한 _linked 와 동일하므로 controller 에서 무변경으로 판정된다.
    """
    if grid_df is None or "_linked" not in grid_df.columns or "코드" not in grid_df.columns:
        return None
    linked = grid_df[
        (grid_df["_row_state"].astype(str) == "existing")
        & (grid_df["_linked"].astype(str).str.strip() == "1")
    ]
    if linked.empty:
        return None
    return str(linked.iloc[0]["코드"]).strip()


# ---------- 공통 시트 헬퍼 ----------
def _flag(cond) -> str:
    return "1" if bool(cond) else ""


def _plan_codes(plan) -> set:
    """그룹·부서 삭제 계획의 대상 코드(삭제+미사용) — _delete 시각용."""
    if not plan:
        return set()
    codes = set(plan.get("delete", []))
    codes |= {item["code"] for item in plan.get("deactivate", []) if "code" in item}
    return codes


# 저장된 코드(=신규 아님)는 수정 불가 — 공통 .ms-cell-readonly(Wave A) 로 읽기전용
# 어포던스(중립 틴트 + 기본 커서)를 준다. 상태 행 배경(!important)이 우선하므로 선택/신규/
# 삭제/오류 시각과 충돌하지 않는다(색만으로 상태 표시 금지 계약 유지).
_CODE_READONLY_RULES = {"ms-cell-readonly": "data._row_state !== 'new'"}


def _code_name_config() -> dict:
    """그룹·부서 시트 공통 컬럼 설정(코드=신규만·코드명·순서/비고/사용).

    최소 열폭 합(≈254px)을 낮춰 3시트가 1366·1280px 데스크톱(사이드바 제외)에서
    가로스크롤·열잘림 없이 맞도록 한다. 넓은 폭에서는 flex(코드명·비고)로 채운다.
    """
    return {
        "코드": {"flex": 0, "width": 54, "minWidth": 44, "cellClass": "md-c-left",
                "editable": _EDIT_NEW_ONLY, "cellClassRules": dict(_CODE_READONLY_RULES)},
        "코드명": {"flex": 1.4, "minWidth": 44, "cellClass": "md-c-left", "editable": _EDIT_UNLESS_PROTECTED},
        "순서": {"flex": 0, "width": 40, "minWidth": 34, "maxWidth": 72,
                "cellClass": "md-c-center ms-num", "editable": _EDIT_UNLESS_PROTECTED},
        "비고": {"flex": 1.1, "minWidth": 38, "cellClass": "md-c-left", "editable": _EDIT_UNLESS_PROTECTED},
        "사용": {"flex": 0, "width": 42, "minWidth": 36, "maxWidth": 64,
                "cellClass": "md-c-center", "editable": _EDIT_UNLESS_PROTECTED},
    }


# 조 시트는 유형 컬럼이 하나 더 있어 6열이다 — 최소 열폭을 더 조여 1280px에서도 맞춘다.
_UNIT_COL_CONFIG = {
    "코드": {"flex": 0, "width": 46, "minWidth": 40, "cellClass": "md-c-left",
            "editable": _EDIT_NEW_ONLY, "cellClassRules": dict(_CODE_READONLY_RULES)},
    "명칭": {"headerName": "코드명", "flex": 1.4, "minWidth": 42, "cellClass": "md-c-left",
           "editable": _EDIT_UNLESS_PROTECTED},
    "유형": {
        "headerName": "유형", "flex": 0, "width": 50, "minWidth": 44, "maxWidth": 96,
        "cellClass": "md-c-center", "cellEditor": "agSelectCellEditor",
        "cellEditorParams": {"values": ["교대", "일반"]},
        "cellClassRules": {"ms-unit-shift": "value == '교대'", "ms-unit-general": "value == '일반'"},
    },
    "표시순서": {"headerName": "순서", "flex": 0, "width": 40, "minWidth": 34, "maxWidth": 72,
             "cellClass": "md-c-center ms-num", "editable": _EDIT_UNLESS_PROTECTED},
    "비고": {"flex": 1.1, "minWidth": 34, "cellClass": "md-c-left", "editable": _EDIT_UNLESS_PROTECTED},
    "사용": {"flex": 0, "width": 40, "minWidth": 36, "maxWidth": 64, "cellClass": "md-c-center",
           "editable": _EDIT_UNLESS_PROTECTED},
}


def _write_reason(readiness: ReadinessState) -> str | None:
    return readiness.message if not readiness.write_enabled else None


def _locked_action_bar(state: DraftState, readiness: ReadinessState) -> None:
    """상위 미선택 잠금 시트의 액션바 — 모든 write 비활성(버튼 키는 유지)."""
    reason = _write_reason(readiness) or "상위 항목을 먼저 선택하세요."
    master_action_bar(state, sel_count=0, dirty_total=0, can_write=False, write_disabled_reason=reason)


def _summary_chips(rows: pd.DataFrame, params: dict) -> None:
    """표 위 요약 스트립 — 좌: 활성 필터 칩(사용 여부·검색), 우: 결과 사용/미사용 분포.

    사용자 관리(_render_summary_chips)와 동일하게 **현재 스코프/필터 결과** 기준으로 센다
    (전체수 아님). 모든 필터가 기본이고 결과도 없으면 비운다.
    """
    existing = rows[rows["_row_state"].astype(str) == "existing"] if rows is not None and not rows.empty \
        else pd.DataFrame(columns=["사용"])
    left = ""
    if params.get("active") and params["active"] != "전체":
        left += chip_html(f"사용 여부: {params['active']}", "lock")
    if params.get("search"):
        left += chip_html(f"검색: {params['search']}", "lock")
    right = ""
    if not existing.empty:
        on = int(existing["사용"].map(grid_bool).sum())
        off = len(existing) - on
        right = chip_html(f"사용 {on}", "ok")
        if off:
            right += chip_html(f"미사용 {off}", "mute")
    if not left and not right:
        return
    st.markdown(
        "<div style='display:flex;justify-content:space-between;align-items:center;"
        "gap:.5rem;margin:.1rem 0 .2rem'>"
        f"<div style='display:flex;gap:.3rem;flex-wrap:wrap'>{left}</div>"
        f"<div style='display:flex;gap:.3rem;flex:0 0 auto'>{right}</div></div>",
        unsafe_allow_html=True,
    )


# ---------- 그룹 시트 ----------
def build_group_rows(df: pd.DataFrame) -> pd.DataFrame:
    """organization_groups 프레임 → 그룹 시트 편집 행. 정렬: 순서 → 코드."""
    if df is None or df.empty:
        return pd.DataFrame(columns=_GROUP_ROW_COLS)
    frame = df.copy()
    frame["_o"] = pd.to_numeric(frame["sort_order"], errors="coerce").fillna(0).astype("int64")
    frame = frame.sort_values(["_o", "group_code"]).reset_index(drop=True)
    rows = pd.DataFrame({
        "_row_id": "e:" + frame["group_code"].astype(str),
        "_row_state": "existing", "_sel": False,
        "코드": frame["group_code"].fillna("").astype("string"),
        "코드명": frame["group_name"].fillna("").astype("string"),
        "순서": frame["_o"].astype(str).astype("string"),
        "비고": frame.get("description", "").fillna("").astype("string") if "description" in frame else "",
        "사용": frame["is_active"].fillna(True).astype(bool),
    })
    return rows[_GROUP_ROW_COLS].reset_index(drop=True)


def _load_groups(q: dict) -> None:
    df = db.get_org_groups()
    df = _apply_filter(df, q, "group_code", "group_name")
    rows = build_group_rows(df)
    _GRP.set_rows(rows)
    _set_baseline(_GRP, rows, _GROUP_COLS)
    _GRP.bump_nonce()
    _GRP.set_dirty(False)


def _group_display(rows: pd.DataFrame, sel_group: str) -> pd.DataFrame:
    frame = rows.copy() if rows is not None else pd.DataFrame(columns=_GROUP_ROW_COLS)
    if frame.empty:
        return frame
    codes = frame["코드"].astype(str).str.strip()
    is_existing = frame["_row_state"].astype(str) == "existing"
    frame["_inactive"] = ((is_existing) & (~frame["사용"].map(grid_bool))).map(_flag)
    frame["_protected"] = (is_existing & codes.str.upper().isin(_SYSTEM_CODES)).map(_flag)
    frame["_linked"] = (codes == str(sel_group).strip()).map(_flag)
    frame["_delete"] = codes.isin(_plan_codes(st.session_state.get(_GRP.delete_plan_key))).map(_flag)
    return frame


def _render_group_sheet(params: dict, readiness: ReadinessState, sel_group: str) -> pd.DataFrame:
    show_flash(_GRP)
    if _GRP.has_pending_reload():
        gate = discard_confirm_bar(_GRP)
        if gate == "discard":
            p = _GRP.apply_pending_reload()
            st.session_state.pop(_GRP.delete_plan_key, None)
            _load_groups(p if p is not None else params)
            st.rerun()
        elif gate == "cancel":
            _GRP.cancel_pending_reload()
            st.rerun()

    plan = st.session_state.get(_GRP.delete_plan_key)
    rows = _GRP.get_rows()
    sheet_head("그룹", count=_existing_count(rows))
    if plan:
        _group_confirm_bar(plan, params, readiness)

    _summary_chips(rows, params)           # 표 위 요약(현재 필터 결과 기준)
    bar_slot = st.container()              # 액션바(표 위) — 건수 계산 후 채운다

    spec = MasterGridSpec(
        page_id=_GRP.page_id, columns=_GROUP_GRID_COLUMNS, order=_GROUP_COLS,
        col_config=_code_name_config(), select_all=True, include_linked_rows=True,
        grid_options={"onCellClicked": _DRILL_CLICK},  # 행 클릭 → 그룹 드릴다운 선택
        height=master_grid_height(len(rows) if rows is not None else 0),
    )
    grid_df = render_master_grid(spec, _group_display(rows, sel_group), key=_GRP.grid_key())

    live = live_rows(grid_df)
    existing = live[live["_row_state"] == "existing"]
    sel_count = int((existing["_sel"].map(grid_bool)).sum()) if not existing.empty else 0
    new_cnt, changed_cnt = _dirty_counts(_GRP, live, _GROUP_COLS)
    total = dirty_total(new_cnt, changed_cnt)
    _GRP.set_dirty(total > 0)
    with bar_slot:
        master_action_bar(
            _GRP, sel_count=sel_count, dirty_total=total,
            can_write=readiness.write_enabled, write_disabled_reason=_write_reason(readiness),
        )
    count_strip(len(existing), new_cnt, changed_cnt, sel_count)
    return grid_df


def _add_group_row(grid_df: pd.DataFrame) -> None:
    live = live_rows(grid_df)
    row = {
        "_row_id": _GRP.next_rid(), "_row_state": "new", "_sel": False,
        "코드": "", "코드명": "", "순서": str(_next_order(live)), "비고": "", "사용": True,
    }
    _GRP.set_rows(pd.concat([live[_GROUP_ROW_COLS], pd.DataFrame([row])], ignore_index=True)[_GROUP_ROW_COLS])
    _GRP.bump_nonce()
    st.rerun()


def _validate_groups(live: pd.DataFrame):
    """그룹 시트 → organization_groups 레코드 + 행 검증. 완전히 빈 신규 행은 제외."""
    records, errors = [], []
    for i, (_, row) in enumerate(live.iterrows(), start=1):
        code = str(row.get("코드") or "").strip()
        name = str(row.get("코드명") or "").strip()
        order_raw = str(row.get("순서") or "").strip()
        if not any([code, name]):
            continue
        tag = f"{i}행" + (f"({code})" if code else "")
        if not code:
            errors.append(f"{i}행: 그룹코드를 입력하세요.")
        if not name:
            errors.append(f"{tag}: 그룹명을 입력하세요.")
        order_val = 0
        if order_raw:
            try:
                order_val = int(order_raw)
            except ValueError:
                errors.append(f"{tag}: 순서는 숫자여야 합니다.")
        records.append({
            "group_code": code, "group_name": name, "sort_order": order_val,
            "description": str(row.get("비고") or "").strip(), "is_active": grid_bool(row.get("사용")),
        })
    return records, errors


def _save_groups(grid_df: pd.DataFrame, q: dict) -> None:
    readiness = _readiness()
    if not readiness.write_enabled:
        banner("danger" if readiness.state is Readiness.PROBE_ERROR else "warn", readiness.message)
        return
    live = live_rows(grid_df)
    store = db.get_org_groups()
    counts: dict[str, int] = {}

    def _validate():
        return _validate_groups(live)

    def _build(records):
        merged, dup, n_c, n_u, _n_d = db.upsert_records(
            store, records, set(), ["group_code"], "is_active", db.ORG_GROUP_COLUMNS,
        )
        counts["create"], counts["update"] = n_c, n_u
        errs = []
        if dup:
            errs.append("그룹코드가 중복되었습니다: " + ", ".join(k[0] for k in dup))
        return merged, errs

    def _persist(merged, records):
        keys = [r["group_code"] for r in records if r.get("group_code")]
        try:
            report = db.save_org_groups_report(merged)
        except db.DATA_SOURCE_ERRORS as exc:
            return PersistResult.failure(_GRP.page_id, keys, str(exc))
        return PersistResult(page_id=_GRP.page_id, **report.to_persist_kwargs())

    outcome = run_save(_GRP, validate=_validate, build_candidate=_build, persist=_persist)
    if outcome.status in ("invalid", "failed"):
        _error_banner("그룹을 저장하지 못했습니다.", outcome.errors)
        return
    if outcome.status in ("partial", "unknown"):
        ledger_banner(outcome.result)
        return
    _load_groups(q)
    _GRP.set_flash("success", f"그룹을 저장했습니다. (신규 {counts.get('create', 0)} · 수정 {counts.get('update', 0)})")
    st.rerun()


def _plan_group_delete(grid_df: pd.DataFrame) -> None:
    readiness = _readiness()
    if not readiness.write_enabled:
        _GRP.set_flash("error" if readiness.state is Readiness.PROBE_ERROR else "warning", readiness.message)
        st.rerun()
    live = live_rows(grid_df)
    sel = live[(live["_row_state"] == "existing") & live["_sel"].map(grid_bool)]
    codes = sorted({str(c).strip() for c in sel["코드"] if str(c).strip()})
    if not codes:
        _GRP.set_flash("warning", "삭제할 기존 그룹을 선택하세요.")
        st.rerun()
    plan = {"delete": [], "deactivate": [], "block": []}
    for code in codes:
        if code.upper() in _SYSTEM_CODES:
            plan["block"].append(code)
            continue
        refs = db.org_group_reference_counts(code)
        if sum(refs.values()) > 0:
            plan["deactivate"].append({"code": code, "refs": refs})
        else:
            plan["delete"].append(code)
    st.session_state[_GRP.delete_plan_key] = plan
    st.rerun()


def _group_confirm_bar(plan: dict, params: dict, readiness: ReadinessState) -> None:
    lines = []
    if plan["delete"]:
        lines.append("삭제 가능: " + ", ".join(plan["delete"]))
    for item in plan["deactivate"]:
        lines.append(f"미사용 처리: {item['code']} — 소속 부서 {item['refs'].get('departments', 0)}개")
    for code in plan["block"]:
        lines.append(f"처리 불가: {code} — 시스템 필수 그룹 (ADMIN 보호)")
    actionable = bool(plan["delete"] or plan["deactivate"]) and readiness.write_enabled
    result = confirm_bar(
        _GRP, title="선택한 그룹을 참조 확인 후 미사용/삭제 처리합니다 (ADMIN 보호).",
        lines=lines, confirm_label="삭제 실행", confirm_enabled=actionable, scope="del",
    )
    if result == "confirm":
        _execute_group_delete(plan, params)
    elif result == "cancel":
        st.session_state.pop(_GRP.delete_plan_key, None)
        st.rerun()


def _execute_group_delete(plan: dict, params: dict) -> None:
    n_del = n_deact = 0
    failed: list[str] = []
    for code in plan["delete"]:
        try:
            db.delete_org_group(code)
            n_del += 1
        except db.DATA_SOURCE_ERRORS:
            failed.append(code)
    for item in plan["deactivate"]:
        try:
            db.deactivate_org_group(item["code"])
            n_deact += 1
        except db.DATA_SOURCE_ERRORS:
            failed.append(item["code"])
    st.session_state.pop(_GRP.delete_plan_key, None)
    _load_groups(params)
    _finish_delete(_GRP, "그룹", n_del, n_deact, plan.get("block"), failed)


# ---------- 부서 시트 ----------
def build_dept_rows(df: pd.DataFrame) -> pd.DataFrame:
    """departments 프레임 → 부서 시트 편집 행. 정렬: 순서 → 코드."""
    if df is None or df.empty:
        return pd.DataFrame(columns=_DEPT_ROW_COLS)
    frame = df.copy()
    frame["_o"] = pd.to_numeric(frame["sort_order"], errors="coerce").fillna(0).astype("int64")
    frame = frame.sort_values(["_o", "dept_code"]).reset_index(drop=True)
    rows = pd.DataFrame({
        "_row_id": "e:" + frame["dept_code"].astype(str),
        "_row_state": "existing", "_sel": False,
        "코드": frame["dept_code"].fillna("").astype("string"),
        "코드명": frame["dept_name"].fillna("").astype("string"),
        "순서": frame["_o"].astype(str).astype("string"),
        "비고": frame.get("description", "").fillna("").astype("string") if "description" in frame else "",
        "사용": frame["is_active"].fillna(True).astype(bool),
    })
    return rows[_DEPT_ROW_COLS].reset_index(drop=True)


def _load_depts(q: dict) -> None:
    df = db.get_org_departments(group_code=q.get("group"))
    df = _apply_filter(df, q, "dept_code", "dept_name")
    rows = build_dept_rows(df)
    _OD.set_rows(rows)
    _set_baseline(_OD, rows, _DEPT_COLS)
    # 적재 시점의 귀속 그룹을 안정 상위키로 기록한다 — 저장은 현재 selectbox 값이 아니라
    # 이 값으로 행을 귀속시켜, 상위 전환 중 옛 행이 새 그룹에 오귀속되는 것을 막는다.
    st.session_state[_OD.key("loaded_group")] = str(q.get("group") or "")
    _OD.bump_nonce()
    _OD.set_dirty(False)


def _dept_display(rows: pd.DataFrame, sel_dept: str) -> pd.DataFrame:
    frame = rows.copy() if rows is not None else pd.DataFrame(columns=_DEPT_ROW_COLS)
    if frame.empty:
        return frame
    codes = frame["코드"].astype(str).str.strip()
    is_existing = frame["_row_state"].astype(str) == "existing"
    frame["_inactive"] = ((is_existing) & (~frame["사용"].map(grid_bool))).map(_flag)
    frame["_protected"] = (is_existing & codes.str.upper().isin(_SYSTEM_CODES)).map(_flag)
    frame["_linked"] = (codes == str(sel_dept).strip()).map(_flag)
    frame["_delete"] = codes.isin(_plan_codes(st.session_state.get(_OD.delete_plan_key))).map(_flag)
    return frame


def _render_dept_sheet(params: dict, readiness: ReadinessState, group_code: str,
                       group_name: str, sel_dept: str):
    show_flash(_OD)
    if not group_code:
        sheet_head("부서", locked=True)
        sheet_locked("그룹을 먼저 선택하세요", "그룹을 선택하면 해당 그룹의 부서만 조회·등록됩니다.")
        _locked_action_bar(_OD, readiness)
        return None

    # 상위(그룹) 전환 중 미저장 draft 폐기 게이트. 해소 전까지 pending 이 유지되며,
    # 그동안 이 시트의 write(행추가·삭제·저장)를 비활성해 옛 행 오귀속을 차단한다(§17).
    pending = _OD.has_pending_reload()
    if pending:
        gate = discard_confirm_bar(_OD)
        if gate == "discard":
            _OD.apply_pending_reload()
            st.session_state.pop(_OD.delete_plan_key, None)
            _load_depts(params)
            st.rerun()
        elif gate == "cancel":
            _OD.cancel_pending_reload()
            st.rerun()

    plan = st.session_state.get(_OD.delete_plan_key)
    rows = _OD.get_rows()
    sheet_head("부서", count=_existing_count(rows), context=group_name)
    if plan:
        _dept_confirm_bar(plan, params, readiness)

    _summary_chips(rows, params)           # 표 위 요약(현재 필터 결과 기준)
    bar_slot = st.container()              # 액션바(표 위) — 건수 계산 후 채운다

    spec = MasterGridSpec(
        page_id=_OD.page_id, columns=_DEPT_GRID_COLUMNS, order=_DEPT_COLS,
        col_config=_code_name_config(), select_all=True, include_linked_rows=True,
        grid_options={"onCellClicked": _DRILL_CLICK},  # 행 클릭 → 부서 드릴다운 선택
        height=master_grid_height(len(rows) if rows is not None else 0),
    )
    grid_df = render_master_grid(spec, _dept_display(rows, sel_dept), key=_OD.grid_key(suffix=group_code))

    live = live_rows(grid_df)
    existing = live[live["_row_state"] == "existing"]
    sel_count = int((existing["_sel"].map(grid_bool)).sum()) if not existing.empty else 0
    new_cnt, changed_cnt = _dirty_counts(_OD, live, _DEPT_COLS)
    total = dirty_total(new_cnt, changed_cnt)
    _OD.set_dirty(total > 0)
    can_write = readiness.write_enabled and not pending
    reason = _write_reason(readiness) or ("위의 미저장 변경 안내를 먼저 처리하세요." if pending else None)
    with bar_slot:
        master_action_bar(
            _OD, sel_count=sel_count, dirty_total=total,
            can_write=can_write, write_disabled_reason=reason,
        )
    count_strip(len(existing), new_cnt, changed_cnt, sel_count)
    return grid_df


def _add_dept_row(grid_df: pd.DataFrame, group_code: str) -> None:
    live = live_rows(grid_df)
    row = {
        "_row_id": _OD.next_rid(), "_row_state": "new", "_sel": False,
        "코드": "", "코드명": "", "순서": str(_next_order(live)), "비고": "", "사용": True,
    }
    _OD.set_rows(pd.concat([live[_DEPT_ROW_COLS], pd.DataFrame([row])], ignore_index=True)[_DEPT_ROW_COLS])
    _OD.bump_nonce()
    st.rerun()


def _validate_depts(live: pd.DataFrame, group_code: str):
    """부서 시트 → departments 레코드 + 행 검증. 신규·기존 모두 선택 그룹에 귀속."""
    records, errors = [], []
    gcode = str(group_code).strip()
    for i, (_, row) in enumerate(live.iterrows(), start=1):
        code = str(row.get("코드") or "").strip()
        name = str(row.get("코드명") or "").strip()
        order_raw = str(row.get("순서") or "").strip()
        if not any([code, name]):
            continue
        tag = f"{i}행" + (f"({code})" if code else "")
        if not code:
            errors.append(f"{i}행: 부서코드를 입력하세요.")
        if not name:
            errors.append(f"{tag}: 부서명을 입력하세요.")
        order_val = 0
        if order_raw:
            try:
                order_val = int(order_raw)
            except ValueError:
                errors.append(f"{tag}: 순서는 숫자여야 합니다.")
        records.append({
            "dept_code": code, "dept_name": name, "group_code": gcode,
            "description": str(row.get("비고") or "").strip(), "sort_order": order_val,
            "is_active": grid_bool(row.get("사용")),
        })
    return records, errors


def _save_depts(grid_df: pd.DataFrame, q: dict, group_code: str) -> None:
    readiness = _readiness()
    if not readiness.write_enabled:
        banner("danger" if readiness.state is Readiness.PROBE_ERROR else "warn", readiness.message)
        return
    live = live_rows(grid_df)
    store = db.get_org_departments()
    counts: dict[str, int] = {}
    # 귀속 그룹은 현재 selectbox 값(group_code)이 아니라 이 행들이 적재된 시점의 그룹으로
    # 바인딩한다. 상위 전환 중이라도(게이트가 처리 전) 옛 행이 새 그룹에 오귀속되지 않는다.
    owner = str(st.session_state.get(_OD.key("loaded_group"), group_code) or group_code)

    def _validate():
        return _validate_depts(live, owner)

    def _build(records):
        merged, dup, n_c, n_u, _n_d = db.upsert_records(
            store, records, set(), ["dept_code"], "is_active", db.ORG_DEPT_COLUMNS,
        )
        counts["create"], counts["update"] = n_c, n_u
        errs = []
        if dup:
            errs.append("부서코드가 중복되었습니다: " + ", ".join(k[0] for k in dup))
        return merged, errs

    def _persist(merged, records):
        keys = [r["dept_code"] for r in records if r.get("dept_code")]
        try:
            report = db.save_org_departments_report(merged)
        except db.DATA_SOURCE_ERRORS as exc:
            return PersistResult.failure(_OD.page_id, keys, str(exc))
        return PersistResult(page_id=_OD.page_id, **report.to_persist_kwargs())

    outcome = run_save(_OD, validate=_validate, build_candidate=_build, persist=_persist)
    if outcome.status in ("invalid", "failed"):
        _error_banner("부서를 저장하지 못했습니다.", outcome.errors)
        return
    if outcome.status in ("partial", "unknown"):
        ledger_banner(outcome.result)
        return
    _load_depts({**q, "group": owner})  # 방금 저장한(귀속) 그룹으로 재적재
    st.session_state.pop(_OU.query_key, None)  # 부서명 변경을 조 컨텍스트에 반영
    _OD.set_flash("success", f"부서를 저장했습니다. (신규 {counts.get('create', 0)} · 수정 {counts.get('update', 0)})")
    st.rerun()


def _ref_text(refs: dict) -> str:
    parts = []
    if refs.get("users"):
        parts.append(f"사용자 {refs['users']}명")
    if refs.get("teams"):
        parts.append(f"조 {refs['teams']}개")
    if refs.get("shift_groups"):
        parts.append(f"편성 {refs['shift_groups']}건")
    return ", ".join(parts) or "참조 있음"


def _plan_dept_delete(grid_df: pd.DataFrame, params: dict) -> None:
    readiness = _readiness()
    if not readiness.write_enabled:
        _OD.set_flash("error" if readiness.state is Readiness.PROBE_ERROR else "warning", readiness.message)
        st.rerun()
    live = live_rows(grid_df)
    sel = live[(live["_row_state"] == "existing") & live["_sel"].map(grid_bool)]
    codes = sorted({str(c).strip() for c in sel["코드"] if str(c).strip()})
    if not codes:
        _OD.set_flash("warning", "삭제할 기존 부서를 선택하세요.")
        st.rerun()
    plan = {"delete": [], "deactivate": [], "block": []}
    for code in codes:
        if code.upper() in _SYSTEM_CODES:
            plan["block"].append(code)
            continue
        refs = db.department_reference_counts(code)
        if sum(refs.values()) > 0:
            plan["deactivate"].append({"code": code, "refs": refs})
        else:
            plan["delete"].append(code)
    st.session_state[_OD.delete_plan_key] = plan
    st.rerun()


def _dept_confirm_bar(plan: dict, params: dict, readiness: ReadinessState) -> None:
    lines = []
    if plan["delete"]:
        lines.append("삭제 가능: " + ", ".join(plan["delete"]))
    for item in plan["deactivate"]:
        lines.append(f"미사용 처리: {item['code']} — {_ref_text(item['refs'])} 참조 중")
    for code in plan["block"]:
        lines.append(f"처리 불가: {code} — 시스템 필수 부서 (ADMIN 보호)")
    actionable = bool(plan["delete"] or plan["deactivate"]) and readiness.write_enabled
    result = confirm_bar(
        _OD, title="선택한 부서를 참조 확인 후 미사용/삭제 처리합니다 (ADMIN 보호).",
        lines=lines, confirm_label="삭제 실행", confirm_enabled=actionable, scope="del",
    )
    if result == "confirm":
        _execute_dept_delete(plan, params)
    elif result == "cancel":
        st.session_state.pop(_OD.delete_plan_key, None)
        st.rerun()


def _execute_dept_delete(plan: dict, params: dict) -> None:
    n_del = 0
    failed: list[str] = []
    for code in plan["delete"]:
        try:
            db.delete_department(code)
            n_del += 1
        except db.DATA_SOURCE_ERRORS:
            failed.append(code)
    deactivate_codes = [item["code"] for item in plan["deactivate"]]
    n_deact = 0
    if deactivate_codes:
        try:
            store = db.get_org_departments().copy()
            mask = store["dept_code"].astype(str).isin(deactivate_codes)
            n_deact = int(mask.sum())
            store.loc[mask, "is_active"] = False
            db.save_org_departments(store[db.ORG_DEPT_COLUMNS])
        except db.DATA_SOURCE_ERRORS:
            n_deact = 0
            failed.extend(deactivate_codes)
    st.session_state.pop(_OD.delete_plan_key, None)
    _load_depts(params)
    st.session_state.pop(_OU.query_key, None)
    _finish_delete(_OD, "부서", n_del, n_deact, plan.get("block"), failed)


# ---------- 조(운영단위) 시트 ----------
def build_team_rows(df: pd.DataFrame) -> pd.DataFrame:
    """teams 프레임 → 조 시트 편집 행(유형 포함). 정렬: 순서 → 코드."""
    if df is None or df.empty:
        return pd.DataFrame(columns=_UNIT_ROW_COLS)
    frame = df.sort_values(["sort_order", "team_code"]).reset_index(drop=True)
    order = pd.to_numeric(frame["sort_order"], errors="coerce").fillna(0).astype("int64")
    rows = pd.DataFrame({
        "_row_id": "e:" + frame["dept_code"].astype(str) + "|" + frame["team_code"].astype(str),
        "_row_state": "existing", "_sel": False,
        "코드": frame["team_code"].fillna("").astype("string"),
        "명칭": frame["team_name"].fillna("").astype("string"),
        "유형": frame["unit_type"].map(db.UNIT_TYPE_LABELS).fillna("교대").astype("string"),
        "표시순서": order.astype(str).astype("string"),
        "비고": frame.get("description", "").fillna("").astype("string") if "description" in frame else "",
        "사용": frame["is_active"].fillna(True).astype(bool),
    })
    return rows[_UNIT_ROW_COLS].reset_index(drop=True)


def _load_units(dept_code: str, q: dict | None = None) -> None:
    df = db.get_org_teams(dept_code)
    if q:
        df = _apply_filter(df, q, "team_code", "team_name")
    rows = build_team_rows(df)
    _OU.set_rows(rows)
    _set_baseline(_OU, rows, _UNIT_COLS)
    st.session_state[_OU.key("loaded_dept")] = str(dept_code)
    _OU.bump_nonce()
    _OU.set_dirty(False)


def _unit_display(rows: pd.DataFrame) -> pd.DataFrame:
    frame = rows.copy() if rows is not None else pd.DataFrame(columns=_UNIT_ROW_COLS)
    if frame.empty:
        return frame
    frame["_inactive"] = (~frame["사용"].map(grid_bool)).map(_flag)
    plan = st.session_state.get(_OU.delete_plan_key)
    del_codes = set()
    if plan:
        for bucket in ("delete", "deactivate"):
            del_codes |= {it["team_code"] for it in plan.get(bucket, []) if "team_code" in it}
    frame["_delete"] = frame["코드"].astype(str).str.strip().isin(del_codes).map(_flag)
    return frame


def _render_unit_sheet(params: dict, readiness: ReadinessState, dept_code: str, dept_name: str):
    show_flash(_OU)
    if not dept_code:
        sheet_head("조", locked=True)
        sheet_locked("부서를 먼저 선택하세요", "부서를 선택하면 해당 부서의 조(운영단위)만 조회·등록됩니다.")
        _locked_action_bar(_OU, readiness)
        return None

    # 상위(부서) 전환 중 미저장 draft 폐기 게이트. 해소 전까지 이 시트의 write 를 비활성해
    # 옛 조 행이 새 부서 밑으로 오귀속·중복 생성되는 것을 차단한다(§17).
    pending = _OU.has_pending_reload()
    if pending:
        gate = discard_confirm_bar(_OU)
        if gate == "discard":
            _OU.apply_pending_reload()
            st.session_state.pop(_OU.delete_plan_key, None)
            _load_units(dept_code, params)
            st.rerun()
        elif gate == "cancel":
            _OU.cancel_pending_reload()
            st.rerun()

    plan = st.session_state.get(_OU.delete_plan_key)
    rows = _OU.get_rows()
    sheet_head("조", count=_existing_count(rows), context=dept_name)
    if plan:
        _unit_confirm_bar(plan, dept_code, readiness)

    _summary_chips(rows, params)           # 표 위 요약(현재 필터 결과 기준)
    bar_slot = st.container()              # 액션바(표 위) — 건수 계산 후 채운다

    spec = MasterGridSpec(
        page_id=_OU.page_id, columns=_UNIT_GRID_COLUMNS, order=_UNIT_COLS,
        col_config=_UNIT_COL_CONFIG, select_all=True,
        height=master_grid_height(len(rows) if rows is not None else 0),
    )
    grid_df = render_master_grid(spec, _unit_display(rows), key=_OU.grid_key(suffix=dept_code))

    if rows is not None and rows.empty:
        empty_state("등록된 조가 없습니다.", "‘행 추가’로 이 부서의 교대조·일반근무를 등록하세요.")

    live = live_rows(grid_df)
    existing = live[live["_row_state"] == "existing"]
    sel_count = int((existing["_sel"].map(grid_bool)).sum()) if not existing.empty else 0
    new_cnt, changed_cnt = _dirty_counts(_OU, live, _UNIT_COLS)
    total = dirty_total(new_cnt, changed_cnt)
    _OU.set_dirty(total > 0)
    can_write = readiness.write_enabled and not pending
    reason = _write_reason(readiness) or ("위의 미저장 변경 안내를 먼저 처리하세요." if pending else None)
    with bar_slot:
        master_action_bar(
            _OU, sel_count=sel_count, dirty_total=total,
            can_write=can_write, write_disabled_reason=reason,
        )
    count_strip(len(existing), new_cnt, changed_cnt, sel_count)
    return grid_df


def _add_unit_row(grid_df: pd.DataFrame, dept_code: str) -> None:
    if grid_df is None or not dept_code:
        _OU.set_flash("warning", "조를 추가할 부서를 먼저 선택하세요.")
        st.rerun()
    readiness = _readiness()
    if not readiness.write_enabled:
        _OU.set_flash("error" if readiness.state is Readiness.PROBE_ERROR else "warning", readiness.message)
        st.rerun()
    live = live_rows(grid_df)
    row = {
        "_row_id": _OU.next_rid(), "_row_state": "new", "_sel": False,
        "코드": "", "명칭": "", "유형": "교대", "표시순서": str(_next_order(live, col="표시순서")),
        "비고": "", "사용": True,
    }
    _OU.set_rows(pd.concat([live[_UNIT_ROW_COLS], pd.DataFrame([row])], ignore_index=True)[_UNIT_ROW_COLS])
    _OU.bump_nonce()
    st.rerun()


def _validate_units(live: pd.DataFrame, dept_code: str):
    """조 시트 표시 형태 → teams 저장 형태 변환 + 행별 검증. 완전히 빈 신규 행은 제외.

    교차 화면 회귀 테스트(test_master_and_views/test_master_forms)가 참조하는 시그니처라
    field 키(명칭/표시순서)와 반환 계약(dept_code·unit_type SHIFT/GENERAL·빈 행 제외)을
    보존한다. 비고는 있으면 반영하고 없으면 빈 값으로 채운다(추가형, 후방호환).
    """
    records, errors = [], []
    for i, (_, row) in enumerate(live.iterrows(), start=1):
        code = str(row.get("코드") or "").strip()
        name = str(row.get("명칭") or "").strip()
        type_raw = str(row.get("유형") or "").strip()
        order_raw = str(row.get("표시순서") or "").strip()
        if not any([code, name]):
            continue
        tag = f"{i}행" + (f"({code})" if code else "")
        if not code:
            errors.append(f"{i}행: 운영단위 코드를 입력하세요.")
        if not name:
            errors.append(f"{tag}: 운영단위 명칭을 입력하세요.")
        unit_type = _UNIT_TYPE_OF.get(type_raw.upper() if type_raw.isascii() else type_raw)
        if unit_type is None:
            errors.append(f"{tag}: 유형은 교대 또는 일반만 가능합니다. (입력값: {type_raw or '빈 값'})")
            unit_type = "SHIFT"
        try:
            order_val = int(order_raw) if order_raw else 0
        except ValueError:
            order_val = 0
            errors.append(f"{tag}: 표시순서는 숫자여야 합니다.")
        if order_raw == "":
            errors.append(f"{tag}: 표시순서를 입력하세요.")
        records.append({
            "dept_code": str(dept_code).strip(), "team_code": code, "team_name": name,
            "unit_type": unit_type, "description": str(row.get("비고") or "").strip(),
            "sort_order": order_val, "is_active": grid_bool(row.get("사용")),
        })
    return records, errors


def _unit_structure_errors(merged: pd.DataFrame, dept_code: str) -> list[str]:
    """선택 부서 기준 구조 검증 — 명칭·표시순서 중복 금지 (코드는 upsert 키로 보장)."""
    errors: list[str] = []
    if merged.empty:
        return errors
    sub = merged[merged["dept_code"].astype(str) == str(dept_code).strip()].copy()
    if sub.empty:
        return errors
    sub["team_name"] = sub["team_name"].astype(str).str.strip()
    sub["sort_order"] = pd.to_numeric(sub["sort_order"], errors="coerce").fillna(0).astype("int64")
    for name, group in sub.groupby("team_name"):
        if len(group) > 1:
            errors.append(f"운영단위 명칭 '{name}'이(가) 중복되었습니다: " + ", ".join(group["team_code"].astype(str)))
    for order, group in sub.groupby("sort_order"):
        if len(group) > 1:
            errors.append(f"표시순서 {order}이(가) 중복되었습니다: " + ", ".join(group["team_code"].astype(str)))
    return errors


def _save_units(grid_df, dept_code: str) -> None:
    """선택 부서의 조(운영단위) 편집 결과 검증 후 (부서, 코드) 기준 upsert."""
    if grid_df is None or not str(dept_code).strip():
        st.error("조를 저장할 부서를 먼저 선택하세요.")
        return
    readiness = _readiness()
    if not readiness.write_enabled:
        banner("danger" if readiness.state is Readiness.PROBE_ERROR else "warn", readiness.message)
        return
    live = live_rows(grid_df)
    store = db.get_org_teams()
    counts: dict[str, int] = {}
    # 귀속 부서는 현재 selectbox 값(dept_code)이 아니라 이 조 행들이 적재된 시점의 부서로
    # 바인딩한다. 상위 전환 중이라도 옛 조 행이 새 부서 밑으로 오귀속·중복되지 않는다.
    owner = str(st.session_state.get(_OU.key("loaded_dept"), dept_code) or dept_code)

    def _validate():
        return _validate_units(live, owner)

    def _build(records):
        merged, dup, n_c, n_u, _n_d = db.upsert_records(
            store, records, set(), ["dept_code", "team_code"], "is_active", db.ORG_TEAM_COLUMNS,
        )
        counts["create"], counts["update"] = n_c, n_u
        errs = []
        if dup:
            errs.append("운영단위 코드가 중복되었습니다: " + ", ".join(t for _d, t in dup))
        errs.extend(_unit_structure_errors(merged, owner))
        return merged, errs

    def _persist(merged, records):
        keys = [(r["dept_code"], r["team_code"]) for r in records if r.get("team_code")]
        try:
            report = db.save_org_teams_report(merged)
        except db.DATA_SOURCE_ERRORS as exc:
            return PersistResult.failure(_OU.page_id, keys, str(exc))
        return PersistResult(page_id=_OU.page_id, **report.to_persist_kwargs())

    outcome = run_save(_OU, validate=_validate, build_candidate=_build, persist=_persist)
    if outcome.status in ("invalid", "failed"):
        _error_banner("조를 저장하지 못했습니다.", outcome.errors)
        return
    if outcome.status in ("partial", "unknown"):
        ledger_banner(outcome.result)
        return
    _load_units(owner)  # 방금 저장한(귀속) 부서로 재적재
    _OU.set_flash("success", f"조를 저장했습니다. (신규 {counts.get('create', 0)} · 수정 {counts.get('update', 0)})")
    st.rerun()


def _plan_unit_delete(grid_df, dept_code: str) -> None:
    if grid_df is None:
        return
    readiness = _readiness()
    if not readiness.write_enabled:
        _OU.set_flash("error" if readiness.state is Readiness.PROBE_ERROR else "warning", readiness.message)
        st.rerun()
    live = live_rows(grid_df)
    sel = live[(live["_row_state"] == "existing") & live["_sel"].map(grid_bool)]
    keys = [str(r["_row_id"])[2:] for _, r in sel.iterrows()]  # _row_id = "e:{dept}|{team}"
    if not keys:
        _OU.set_flash("warning", "삭제할 기존 조를 선택하세요.")
        st.rerun()
    plan = {"delete": [], "deactivate": []}
    for key in keys:
        dc, tc = key.split("|", 1) if "|" in key else (dept_code, key)
        refs = db.team_reference_counts(dc, tc)
        item = {"dept_code": dc, "team_code": tc, "refs": refs}
        (plan["deactivate"] if sum(refs.values()) > 0 else plan["delete"]).append(item)
    st.session_state[_OU.delete_plan_key] = plan
    st.rerun()


def _unit_confirm_bar(plan: dict, dept_code: str, readiness: ReadinessState) -> None:
    lines = []
    for it in plan["delete"]:
        lines.append(f"삭제 가능: {it['team_code']}")
    for it in plan["deactivate"]:
        lines.append(f"미사용 처리: {it['team_code']} — 사용자 {it['refs'].get('users', 0)}명 소속")
    actionable = bool(plan["delete"] or plan["deactivate"]) and readiness.write_enabled
    result = confirm_bar(
        _OU, title="선택한 조를 참조 확인 후 미사용/삭제 처리합니다.",
        lines=lines, confirm_label="삭제 실행", confirm_enabled=actionable, scope="del",
    )
    if result == "confirm":
        _execute_unit_delete(plan, dept_code)
    elif result == "cancel":
        st.session_state.pop(_OU.delete_plan_key, None)
        st.rerun()


def _execute_unit_delete(plan: dict, dept_code: str) -> None:
    n_del = 0
    failed: list[str] = []
    for it in plan["delete"]:
        try:
            db.delete_team(it["dept_code"], it["team_code"])
            n_del += 1
        except db.DATA_SOURCE_ERRORS:
            failed.append(it["team_code"])
    deact = plan["deactivate"]
    n_deact = 0
    if deact:
        try:
            store = db.get_org_teams().copy()
            for it in deact:
                mask = (
                    (store["dept_code"].astype(str) == it["dept_code"])
                    & (store["team_code"].astype(str) == it["team_code"])
                )
                n_deact += int(mask.sum())
                store.loc[mask, "is_active"] = False
            db.save_org_teams(store[db.ORG_TEAM_COLUMNS])
        except db.DATA_SOURCE_ERRORS:
            n_deact = 0
            failed.extend(it["team_code"] for it in deact)
    st.session_state.pop(_OU.delete_plan_key, None)
    _load_units(dept_code)
    _finish_delete(_OU, "조", n_del, n_deact, None, failed)


# ---------- 그룹 구조 검증(교차 화면 회귀 호환 순수 함수) ----------
def _group_structure_errors(merged: pd.DataFrame) -> list[str]:
    """부서 프레임(department_group/group_sort_order) 기준 그룹순서 전역 유일 검증.

    migration 004 3시트 화면은 그룹을 organization_groups 1급 테이블로 관리하므로 이
    함수를 사용하지 않는다. 다만 교차 화면 회귀 테스트가 참조하는 순수 함수라 시그니처와
    동작(그룹 간 순서 중복·같은 그룹 순서 불일치 검출)을 보존한다.
    """
    errors: list[str] = []
    if merged is None or merged.empty or "department_group" not in merged:
        return errors
    frame = merged.copy()
    frame["department_group"] = frame["department_group"].astype(str).str.strip()
    frame["group_sort_order"] = pd.to_numeric(
        frame["group_sort_order"], errors="coerce"
    ).fillna(0).astype("int64")
    for group, sub in frame.groupby("department_group"):
        if not group:
            errors.append("그룹명이 비어 있는 부서가 있습니다: " + ", ".join(sub["dept_code"].astype(str)))
            continue
        orders = sorted(set(sub["group_sort_order"]))
        if len(orders) > 1:
            errors.append(f"그룹 '{group}'의 그룹순서가 서로 다릅니다: " + ", ".join(str(o) for o in orders))
    order_groups: dict[int, set] = {}
    for _, r in frame.iterrows():
        if r["department_group"]:
            order_groups.setdefault(int(r["group_sort_order"]), set()).add(r["department_group"])
    for order, names in sorted(order_groups.items()):
        if len(names) > 1:
            errors.append(f"그룹순서 {order}이(가) 여러 그룹에 중복되었습니다: " + ", ".join(sorted(names)))
    return errors


# ---------- 행 상태 · dirty · 오류/결과 배너 공통 헬퍼 ----------
def _apply_filter(df: pd.DataFrame, q: dict, code_col: str, name_col: str) -> pd.DataFrame:
    """사용 여부(3-state) + 검색어(코드·명칭 부분일치)로 조회 결과를 거른다."""
    if df is None or df.empty:
        return df
    if q.get("active") == "사용 중":
        df = df[df["is_active"].astype(bool)]
    elif q.get("active") == "사용 안 함":
        df = df[~df["is_active"].astype(bool)]
    term = str(q.get("search", "")).strip()
    if term:
        hit = (
            df[code_col].astype(str).str.contains(term, case=False, na=False, regex=False)
            | df[name_col].astype(str).str.contains(term, case=False, na=False, regex=False)
        )
        df = df[hit]
    return df


def _next_order(live: pd.DataFrame, col: str = "순서") -> int:
    """신규 행 기본 표시순서 = 현재 표시된 순서의 최대 + 1(없으면 1)."""
    if live is None or col not in live:
        return 1
    orders = pd.to_numeric(live[col], errors="coerce").dropna()
    return int(orders.max()) + 1 if len(orders) else 1


def _existing_count(rows: pd.DataFrame) -> int:
    if rows is None or rows.empty:
        return 0
    return int((rows["_row_state"].astype(str) == "existing").sum())


def _finish_delete(state: DraftState, noun: str, n_del: int, n_deact: int,
                   blocked, failed: list[str]) -> None:
    """삭제/미사용 실행 결과를 flash 로 통일 표기하고 rerun 한다(성공/실패 구분)."""
    parts = []
    if n_del:
        parts.append(f"{n_del}개 삭제")
    if n_deact:
        parts.append(f"{n_deact}개 미사용 처리")
    if blocked:
        parts.append(f"시스템 {noun} 제외: {', '.join(blocked)}")
    if failed:
        done = f"{noun} " + ", ".join(parts) + " · " if parts else ""
        state.set_flash(
            "error",
            f"{done}일부 {noun} 처리 실패: {', '.join(sorted(set(failed)))} — 다시 선택해 재시도하세요.",
        )
    else:
        msg = f"{noun}을(를) " + ", ".join(parts) + "했습니다." if parts else f"처리할 {noun}이(가) 없습니다."
        state.set_flash("success" if (n_del or n_deact) else "warning", msg)
    st.rerun()


def _error_banner(title: str, errors: list[str]) -> None:
    """§15/§21 오류 요약 배너 — 사유 목록을 배너 하단에 붙인다. draft 는 재적재하지 않는다."""
    body = "".join(f"<div>· {escape(str(e))}</div>" for e in (errors or []))
    banner("danger", title, extra=(f"<div class='keys'>{body}</div>" if body else ""))


def _set_baseline(state: DraftState, frame: pd.DataFrame, data_cols: list[str]) -> None:
    """dirty 비교 기준선(로드 시점 값)을 저장한다 — 셀 편집을 기존 값과 대조하기 위함."""
    base: dict[str, tuple] = {}
    if frame is not None and not frame.empty:
        for _, r in frame.iterrows():
            base[str(r["_row_id"])] = tuple(str(r.get(c, "")) for c in data_cols)
    st.session_state[state.key("baseline")] = base


def _dirty_counts(state: DraftState, live: pd.DataFrame, data_cols: list[str]) -> tuple[int, int]:
    """(신규 행 수, 기존 변경 행 수) — §20 dirty_total 공식 입력."""
    base = st.session_state.get(state.key("baseline"), {})
    new_cnt = changed_cnt = 0
    if live is None or live.empty:
        return 0, 0
    for _, r in live.iterrows():
        rid = str(r["_row_id"])
        vals = tuple(str(r.get(c, "")) for c in data_cols)
        if str(r["_row_state"]) == "new":
            if any(str(v).strip() for v in vals):
                new_cnt += 1
        elif rid in base and vals != base[rid]:
            changed_cnt += 1
    return new_cnt, changed_cnt


def _sync_rows(state: DraftState, grid_df: pd.DataFrame, row_cols: list[str]) -> bool:
    """붙여넣기로 생긴 무명 신규 행에 _row_id/_row_state 부여 + − 제거 행 반영.

    구조 변경이 있으면 Python 권위 상태(state.rows)를 갱신하고 True 를 반환한다."""
    if grid_df is None or grid_df.empty or "_row_id" not in grid_df.columns:
        return False
    removed = (
        grid_df["_removed"].fillna("").astype(str).str.strip() == "1"
        if "_removed" in grid_df
        else pd.Series(False, index=grid_df.index)
    )
    live = grid_df[~removed].copy()
    rid = live["_row_id"].fillna("").astype(str).str.strip()
    needs_id = rid == ""
    if not bool(removed.any() or needs_id.any()):
        return False
    live["_row_id"] = rid
    for idx in live.index[needs_id]:
        live.at[idx, "_row_id"] = state.next_rid()
        live.at[idx, "_row_state"] = "new"
        live.at[idx, "_sel"] = False
    live["_row_state"] = live["_row_state"].fillna("").astype(str).replace("", "new")
    state.set_rows(live[list(row_cols)].reset_index(drop=True))
    state.bump_nonce()
    return True
