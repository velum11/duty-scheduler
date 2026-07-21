"""기준정보 — 조직 관리: 그룹·부서(좌) + 선택 부서의 운영단위(우) 통합 화면.

부서 관리·조 관리 메뉴는 모두 이 화면을 연다 (사이드바 메뉴 구조는 무변경).
연결 구조는 그룹 → 부서 → 운영단위이며, 그룹은 departments 의 컬럼
(department_group/group_sort_order)로 관리하고 운영단위는 teams 를 그대로 쓰되
unit_type(SHIFT=교대/GENERAL=일반)으로 교대조와 일반근무를 함께 담는다.

이 화면은 Phase4 재설계로 공통 기반 패키지(``views/master``)와 디자인 계약
(design-contract.md §1~§25)을 따른다. **데이터 계약은 100% 보존**한다:
가상 그룹 모델(별도 groups 테이블·그룹코드 신설 없음), 그룹→부서→운영단위 종속,
그룹 편집의 화면 밖 전파, merged 기준 구조검증, 사용자 표시순서 충돌 사전검증,
좌·우 독립 저장·실패 초안 유지, 참조 기반 soft-delete·ADMIN 보호,
migration 003 미적용 시 저장 차단(UI+repository 이중 방어)을 그대로 유지한다.

순수·도메인 함수(build_org_rows/parse_org_grid/_group_structure_errors/
_validate_units/_unit_structure_errors)는 계약 테스트 대상이라 시그니처를 보존한다.
UI 계층만 공통 기반(DraftState/MasterGridSpec/master_action_bar/run_save/
ReadinessState/ledger_banner/style)으로 재구현한다.

좌측 그리드는 DB 의 행별 반복 저장 구조를 그대로 노출하지 않는다:
  - 가상 그룹 부모 행(_row_state="group") 아래에 부서 자식 행이 붙는 계층 표시.
  - 그룹명·그룹순서는 그룹 부모 행에서 한 번만 편집한다 (부서 행에는 없음).
  - 부서 행의 '소속그룹'은 이동/배정용 선택 필드다 — 그룹값을 직접 타이핑하지 않는다.
  - 저장 시 그룹 부모의 이름·순서를 소속 부서 전체 payload 로 자동 전파한다.
    (필터로 화면에 안 보이는 같은 그룹 부서에도 전파해 그룹이 갈라지지 않게 한다.)
  - 부서순서(sort_order)는 그룹 안 보조 표시순서 — 중복을 저장 오류로 막지 않는다
    (같으면 부서코드 보조 정렬). 그룹 내 유일해야 하는 순서는 사용자 표시순서
    (users.display_order)이며 사용자 관리에서 관리한다.

좌/우 패널은 각각 독립 저장 계약을 가진다 (org_dept = 그룹·부서, org_unit = 운영단위):
  - 저장 오류를 영역별로 분리해 보여주고, 실패한 영역의 편집 초안은 유지한다.
  - 운영단위는 우측 상단에서 선택한 부서에 종속된다 — 부서 선택 없이 저장 불가.

검증 규칙:
  - 그룹순서(group_sort_order)는 그룹 간 중복 금지, 같은 그룹은 하나의 순서만.
  - 그룹명 필수(trim), 그룹명 중복 비교는 trim+casefold — 이름이 같아지면 병합.
  - 빈 그룹(부서 0개인 새 그룹)은 저장 불가 (그룹은 부서 행에 실려 저장되므로).
  - 부서코드는 전역 유일. 같은 그룹 안 부서순서 중복은 허용.
  - 조직 저장 전, 변경 후 그룹 구조 기준으로 활성 사용자 표시순서 충돌을 검증한다
    (그룹 병합 시 PET생산부 1번·PET원료실 1번 같은 충돌을 사전 차단).
  - 같은 부서 안에서 운영단위 코드·명칭·표시순서 중복 금지, 유형은 교대/일반만.
  구조 검증은 화면에 보이는 행이 아니라 저장 후 전체(merged) 기준으로 수행해
  필터로 가려진 행과의 충돌도 차단한다.
"""
import json
from html import escape

import pandas as pd
import streamlit as st
from st_aggrid import JsCode

from modules import db, ui
from views.master import (
    ADD,
    ADD_GROUP,
    CONFIRM,
    DELETE,
    KEEP,
    RELOAD,
    REFRESH,
    SAVE,
    DraftState,
    MasterGridSpec,
    PersistResult,
    Readiness,
    ReadinessState,
    banner,
    confirm_bar,
    count_strip,
    dirty_total,
    discard_confirm_bar,
    grid_bool,
    ledger_banner,
    live_rows,
    master_action_bar,
    master_grid_height,
    master_screen_head,
    mode_badge_html,
    render_master_grid,
    run_save,
    show_flash,
)

_STATUS = ["사용 중", "사용 안 함", "전체"]

# 좌/우 패널의 page-scoped 편집 상태(공용 ms_* 누수 없음). 프레임워크가 없는 얇은
# 어댑터라 모듈 상수로 두어도 세션 상태(st.session_state)만 참조한다.
_OD = DraftState("org_dept")   # 좌: 그룹·부서
_OU = DraftState("org_unit")   # 우: 선택 부서의 운영단위

# migration 003 미적용 시 상단 1회 경고(readiness NOT_READY 배너 문구). 계약: 소스에 1회.
_NOT_READY_MSG = "조직 확장(migration 003) 적용 전 — 조회만 가능하며 저장은 차단됩니다."
# readiness 확인 자체 실패(PROBE_ERROR) — 네트워크/권한. 재확인(재probe)으로 회복 시도.
_PROBE_ERROR_MSG = "조직 스키마 상태 확인 실패 — 재확인이 필요합니다 (조회만 가능하며 저장은 차단됩니다)."

# 좌측: 그룹 부모 + 부서 자식 (한 그리드의 두 행 유형)
_DEPT_COLS = ["그룹·부서명", "순서", "소속그룹", "부서코드", "사용"]
_DEPT_ROW_COLS = ["_row_id", "_row_state", "_sel", *_DEPT_COLS]
_DEPT_GRID_COLUMNS = {
    "그룹·부서명": "text", "순서": "text", "소속그룹": "text",
    "부서코드": "text", "사용": "bool",
}
_SYSTEM_CODES = {"ADMIN"}

# 신규 그룹의 임시 라벨 (저장 시 그룹 부모 행의 이름으로 대체된다)
_NEW_GROUP_LABEL = "(새 그룹 {n} — 이름 입력)"

# 부서 행 전용 편집 — 그룹 부모 행에서는 소속그룹/부서코드/사용을 편집하지 않는다.
_DEPT_ONLY_EDITABLE = JsCode("function(p){ return p.data && p.data._row_state !== 'group'; }")

