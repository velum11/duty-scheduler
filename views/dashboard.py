"""역할별 홈 대시보드.

ADMIN/MANAGER 는 선택한 일자의 근무 현황(지표)과 부서 → 조직 계층별 근무자 명단을,
USER 는 본인 근무 현황을 표시한다. 데이터는 db 파사드를 통해 조회한다(샘플/Supabase
공통). 대시보드는 조회 전용이며 저장 계약과 무관하다.

화면 골격(사용자 재구성 지시서 · DESIGN.md §2~§4 토큰)::

    ① 제목/설명            상단 52px 헤더 우측에 선택 일자 스탬프
    ② 조회 행              [‹ | 일자 | ›] 세그먼트 · [오늘] ······ 우측 끝: 부서 필터 칩
    ③ 지표 스트립          당일 근무 / 주간 / 야간 / 휴무
    ④ 부서별 근무자        부서(대분류) → 조직(중분류) → 주간·야간·휴무 3열 명단

계층 용어: 화면의 "부서"는 조직 관리에서 사람이 입력하는 대분류(major_category),
"조직"은 중분류(minor_category)다(migration 009). 인원은 **중분류 단위로 합산**하므로
1팀/2팀·1파트/2파트 같은 하위 분할은 화면에 나타나지 않는다. 어떤 분류명도 코드에
고정하지 않으며, 유일한 예외는 사용자가 지정한 제외 규칙(아래 상수)이다.
"""
# DESIGN.md §0 화면 유형 규약 — 대시보드형.
SCREEN_ARCHETYPE = "DASHBOARD"

from datetime import date, timedelta
from html import escape

import pandas as pd
import streamlit as st

from modules import db, ui
from views.common import erp

# 버킷 표시 순서. classify_work_group 은 주간/야간/OFF/휴가/None 을 반환한다.
# OFF→휴무, None→기타. 주간·야간·휴무는 항상 열로 두고, 휴가·기타는 실제 인원이 있을
# 때만 열을 덧붙인다(값이 있는데 사람을 조용히 떨어뜨리지 않기 위함).
_BUCKET_ORDER = ("주간", "야간", "휴무", "휴가", "기타")
_CORE_BUCKETS = ("주간", "야간", "휴무")
# 열 머리글 6px 사각 점 — 색만이 아니라 라벨을 병기하는 이중 부호화(장식용 보조 신호).
# §2 팔레트 안에서만 고른다: 주간=주 셀 글자색, 야간=야 셀 글자색, 휴가=연차 셀 글자색,
# 휴무=아주 약함(무채), 기타=제출됨 배지 글자색.
_BUCKET_DOT = {
    "주간": "#2f4d99",
    "야간": "#9c3232",
    "휴무": "#a09a90",
    "휴가": "#2f6b45",
    "기타": "#8a6212",
}
# 요일 색(§2 팔레트) — 토/일만 구분한다(요일 글자 자체가 이중 부호화).
_DOW_COLOR = {5: "#2f4d99", 6: "#9c3232"}

# canonical(비위젯) 일자 키 — 페이지를 이동해도 유지된다. date_input 위젯 키는
# Streamlit 이 화면 이탈 시 비우므로(선례: schedule_edit) 별도 위젯 키를 두고
# canonical 로 재seed 한다. 부서 필터도 같은 2단 방식이다.
_DASHBOARD_DATE = "dashboard_date"
_DASHBOARD_DATE_WIDGET = "dash_date_input"
_DASHBOARD_MAJOR = "dashboard_major"
_DASHBOARD_MAJOR_WIDGET = "dash_major_pills"

#: 부서 필터의 '전체' 선택지 라벨(대분류명과 충돌하지 않는 고정 문구).
_ALL_MAJORS = "전체"
#: 대분류가 비어 있는 부서를 모으는 자리. 감추지 않고 마지막에 따로 노출한다 —
#: 조직 관리에서 분류가 빠진 부서를 관리자가 발견할 수 있어야 하기 때문이다.
_UNCLASSIFIED_LABEL = "미분류"
#: 소속을 해석하지 못한 근무행의 조직 라벨(집계를 조용히 버리지 않기 위함).
_UNASSIGNED_LABEL = "(부서 미지정)"
#: 사용자 지정 제외 대분류 — 이 화면에서만 감춘다(데이터·다른 화면 무변경).
_EXCLUDED_MAJORS = ("관리",)
#: 시스템 부서(로그인·권한 전용) 제외.
_EXCLUDED_DEPT_CODES = ("ADMIN",)
#: 부서 기준정보에 없는 코드의 정렬 자리(항상 뒤).
_TAIL_ORDER = 10 ** 6


