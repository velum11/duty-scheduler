"""근무표/기준정보 업무 화면이 공유하는 공통 프레임과 헬퍼.

화면별 파일(schedule_edit, schedule_view, master_*)은 각자 render() 만 두고,
아래 공통 요소를 조합해 DESIGN.md §10 구조를 구성한다:
  페이지 제목 → 한 줄 설명 → 조회 조건 카드 → 요약 카드 → 데이터 그리드 → 하단 액션.

조회는 명시적 [조회] 버튼으로만 갱신하며(자동 조회 없음), 그리드는 읽기 전용으로
근무코드 색상을 입힌다. 기준정보/근무표의 등록·수정 저장 로직은 이후 단계에서
이 화면 위에 얹는다.
"""
import calendar
from datetime import date

import pandas as pd
import streamlit as st

from modules import db, ui

ALL = "(전체)"


def editor_has_changes(key: str) -> bool:
    """data_editor의 미저장 추가·수정·삭제가 있는지 확인한다."""
    state = st.session_state.get(key)
    if not isinstance(state, dict):
        return False
    return any(state.get(field) for field in ("edited_rows", "added_rows", "deleted_rows"))


# ---------- 조회 상태 (명시적 [조회] 버튼으로만 갱신) ----------
def run_query(page_id: str, clicked: bool, params: dict):
    """[조회] 클릭 시 조건을 세션에 저장하고, 저장된 조건을 반환한다."""
    key = f"q_{page_id}"
    if clicked:
        st.session_state[key] = params
    return st.session_state.get(key)


def grid_height(nrows: int) -> int:
    return min(38 * nrows + 40, 560)


# ---------- 편집 화면 공통 (기준정보 등록/수정) ----------
def master_editor_height() -> int:
    """기준정보 편집기의 작은 화면용 안전한 최소 높이."""
    return 360


def master_editor_container():
    """뷰포트에 맞춰 확장되는 기준정보 편집기 컨테이너."""
    st.markdown(
        """
        <style>
        .st-key-master_editor div[data-testid="stDataFrame"],
        .st-key-master_editor div[data-testid="stDataFrameResizable"] {
          height: clamp(360px, calc(100dvh - 27rem), 760px) !important;
          min-height: 360px;
        }
        .st-key-master_editor div[data-testid="stDataFrame"] > div {
          height: 100% !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    return st.container(key="master_editor")


def master_data_editor(data, **kwargs):
    """공통 반응형 컨테이너 안에 기준정보 data_editor를 배치한다."""
    with master_editor_container():
        return st.data_editor(data, height=master_editor_height(), **kwargs)


def normalize_editor_text(df: pd.DataFrame, columns) -> pd.DataFrame:
    """data_editor의 텍스트 셀을 빈 문자열 기반 string dtype으로 정규화한다."""
    frame = df.copy()
    for column in columns:
        frame[column] = frame[column].fillna("").astype("string")
    return frame


def set_flash(page_id: str, kind: str, text: str) -> None:
    """저장 결과 메시지를 다음 rerun 에서 1회 표시하도록 세션에 담는다.

    kind 는 st 의 메서드명("success" / "warning" / "error")."""
    st.session_state[f"flash_{page_id}"] = (kind, text)


def show_flash(page_id: str) -> None:
    msg = st.session_state.pop(f"flash_{page_id}", None)
    if msg:
        kind, text = msg
        getattr(st, kind)(text)


def save_bar(page_id: str) -> bool:
    """편집 그리드 하단 [저장] 액션. 클릭 여부를 반환한다."""
    (save,) = ui.action_bar("save")
    with save:
        return st.button("저장", key=f"{page_id}_save", type="primary", width="stretch")


def master_download(view: pd.DataFrame, name: str, key: str) -> None:
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


# ---------- 근무표 등록/수정 · 전체 근무표 조회 (공통 본문) ----------
def schedule_screen(user: dict, page_id: str) -> None:
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
        c1, c2, c3, c4, c5, c6 = st.columns(
            [0.9, 0.9, 1.5, 1.1, 1.6, 0.8],
            vertical_alignment="bottom",
        )
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
            dept_opts = [ALL] + list(dept_names)
            dept = c3.selectbox(
                "부서", dept_opts, format_func=lambda c: dept_names.get(c, c),
                key=f"{page_id}_d",
            )
        team_rows = teams[teams["dept_code"] == dept] if dept != ALL else teams.iloc[0:0]
        team_names = {r["team_code"]: r["team_name"] for _, r in team_rows.iterrows()}
        team = c4.selectbox(
            "조", [ALL] + list(team_names), format_func=lambda c: team_names.get(c, c),
            key=f"{page_id}_t",
        )
        keyword = c5.text_input(
            "사번 또는 성명",
            key=f"{page_id}_kw",
            placeholder="전체",
        )
        clicked = c6.button("조회", key=f"{page_id}_go", type="primary", width="stretch")

    q = run_query(
        page_id,
        clicked,
        {
            "year": year,
            "month": month,
            "dept": dept,
            "team": team,
            "keyword": keyword.strip(),
        },
    )
    if not q:
        ui.empty_state("조회 조건을 선택한 후 조회하세요.", head="월별 근무표")
        return

    grid, month_rows = _build_month_grid(q)
    if grid.empty:
        ui.empty_state("조회 조건에 해당하는 직원이 없습니다.", head="월별 근무표")
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
    ui.panel_head("월간 근무표", f"조회 결과 {len(grid)}건")
    styled = grid.style.map(lambda v: _cell_style(v, wt), subset=day_cols)
    st.dataframe(styled, width="stretch", hide_index=True, height=grid_height(len(grid)))
    st.markdown(ui.legend_html(wt), unsafe_allow_html=True)

    # 사용자별 집계 (전체 근무표 조회)
    if page_id == "schedule_view" and not month_rows.empty:
        st.write("")
        ui.panel_head("직원별 근무형태 집계")
        agg = _build_agg(grid, month_rows, wt)
        st.dataframe(agg, width="stretch", hide_index=True, height=grid_height(len(agg)))

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
    if q["dept"] != ALL:
        users = users[users["dept_code"] == q["dept"]]
        if q["team"] != ALL:
            users = users[users["team_code"] == q["team"]]
    keyword = str(q.get("keyword", "")).strip()
    if keyword:
        emp_match = users["emp_no"].astype(str).str.contains(
            keyword, case=False, na=False, regex=False,
        )
        name_match = users["name"].astype(str).str.contains(
            keyword, case=False, na=False, regex=False,
        )
        users = users[emp_match | name_match]
    users = users.sort_values(["dept_code", "team_code", "emp_no"])

    scheds = db.get_month_schedules(users["emp_no"], q["year"], q["month"])

    lookup = {(r["emp_no"], r["duty_date"]): r["work_type_code"] for _, r in scheds.iterrows()}
    ndays = calendar.monthrange(q["year"], q["month"])[1]
    days = [date(q["year"], q["month"], d) for d in range(1, ndays + 1)]

    rows = []
    for _, u in users.iterrows():
        row = {
            "사번": u["emp_no"],
            "성명": u["name"],
            "부서": db.dept_name(u["dept_code"]),
            "조": db.team_name(u["dept_code"], u["team_code"]),
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
