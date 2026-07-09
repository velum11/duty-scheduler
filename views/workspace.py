"""근무표/기준정보 업무 화면 (공통 프레임).

모든 화면이 DESIGN.md §10 공통 구조를 따른다:
  페이지 제목 → 한 줄 설명 → 조회 조건 카드 → 요약 카드 → 데이터 그리드 → 하단 액션.

이 단계에서는 조회 흐름까지 구현한다 — 필터를 선택하고 [조회]를 눌렀을 때만
데이터를 표시하고(자동 조회 없음), 그리드는 읽기 전용으로 근무코드 색상을 입힌다.
기준정보/근무표의 등록·수정 저장 로직은 이후 단계에서 이 화면 위에 얹는다.
"""
import calendar
from datetime import date

import pandas as pd
import streamlit as st

from modules import db, ui

_ALL = "(전체)"


def render(user: dict, page_id: str) -> None:
    ui.page_header(page_id)
    if page_id in ("schedule_edit", "schedule_view"):
        _schedule_screen(user, page_id)
    elif page_id == "master_users":
        _master_users()
    elif page_id == "master_departments":
        _master_departments()
    elif page_id == "master_teams":
        _master_teams()
    elif page_id == "master_work_types":
        _master_work_types()
    else:
        ui.empty_state("이 화면에 접근할 권한이 없습니다.")


# ---------- 조회 상태 (명시적 [조회] 버튼으로만 갱신) ----------
def _run_query(page_id: str, clicked: bool, params: dict):
    """[조회] 클릭 시 조건을 세션에 저장하고, 저장된 조건을 반환한다."""
    key = f"q_{page_id}"
    if clicked:
        st.session_state[key] = params
    return st.session_state.get(key)


# ---------- 근무표 등록/수정 · 전체 근무표 조회 ----------
def _schedule_screen(user: dict, page_id: str) -> None:
    scheds = db.get_schedules()
    depts = db.get_departments()
    teams = db.get_teams()
    today = date.today()

    months = sorted({s[:7] for s in scheds["duty_date"]}) if not scheds.empty else []
    years = sorted({int(m[:4]) for m in months} | {today.year})

    dept_names = {r["dept_code"]: r["dept_name"] for _, r in depts.iterrows()}
    manager_locked = user["role"] == "MANAGER" and user.get("dept_code")

    # 조회 조건 카드
    with ui.card():
        c1, c2, c3, c4, c5 = st.columns([1, 1, 1.6, 1.2, 0.9], vertical_alignment="bottom")
        year = c1.selectbox("연도", years, index=years.index(today.year), key=f"{page_id}_y")
        month = c2.selectbox(
            "월", list(range(1, 13)), index=today.month - 1,
            format_func=lambda m: f"{m}월", key=f"{page_id}_m",
        )
        if manager_locked:
            dept = c3.selectbox(
                "부서", [user["dept_code"]], format_func=lambda c: dept_names.get(c, c),
                key=f"{page_id}_d", disabled=True,
            )
        else:
            dept_opts = [_ALL] + list(dept_names)
            dept = c3.selectbox(
                "부서", dept_opts, format_func=lambda c: dept_names.get(c, c),
                key=f"{page_id}_d",
            )
        team_rows = teams[teams["dept_code"] == dept] if dept != _ALL else teams.iloc[0:0]
        team_names = {r["team_code"]: r["team_name"] for _, r in team_rows.iterrows()}
        team = c4.selectbox(
            "조", [_ALL] + list(team_names), format_func=lambda c: team_names.get(c, c),
            key=f"{page_id}_t",
        )
        clicked = c5.button("조회", key=f"{page_id}_go", type="primary", width="stretch")

    q = _run_query(page_id, clicked, {"year": year, "month": month, "dept": dept, "team": team})
    if not q:
        ui.empty_state("조회 조건을 선택한 후 조회하세요.")
        return

    grid, month_rows = _build_month_grid(q)
    if grid.empty:
        ui.empty_state("조회 조건에 해당하는 직원이 없습니다.")
        return

    # 요약 카드
    wt = db.work_types_map()
    n_work = sum(1 for c in month_rows["work_type_code"] if wt.get(c, {}).get("is_work"))
    ui.summary_cards([
        ("대상 인원", f"{len(grid)}명"),
        ("근무 데이터", f"{len(month_rows)}건"),
        ("실근무", f"{n_work}건"),
        ("휴무·휴가", f"{len(month_rows) - n_work}건"),
    ])
    st.write("")

    # 데이터 그리드 (근무코드 색상, 읽기 전용)
    day_cols = [c for c in grid.columns if c[0].isdigit()]
    styled = grid.style.map(lambda v: _cell_style(v, wt), subset=day_cols)
    st.dataframe(styled, width="stretch", hide_index=True, height=_grid_height(len(grid)))
    st.markdown(ui.legend_html(wt), unsafe_allow_html=True)

    # 사용자별 집계 (전체 근무표 조회)
    if page_id == "schedule_view" and not month_rows.empty:
        st.markdown("<div class='page-desc' style='margin-top:0.8rem'>직원별 근무형태 집계</div>",
                    unsafe_allow_html=True)
        agg = _build_agg(grid, month_rows, wt)
        st.dataframe(agg, width="stretch", hide_index=True, height=_grid_height(len(agg)))

    # 하단 액션
    (dl,) = ui.action_bar("download")
    with dl:
        st.download_button(
            "엑셀 다운로드",
            grid.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"근무표_{q['year']}-{q['month']:02d}.csv",
            mime="text/csv",
            key=f"{page_id}_dl",
            width="stretch",
        )