_ORG_NAME_RENDERER = JsCode(
    """
    function(p) {
      if (!p.data || p.data._row_state !== 'group') { return p.value || ''; }
      const name = p.value || '이름 없는 그룹';
      const rid = p.data._row_id || '';
      const target = rid.indexOf('g:') === 0
        ? rid.substring(2)
        : '(새 그룹 ' + rid.substring(3) + ' — 이름 입력)';
      let count = 0;
      p.api.forEachNodeAfterFilterAndSort(function(node) {
        if (node.rowIndex <= p.node.rowIndex) { return; }
        if (node.data && node.data._row_state === 'group') { return; }
        if (node.data && node.data['소속그룹'] === target) { count += 1; }
      });
      return name + ' · 부서 ' + count + '개';
    }
    """
)

_DEPT_CODE_RENDERER = JsCode(
    "function(p){ return p.data && p.data._row_state === 'group' ? '' : (p.value || ''); }"
)

# 우측: 선택한 부서의 운영단위 (교대조 A/B/C + 일반근무 나인투식스/상근 등)
_UNIT_COLS = ["코드", "명칭", "유형", "표시순서", "사용"]
_UNIT_ROW_COLS = ["_row_id", "_row_state", "_sel", *_UNIT_COLS]
_UNIT_GRID_COLUMNS = {"코드": "text", "명칭": "text", "유형": "text", "표시순서": "text", "사용": "bool"}
_UNIT_COL_CONFIG = {
    "코드": {"flex": 0, "width": 84, "minWidth": 72, "cellClass": "md-c-left"},
    "명칭": {"flex": 1, "minWidth": 100, "cellClass": "md-c-left"},
    "유형": {
        "flex": 0, "width": 84, "minWidth": 72, "maxWidth": 104, "cellClass": "md-c-center",
        "cellEditor": "agSelectCellEditor",
        "cellEditorParams": {"values": ["교대", "일반"]},
        "cellClassRules": {
            "ms-unit-shift": "value == '교대'",
            "ms-unit-general": "value == '일반'",
        },
    },
    "표시순서": {"flex": 0, "width": 80, "minWidth": 68, "maxWidth": 104, "cellClass": "md-c-center ms-num"},
    "사용": {"flex": 0, "width": 62, "minWidth": 56, "maxWidth": 84, "cellClass": "md-c-center"},
}

# 유형 입력 정규화 — 화면 표시값(교대/일반)과 내부값(SHIFT/GENERAL) 모두 허용.
_UNIT_TYPE_OF = {
    "교대": "SHIFT", "일반": "GENERAL",
    "SHIFT": "SHIFT", "GENERAL": "GENERAL",
}

# 조직 전용 페이지 크롬 — 공통 크롬(views/master/style) 위에 흐름 스텝과 패널 카드만
# 얹는다. 색은 공통 토큰(--ms-*)을 재사용한다.
_ORG_PAGE_CSS = """
<style>
.org-flow { display:flex; align-items:center; gap:.5rem; margin:.15rem 0 .35rem; color:var(--ms-ink-2); font-size:.76rem; flex-wrap:wrap; }
.org-flow-step { display:flex; align-items:center; gap:.4rem; padding:.32rem .58rem; background:var(--ms-surface-2); border:1px solid var(--ms-line); border-radius:7px; }
.org-flow-step b { display:inline-flex; align-items:center; justify-content:center; width:1.2rem; height:1.2rem; border-radius:50%; background:var(--ms-navy); color:#FFF; font-size:.66rem; }
.org-flow-arrow { color:var(--ms-gold); font-weight:700; }
.st-key-org_dept__panel, .st-key-org_unit__panel { background:var(--ms-surface); border:1px solid var(--ms-line-strong);
  border-radius:8px; padding:.7rem .75rem .6rem; box-shadow:0 1px 0 rgba(0,0,0,.02); }
/* 액션바 버튼은 절대 세로로 줄바꿈하지 않는다(좁은 폭에서도 `부/서` 눌림 방지). */
.st-key-org_dept__bar div.stButton > button, .st-key-org_unit__bar div.stButton > button {
  white-space:nowrap; min-width:0; overflow:hidden; text-overflow:ellipsis; }
/* §23 반응형 — ≤1100px 에서 좌/우 2패널을 세로 스택(좌 위·우 아래). 본문 가로 스크롤 금지. */
@media (max-width: 1100px) {
  .st-key-org__panels div[data-testid="stHorizontalBlock"] { flex-wrap:wrap; }
  .st-key-org__panels div[data-testid="stColumn"] { flex:1 1 100% !important; width:100% !important; min-width:100% !important; }
  .st-key-org__panels div[data-testid="stColumn"]:first-child { margin-bottom:.6rem; }
}
</style>
"""


def render(user: dict) -> None:
    master_screen_head(
        "조직 관리",
        "그룹과 부서를 관리하고, 선택한 부서의 운영단위(교대조·일반근무)를 설정합니다.",
        breadcrumb="기준정보 › 조직 관리",
        mode_badge=_head_badges(),
    )
    st.markdown(_ORG_PAGE_CSS, unsafe_allow_html=True)

    readiness = _readiness()
    readiness.banner()  # NOT_READY/PROBE_ERROR 만 배너, READY 는 모드/스키마 배지로만.
    if readiness.state is Readiness.PROBE_ERROR:
        # 확인 자체 실패 — 캐시를 비우고 재probe 하는 명시적 재확인 동작(§25).
        if st.button("스키마 재확인", key="org__recheck", icon=":material/refresh:"):
            db.reset_org_schema_cache()
            st.rerun()

    st.markdown(
        "<div class='org-flow'>"
        "<span class='org-flow-step'><b>1</b>그룹</span><span class='org-flow-arrow'>›</span>"
        "<span class='org-flow-step'><b>2</b>부서</span><span class='org-flow-arrow'>›</span>"
        "<span class='org-flow-step'><b>3</b>선택 부서의 운영단위</span>"
        "</div>",
        unsafe_allow_html=True,
    )

    # 새로고침 의도는 렌더 시작에서 소비(재적재 판단에 필요). 나머지 액션은 그리드
    # 렌더 뒤(최신 snapshot 수신 후) 소비한다 — §24 2단계 command 순서.
    refresh_dept = _OD.take_action(REFRESH)
    refresh_unit = _OU.take_action(REFRESH)

    with st.container(key="org__filter"):
        f1, f2, _sp = st.columns([1.4, 3.0, 5.6], vertical_alignment="bottom")
        active = f1.selectbox("사용 여부", _STATUS, key="og_active", label_visibility="collapsed")
        search = f2.text_input(
            "검색", key="og_search", placeholder="그룹·부서코드·부서명 검색",
            label_visibility="collapsed",
        )

    params = {"active": active, "search": search.strip()}
    # dirty 미저장 draft 는 무경고로 폐기하지 않는다(§17) — CONFIRM 시 폐기 확인 바를 탄다.
    decision = _OD.resolve_reload(params, refresh=refresh_dept, dirty=_OD.is_dirty())
    if decision == RELOAD:
        st.session_state.pop(_OD.delete_plan_key, None)
        _load_depts(params)

    # 패널 행을 스코프 컨테이너로 감싸 ≤1100px 세로 스택 CSS 를 이 행에만 적용한다.
    with st.container(key="org__panels"):
        left, right = st.columns([1.25, 1], gap="medium")
        with left:
            with st.container(key="org_dept__panel"):
                dept_grid = _render_dept_panel(params, readiness)
        with right:
            with st.container(key="org_unit__panel"):
                unit_grid, unit_dept = _render_unit_panel(refresh_unit, readiness)

    # 버튼 클릭 처리 (최신 grid 데이터 기준 — 양쪽 그리드 렌더 이후, page-scoped flag).
    if _OD.take_action(ADD_GROUP):
        _add_group_rows(dept_grid)
    if _OD.take_action(ADD):
        _add_dept_row(dept_grid)
    if _OD.take_action(DELETE):
        _plan_dept_delete(dept_grid)
    if _OD.take_action(SAVE):
        _save_depts(dept_grid, params)
    if _OU.take_action(ADD):
        _add_unit_row(unit_grid, unit_dept)
    if _OU.take_action(DELETE):
        _plan_unit_delete(unit_grid, unit_dept)
    if _OU.take_action(SAVE):
        _save_units(unit_grid, unit_dept)

    changed = _sync_rows(_OD, dept_grid, _DEPT_ROW_COLS)
    if unit_grid is not None:
        changed = _sync_rows(_OU, unit_grid, _UNIT_ROW_COLS) or changed
    if changed:
        st.rerun()


