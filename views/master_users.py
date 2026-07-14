"""기준정보 — 사용자 관리: Excel 붙여넣기를 지원하는 직접 편집 그리드.

목록에서 직접 입력·수정하고 [저장]으로 일괄 반영한다(자동 저장 없음).
Excel 의 여러 행·열(탭/줄바꿈 구분)을 그대로 붙여넣을 수 있고, 마지막 빈 행에
입력하면 신규 사용자를 계속 추가할 수 있다. 사용자는 물리 삭제하지 않고
재직 여부(is_active)로 관리한다(소프트 삭제).

화면 표시 원칙:
- 조는 조코드가 아니라 조명(team_name)으로 표시하고, 저장 시 (부서, 조명)을
  team_code 로 변환한다. 조명은 관계 키가 아니다.
- 권한은 관리자/조장/조원으로 표시하고, 저장 시 ADMIN/MANAGER/USER 로 변환한다.
  DB 저장값과 권한 분기 코드는 기존 값을 유지한다.
"""
import pandas as pd
import streamlit as st

from modules import db, ui
from views.workspace import ALL, editable_aggrid, grid_bool, set_flash, show_flash

# 화면 표시 라벨 ↔ 저장 코드 매핑 (DB 값은 ADMIN/MANAGER/USER 유지)
_ROLE_TO_LABEL = {"ADMIN": "관리자", "MANAGER": "조장", "USER": "조원"}
_LABEL_TO_ROLE = {label: role for role, label in _ROLE_TO_LABEL.items()}

_COLS = ["사번", "성명", "부서", "조", "직급", "권한", "재직"]
_STATUS = ["재직", "퇴직", "전체"]


def _dept_labels(dept_names: dict[str, str]) -> dict[str, str]:
    """부서명 중복에도 안전한 편집기 표시값(code -> label)."""
    return {code: f"{name} ({code})" for code, name in dept_names.items()}


def _dept_resolver(dept_names: dict[str, str]) -> dict[str, str]:
    """입력값 -> 부서코드. 표시 라벨/코드를 허용하고, 유일한 부서명도 허용한다.

    Excel 붙여넣기는 표시 라벨이 아니라 원본 부서명이나 코드일 수 있으므로
    셀 값 해석을 관대하게 하되, 중복 부서명은 매핑하지 않는다(라벨/코드로 유도).
    """
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


def _role_resolver() -> dict[str, str]:
    """입력값 -> 권한 코드. 한글 라벨과 기존 코드(대소문자 무관)를 허용한다."""
    resolver = dict(_LABEL_TO_ROLE)
    for role in _ROLE_TO_LABEL:
        resolver[role] = role
        resolver[role.lower()] = role
    return resolver


def _grid_height(nrows: int) -> int:
    """행 수 기반 고정 높이. 화면 높이에 따라 무한정 커지지 않고 내부 스크롤한다."""
    return max(240, min(35 * (nrows + 1) + 60, 460))


def render(user: dict) -> None:
    ui.page_header("master_users")

    depts = db.get_departments()
    teams = db.get_teams()
    source_users = db.get_users()
    dept_names = {str(r["dept_code"]): str(r["dept_name"]) for _, r in depts.iterrows()}
    team_resolve, team_display = _team_maps(teams)

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
        refresh = c4.button("새로고침", key="mu_go", type="primary", width="stretch")

    # 목록 적재: 필터 변경 / 새로고침 / 최초 진입 시에만 DB 재조회.
    params = {"dept": dept, "team": team, "active": active}
    if refresh or st.session_state.get("q_master_users") != params or "mu_work" not in st.session_state:
        st.session_state["q_master_users"] = params
        _load_editor(params, dept_names, team_display, source_users)

    show_flash("master_users")

    # 요약 카드 (편집 중인 내용 기준으로 갱신)
    sum_ph = st.container()

    dept_labels = _dept_labels(dept_names)
    team_names = sorted({str(r["team_name"]) for _, r in teams.iterrows()})
    # 그리드에 전달하는 데이터(mu_work)는 조회 시점 값으로 고정한다. 편집 결과를
    # 매 rerun 그리드에 되돌려주면 컴포넌트가 재설정·재전송을 반복해 곧바로 이어지는
    # 버튼 클릭(저장 등)의 rerun 을 삼킬 수 있다. 편집 내용은 반환값(edited)으로만
    # 받고, 행 확장은 그리드 내부(JS)가 처리한다.
    nonce = st.session_state.setdefault("mu_nonce", 0)
    edited = editable_aggrid(
        st.session_state["mu_work"],
        key=f"mu_editor_{nonce}",
        columns={
            "사번": "text",
            "성명": "text",
            "부서": list(dept_labels.values()),
            "조": [""] + team_names,
            "직급": "text",
            "권한": list(_LABEL_TO_ROLE),
            "재직": "bool",
        },
        height=_grid_height(len(st.session_state["mu_work"])),
    )

    with sum_ph:
        _summary_cards(edited)

    # 셀 편집 직후(편집기 blur -> cellValueChanged 전송) 버튼을 누르면 컴포넌트
    # 데이터 전송이 클릭 rerun 을 중단시켜 버튼 상태가 소실될 수 있다. on_click
    # 콜백으로 세션에 요청 플래그를 남기면, 클릭 rerun 이 대체되더라도 다음
    # rerun(최신 그리드 데이터 포함)에서 반드시 처리된다.
    new, _space = st.columns([1, 7])
    new.button(
        "신규", key="mu_new", width="stretch",
        on_click=lambda: st.session_state.update(mu_add_row=True),
    )
    (save,) = ui.action_bar("save")
    save.button(
        "저장", key="mu_save", type="primary", width="stretch",
        on_click=lambda: st.session_state.update(mu_save_requested=True),
    )

    if st.session_state.pop("mu_add_row", False):
        # 편집 중 내용(edited)을 보존한 채 빈 행을 붙이고 그리드를 재마운트한다.
        blank = {c: (True if c == "재직" else "") for c in _COLS}
        st.session_state["mu_work"] = pd.concat(
            [edited, pd.DataFrame([blank])], ignore_index=True,
        )
        st.session_state["mu_nonce"] = nonce + 1
        st.rerun()

    if st.session_state.pop("mu_save_requested", False):
        _save(edited, params, dept_names, team_resolve, team_display)


