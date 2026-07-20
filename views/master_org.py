"""기준정보 — 조직 관리: 그룹·부서(좌) + 선택 부서의 운영단위(우) 통합 화면.

부서 관리·조 관리 메뉴는 모두 이 화면을 연다 (사이드바 메뉴 구조는 무변경).
연결 구조는 그룹 → 부서 → 운영단위이며, 그룹은 departments 의 컬럼
(department_group/group_sort_order)로 관리하고 운영단위는 teams 를 그대로 쓰되
unit_type(SHIFT=교대/GENERAL=일반)으로 교대조와 일반근무를 함께 담는다.

좌/우 패널은 각각 독립 저장 계약을 가진다 (od_* = 그룹·부서, ou_* = 운영단위):
  - 저장 오류를 영역별로 분리해 보여주고, 실패한 영역의 편집 초안은 유지한다.
  - 운영단위는 우측 상단에서 선택한 부서에 종속된다 — 부서 선택 없이 저장 불가.
행 상태 계약(_row_id/_row_state/_sel)과 붙여넣기/삭제 흐름은 기존 기준정보
화면(views/workspace 공용 helper)과 동일하다.

검증 규칙 (그룹 순서는 전역 유일):
  - 그룹순서(group_sort_order)는 그룹 간 중복 금지, 같은 그룹은 하나의 순서만.
  - 같은 그룹 안에서 부서순서(sort_order) 중복 금지. 부서코드는 전역 유일.
  - 같은 부서 안에서 운영단위 코드·명칭·표시순서 중복 금지, 유형은 교대/일반만.
  구조 검증은 화면에 보이는 행이 아니라 저장 후 전체(merged) 기준으로 수행해
  필터로 가려진 행과의 충돌도 차단한다.
"""
import pandas as pd
import streamlit as st

from modules import db, ui
from views import workspace
from views.workspace import grid_bool, selectable_master_grid, set_flash, show_flash

_STATUS = ["사용 중", "사용 안 함", "전체"]

# 좌측: 그룹·부서 (그룹이 앞에 붙어 그룹-부서가 한 행에서 이어져 보인다)
_DEPT_COLS = ["그룹명", "그룹순서", "부서코드", "부서명", "부서순서", "사용"]
_DEPT_ROW_COLS = ["_row_id", "_row_state", "_sel", *_DEPT_COLS]
_DEPT_GRID_COLUMNS = {
    "그룹명": "text", "그룹순서": "text", "부서코드": "text",
    "부서명": "text", "부서순서": "text", "사용": "bool",
}
_DEPT_COL_CONFIG = {
    "그룹명": {"flex": 1.1, "minWidth": 92, "cellClass": "md-c-left"},
    "그룹순서": {"flex": 0, "width": 76, "minWidth": 68, "maxWidth": 100, "cellClass": "md-c-center"},
    "부서코드": {"flex": 0, "width": 88, "minWidth": 78, "cellClass": "md-c-left"},
    "부서명": {"flex": 1.5, "minWidth": 112, "cellClass": "md-c-left"},
    "부서순서": {"flex": 0, "width": 76, "minWidth": 68, "maxWidth": 100, "cellClass": "md-c-center"},
    "사용": {"flex": 0, "width": 62, "minWidth": 56, "maxWidth": 84, "cellClass": "md-c-center"},
}
_SYSTEM_CODES = {"ADMIN"}

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
    },
    "표시순서": {"flex": 0, "width": 80, "minWidth": 68, "maxWidth": 104, "cellClass": "md-c-center"},
    "사용": {"flex": 0, "width": 62, "minWidth": 56, "maxWidth": 84, "cellClass": "md-c-center"},
}

# 유형 입력 정규화 — 화면 표시값(교대/일반)과 내부값(SHIFT/GENERAL) 모두 허용.
_UNIT_TYPE_OF = {
    "교대": "SHIFT", "일반": "GENERAL",
    "SHIFT": "SHIFT", "GENERAL": "GENERAL",
}


