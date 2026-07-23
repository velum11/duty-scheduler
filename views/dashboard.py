"""역할별 홈 대시보드.

ADMIN/MANAGER 는 당일 조직 그룹별 근무 보드(주간·야간·휴무…)를, USER 는 본인
근무 현황을 표시한다. 데이터는 db 파사드를 통해 조회한다 (샘플/Supabase 공통).
대시보드는 조회 전용이며 저장 계약과 무관하다.
"""
from datetime import date, timedelta
from html import escape

import pandas as pd
import streamlit as st

from modules import db, ui
from views import workspace

# 버킷 표시 순서와 대표 색상(카테고리 accent — 색만이 아닌 라벨 병기로 이중 부호화).
# classify_work_group 은 주간/야간/OFF/휴가/None 을 반환한다. OFF→휴무(라벨만),
# None→기타(값이 있을 때만 노출). 판정이 category 기반이라 근무형태가 추가돼도 자동 반영.
_BUCKET_ORDER = ["주간", "야간", "휴무", "휴가", "기타"]
_BUCKET_COLOR = {
    "주간": "#1E6FD9",
    "야간": "#7B4FD8",
    "휴무": "#7A776F",
    "휴가": "#2F6B4F",
    "기타": "#8A6A1C",
}
_DASHBOARD_DATE = "dashboard_date"


def render(user: dict) -> None:
    if str(user.get("role", "")).strip().upper() == "USER":
        _render_user(user)
        return

    ui.page_header("dashboard")
    the_date = _date_nav_bar()
    _inject_board_style()

    try:
        day_rows = db.get_day_schedules(the_date)
        users = db.get_users()
        wt = db.work_types_map()
        display_of, color_of = workspace.work_type_display()
    except db.DATA_SOURCE_ERRORS as exc:
        st.error(f"근무 데이터를 불러오지 못했습니다. 데이터 연결 상태를 확인하세요. ({exc})")
        return
    except Exception:
        st.error("근무 정보를 불러오지 못했습니다. 잠시 후 다시 확인하세요.")
        return

    board, present_buckets, totals = _build_board(day_rows, users, wt)

    ui.summary_cards([
        ("당일 근무", f"{totals['주간'] + totals['야간']}명"),
        ("주간", f"{totals['주간']}명"),
        ("야간", f"{totals['야간']}명"),
        ("휴무", f"{totals['휴무']}명"),
    ])
    st.write("")

    if not board:
        ui.empty_state(
            f"{the_date.isoformat()}({ui.weekday_kr(the_date)}) 등록된 근무가 없습니다.",
            head="당일 근무 현황",
        )
        return

    # 항상 주간·야간·휴무 컬럼을 두고, 값이 있을 때만 휴가·기타 컬럼을 덧붙인다.
    columns = [b for b in _BUCKET_ORDER if b in {"주간", "야간", "휴무"} or b in present_buckets]

    for group in board:
        with ui.card():
            ui.panel_head(group["name"], f"{group['total']}명")
            st.markdown(
                _group_grid_html(group, columns, display_of, color_of),
                unsafe_allow_html=True,
            )


# ---------- 일자 네비게이션 ----------
def _current_date() -> date:
    value = st.session_state.get(_DASHBOARD_DATE)
    if not isinstance(value, date):
        value = date.today()
        st.session_state[_DASHBOARD_DATE] = value
    return value


def _date_nav_bar() -> date:
    """‹ 전일 / 익일 › + 네이티브 캘린더 date_input + [오늘]. 세션키=dashboard_date.

    date_input 을 세션키에 직접 바인딩하고, 버튼은 그 키를 갱신한 뒤 rerun 한다.
    rerun 후 date_input 이 갱신된 세션 값을 그대로 집어 올린다(값 인자 미전달).
    """
    cur = _current_date()
    cols = st.columns([1.3, 1.3, 2.6, 1.2, 4.6])
    with cols[0]:
        if st.button("‹ 전일", key="dash_prev", width="stretch"):
            st.session_state[_DASHBOARD_DATE] = cur - timedelta(days=1)
            st.rerun()
    with cols[1]:
        if st.button("익일 ›", key="dash_next", width="stretch"):
            st.session_state[_DASHBOARD_DATE] = cur + timedelta(days=1)
            st.rerun()
    with cols[3]:
        if st.button("오늘", key="dash_today", width="stretch"):
            st.session_state[_DASHBOARD_DATE] = date.today()
            st.rerun()
    with cols[2]:
        st.date_input("조회 일자", key=_DASHBOARD_DATE, label_visibility="collapsed")
    cur = _current_date()
    with cols[4]:
        color = ui.weekend_color(cur)
        st.markdown(
            f"<div class='dash-date-label'>조회 일자 "
            f"<b style='color:{color}'>{cur.isoformat()} ({ui.weekday_kr(cur)})</b></div>",
            unsafe_allow_html=True,
        )
    return cur


