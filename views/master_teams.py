"""기준정보 — 조 관리: Excel 붙여넣기를 지원하는 직접 편집 그리드."""
import pandas as pd
import streamlit as st

from modules import db, ui
from views.workspace import ALL, editable_aggrid, grid_bool, save_bar, set_flash, show_flash

_STATUS = ["사용 중", "사용 안 함", "전체"]
_COLS = ["부서", "조코드", "조명", "표시순서", "사용"]


def _dept_labels(dept_names: dict[str, str]) -> dict[str, str]:
    """부서명 중복에도 안전한 편집기 표시값(code -> label)."""
    return {
        code: f"{name} ({code})"
        for code, name in dept_names.items()
    }


def render(user: dict) -> None:
    ui.page_header("master_teams")
    depts = db.get_departments()
    dept_names = {str(r["dept_code"]): str(r["dept_name"]) for _, r in depts.iterrows()}
    if not dept_names:
        ui.empty_state("등록된 부서가 없습니다. 먼저 부서를 등록하세요.", head="조 관리")
        return

    with ui.card():
        c1, c2, c3 = st.columns([1.6, 1.2, 0.9], vertical_alignment="bottom")
        dept = c1.selectbox("부서", [ALL] + list(dept_names), format_func=lambda value: dept_names.get(value, value), key="mt_dept")
        active = c2.selectbox("사용 여부", _STATUS, key="mt_active")
        refresh = c3.button("새로고침", key="mt_go", type="primary", width="stretch")

    params = {"dept": dept, "active": active}
    if refresh or st.session_state.get("q_master_teams") != params or "mt_work" not in st.session_state:
        st.session_state["q_master_teams"] = params
        _load_editor(params, dept_names)

    show_flash("master_teams")
    dept_labels = _dept_labels(dept_names)
    edited = editable_aggrid(
        st.session_state["mt_work"],
        key="mt_editor",
        columns={
            "부서": list(dept_labels.values()), "조코드": "text", "조명": "text",
            "표시순서": "number", "사용": "bool",
        },
    )
    st.session_state["mt_work"] = edited

    new, _space = st.columns([1, 7])
    if new.button("신규", key="mt_new", width="stretch"):
        st.session_state["mt_work"] = pd.concat(
            [edited, pd.DataFrame([{column: False if column == "사용" else 0 if column == "표시순서" else "" for column in _COLS}])],
            ignore_index=True,
        )
        st.rerun()
    if save_bar("mt"):
        _save(st.session_state["mt_work"], params, dept_names)


def _load_editor(params: dict, dept_names: dict) -> None:
    source = db.get_teams().copy()
    if params["dept"] != ALL:
        source = source[source["dept_code"].astype(str) == params["dept"]]
    if params["active"] == "사용 중":
        source = source[source["is_active"].astype(bool)]
    elif params["active"] == "사용 안 함":
        source = source[~source["is_active"].astype(bool)]
    source = source.sort_values(["dept_code", "sort_order", "team_code"]).reset_index(drop=True)
    labels = _dept_labels(dept_names)
    st.session_state["mt_work"] = pd.DataFrame({
        "부서": source["dept_code"].map(labels).fillna("").astype("string"),
        "조코드": source["team_code"].fillna("").astype("string"),
        "조명": source["team_name"].fillna("").astype("string"),
        "표시순서": source["sort_order"].fillna(0).astype("int64"),
        "사용": source["is_active"].fillna(True).astype(bool),
    })


def _save(edited: pd.DataFrame, params: dict, dept_names: dict) -> None:
    label_to_code = {label: code for code, label in _dept_labels(dept_names).items()}
    records, errors = _validate(edited, label_to_code)
    if errors:
        st.error("저장하지 못했습니다.\n\n- " + "\n- ".join(errors))
        return
    store = db.get_teams()
    merged, duplicates, created, updated, deactivated = db.upsert_records(
        store, records, set(), ["dept_code", "team_code"], "is_active", db.TEAM_COLUMNS,
    )
    if duplicates:
        errors.append("같은 부서의 조코드가 중복되었습니다: " + ", ".join(f"{dept}/{code}" for dept, code in duplicates))
    if errors:
        st.error("저장하지 못했습니다.\n\n- " + "\n- ".join(errors))
        return
    db.save_teams(merged)
    _load_editor(params, dept_names)
    set_flash("master_teams", "success", f"조를 저장했습니다. (신규 {created}건 · 수정 {updated}건 · 사용 해제 {deactivated}건)")
    st.rerun()


def _validate(edited: pd.DataFrame, label_to_code: dict) -> tuple[list[dict], list[str]]:
    records, errors, seen = [], [], set()
    for row_number, (_, row) in enumerate(edited.iterrows(), start=1):
        dept_label = str(row.get("부서") or "").strip()
        code = str(row.get("조코드") or "").strip()
        name = str(row.get("조명") or "").strip()
        if not any((dept_label, code, name)):
            continue
        dept_code = label_to_code.get(dept_label, "")
        if not dept_code:
            errors.append(f"{row_number}행: 유효한 부서를 선택하세요.")
        if not code:
            errors.append(f"{row_number}행: 조코드를 입력하세요.")
        if not name:
            errors.append(f"{row_number}행: 조명을 입력하세요.")
        key = (dept_code, code)
        if dept_code and code and key in seen:
            errors.append(f"{row_number}행: 부서 내 조코드가 중복됩니다 ({dept_label}/{code}).")
        seen.add(key)
        try:
            order = int(row.get("표시순서") or 0)
        except (TypeError, ValueError):
            errors.append(f"{row_number}행: 표시순서는 숫자여야 합니다.")
            order = 0
        records.append({"dept_code": dept_code, "team_code": code, "team_name": name, "sort_order": order, "is_active": grid_bool(row.get("사용"))})
    return records, errors
