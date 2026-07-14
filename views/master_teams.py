"""기준정보 — 조 관리 화면.

조회 조건으로 대상을 불러온 뒤 스프레드시트형 편집기(st.data_editor)로 등록/수정한다.
[저장] 을 눌렀을 때만 검증 후 반영하며(자동 저장 없음), 로컬 샘플 모드에서는
세션 상태(db.save_teams)에 저장해 현재 세션 동안 유지된다.

부서 조건으로 일부만 조회했더라도 저장 시 미조회 조/팀은 그대로 보존한다
(조회 대상만 교체 후 병합). 조/팀 코드는 부서 안에서 유일해야 한다.
"""
import pandas as pd
import streamlit as st

from modules import db, ui
from views.workspace import ALL, master_data_editor, normalize_editor_text, save_bar, set_flash, show_flash

_COLS = ["부서", "조코드", "조명", "표시순서", "사용"]
_STATUS = ["사용 중", "사용 안 함", "전체"]


def render(user: dict) -> None:
    ui.page_header("master_teams")

    depts = db.get_departments()
    source_teams = db.get_teams()
    dept_names = {r["dept_code"]: r["dept_name"] for _, r in depts.iterrows()}
    name_to_code = {v: k for k, v in dept_names.items()}

    # 조회 조건 카드
    with ui.card():
        c1, c2, c3 = st.columns([1.6, 1.2, 0.9], vertical_alignment="bottom")
        dept = c1.selectbox(
            "부서", [ALL] + list(dept_names), format_func=lambda c: dept_names.get(c, c),
            key="mt_dept",
        )
        active = c2.selectbox("사용 여부", _STATUS, key="mt_active")
        clicked = c3.button("새로고침", key="mt_go", type="primary", width="stretch")

    # 화면 진입 시 기본 필터로 자동 조회, [새로고침] 시 현재 필터로 재조회.
    params = {"dept": dept, "active": active}
    q = st.session_state.get("q_master_teams")
    if clicked or q is None or q != params:
        q = params
        st.session_state["q_master_teams"] = q
        _load_editor(q, dept_names, source_teams)
    elif "mt_work" not in st.session_state:
        _load_editor(q, dept_names, source_teams)

    show_flash("master_teams")

    users = db.get_users()
    headcount = users[users["is_active"]].groupby(["dept_code", "team_code"]).size()

    # 요약 카드 (편집 중인 내용 기준으로 갱신)
    sum_ph = st.container()

    # 스프레드시트형 편집 그리드 (행 추가 가능)
    edited = master_data_editor(
        st.session_state["mt_work"],
        key="mt_editor",
        num_rows="dynamic",
        width="stretch",
        hide_index=True,
        column_config={
            "부서": st.column_config.SelectboxColumn("부서", options=list(dept_names.values()), default=""),
            "조코드": st.column_config.TextColumn("조코드", width="small", default=""),
            "조명": st.column_config.TextColumn("조명", width="small", default=""),
            "표시순서": st.column_config.NumberColumn(
                "표시순서", width="small", min_value=0, step=1,
            ),
            "사용": st.column_config.CheckboxColumn("사용", width="small", default=True),
        },
    )

    edited = normalize_editor_text(edited, ["부서", "조코드", "조명"])

    with sum_ph:
        _summary_cards(edited, name_to_code, headcount)

    if save_bar("mt"):
        _save(edited, q, dept_names, name_to_code)


def _to_display(df: pd.DataFrame, dept_names: dict) -> pd.DataFrame:
    """저장 형태(코드) → 편집기 표시 형태(라벨)."""
    return pd.DataFrame({
        "부서": df["dept_code"].map(dept_names).fillna("").astype("string"),
        "조코드": df["team_code"].fillna("").astype("string"),
        "조명": df["team_name"].fillna("").astype("string"),
        "표시순서": df["sort_order"].astype(int),
        "사용": df["is_active"].astype(bool),
    })


