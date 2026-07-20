"""기준정보 — 사용자 관리: 부서·조·근무형태 관리와 동일한 스프레드시트형 편집 화면.

행 상태 계약(_row_id/_row_state/_sel)으로 기존 저장 행과 미저장 신규 행을 분리한다.
  - 기존 행: 첫 열 선택 체크박스 → 상단 [삭제] 대상
  - 신규 행: 첫 열 − 제거 버튼 → 즉시 개별 제거(확인·DB 작업 없음)
목록에서 직접 입력·수정하고 [저장]으로 일괄 반영한다(자동 저장 없음). Excel 의 여러
행·열(탭/줄바꿈)을 그대로 붙여넣을 수 있고, [행 추가]로 신규 사용자를 추가한다.
사용자는 물리 삭제하지 않고 재직 여부(is_active)로 관리한다([삭제]=퇴직/미사용 처리).

화면 표시 원칙:
- 부서는 부서명(중복 시 코드 병기)으로 표시하고 저장 시 dept_code 로 변환한다.
- 조는 조코드가 아니라 조명(team_name)으로 표시하고, 저장 시 (부서, 조명)을
  team_code 로 변환한다. 조명은 관계 키가 아니다.
- 권한은 관리자/조장/조원으로 표시하고, 저장 시 ADMIN/MANAGER/USER 로 변환한다.
  DB 저장값과 권한 분기 코드는 기존 값을 유지한다.
"""
import pandas as pd
import streamlit as st

from modules import db
from views import workspace
from views.workspace import ALL, grid_bool, selectable_master_grid, set_flash, show_flash

# 화면 표시 라벨 ↔ 저장 코드 매핑 (DB 값은 ADMIN/MANAGER/USER 유지)
_ROLE_TO_LABEL = {"ADMIN": "관리자", "MANAGER": "조장", "USER": "조원"}
_LABEL_TO_ROLE = {label: role for role, label in _ROLE_TO_LABEL.items()}

_STATUS = ["전체", "재직", "퇴직"]
# 표시순서: 부서그룹 안에서의 직원 출력 순서 (users.display_order, 빈 값=미지정).
# 같은 부서그룹의 활성 사용자끼리 중복 금지 — 부서가 아니라 그룹 기준으로 검증한다.
_USER_COLS = ["사번", "성명", "부서", "조", "직급", "권한", "표시순서", "재직"]
_ROW_COLS = ["_row_id", "_row_state", "_sel", *_USER_COLS]
_GRID_COLUMNS = {
    "사번": "text", "성명": "text", "부서": "text", "조": "text",
    "직급": "text", "권한": "text", "표시순서": "text", "재직": "bool",
}


def _dept_labels(dept_names: dict[str, str]) -> dict[str, str]:
    """부서명 중복에도 안전한 편집기 표시값(code -> label)."""
    counts = pd.Series(list(dept_names.values())).value_counts()
    return {
        code: (name if counts.get(name, 0) == 1 else f"{name} ({code})")
        for code, name in dept_names.items()
    }


def _dept_resolver(dept_names: dict[str, str]) -> dict[str, str]:
    """입력값 -> 부서코드. 표시 라벨/코드를 허용하고, 유일한 부서명도 허용한다."""
    resolver: dict[str, str] = {}
    for code, label in _dept_labels(dept_names).items():
        resolver[label] = code
        resolver[str(code)] = code
    name_counts = pd.Series(list(dept_names.values())).value_counts()
    for code, name in dept_names.items():
        if name_counts.get(name, 0) == 1:
            resolver.setdefault(str(name), code)
    return resolver


def _team_maps(teams: pd.DataFrame):
    """(부서코드, 입력값) -> 조코드 해석기와 (부서코드, 조코드) -> 조명 맵.

    입력값은 조명(표시값) 우선, 조코드도 허용한다. 같은 부서에 조명이 중복되면
    해당 조명은 매핑하지 않아(None) 잘못된 조로 저장되는 것을 막는다.
    """
    resolve: dict[tuple[str, str], str | None] = {}
    display: dict[tuple[str, str], str] = {}
    for _, row in teams.iterrows():
        dept = str(row["dept_code"])
        code = str(row["team_code"])
        name = str(row["team_name"])
        display[(dept, code)] = name
        name_key = (dept, name)
        resolve[name_key] = None if name_key in resolve else code
        resolve.setdefault((dept, code), code)
    return resolve, display