def _clean(value) -> str:
    """pandas NA-safe 문자열 정규화 — None/NaN/pd.NA → ''(폴백), 그 외 str.strip()."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass  # 배열·비스칼라 등 isna 판정 불가 값은 그대로 문자열화
    return str(value).strip()


def _scope_for(user: dict) -> tuple[str, str | None]:
    """대시보드 조회 범위를 결정한다(fail-closed).

    반환: ("all", None)      — ADMIN 만: 전체 조회
          ("scoped", dept)   — MANAGER 且 유효 담당 부서(dept)일 때만: 그 부서로 한정
          ("blocked", None)  — 그 외 전부(부서 미확정 MANAGER, 미지/비정상 역할,
                               MANAGER 아닌데 dept 있는 경우 등)

    fail-closed 원칙: '전체 조회(제한 없음)'는 오직 ADMIN, '부서 한정'은 오직
    MANAGER 且 유효 dept 일 때만 부여한다. 그 밖의 모든 경우는 데이터를 열지 않고
    차단한다(미지 역할이 유효 dept 로 scoped 로 새는 fail-open 방지). USER 는 상위
    render 에서 개인 요약으로 분기하므로 이 경로에 도달하지 않는다.
    """
    role = _clean(user.get("role")).upper()
    if role == "ADMIN":
        return ("all", None)
    if role == "MANAGER":
        dept = _clean(user.get("dept_code")) or None
        if dept is not None:
            return ("scoped", dept)
    return ("blocked", None)


def render(user: dict) -> None:
    role = _clean(user.get("role")).upper()
    if role == "USER":
        _render_user(user)
        return

    # ① 제목 — §1-F 헤더 중립 프레임(아이콘 밴드 없음: 표준 아이콘 8종은 상단 52px 헤더 소유).
    erp.screen_frame(
        SCREEN_ARCHETYPE,
        title="대시보드",
        desc="선택한 날짜의 근무 현황과 부서별 근무자를 확인합니다.",
        breadcrumb="홈 › 대시보드",
    )
    _inject_style()

    # 범위 결정(fail-closed): ADMIN=전체, MANAGER=자기 부서, 부서 미확정 MANAGER=차단.
    scope, manager_dept = _scope_for(user)
    if scope == "blocked":
        ui.empty_state(
            "소속 부서가 지정되지 않아 근무 현황을 표시할 수 없습니다. "
            "관리자에게 부서 지정을 요청하세요.",
            head="당일 근무 현황",
        )
        return

    the_date = _resolve_date()
    # 조직 조회(부서 기준정보·편성 스냅샷)도 오류 처리 범위에 포함한다 — 근무 조회만
    # 감싸면 계층 구성 중 데이터소스 오류가 화면 전체 예외가 된다.
    try:
        tree, majors = _duty_board(the_date, manager_dept=manager_dept)
    except db.DATA_SOURCE_ERRORS as exc:
        st.error(f"근무 데이터를 불러오지 못했습니다. 데이터 연결 상태를 확인하세요. ({exc})")
        return
    except Exception:
        st.error("근무 정보를 불러오지 못했습니다. 잠시 후 다시 확인하세요.")
        return

    # ② 조회 행 — 일자 세그먼트 + [오늘] + 우측 끝 부서 칩(같은 행).
    picked = _query_row(the_date, majors)
    shown = tree if picked == _ALL_MAJORS else [m for m in tree if m["name"] == picked]
    totals, columns = _summarize(shown)

    # 상단 52px 헤더 우측 스탬프 — 조회 행과 **같은 run 에서** 같은 값을 채운다(슬롯 방식).
    ui.header_stamp(
        f"{the_date.isoformat()} ({ui.weekday_kr(the_date)}) · "
        f"{_scope_label(picked, manager_dept)}"
    )

    # ③ 지표 스트립(제목·조회 행 아래 첫 블록, §0-4). 값은 ④ 명단과 같은 집계에서
    #    파생하므로 필터 선택과 항상 일치한다.
    st.markdown(_kpi_strip_html(totals), unsafe_allow_html=True)

    # ④ 부서별 근무자.
    if not shown:
        ui.empty_state(
            f"{the_date.isoformat()}({ui.weekday_kr(the_date)}) 등록된 근무가 없습니다.",
            head="부서별 근무자",
        )
        return
    st.markdown(_people_html(shown, columns), unsafe_allow_html=True)


def _scope_label(picked: str, manager_dept: str | None) -> str:
    """헤더 스탬프의 범위 표기 — MANAGER 는 담당 부서, ADMIN 은 선택 대분류(기본 전사)."""
    if manager_dept:
        return db.dept_name(manager_dept) or manager_dept
    return "전사" if picked == _ALL_MAJORS else picked


# ---------- ② 조회 행 ----------
def _resolve_date() -> date:
    """이번 run 의 조회 일자. 위젯 값 → canonical → 오늘 순으로 해석한다.

    date_input 을 직접 바꾼 run 에서는 위젯 키에 새 값이 이미 반영돼 있으므로 위젯을
    먼저 본다(헤더 스탬프·집계가 같은 run 에서 같은 날짜를 쓴다). 화면을 떠나면
    Streamlit 이 위젯 키를 비우므로 canonical(비위젯) 키로 복원하고 다시 seed 한다.
    """
    picked = st.session_state.get(_DASHBOARD_DATE_WIDGET)
    if isinstance(picked, date):
        st.session_state[_DASHBOARD_DATE] = picked
        return picked
    cur = st.session_state.get(_DASHBOARD_DATE)
    if not isinstance(cur, date):
        cur = date.today()
    st.session_state[_DASHBOARD_DATE] = cur
    st.session_state[_DASHBOARD_DATE_WIDGET] = cur  # 이탈 후 복귀 재seed
    return cur


def _set_date(new_date: date) -> None:
    """canonical 과 date_input 위젯 값을 함께 갱신한다(버튼 조작 경로)."""
    st.session_state[_DASHBOARD_DATE] = new_date
    st.session_state[_DASHBOARD_DATE_WIDGET] = new_date


def _shift_date(days: int) -> None:
    """전일/익일 이동(on_click 콜백) — 콜백은 다음 run 보다 먼저 실행되므로 헤더도 새 값."""
    _set_date(_resolve_date() + timedelta(days=days))


def _goto_today() -> None:
    _set_date(date.today())


def _query_row(the_date: date, majors: list) -> str:
    """일자 세그먼트 + [오늘] + 부서 필터 칩을 **한 행**에 렌더하고 선택 대분류를 반환한다.

    칩은 대분류 데이터에서 만든다('전체' + 근무자가 있는 대분류) — 대분류명을 코드에
    박지 않으므로 조직 개편이 그대로 반영되고, 근무자가 없는 대분류는 칩도 생기지
    않는다. 선택값은 canonical 키에 보관해 화면을 떠났다 돌아와도 유지한다.
    """
    options = [_ALL_MAJORS] + list(majors)
    stored = st.session_state.get(_DASHBOARD_MAJOR)
    if stored not in options:  # 조직 개편·일자 이동으로 사라진 선택은 전체로 되돌린다
        stored = _ALL_MAJORS
        st.session_state[_DASHBOARD_MAJOR] = stored
    if st.session_state.get(_DASHBOARD_MAJOR_WIDGET) not in options:
        st.session_state[_DASHBOARD_MAJOR_WIDGET] = stored  # 이탈 후 복귀·옵션 변경 복구

    dow_color = _DOW_COLOR.get(the_date.weekday(), "#1c1a17")
    with st.container(key="dash_qrow", horizontal=True, gap="small",
                      vertical_alignment="center"):
        # 전일/일자/익일은 한 덩어리 세그먼트(내부 구분선만, 버튼 3개를 늘어놓지 않는다).
        with st.container(key="dash_seg", horizontal=True, gap=None,
                          vertical_alignment="center", width="content"):
            st.button("‹", key="dash_prev", help="전일", on_click=_shift_date, args=(-1,))
            with st.container(key="dash_segval", horizontal=True, gap=None,
                              vertical_alignment="center", width="content"):
                st.date_input(
                    "조회 일자", key=_DASHBOARD_DATE_WIDGET, format="YYYY-MM-DD",
                    label_visibility="collapsed", width=92,
                )
                st.markdown(
                    f"<span class='dash-dow' style='color:{dow_color}'>"
                    f"({ui.weekday_kr(the_date)})</span>",
                    unsafe_allow_html=True,
                )
            st.button("›", key="dash_next", help="익일", on_click=_shift_date, args=(1,))
        st.button("오늘", key="dash_today", on_click=_goto_today)
        with st.container(key="dash_chips", width="content"):
            picked = st.pills(
                "부서 필터", options, key=_DASHBOARD_MAJOR_WIDGET, required=True,
                label_visibility="collapsed", width="content",
            )
    picked = picked if picked in options else _ALL_MAJORS
    st.session_state[_DASHBOARD_MAJOR] = picked
    return picked


# ---------- 스냅샷·버킷 ----------
def _month_snapshot(the_date: date) -> dict:
    """해당 일자가 속한 월의 편성 스냅샷 emp_no -> (dept_code, team_code).

    편성 스냅샷이 있으면 그 당시 소속으로 계층을 결정한다(불변계약: 스냅샷은 해당
    월의 부서·운영단위를 보존 — requirements.md §5). 없으면 호출부가 현재 users
    소속으로 폴백한다(표시용, 자동저장 금지).
    """
    assigns = db.get_month_assignments(the_date.year, the_date.month)
    snap: dict = {}
    if assigns is None or assigns.empty:
        return snap
    for _, r in assigns.iterrows():
        emp = _clean(r.get("emp_no"))
        if emp:
            snap[emp] = (_clean(r.get("dept_code")), _clean(r.get("team_code")))
    return snap


def _bucket_of(code: str, wt: dict) -> str:
    group = db.classify_work_group(code, wt.get(str(code).strip(), {}))
    if group == "OFF":
        return "휴무"
    if group in ("주간", "야간", "휴가"):
        return group
    return "기타"


def _order_of(value) -> int:
    """정렬 순서 숫자화(해석 불가는 0) — 조직 관리 시트의 '순서' 열을 그대로 따른다."""
    num = pd.to_numeric(value, errors="coerce")
    return 0 if pd.isna(num) else int(num)


# ---------- ④ 집계 ----------
def _dept_index(depts) -> tuple[dict, set]:
    """부서코드 → (대분류, 중분류, 정렬순서, 부서명) 색인 + 제외 부서코드 집합.

    비활성 부서도 색인에 넣는다 — 그 부서로 등록된 근무가 남아 있으면 계층을 해석해
    제자리에 보여야 한다(집계를 조용히 버리지 않는다). 감추는 것은 규칙 두 가지뿐:
    시스템 부서(``_EXCLUDED_DEPT_CODES``)와 사용자 지정 제외 대분류(``_EXCLUDED_MAJORS``).
    제외는 지표와 명단에 **같은 기준**으로 적용된다(둘이 다른 말을 하지 않게).
    """
    index: dict = {}
    excluded: set = {code for code in _EXCLUDED_DEPT_CODES}
    if depts is None or depts.empty:
        return index, excluded
    for _, row in depts.iterrows():
        code = _clean(row.get("dept_code"))
        if not code:
            continue
        major = _clean(row.get("major_category"))
        if code.upper() in _EXCLUDED_DEPT_CODES or major in _EXCLUDED_MAJORS:
            excluded.add(code)
            continue
        index[code] = (
            major,
            _clean(row.get("minor_category")),
            _order_of(row.get("sort_order")),
            _clean(row.get("dept_name")) or code,
        )
    return index, excluded


def _duty_board(the_date, *, manager_dept=None, depts=None, users=None, day_rows=None):
    """선택 일자의 근무행을 부서(대분류) → 조직(중분류) → 버킷별 명단으로 모은다.

    - 소속 판정: 그 달 편성 스냅샷 우선, 없으면 현재 users 소속 폴백(표시용·저장 금지).
    - 버킷 판정: :func:`_bucket_of` (= ``db.classify_work_group``) — 새 분류를 만들지 않는다.
    - 인원은 **중분류 단위로 합산**한다(PET생산1팀·2팀 → PET생산팀). 중분류가 빈 부서는
      부서명을 조직 라벨로 쓴다.
    - 근무자가 없는 조직·부서는 애초에 생기지 않는다(근무행에서만 계층을 만든다).
    - ``manager_dept`` 가 지정되면 그 부서 근무자만 집계한다(MANAGER 범위).
    - depts/users/day_rows 는 테스트 주입용.

    반환: ``(tree, majors)``
      - tree: ``[{name, unclassified, orgs:[{name, people:{버킷:[{name, emp_no}]}}]}]``
      - majors: 부서 필터 칩 선택지(노출 순서 그대로)
    """
    users = db.get_users(include_resigned=False) if users is None else users
    depts = db.get_org_departments() if depts is None else depts
    day_rows = db.get_day_schedules(the_date) if day_rows is None else day_rows
    if day_rows is None or day_rows.empty:
        return [], []

    index, excluded = _dept_index(depts)
    wt = db.work_types_map()
    snap = _month_snapshot(the_date)
    merged = day_rows.merge(users, on="emp_no", how="left")

    majors: dict = {}
    for _, row in merged.iterrows():
        emp_no = _clean(row.get("emp_no"))
        snap_dept, _team = snap.get(emp_no, ("", ""))
        dept = snap_dept or _clean(row.get("dept_code"))
        if manager_dept is not None and dept != manager_dept:
            continue  # MANAGER 담당 부서 범위 밖
        if dept in excluded or dept.upper() in _EXCLUDED_DEPT_CODES:
            continue  # 제외 규칙(시스템 부서·제외 대분류)
        major, minor, order, dept_name = index.get(
            dept, ("", "", _TAIL_ORDER, db.dept_name(dept) or dept)
        )
        major_key = major or _UNCLASSIFIED_LABEL
        org_key = minor or dept_name or _UNASSIGNED_LABEL
        node = majors.setdefault(major_key, {
            "name": major_key, "unclassified": not major,
            "order": order, "orgs": {},
        })
        node["order"] = min(node["order"], order)
        org = node["orgs"].setdefault(org_key, {"name": org_key, "order": order, "people": {}})
        org["order"] = min(org["order"], order)
        org["people"].setdefault(_bucket_of(_clean(row.get("work_type_code")), wt), []).append(
            {"name": _clean(row.get("name")) or emp_no, "emp_no": emp_no}
        )

    # 노출 순서는 조직 관리 시트의 순서(sort_order)를 그대로 따르고, 미분류만 마지막.
    tree = []
    for node in sorted(majors.values(),
                       key=lambda m: (1 if m["unclassified"] else 0, m["order"], m["name"])):
        orgs = sorted(node["orgs"].values(), key=lambda o: (o["order"], o["name"]))
        for org in orgs:
            for members in org["people"].values():
                members.sort(key=lambda p: (p["name"], p["emp_no"]))
        node["orgs"] = orgs
        tree.append(node)
    return tree, [node["name"] for node in tree]


def _summarize(tree: list) -> tuple[dict, list]:
    """표시 중인 계층에서 버킷 합계와 렌더할 열 목록을 만든다(지표 = 명단의 합)."""
    totals = {bucket: 0 for bucket in _BUCKET_ORDER}
    for major in tree:
        for org in major["orgs"]:
            for bucket, members in org["people"].items():
                totals[bucket] = totals.get(bucket, 0) + len(members)
    columns = [b for b in _BUCKET_ORDER if b in _CORE_BUCKETS or totals.get(b)]
    return totals, columns


# ---------- ③ 지표 · ④ 명단 HTML ----------
def _kpi_strip_html(totals: dict) -> str:
    """지표 스트립 — 좌측 2px 보더 + 모노 값(카드 없음). 당일 근무만 액센트."""
    on_duty = totals.get("주간", 0) + totals.get("야간", 0)
    metrics = [
        ("당일 근무", on_duty, True),
        ("주간", totals.get("주간", 0), False),
        ("야간", totals.get("야간", 0), False),
        ("휴무", totals.get("휴무", 0), False),
    ]
    cells = []
    for label, value, accent in metrics:
        border = "#c2410c" if accent else "#cfc8bd"
        vcolor = "#b4451a" if accent else "#1c1a17"
        cells.append(
            f"<div class='dash-kpi' style='border-left:2px solid {border};'>"
            f"<span class='dash-klabel'>{escape(label)}</span>"
            f"<div class='dash-kval-row'>"
            f"<span class='dash-kval' style='color:{vcolor};'>{value}</span>"
            f"<span class='dash-kunit'>명</span></div></div>"
        )
    return f"<div class='dash-kpis'>{''.join(cells)}</div>"


def _people_html(tree: list, columns: list) -> str:
    """부서 → 조직 → 주간·야간·휴무 3열 명단(이름은 열 아래로 세로로 쌓인다).

    이름마다 위젯을 만들지 않고 한 번의 HTML 로 렌더한다(리렌더 비용·간격 붕괴 방지).
    열은 flex-wrap 이라 좁아지면 2열 → 1열로 접힌다(고정 3분할 아님).
    """
    blocks = []
    for major in tree:
        # 부서 헤더 우측은 비운다(합계는 조직 줄이 말한다 — 같은 말을 두 번 하지 않는다).
        blocks.append(f"<div class='dorg-major'>{escape(major['name'])}</div>")
        for org in major["orgs"]:
            counts = {b: len(org["people"].get(b, [])) for b in columns}
            # 요약은 기본 3버킷을 항상(0 이어도) 쓰고, 휴가·기타는 그 조직에 실제로
            # 있을 때만 덧붙인다 — 열은 목록 전체에서 같은 순서·같은 개수로 유지해
            # 조직끼리 세로로 맞춰 읽히게 두되, 요약 문구에 0 을 늘어놓지 않는다.
            summary = " · ".join(
                f"{b} {counts[b]}" for b in columns if b in _CORE_BUCKETS or counts[b]
            )
            cols_html = []
            for bucket in columns:
                names = "".join(
                    f"<div class='dorg-name'>{escape(person['name'])}</div>"
                    for person in org["people"].get(bucket, [])
                )
                cols_html.append(
                    "<div class='dorg-col'><div class='dorg-chead'>"
                    f"<span class='dorg-dot' style='background:{_BUCKET_DOT.get(bucket, '#a09a90')}'></span>"
                    f"<span class='dorg-clabel'>{escape(bucket)}</span>"
                    f"<span class='dorg-cnum'>{counts[bucket]}</span></div>"
                    f"<div class='dorg-names'>{names}</div></div>"
                )
            blocks.append(
                "<div class='dorg-org'><div class='dorg-ohead'>"
                f"<span class='dorg-oname'>{escape(org['name'])}</span>"
                f"<span class='dorg-osum'>{escape(summary)}</span></div>"
                f"<div class='dorg-cols'>{''.join(cols_html)}</div></div>"
            )
    return f"<div class='dorg'>{''.join(blocks)}</div>"


def _inject_style() -> None:
    # §2 팔레트·§3 타이포. 카드(테두리+radius+그림자) 없음 — 구획은 헤어라인과 여백뿐(§0-5).
    # 작은 의미 텍스트(라벨·건수·요약)는 부속서 A-2 하한 #6b665d 이상을 쓴다.
    # 모노(값·건수)는 전역 stMarkdownContainer 폰트 규칙(특이도 0,2,0)을 0,3,0 규칙으로
    # 덮어 강제한다(Streamlit 이 인라인 font-family 를 제거하므로 CSS 로).
    st.markdown(
        """
