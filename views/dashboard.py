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
# canonical(비위젯) 일자 키 — 페이지를 이동해도 유지된다. date_input 위젯 키는
# Streamlit 이 화면 이탈 시 비우므로(선례: schedule_edit) 별도 위젯 키를 두고
# canonical 로 재seed 한다.
_DASHBOARD_DATE = "dashboard_date"
_DASHBOARD_DATE_WIDGET = "dash_date_input"


def render(user: dict) -> None:
    role = str(user.get("role", "")).strip().upper()
    if role == "USER":
        _render_user(user)
        return

    ui.page_header("dashboard")
    the_date = _date_nav_bar()
    _inject_board_style()

    # MANAGER 는 담당 부서 범위만 본다(requirements.md §2). 근무표 편성·조회 화면
    # (schedule_edit/workspace)의 선례와 동일하게 본인 dept_code 로 한정하고, ADMIN 은
    # 전체를 유지한다. USER 는 위에서 개인 요약으로 분기했다.
    manager_dept = None
    if role == "MANAGER":
        manager_dept = str(user.get("dept_code") or "").strip() or None

    # 조직 조회(get_org_groups/dept_group_map/team_name 등)도 오류 처리 범위에 포함한다
    # — 최초 근무 조회만 감싸면 보드 구성 중 데이터소스 오류가 화면 전체 예외가 된다.
    try:
        day_rows = db.get_day_schedules(the_date)
        users = db.get_users()
        wt = db.work_types_map()
        display_of, color_of = _display_maps()
        # 스냅샷 소속: 해당 월 편성이 있으면 그 당시 부서/조로 그룹핑, 없으면 현재
        # 소속 폴백(표시용, 자동저장 금지 — requirements.md §5·불변계약).
        snap = _month_snapshot(the_date)
        board, present_buckets, totals = _build_board(
            day_rows, users, wt, snap=snap, manager_dept=manager_dept
        )
    except db.DATA_SOURCE_ERRORS as exc:
        st.error(f"근무 데이터를 불러오지 못했습니다. 데이터 연결 상태를 확인하세요. ({exc})")
        return
    except Exception:
        st.error("근무 정보를 불러오지 못했습니다. 잠시 후 다시 확인하세요.")
        return

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
def _canonical_date() -> date:
    value = st.session_state.get(_DASHBOARD_DATE)
    if not isinstance(value, date):
        value = date.today()
        st.session_state[_DASHBOARD_DATE] = value
    return value


def _set_date(new_date: date) -> None:
    """canonical 과 date_input 위젯 값을 함께 갱신한다(버튼 조작 경로)."""
    st.session_state[_DASHBOARD_DATE] = new_date
    st.session_state[_DASHBOARD_DATE_WIDGET] = new_date


def _date_nav_bar() -> date:
    """‹ 전일 / 익일 › + 네이티브 캘린더 date_input + [오늘]. 기본=오늘.

    canonical 키(dashboard_date)는 비위젯이라 페이지 이동에도 유지된다. date_input
    위젯 키는 이동 시 Streamlit 이 비우므로 매 실행마다 canonical 로 재seed 하고,
    위젯에서 새 날짜를 고르면 canonical 에 반영한다.
    """
    cur = _canonical_date()
    cols = st.columns([1.3, 1.3, 2.6, 1.2, 4.6])
    with cols[0]:
        if st.button("‹ 전일", key="dash_prev", width="stretch"):
            _set_date(cur - timedelta(days=1))
            st.rerun()
    with cols[1]:
        if st.button("익일 ›", key="dash_next", width="stretch"):
            _set_date(cur + timedelta(days=1))
            st.rerun()
    with cols[3]:
        if st.button("오늘", key="dash_today", width="stretch"):
            _set_date(date.today())
            st.rerun()
    with cols[2]:
        # 이동 후 위젯 상태가 비워지면 canonical 로 재seed(값 인자 대신 세션키 사용).
        st.session_state.setdefault(_DASHBOARD_DATE_WIDGET, cur)
        picked = st.date_input(
            "조회 일자", key=_DASHBOARD_DATE_WIDGET, label_visibility="collapsed"
        )
    if isinstance(picked, date) and picked != cur:
        st.session_state[_DASHBOARD_DATE] = picked  # 위젯 선택 → canonical 반영
        cur = picked
    with cols[4]:
        color = ui.weekend_color(cur)
        st.markdown(
            f"<div class='dash-date-label'>조회 일자 "
            f"<b style='color:{color}'>{cur.isoformat()} ({ui.weekday_kr(cur)})</b></div>",
            unsafe_allow_html=True,
        )
    return cur