def _order_text(value) -> str:
    """저장소 display_order → 편집기 표시 문자열 ('' = 미지정)."""
    try:
        order = db.normalize_display_order(value)
    except (TypeError, ValueError):
        return ""
    return "" if order is None else str(order)


def _role_resolver() -> dict[str, str]:
    """입력값 -> 권한 코드. 한글 라벨과 기존 코드(대소문자 무관)를 허용한다."""
    resolver = dict(_LABEL_TO_ROLE)
    for role in _ROLE_TO_LABEL:
        resolver[role] = role
        resolver[role.lower()] = role
    return resolver


def render(user: dict) -> None:
    depts = db.get_departments()
    teams = db.get_teams()
    dept_names = {str(r["dept_code"]): str(r["dept_name"]) for _, r in depts.iterrows()}
    team_resolve, team_display = _team_maps(teams)
    dept_labels = _dept_labels(dept_names)
    team_names = sorted({str(r["team_name"]) for _, r in teams.iterrows()})

    workspace.master_screen_head(
        "사용자 관리", "사번·소속·권한을 표에서 직접 편집하고 [저장]으로 일괄 반영합니다.",
    )

    refresh = st.session_state.pop("ms_refresh_req", False)
    with st.container(key="ms_filter"):
        f1, f2, f3, f4 = st.columns([1.2, 1.6, 1.4, 3.0], vertical_alignment="bottom")
        active = f1.selectbox("재직 여부", _STATUS, key="mu_active", label_visibility="collapsed")
        dept = f2.selectbox(
            "부서", [ALL] + list(dept_names), format_func=lambda c: dept_names.get(c, c),
            key="mu_dept", label_visibility="collapsed",
        )
        role_opts = [ALL] + list(_ROLE_TO_LABEL)
        role = f3.selectbox(
            "권한", role_opts, format_func=lambda c: _ROLE_TO_LABEL.get(c, "전체 권한" if c == ALL else c),
            key="mu_role", label_visibility="collapsed",
        )
        search = f4.text_input(
            "검색", key="mu_search", placeholder="사번·성명 검색", label_visibility="collapsed",
        )

    params = {"active": active, "dept": dept, "role": role, "search": search.strip()}
    if refresh or st.session_state.get("q_master_users") != params or "mu_rows" not in st.session_state:
        st.session_state["q_master_users"] = params
        st.session_state.pop("mu_del_plan", None)
        _load_editor(params, dept_names, team_display)

    show_flash("master_users")

    plan = st.session_state.get("mu_del_plan")
    if plan:
        _confirm_bar(plan, params, dept_names, team_display)

    bar = st.container(key="ms_bar")

    nonce = st.session_state.setdefault("mu_nonce", 0)
    col_config = {
        "사번": {"width": 128, "minWidth": 104, "cellClass": "md-c-left"},
        "성명": {"width": 104, "minWidth": 84, "cellClass": "md-c-left"},
        "부서": {"flex": 1, "minWidth": 150, "cellClass": "md-c-left",
                "cellEditor": "agSelectCellEditor",
                "cellEditorParams": {"values": list(dept_labels.values())}},
        "조": {"width": 120, "minWidth": 92, "cellClass": "md-c-left",
              "cellEditor": "agSelectCellEditor",
              "cellEditorParams": {"values": [""] + team_names}},
        "직급": {"width": 92, "minWidth": 72, "cellClass": "md-c-left"},
        "권한": {"width": 96, "minWidth": 80, "cellClass": "md-c-center",
                "cellEditor": "agSelectCellEditor",
                "cellEditorParams": {"values": list(_LABEL_TO_ROLE)}},
        "표시순서": {"width": 84, "minWidth": 70, "maxWidth": 108, "cellClass": "md-c-center"},
        "재직": {"width": 74, "minWidth": 64, "cellClass": "md-c-center"},
    }
    rows = st.session_state["mu_rows"]
    with st.container(key="ms_grid"):
        grid_df = selectable_master_grid(
            rows, key=f"mu_grid_{nonce}", columns=_GRID_COLUMNS, order=_USER_COLS,
            height=workspace.master_grid_height(len(rows)),
            col_config=col_config, select_all_header=True,
        )

    live = _live(grid_df)
    existing = live[live["_row_state"] == "existing"]
    new_rows = live[live["_row_state"] != "existing"]
    sel_count = int((existing["_sel"].map(grid_bool)).sum()) if not existing.empty else 0
    workspace.master_count(len(existing), len(new_rows), sel_count)
    if not db.org_schema_ready():
        st.caption(
            "표시순서 컬럼(users.display_order, migration 003)이 아직 적용되지 않아 "
            "표시순서를 입력하면 저장이 차단됩니다 — supabase/migrations/003_org_structure.sql 적용 후 사용하세요."
        )

    with bar:
        workspace.master_action_bar(sel_count)

    if st.session_state.pop("ms_save_req", False):
        _save(grid_df, params, dept_names, team_resolve, team_display)
    if st.session_state.pop("ms_del_req", False):
        _handle_delete(grid_df)
    if st.session_state.pop("ms_add_req", False):
        _add_row(grid_df)
    if _normalize(grid_df):
        st.rerun()


