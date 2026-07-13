"""기준정보 — 사용자 관리 화면.

조회 조건으로 대상을 불러온 뒤 스프레드시트형 편집기(st.data_editor)로 등록/수정한다.
[저장] 을 눌렀을 때만 검증 후 반영하며(자동 저장 없음), 로컬 샘플 모드에서는
세션 상태(db.save_users)에 저장해 현재 세션 동안 유지된다.

사용자는 물리 삭제하지 않고 재직 여부(is_active)로 관리한다(소프트 삭제).
"""
import pandas as pd
import streamlit as st

from modules import db, ui
from views.workspace import ALL, editor_has_changes, grid_height, save_bar, set_flash, show_flash

# 화면 표시 라벨 ↔ 저장 코드 매핑
_ROLE_TO_LABEL = {"USER": "직원", "MANAGER": "매니저", "ADMIN": "관리자"}
_LABEL_TO_ROLE = {v: k for k, v in _ROLE_TO_LABEL.items()}
_VALID_ROLES = set(_ROLE_TO_LABEL)

_COLS = ["사번", "성명", "부서", "조/팀", "직급", "권한", "재직"]
_STATUS = ["재직", "퇴직", "전체"]


def render(user: dict) -> None:
    ui.page_header("master_users")

    depts = db.get_departments()
    teams = db.get_teams()
    source_users = db.get_users()
    source_signature = db.frame_signature(source_users, db.USER_COLUMNS)
    dept_names = {r["dept_code"]: r["dept_name"] for _, r in depts.iterrows()}
    name_to_code = {v: k for k, v in dept_names.items()}
    team_set = set(zip(teams["dept_code"], teams["team_code"]))
    team_codes = sorted(teams["team_code"].unique().tolist())

    # 조회 조건 카드
    with ui.card():
        c1, c2, c3, c4 = st.columns([1.6, 1.2, 1.2, 0.9], vertical_alignment="bottom")
        dept = c1.selectbox(
            "부서", [ALL] + list(dept_names), format_func=lambda c: dept_names.get(c, c),
            key="mu_dept",
        )
        team_rows = teams[teams["dept_code"] == dept] if dept != ALL else teams.iloc[0:0]
        team_opts = {r["team_code"]: r["team_name"] for _, r in team_rows.iterrows()}
        team = c2.selectbox(
            "조", [ALL] + list(team_opts), format_func=lambda c: team_opts.get(c, c),
            key="mu_team",
        )
        active = c3.selectbox("재직 여부", _STATUS, key="mu_active")
        clicked = c4.button("새로고침", key="mu_go", type="primary", width="stretch")

    # 화면 진입 시 기본 필터로 자동 조회, [새로고침] 시 현재 필터로 재조회.
    params = {"dept": dept, "team": team, "active": active}
    q = st.session_state.get("q_master_users")
    if clicked or q is None:
        q = params
        st.session_state["q_master_users"] = q
        _load_editor(q, dept_names, source_users)
    elif (
        "mu_work" not in st.session_state
        or (
            st.session_state.get("mu_source_signature") != source_signature
            and not editor_has_changes("mu_editor")
        )
    ):
        _load_editor(q, dept_names, source_users)

    show_flash("master_users")

    # 요약 카드 (편집 중인 내용 기준으로 갱신)
    sum_ph = st.container()

    # 스프레드시트형 편집 그리드 (행 추가 가능, 사용자 물리 삭제는 저장 시 차단)
    edited = st.data_editor(
        st.session_state["mu_work"],
        key="mu_editor",
        num_rows="dynamic",
        width="stretch",
        hide_index=True,
        height=grid_height(len(st.session_state["mu_work"]) + 1),
        column_config={
            "사번": st.column_config.TextColumn("사번", width="small"),
            "성명": st.column_config.TextColumn("성명", width="small"),
            "부서": st.column_config.SelectboxColumn("부서", options=list(dept_names.values())),
            "조/팀": st.column_config.SelectboxColumn("조/팀", options=[""] + team_codes, width="small"),
            "직급": st.column_config.TextColumn("직급", width="small"),
            "권한": st.column_config.SelectboxColumn("권한", options=list(_LABEL_TO_ROLE), width="small"),
            "재직": st.column_config.CheckboxColumn("재직", width="small", default=True),
        },
    )

    with sum_ph:
        _summary_cards(edited)

    if save_bar("mu"):
        _save(edited, q, dept_names, name_to_code, team_set)


def _to_display(df: pd.DataFrame, dept_names: dict) -> pd.DataFrame:
    """저장 형태(코드) → 편집기 표시 형태(라벨)."""
    return pd.DataFrame({
        "사번": df["emp_no"].astype(str),
        "성명": df["name"].astype(str),
        "부서": df["dept_code"].map(dept_names).fillna(""),
        "조/팀": df["team_code"].astype(str),
        "직급": df["position"].astype(str),
        "권한": df["role"].map(_ROLE_TO_LABEL).fillna(""),
        "재직": df["is_active"].astype(bool),
    })