# ---------- 보드 구성 ----------
def _bucket_of(code: str, wt: dict) -> str:
    group = db.classify_work_group(code, wt.get(str(code).strip(), {}))
    if group == "OFF":
        return "휴무"
    if group in ("주간", "야간", "휴가"):
        return group
    return "기타"


def _build_board(day_rows, users, wt):
    """당일 근무행을 조직 그룹 → 버킷 → 인원으로 집계한다.

    반환: (board, present_buckets, totals)
      - board: [{code, name, total, buckets:{버킷: [ {name, team, code} ]}}], 그룹순
      - present_buckets: 실제 인원이 있는 버킷 집합(휴가/기타 컬럼 노출 판단용)
      - totals: 버킷별 전체 인원수(요약 카드)
    """
    totals = {b: 0 for b in _BUCKET_ORDER}
    present_buckets: set = set()
    if day_rows is None or day_rows.empty:
        return [], present_buckets, totals

    active = users[users["is_active"]] if not users.empty else users
    merged = day_rows.merge(users, on="emp_no", how="left")

    # 조직 그룹 정의(동적) — sort_order 순. 그룹코드→그룹명, 부서→그룹 매핑.
    groups_df = db.get_org_groups(is_active=True)
    if not groups_df.empty:
        groups_df = groups_df.sort_values("sort_order", kind="stable")
    group_name_of = dict(zip(
        groups_df["group_code"].astype(str), groups_df["group_name"].astype(str)
    ))
    group_seq = list(groups_df["group_code"].astype(str))
    dgm = db.dept_group_map()  # dept_code -> (group_code, group_order)

    # 활성 사용자 소속으로 부서 fallback 준비(근무행에 dept 없을 때 표시용 — 저장 안 함).
    active_dept = dict(zip(
        active["emp_no"].astype(str).str.strip(), active["dept_code"].astype(str)
    )) if not active.empty else {}

    boards: dict = {}
    order: list = list(group_seq)

    for _, row in merged.iterrows():
        emp_no = str(row.get("emp_no") or "").strip()
        dept = str(row.get("dept_code") or "").strip()
        if not dept:
            dept = active_dept.get(emp_no, "")  # 과거일 등 — 현재 소속 fallback
        gc, _ = dgm.get(dept, ("", 0))
        if not gc:
            gc = dept or "(미지정)"  # group_code 공백/migration 미적용 → dept 폴백
        if gc not in boards:
            boards[gc] = {
                "code": gc,
                "name": group_name_of.get(gc) or db.dept_name(gc) if gc != "(미지정)" else "(그룹 미지정)",
                "total": 0,
                "buckets": {},
            }
            if gc not in order:
                order.append(gc)

        code = str(row.get("work_type_code") or "").strip()
        bucket = _bucket_of(code, wt)
        name = str(row.get("name") or emp_no or "").strip() or emp_no
        team = db.team_name(dept, str(row.get("team_code") or "").strip())
        boards[gc]["buckets"].setdefault(bucket, []).append(
            {"name": name, "team": team, "code": code}
        )
        boards[gc]["total"] += 1
        totals[bucket] += 1
        present_buckets.add(bucket)

    # 인원이 실제로 배치된 그룹만, 정의 순서대로 반환.
    board = [boards[gc] for gc in order if gc in boards and boards[gc]["total"] > 0]
    return board, present_buckets, totals


def _group_grid_html(group, columns, display_of, color_of) -> str:
    """한 그룹 카드 내부의 버킷 컬럼 그리드(auto-fit → 좁은 폭에서 자연 줄바꿈)."""
    cols_html = []
    for bucket in columns:
        people = group["buckets"].get(bucket, [])
        accent = _BUCKET_COLOR.get(bucket, "#8A8880")
        people_html = "".join(
            "<div class='dash-person'>"
            + _person_badge(person["code"], display_of, color_of)
            + f"<span class='dash-name'>{escape(person['name'])}</span>"
            + (f"<span class='dash-team'>{escape(person['team'])}</span>" if person["team"] else "")
            + "</div>"
            for person in people
        ) or "<div class='dash-empty'>-</div>"
        cols_html.append(
            "<div class='dash-col'>"
            "<div class='dash-col-head'>"
            f"<span class='dash-dot' style='background:{accent}'></span>"
            f"<span class='dash-bucket'>{escape(bucket)}</span>"
            f"<span class='dash-count'>{len(people)}</span>"
            "</div>"
            f"<div class='dash-list'>{people_html}</div>"
            "</div>"
        )
    return f"<div class='dash-grid'>{''.join(cols_html)}</div>"