def _build_month_grid(q: dict):
    """해당 월/부서/조의 가로형 근무표 DataFrame 과 세로형 원본 레코드를 반환."""
    users = db.get_users()
    users = users[users["is_active"]]
    if q["dept"] != _ALL:
        users = users[users["dept_code"] == q["dept"]]
        if q["team"] != _ALL:
            users = users[users["team_code"] == q["team"]]
    users = users.sort_values(["dept_code", "team_code", "emp_no"])

    scheds = db.get_schedules()
    prefix = f"{q['year']:04d}-{q['month']:02d}"
    if not scheds.empty:
        scheds = scheds[
            scheds["duty_date"].str.startswith(prefix)
            & scheds["emp_no"].isin(users["emp_no"])
        ]

    lookup = {(r["emp_no"], r["duty_date"]): r["work_type_code"] for _, r in scheds.iterrows()}
    ndays = calendar.monthrange(q["year"], q["month"])[1]
    days = [date(q["year"], q["month"], d) for d in range(1, ndays + 1)]

    rows = []
    for _, u in users.iterrows():
        row = {
            "사번": u["emp_no"],
            "성명": u["name"],
            "부서": db.dept_name(u["dept_code"]),
            "조/팀": db.team_name(u["dept_code"], u["team_code"]),
        }
        for d in days:
            row[f"{d.day}({ui.weekday_kr(d)})"] = lookup.get((u["emp_no"], d.isoformat()), "")
        rows.append(row)
    return pd.DataFrame(rows), scheds


def _build_agg(grid: pd.DataFrame, month_rows: pd.DataFrame, wt: dict) -> pd.DataFrame:
    """직원별 근무형태 집계표: 성명 | 코드별 건수 | 계."""
    codes = [c for c in wt if c in set(month_rows["work_type_code"])]
    pivot = (
        month_rows.groupby(["emp_no", "work_type_code"]).size().unstack(fill_value=0)
    )
    rows = []
    for _, g in grid.iterrows():
        counts = pivot.loc[g["사번"]] if g["사번"] in pivot.index else None
        row = {"사번": g["사번"], "성명": g["성명"]}
        total = 0
        for c in codes:
            n = int(counts[c]) if counts is not None and c in counts else 0
            row[c] = n
            total += n
        row["계"] = total
        rows.append(row)
    return pd.DataFrame(rows)