def render(user: dict) -> None:
    workspace.master_screen_head(
        "조직 관리",
        "그룹과 부서를 관리하고, 선택한 부서의 운영단위(교대조·일반근무)를 설정합니다.",
    )
    if not db.org_schema_ready():
        st.warning(
            "그룹·운영단위 확장 컬럼(migration 003)이 아직 적용되지 않았습니다. "
            "적용 전에는 그룹이 부서명 기준 기본값으로 표시되며, 이 화면의 저장은 차단됩니다."
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
        dept_grid = _render_dept_panel(params)
    with right:
        unit_grid, unit_dept = _render_unit_panel(refresh_unit)

    # 버튼 클릭 처리 (최신 grid 데이터 기준 — 양쪽 그리드 렌더 이후)
    if st.session_state.pop("od_save_req", False):
        _save_depts(dept_grid, params)
    if st.session_state.pop("od_del_req", False):
        _plan_dept_delete(dept_grid)
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


# ---------- 좌측 패널: 그룹·부서 ----------
def _render_dept_panel(params: dict) -> pd.DataFrame:
    st.markdown("<div class='ms-panel'>그룹·부서</div>", unsafe_allow_html=True)
    show_flash("org_dept")

    plan = st.session_state.get("od_plan")
    if plan:
        _dept_confirm_bar(plan, params)

    bar = st.container(key="od_bar")
    nonce = st.session_state.setdefault("od_nonce", 0)
    rows = st.session_state["od_rows"]
    with st.container(key="od_grid"):
        grid_df = selectable_master_grid(
            rows, key=f"od_grid_{nonce}", columns=_DEPT_GRID_COLUMNS, order=_DEPT_COLS,
            height=workspace.master_grid_height(len(rows)),
            col_config=_DEPT_COL_CONFIG, select_all_header=True,
        )

    live = _live(grid_df)
    existing = live[live["_row_state"] == "existing"]
    new_rows = live[live["_row_state"] != "existing"]
    sel_count = int((existing["_sel"].map(grid_bool)).sum()) if not existing.empty else 0
    workspace.master_count(len(existing), len(new_rows), sel_count)
    with bar:
        workspace.master_action_bar(sel_count, prefix="od")
    return grid_df


def _load_depts(q: dict) -> None:
    """조회 조건(사용 여부 + 검색어)으로 그룹·부서를 편집기에 적재한다."""
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
    df = df.sort_values(
        ["group_sort_order", "department_group", "sort_order", "dept_code"]
    ).reset_index(drop=True)

    g_order = pd.to_numeric(df["group_sort_order"], errors="coerce").fillna(0).astype("int64")
    d_order = pd.to_numeric(df["sort_order"], errors="coerce").fillna(0).astype("int64")
    rows = pd.DataFrame({
        "_row_id": "e:" + df["dept_code"].astype(str),
        "_row_state": "existing",
        "_sel": False,
        "그룹명": df["department_group"].fillna("").astype("string"),
        "그룹순서": g_order.astype(str).astype("string"),
        "부서코드": df["dept_code"].fillna("").astype("string"),
        "부서명": df["dept_name"].fillna("").astype("string"),
        "부서순서": d_order.astype(str).astype("string"),
        "사용": df["is_active"].fillna(True).astype(bool),
    }) if not df.empty else pd.DataFrame(columns=_DEPT_ROW_COLS)

    st.session_state["od_rows"] = rows[_DEPT_ROW_COLS].reset_index(drop=True)
    st.session_state["od_nonce"] = st.session_state.get("od_nonce", 0) + 1


def _add_dept_row(grid_df: pd.DataFrame) -> None:
    live = _live(grid_df)
    orders = pd.to_numeric(live.get("부서순서"), errors="coerce").dropna()
    next_order = int(orders.max()) + 1 if len(orders) else 1
    row = {
        "_row_id": _next_rid("od_rid"), "_row_state": "new", "_sel": False,
        "그룹명": "", "그룹순서": "", "부서코드": "", "부서명": "",
        "부서순서": str(next_order), "사용": True,
    }
    st.session_state["od_rows"] = pd.concat(
        [live[_DEPT_ROW_COLS], pd.DataFrame([row])], ignore_index=True,
    )[_DEPT_ROW_COLS]
    st.session_state["od_nonce"] = st.session_state.get("od_nonce", 0) + 1
    st.rerun()


def _save_depts(grid_df: pd.DataFrame, q: dict) -> None:
    """그룹·부서 편집 결과 검증 후 dept_code 기준 upsert (오류 시 전체 차단)."""
    live = _live(grid_df)
    store = db.get_org_departments()
    records, errors = _validate_departments(live, store)

    merged, dup, n_c, n_u, _n_d = db.upsert_records(
        store, records, set(), ["dept_code"], "is_active", db.ORG_DEPT_COLUMNS,
    )
    if dup:
        errors.append("부서코드가 중복되었습니다: " + ", ".join(k[0] for k in dup))
    # 구조 검증은 merged(저장 후 전체) 기준 — 필터로 가려진 그룹·부서와의 충돌 차단.
    errors.extend(_group_structure_errors(merged))
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
    set_flash("org_dept", "success", f"그룹·부서를 저장했습니다. (신규 {n_c} · 수정 {n_u})")
    st.rerun()


def _validate_departments(live: pd.DataFrame, store: pd.DataFrame):
    """표시 형태 → 저장 형태 변환 + 행별 검증. 완전히 빈 신규 행은 제외.

    그룹순서가 빈 행은 같은 그룹의 다른 행(편집 중 행 우선, 없으면 저장된 그룹)의
    순서를 이어받는다 — 기존 그룹에 부서를 추가할 때 순서를 다시 칠 필요가 없다.
    """
    parsed = []
    for i, (_, row) in enumerate(live.iterrows(), start=1):
        group = str(row.get("그룹명") or "").strip()
        g_raw = str(row.get("그룹순서") or "").strip()
        code = str(row.get("부서코드") or "").strip()
        name = str(row.get("부서명") or "").strip()
        d_raw = str(row.get("부서순서") or "").strip()
        if not any([group, code, name]):
            continue
        parsed.append((i, group, g_raw, code, name, d_raw, grid_bool(row.get("사용"))))

    # 그룹 → 순서: 편집 중 행의 명시값이 저장된 값보다 우선한다
    # (그룹 순서를 바꾸는 편집에서 빈 칸 상속이 새 값을 따라가도록).
    known_orders: dict[str, int] = {}
    for _i, group, g_raw, _c, _n, _d, _a in parsed:
        if group and g_raw:
            try:
                known_orders.setdefault(group, int(g_raw))
            except ValueError:
                pass
    if not store.empty:
        for _, r in store.iterrows():
            g = str(r["department_group"]).strip()
            if g:
                known_orders.setdefault(g, int(r["group_sort_order"]))

    records, errors = [], []
    for i, group, g_raw, code, name, d_raw, active in parsed:
        tag = f"{i}행" + (f"({code})" if code else "")
        if not code:
            errors.append(f"{i}행: 부서코드를 입력하세요.")
        if not name:
            errors.append(f"{tag}: 부서명을 입력하세요.")
        if not group:
            errors.append(f"{tag}: 그룹명을 입력하세요.")

        g_order = None
        if g_raw:
            try:
                g_order = int(g_raw)
            except ValueError:
                errors.append(f"{tag}: 그룹순서는 숫자여야 합니다.")
        elif group in known_orders:
            g_order = known_orders[group]
        elif group:
            errors.append(f"{tag}: 그룹순서를 입력하세요. (새 그룹 '{group}')")

        try:
            d_order = int(d_raw) if d_raw else None
        except ValueError:
            d_order = None
            errors.append(f"{tag}: 부서순서는 숫자여야 합니다.")
        if d_raw == "":
            errors.append(f"{tag}: 부서순서를 입력하세요.")

        records.append({
            "dept_code": code, "dept_name": name,
            "department_group": group,
            "group_sort_order": g_order if g_order is not None else 0,
            "sort_order": d_order if d_order is not None else 0,
            "is_active": active,
        })
    return records, errors


def _group_structure_errors(merged: pd.DataFrame) -> list[str]:
    """저장 후 전체 기준 구조 검증 — 그룹순서 전역 유일 + 그룹 내 부서순서 유일."""
    errors: list[str] = []
    if merged.empty:
        return errors
    frame = merged.copy()
    frame["department_group"] = frame["department_group"].astype(str).str.strip()
    frame["group_sort_order"] = pd.to_numeric(
        frame["group_sort_order"], errors="coerce"
    ).fillna(0).astype("int64")
    frame["sort_order"] = pd.to_numeric(frame["sort_order"], errors="coerce").fillna(0).astype("int64")

    # 같은 그룹은 하나의 그룹순서만 가진다.
    for group, sub in frame.groupby("department_group"):
        orders = sorted(set(sub["group_sort_order"]))
        if len(orders) > 1:
            errors.append(
                f"그룹 '{group}'의 그룹순서가 서로 다릅니다: "
                + ", ".join(str(o) for o in orders)
            )

    # 그룹이 다르면 그룹순서도 달라야 한다 (전역 유일).
    order_groups: dict[int, set] = {}
    for _, r in frame.iterrows():
        order_groups.setdefault(int(r["group_sort_order"]), set()).add(r["department_group"])
    for order, groups in sorted(order_groups.items()):
        if len(groups) > 1:
            errors.append(
                f"그룹순서 {order}이(가) 여러 그룹에 중복되었습니다: " + ", ".join(sorted(groups))
            )

    # 같은 그룹 안에서 부서순서 중복 금지.
    for (group, order), sub in frame.groupby(["department_group", "sort_order"]):
        if len(sub) > 1:
            codes = ", ".join(sub["dept_code"].astype(str))
            errors.append(f"그룹 '{group}'의 부서순서 {order}이(가) 중복되었습니다: {codes}")
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
        disp_of[code] = name if name_dups.get(name, 0) == 1 else f"{name} ({code})"
    return list(disp_of), disp_of


def _render_unit_panel(refresh: bool) -> tuple[pd.DataFrame | None, str]:
    st.markdown("<div class='ms-panel'>선택한 부서의 운영단위</div>", unsafe_allow_html=True)

    codes, disp_of = _dept_options()
    if not codes:
        ui.empty_state("등록된 부서가 없습니다. 왼쪽에서 부서를 먼저 등록하세요.", head="운영단위")
        return None, ""

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
