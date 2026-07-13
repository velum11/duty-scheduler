"""근무표 관리 — 근무표 등록/수정 화면 (1차).

연도·월·부서·조/팀을 선택하면 해당 조의 재직 직원 월간 근무표를 가로형
스프레드시트로 불러온다. 셀에 근무형태 코드(또는 약칭)를 입력·수정하고 [저장]을
눌렀을 때만 반영한다(자동 저장 없음). 저장 계층은 세로형(long) — 사번 | 근무일자 |
근무형태 (docs/database.md §5.4) — 이며, 로컬 샘플 모드에서는 db 세션 스토어에만
저장한다(CSV 는 건드리지 않음).

저장 범위는 (선택 직원 × 선택 월)로 한정한다. 이 범위의 근무표는 화면에 보이는
그리드 내용으로 교체하고, 다른 월·다른 직원의 근무표는 그대로 보존한다.
등록된 근무형태 코드/약칭이 아닌 값이 있으면 저장을 차단한다.
"""
import calendar
from datetime import date

import pandas as pd
import streamlit as st

from modules import db, ui
from views.workspace import grid_height, save_bar, set_flash, show_flash

_FIXED = ["사번", "성명", "조/팀"]


def render(user: dict) -> None:
    ui.page_header("schedule_edit")

    depts = db.get_departments()
    teams = db.get_teams()
    today = date.today()

    active_depts = depts[depts["is_active"]].sort_values("sort_order")
    dept_names = {r["dept_code"]: r["dept_name"] for _, r in active_depts.iterrows()}
    if not dept_names:
        ui.empty_state("등록된 부서가 없습니다. 먼저 기준정보에서 부서를 등록하세요.", head="월별 근무표")
        return

    manager_locked = user["role"] == "MANAGER" and user.get("dept_code") in dept_names
    years = list(range(today.year - 1, today.year + 2))

    # 조회 조건 카드
    with ui.card():
        c1, c2, c3, c4, c5 = st.columns([1, 1, 1.6, 1.2, 0.9], vertical_alignment="bottom")
        year = c1.selectbox("연도", years, index=years.index(today.year), key="se_y")
        month = c2.selectbox(
            "월", list(range(1, 13)), index=today.month - 1,
            format_func=lambda m: f"{m}월", key="se_m",
        )
        if manager_locked:
            dept = c3.selectbox(
                "부서", [user["dept_code"]], format_func=lambda c: dept_names.get(c, c),
                key="se_d", disabled=True,
            )
        else:
            dept = c3.selectbox(
                "부서", list(dept_names), format_func=lambda c: dept_names.get(c, c),
                key="se_d",
            )
        team_rows = teams[(teams["dept_code"] == dept) & teams["is_active"]].sort_values("sort_order")
        team_names = {r["team_code"]: r["team_name"] for _, r in team_rows.iterrows()}
        team = c4.selectbox(
            "조", list(team_names), format_func=lambda c: team_names.get(c, c), key="se_t",
        )
        clicked = c5.button("새로고침", key="se_go", type="primary", width="stretch")

    show_flash("schedule_edit")

    if team is None:
        ui.empty_state("선택한 부서에 등록된 조/팀이 없습니다.", head="월별 근무표")
        return

    # 화면 진입 시 기본 조건(현재 연월 · 첫 부서/조)으로 자동 조회, [새로고침] 시 재조회.
    params = {"year": year, "month": month, "dept": dept, "team": team}
    q = st.session_state.get("q_schedule_edit")
    if clicked or q is None:
        q = params
        st.session_state["q_schedule_edit"] = q
        _load_grid(q)
    elif "se_grid" not in st.session_state:  # 조건만 남고 편집본이 없을 때
        _load_grid(q)

    grid = st.session_state["se_grid"]
    if grid.empty:
        ui.empty_state("조회 조건에 해당하는 재직 직원이 없습니다.", head="월별 근무표")
        return

    # 요약 카드 + 스프레드시트형 편집 그리드
    sum_ph = st.container()
    day_cols = [c for c in grid.columns if c not in _FIXED]
    column_config = {
        "사번": st.column_config.TextColumn("사번", width="small"),
        "성명": st.column_config.TextColumn("성명", width="small"),
        "조/팀": st.column_config.TextColumn("조/팀", width="small"),
    }
    for c in day_cols:
        column_config[c] = st.column_config.TextColumn(c, width="small")

    edited = st.data_editor(
        grid,
        key="se_editor",
        num_rows="fixed",
        width="stretch",
        hide_index=True,
        height=grid_height(len(grid)),
        column_config=column_config,
        disabled=_FIXED,
    )

    with sum_ph:
        _summary_cards(q, edited, day_cols)
        st.write("")

    st.markdown(ui.legend_html(db.work_types_map()), unsafe_allow_html=True)
    ui.sample_mode_banner()

    if save_bar("se"):
        _save(edited, q)


