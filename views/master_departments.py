"""기준정보 — 부서 관리 화면.

조회 조건으로 대상을 불러온 뒤 스프레드시트형 편집기(st.data_editor)로 등록/수정한다.
[저장] 을 눌렀을 때만 검증 후 반영하며(자동 저장 없음), 로컬 샘플 모드에서는
세션 상태(db.save_departments)에 저장해 현재 세션 동안 유지된다.

'사용 중'만 조회했더라도 저장 시 미조회 부서(미사용 등)는 그대로 보존한다
(조회 대상만 교체 후 병합).
"""
import pandas as pd
import streamlit as st

from modules import db, ui
from views.workspace import grid_height, save_bar, set_flash, show_flash

_COLS = ["부서코드", "부서명", "표시순서", "사용"]
_STATUS = ["사용 중", "사용 안 함", "전체"]


def render(user: dict) -> None:
    ui.page_header("master_departments")

    # 조회 조건 카드
    with ui.card():
        c1, c2 = st.columns([1.4, 0.9], vertical_alignment="bottom")
        active = c1.selectbox("사용 여부", _STATUS, key="md_active")
        clicked = c2.button("새로고침", key="md_go", type="primary", width="stretch")

    # 화면 진입 시 기본 필터로 자동 조회, [새로고침] 시 현재 필터로 재조회.
    params = {"active": active}
    q = st.session_state.get("q_master_departments")
    if clicked or q is None:
        q = params
        st.session_state["q_master_departments"] = q
        _load_editor(q)
    elif "md_work" not in st.session_state:  # rerun 등으로 조건만 남고 편집본이 없을 때
        _load_editor(q)

    show_flash("master_departments")

    users = db.get_users()
    headcount = users[users["is_active"]].groupby("dept_code").size()

    # 요약 카드 (편집 중인 내용 기준으로 갱신)
    sum_ph = st.container()

    # 스프레드시트형 편집 그리드 (행 추가 가능)
    st.caption("셀 이동은 Tab 키를 사용하세요.")
    edited = st.data_editor(
        st.session_state["md_work"],
        key="md_editor",
        num_rows="dynamic",
        width="stretch",
        hide_index=True,
        height=grid_height(len(st.session_state["md_work"]) + 1),
        column_config={
            "부서코드": st.column_config.TextColumn("부서코드", width="small"),
            "부서명": st.column_config.TextColumn("부서명"),
            "표시순서": st.column_config.NumberColumn(
                "표시순서", width="small", min_value=0, step=1,
            ),
            "사용": st.column_config.CheckboxColumn("사용", width="small", default=True),
        },
    )

    with sum_ph:
        _summary_cards(edited, headcount)

    if save_bar("md"):
        _save(edited, q)


def _to_display(df: pd.DataFrame) -> pd.DataFrame:
    """저장 형태 → 편집기 표시 형태."""
    return pd.DataFrame({
        "부서코드": df["dept_code"].astype(str),
        "부서명": df["dept_name"].astype(str),
        "표시순서": df["sort_order"].astype(int),
        "사용": df["is_active"].astype(bool),
    })


def _load_editor(q: dict) -> None:
    """조회 조건으로 대상 부서를 편집기에 적재하고, 원본 부서코드 집합을 스냅샷한다."""
    df = db.get_departments()
    if q["active"] == "사용 중":
        df = df[df["is_active"]]
    elif q["active"] == "사용 안 함":
        df = df[~df["is_active"].astype(bool)]
    df = df.sort_values("sort_order").reset_index(drop=True)

    st.session_state["md_work"] = _to_display(df)
    st.session_state["md_loaded"] = [(str(c).strip(),) for c in df["dept_code"]]
    st.session_state.pop("md_editor", None)  # 이전 편집 상태 초기화


def _summary_cards(edited: pd.DataFrame, headcount: pd.Series) -> None:
    codes = edited["부서코드"].astype(str)
    ui.summary_cards([
        ("부서", f"{len(edited)}개"),
        ("사용 중", f"{int(edited['사용'].fillna(False).astype(bool).sum())}개"),
        ("소속 인원", f"{int(headcount.reindex(codes).fillna(0).sum())}명"),
    ])
    st.write("")


def _save(edited: pd.DataFrame, q: dict) -> None:
    """편집 결과를 검증하고, 자연키 기준 upsert 로 스토어에 병합해 저장한다."""
    records, errors = _validate(edited)

    # 기존 행은 U, 신규 행은 C, 조회했다가 사라진 행은 사용=False 소프트 삭제.
    loaded = set(st.session_state.get("md_loaded", []))
    store = db.get_departments()
    merged, dup, n_c, n_u, n_d = db.upsert_records(
        store, records, loaded, ["dept_code"], "is_active", db.DEPT_COLUMNS,
    )
    if dup:
        errors.append("부서코드가 중복되었습니다: " + ", ".join(k[0] for k in dup))

    if errors:
        st.error("저장하지 못했습니다.\n\n- " + "\n- ".join(errors))
        return

    db.save_departments(merged)
    st.session_state.pop("md_editor", None)
    _load_editor(q)  # 저장된 스토어 기준으로 편집기 새로고침
    set_flash(
        "master_departments", "success",
        f"부서를 저장했습니다. (신규 {n_c} · 수정 {n_u} · 미사용 처리 {n_d})",
    )
    st.rerun()


def _validate(edited: pd.DataFrame):
    """표시 형태 → 저장 형태 변환 + 행별 기본 검증. (records, errors) 반환."""
    records, errors = [], []
    for i, (_, row) in enumerate(edited.iterrows(), start=1):
        code = str(row["부서코드"] or "").strip()
        name = str(row["부서명"] or "").strip()

        # 완전히 빈 행(새 행 자동 추가분)은 조용히 건너뛴다
        if not any([code, name]):
            continue

        tag = f"{i}행" + (f"({code})" if code else "")
        if not code:
            errors.append(f"{i}행: 부서코드를 입력하세요.")
        if not name:
            errors.append(f"{tag}: 부서명을 입력하세요.")

        try:
            so = row["표시순서"]
            sort_order = 0 if pd.isna(so) else int(so)
        except (TypeError, ValueError):
            sort_order = 0

        records.append({
            "dept_code": code,
            "dept_name": name,
            "sort_order": sort_order,
            "is_active": bool(row["사용"]),
        })
    return records, errors
