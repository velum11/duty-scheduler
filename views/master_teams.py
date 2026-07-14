"""기준정보 — 조 관리 화면 (폼 기반 입력).

한글 IME 조합 입력이 st.data_editor 셀과 충돌하는 문제를 피하려고, 목록은 읽기 전용
그리드(행 선택)로 조회만 하고 등록·수정은 st.form + st.text_input 으로 처리한다.
form 안의 입력 위젯은 [저장] 제출 전까지 rerun 을 일으키지 않으므로 한글 조합이
중간에 확정·손실되지 않는다(`B조`가 `BWH`로 확정되던 문제 방지).

- 부서는 st.selectbox 로 선택하고, 조코드·조명은 직접 입력한다.
- 목록에서 행을 선택하면 해당 조를 폼에 불러온다.
- [저장] 을 눌렀을 때만 db 파사드(save_teams)로 반영하며 부서-조 관계를 유지한다.
- [삭제] 는 기존 CRUD 정책(사용여부 소프트삭제)을 유지한다.
현재 master_teams / Repository 계약과 화면 명칭은 이번 작업에서 변경하지 않는다.
"""
import pandas as pd
import streamlit as st

from modules import db, ui
from views.workspace import ALL, list_height, pick_row, set_flash, show_flash

_STATUS = ["사용 중", "사용 안 함", "전체"]

# 폼 위젯 key (rerun 사이에 안정적으로 유지)
_F_DEPT, _F_CODE, _F_NAME = "mt_f_dept", "mt_f_code", "mt_f_name"
_F_ORDER, _F_ACTIVE = "mt_f_order", "mt_f_active"


def render(user: dict) -> None:
    ui.page_header("master_teams")

    depts = db.get_departments()
    dept_names = {r["dept_code"]: r["dept_name"] for _, r in depts.iterrows()}
    if not dept_names:
        ui.empty_state("등록된 부서가 없습니다. 먼저 부서 관리에서 부서를 등록하세요.", head="조 목록")
        return

    source = db.get_teams()

    # 조회 조건 카드
    with ui.card():
        c1, c2, c3 = st.columns([1.6, 1.2, 0.9], vertical_alignment="bottom")
        dept = c1.selectbox(
            "부서", [ALL] + list(dept_names), format_func=lambda c: dept_names.get(c, c),
            key="mt_dept",
        )
        active = c2.selectbox("사용 여부", _STATUS, key="mt_active")
        refresh = c3.button("새로고침", key="mt_go", type="primary", width="stretch")

    # 목록 적재: 필터 변경 / 새로고침 / 최초 진입 시에만 DB 재조회.
    params = {"dept": dept, "active": active}
    if refresh or st.session_state.get("q_master_teams") != params or "mt_list" not in st.session_state:
        st.session_state["q_master_teams"] = params
        _load_list(source, dept, active)

    if "mt_editing" not in st.session_state:  # 폼 상태 최초 1회 초기화(신규 모드)
        _seed_new(dept_names)

    show_flash("master_teams")

    list_df = st.session_state["mt_list"]
    users = db.get_users()
    headcount = users[users["is_active"]].groupby(["dept_code", "team_code"]).size()
    _summary_cards(list_df, dept_names, headcount)

    # 목록 (읽기 전용, 단일 행 선택)
    ui.panel_head("조 목록", f"{len(list_df)}건")
    nonce = st.session_state.setdefault("mt_nonce", 0)
    picked = pick_row(_to_display(list_df, dept_names), f"mt_grid_{nonce}", list_height(len(list_df)))

    editing = st.session_state.get("mt_editing")
    b1, b2, _sp = st.columns([1, 1, 6])
    new_clicked = b1.button("신규", key="mt_new", width="stretch")
    del_clicked = b2.button("삭제", key="mt_del", width="stretch", disabled=editing is None)

    if new_clicked:
        _seed_new(dept_names)
        st.session_state["mt_nonce"] = nonce + 1
        st.rerun()
    if del_clicked and editing is not None:
        _delete(editing)

    # 선택이 바뀐 경우에만 폼에 적재 (입력 중 원본으로 덮어쓰지 않음).
    if picked is not None:
        row = list_df.iloc[picked]
        key = (str(row["dept_code"]), str(row["team_code"]))
        if editing != key:
            _seed_from_row(row)

    _form(dept_names)


def _to_display(df: pd.DataFrame, dept_names: dict) -> pd.DataFrame:
    return pd.DataFrame({
        "부서": df["dept_code"].map(dept_names).fillna(df["dept_code"]).astype(str),
        "조코드": df["team_code"].astype(str),
        "조명": df["team_name"].astype(str),
        "표시순서": df["sort_order"].astype(int),
        "사용": df["is_active"].map(lambda v: "사용" if bool(v) else "미사용"),
    })


def _load_list(source: pd.DataFrame, dept: str, active: str) -> None:
    df = source.copy()
    if dept != ALL:
        df = df[df["dept_code"] == dept]
    if active == "사용 중":
        df = df[df["is_active"]]
    elif active == "사용 안 함":
        df = df[~df["is_active"].astype(bool)]
    st.session_state["mt_list"] = df.sort_values(["dept_code", "sort_order"]).reset_index(drop=True)