def _cell_style(value, wt: dict) -> str:
    info = wt.get(str(value).strip())
    if not info:
        return ""
    return f"background-color:{info['color']}26; color:#1F2328; font-weight:600"


def _grid_height(nrows: int) -> int:
    return min(38 * nrows + 40, 560)


# ---------- 기준정보: 사용자 관리 ----------
def _master_users() -> None:
    users = db.get_users()
    depts = db.get_departments()
    teams = db.get_teams()
    dept_names = {r["dept_code"]: r["dept_name"] for _, r in depts.iterrows()}

    with ui.card():
        c1, c2, c3, c4 = st.columns([1.6, 1.2, 1.2, 0.9], vertical_alignment="bottom")
        dept = c1.selectbox(
            "부서", [_ALL] + list(dept_names), format_func=lambda c: dept_names.get(c, c),
            key="mu_dept",
        )
        team_rows = teams[teams["dept_code"] == dept] if dept != _ALL else teams.iloc[0:0]
        team_names = {r["team_code"]: r["team_name"] for _, r in team_rows.iterrows()}
        team = c2.selectbox(
            "조", [_ALL] + list(team_names), format_func=lambda c: team_names.get(c, c),
            key="mu_team",
        )
        active = c3.selectbox("재직 여부", ["재직만", "전체"], key="mu_active")
        clicked = c4.button("조회", key="mu_go", type="primary", width="stretch")

    q = _run_query("master_users", clicked, {"dept": dept, "team": team, "active": active})
    if not q:
        ui.empty_state("조회 조건을 선택한 후 조회하세요.")
        return

    df = users.copy()
    if q["active"] == "재직만":
        df = df[df["is_active"]]
    if q["dept"] != _ALL:
        df = df[df["dept_code"] == q["dept"]]
        if q["team"] != _ALL:
            df = df[df["team_code"] == q["team"]]

    ui.summary_cards([
        ("조회 인원", f"{len(df)}명"),
        ("재직", f"{int(df['is_active'].sum())}명"),
        ("부서", f"{df['dept_code'].nunique()}개"),
        ("매니저 이상", f"{int(df['role'].isin(['MANAGER', 'ADMIN']).sum())}명"),
    ])
    st.write("")

    view = pd.DataFrame({
        "사번": df["emp_no"],
        "성명": df["name"],
        "부서": df["dept_code"].map(db.dept_name),
        "조/팀": [db.team_name(d, t) for d, t in zip(df["dept_code"], df["team_code"])],
        "직급": df["position"],
        "권한": df["role"].map(ui.role_label),
        "재직": df["is_active"].map({True: "재직", False: "퇴직"}),
    })
    st.dataframe(view, width="stretch", hide_index=True, height=_grid_height(len(view)))
    _master_download(view, "사용자목록", "mu_dl")


# ---------- 기준정보: 부서 관리 ----------
def _master_departments() -> None:
    users = db.get_users()
    with ui.card():
        c1, c2 = st.columns([1.4, 0.9], vertical_alignment="bottom")
        active = c1.selectbox("사용 여부", ["사용 중", "전체"], key="md_active")
        clicked = c2.button("조회", key="md_go", type="primary", width="stretch")

    q = _run_query("master_departments", clicked, {"active": active})
    if not q:
        ui.empty_state("조회 조건을 선택한 후 조회하세요.")
        return

    df = db.get_departments()
    if q["active"] == "사용 중":
        df = df[df["is_active"]]
    headcount = users[users["is_active"]].groupby("dept_code").size()

    ui.summary_cards([
        ("부서", f"{len(df)}개"),
        ("사용 중", f"{int(df['is_active'].sum())}개"),
        ("소속 인원", f"{int(headcount.reindex(df['dept_code']).fillna(0).sum())}명"),
    ])
    st.write("")

    view = pd.DataFrame({
        "부서코드": df["dept_code"],
        "부서명": df["dept_name"],
        "표시순서": df["sort_order"],
        "소속 인원": df["dept_code"].map(headcount).fillna(0).astype(int),
        "사용": df["is_active"].map({True: "사용", False: "미사용"}),
    })
    st.dataframe(view, width="stretch", hide_index=True, height=_grid_height(len(view)))
    _master_download(view, "부서목록", "md_dl")