def _build_grid(q: dict):
    """선택 조건의 재직 직원 월간 근무표(가로형)와 날짜열→ISO 매핑을 만든다."""
    users = db.get_users()
    users = users[users["is_active"]]
    users = users[(users["dept_code"] == q["dept"]) & (users["team_code"] == q["team"])]
    users = users.sort_values("emp_no")

    scheds = db.get_schedules()
    prefix = f"{q['year']:04d}-{q['month']:02d}"
    if not scheds.empty:
        scheds = scheds[
            scheds["duty_date"].str.startswith(prefix)
            & scheds["emp_no"].isin(users["emp_no"])
        ]
    lookup = {(r["emp_no"], r["duty_date"]): r["work_type_code"] for _, r in scheds.iterrows()}

    ndays = calendar.monthrange(q["year"], q["month"])[1]
    days = []  # (컬럼명, ISO 날짜)
    for d in range(1, ndays + 1):
        dt = date(q["year"], q["month"], d)
        days.append((f"{d}({ui.weekday_kr(dt)})", dt.isoformat()))

    rows = []
    for _, u in users.iterrows():
        row = {
            "사번": u["emp_no"],
            "성명": u["name"],
            "조/팀": db.team_name(u["dept_code"], u["team_code"]),
        }
        for col, iso in days:
            row[col] = str(lookup.get((u["emp_no"], iso), "") or "")
        rows.append(row)

    cols = _FIXED + [c for c, _ in days]
    return pd.DataFrame(rows, columns=cols), days


def _load_grid(q: dict) -> None:
    grid, days = _build_grid(q)
    st.session_state["se_grid"] = grid
    st.session_state["se_days"] = days
    st.session_state.pop("se_editor", None)  # 이전 편집 상태 초기화


def _summary_cards(q: dict, edited: pd.DataFrame, day_cols: list) -> None:
    ndays = len(day_cols)
    total = len(edited) * ndays
    filled = int(edited[day_cols].apply(
        lambda col: col.map(lambda v: bool(str(v).strip()) if pd.notna(v) else False)
    ).sum().sum()) if day_cols else 0
    ui.summary_cards([
        ("대상 인원", f"{len(edited)}명"),
        ("대상 월", f"{q['year']}-{q['month']:02d}"),
        ("입력 일수", f"{filled}건"),
        ("미입력", f"{total - filled}건"),
    ])


def _allowed_map() -> dict:
    """사용 중 근무형태의 입력 허용값 → 저장 코드 매핑 (코드 및 약칭 모두 허용)."""
    wt = db.get_work_types()
    if wt.empty:
        return {}
    active = wt[wt["is_active"]]
    norm = {}
    for _, r in active.iterrows():
        code = str(r["code"]).strip()
        if code:
            norm[code] = code
    for _, r in active.iterrows():  # 코드 우선, 약칭은 미충돌 시 보조 허용
        code = str(r["code"]).strip()
        sl = str(r["short_label"]).strip()
        if code and sl:
            norm.setdefault(sl, code)
    return norm


def _save(edited: pd.DataFrame, q: dict) -> None:
    """편집 결과를 검증하고 (선택 직원 × 선택 월) 범위만 교체해 저장한다."""
    day_isos = dict(st.session_state.get("se_days", []))
    norm = _allowed_map()
    day_cols = [c for c in edited.columns if c not in _FIXED]

    records, errors = [], []
    for _, row in edited.iterrows():
        emp_no = str(row["사번"]).strip()
        if not emp_no:
            continue
        for col in day_cols:
            raw = row[col]
            val = "" if pd.isna(raw) else str(raw).strip()
            if not val:
                continue
            if val not in norm:
                errors.append(f"{row['성명']}({emp_no}) {col}: 알 수 없는 근무형태 '{val}'")
                continue
            records.append({
                "emp_no": emp_no,
                "duty_date": day_isos[col],
                "work_type_code": norm[val],
                "note": "",
            })

    if errors:
        head = "저장하지 못했습니다. 기준정보에 등록된 근무형태 코드 또는 약칭만 입력할 수 있습니다."
        shown = errors[:20]
        more = f"\n- 외 {len(errors) - 20}건" if len(errors) > 20 else ""
        st.error(head + "\n\n- " + "\n- ".join(shown) + more)
        return

    # (선택 직원 × 선택 월) 범위만 repository 계층에서 교체한다.
    emp_nos = [str(e).strip() for e in edited["사번"] if str(e).strip()]
    db.replace_month_schedules(emp_nos, q["year"], q["month"], records)

    st.session_state.pop("se_editor", None)
    _load_grid(q)  # 저장된 스토어 기준으로 편집기 새로고침
    set_flash("schedule_edit", "success", f"근무표를 저장했습니다. (근무 {len(records)}건)")
    st.rerun()