# ---------- 행 상태 헬퍼 (부서 관리와 동일 계약) ----------
def _live(grid_df: pd.DataFrame) -> pd.DataFrame:
    if "_removed" not in grid_df.columns:
        return grid_df
    return grid_df[grid_df["_removed"].fillna("").astype(str).str.strip() != "1"]


def _next_rid() -> str:
    n = st.session_state.get("mu_rid", 0) + 1
    st.session_state["mu_rid"] = n
    return f"n:{n}"


def _new_row() -> dict:
    row = {"_row_id": _next_rid(), "_row_state": "new", "_sel": False}
    for c in _USER_COLS:
        row[c] = True if c == "재직" else ""
    return row


def _add_row(grid_df: pd.DataFrame) -> None:
    live = _live(grid_df)
    st.session_state["mu_rows"] = pd.concat(
        [live[_ROW_COLS], pd.DataFrame([_new_row()])], ignore_index=True,
    )[_ROW_COLS]
    st.session_state["mu_nonce"] = st.session_state.get("mu_nonce", 0) + 1
    st.rerun()


def _normalize(grid_df: pd.DataFrame) -> bool:
    if grid_df is None or grid_df.empty or "_row_id" not in grid_df.columns:
        return False
    removed = grid_df["_removed"].fillna("").astype(str).str.strip() == "1" if "_removed" in grid_df else pd.Series(False, index=grid_df.index)
    live = grid_df[~removed].copy()
    rid = live["_row_id"].fillna("").astype(str).str.strip()
    needs_id = rid == ""
    changed = bool(removed.any() or needs_id.any())
    if not changed:
        return False
    live["_row_id"] = rid
    for idx in live.index[needs_id]:
        live.at[idx, "_row_id"] = _next_rid()
        live.at[idx, "_row_state"] = "new"
        live.at[idx, "_sel"] = False
    live["_row_state"] = live["_row_state"].fillna("").astype(str).replace("", "new")
    st.session_state["mu_rows"] = live[_ROW_COLS].reset_index(drop=True)
    st.session_state["mu_nonce"] = st.session_state.get("mu_nonce", 0) + 1
    return True


# ---------- 삭제 (기존 저장 행 전용 — 사용자는 소프트 삭제) ----------
def _handle_delete(grid_df: pd.DataFrame) -> None:
    live = _live(grid_df)
    sel = live[(live["_row_state"] == "existing") & live["_sel"].map(grid_bool)]
    emps = sorted({str(r["_row_id"])[2:] for _, r in sel.iterrows() if str(r["_row_id"]).startswith("e:")})
    if not emps:
        set_flash("master_users", "warning", "퇴직 처리할 기존 사용자를 선택하세요.")
        st.rerun()
    st.session_state["mu_del_plan"] = emps
    st.rerun()


