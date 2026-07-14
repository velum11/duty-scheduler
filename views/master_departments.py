"""기준정보 — 부서 관리 화면 (폼 기반 입력).

한글 IME 조합 입력이 st.data_editor 셀과 충돌하는 문제를 피하려고, 목록은 읽기 전용
그리드(행 선택)로 조회만 하고 등록·수정은 st.form + st.text_input 으로 처리한다.
form 안의 입력 위젯은 [저장] 제출 전까지 rerun 을 일으키지 않으므로 한글 조합이
중간에 확정·손실되지 않는다.

- 목록에서 행을 선택하면 해당 부서를 폼에 불러온다.
- [신규] 는 빈 폼(신규 모드)으로 초기화한다.
- [저장] 을 눌렀을 때만 db 파사드(save_departments)로 반영한다.
- [삭제] 는 기존 CRUD 정책(사용여부 소프트삭제)을 유지한다.
저장 계층은 기존 Repository 계약을 그대로 사용하며 이름을 관계 키로 쓰지 않는다.
"""
import pandas as pd
import streamlit as st

from modules import db, ui
from views.workspace import list_height, pick_row, set_flash, show_flash

_STATUS = ["사용 중", "사용 안 함", "전체"]

# 폼 위젯 key (rerun 사이에 안정적으로 유지)
_F_CODE, _F_NAME, _F_ORDER, _F_ACTIVE = "md_f_code", "md_f_name", "md_f_order", "md_f_active"


def render(user: dict) -> None:
    ui.page_header("master_departments")
    source = db.get_departments()

    # 조회 조건 카드
    with ui.card():
        c1, c2 = st.columns([1.4, 0.9], vertical_alignment="bottom")
        active = c1.selectbox("사용 여부", _STATUS, key="md_active")
        refresh = c2.button("새로고침", key="md_go", type="primary", width="stretch")

    # 목록 적재: 필터 변경 / 새로고침 / 최초 진입 시에만 DB 재조회.
    params = {"active": active}
    if refresh or st.session_state.get("q_master_departments") != params or "md_list" not in st.session_state:
        st.session_state["q_master_departments"] = params
        _load_list(source, active)

    if "md_editing" not in st.session_state:  # 폼 상태 최초 1회 초기화(신규 모드)
        _seed_new()

    show_flash("master_departments")

    list_df = st.session_state["md_list"]
    users = db.get_users()
    headcount = users[users["is_active"]].groupby("dept_code").size()
    _summary_cards(list_df, headcount)

    # 목록 (읽기 전용, 단일 행 선택)
    ui.panel_head("부서 목록", f"{len(list_df)}건")
    nonce = st.session_state.setdefault("md_nonce", 0)
    picked = pick_row(_to_display(list_df), f"md_grid_{nonce}", list_height(len(list_df)))

    editing = st.session_state.get("md_editing")
    b1, b2, _sp = st.columns([1, 1, 6])
    new_clicked = b1.button("신규", key="md_new", width="stretch")
    del_clicked = b2.button("삭제", key="md_del", width="stretch", disabled=editing is None)

    if new_clicked:
        _seed_new()
        st.session_state["md_nonce"] = nonce + 1
        st.rerun()
    if del_clicked and editing is not None:
        _delete(editing)

    # 선택이 바뀐 경우에만 폼에 적재 (입력 중 원본으로 덮어쓰지 않음).
    if picked is not None:
        row = list_df.iloc[picked]
        if editing != str(row["dept_code"]):
            _seed_from_row(row)

    _form()


def _to_display(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "부서코드": df["dept_code"].astype(str),
        "부서명": df["dept_name"].astype(str),
        "표시순서": df["sort_order"].astype(int),
        "사용": df["is_active"].map(lambda v: "사용" if bool(v) else "미사용"),
    })


def _load_list(source: pd.DataFrame, active: str) -> None:
    df = source.copy()
    if active == "사용 중":
        df = df[df["is_active"]]
    elif active == "사용 안 함":
        df = df[~df["is_active"].astype(bool)]
    st.session_state["md_list"] = df.sort_values("sort_order").reset_index(drop=True)