def _load_editor(q: dict, dept_names: dict, source: pd.DataFrame | None = None) -> None:
    """조회 조건으로 대상 조/팀을 편집기에 적재하고, 원본 (부서,조코드) 집합을 스냅샷한다."""
    source = db.get_teams() if source is None else source
    df = source.copy()
    if q["dept"] != ALL:
        df = df[df["dept_code"] == q["dept"]]
    if q.get("active") == "사용 중":
        df = df[df["is_active"].astype(bool)]
    elif q.get("active") == "사용 안 함":
        df = df[~df["is_active"].astype(bool)]
    df = df.sort_values(["dept_code", "sort_order"]).reset_index(drop=True)

    st.session_state["mt_work"] = _to_display(df, dept_names)
    st.session_state["mt_loaded"] = [
        (str(d).strip(), str(t).strip()) for d, t in zip(df["dept_code"], df["team_code"])
    ]
    st.session_state.pop("mt_editor", None)  # 이전 편집 상태 초기화


def _summary_cards(edited: pd.DataFrame, name_to_code: dict, headcount: pd.Series) -> None:
    codes = edited["부서"].map(name_to_code)
    total = 0
    for dept_code, team_code in zip(codes, edited["조코드"].astype(str)):
        total += int(headcount.get((dept_code, team_code), 0))
    ui.summary_cards([
        ("조", f"{len(edited)}개"),
        ("사용 중", f"{int(edited['사용'].fillna(False).astype(bool).sum())}개"),
        ("부서", f"{codes.replace('', pd.NA).nunique()}개"),
        ("소속 인원", f"{total}명"),
    ])
    st.write("")


def _save(edited, q, dept_names, name_to_code) -> None:
    """편집 결과를 검증하고, 자연키(부서+조코드) 기준 upsert 로 병합해 저장한다."""
    records, errors = _validate(edited, dept_names, name_to_code)

    # 기존 행은 U, 신규 행은 C, 조회했다가 사라진 행은 사용=False 소프트 삭제.
    # 조/팀 코드는 부서 안에서 유일해야 하므로 (부서, 조코드)를 자연키로 쓴다.
    loaded = set(st.session_state.get("mt_loaded", []))
    store = db.get_teams()
    merged, dup, n_c, n_u, n_d = db.upsert_records(
        store, records, loaded, ["dept_code", "team_code"], "is_active", db.TEAM_COLUMNS,
    )
    if dup:
        labels = ", ".join(f"{dept_names.get(d, d)}/{t}" for d, t in dup)
        errors.append(f"같은 부서에 조/팀 코드가 중복되었습니다: {labels}")

    if errors:
        st.error("저장하지 못했습니다.\n\n- " + "\n- ".join(errors))
        return

    db.save_teams(merged)
    st.session_state.pop("mt_editor", None)
    _load_editor(q, dept_names)  # 저장된 스토어 기준으로 편집기 새로고침
    set_flash(
        "master_teams", "success",
        f"조/팀을 저장했습니다. (신규 {n_c} · 수정 {n_u} · 미사용 처리 {n_d})",
    )
    st.rerun()


def _validate(edited, dept_names, name_to_code):
    """표시 형태 → 저장 형태 변환 + 행별 기본 검증. (records, errors) 반환."""
    records, errors = [], []
    for i, (_, row) in enumerate(edited.iterrows(), start=1):
        dept_label = str(row["부서"] or "").strip()
        team_code = str(row["조코드"] or "").strip()
        team_name = str(row["조명"] or "").strip()
        dept_code = name_to_code.get(dept_label, "")

        # 완전히 빈 행(새 행 자동 추가분)은 조용히 건너뛴다
        if not any([dept_label, team_code, team_name]):
            continue

        tag = f"{i}행" + (f"({team_code})" if team_code else "")
        if not team_code:
            errors.append(f"{i}행: 조/팀 코드를 입력하세요.")
        if not team_name:
            errors.append(f"{tag}: 조/팀명을 입력하세요.")
        if not dept_label:
            errors.append(f"{tag}: 부서를 선택하세요.")
        elif dept_code not in dept_names:
            errors.append(f"{tag}: 부서 기준정보에 없는 부서입니다.")

        try:
            so = row["표시순서"]
            sort_order = 0 if pd.isna(so) else int(so)
        except (TypeError, ValueError):
            sort_order = 0

        records.append({
            "dept_code": dept_code,
            "team_code": team_code,
            "team_name": team_name,
            "sort_order": sort_order,
            "is_active": bool(row["사용"]),
        })
    return records, errors