def _confirm_bar(emps: list, params: dict, dept_names: dict, team_display: dict) -> None:
    st.warning(
        f"선택한 {len(emps)}명을 퇴직(미사용) 처리합니다. 물리 삭제가 아니라 재직 상태를 "
        f"해제하며, 과거 근무표는 그대로 유지됩니다.\n\n- " + ", ".join(emps)
    )
    c1, c2, _sp = st.columns([1.4, 1.0, 6], vertical_alignment="center")
    if c1.button("실행", key="mu_del_ok", type="primary", width="stretch"):
        _execute_delete(emps, params, dept_names, team_display)
    if c2.button("취소", key="mu_del_cancel", width="stretch"):
        st.session_state.pop("mu_del_plan", None)
        st.rerun()


def _execute_delete(emps: list, params: dict, dept_names: dict, team_display: dict) -> None:
    store = db.get_users().copy()
    mask = store["emp_no"].astype(str).isin(emps)
    n = int(mask.sum())
    store.loc[mask, "is_active"] = False
    db.save_users(store[db.USER_COLUMNS])
    st.session_state.pop("mu_del_plan", None)
    _load_editor(params, dept_names, team_display)
    set_flash(
        "master_users", "success" if n else "warning",
        f"{n}명을 퇴직(미사용) 처리했습니다." if n else "처리할 사용자가 없습니다.",
    )
    st.rerun()


# ---------- 적재 / 저장 ----------
def _load_editor(q: dict, dept_names: dict, team_display: dict, source: pd.DataFrame | None = None) -> None:
    """조회 조건(재직/부서/권한/검색)으로 대상 사용자를 편집기에 적재한다(모두 기존 행)."""
    source = db.get_users() if source is None else source
    df = source.copy()
    if q["active"] == "재직":
        df = df[df["is_active"]]
    elif q["active"] == "퇴직":
        df = df[~df["is_active"].astype(bool)]
    if q["dept"] != ALL:
        df = df[df["dept_code"] == q["dept"]]
    if q["role"] != ALL:
        df = df[df["role"].astype(str).str.upper() == q["role"]]
    term = str(q.get("search", "")).strip()
    if term:
        hit = (
            df["emp_no"].astype(str).str.contains(term, case=False, na=False, regex=False)
            | df["name"].astype(str).str.contains(term, case=False, na=False, regex=False)
        )
        df = df[hit]
    df = df.sort_values(["dept_code", "team_code", "emp_no"]).reset_index(drop=True)

    labels = _dept_labels(dept_names)
    if df.empty:
        rows = pd.DataFrame(columns=_ROW_COLS)
    else:
        rows = pd.DataFrame({
            "_row_id": "e:" + df["emp_no"].astype(str),
            "_row_state": "existing",
            "_sel": False,
            "사번": df["emp_no"].fillna("").astype("string"),
            "성명": df["name"].fillna("").astype("string"),
            "부서": df["dept_code"].map(labels).fillna("").astype("string"),
            "조": [team_display.get((str(d), str(t)), str(t or "")) for d, t in zip(df["dept_code"], df["team_code"])],
            "직급": df["position"].fillna("").astype("string"),
            "권한": df["role"].map(_ROLE_TO_LABEL).fillna("").astype("string"),
            "표시순서": [_order_text(v) for v in df.get("display_order", pd.Series([None] * len(df)))],
            "재직": df["is_active"].fillna(True).astype(bool),
        })[_ROW_COLS]
    st.session_state["mu_rows"] = rows[_ROW_COLS].reset_index(drop=True)
    st.session_state["mu_nonce"] = st.session_state.get("mu_nonce", 0) + 1