def _person_badge(code: str, display_of: dict, color_of: dict) -> str:
    code = str(code or "").strip()
    if not code:
        return ""
    label = display_of.get(code, code)
    color = color_of.get(code) or color_of.get(label) or "#9AA0A6"
    return f"<span class='dash-badge' style='background:{color}'>{escape(label)}</span>"


def _inject_board_style() -> None:
    st.markdown(
        """
<style>
.dash-date-label { font-size:13px; color:#5F5C55; padding-top:.5rem; }
.dash-date-label b { font-weight:700; }
.dash-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(148px,1fr));
  gap:.55rem; margin-top:.35rem; }
.dash-col { border:1px solid #E4E0D8; border-radius:8px; overflow:hidden; background:#FFFFFF; }
.dash-col-head { display:flex; align-items:center; gap:.4rem; padding:.4rem .55rem;
  background:#F7F5F0; border-bottom:1px solid #E4E0D8; }
.dash-dot { width:9px; height:9px; border-radius:2px; flex:0 0 auto; }
.dash-bucket { font-size:12.5px; font-weight:600; color:#24262B; }
.dash-count { margin-left:auto; font-size:12.5px; font-weight:600; color:#24262B;
  font-variant-numeric:tabular-nums; }
.dash-list { padding:.2rem .35rem .35rem; display:flex; flex-direction:column; gap:.1rem; }
.dash-person { display:flex; align-items:center; gap:.4rem; padding:.24rem .2rem;
  border-bottom:1px solid #F1EEE7; }
.dash-person:last-child { border-bottom:none; }
.dash-badge { display:inline-flex; align-items:center; justify-content:center; min-width:26px;
  padding:.05rem .32rem; border-radius:5px; color:#FFFFFF; font-size:11px; font-weight:600;
  flex:0 0 auto; }
.dash-name { font-size:13px; color:#24262B; overflow-wrap:anywhere; }
.dash-team { margin-left:auto; font-size:11.5px; color:#5F5C55; flex:0 0 auto; }
.dash-empty { color:#908C83; font-size:12.5px; padding:.3rem .2rem; }
</style>
""",
        unsafe_allow_html=True,
    )


def _render_user(user: dict) -> None:
    """현재 저장 데이터로 계산 가능한 USER 개인 근무 요약."""
    ui.page_title("대시보드", "내 근무 현황을 확인합니다.")
    today = date.today()
    emp_no = str(user.get("emp_no", "")).strip()

    try:
        rows = db.get_user_schedules(emp_no).copy()
        month_rows = db.get_month_schedules(emp_no, today.year, today.month)
        work_types = {
            str(row["code"]): row.to_dict()
            for _, row in db.get_work_types().iterrows()
        }
        rows["date"] = pd.to_datetime(rows["duty_date"], errors="coerce").dt.date
    except Exception:
        st.error("근무 정보를 불러오지 못했습니다. 잠시 후 다시 확인하세요.")
        return

    today_rows = rows[rows["date"] == today] if not rows.empty else rows
    today_code = "미등록" if today_rows.empty else str(today_rows.iloc[0]["work_type_code"])

    future = rows[rows["date"] > today].sort_values("date") if not rows.empty else rows
    if future.empty:
        next_label, next_value = "다음 근무", "데이터 없음"
    else:
        next_row = future.iloc[0]
        next_date = next_row["date"]
        next_label = "내일 근무" if (next_date - today).days == 1 else f"다음 근무 ({next_date.month}/{next_date.day})"
        next_value = str(next_row["work_type_code"])

    counts = {"주간": 0, "야간": 0, "OFF": 0}
    for code, count in month_rows["work_type_code"].value_counts().items():
        group = db.classify_work_group(str(code), work_types.get(str(code), {}))
        if group in counts:
            counts[group] += int(count)

    items = [
        ("오늘 내 근무", today_code),
        (next_label, next_value),
        ("이번 달 주간", f"{counts['주간']}회"),
        ("이번 달 야간", f"{counts['야간']}회"),
        ("이번 달 OFF", f"{counts['OFF']}회"),
    ]
    cards = "".join(
        f"<div class='sum-card'><div class='sum-value'>{escape(value)}</div>"
        f"<div class='sum-label'>{escape(label)}</div></div>"
        for label, value in items
    )
    st.markdown(
        """
<style>
.user-dashboard-grid { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:.6rem; }
.user-dashboard-grid .sum-value { font-size:1.18rem; overflow-wrap:anywhere; }
@media (max-width:768px) {
  .user-dashboard-grid { grid-template-columns:repeat(2,minmax(0,1fr)); gap:.45rem; }
  .user-dashboard-grid .sum-card:first-child { grid-column:span 1; }
  .user-dashboard-grid .sum-value { font-size:1.05rem; }
}
</style>
""" + f"<div class='user-dashboard-grid'>{cards}</div>",
        unsafe_allow_html=True,
    )