<style>
/* ===== ② 조회 행 — 세그먼트 + [오늘] + 우측 끝 부서 칩(한 행), 하단 헤어라인 ===== */
.st-key-dash_qrow { align-items:center !important; flex-wrap:wrap !important;
  gap:10px !important; border-bottom:1px solid #e0dbd2; padding-bottom:10px;
  margin-bottom:12px; }
.st-key-dash_qrow > div { flex:0 0 auto !important; }
/* 마지막 항목(부서 칩)만 우측 끝으로 — 키 컨테이너는 레이아웃 래퍼로 감싸이므로
   래퍼(직계 자식)에 걸어야 margin-left:auto 가 먹는다. */
.st-key-dash_qrow > div:last-child { margin-left:auto !important; }
/* 전일 | 일자 | 익일 = 한 덩어리(외곽 1px, 내부 구분선만) */
.st-key-dash_seg { height:34px; border:1px solid #e2ddd4; border-radius:8px;
  background:#fff; overflow:hidden; align-items:stretch !important; gap:0 !important;
  padding:0 !important; }
.st-key-dash_seg > div { flex:0 0 auto !important; display:flex; align-items:center; }
.st-key-dash_seg > div + div { border-left:1px solid #eeeae3; }
/* 후손 선택자로 잡는다 — help(툴팁) 래퍼가 있으면 button 이 .stButton 의 직계자식이
   아니라 직계자식 선택자는 크기 규칙을 놓친다(키트 _KIT_CSS 주석과 같은 사유). */
.st-key-dash_seg button {
  height:32px !important; min-height:32px !important; min-width:34px; padding:0 10px;
  border:0 !important; border-radius:0 !important; background:transparent !important;
  box-shadow:none !important; color:#4a453d !important; font-size:15px; line-height:1; }
.st-key-dash_seg button:hover { background:#f1eee8 !important; color:#1c1a17 !important; }
.st-key-dash_seg button:focus-visible { outline:2px solid #c2410c; outline-offset:-2px; }
.st-key-dash_seg div.stButton, .st-key-dash_seg div[data-testid="stTooltipHoverTarget"] {
  display:flex; align-items:center; }
/* 일자 텍스트 = 모노 14px/500. date_input 은 세그먼트 안에서 테두리 없이 값처럼 보이게. */
.st-key-dash_segval { padding:0 6px 0 12px; gap:2px !important; }
.st-key-dash_segval div[data-testid="stDateInput"] { width:92px; }  /* 모노 10자(84px) + 여유 */
.st-key-dash_segval div[data-baseweb="input"] { border:0 !important; background:transparent !important;
  box-shadow:none !important; }
.st-key-dash_segval div[data-baseweb="input"] > div { padding-right:0 !important; }
.st-key-dash_segval input { padding:0 !important; height:32px; color:#1c1a17 !important;
  font-family:'IBM Plex Mono','Consolas','Menlo',monospace !important; font-size:14px !important;
  font-weight:500 !important; font-variant-numeric:tabular-nums; cursor:pointer; }
.st-key-dash_segval div[data-testid="stDateInput"] svg { width:15px; height:15px; color:#8b857c; }
.dash-dow { font-family:'IBM Plex Mono','Consolas','Menlo',monospace; font-size:14px;
  font-weight:500; white-space:nowrap; }
/* [오늘] = 분리된 보조 버튼(같은 높이·테두리) */
.st-key-dash_today button {
  height:34px !important; min-height:34px !important; padding:0 13px;
  border:1px solid #e2ddd4 !important; border-radius:8px; background:#fff !important;
  color:#4a453d !important; font-size:13px; }
.st-key-dash_today button:hover { background:#f1eee8 !important; color:#1c1a17 !important; }
/* 부서 필터 칩(st.pills = stButtonGroup) — 선택은 오렌지 틴트 pill, 비선택은 중립 테두리. */
.st-key-dash_chips div[data-testid="stButtonGroup"] { gap:6px; flex-wrap:wrap; }
.st-key-dash_chips div[data-testid="stButtonGroup"] button {
  min-height:28px; padding:5px 12px; border-radius:999px;
  border:1px solid #e2ddd4 !important; background:#fff !important; color:#6b665d !important;
  font-size:13px !important; font-weight:500; }
.st-key-dash_chips div[data-testid="stButtonGroup"] button p { font-size:13px !important; }
.st-key-dash_chips div[data-testid="stButtonGroup"] button:hover {
  border-color:#cfc8bd !important; color:#1c1a17 !important; }
.st-key-dash_chips div[data-testid="stButtonGroup"] button[aria-checked="true"] {
  border-color:#c2410c !important; background:#fdf3ec !important; color:#b4451a !important;
  font-weight:600; }
.st-key-dash_chips div[data-testid="stButtonGroup"] button:focus-visible {
  outline:2px solid #c2410c; outline-offset:1px; }
/* ===== ③ 지표 스트립 — 좌측 2px 보더 + 모노 값(카드 없음) ===== */
.dash-kpis { display:flex; flex-wrap:wrap; gap:12px; margin:.1rem 0 1rem; }
.dash-kpi { flex:1 1 168px; min-width:0; display:flex; flex-direction:column; gap:3px;
  padding:2px 16px; }
.dash-klabel { font-size:13px; color:#6b665d; }
.dash-kval-row { display:flex; align-items:baseline; gap:4px; }
.dash-kval { font-size:27px; font-weight:600; letter-spacing:-0.03em; line-height:1.15; }
.dash-kunit { font-size:13px; color:#6b665d; }
/* ===== ④ 부서별 근무자 — 부서 → 조직 → 주간·야간·휴무 3열 ===== */
.dorg-major { font-size:15px; font-weight:600; color:#1c1a17; padding-bottom:6px;
  border-bottom:1px solid #cfc8bd; margin-top:14px; }
.dorg { margin-top:2px; }
.dorg-org { padding:14px 0 16px; border-bottom:1px solid #e6e2da; }
.dorg-ohead { display:flex; align-items:baseline; gap:10px; flex-wrap:wrap; }
.dorg-oname { font-size:14px; font-weight:600; color:#1c1a17; overflow-wrap:anywhere; }
.dorg-osum { margin-left:auto; font-size:12px; color:#6b665d; white-space:nowrap; }
.dorg-cols { display:flex; flex-wrap:wrap; gap:12px 28px; margin-top:9px; }
.dorg-col { flex:1 1 190px; min-width:0; }
.dorg-chead { display:flex; align-items:center; gap:7px; padding-bottom:5px;
  border-bottom:1px solid #e0dbd2; }
.dorg-dot { width:6px; height:6px; border-radius:1px; flex:0 0 auto; }
.dorg-clabel { font-size:13px; font-weight:500; color:#4a453d; }
.dorg-cnum { margin-left:auto; font-size:12px; color:#6b665d; }
.dorg-name { font-size:14.5px; color:#1c1a17; padding:6px 0; overflow-wrap:anywhere;
  border-bottom:1px solid #efece6; }
/* 모노 강제(값·건수) — 인라인 font-family 는 Streamlit 이 제거하므로 0,3,0 규칙으로 */
.stApp [data-testid="stMarkdownContainer"] .dash-kval,
.stApp [data-testid="stMarkdownContainer"] .dash-dow,
.stApp [data-testid="stMarkdownContainer"] .dorg-osum,
.stApp [data-testid="stMarkdownContainer"] .dorg-cnum {
  font-family:'IBM Plex Mono','Consolas','Menlo',monospace; font-variant-numeric:tabular-nums;
}
@media (max-width:768px) {
  /* 줄바꿈되면 칩을 우측으로 밀지 않는다(다음 줄 좌측 정렬) */
  .st-key-dash_qrow > div:last-child { margin-left:0 !important; }
  .dorg-cols { gap:10px 16px; }
  .dorg-col { flex:1 1 150px; }
}
@media (max-width:640px) {
  /* 폰 폭: 주간·야간·휴무 3열이 항상 한 줄에 들어가도록 백분율 기반으로 전환.
     150px 고정 basis 는 3열 합이 폰 폭을 넘어 줄바꿈을 만든다(2026-08-13 사용자 신고). */
  .dorg-cols { gap:8px 10px; }
  .dorg-col { flex:1 1 calc(33.333% - 7px); max-width:calc(33.333% - 7px); }
  .dorg-clabel { font-size:12px; }
  .dorg-cnum { font-size:11px; }
  .dorg-name { font-size:13.5px; padding:5px 0; }
}
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