# ---------- 기준정보: 조 관리 ----------
def _master_teams() -> None:
    depts = db.get_departments()
    users = db.get_users()
    dept_names = {r["dept_code"]: r["dept_name"] for _, r in depts.iterrows()}

    with ui.card():
        c1, c2 = st.columns([1.6, 0.9], vertical_alignment="bottom")
        dept = c1.selectbox(
            "부서", [_ALL] + list(dept_names), format_func=lambda c: dept_names.get(c, c),
            key="mt_dept",
        )
        clicked = c2.button("조회", key="mt_go", type="primary", width="stretch")

    q = _run_query("master_teams", clicked, {"dept": dept})
    if not q:
        ui.empty_state("조회 조건을 선택한 후 조회하세요.")
        return

    df = db.get_teams()
    if q["dept"] != _ALL:
        df = df[df["dept_code"] == q["dept"]]
    active_users = users[users["is_active"]]
    headcount = active_users.groupby(["dept_code", "team_code"]).size()

    ui.summary_cards([
        ("조", f"{len(df)}개"),
        ("부서", f"{df['dept_code'].nunique()}개"),
        ("소속 인원", f"{int(sum(headcount.get((d, t), 0) for d, t in zip(df['dept_code'], df['team_code'])))}명"),
    ])
    st.write("")

    view = pd.DataFrame({
        "부서": df["dept_code"].map(db.dept_name),
        "조코드": df["team_code"],
        "조명": df["team_name"],
        "표시순서": df["sort_order"],
        "소속 인원": [int(headcount.get((d, t), 0)) for d, t in zip(df["dept_code"], df["team_code"])],
        "사용": df["is_active"].map({True: "사용", False: "미사용"}),
    })
    st.dataframe(view, width="stretch", hide_index=True, height=_grid_height(len(view)))
    _master_download(view, "조목록", "mt_dl")


# ---------- 기준정보: 근무형태 관리 ----------
def _master_work_types() -> None:
    with ui.card():
        c1, c2 = st.columns([1.4, 0.9], vertical_alignment="bottom")
        active = c1.selectbox("사용 여부", ["사용 중", "전체"], key="mw_active")
        clicked = c2.button("조회", key="mw_go", type="primary", width="stretch")

    q = _run_query("master_work_types", clicked, {"active": active})
    if not q:
        ui.empty_state("조회 조건을 선택한 후 조회하세요.")
        return

    df = db.get_work_types()
    if q["active"] == "사용 중":
        df = df[df["is_active"]]

    ui.summary_cards([
        ("근무형태", f"{len(df)}개"),
        ("실근무 코드", f"{int(df['is_work'].sum())}개"),
        ("휴무·휴가 코드", f"{int((~df['is_work']).sum())}개"),
    ])
    st.write("")

    view = pd.DataFrame({
        "코드": df["code"],
        "명칭": df["name"],
        "시작": df["start_time"],
        "종료": df["end_time"],
        "색상": df["color"],
        "실근무": df["is_work"].map({True: "실근무", False: "휴무성"}),
        "표시순서": df["sort_order"],
        "사용": df["is_active"].map({True: "사용", False: "미사용"}),
    })
    st.dataframe(view, width="stretch", hide_index=True, height=_grid_height(len(view)))

    badges = "".join(ui.badge_html(r["code"], r["color"]) for _, r in df.iterrows())
    st.markdown(f"<div class='duty-legend'>{badges}</div>", unsafe_allow_html=True)
    _master_download(view, "근무형태목록", "mw_dl")


def _master_download(view: pd.DataFrame, name: str, key: str) -> None:
    """하단 액션 버튼 영역 (기준정보 공통)."""
    (dl,) = ui.action_bar("download")
    with dl:
        st.download_button(
            "엑셀 다운로드",
            view.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"{name}.csv",
            mime="text/csv",
            key=key,
            width="stretch",
        )