# ---------- 표시맵·스냅샷 헬퍼 ----------
def _display_maps():
    """근무 약칭·색상 표시맵. 활성은 work_type_display(약칭 모호성 처리)를 쓰고,
    비활성(소프트삭제) 근무형태도 과거 근무 참조 보존(requirements.md §6.4·§7)을 위해
    전체 기준정보에서 약칭·색을 보강한다 — 활성 매핑이 우선한다.
    """
    display_of, color_of = workspace.work_type_display()
    display_of = dict(display_of)
    color_of = dict(color_of)
    wt_all = db.get_work_types()
    if not wt_all.empty:
        for _, r in wt_all.iterrows():
            code = str(r["code"]).strip()
            if not code:
                continue
            label = str(r.get("short_label") or "").strip() or code
            color = str(r.get("color") or "").strip()
            display_of.setdefault(code, label)
            if color.startswith("#"):
                color_of.setdefault(code, color)
                color_of.setdefault(label, color)
    return display_of, color_of


def _month_snapshot(the_date: date) -> dict:
    """해당 일자가 속한 월의 편성 스냅샷 emp_no -> (dept_code, team_code).

    편성 스냅샷이 있으면 그 당시 소속으로 그룹을 결정한다(불변계약: 스냅샷은 해당
    월의 부서·운영단위를 보존 — requirements.md §5). 없으면 호출부가 현재 users
    소속으로 폴백한다(표시용, 자동저장 금지).
    """
    assigns = db.get_month_assignments(the_date.year, the_date.month)
    snap: dict = {}
    if assigns is None or assigns.empty:
        return snap
    for _, r in assigns.iterrows():
        emp = str(r.get("emp_no") or "").strip()
        if emp:
            snap[emp] = (
                str(r.get("dept_code") or "").strip(),
                str(r.get("team_code") or "").strip(),
            )
    return snap


# ---------- 보드 구성 ----------
def _bucket_of(code: str, wt: dict) -> str:
    group = db.classify_work_group(code, wt.get(str(code).strip(), {}))
    if group == "OFF":
        return "휴무"
    if group in ("주간", "야간", "휴가"):
        return group
    return "기타"


def _build_board(day_rows, users, wt, snap=None, manager_dept=None):
    """당일 근무행을 조직 그룹 → 버킷 → 인원으로 집계한다.

    - snap: emp_no -> (dept_code, team_code) 편성 스냅샷. 있으면 그 당시 소속으로
      그룹핑하고, 없으면 현재 users 소속으로 폴백한다(표시용, 저장 안 함).
    - manager_dept: 지정되면 그 부서(담당 범위)의 근무자만 집계한다(MANAGER 범위).
      None 이면 전체(ADMIN).

    반환: (board, present_buckets, totals)
      - board: [{code, name, total, buckets:{버킷: [ {name, team, code} ]}}], 그룹순
      - present_buckets: 실제 인원이 있는 버킷 집합(휴가/기타 컬럼 노출 판단용)
      - totals: 버킷별 전체 인원수(요약 카드)
    """
    snap = snap or {}
    totals = {b: 0 for b in _BUCKET_ORDER}
    present_buckets: set = set()
    if day_rows is None or day_rows.empty:
        return [], present_buckets, totals

    merged = day_rows.merge(users, on="emp_no", how="left")

    # 그룹명은 전체(비활성 포함)에서 조회해 비활성 그룹 부서가 dept_name(group_code)로
    # 오표시되지 않게 한다(P2-4). 정의 순서는 활성 그룹 sort_order 를 우선한다.
    groups_all = db.get_org_groups()
    group_name_of = dict(zip(
        groups_all["group_code"].astype(str), groups_all["group_name"].astype(str)
    )) if not groups_all.empty else {}
    active_groups = db.get_org_groups(is_active=True)
    if not active_groups.empty:
        active_groups = active_groups.sort_values("sort_order", kind="stable")
    group_seq = list(active_groups["group_code"].astype(str))
    dgm = db.dept_group_map()  # dept_code -> (group_code, group_order)

    boards: dict = {}
    order: list = list(group_seq)

    for _, row in merged.iterrows():
        emp_no = str(row.get("emp_no") or "").strip()
        # 스냅샷 소속 우선 → 현재 users 소속 폴백(과거일/편성없음, 표시용·저장 안 함).
        snap_dept, snap_team = snap.get(emp_no, ("", ""))
        dept = snap_dept or str(row.get("dept_code") or "").strip()
        team = snap_team or str(row.get("team_code") or "").strip()

        if manager_dept is not None and dept != manager_dept:
            continue  # MANAGER 담당 부서 범위 밖

        gc, _ = dgm.get(dept, ("", 0))
        if not gc:
            gc = dept or "(미지정)"  # group_code 공백/migration 미적용 → dept 폴백
        if gc not in boards:
            if gc == "(미지정)":
                name = "(그룹 미지정)"
            else:
                name = group_name_of.get(gc) or db.dept_name(gc)
            boards[gc] = {"code": gc, "name": name, "total": 0, "buckets": {}}
            if gc not in order:
                order.append(gc)

        code = str(row.get("work_type_code") or "").strip()
        bucket = _bucket_of(code, wt)
        display_name = str(row.get("name") or emp_no or "").strip() or emp_no
        team_label = db.team_name(dept, team)
        boards[gc]["buckets"].setdefault(bucket, []).append(
            {"name": display_name, "team": team_label, "code": code}
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