def _seed_new() -> None:
    st.session_state["md_editing"] = None
    st.session_state[_F_CODE] = ""
    st.session_state[_F_NAME] = ""
    st.session_state[_F_ORDER] = 0
    st.session_state[_F_ACTIVE] = True


def _seed_from_row(row) -> None:
    st.session_state["md_editing"] = str(row["dept_code"])
    st.session_state[_F_CODE] = str(row["dept_code"])
    st.session_state[_F_NAME] = str(row["dept_name"])
    st.session_state[_F_ORDER] = int(row["sort_order"])
    st.session_state[_F_ACTIVE] = bool(row["is_active"])


def _form() -> None:
    editing = st.session_state.get("md_editing")
    with ui.card():
        ui.panel_head("부서 등록" if editing is None else f"부서 수정 — {editing}")
        with st.form("md_form", clear_on_submit=False):
            c1, c2 = st.columns(2)
            c1.text_input("부서코드", key=_F_CODE, placeholder="예: PET1")
            c2.text_input("부서명", key=_F_NAME, placeholder="예: PET생산부(본동)")
            c3, c4 = st.columns([1, 1])
            c3.number_input("표시순서", key=_F_ORDER, min_value=0, step=1)
            c4.checkbox("사용", key=_F_ACTIVE)
            submitted = st.form_submit_button("저장", type="primary", width="stretch")
    if submitted:
        _save()


def _save() -> None:
    code = str(st.session_state.get(_F_CODE, "")).strip()
    name = str(st.session_state.get(_F_NAME, "")).strip()
    order = int(st.session_state.get(_F_ORDER, 0) or 0)
    active = bool(st.session_state.get(_F_ACTIVE, True))

    errors = []
    if not code:
        errors.append("부서코드를 입력하세요.")
    if not name:
        errors.append("부서명을 입력하세요.")
    if errors:
        st.error("저장하지 못했습니다.\n\n- " + "\n- ".join(errors))
        return

    store = db.get_departments()
    merged = _merged(store, {
        "dept_code": code, "dept_name": name, "sort_order": order, "is_active": active,
    })
    db.save_departments(merged)
    st.session_state["md_editing"] = code  # 저장된 행을 폼에 유지
    _reload_after_write()
    set_flash("master_departments", "success", f"부서를 저장했습니다. ({code})")
    st.rerun()


def _delete(code: str) -> None:
    store = db.get_departments()
    match = store[store["dept_code"].astype(str) == str(code)]
    if match.empty:
        set_flash("master_departments", "warning", "이미 삭제된 부서입니다.")
    else:
        record = match.iloc[0].to_dict()
        record["is_active"] = False
        db.save_departments(_merged(store, record))
        set_flash("master_departments", "success", f"부서를 삭제(비활성) 처리했습니다. ({code})")
    _seed_new()
    _reload_after_write()
    st.rerun()


def _merged(store: pd.DataFrame, record: dict) -> pd.DataFrame:
    by_code = {str(r["dept_code"]): r for r in store.to_dict("records")}
    by_code[str(record["dept_code"])] = record
    return pd.DataFrame(list(by_code.values()), columns=db.DEPT_COLUMNS)


def _reload_after_write() -> None:
    params = st.session_state.get("q_master_departments", {"active": "사용 중"})
    _load_list(db.get_departments(), params.get("active", "사용 중"))
    st.session_state["md_nonce"] = st.session_state.get("md_nonce", 0) + 1


def _summary_cards(df: pd.DataFrame, headcount: pd.Series) -> None:
    codes = df["dept_code"].astype(str)
    ui.summary_cards([
        ("부서", f"{len(df)}개"),
        ("사용 중", f"{int(df['is_active'].fillna(False).astype(bool).sum())}개"),
        ("소속 인원", f"{int(headcount.reindex(codes).fillna(0).sum())}명"),
    ])
    st.write("")
