"""기준정보 — 조 관리: 부서 관리와 동일한 스프레드시트형 직접 편집 화면.

행 상태 계약(_row_id/_row_state/_sel)으로 기존 저장 행과 미저장 신규 행을 분리한다.
  - 기존 행: 첫 열 선택 체크박스 → 상단 [삭제] 대상
  - 신규 행: 첫 열 − 제거 버튼 → 즉시 개별 제거(확인·DB 작업 없음)
부서는 표시명(또는 코드)으로 입력하고 저장 시 dept_code 로 변환한다(users 무변경).
[삭제]는 참조(소속 사용자) 없는 조는 실제 삭제, 참조 중이면 미사용 처리한다.
"""
import pandas as pd
import streamlit as st

from modules import db, ui
from views import workspace
from views.workspace import grid_bool, selectable_master_grid, set_flash, show_flash

_STATUS = ["사용 중", "사용 안 함", "전체"]
_USER_COLS = ["부서", "조코드", "조명", "표시순서", "사용"]
_ROW_COLS = ["_row_id", "_row_state", "_sel", *_USER_COLS]
_GRID_COLUMNS = {"부서": "text", "조코드": "text", "조명": "text", "표시순서": "text", "사용": "bool"}


def _dept_maps():
    """(code->표시명, 표시명/코드->code). 부서명 중복에도 안전하게 코드를 붙여 표시한다."""
    depts = db.get_departments()
    disp_of, code_of = {}, {}
    name_dups: dict[str, int] = {}
    for _, r in depts.iterrows():
        name_dups[str(r["dept_name"]).strip()] = name_dups.get(str(r["dept_name"]).strip(), 0) + 1
    for _, r in depts.iterrows():
        code = str(r["dept_code"]).strip()
        name = str(r["dept_name"]).strip()
        disp = name if name_dups.get(name, 0) == 1 else f"{name} ({code})"
        disp_of[code] = disp
        code_of[disp] = code
        code_of[code] = code  # 코드 직접 입력도 허용
    return disp_of, code_of


def render(user: dict) -> None:
    depts = db.get_departments()
    if depts[depts["is_active"]].empty:
        workspace.master_screen_head("조 관리", "부서별 조를 표에서 직접 편집하고 [저장]으로 일괄 반영합니다.")
        ui.empty_state("등록된 부서가 없습니다. 먼저 부서를 등록하세요.", head="조 관리")
        return
    disp_of, _code_of = _dept_maps()

    workspace.master_screen_head("조 관리", "부서별 조(조코드·조명)를 표에서 직접 편집하고 [저장]으로 일괄 반영합니다.")

    refresh = st.session_state.pop("ms_refresh_req", False)
    with st.container(key="ms_filter"):
        f1, f2, _sp = st.columns([1.4, 3.0, 5.6], vertical_alignment="bottom")
        active = f1.selectbox("사용 여부", _STATUS, key="mt_active", label_visibility="collapsed")
        search = f2.text_input("검색", key="mt_search", placeholder="조코드·조명·부서 검색", label_visibility="collapsed")

    params = {"active": active, "search": search.strip()}
    if refresh or st.session_state.get("q_master_teams") != params or "mt_rows" not in st.session_state:
        st.session_state["q_master_teams"] = params
        st.session_state.pop("mt_del_plan", None)
        _load_editor(params, disp_of)

    show_flash("master_teams")

    plan = st.session_state.get("mt_del_plan")
    if plan:
        _confirm_bar(plan, params)

    bar = st.container(key="ms_bar")

    nonce = st.session_state.setdefault("mt_nonce", 0)
    col_config = {
        "부서": {"flex": 2, "minWidth": 150, "cellClass": "md-c-left"},
        "조코드": {"width": 110, "minWidth": 90, "cellClass": "md-c-left"},
        "조명": {"flex": 1, "minWidth": 120, "cellClass": "md-c-left"},
        "표시순서": {"width": 108, "minWidth": 92, "maxWidth": 140, "cellClass": "md-c-center"},
        "사용": {"width": 82, "minWidth": 72, "maxWidth": 108, "cellClass": "md-c-center"},
    }
    rows = st.session_state["mt_rows"]
    with st.container(key="ms_grid"):
        grid_df = selectable_master_grid(
            rows, key=f"mt_grid_{nonce}", columns=_GRID_COLUMNS, order=_USER_COLS,
            height=workspace.master_grid_height(len(rows)),
            col_config=col_config, select_all_header=True,
        )

    live = _live(grid_df)
    existing = live[live["_row_state"] == "existing"]
    new_rows = live[live["_row_state"] != "existing"]
    sel_count = int((existing["_sel"].map(grid_bool)).sum()) if not existing.empty else 0
    workspace.master_count(len(existing), len(new_rows), sel_count)

    with bar:
        workspace.master_action_bar(sel_count)

    if st.session_state.pop("ms_save_req", False):
        _save(grid_df, params)
    if st.session_state.pop("ms_del_req", False):
        _handle_delete(grid_df, params)
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
    n = st.session_state.get("mt_rid", 0) + 1
    st.session_state["mt_rid"] = n
    return f"n:{n}"