def _save(grid_df, q, dept_names, team_resolve, team_display) -> None:
    """편집 결과를 검증하고 사번 기준 upsert 로 병합해 저장한다(오류 시 전체 차단).

    필터로 보이지 않는 기존 사용자를 자동 퇴직 처리하지 않는다(loaded_keys 비움).
    """
    live = _live(grid_df)
    records, errors = _validate(live, _dept_resolver(dept_names), team_resolve)

    if not db.org_schema_ready():
        ordered = [
            str(record.get("emp_no") or "(사번 없음)")
            for record in records
            if record.get("display_order") is not None
        ]
        if ordered:
            errors.append(
                "migration 003 미적용 상태에서는 표시순서를 저장할 수 없습니다: "
                + ", ".join(ordered)
            )

    store = db.get_users()
    merged, dup, n_c, n_u, _n_d = db.upsert_records(
        store, records, set(), ["emp_no"], "is_active", db.USER_COLUMNS,
    )
    if dup:
        errors.append("사번이 중복되었습니다: " + ", ".join(k[0] for k in dup))
    # 표시순서 충돌 검증 — 부서가 아니라 '부서그룹' 기준, 활성 사용자만, 저장 후
    # 전체(merged) 기준 (필터로 안 보이는 사용자·부서 이동 후 충돌까지 차단).
    errors.extend(db.display_order_conflicts(merged, db.dept_group_map()))
    if errors:
        st.error("저장하지 못했습니다.\n\n- " + "\n- ".join(errors))
        return

    db.save_users(merged)
    _load_editor(q, dept_names, team_display)  # 저장된 스토어 기준 재조회 → 신규 행이 기존 행으로 전환
    set_flash(
        "master_users", "success",
        f"사용자를 저장했습니다. (신규 {n_c} · 수정 {n_u})",
    )
    st.rerun()


def _validate(live, dept_resolver, team_resolve):
    """표시 형태 → 저장 형태 변환 + 행별 기본 검증. (records, errors) 반환.

    완전히 빈 행(붙여넣기 버퍼/신규 행)은 조용히 건너뛴다.
    """
    role_resolver = _role_resolver()
    records, errors = [], []
    for i, (_, row) in enumerate(live.iterrows(), start=1):
        emp_no = str(row.get("사번") or "").strip()
        name = str(row.get("성명") or "").strip()
        dept_value = str(row.get("부서") or "").strip()
        team_value = str(row.get("조") or "").strip()
        position = str(row.get("직급") or "").strip()
        role = role_resolver.get(str(row.get("권한") or "").strip(), "")
        dept_code = dept_resolver.get(dept_value, "")

        if not any([emp_no, name, dept_value, team_value, position]):
            continue

        tag = f"{i}행" + (f"({emp_no})" if emp_no else "")
        if not emp_no:
            errors.append(f"{i}행: 사번을 입력하세요.")
        if not name:
            errors.append(f"{tag}: 성명을 입력하세요.")
        if not dept_code:
            errors.append(f"{tag}: 부서를 선택하세요.")

        team_code = ""
        if team_value and dept_code:
            resolved = team_resolve.get((dept_code, team_value))
            if resolved is None and (dept_code, team_value) in team_resolve:
                errors.append(f"{tag}: 조명이 부서 내에서 중복되어 특정할 수 없습니다: {team_value}")
            elif resolved is None:
                errors.append(f"{tag}: 선택한 부서에 없는 조입니다: {team_value}")
            else:
                team_code = resolved
        elif team_value and not dept_code:
            errors.append(f"{tag}: 조를 확인하려면 먼저 부서를 선택하세요.")

        if role not in _ROLE_TO_LABEL:
            errors.append(f"{tag}: 권한을 선택하세요. (관리자/조장/조원)")

        # 표시순서: 빈 값=미지정(NULL), 정수만 허용, 1 이상 권장.
        display_order = None
        order_raw = str(row.get("표시순서") or "").strip()
        if order_raw:
            try:
                display_order = db.normalize_display_order(order_raw)
            except (TypeError, ValueError):
                errors.append(f"{tag}: 표시순서는 숫자여야 합니다. (입력값: {order_raw})")
            if display_order is not None and display_order < 1:
                errors.append(f"{tag}: 표시순서는 1 이상이어야 합니다.")

        records.append({
            "emp_no": emp_no,
            "name": name,
            "dept_code": dept_code,
            "team_code": team_code,
            "position": position,
            "role": role,
            "is_active": grid_bool(row.get("재직")),
            "display_order": display_order,
        })
    return records, errors