def _to_display(df: pd.DataFrame, dept_names: dict, team_display: dict) -> pd.DataFrame:
    """저장 형태(코드) → 편집기 표시 형태(부서 라벨·조명·권한 한글)."""
    labels = _dept_labels(dept_names)
    return pd.DataFrame({
        "사번": df["emp_no"].fillna("").astype("string"),
        "성명": df["name"].fillna("").astype("string"),
        "부서": df["dept_code"].map(labels).fillna("").astype("string"),
        "조": [
            team_display.get((str(d), str(t)), str(t or ""))
            for d, t in zip(df["dept_code"], df["team_code"])
        ],
        "직급": df["position"].fillna("").astype("string"),
        "권한": df["role"].map(_ROLE_TO_LABEL).fillna("").astype("string"),
        "재직": df["is_active"].fillna(True).astype(bool),
    })


def _load_editor(q: dict, dept_names: dict, team_display: dict, source: pd.DataFrame | None = None) -> None:
    """조회 조건으로 대상 사용자를 편집기에 적재한다."""
    source = db.get_users() if source is None else source
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

    st.session_state["mu_work"] = _to_display(df, dept_names, team_display)
    st.session_state["mu_nonce"] = st.session_state.get("mu_nonce", 0) + 1


def _summary_cards(edited: pd.DataFrame) -> None:
    # 붙여넣기용 빈 행은 화면 요약과 저장 대상에서 제외한다.
    rows = edited[
        edited[["사번", "성명", "부서", "조", "직급"]]
        .fillna("")
        .astype(str)
        .apply(lambda row: row.str.strip().ne("").any(), axis=1)
    ].copy()
    roles = rows["권한"].map(_role_resolver())
    ui.summary_cards([
        ("조회 인원", f"{len(rows)}명"),
        ("재직", f"{int(rows['재직'].map(grid_bool).sum())}명"),
        ("부서", f"{rows['부서'].replace('', pd.NA).nunique()}개"),
        ("조장 이상", f"{int(roles.isin(['MANAGER', 'ADMIN']).sum())}명"),
    ])
    st.write("")


def _save(edited, q, dept_names, team_resolve, team_display) -> None:
    """편집 결과를 검증하고, 사번 기준 upsert 로 병합해 저장한다.

    검증 오류가 하나라도 있으면 아무것도 저장하지 않는다(전체 성공/전체 차단).
    필터로 보이지 않는 기존 사용자를 자동 퇴직 처리하지 않는다.
    """
    records, errors = _validate(edited, _dept_resolver(dept_names), team_resolve)

    store = db.get_users()
    merged, dup, n_c, n_u, n_d = db.upsert_records(
        store, records, set(), ["emp_no"], "is_active", db.USER_COLUMNS,
    )
    if dup:
        errors.append("사번이 중복되었습니다: " + ", ".join(k[0] for k in dup))

    if errors:
        st.error("저장하지 못했습니다.\n\n- " + "\n- ".join(errors))
        return

    db.save_users(merged)
    _load_editor(q, dept_names, team_display)  # 저장된 스토어 기준으로 편집기 새로고침
    set_flash(
        "master_users", "success",
        f"사용자를 저장했습니다. (신규 {n_c} · 수정 {n_u} · 퇴직 처리 {n_d})",
    )
    st.rerun()


def _validate(edited, dept_resolver, team_resolve):
    """표시 형태 → 저장 형태 변환 + 행별 기본 검증. (records, errors) 반환."""
    role_resolver = _role_resolver()
    records, errors = [], []
    for i, (_, row) in enumerate(edited.iterrows(), start=1):
        emp_no = str(row.get("사번") or "").strip()
        name = str(row.get("성명") or "").strip()
        dept_value = str(row.get("부서") or "").strip()
        team_value = str(row.get("조") or "").strip()
        position = str(row.get("직급") or "").strip()
        role = role_resolver.get(str(row.get("권한") or "").strip(), "")
        dept_code = dept_resolver.get(dept_value, "")

        # 완전히 빈 행(붙여넣기 버퍼/신규 행)은 조용히 건너뛴다
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

        records.append({
            "emp_no": emp_no,
            "name": name,
            "dept_code": dept_code,
            "team_code": team_code,
            "position": position,
            "role": role,
            "is_active": grid_bool(row.get("재직")),
        })
    return records, errors