def _next_order(rows: pd.DataFrame) -> int:
    orders = pd.to_numeric(rows.get("표시순서"), errors="coerce").dropna()
    return int(orders.max()) + 1 if len(orders) else 1


def _new_row(order_val: int) -> dict:
    return {"_row_id": _next_rid(), "_row_state": "new", "_sel": False,
            "부서": "", "조코드": "", "조명": "", "표시순서": str(order_val), "사용": True}


def _add_row(grid_df: pd.DataFrame) -> None:
    live = _live(grid_df)
    st.session_state["mt_rows"] = pd.concat(
        [live[_ROW_COLS], pd.DataFrame([_new_row(_next_order(live))])], ignore_index=True,
    )[_ROW_COLS]
    st.session_state["mt_nonce"] = st.session_state.get("mt_nonce", 0) + 1
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
    st.session_state["mt_rows"] = live[_ROW_COLS].reset_index(drop=True)
    st.session_state["mt_nonce"] = st.session_state.get("mt_nonce", 0) + 1
    return True


# ---------- 삭제 (기존 저장 행 전용) ----------
def _handle_delete(grid_df: pd.DataFrame, params: dict) -> None:
    live = _live(grid_df)
    sel = live[(live["_row_state"] == "existing") & live["_sel"].map(grid_bool)]
    keys = [(str(r["_row_id"])[2:]) for _, r in sel.iterrows()]  # _row_id = "e:{dept}|{team}"
    if not keys:
        set_flash("master_teams", "warning", "삭제할 기존 조를 선택하세요.")
        st.rerun()

    plan = {"delete": [], "deactivate": []}
    for key in keys:
        dept_code, team_code = key.split("|", 1) if "|" in key else (key, "")
        refs = db.team_reference_counts(dept_code, team_code)
        item = {"dept_code": dept_code, "team_code": team_code, "refs": refs}
        (plan["deactivate"] if sum(refs.values()) > 0 else plan["delete"]).append(item)
    st.session_state["mt_del_plan"] = plan
    st.rerun()


def _confirm_bar(plan: dict, params: dict) -> None:
    lines = []
    for it in plan["delete"]:
        lines.append(f"삭제 가능: {it['dept_code']}/{it['team_code']}")
    for it in plan["deactivate"]:
        lines.append(f"미사용 처리: {it['dept_code']}/{it['team_code']} — 사용자 {it['refs'].get('users', 0)}명 소속")
    st.warning("선택한 조를 다음과 같이 처리합니다.\n\n- " + "\n- ".join(lines))
    c1, c2, _sp = st.columns([1.4, 1.0, 6], vertical_alignment="center")
    if c1.button("실행", key="mt_del_ok", type="primary", width="stretch"):
        _execute_delete(plan, params)
    if c2.button("취소", key="mt_del_cancel", width="stretch"):
        st.session_state.pop("mt_del_plan", None)
        st.rerun()


def _execute_delete(plan: dict, params: dict) -> None:
    n_del = 0
    for it in plan["delete"]:
        db.delete_team(it["dept_code"], it["team_code"])
        n_del += 1
    deact = plan["deactivate"]
    n_deact = 0
    if deact:
        store = db.get_teams().copy()
        for it in deact:
            mask = (
                (store["dept_code"].astype(str) == it["dept_code"])
                & (store["team_code"].astype(str) == it["team_code"])
            )
            n_deact += int(mask.sum())
            store.loc[mask, "is_active"] = False
        db.save_teams(store[db.TEAM_COLUMNS])
    st.session_state.pop("mt_del_plan", None)
    _load_editor(params, _dept_maps()[0])
    parts = []
    if n_del:
        parts.append(f"{n_del}개 삭제")
    if n_deact:
        parts.append(f"{n_deact}개 미사용 처리")
    msg = "조를 " + ", ".join(parts) + "했습니다." if parts else "처리할 조가 없습니다."
    set_flash("master_teams", "success" if (n_del or n_deact) else "warning", msg)
    st.rerun()