def _load_editor(q: dict, dept_names: dict, source: pd.DataFrame | None = None) -> None:
    """조회 조건으로 대상 사용자를 편집기에 적재하고, 원본 사번 집합을 스냅샷한다."""
    source = db.get_users() if source is None else source
    st.session_state["mu_source_signature"] = db.frame_signature(source, db.USER_COLUMNS)
    df = source.copy()
    if q["active"] == "재직":
        df = df[df["is_active"]]
    elif q["active"] == "퇴직":
        df = df[~df["is_active"].astype(bool)]
    if q["dept"] != ALL:
        df = df[df["dept_code"] == q["dept"]]
        if q["team"] != ALL:
            df = df[df["team_code"] == q["team"]]
    df = df.sort_values(["dept_code", "team_code", "emp_no"]).reset_index(drop=True)

    st.session_state["mu_work"] = _to_display(df, dept_names)
    st.session_state["mu_loaded_emp"] = [(str(e).strip(),) for e in df["emp_no"]]
    st.session_state.pop("mu_editor", None)  # 이전 편집 상태 초기화


def _summary_cards(edited: pd.DataFrame) -> None:
    roles = edited["권한"].map(_LABEL_TO_ROLE)
    ui.summary_cards([
        ("조회 인원", f"{len(edited)}명"),
        ("재직", f"{int(edited['재직'].fillna(False).astype(bool).sum())}명"),
        ("부서", f"{edited['부서'].replace('', pd.NA).nunique()}개"),
        ("매니저 이상", f"{int(roles.isin(['MANAGER', 'ADMIN']).sum())}명"),
    ])
    st.write("")


def _save(edited, q, dept_names, name_to_code, team_set) -> None:
    """편집 결과를 검증하고, 사번 기준 upsert 로 병합해 저장한다.

    사용자는 물리 삭제하지 않는다. 그리드에서 지운 행(조회했다가 사라진 사번)은
    삭제 대신 재직 여부(is_active)를 False(퇴직)로 바꿔 보존한다.
    """
    records, errors = _validate(edited, dept_names, name_to_code, team_set)

    # 기존 사번은 U, 신규 사번은 C, 지운 사번은 재직=False 소프트 삭제.
    loaded = set(st.session_state.get("mu_loaded_emp", []))
    store = db.get_users()
    merged, dup, n_c, n_u, n_d = db.upsert_records(
        store, records, loaded, ["emp_no"], "is_active", db.USER_COLUMNS,
    )
    if dup:
        errors.append("사번이 중복되었습니다: " + ", ".join(k[0] for k in dup))

    if errors:
        st.error("저장하지 못했습니다.\n\n- " + "\n- ".join(errors))
        return

    db.save_users(merged)
    st.session_state.pop("mu_editor", None)
    _load_editor(q, dept_names)  # 저장된 스토어 기준으로 편집기 새로고침
    set_flash(
        "master_users", "success",
        f"사용자를 저장했습니다. (신규 {n_c} · 수정 {n_u} · 퇴직 처리 {n_d})",
    )
    st.rerun()


def _validate(edited, dept_names, name_to_code, team_set):
    """표시 형태 → 저장 형태 변환 + 행별 기본 검증. (records, errors) 반환."""
    records, errors = [], []
    for i, (_, row) in enumerate(edited.iterrows(), start=1):
        emp_no = str(row["사번"] or "").strip()
        name = str(row["성명"] or "").strip()
        dept_label = str(row["부서"] or "").strip()
        team_code = str(row["조/팀"] or "").strip()
        role = _LABEL_TO_ROLE.get(str(row["권한"] or "").strip(), "")
        dept_code = name_to_code.get(dept_label, "")

        # 완전히 빈 행(새 행 자동 추가분)은 조용히 건너뛴다
        if not any([emp_no, name, dept_label, team_code, str(row["직급"] or "").strip()]):
            continue

        tag = f"{i}행" + (f"({emp_no})" if emp_no else "")
        if not emp_no:
            errors.append(f"{i}행: 사번을 입력하세요.")
        if not name:
            errors.append(f"{tag}: 성명을 입력하세요.")
        if dept_code not in dept_names:
            errors.append(f"{tag}: 부서를 선택하세요.")
        elif team_code and (dept_code, team_code) not in team_set:
            errors.append(f"{tag}: 선택한 부서에 없는 조/팀입니다.")
        if role not in _VALID_ROLES:
            errors.append(f"{tag}: 권한을 선택하세요.")

        records.append({
            "emp_no": emp_no,
            "name": name,
            "dept_code": dept_code,
            "team_code": team_code,
            "position": str(row["직급"] or "").strip(),
            "role": role,
            "is_active": bool(row["재직"]),
        })
    return records, errors