def _seed_new(dept_names: dict) -> None:
    q = st.session_state.get("q_master_teams", {})
    default_dept = q["dept"] if q.get("dept") and q["dept"] != ALL else next(iter(dept_names))
    st.session_state["mt_editing"] = None
    st.session_state[_F_DEPT] = default_dept
    st.session_state[_F_CODE] = ""
    st.session_state[_F_NAME] = ""
    st.session_state[_F_ORDER] = 0
    st.session_state[_F_ACTIVE] = True


def _seed_from_row(row) -> None:
    st.session_state["mt_editing"] = (str(row["dept_code"]), str(row["team_code"]))
    st.session_state[_F_DEPT] = str(row["dept_code"])
    st.session_state[_F_CODE] = str(row["team_code"])
    st.session_state[_F_NAME] = str(row["team_name"])
    st.session_state[_F_ORDER] = int(row["sort_order"])
    st.session_state[_F_ACTIVE] = bool(row["is_active"])


def _form(dept_names: dict) -> None:
    editing = st.session_state.get("mt_editing")
    head = "조 등록" if editing is None else f"조 수정 — {dept_names.get(editing[0], editing[0])} / {editing[1]}"
    with ui.card():
        ui.panel_head(head)
        with st.form("mt_form", clear_on_submit=False):
            c1, c2 = st.columns(2)
            c1.selectbox("부서", list(dept_names), format_func=lambda c: dept_names.get(c, c), key=_F_DEPT)
            c2.text_input("조코드", key=_F_CODE, placeholder="예: A")
            c3, c4 = st.columns(2)
            c3.text_input("조명", key=_F_NAME, placeholder="예: A조")
            c4.number_input("표시순서", key=_F_ORDER, min_value=0, step=1)
            st.checkbox("사용", key=_F_ACTIVE)
            submitted = st.form_submit_button("저장", type="primary", width="stretch")
    if submitted:
        _save(dept_names)


def _save(dept_names: dict) -> None:
    dept_code = str(st.session_state.get(_F_DEPT, "")).strip()
    code = str(st.session_state.get(_F_CODE, "")).strip()
    name = str(st.session_state.get(_F_NAME, "")).strip()
    order = int(st.session_state.get(_F_ORDER, 0) or 0)
    active = bool(st.session_state.get(_F_ACTIVE, True))

    errors = []
    if dept_code not in dept_names:
        errors.append("부서를 선택하세요.")
    if not code:
        errors.append("조코드를 입력하세요.")
    if not name:
        errors.append("조명을 입력하세요.")
    if errors:
        st.error("저장하지 못했습니다.\n\n- " + "\n- ".join(errors))
        return

    store = db.get_teams()
    merged = _merged(store, {
        "dept_code": dept_code, "team_code": code, "team_name": name,
        "sort_order": order, "is_active": active,
    })
    db.save_teams(merged)
    st.session_state["mt_editing"] = (dept_code, code)  # 저장된 행을 폼에 유지
    _reload_after_write()
    set_flash("master_teams", "success", f"조를 저장했습니다. ({dept_names.get(dept_code, dept_code)} / {code})")
    st.rerun()


def _delete(editing: tuple) -> None:
    dept_code, code = editing
    store = db.get_teams()
    match = store[(store["dept_code"].astype(str) == dept_code) & (store["team_code"].astype(str) == code)]
    if match.empty:
        set_flash("master_teams", "warning", "이미 삭제된 조입니다.")
    else:
        record = match.iloc[0].to_dict()
        record["is_active"] = False
        db.save_teams(_merged(store, record))
        set_flash("master_teams", "success", f"조를 삭제(비활성) 처리했습니다. ({dept_code} / {code})")
    dept_names = {r["dept_code"]: r["dept_name"] for _, r in db.get_departments().iterrows()}
    _seed_new(dept_names)
    _reload_after_write()
    st.rerun()


def _merged(store: pd.DataFrame, record: dict) -> pd.DataFrame:
    by_key = {(str(r["dept_code"]), str(r["team_code"])): r for r in store.to_dict("records")}
    by_key[(str(record["dept_code"]), str(record["team_code"]))] = record
    return pd.DataFrame(list(by_key.values()), columns=db.TEAM_COLUMNS)


def _reload_after_write() -> None:
    params = st.session_state.get("q_master_teams", {"dept": ALL, "active": "사용 중"})
    _load_list(db.get_teams(), params.get("dept", ALL), params.get("active", "사용 중"))
    st.session_state["mt_nonce"] = st.session_state.get("mt_nonce", 0) + 1


def _summary_cards(df: pd.DataFrame, dept_names: dict, headcount: pd.Series) -> None:
    total = 0
    for dept_code, team_code in zip(df["dept_code"].astype(str), df["team_code"].astype(str)):
        total += int(headcount.get((dept_code, team_code), 0))
    ui.summary_cards([
        ("조", f"{len(df)}개"),
        ("사용 중", f"{int(df['is_active'].fillna(False).astype(bool).sum())}개"),
        ("부서", f"{df['dept_code'].replace('', pd.NA).nunique()}개"),
        ("소속 인원", f"{total}명"),
    ])
    st.write("")