# ---------- 적재 / 저장 ----------
def _load_editor(q: dict, disp_of: dict) -> None:
    df = db.get_teams().copy()
    if q["active"] == "사용 중":
        df = df[df["is_active"]]
    elif q["active"] == "사용 안 함":
        df = df[~df["is_active"].astype(bool)]
    term = str(q.get("search", "")).strip()
    if term:
        hit = (
            df["team_code"].astype(str).str.contains(term, case=False, na=False, regex=False)
            | df["team_name"].astype(str).str.contains(term, case=False, na=False, regex=False)
            | df["dept_code"].astype(str).map(lambda c: disp_of.get(str(c), str(c))).str.contains(term, case=False, na=False, regex=False)
        )
        df = df[hit]
    df = df.sort_values(["dept_code", "sort_order", "team_code"]).reset_index(drop=True)

    order = pd.to_numeric(df["sort_order"], errors="coerce").fillna(0).astype("int64")
    rows = pd.DataFrame({
        "_row_id": "e:" + df["dept_code"].astype(str) + "|" + df["team_code"].astype(str),
        "_row_state": "existing",
        "_sel": False,
        "부서": df["dept_code"].astype(str).map(lambda c: disp_of.get(str(c), str(c))).astype("string"),
        "조코드": df["team_code"].fillna("").astype("string"),
        "조명": df["team_name"].fillna("").astype("string"),
        "표시순서": order.astype(str).astype("string"),
        "사용": df["is_active"].fillna(True).astype(bool),
    }) if not df.empty else pd.DataFrame(columns=_ROW_COLS)

    st.session_state["mt_rows"] = rows[_ROW_COLS].reset_index(drop=True)
    st.session_state["mt_nonce"] = st.session_state.get("mt_nonce", 0) + 1


def _save(grid_df, q) -> None:
    live = _live(grid_df)
    records, errors = _validate(live)
    store = db.get_teams()
    merged, dup, n_c, n_u, _n_d = db.upsert_records(
        store, records, set(), ["dept_code", "team_code"], "is_active", db.TEAM_COLUMNS,
    )
    if dup:
        errors.append("같은 부서의 조코드가 중복되었습니다: " + ", ".join(f"{d}/{t}" for d, t in dup))
    if errors:
        st.error("저장하지 못했습니다.\n\n- " + "\n- ".join(errors))
        return
    db.save_teams(merged)
    _load_editor(q, _dept_maps()[0])
    set_flash("master_teams", "success", f"조를 저장했습니다. (신규 {n_c} · 수정 {n_u})")
    st.rerun()


def _validate(live: pd.DataFrame):
    _disp_of, code_of = _dept_maps()
    records, errors, seen = [], [], set()
    for i, (_, row) in enumerate(live.iterrows(), start=1):
        dept_txt = str(row.get("부서") or "").strip()
        code = str(row.get("조코드") or "").strip()
        name = str(row.get("조명") or "").strip()
        order_raw = row.get("표시순서")
        if not any([dept_txt, code, name]):
            continue

        tag = f"{i}행" + (f"({code})" if code else "")
        dept_code = code_of.get(dept_txt, "")
        if not dept_code:
            errors.append(f"{i}행: 존재하지 않는 부서입니다: {dept_txt or '(빈 값)'}")
        if not code:
            errors.append(f"{tag}: 조코드를 입력하세요.")
        if not name:
            errors.append(f"{tag}: 조명을 입력하세요.")
        key = (dept_code, code)
        if dept_code and code and key in seen:
            errors.append(f"{tag}: 부서 내 조코드가 중복됩니다 ({dept_txt}/{code}).")
        seen.add(key)
        try:
            order_val = int(order_raw) if str(order_raw).strip() != "" else 0
        except (TypeError, ValueError):
            order_val = 0
            errors.append(f"{tag}: 표시순서는 숫자여야 합니다.")

        records.append({
            "dept_code": dept_code, "team_code": code, "team_name": name,
            "sort_order": order_val, "is_active": grid_bool(row.get("사용")),
        })
    return records, errors
