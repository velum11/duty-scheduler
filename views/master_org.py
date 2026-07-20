"""기준정보 — 조직 관리: 그룹·부서(좌) + 선택 부서의 운영단위(우) 통합 화면.

부서 관리·조 관리 메뉴는 모두 이 화면을 연다 (사이드바 메뉴 구조는 무변경).
연결 구조는 그룹 → 부서 → 운영단위이며, 그룹은 departments 의 컬럼
(department_group/group_sort_order)로 관리하고 운영단위는 teams 를 그대로 쓰되
unit_type(SHIFT=교대/GENERAL=일반)으로 교대조와 일반근무를 함께 담는다.

좌측 그리드는 DB 의 행별 반복 저장 구조를 그대로 노출하지 않는다:
  - 가상 그룹 부모 행(_row_state="group") 아래에 부서 자식 행이 붙는 계층 표시.
  - 그룹명·그룹순서는 그룹 부모 행에서 한 번만 편집한다 (부서 행에는 없음).
  - 부서 행의 '소속그룹'은 이동/배정용 선택 필드다 — 그룹값을 직접 타이핑하지 않는다.
  - 저장 시 그룹 부모의 이름·순서를 소속 부서 전체 payload 로 자동 전파한다.
    (필터로 화면에 안 보이는 같은 그룹 부서에도 전파해 그룹이 갈라지지 않게 한다.)
  - 부서순서(sort_order)는 그룹 안 보조 표시순서 — 중복을 저장 오류로 막지 않는다
    (같으면 부서코드 보조 정렬). 그룹 내 유일해야 하는 순서는 사용자 표시순서
    (users.display_order)이며 사용자 관리에서 관리한다.

좌/우 패널은 각각 독립 저장 계약을 가진다 (od_* = 그룹·부서, ou_* = 운영단위):
  - 저장 오류를 영역별로 분리해 보여주고, 실패한 영역의 편집 초안은 유지한다.
  - 운영단위는 우측 상단에서 선택한 부서에 종속된다 — 부서 선택 없이 저장 불가.
행 상태 계약(_row_id/_row_state/_sel)과 붙여넣기/삭제 흐름은 기존 기준정보
화면(views/workspace 공용 helper)과 동일하다.

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
from views import workspace
from views.workspace import grid_bool, selectable_master_grid, set_flash, show_flash

_STATUS = ["사용 중", "사용 안 함", "전체"]

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

_GROUP_ROW_CLASS_RULES = {"ms-group-row": "data._row_state == 'group'"}

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
    "표시순서": {"flex": 0, "width": 80, "minWidth": 68, "maxWidth": 104, "cellClass": "md-c-center"},
    "사용": {"flex": 0, "width": 62, "minWidth": 56, "maxWidth": 84, "cellClass": "md-c-center"},
}

# 유형 입력 정규화 — 화면 표시값(교대/일반)과 내부값(SHIFT/GENERAL) 모두 허용.
_UNIT_TYPE_OF = {
    "교대": "SHIFT", "일반": "GENERAL",
    "SHIFT": "SHIFT", "GENERAL": "GENERAL",
}

_ORG_PAGE_CSS = """
<style>
.org-flow { display:flex; align-items:center; gap:.55rem; margin:.1rem 0 .65rem; color:#6F6B63; font-size:.78rem; }
.org-flow-step { display:flex; align-items:center; gap:.42rem; padding:.38rem .62rem; background:#F7F5F1; border:1px solid #DED8CD; border-radius:7px; }
.org-flow-step b { display:inline-flex; align-items:center; justify-content:center; width:1.25rem; height:1.25rem; border-radius:50%; background:#1E3A6E; color:#FFF; font-size:.68rem; }
.org-flow-arrow { color:#C9A26B; font-weight:700; }
.st-key-od_panel, .st-key-ou_panel { background:#FFFFFF; border:1px solid #D8D2C7; border-radius:10px; padding:.75rem .8rem .65rem; box-shadow:0 1px 2px rgba(38,36,31,.04); }
.st-key-od_panel .ms-panel, .st-key-ou_panel .ms-panel { margin:0 0 .45rem; padding-bottom:.45rem; border-bottom:1px solid #E7E3DB; }
</style>
"""


def render(user: dict) -> None:
    workspace.master_screen_head(
        "조직 관리",
        "그룹과 부서를 관리하고, 선택한 부서의 운영단위(교대조·일반근무)를 설정합니다.",
    )
    st.markdown(_ORG_PAGE_CSS, unsafe_allow_html=True)
    org_ready = db.org_schema_ready()
    if not org_ready:
        st.warning("조직 확장(migration 003) 적용 전 — 조회만 가능하며 저장은 차단됩니다.")

    st.markdown(
        "<div class='org-flow'>"
        "<span class='org-flow-step'><b>1</b>그룹</span><span class='org-flow-arrow'>›</span>"
        "<span class='org-flow-step'><b>2</b>부서</span><span class='org-flow-arrow'>›</span>"
        "<span class='org-flow-step'><b>3</b>선택 부서의 운영단위</span>"
        "</div>",
        unsafe_allow_html=True,
    )

    refresh_dept = st.session_state.pop("od_refresh_req", False)
    refresh_unit = st.session_state.pop("ou_refresh_req", False)

    with st.container(key="ms_filter"):
        f1, f2, _sp = st.columns([1.4, 3.0, 5.6], vertical_alignment="bottom")
        active = f1.selectbox("사용 여부", _STATUS, key="og_active", label_visibility="collapsed")
        search = f2.text_input(
            "검색", key="og_search", placeholder="그룹·부서코드·부서명 검색",
            label_visibility="collapsed",
        )

    params = {"active": active, "search": search.strip()}
    if (
        refresh_dept
        or st.session_state.get("q_master_org") != params
        or "od_rows" not in st.session_state
    ):
        st.session_state["q_master_org"] = params
        st.session_state.pop("od_plan", None)
        _load_depts(params)

    left, right = st.columns([1.25, 1], gap="medium")
    with left:
        with st.container(key="od_panel"):
            dept_grid = _render_dept_panel(params, org_ready)
    with right:
        with st.container(key="ou_panel"):
            unit_grid, unit_dept = _render_unit_panel(refresh_unit, org_ready)

    # 버튼 클릭 처리 (최신 grid 데이터 기준 — 양쪽 그리드 렌더 이후)
    if st.session_state.pop("od_save_req", False):
        _save_depts(dept_grid, params)
    if st.session_state.pop("od_del_req", False):
        _plan_dept_delete(dept_grid)
    if st.session_state.pop("od_addg_req", False):
        _add_group_rows(dept_grid)
    if st.session_state.pop("od_add_req", False):
        _add_dept_row(dept_grid)
    if st.session_state.pop("ou_save_req", False):
        _save_units(unit_grid, unit_dept)
    if st.session_state.pop("ou_del_req", False):
        _plan_unit_delete(unit_grid, unit_dept)
    if st.session_state.pop("ou_add_req", False):
        _add_unit_row(unit_grid, unit_dept)

    changed = _normalize(dept_grid, "od_rows", "od_nonce", "od_rid", _DEPT_ROW_COLS)
    if unit_grid is not None:
        changed = _normalize(unit_grid, "ou_rows", "ou_nonce", "ou_rid", _UNIT_ROW_COLS) or changed
    if changed:
        st.rerun()


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


def _render_dept_panel(params: dict, org_ready: bool) -> pd.DataFrame:
    st.markdown("<div class='ms-panel'>그룹 · 부서 구조</div>", unsafe_allow_html=True)
    show_flash("org_dept")

    plan = st.session_state.get("od_plan")
    if plan:
        _dept_confirm_bar(plan, params)

    bar = st.container(key="od_bar")
    nonce = st.session_state.setdefault("od_nonce", 0)
    rows = st.session_state["od_rows"]

    # 소속그룹 선택지는 현재 그리드의 그룹 부모 행에서 도출 (신규 그룹 포함)
    col_config = {
        "그룹·부서명": {
            "flex": 1.6, "minWidth": 130, "cellClass": "md-c-left",
            "cellClassRules": {"ms-indent": "data._row_state != 'group'"},
            "cellRenderer": _ORG_NAME_RENDERER,
        },
        "순서": {"flex": 0, "width": 68, "minWidth": 60, "maxWidth": 92, "cellClass": "md-c-center"},
        "소속그룹": {
            "flex": 1, "minWidth": 104, "cellClass": "md-c-left",
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
    with st.container(key="od_grid"):
        grid_df = selectable_master_grid(
            rows, key=f"od_grid_{nonce}", columns=_DEPT_GRID_COLUMNS, order=_DEPT_COLS,
            height=workspace.master_grid_height(len(rows)),
            col_config=col_config, select_all_header=True,
            extra_grid_options={"rowClassRules": _GROUP_ROW_CLASS_RULES},
        )

    live = _live(grid_df)
    depts_live = live[live["_row_state"] != "group"]
    existing = depts_live[depts_live["_row_state"] == "existing"]
    new_rows = depts_live[depts_live["_row_state"] == "new"]
    sel_count = int((existing["_sel"].map(grid_bool)).sum()) if not existing.empty else 0
    n_groups = int((live["_row_state"] == "group").sum())
    workspace.master_count(len(existing), len(new_rows), sel_count)
    with bar:
        _org_dept_bar(sel_count)
    st.caption(f"그룹 {n_groups}개")
    return grid_df


def _org_dept_bar(sel_count: int) -> None:
    """좌측 작업 버튼: [＋ 그룹][＋ 부서][삭제][저장] · 우측 [새로고침]."""
    g, a, d, s, _sp, r = st.columns([1.4, 1.4, 1.2, 1.2, 2.2, 1.6], vertical_alignment="center")
    g.button("그룹", key="od_addg", icon=":material/create_new_folder:", width="stretch",
             help="새 그룹과 첫 부서 행을 함께 추가합니다 (빈 그룹은 저장할 수 없습니다)",
             on_click=lambda: st.session_state.update(od_addg_req=True))
    a.button("부서", key="od_add", icon=":material/add:", width="stretch",
             help="부서 행을 추가합니다 — 소속그룹을 선택하세요",
             on_click=lambda: st.session_state.update(od_add_req=True))
    d.button("삭제", key="od_del", icon=":material/delete:", width="stretch",
             disabled=int(sel_count) == 0,
             on_click=lambda: st.session_state.update(od_del_req=True))
    s.button("저장", key="od_save", type="primary", width="stretch",
             on_click=lambda: st.session_state.update(od_save_req=True))
    r.button("새로고침", key="od_refresh", icon=":material/refresh:", width="stretch",
             on_click=lambda: st.session_state.update(od_refresh_req=True))


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
    st.session_state["od_rows"] = build_org_rows(df)
    st.session_state["od_nonce"] = st.session_state.get("od_nonce", 0) + 1


def _add_group_rows(grid_df: pd.DataFrame) -> None:
    """새 가상 그룹 부모 + 첫 부서 자식 행을 함께 추가한다 (빈 그룹 저장 불가 안내)."""
    live = _live(grid_df)
    n = st.session_state.get("od_gid", 0) + 1
    st.session_state["od_gid"] = n
    label = _NEW_GROUP_LABEL.format(n=n)
    group_row = {
        "_row_id": f"gn:{n}", "_row_state": "group", "_sel": False,
        "그룹·부서명": "", "순서": "", "소속그룹": "", "부서코드": "", "사용": True,
    }
    dept_row = {
        "_row_id": _next_rid("od_rid"), "_row_state": "new", "_sel": False,
        "그룹·부서명": "", "순서": "1", "소속그룹": label, "부서코드": "", "사용": True,
    }
    st.session_state["od_rows"] = pd.concat(
        [live[_DEPT_ROW_COLS], pd.DataFrame([group_row, dept_row])], ignore_index=True,
    )[_DEPT_ROW_COLS]
    st.session_state["od_nonce"] = st.session_state.get("od_nonce", 0) + 1
    st.rerun()


def _add_dept_row(grid_df: pd.DataFrame) -> None:
    """신규 부서 자식 행 추가 — 소속그룹은 selectbox 로 선택한다."""
    live = _live(grid_df)
    labels = _group_labels(live)
    row = {
        "_row_id": _next_rid("od_rid"), "_row_state": "new", "_sel": False,
        "그룹·부서명": "", "순서": "", "소속그룹": labels[0] if len(labels) == 1 else "",
        "부서코드": "", "사용": True,
    }
    st.session_state["od_rows"] = pd.concat(
        [live[_DEPT_ROW_COLS], pd.DataFrame([row])], ignore_index=True,
    )[_DEPT_ROW_COLS]
    st.session_state["od_nonce"] = st.session_state.get("od_nonce", 0) + 1
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
    """그룹·부서 편집 결과 검증 후 dept_code 기준 batch upsert (오류 시 전체 차단)."""
    live = _live(grid_df)
    store = db.get_org_departments()
    records, errors = parse_org_grid(live, store)

    merged, dup, n_c, n_u, _n_d = db.upsert_records(
        store, records, set(), ["dept_code"], "is_active", db.ORG_DEPT_COLUMNS,
    )
    if dup:
        errors.append("부서코드가 중복되었습니다: " + ", ".join(k[0] for k in dup))
    # 구조 검증은 merged(저장 후 전체) 기준 — 필터로 가려진 그룹·부서와의 충돌 차단.
    errors.extend(_group_structure_errors(merged))
    # 변경 후 그룹 구조 기준 활성 사용자 표시순서 충돌 검증 (그룹 병합 사전 차단).
    order_errors = db.display_order_conflicts(db.get_users(), db.dept_group_map(merged))
    if order_errors:
        errors.extend(order_errors)
        errors.append("→ 사용자 관리에서 해당 사용자의 표시순서를 먼저 조정한 뒤 다시 저장하세요.")
    if errors:
        st.error("그룹·부서를 저장하지 못했습니다.\n\n- " + "\n- ".join(errors))
        return

    try:
        db.save_org_departments(merged)
    except db.DATA_SOURCE_ERRORS as exc:
        st.error(str(exc))
        return
    _load_depts(q)
    st.session_state.pop("ou_loaded_dept", None)  # 부서명·그룹 변경 반영 위해 우측 재적재
    set_flash("org_dept", "success", f"그룹·부서를 저장했습니다. (부서 {len(records)}건 반영 — 신규 {n_c} · 수정 {n_u})")
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
    live = _live(grid_df)
    sel = live[(live["_row_state"] == "existing") & live["_sel"].map(grid_bool)]
    codes = sorted({str(c).strip() for c in sel["부서코드"] if str(c).strip()})
    if not codes:
        set_flash("org_dept", "warning", "삭제할 기존 부서를 선택하세요.")
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
    st.session_state["od_plan"] = plan
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


def _dept_confirm_bar(plan: dict, params: dict) -> None:
    lines = []
    if plan["delete"]:
        lines.append("삭제 가능: " + ", ".join(plan["delete"]))
    for item in plan["deactivate"]:
        lines.append(f"미사용 처리: {item['code']} — {_ref_text(item['refs'])} 참조 중")
    for code in plan["block"]:
        lines.append(f"처리 불가: {code} — 시스템 필수 부서")
    st.warning("선택한 부서를 다음과 같이 처리합니다.\n\n- " + "\n- ".join(lines))

    c1, c2, _sp = st.columns([1.2, 1.0, 2.6], vertical_alignment="center")
    actionable = bool(plan["delete"] or plan["deactivate"])
    if c1.button("실행", key="od_del_ok", type="primary", width="stretch", disabled=not actionable):
        _execute_dept_delete(plan, params)
    if c2.button("취소", key="od_del_cancel", width="stretch"):
        st.session_state.pop("od_plan", None)
        st.rerun()


def _execute_dept_delete(plan: dict, params: dict) -> None:
    """참조 없는 부서는 물리 삭제, 참조 중인 부서는 미사용 처리 (기존 정책 유지)."""
    n_del = 0
    for code in plan["delete"]:
        db.delete_department(code)
        n_del += 1

    deactivate_codes = [item["code"] for item in plan["deactivate"]]
    n_deact = 0
    if deactivate_codes:
        store = db.get_org_departments().copy()
        mask = store["dept_code"].astype(str).isin(deactivate_codes)
        n_deact = int(mask.sum())
        store.loc[mask, "is_active"] = False
        db.save_org_departments(store[db.ORG_DEPT_COLUMNS])

    st.session_state.pop("od_plan", None)
    _load_depts(params)
    st.session_state.pop("ou_loaded_dept", None)

    parts = []
    if n_del:
        parts.append(f"{n_del}개 삭제")
    if n_deact:
        parts.append(f"{n_deact}개 미사용 처리")
    if plan["block"]:
        parts.append(f"시스템 부서 제외: {', '.join(plan['block'])}")
    msg = "부서를 " + ", ".join(parts) + "했습니다." if parts else "처리할 부서가 없습니다."
    set_flash("org_dept", "success" if (n_del or n_deact) else "warning", msg)
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


def _render_unit_panel(refresh: bool, org_ready: bool) -> tuple[pd.DataFrame | None, str]:
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

    dept = st.selectbox(
        "대상 부서", codes, key="ou_dept",
        format_func=lambda c: disp_of.get(c, c), label_visibility="collapsed",
    )
    if refresh or st.session_state.get("ou_loaded_dept") != dept or "ou_rows" not in st.session_state:
        st.session_state["ou_loaded_dept"] = dept
        st.session_state.pop("ou_plan", None)
        _load_units(dept)

    show_flash("org_unit")
    plan = st.session_state.get("ou_plan")
    if plan:
        _unit_confirm_bar(plan, dept)

    bar = st.container(key="ou_bar")
    nonce = st.session_state.setdefault("ou_nonce", 0)
    rows = st.session_state["ou_rows"]
    with st.container(key="ou_grid"):
        grid_df = selectable_master_grid(
            rows, key=f"ou_grid_{dept}_{nonce}", columns=_UNIT_GRID_COLUMNS, order=_UNIT_COLS,
            height=workspace.master_grid_height(len(rows)),
            col_config=_UNIT_COL_CONFIG, select_all_header=True,
        )

    live = _live(grid_df)
    existing = live[live["_row_state"] == "existing"]
    new_rows = live[live["_row_state"] != "existing"]
    sel_count = int((existing["_sel"].map(grid_bool)).sum()) if not existing.empty else 0
    workspace.master_count(len(existing), len(new_rows), sel_count)
    with bar:
        workspace.master_action_bar(sel_count, prefix="ou")
    return grid_df, dept


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

    st.session_state["ou_rows"] = rows[_UNIT_ROW_COLS].reset_index(drop=True)
    st.session_state["ou_nonce"] = st.session_state.get("ou_nonce", 0) + 1


def _add_unit_row(grid_df: pd.DataFrame | None, dept_code: str) -> None:
    if grid_df is None or not dept_code:
        set_flash("org_unit", "warning", "운영단위를 추가할 부서를 먼저 선택하세요.")
        st.rerun()
    live = _live(grid_df)
    orders = pd.to_numeric(live.get("표시순서"), errors="coerce").dropna()
    next_order = int(orders.max()) + 1 if len(orders) else 1
    row = {
        "_row_id": _next_rid("ou_rid"), "_row_state": "new", "_sel": False,
        "코드": "", "명칭": "", "유형": "교대", "표시순서": str(next_order), "사용": True,
    }
    st.session_state["ou_rows"] = pd.concat(
        [live[_UNIT_ROW_COLS], pd.DataFrame([row])], ignore_index=True,
    )[_UNIT_ROW_COLS]
    st.session_state["ou_nonce"] = st.session_state.get("ou_nonce", 0) + 1
    st.rerun()


def _save_units(grid_df: pd.DataFrame | None, dept_code: str) -> None:
    """선택 부서의 운영단위 편집 결과 검증 후 (부서, 코드) 기준 upsert."""
    if grid_df is None or not str(dept_code).strip():
        st.error("운영단위를 저장할 부서를 먼저 선택하세요.")
        return
    live = _live(grid_df)
    records, errors = _validate_units(live, dept_code)

    store = db.get_org_teams()
    merged, dup, n_c, n_u, _n_d = db.upsert_records(
        store, records, set(), ["dept_code", "team_code"], "is_active", db.ORG_TEAM_COLUMNS,
    )
    if dup:
        errors.append("운영단위 코드가 중복되었습니다: " + ", ".join(t for _d, t in dup))
    errors.extend(_unit_structure_errors(merged, dept_code))
    if errors:
        st.error("운영단위를 저장하지 못했습니다.\n\n- " + "\n- ".join(errors))
        return

    try:
        db.save_org_teams(merged)
    except db.DATA_SOURCE_ERRORS as exc:
        st.error(str(exc))
        return
    _load_units(dept_code)
    set_flash("org_unit", "success", f"운영단위를 저장했습니다. (신규 {n_c} · 수정 {n_u})")
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
    live = _live(grid_df)
    sel = live[(live["_row_state"] == "existing") & live["_sel"].map(grid_bool)]
    keys = [str(r["_row_id"])[2:] for _, r in sel.iterrows()]  # _row_id = "e:{dept}|{team}"
    if not keys:
        set_flash("org_unit", "warning", "삭제할 기존 운영단위를 선택하세요.")
        st.rerun()

    plan = {"delete": [], "deactivate": []}
    for key in keys:
        dc, tc = key.split("|", 1) if "|" in key else (dept_code, key)
        refs = db.team_reference_counts(dc, tc)
        item = {"dept_code": dc, "team_code": tc, "refs": refs}
        (plan["deactivate"] if sum(refs.values()) > 0 else plan["delete"]).append(item)
    st.session_state["ou_plan"] = plan
    st.rerun()


def _unit_confirm_bar(plan: dict, dept_code: str) -> None:
    lines = []
    for it in plan["delete"]:
        lines.append(f"삭제 가능: {it['team_code']}")
    for it in plan["deactivate"]:
        lines.append(
            f"미사용 처리: {it['team_code']} — 사용자 {it['refs'].get('users', 0)}명 소속"
        )
    st.warning("선택한 운영단위를 다음과 같이 처리합니다.\n\n- " + "\n- ".join(lines))
    c1, c2, _sp = st.columns([1.2, 1.0, 2.6], vertical_alignment="center")
    if c1.button("실행", key="ou_del_ok", type="primary", width="stretch"):
        _execute_unit_delete(plan, dept_code)
    if c2.button("취소", key="ou_del_cancel", width="stretch"):
        st.session_state.pop("ou_plan", None)
        st.rerun()


def _execute_unit_delete(plan: dict, dept_code: str) -> None:
    n_del = 0
    for it in plan["delete"]:
        db.delete_team(it["dept_code"], it["team_code"])
        n_del += 1
    deact = plan["deactivate"]
    n_deact = 0
    if deact:
        store = db.get_org_teams().copy()
        for it in deact:
            mask = (
                (store["dept_code"].astype(str) == it["dept_code"])
                & (store["team_code"].astype(str) == it["team_code"])
            )
            n_deact += int(mask.sum())
            store.loc[mask, "is_active"] = False
        db.save_org_teams(store[db.ORG_TEAM_COLUMNS])
    st.session_state.pop("ou_plan", None)
    _load_units(dept_code)
    parts = []
    if n_del:
        parts.append(f"{n_del}개 삭제")
    if n_deact:
        parts.append(f"{n_deact}개 미사용 처리")
    msg = "운영단위를 " + ", ".join(parts) + "했습니다." if parts else "처리할 운영단위가 없습니다."
    set_flash("org_unit", "success" if (n_del or n_deact) else "warning", msg)
    st.rerun()


# ---------- 행 상태 공통 헬퍼 (기존 기준정보 화면과 동일 계약) ----------
def _live(grid_df: pd.DataFrame) -> pd.DataFrame:
    if "_removed" not in grid_df.columns:
        return grid_df
    return grid_df[grid_df["_removed"].fillna("").astype(str).str.strip() != "1"]


def _next_rid(counter_key: str) -> str:
    n = st.session_state.get(counter_key, 0) + 1
    st.session_state[counter_key] = n
    return f"n:{n}"


def _normalize(grid_df: pd.DataFrame, rows_key: str, nonce_key: str, rid_key: str, row_cols) -> bool:
    """붙여넣기로 생긴 무명 신규 행에 _row_id/_row_state 부여 + − 제거 행 반영.

    구조 변경이 있으면 Python 권위 상태(rows_key)를 갱신하고 True 를 반환한다."""
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
        live.at[idx, "_row_id"] = _next_rid(rid_key)
        live.at[idx, "_row_state"] = "new"
        live.at[idx, "_sel"] = False
    live["_row_state"] = live["_row_state"].fillna("").astype(str).replace("", "new")
    st.session_state[rows_key] = live[list(row_cols)].reset_index(drop=True)
    st.session_state[nonce_key] = st.session_state.get(nonce_key, 0) + 1
    return True