# ---------- 헤더 배지 · readiness ----------
def _head_badges() -> str:
    """§5 모드 배지(데이터 연결) + §25 readiness 배지(스키마 준비) — 색·의미 분리."""
    readiness = _readiness()
    badges = ""
    if not readiness.write_enabled:  # READY 가 아니면 스키마 배지를 함께 노출
        badges += readiness.badge_html()
    badges += mode_badge_html(connected=True, sample=db.is_sample_mode())
    return badges


def _readiness() -> ReadinessState:
    """migration 003 적용 상태를 3-state(READY/NOT_READY/PROBE_ERROR)로 매핑한다.

    Lane E 의 ``db.org_schema_readiness()`` 라이브 read-only probe 를 그대로 승격한다:
      - READY: 확장 컬럼 사용 가능 → 좌·우 write 활성.
      - NOT_READY: migration 003 미적용(확인 성공) → 조회 전용 warn 배너.
      - PROBE_ERROR: 확인 자체 실패(권한/네트워크) → danger 배너 + '스키마 재확인'(재probe).
    실제 WRITE 차단은 ``ReadinessState.write_enabled``(READY 에서만 True)가 담당하므로
    오분류(NOT_READY↔PROBE_ERROR)가 쓰기를 열지 않는다.
    """
    state = db.org_schema_readiness()
    if state == db.READINESS_READY:
        return ReadinessState.ready()
    if state == db.READINESS_PROBE_ERROR:
        return ReadinessState.probe_error(_PROBE_ERROR_MSG)
    return ReadinessState.not_ready(_NOT_READY_MSG)


# ---------- 좌측 패널: 그룹(부모) · 부서(자식) ----------
def _group_labels(rows: pd.DataFrame) -> list[str]:
    """현재 그리드의 그룹 부모 라벨 목록 (소속그룹 selectbox 선택지)."""
    if rows is None or rows.empty:
        return []
    groups = rows[rows["_row_state"] == "group"]
    labels = []
    for _, r in groups.iterrows():
        rid = str(r["_row_id"])
        if rid.startswith("gn:"):
            labels.append(_NEW_GROUP_LABEL.format(n=rid[3:]))
        else:
            labels.append(rid[2:])  # "g:{로드 시점 그룹명}"
    return labels


def _render_dept_panel(params: dict, readiness: ReadinessState) -> pd.DataFrame:
    st.markdown("<div class='ms-panel'>그룹 · 부서 구조</div>", unsafe_allow_html=True)
    show_flash(_OD)

    # dirty 폐기 확인 바(§17) — 필터/새로고침으로 재적재가 대기 중일 때만.
    if _OD.has_pending_reload():
        gate = discard_confirm_bar(_OD)
        if gate == "discard":
            p = _OD.apply_pending_reload()
            st.session_state.pop(_OD.delete_plan_key, None)
            _load_depts(p if p is not None else params)
            st.rerun()
        elif gate == "cancel":
            _OD.cancel_pending_reload()
            st.rerun()

    plan = st.session_state.get(_OD.delete_plan_key)
    if plan:
        _dept_confirm_bar(plan, params, readiness)

    bar = st.container(key="org_dept__bar")
    rows = _OD.get_rows()

    # 소속그룹 선택지는 현재 그리드의 그룹 부모 행에서 도출 (신규 그룹 포함)
    col_config = {
        "그룹·부서명": {
            "flex": 1.6, "minWidth": 130, "cellClass": "md-c-left",
            "cellClassRules": {"ms-indent": "data._row_state != 'group'"},
            "cellRenderer": _ORG_NAME_RENDERER,
        },
        "순서": {"flex": 0, "width": 68, "minWidth": 60, "maxWidth": 92, "cellClass": "md-c-center ms-num"},
        "소속그룹": {
            "flex": 1, "minWidth": 104, "cellClass": "md-c-left ms-cell-select",
            "headerName": "그룹 이동",
            # editable(JsCode) + cellEditor 조합은 st_aggrid 에서 select 가 열리지
            # 않아, selector 로 그룹 행 차단과 select 지정을 함께 처리한다.
            "cellEditorSelector": JsCode(
                "function(p){"
                " if (p.data && p.data._row_state === 'group') { return null; }"
                " return { component: 'agSelectCellEditor',"
                f" params: {{ values: {json.dumps([''] + _group_labels(rows), ensure_ascii=False)} }} }};"
                "}"
            ),
        },
        "부서코드": {"flex": 0, "width": 92, "minWidth": 80, "cellClass": "md-c-left",
                  "editable": _DEPT_ONLY_EDITABLE, "cellRenderer": _DEPT_CODE_RENDERER},
        "사용": {"flex": 0, "width": 60, "minWidth": 54, "maxWidth": 84, "cellClass": "md-c-center",
               "editable": _DEPT_ONLY_EDITABLE},
    }
    spec = MasterGridSpec(
        page_id=_OD.page_id, columns=_DEPT_GRID_COLUMNS, order=_DEPT_COLS,
        col_config=col_config, select_all=True, include_group_rows=True,
        height=master_grid_height(len(rows)),
    )
    with st.container(key="org_dept__grid"):
        grid_df = render_master_grid(spec, _dept_display(rows), key=_OD.grid_key())

    live = live_rows(grid_df)
    depts_live = live[live["_row_state"] != "group"]
    existing = depts_live[depts_live["_row_state"] == "existing"]
    sel_count = int((existing["_sel"].map(grid_bool)).sum()) if not existing.empty else 0
    n_groups = int((live["_row_state"] == "group").sum())
    new_cnt, changed_cnt = _dirty_counts(_OD, live, _DEPT_COLS)
    total = dirty_total(new_cnt, changed_cnt)
    _OD.set_dirty(total > 0)

    with bar:
        _org_dept_bar(sel_count, total, readiness)
    count_strip(len(existing), new_cnt, changed_cnt, sel_count, groups=n_groups)
    return grid_df


def _org_dept_bar(sel_count: int, total: int, readiness: ReadinessState) -> None:
    """좌측 작업 버튼: [＋ 그룹][＋ 부서][삭제][저장] · 우측 [새로고침].

    액션바 키는 ``{page_id}__{role}`` 규칙(공통 style 부분일치 선택자 대상)이다.
    NOT_READY/PROBE_ERROR 면 그룹·부서·삭제·저장(=모든 write control)을 비활성(§25) —
    조회·새로고침만 가능하고 disabled 사유는 동일한 readiness 메시지로 통일한다.
    """
    write = readiness.write_enabled
    write_reason = readiness.message if not write else None  # 통일된 readiness 사유
    save_enabled = write and total > 0
    if not write:
        save_reason = write_reason
    elif total == 0:
        save_reason = "저장할 변경이 없습니다"
    else:
        save_reason = None
    save_label = f"저장 · {total}" if total else "저장"

    g, a, d, s, _sp, r = st.columns([1.3, 1.3, 1.2, 1.4, 2.0, 1.6], vertical_alignment="center")
    g.button("그룹", key=f"{_OD.page_id}__addg", icon=":material/create_new_folder:", width="stretch",
             disabled=not write,
             help=write_reason or "새 그룹과 첫 부서 행을 함께 추가합니다 (빈 그룹은 저장할 수 없습니다)",
             on_click=_OD.action_requester(ADD_GROUP))
    a.button("부서", key=f"{_OD.page_id}__add", icon=":material/add:", width="stretch",
             disabled=not write, help=write_reason or "부서 행을 추가합니다 — 소속그룹을 선택하세요",
             on_click=_OD.action_requester(ADD))
    d.button("삭제", key=f"{_OD.page_id}__delete", icon=":material/delete:", width="stretch",
             disabled=not write or int(sel_count) == 0,
             help=write_reason or ("삭제할 행을 먼저 선택" if int(sel_count) == 0 else None),
             on_click=_OD.action_requester(DELETE))
    s.button(save_label, key=f"{_OD.page_id}__save", type="primary", width="stretch",
             disabled=not save_enabled, help=save_reason,
             on_click=_OD.action_requester(SAVE))
    r.button("새로고침", key=f"{_OD.page_id}__refresh", icon=":material/refresh:", width="stretch",
             on_click=_OD.action_requester(REFRESH))


def _dept_display(rows: pd.DataFrame) -> pd.DataFrame:
    """세션 권위 행에 view-model 메타(_inactive/_protected/_delete)를 얹는다(§25 B5).

    상태→시각 이중부호화는 공통 style 의 rowClassRules 가 이 숨김 필드를 읽어 그린다.
    """
    frame = rows.copy() if rows is not None else pd.DataFrame(columns=_DEPT_ROW_COLS)
    if frame.empty:
        return frame
    codes = frame["부서코드"].astype(str).str.strip()
    is_dept = frame["_row_state"].astype(str) != "group"
    frame["_inactive"] = ((is_dept) & (~frame["사용"].map(grid_bool))).map(_flag)
    frame["_protected"] = (is_dept & codes.str.upper().isin(_SYSTEM_CODES)).map(_flag)
    plan = st.session_state.get(_OD.delete_plan_key)
    del_codes = _plan_codes(plan)
    frame["_delete"] = codes.isin(del_codes).map(_flag)
    return frame


def _flag(cond) -> str:
    return "1" if bool(cond) else ""


def _plan_codes(plan) -> set:
    if not plan:
        return set()
    codes = set(plan.get("delete", []))
    codes |= {item["code"] for item in plan.get("deactivate", []) if "code" in item}
    return codes


def build_org_rows(df: pd.DataFrame) -> pd.DataFrame:
    """departments 프레임 → 가상 그룹 부모 + 부서 자식 행 모델 (항상 펼침).

    그룹 부모: _row_id="g:{그룹명}", 그룹·부서명=그룹명, 순서=그룹순서,
               부서코드 셀은 비워 두고 렌더러가 명칭 옆에 부서 수를 표시.
    부서 자식: _row_id="e:{부서코드}", 그룹·부서명=부서명(들여쓰기), 순서=부서순서,
               소속그룹=로드 시점 그룹명 (selectbox 로 이동).
    정렬: 그룹순서 → (그룹명) → 부서순서 → 부서코드 (부서순서 동률은 코드 보조 정렬).
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=_DEPT_ROW_COLS)
    frame = df.copy()
    frame["department_group"] = frame["department_group"].fillna("").astype(str).str.strip()
    frame["group_sort_order"] = pd.to_numeric(frame["group_sort_order"], errors="coerce").fillna(0).astype("int64")
    frame["sort_order"] = pd.to_numeric(frame["sort_order"], errors="coerce").fillna(0).astype("int64")
    frame = frame.sort_values(
        ["group_sort_order", "department_group", "sort_order", "dept_code"]
    ).reset_index(drop=True)

    rows: list[dict] = []
    for (g_order, group), sub in frame.groupby(
        ["group_sort_order", "department_group"], sort=True
    ):
        rows.append({
            "_row_id": f"g:{group}", "_row_state": "group", "_sel": False,
            "그룹·부서명": group, "순서": str(int(g_order)),
            "소속그룹": "", "부서코드": "", "사용": True,
        })
        for _, r in sub.iterrows():
            rows.append({
                "_row_id": f"e:{str(r['dept_code']).strip()}",
                "_row_state": "existing", "_sel": False,
                "그룹·부서명": str(r["dept_name"]).strip(),
                "순서": str(int(r["sort_order"])),
                "소속그룹": group,
                "부서코드": str(r["dept_code"]).strip(),
                "사용": bool(r["is_active"]),
            })
    return pd.DataFrame(rows, columns=_DEPT_ROW_COLS)


def _load_depts(q: dict) -> None:
    """조회 조건(사용 여부 + 검색어)으로 그룹·부서를 계층 행 모델로 적재한다."""
    df = db.get_org_departments()
    if q["active"] == "사용 중":
        df = df[df["is_active"]]
    elif q["active"] == "사용 안 함":
        df = df[~df["is_active"].astype(bool)]
    term = str(q.get("search", "")).strip()
    if term:
        hit = (
            df["department_group"].astype(str).str.contains(term, case=False, na=False, regex=False)
            | df["dept_code"].astype(str).str.contains(term, case=False, na=False, regex=False)
            | df["dept_name"].astype(str).str.contains(term, case=False, na=False, regex=False)
        )
        df = df[hit]
    rows = build_org_rows(df)
    _OD.set_rows(rows)
    _set_baseline(_OD, rows, _DEPT_COLS)
    _OD.bump_nonce()
    _OD.set_dirty(False)


def _add_group_rows(grid_df: pd.DataFrame) -> None:
    """새 가상 그룹 부모 + 첫 부서 자식 행을 함께 추가한다 (빈 그룹 저장 불가 안내)."""
    live = live_rows(grid_df)
    n = st.session_state.get(_OD.key("gid"), 0) + 1
    st.session_state[_OD.key("gid")] = n
    label = _NEW_GROUP_LABEL.format(n=n)
    group_row = {
        "_row_id": f"gn:{n}", "_row_state": "group", "_sel": False,
        "그룹·부서명": "", "순서": "", "소속그룹": "", "부서코드": "", "사용": True,
    }
    dept_row = {
        "_row_id": _OD.next_rid(), "_row_state": "new", "_sel": False,
        "그룹·부서명": "", "순서": "1", "소속그룹": label, "부서코드": "", "사용": True,
    }
    _OD.set_rows(pd.concat(
        [live[_DEPT_ROW_COLS], pd.DataFrame([group_row, dept_row])], ignore_index=True,
    )[_DEPT_ROW_COLS])
    _OD.bump_nonce()
    st.rerun()


def _add_dept_row(grid_df: pd.DataFrame) -> None:
    """신규 부서 자식 행 추가 — 소속그룹은 selectbox 로 선택한다."""
    live = live_rows(grid_df)
    labels = _group_labels(live)
    row = {
        "_row_id": _OD.next_rid(), "_row_state": "new", "_sel": False,
        "그룹·부서명": "", "순서": "", "소속그룹": labels[0] if len(labels) == 1 else "",
        "부서코드": "", "사용": True,
    }
    _OD.set_rows(pd.concat(
        [live[_DEPT_ROW_COLS], pd.DataFrame([row])], ignore_index=True,
    )[_DEPT_ROW_COLS])
    _OD.bump_nonce()
    st.rerun()


def parse_org_grid(live: pd.DataFrame, store: pd.DataFrame):
    """계층 그리드 → 부서 저장 레코드. (records, errors) 반환 (모듈 레벨 — 테스트 가능).

    - 그룹 부모 행에서 그룹명·그룹순서를 1회 수집한다.
    - 부서 자식 행의 '소속그룹'(로드 시점 라벨/신규 라벨)을 그룹 부모에 매핑해
      department_group/group_sort_order 를 자동 부여한다.
    - 기존 그룹의 이름·순서 변경은 화면(필터)에 없는 같은 그룹 부서에도 전파한다.
    - 그룹명은 trim, 중복 비교는 casefold — 이름이 같아지면 병합(순서 동일해야 함).
    - 빈 그룹(부서 0개인 새 그룹)은 오류. 부서순서는 빈 값=0 허용, 중복 허용.
    """
    errors: list[str] = []

    # 1) 그룹 부모 수집: gid → {orig(로드 시 라벨), name, order}
    groups: dict[str, dict] = {}
    label_to_gid: dict[str, str] = {}
    for i, (_, row) in enumerate(live.iterrows(), start=1):
        if str(row.get("_row_state")) != "group":
            continue
        gid = str(row.get("_row_id") or "")
        name = str(row.get("그룹·부서명") or "").strip()
        order_raw = str(row.get("순서") or "").strip()
        orig = gid[2:] if gid.startswith("g:") else None
        label = orig if orig is not None else _NEW_GROUP_LABEL.format(n=gid[3:] or "?")
        label_to_gid[label] = gid
        label_to_gid[label.casefold()] = gid
        order = None
        if order_raw:
            try:
                order = int(order_raw)
            except ValueError:
                errors.append(f"그룹 '{name or label}': 그룹순서는 숫자여야 합니다.")
        groups[gid] = {"orig": orig, "label": label, "name": name, "order": order, "row": i}

    # 2) 부서 자식 수집 + 소속그룹 매핑
    dept_rows: list[dict] = []
    for i, (_, row) in enumerate(live.iterrows(), start=1):
        if str(row.get("_row_state")) == "group":
            continue
        code = str(row.get("부서코드") or "").strip()
        name = str(row.get("그룹·부서명") or "").strip()
        d_raw = str(row.get("순서") or "").strip()
        parent_txt = str(row.get("소속그룹") or "").strip()
        if not any([code, name, parent_txt]):
            continue  # 완전히 빈 신규 행

        tag = f"{i}행" + (f"({code})" if code else "")
        if not code:
            errors.append(f"{i}행: 부서코드를 입력하세요.")
        if not name:
            errors.append(f"{tag}: 부서명을 입력하세요.")

        gid = label_to_gid.get(parent_txt) or label_to_gid.get(parent_txt.casefold())
        if not parent_txt:
            errors.append(f"{tag}: 소속그룹을 선택하세요.")
        elif gid is None:
            errors.append(f"{tag}: 존재하지 않는 그룹입니다: {parent_txt}")

        d_order = 0
        if d_raw:
            try:
                d_order = int(d_raw)
            except ValueError:
                errors.append(f"{tag}: 부서순서는 숫자여야 합니다.")

        dept_rows.append({
            "gid": gid, "dept_code": code, "dept_name": name,
            "sort_order": d_order, "is_active": grid_bool(row.get("사용")),
        })

    # 3) 그룹 검증 — 자식 있는 그룹만 이름·순서 필수, 새 그룹은 자식 필수
    children: dict[str, int] = {}
    for d in dept_rows:
        if d["gid"]:
            children[d["gid"]] = children.get(d["gid"], 0) + 1
    for gid, info in groups.items():
        has_children = children.get(gid, 0) > 0
        in_store = (
            info["orig"] is not None
            and not store.empty
            and (store["department_group"].astype(str).str.strip() == info["orig"]).any()
        )
        if info["orig"] is None and not has_children:
            errors.append(
                f"새 그룹 '{info['name'] or info['label']}'에 부서가 없습니다 — "
                "부서를 1개 이상 추가하거나 그룹 행을 비워두지 마세요."
            )
        if not (has_children or in_store):
            continue  # 저장에 영향 없는 그룹 행은 더 검증하지 않음
        if not info["name"]:
            errors.append(f"그룹 행({info['label']}): 그룹명을 입력하세요.")
        if info["order"] is None:
            errors.append(f"그룹 '{info['name'] or info['label']}': 그룹순서를 입력하세요.")

    # 4) 최종 그룹명 casefold 병합 — 이름이 같으면 순서도 같아야 한다
    by_final: dict[str, list] = {}
    for gid, info in groups.items():
        if info["name"]:
            by_final.setdefault(info["name"].casefold(), []).append(info)
    for _key, infos in by_final.items():
        orders = {info["order"] for info in infos if info["order"] is not None}
        if len(orders) > 1:
            errors.append(
                f"그룹 '{infos[0]['name']}'(병합)의 그룹순서가 서로 다릅니다: "
                + ", ".join(str(o) for o in sorted(orders))
            )

    # 5) 레코드 생성 — 화면 부서 행 + 화면 밖 같은 그룹 부서 전파
    records: list[dict] = []
    seen_codes: set[str] = set()
    for d in dept_rows:
        info = groups.get(d["gid"]) if d["gid"] else None
        group_name = info["name"] if info else ""
        group_order = info["order"] if info and info["order"] is not None else 0
        records.append({
            "dept_code": d["dept_code"], "dept_name": d["dept_name"],
            "department_group": group_name, "group_sort_order": group_order,
            "sort_order": d["sort_order"], "is_active": d["is_active"],
        })
        if d["dept_code"]:
            seen_codes.add(d["dept_code"])

    if not store.empty:
        store_group = store["department_group"].astype(str).str.strip()
        for gid, info in groups.items():
            if info["orig"] is None or not info["name"] or info["order"] is None:
                continue
            renamed = info["name"] != info["orig"]
            for _, r in store[store_group == info["orig"]].iterrows():
                code = str(r["dept_code"]).strip()
                if code in seen_codes:
                    continue
                same_order = int(pd.to_numeric(r["group_sort_order"], errors="coerce") or 0) == info["order"]
                if not renamed and same_order:
                    continue  # 변경 없음 — 전파 불필요
                records.append({
                    "dept_code": code, "dept_name": str(r["dept_name"]).strip(),
                    "department_group": info["name"], "group_sort_order": info["order"],
                    "sort_order": int(pd.to_numeric(r["sort_order"], errors="coerce") or 0),
                    "is_active": bool(r["is_active"]),
                })
                seen_codes.add(code)
    return records, errors


def _save_depts(grid_df: pd.DataFrame, q: dict) -> None:
    """그룹·부서 편집 결과 검증 후 dept_code 기준 batch upsert (오류 시 전체 차단).

    저장 프로토콜은 공통 ``run_save`` 로 감싼다: validate → build merged candidate →
    persist. 실패/불명은 draft 를 보존하고, 완전 성공에서만 재적재한다(§22·§25).
    """
    readiness = _readiness()
    if not readiness.write_enabled:
        banner("danger" if readiness.state is Readiness.PROBE_ERROR else "warn", readiness.message)
        return
    live = live_rows(grid_df)
    store = db.get_org_departments()
    counts: dict[str, int] = {}

    def _validate():
        return parse_org_grid(live, store)

    def _build(records):
        merged, dup, n_c, n_u, _n_d = db.upsert_records(
            store, records, set(), ["dept_code"], "is_active", db.ORG_DEPT_COLUMNS,
        )
        counts["records"] = len(records)
        counts["create"], counts["update"] = n_c, n_u
        errs: list[str] = []
        if dup:
            errs.append("부서코드가 중복되었습니다: " + ", ".join(k[0] for k in dup))
        # 구조 검증은 merged(저장 후 전체) 기준 — 필터로 가려진 그룹·부서와의 충돌 차단.
        errs.extend(_group_structure_errors(merged))
        # 변경 후 그룹 구조 기준 활성 사용자 표시순서 충돌 검증 (그룹 병합 사전 차단).
        order_errors = db.display_order_conflicts(db.get_users(), db.dept_group_map(merged))
        if order_errors:
            errs.extend(order_errors)
            errs.append("→ 사용자 관리에서 해당 사용자의 표시순서를 먼저 조정한 뒤 다시 저장하세요.")
        return merged, errs

    def _persist(merged, records):
        # 부분성공 원장 API — repository 가 저장/실패 자연키를 그대로 돌려준다(§22).
        # 좌 패널은 자기 명령만 저장한다(우 패널과 합치지 않음 = 별도 ledger).
        keys = [r["dept_code"] for r in records if r.get("dept_code")]
        try:
            report = db.save_org_departments_report(merged)
        except db.DATA_SOURCE_ERRORS as exc:
            return PersistResult.failure(_OD.page_id, keys, str(exc))
        return PersistResult(page_id=_OD.page_id, **report.to_persist_kwargs())

    outcome = run_save(_OD, validate=_validate, build_candidate=_build, persist=_persist)

    if outcome.status == "invalid":
        _error_banner("그룹·부서를 저장하지 못했습니다.", outcome.errors)
        return
    if outcome.status == "failed":
        _error_banner("그룹·부서를 저장하지 못했습니다.", outcome.errors)
        return
    if outcome.status in ("partial", "unknown"):
        ledger_banner(outcome.result)  # NOT_READY 는 위에서 이미 차단됨(§25 원장 금지 준수)
        return
    # saved — 완전 성공에서만 재적재 + 우측 컨텍스트 재평가.
    _load_depts(q)
    st.session_state.pop(_OU.query_key, None)  # 부서명·그룹 변경 반영 위해 우측 재적재 유도
    n_c, n_u = counts.get("create", 0), counts.get("update", 0)
    _OD.set_flash(
        "success",
        f"그룹·부서를 저장했습니다. (부서 {counts.get('records', 0)}건 반영 — 신규 {n_c} · 수정 {n_u})",
    )
    st.rerun()


def _group_structure_errors(merged: pd.DataFrame) -> list[str]:
    """저장 후 전체 기준 구조 검증 — 그룹순서 전역 유일 + 같은 그룹 순서 단일.

    부서순서(sort_order)는 그룹 안 보조 표시순서라 중복을 허용한다
    (같으면 부서코드 보조 정렬). 그룹 내 유일 요구는 사용자 표시순서 쪽 계약이다.
    """
    errors: list[str] = []
    if merged.empty:
        return errors
    frame = merged.copy()
    frame["department_group"] = frame["department_group"].astype(str).str.strip()
    frame["group_sort_order"] = pd.to_numeric(
        frame["group_sort_order"], errors="coerce"
    ).fillna(0).astype("int64")

    for group, sub in frame.groupby("department_group"):
        if not group:
            errors.append(
                "그룹명이 비어 있는 부서가 있습니다: "
                + ", ".join(sub["dept_code"].astype(str))
            )
            continue
        orders = sorted(set(sub["group_sort_order"]))
        if len(orders) > 1:
            errors.append(
                f"그룹 '{group}'의 그룹순서가 서로 다릅니다: "
                + ", ".join(str(o) for o in orders)
            )

    order_groups: dict[int, set] = {}
    for _, r in frame.iterrows():
        if r["department_group"]:
            order_groups.setdefault(int(r["group_sort_order"]), set()).add(r["department_group"])
    for order, names in sorted(order_groups.items()):
        if len(names) > 1:
            errors.append(
                f"그룹순서 {order}이(가) 여러 그룹에 중복되었습니다: " + ", ".join(sorted(names))
            )
    return errors


def _plan_dept_delete(grid_df: pd.DataFrame) -> None:
    readiness = _readiness()
    if not readiness.write_enabled:
        _OD.set_flash("error" if readiness.state is Readiness.PROBE_ERROR else "warning", readiness.message)
        st.rerun()
    live = live_rows(grid_df)
    sel = live[(live["_row_state"] == "existing") & live["_sel"].map(grid_bool)]
    codes = sorted({str(c).strip() for c in sel["부서코드"] if str(c).strip()})
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


def _ref_text(refs: dict) -> str:
    parts = []
    if refs.get("users"):
        parts.append(f"사용자 {refs['users']}명")
    if refs.get("teams"):
        parts.append(f"운영단위 {refs['teams']}개")
    if refs.get("shift_groups"):
        parts.append(f"편성 {refs['shift_groups']}건")
    return ", ".join(parts) or "참조 있음"


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
    """참조 없는 부서는 물리 삭제, 참조 중인 부서는 미사용 처리.

    B4: 대상별 write 예외(``DATA_SOURCE_ERRORS``)를 controller 경계에서 잡아 성공/실패를
    구분한다 — raw Streamlit 예외 대신, 성공분만 반영하고 실패분은 재시도 가능한 안내를
    남긴다. 2단계 확인·ADMIN 보호·참조 시 soft/미참조 시 hard 계약은 유지한다.
    """
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

    parts = []
    if n_del:
        parts.append(f"{n_del}개 삭제")
    if n_deact:
        parts.append(f"{n_deact}개 미사용 처리")
    if plan["block"]:
        parts.append(f"시스템 부서 제외: {', '.join(plan['block'])}")
    if failed:
        done = "부서 " + ", ".join(parts) + " · " if parts else ""
        _OD.set_flash(
            "error",
            f"{done}일부 부서 처리 실패: {', '.join(sorted(set(failed)))} — 다시 선택해 재시도하세요.",
        )
    else:
        msg = "부서를 " + ", ".join(parts) + "했습니다." if parts else "처리할 부서가 없습니다."
        _OD.set_flash("success" if (n_del or n_deact) else "warning", msg)
    st.rerun()


# ---------- 우측 패널: 선택한 부서의 운영단위 ----------
def _dept_options() -> tuple[list[str], dict]:
    """활성 부서 코드 목록(그룹순서→부서순서 정렬)과 표시명 맵. 중복명은 코드 병기."""
    depts = db.get_org_departments()
    depts = depts[depts["is_active"]].sort_values(
        ["group_sort_order", "department_group", "sort_order", "dept_code"]
    )
    name_dups: dict[str, int] = {}
    for _, r in depts.iterrows():
        name = str(r["dept_name"]).strip()
        name_dups[name] = name_dups.get(name, 0) + 1
    disp_of = {}
    for _, r in depts.iterrows():
        code = str(r["dept_code"]).strip()
        name = str(r["dept_name"]).strip()
        group = str(r.get("department_group") or "").strip()
        dept_label = name if name_dups.get(name, 0) == 1 else f"{name} ({code})"
        disp_of[code] = f"{group} › {dept_label}" if group else dept_label
    return list(disp_of), disp_of


def _render_unit_panel(refresh: bool, readiness: ReadinessState) -> tuple[pd.DataFrame | None, str]:
    codes, disp_of = _dept_options()
    if not codes:
        st.markdown("<div class='ms-panel'>운영단위</div>", unsafe_allow_html=True)
        ui.empty_state("등록된 부서가 없습니다. 왼쪽에서 부서를 먼저 등록하세요.", head="운영단위")
        return None, ""

    current = st.session_state.get("ou_dept")
    if current not in codes:
        current = codes[0]
    st.markdown(
        f"<div class='ms-panel'>운영단위 <small>— {escape(disp_of.get(current, current))}</small></div>",
        unsafe_allow_html=True,
    )
    show_flash(_OU)

    dept = st.selectbox(
        "대상 부서", codes, key="ou_dept",
        format_func=lambda c: disp_of.get(c, c), label_visibility="collapsed",
    )

    # 부서 전환·새로고침도 dirty 미저장 draft 를 무경고 폐기하지 않는다(§25 드릴다운).
    # 권위 컨텍스트 키는 persisted dept_code — 표시명·행번호를 키로 쓰지 않는다.
    decision = _OU.resolve_reload({"dept": dept}, refresh=refresh, dirty=_OU.is_dirty())
    if decision == RELOAD:
        st.session_state.pop(_OU.delete_plan_key, None)
        _load_units(dept)

    if _OU.has_pending_reload():
        gate = discard_confirm_bar(_OU)
        if gate == "discard":
            _OU.apply_pending_reload()
            st.session_state.pop(_OU.delete_plan_key, None)
            _load_units(dept)
            st.rerun()
        elif gate == "cancel":
            _OU.cancel_pending_reload()
            st.rerun()

    plan = st.session_state.get(_OU.delete_plan_key)
    if plan:
        _unit_confirm_bar(plan, dept, readiness)

    bar = st.container(key="org_unit__bar")
    rows = _OU.get_rows()
    spec = MasterGridSpec(
        page_id=_OU.page_id, columns=_UNIT_GRID_COLUMNS, order=_UNIT_COLS,
        col_config=_UNIT_COL_CONFIG, select_all=True,
        height=master_grid_height(len(rows)),
    )
    with st.container(key="org_unit__grid"):
        grid_df = render_master_grid(spec, _unit_display(rows), key=_OU.grid_key(suffix=dept))

    live = live_rows(grid_df)
    existing = live[live["_row_state"] == "existing"]
    sel_count = int((existing["_sel"].map(grid_bool)).sum()) if not existing.empty else 0
    new_cnt, changed_cnt = _dirty_counts(_OU, live, _UNIT_COLS)
    total = dirty_total(new_cnt, changed_cnt)
    _OU.set_dirty(total > 0)

    with bar:
        # §25: NOT_READY/PROBE_ERROR 면 우 패널의 행 추가·삭제·저장을 모두 비활성
        # (공통 bar can_write). 새로고침(조회)은 유지. 사유는 좌 패널과 동일 메시지.
        write_reason = readiness.message if not readiness.write_enabled else None
        master_action_bar(
            _OU, sel_count=sel_count, dirty_total=total,
            can_write=readiness.write_enabled, write_disabled_reason=write_reason,
        )
    count_strip(len(existing), new_cnt, changed_cnt, sel_count)
    return grid_df, dept


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


def _load_units(dept_code: str) -> None:
    """선택 부서의 운영단위(활성·비활성 모두)를 편집기에 적재한다."""
    df = db.get_org_teams(dept_code)
    df = df.sort_values(["sort_order", "team_code"]).reset_index(drop=True)
    order = pd.to_numeric(df["sort_order"], errors="coerce").fillna(0).astype("int64")
    rows = pd.DataFrame({
        "_row_id": "e:" + df["dept_code"].astype(str) + "|" + df["team_code"].astype(str),
        "_row_state": "existing",
        "_sel": False,
        "코드": df["team_code"].fillna("").astype("string"),
        "명칭": df["team_name"].fillna("").astype("string"),
        "유형": df["unit_type"].map(db.UNIT_TYPE_LABELS).fillna("교대").astype("string"),
        "표시순서": order.astype(str).astype("string"),
        "사용": df["is_active"].fillna(True).astype(bool),
    }) if not df.empty else pd.DataFrame(columns=_UNIT_ROW_COLS)

    rows = rows[_UNIT_ROW_COLS].reset_index(drop=True)
    _OU.set_rows(rows)
    _set_baseline(_OU, rows, _UNIT_COLS)
    st.session_state[_OU.key("loaded_dept")] = str(dept_code)
    _OU.bump_nonce()
    _OU.set_dirty(False)


def _add_unit_row(grid_df: pd.DataFrame | None, dept_code: str) -> None:
    if grid_df is None or not dept_code:
        _OU.set_flash("warning", "운영단위를 추가할 부서를 먼저 선택하세요.")
        st.rerun()
    readiness = _readiness()
    if not readiness.write_enabled:
        _OU.set_flash("error" if readiness.state is Readiness.PROBE_ERROR else "warning", readiness.message)
        st.rerun()
    live = live_rows(grid_df)
    orders = pd.to_numeric(live.get("표시순서"), errors="coerce").dropna()
    next_order = int(orders.max()) + 1 if len(orders) else 1
    row = {
        "_row_id": _OU.next_rid(), "_row_state": "new", "_sel": False,
        "코드": "", "명칭": "", "유형": "교대", "표시순서": str(next_order), "사용": True,
    }
    _OU.set_rows(pd.concat(
        [live[_UNIT_ROW_COLS], pd.DataFrame([row])], ignore_index=True,
    )[_UNIT_ROW_COLS])
    _OU.bump_nonce()
    st.rerun()


def _save_units(grid_df: pd.DataFrame | None, dept_code: str) -> None:
    """선택 부서의 운영단위 편집 결과 검증 후 (부서, 코드) 기준 upsert."""
    if grid_df is None or not str(dept_code).strip():
        st.error("운영단위를 저장할 부서를 먼저 선택하세요.")
        return
    readiness = _readiness()
    if not readiness.write_enabled:
        banner("danger" if readiness.state is Readiness.PROBE_ERROR else "warn", readiness.message)
        return
    live = live_rows(grid_df)
    store = db.get_org_teams()
    counts: dict[str, int] = {}

    def _validate():
        return _validate_units(live, dept_code)

    def _build(records):
        merged, dup, n_c, n_u, _n_d = db.upsert_records(
            store, records, set(), ["dept_code", "team_code"], "is_active", db.ORG_TEAM_COLUMNS,
        )
        counts["create"], counts["update"] = n_c, n_u
        errs: list[str] = []
        if dup:
            errs.append("운영단위 코드가 중복되었습니다: " + ", ".join(t for _d, t in dup))
        errs.extend(_unit_structure_errors(merged, dept_code))
        return merged, errs

    def _persist(merged, records):
        # 부분성공 원장 API — 우 패널은 자기 명령(운영단위)만 저장한다(좌와 별도 ledger).
        keys = [(r["dept_code"], r["team_code"]) for r in records if r.get("team_code")]
        try:
            report = db.save_org_teams_report(merged)
        except db.DATA_SOURCE_ERRORS as exc:
            return PersistResult.failure(_OU.page_id, keys, str(exc))
        return PersistResult(page_id=_OU.page_id, **report.to_persist_kwargs())

    outcome = run_save(_OU, validate=_validate, build_candidate=_build, persist=_persist)

    if outcome.status in ("invalid", "failed"):
        _error_banner("운영단위를 저장하지 못했습니다.", outcome.errors)
        return
    if outcome.status in ("partial", "unknown"):
        ledger_banner(outcome.result)
        return
    _load_units(dept_code)
    _OU.set_flash("success", f"운영단위를 저장했습니다. (신규 {counts.get('create', 0)} · 수정 {counts.get('update', 0)})")
    st.rerun()


def _validate_units(live: pd.DataFrame, dept_code: str):
    """표시 형태 → 저장 형태 변환 + 행별 검증. 완전히 빈 신규 행은 제외."""
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
            "unit_type": unit_type, "sort_order": order_val,
            "is_active": grid_bool(row.get("사용")),
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
            codes = ", ".join(group["team_code"].astype(str))
            errors.append(f"운영단위 명칭 '{name}'이(가) 중복되었습니다: {codes}")
    for order, group in sub.groupby("sort_order"):
        if len(group) > 1:
            codes = ", ".join(group["team_code"].astype(str))
            errors.append(f"표시순서 {order}이(가) 중복되었습니다: {codes}")
    return errors


def _plan_unit_delete(grid_df: pd.DataFrame | None, dept_code: str) -> None:
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
        _OU.set_flash("warning", "삭제할 기존 운영단위를 선택하세요.")
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
        lines.append(
            f"미사용 처리: {it['team_code']} — 사용자 {it['refs'].get('users', 0)}명 소속"
        )
    actionable = bool(plan["delete"] or plan["deactivate"]) and readiness.write_enabled
    result = confirm_bar(
        _OU, title="선택한 운영단위를 참조 확인 후 미사용/삭제 처리합니다.",
        lines=lines, confirm_label="삭제 실행", confirm_enabled=actionable, scope="del",
    )
    if result == "confirm":
        _execute_unit_delete(plan, dept_code)
    elif result == "cancel":
        st.session_state.pop(_OU.delete_plan_key, None)
        st.rerun()


def _execute_unit_delete(plan: dict, dept_code: str) -> None:
    """B4: 운영단위 삭제/비활성 write 예외를 controller 경계에서 잡아 성공/실패 구분.

    참조 있으면 soft(비활성)·미참조 hard(삭제) 계약 유지, 실패분은 재시도 가능 안내로 남긴다.
    """
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
    parts = []
    if n_del:
        parts.append(f"{n_del}개 삭제")
    if n_deact:
        parts.append(f"{n_deact}개 미사용 처리")
    if failed:
        done = "운영단위 " + ", ".join(parts) + " · " if parts else ""
        _OU.set_flash(
            "error",
            f"{done}일부 운영단위 처리 실패: {', '.join(sorted(set(failed)))} — 다시 선택해 재시도하세요.",
        )
    else:
        msg = "운영단위를 " + ", ".join(parts) + "했습니다." if parts else "처리할 운영단위가 없습니다."
        _OU.set_flash("success" if (n_del or n_deact) else "warning", msg)
    st.rerun()


# ---------- 행 상태 · dirty · 오류 배너 공통 헬퍼 ----------
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
    """(신규 행 수, 기존 변경 행 수) — §20 dirty_total 공식 입력.

    신규는 값이 하나라도 채워진 _row_state=='new' 행만, 기존 변경은 baseline 대비
    데이터 컬럼이 달라진 행(그룹 rename 포함)만 센다.
    """
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
