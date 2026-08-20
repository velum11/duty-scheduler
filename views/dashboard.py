"""홈 대시보드 — 선택한 일자의 근무 현황과 부서별 근무자.

세 역할이 **같은 골격**을 쓰고 데이터 범위만 갈린다(DESIGN.md §2 DASHBOARD: "역할에
따라 다른 화면을 만들지 않는다"). ADMIN 은 근태 대상 전 부서, MANAGER 는 담당 부서,
USER 는 같은 목록을 보되 **자기 부서의 대분류가 기본 선택**된다(2026-08-19 사용자
확정 규칙 · :func:`_default_major`). 데이터는 db 파사드를 통해 조회한다(샘플/Supabase
공통). 대시보드는 조회 전용이며 저장 계약과 무관하다.

화면 골격(사용자 재구성 지시서 · DESIGN.md §2~§4 토큰)::

    ① 제목/설명            상단 52px 헤더 우측에 선택 일자 스탬프
    ② 조회 행              [‹ | 일자 | ›] 세그먼트 · [오늘] · 부서 필터 칩(같은 그룹)
    ③ 내 근무(USER 전용)   오늘 근무 · 다음 근무 · 이번 달 집계
    ④ 지표 스트립          당일 근무 / 주간 / 야간 / 휴무
    ⑤ 부서별 근무자        부서(대분류) → 조직(중분류) → 버킷 열 명단(블록 자동 배치)

계층 용어: 화면의 "부서"는 조직 관리에서 사람이 입력하는 대분류(major_category),
"조직"은 중분류(minor_category)다(migration 009). 인원은 **중분류 단위로 합산**하므로
1팀/2팀·1파트/2파트 같은 하위 분할은 화면에 나타나지 않는다. 어떤 분류명도 코드에
고정하지 않으며, 유일한 예외는 사용자가 지정한 제외 규칙(아래 상수)이다.

모집단: 조직 관리에서 지정한 **근태(근무표) 등록 대상 부서**뿐이다(migration 011 ·
``db.attendance_dept_codes``). 지표·부서 필터 칩·명단이 모두 이 한 모집단에서 나오므로
셋이 서로 다른 말을 하지 않는다. 지정 컬럼을 판독할 수 없는 배포에서는 종전처럼 전
부서를 본다(``db.attendance_flag_ready()`` 폴백 — 조회 한정 fail-open).
"""
# DESIGN.md §0 화면 유형 규약 — 대시보드형.
SCREEN_ARCHETYPE = "DASHBOARD"

from datetime import date, timedelta
from html import escape
from math import ceil

import pandas as pd
import streamlit as st

from modules import db, ui
from views.common import erp

# 버킷 표시 순서. classify_work_group 은 주간/야간/OFF/휴가/None 을 반환한다.
# OFF→휴무, None→기타. 주간·야간·휴무는 항상 열로 두고, 휴가·기타는 실제 인원이 있을
# 때만 열을 덧붙인다(값이 있는데 사람을 조용히 떨어뜨리지 않기 위함).
_BUCKET_ORDER = ("주간", "야간", "휴무", "휴가", "기타")
_CORE_BUCKETS = ("주간", "야간", "휴무")
# 열 머리글 8px 사각 점 — 색만이 아니라 라벨을 병기하는 이중 부호화(장식용 보조 신호).
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

# ---------- 폭 산출(내용에서 역산) ----------
# 이 화면의 박스 폭은 "남는 폭을 균등 flex 로 나눠 갖기"가 아니라 **실제로 들어갈 문자열의
# 최대 폭**에서 나온다. 남는 폭은 남긴다.
#
# 글자폭 계수 실측(2026-08-19 재측정 · Pretendard 단일화 이후 · 이 화면 실렌더 ·
# Chromium · ``document.fonts.ready`` + 명시 load 확인): hidden span 에 같은 글자를
# **100자** 넣고 폭/100 으로 얻었다(1자 측정의 반올림 오차 제거). 12·14·20px 에서
# 계수가 동일했다(선형).
#   Pretendard — 한글 0.8643em (400·600 동일) · 숫자 0.6143em(400) / 0.6416em(600)
#                공백 0.251em(400) / 0.2373em(600) · 가운뎃점 0.2539em(400)
# 종전 값은 폐지된 IBM Plex 기준(한글 0.892 · ASCII 0.600)이었다. 한글은 과대(안전),
# **숫자는 과소** 추정이라 숫자 위주 문자열에서 폭이 모자랄 수 있었다. 아래 값은 두
# 굵기 중 넓은 쪽을 올림해 쓴다 — 과대 추정은 잘림을 만들지 않는 방향이다.
_ADV_KO = 0.865       # 한글 1자 / font-size
_ADV_ASCII = 0.642    # 숫자·영문 1자 / font-size (600 기준 = 넓은 쪽)
_ADV_SPACE = 0.252    # 공백 1자 / font-size (400 기준 = 넓은 쪽)
#: 이름 열 폭 상한. 이상치 이름 하나가 3열 합을 데스크톱 본문 폭 밖으로 밀지 않게 한다
#: (240×3 + 간격 48 = 768 ≤ 1024 본문). 넘는 이름은 ``overflow-wrap`` 으로 접힌다.
_COL_MAX_PX = 240
#: 일자 입력 폭 — 14px/600 숫자 0.642em × 10자("2026-08-19") ≒ 90px 상한(하이픈은 더
#: 좁다) + BaseWeb 내부 여백 4px(실측: wrapper 92 - input 88). 실측 렌더 폭으로 검증한다.
_DATE_W_PX = 92


def _text_px(text: str, size: float) -> float:
    """문자열의 렌더 폭(px) 추정 — 위 실측 계수만 쓴다(눈대중 값 금지).

    한글 외 비ASCII(가운뎃점 등)는 한글 계수로 계산한다. 실제보다 넓게 잡히지만 폭
    산출에서 과대 추정은 잘림을 만들지 않는 방향이라 안전하다.
    """
    total = 0.0
    for ch in text:
        if ch == " ":
            total += size * _ADV_SPACE
        elif ch.isascii():
            total += size * _ADV_ASCII
        else:
            total += size * _ADV_KO
    return total


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


def _attendance_scope() -> set[str] | None:
    """이 화면의 부서 모집단(근태 등록 대상). ``None`` 이면 제한 없음(종전 전 부서).

    - 지정 컬럼을 쓸 수 있으면 근태 등록 대상 부서코드 집합을 돌려준다. **비활성 부서도
      포함**한다(``is_active=None``) — 이 화면은 과거 일자도 조회하고, 지금도 비활성
      부서로 등록된 근무행을 버리지 않는다(:func:`_dept_index`). 새로 좁히는 축은
      '근태 대상 여부' 하나뿐이며 사용 여부 축의 거동은 종전 그대로다.
    - ``attendance_flag_ready()`` 가 False 면(스키마 미적용 배포) ``None`` 을 돌려
      **필터 자체를 걸지 않는다**. 이 상태에서 ``attendance_dept_codes()`` 는 전 부서를
      True 로 폴백하지만, 그 결과로 ``isin`` 필터를 걸면 부서 기준정보에 없는 코드의
      근무행이 조용히 사라진다(종전에는 미분류로 남았다). 폴백은 "종전과 동일"이어야
      하므로 집합이 아니라 무필터로 표현한다.
    """
    if not db.attendance_flag_ready():
        return None
    return db.attendance_dept_codes(is_active=None)


def render(user: dict) -> None:
    role = _clean(user.get("role")).upper()

    # ① 제목 — §1-F 헤더 중립 프레임(아이콘 밴드 없음: 표준 아이콘 8종은 상단 52px 헤더 소유).
    # 역할과 무관하게 같은 프레임·같은 블록을 쓴다(§2 DASHBOARD).
    erp.screen_frame(
        SCREEN_ARCHETYPE,
        title="대시보드",
        desc="선택한 날짜의 근무 현황과 부서별 근무자를 확인합니다.",
        breadcrumb="홈 › 대시보드",
    )
    _inject_style()

    # 범위 결정. ADMIN=전체, MANAGER=자기 부서, 부서 미확정 MANAGER=차단(fail-closed).
    # USER 는 같은 목록을 보되 **분류가 있는 부서만**(미분류 제외) 담고 자기 부서의
    # 대분류를 기본 선택으로 연다 — 범위를 잠그지는 않는다(사용자 확정 규칙).
    if role == "USER":
        manager_dept, classified_only = None, True
    else:
        scope, manager_dept = _scope_for(user)
        classified_only = False
        if scope == "blocked":
            ui.empty_state(
                "소속 부서가 지정되지 않아 근무 현황을 표시할 수 없습니다. "
                "관리자에게 부서 지정을 요청하세요.",
                head="당일 근무 현황",
            )
            return

    the_date = _resolve_date()
    # 조직 조회(부서 기준정보·근태 대상 지정·편성 스냅샷)도 오류 처리 범위에 포함한다 —
    # 근무 조회만 감싸면 계층 구성 중 데이터소스 오류가 화면 전체 예외가 된다.
    try:
        tracked = _attendance_scope()
        depts = db.get_org_departments()
        tree, majors = _duty_board(
            the_date, manager_dept=manager_dept, tracked=tracked, depts=depts,
            classified_only=classified_only,
        )
    except db.DATA_SOURCE_ERRORS as exc:
        st.error(f"근무 데이터를 불러오지 못했습니다. 데이터 연결 상태를 확인하세요. ({exc})")
        return
    except Exception:
        st.error("근무 정보를 불러오지 못했습니다. 잠시 후 다시 확인하세요.")
        return

    # ② 조회 행 — 일자 세그먼트 + [오늘] + 부서 칩(한 행·같은 그룹).
    default_major = _default_major(user, depts) if role == "USER" else _ALL_MAJORS
    picked = _query_row(the_date, majors, default=default_major)
    shown = tree if picked == _ALL_MAJORS else [m for m in tree if m["name"] == picked]
    totals, columns = _summarize(shown)

    # 상단 52px 헤더 우측 스탬프 — 조회 행과 **같은 run 에서** 같은 값을 채운다(슬롯 방식).
    ui.header_stamp(
        f"{the_date.isoformat()} ({ui.weekday_kr(the_date)}) · "
        f"{_scope_label(picked, manager_dept, tracked)}"
    )

    # ③ 내 근무(USER 전용) — 본인 근무가 USER 의 첫 관심사라 근무 인원보다 앞에 둔다.
    #    §2 의 "개인 맥락은 화면을 가르지 않는다"는 범위에서 **블록 하나**로만 둔다.
    if role == "USER":
        _my_duty_block(user)

    # ④ 지표 스트립. 값은 ⑤ 명단과 같은 집계에서 파생하므로 필터 선택과 항상 일치한다.
    st.markdown(_section_label("근무 인원"), unsafe_allow_html=True)
    st.markdown(_kpi_strip_html(totals), unsafe_allow_html=True)

    # ⑤ 부서별 근무자.
    if not shown:
        ui.empty_state(
            _empty_message(the_date, tracked, manager_dept, classified_only),
            head="부서별 근무자",
        )
        return
    st.markdown(_people_html(shown, columns), unsafe_allow_html=True)


def _section_label(text: str) -> str:
    """구획 제목 — §1.2 ``label-strong``(12/600 ink-2). 화면이 크기를 새로 만들지 않는다."""
    return f"<div class='dash-slabel'>{escape(text)}</div>"


def _default_major(user: dict, depts=None) -> str:
    """USER 의 부서 칩 **기본 선택**(대분류). 잠금이 아니라 첫 진입 기본값이다.

    2026-08-19 사용자 확정 규칙:

    - 소속 부서에 대분류·중분류가 **둘 다** 있으면 그 **대분류**를 기본 선택으로 연다.
      칩은 대분류 단위이므로(:func:`_query_row`) 중분류가 아니라 대분류를 고른다.
    - 소속 부서에 대분류나 중분류가 없으면(사무직 등 교대 조직 밖) 기본 선택을 두지
      않고 '전체'로 연다. 이때의 '전체'는 :func:`_duty_board` 의 ``classified_only``
      로 **분류가 있는 부서만** 담는다(미분류 제외).
    - 소속 부서가 아예 없는 USER 도 같은 '전체' 경로로 떨어진다.
    """
    dept = _clean(user.get("dept_code"))
    if not dept:
        return _ALL_MAJORS
    depts = db.get_org_departments() if depts is None else depts
    if depts is None or depts.empty:
        return _ALL_MAJORS
    for _, row in depts.iterrows():
        if _clean(row.get("dept_code")) != dept:
            continue
        major = _clean(row.get("major_category"))
        minor = _clean(row.get("minor_category"))
        return major if major and minor else _ALL_MAJORS
    return _ALL_MAJORS


def _scope_label(picked: str, manager_dept: str | None,
                 tracked: set | None = None) -> str:
    """헤더 스탬프의 범위 표기 — MANAGER 는 담당 부서, ADMIN 은 선택 대분류.

    ADMIN 이 '전체' 칩을 고른 상태에서 화면이 실제로 담는 것은 근태 등록 대상 부서
    전부다. 그래서 필터가 살아 있으면 '전사' 대신 '근태 대상'이라고 쓴다 — 4개 부서만
    보이는 화면에 '전사'라고 쓰면 스탬프가 사실과 다른 말을 한다. 필터가 없는 폴백
    상태에서는 종전대로 '전사'다.
    """
    if manager_dept:
        return db.dept_name(manager_dept) or manager_dept
    if picked != _ALL_MAJORS:
        return picked
    return "전사" if tracked is None else "근태 대상"


def _empty_message(the_date: date, tracked: set | None,
                   manager_dept: str | None, classified_only: bool = False) -> str:
    """명단이 비었을 때의 한 줄 안내 — '근무가 없다'와 '대상 부서가 아니다'는 다르다.

    지정이 하나도 없거나 담당 부서가 대상이 아니면 조회 결과가 아니라 조직 관리에서
    할 일이 남은 상태이므로, 다음 행동을 가리키는 문구를 쓴다(§6 카피: 한 줄·실무체).

    ``classified_only``(USER 경로)에서는 "근무가 없다"로 단정하지 않는다 — 대분류·중분류가
    아직 지정되지 않은 배포에서는 근무행이 있어도 이 경로가 전부 걸러내기 때문이다.
    """
    if classified_only:
        return (f"{the_date.isoformat()}({ui.weekday_kr(the_date)}) 표시할 근무 인원이 "
                "없습니다. 조직 관리에서 부서의 대분류·중분류 지정을 확인하세요.")
    if tracked is not None:
        if not tracked:
            return "조직 관리에서 근태 등록 대상 부서를 지정하면 근무 현황이 표시됩니다."
        if manager_dept and manager_dept not in tracked:
            return "담당 부서가 근태 등록 대상이 아닙니다. 조직 관리에서 지정을 확인하세요."
    return f"{the_date.isoformat()}({ui.weekday_kr(the_date)}) 등록된 근무가 없습니다."


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


def _query_row(the_date: date, majors: list, default: str = _ALL_MAJORS) -> str:
    """일자 세그먼트 + [오늘] + 부서 필터 칩을 **한 행**에 렌더하고 선택 대분류를 반환한다.

    세 컨트롤은 모두 "무엇을 조회할지"를 정하므로 **한 그룹으로 왼쪽에 모은다**. 종전에는
    칩만 ``margin-left:auto`` 로 우측 끝에 보내 1440 에서 세그먼트 끝(315px)과 칩
    시작(1166px) 사이가 851px 비었다(실측) — 같은 조회 조건을 눈으로 잇기 어려웠다.
    남는 폭은 흡수하지 않고 남긴다(이 화면의 폭 원칙과 같다).

    ``default`` 는 **첫 진입 기본 선택**이다(USER 는 자기 부서의 대분류). 세션에 값이
    없을 때만 쓰이고, 이후에는 사용자가 고른 값이 이긴다 — 범위를 잠그지 않는다.

    칩은 대분류 데이터에서 만든다('전체' + 근무자가 있는 대분류) — 대분류명을 코드에
    박지 않으므로 조직 개편이 그대로 반영되고, 근무자가 없는 대분류는 칩도 생기지
    않는다. 선택값은 canonical 키에 보관해 화면을 떠났다 돌아와도 유지한다.

    칩 목록은 :func:`_duty_board` 가 돌려준 계층에서 그대로 나오므로 **근태 등록 대상
    부서의 대분류만** 남는다(별도 필터를 두 번 걸지 않는다). '미분류' 칩도 같은 이유로
    "근태 대상인데 대분류가 비어 있는 부서"만 뜻하게 좁혀진다 — 감추지 않는 이유는
    종전과 같다(조직 관리에서 채워야 할 입력 누락을 관리자가 발견해야 한다).
    """
    options = [_ALL_MAJORS] + list(majors)
    stored = st.session_state.get(_DASHBOARD_MAJOR)
    if stored is None and default in options:
        stored = default  # 첫 진입 기본 선택(USER: 자기 부서 대분류)
        st.session_state[_DASHBOARD_MAJOR] = stored
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
                    label_visibility="collapsed", width=_DATE_W_PX,
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


def _duty_board(the_date, *, manager_dept=None, tracked=None, classified_only=False,
                depts=None, users=None, day_rows=None):
    """선택 일자의 근무행을 부서(대분류) → 조직(중분류) → 버킷별 명단으로 모은다.

    - 소속 판정: 그 달 편성 스냅샷 우선, 없으면 현재 users 소속 폴백(표시용·저장 금지).
    - 버킷 판정: :func:`_bucket_of` (= ``db.classify_work_group``) — 새 분류를 만들지 않는다.
    - 인원은 **중분류 단위로 합산**한다(PET생산1팀·2팀 → PET생산팀). 중분류가 빈 부서는
      부서명을 조직 라벨로 쓴다.
    - 근무자가 없는 조직·부서는 애초에 생기지 않는다(근무행에서만 계층을 만든다).
    - ``manager_dept`` 가 지정되면 그 부서 근무자만 집계한다(MANAGER 범위).
    - ``tracked`` 가 부서코드 집합이면 그 부서(근태 등록 대상)만 집계한다. ``None``
      (기본)이면 제한이 없다 — 화면은 :func:`_attendance_scope` 로 값을 만들어 넘긴다.
      **지표·칩·명단이 모두 이 한 트리에서 파생**하므로 모집단이 갈릴 수 없다.
    - ``classified_only`` 가 True 면 **대분류·중분류가 둘 다 있는 부서만** 담는다
      (USER 경로 — 사용자 확정 규칙). 미분류는 조직 관리의 입력 누락을 관리자가
      발견하기 위한 노출이라 USER 화면에서는 빼고, 대신 지표와 명단이 같은 트리에서
      나오는 성질은 그대로 유지한다.
    - tracked/depts/users/day_rows 는 화면(및 테스트)이 주입한다.

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
        # 근태 등록 대상 지정(조직 관리 · migration 011). 소속을 해석하지 못한 근무행
        # (dept 공백)도 여기서 빠진다 — 어느 대상 부서에도 속하지 않는 근무를 '대상
        # 부서만' 보는 화면에 남길 근거가 없다. 지표는 명단의 합이므로 같이 빠진다.
        if tracked is not None and dept not in tracked:
            continue
        major, minor, order, dept_name = index.get(
            dept, ("", "", _TAIL_ORDER, db.dept_name(dept) or dept)
        )
        if classified_only and not (major and minor):
            continue  # 분류가 없는 부서(교대 조직 밖)는 USER 경로에서 제외
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
def _tiles_html(items: list, css_class: str) -> str:
    """지표 타일 스트립 — 좌측 2px 보더 + 20/600 값(카드 없음). 첫 타일만 액센트.

    ``items`` 는 ``(라벨, 값, 단위, 액센트여부)`` 목록이다. 근무 인원 지표와 USER 의
    '내 근무'가 **같은 타일**을 쓴다 — 한 화면에 지표를 두 가지 모양으로 그리면
    (종전: 카드형 ``sum-card`` + 보더형 ``dash-kpi``) 같은 계층이 다른 말을 한다.

    **타일 폭은 내용에서 역산한다.** 종전에는 ``flex:1 1 168px`` 로 남는 폭을 4등분해
    한 자리 숫자가 311px(1440 실측)을 차지했다. 지금은 이번 run 에 실제로 그릴 라벨과
    값의 최대 폭으로 폭을 정하고 **남는 폭은 남긴다**. 한 스트립의 타일은 같은 값을
    공유하므로 세로 눈금이 어긋나지 않는다.
    """
    # 라벨(12px)과 값 줄(20px 값 + 4px gap + 12px 단위) 중 넓은 쪽 + 좌우 padding
    # 16×2(§1.1) + 좌측 액센트 보더 2px. box-sizing:border-box 기준.
    content = max(
        max(_text_px(label, 12) for label, _v, _u, _a in items),
        max(_text_px(str(value), 20) + (4 + _text_px(unit, 12) if unit else 0)
            for _l, value, unit, _a in items),
    )
    tile_px = ceil(2 + 16 * 2 + content)
    cells = []
    for label, value, unit, accent in items:
        border = "#c2410c" if accent else "#cfc8bd"
        vcolor = "#b4451a" if accent else "#1c1a17"
        unit_html = f"<span class='dash-kunit'>{escape(unit)}</span>" if unit else ""
        cells.append(
            f"<div class='dash-kpi' style='border-left:2px solid {border};'>"
            f"<span class='dash-klabel'>{escape(label)}</span>"
            f"<div class='dash-kval-row'>"
            f"<span class='dash-kval' style='color:{vcolor};'>{escape(str(value))}</span>"
            f"{unit_html}</div></div>"
        )
    # 폭은 <style> 로 넘긴다 — Streamlit 이 인라인 style 의 일부 속성을 제거하므로
    # (같은 사유로 font-family 도 CSS 규칙으로 강제한다) 인라인 width 에 의존하지 않는다.
    return (f"<style>.{css_class} .dash-kpi{{width:{tile_px}px}}</style>"
            f"<div class='dash-kpis {css_class}'>{''.join(cells)}</div>")


def _kpi_strip_html(totals: dict) -> str:
    """근무 인원 지표(당일 근무 / 주간 / 야간 / 휴무) — 값은 명단의 합이다."""
    on_duty = totals.get("주간", 0) + totals.get("야간", 0)
    return _tiles_html([
        ("당일 근무", on_duty, "명", True),
        ("주간", totals.get("주간", 0), "명", False),
        ("야간", totals.get("야간", 0), "명", False),
        ("휴무", totals.get("휴무", 0), "명", False),
    ], "dash-kpis-duty")


def _org_col_px(tree: list, columns: list) -> int:
    """명단 열 폭(px) — 이번 run 에 실제로 그릴 내용의 최대 폭에서 역산한다.

    두 가지 중 넓은 쪽이다.

    1. 열 머리글: 점 8 + 간격 8 + 버킷 라벨(12px sans) + 간격 8 + 건수(12px mono).
       건수는 ``margin-left:auto`` 로 우측 끝에 붙으므로 라벨과 최소 8px 은 떨어진다.
    2. 가장 긴 이름(14px sans).

    화면 전체가 **한 값**을 공유한다 — 열마다 제 폭을 갖게 하면 조직끼리 세로로 맞춰
    읽히지 않는다(같은 버킷이 다른 x 좌표에 놓인다). 종전 ``flex:1 1 190px`` 은 남는
    폭을 열 수로 나눠 1440 에서 408px 짜리 열을 만들었다.

    조직 블록이 한 줄에 여러 개 놓이게 된 뒤에도 이 계약은 그대로다: 블록 폭 =
    ``열폭 × 열수 + 간격 × (열수-1)`` 로 모든 블록이 같고 블록 간격도 고정이라, 같은
    버킷 열의 x 좌표가 화면 전체에서 규칙적인 격자에 놓인다(:func:`_people_html`).
    """
    need = 0.0
    for major in tree:
        for org in major["orgs"]:
            for bucket in columns:
                members = org["people"].get(bucket, [])
                head = (8 + 8 + _text_px(bucket, 12) + 8
                        + _text_px(str(len(members)), 12))
                need = max(need, head)
                for person in members:
                    need = max(need, _text_px(person["name"], 14))
    return min(ceil(need), _COL_MAX_PX)


def _people_html(tree: list, columns: list) -> str:
    """부서 → 조직 → 버킷 열 명단(이름은 열 아래로 세로로 쌓인다).

    이름마다 위젯을 만들지 않고 한 번의 HTML 로 렌더한다(리렌더 비용·간격 붕괴 방지).
    열 폭은 :func:`_org_col_px` 가 내용에서 역산하며, 남는 폭은 남긴다.

    **조직 블록은 한 부서 안에서 줄바꿈 배치한다**(``.dorg-grid``). 종전에는 블록이
    본문 폭 전체를 차지하는 행이라, 이름 3자(열 53px)짜리 명단이 1440 에서 284px 만
    쓰고 오른쪽 1121px(79.8%)이 통째로 비었다(실측). 블록 폭은 내용에서 나온 값
    그대로 두고 **블록을 옆으로 채운다** — 열 폭을 억지로 늘리지 않으므로 열 정렬
    계약(:func:`_org_col_px`)도 유지된다.

    조직 줄에는 합계 요약을 쓰지 않는다. 같은 숫자를 열 머리글이 각 열 위에서 이미
    말하고 있어(주간 6 / 야간 5 …) 요약은 **같은 말의 반복**이었다. 남긴 쪽은 열
    머리글이다 — 숫자가 세는 대상 바로 위에 붙어 있어 스캔에 쓰이지만, 요약은 이름
    열에서 최대 200px 떨어진 자리에서 같은 네 숫자를 다시 읽게 했다.
    """
    blocks = []
    for major in tree:
        # 부서 헤더 우측은 비운다(합계는 열 머리글이 말한다 — 같은 말을 두 번 하지 않는다).
        blocks.append(f"<div class='dorg-major'>{escape(major['name'])}</div>")
        orgs_html = []
        for org in major["orgs"]:
            counts = {b: len(org["people"].get(b, [])) for b in columns}
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
            orgs_html.append(
                "<div class='dorg-org'><div class='dorg-ohead'>"
                f"<span class='dorg-oname'>{escape(org['name'])}</span></div>"
                f"<div class='dorg-cols'>{''.join(cols_html)}</div></div>"
            )
        blocks.append(f"<div class='dorg-grid'>{''.join(orgs_html)}</div>")
    # 열 폭·열 수만 넘기고 블록 폭은 CSS 가 두 값에서 계산한다(계산식은 _inject_style).
    return (f"<style>.dorg{{--dorg-colw:{_org_col_px(tree, columns)}px;"
            f"--dorg-n:{len(columns)}}}</style>"
            f"<div class='dorg'>{''.join(blocks)}</div>")


def _inject_style() -> None:
    # §1.3 팔레트 · §1.2 타이포(24/20/14/12 네 단계 · 굵기 400·600 · Pretendard 하나) ·
    # §1.1 간격(4·8·12·16·24·32·40).
    # 카드(테두리+radius+그림자) 없음 — 구획은 헤어라인과 여백뿐.
    # 밀도는 §1.4 **cozy(히트영역 44px 이상)** 다. §3.4 가 이 화면을 "모바일 우선"으로
    # 이름 지어 지목하기 때문이다. 종전 주석은 근거로 "히트영역 하한 32px(§0.6·§4)"를
    # 들었는데 현행 DESIGN.md 에 §0.6 은 없고 §4(금지)에도 히트영역 규정이 없다 —
    # 죽은 절 인용이었고 값도 cozy 하한을 12px 밑돌았다(2026-08-18 정정).
    # 폭은 CSS 가 정하지 않는다 — _text_px 실측 계수로 내용에서 역산해 <style> 로 넘긴다
    # (_kpi_strip_html · _org_col_px). 남는 폭은 흡수하지 않고 남긴다.
    # 굵기는 400·600 만 쓴다(§1.2). 자릿수 정렬은 모노가 아니라 tabular-nums 다.
    st.markdown(
        """
<style>
/* ===== ② 조회 행 — 세그먼트 + [오늘] + 우측 끝 부서 칩(한 행), 하단 헤어라인 ===== */
.st-key-dash_qrow { align-items:center !important; flex-wrap:wrap !important;
  gap:12px !important; border-bottom:1px solid #e0dbd2; padding-bottom:12px;
  margin-bottom:16px; }
.st-key-dash_qrow > div { flex:0 0 auto !important; }
/* 조회 컨트롤 3종은 한 그룹으로 좌측에 모은다(종전 칩 margin-left:auto → 1440 에서
   세그먼트 끝과 칩 사이 851px 공백, 실측). 남는 폭은 흡수하지 않고 남긴다. */
/* 전일 | 일자 | 익일 = 한 덩어리(외곽 1px, 내부 구분선만).
   조회 행 컨트롤의 바깥 높이는 46px = 히트영역 44(§1.4 cozy) + 상하 1px 헤어라인이다.
   세그먼트에는 height 를 주지 않는다 — box-sizing:border-box 라 height:44 를 주면 내부
   버튼이 42px 로 눌려 히트영역이 하한을 밑돈다(종전 34/32 가 그 구조였다). */
.st-key-dash_seg { border:1px solid #e2ddd4; border-radius:8px;
  background:#fff; overflow:hidden; align-items:stretch !important; gap:0 !important;
  padding:0 !important; }
.st-key-dash_seg > div { flex:0 0 auto !important; display:flex; align-items:center; }
.st-key-dash_seg > div + div { border-left:1px solid #eeeae3; }
/* 후손 선택자로 잡는다 — help(툴팁) 래퍼가 있으면 button 이 .stButton 의 직계자식이
   아니라 직계자식 선택자는 크기 규칙을 놓친다(키트 _KIT_CSS 주석과 같은 사유). */
.st-key-dash_seg button {
  height:44px !important; min-height:44px !important; min-width:44px; padding:0 12px;
  border:0 !important; border-radius:0 !important; background:transparent !important;
  box-shadow:none !important; color:#4a453d !important; font-size:14px !important;
  line-height:1; }
.st-key-dash_seg button:hover { background:#f1eee8 !important; color:#1c1a17 !important; }
.st-key-dash_seg button:focus-visible { outline:2px solid #c2410c; outline-offset:-2px; }
.st-key-dash_seg div.stButton, .st-key-dash_seg div[data-testid="stTooltipHoverTarget"] {
  display:flex; align-items:center; }
/* 일자 텍스트 = 모노 14px. date_input 은 세그먼트 안에서 테두리 없이 값처럼 보이게.
   폭 __DATEW__px 의 근거는 _DATE_W_PX 주석(모노 14px 숫자 0.6em × 10자 역산). */
.st-key-dash_segval { padding:0 8px 0 12px; gap:4px !important; }
.st-key-dash_segval div[data-testid="stDateInput"] { width:__DATEW__px; }
.st-key-dash_segval div[data-baseweb="input"] { border:0 !important; background:transparent !important;
  box-shadow:none !important; height:44px; padding-right:4px !important; }
.st-key-dash_segval div[data-baseweb="input"] div { padding-right:0 !important; }
/* 굵기는 400·600 둘뿐이다(§1.2) — 종전 500 은 스케일 밖이었다. */
.st-key-dash_segval input { padding:0 !important; height:44px; color:#1c1a17 !important;
  font-family:"Pretendard","Malgun Gothic",-apple-system,sans-serif !important; font-size:14px !important;
  font-weight:600 !important; font-variant-numeric:tabular-nums; cursor:pointer; }
.st-key-dash_segval div[data-testid="stDateInput"] svg { width:16px; height:16px; color:#8b857c; }
.dash-dow { font-family:"Pretendard","Malgun Gothic",-apple-system,sans-serif; font-size:14px;
  font-weight:600; white-space:nowrap; }
/* 버튼 라벨의 실제 글자 크기는 button 이 아니라 그 안의 마크다운 컨테이너가 정한다.
   modules/ui.py 가 `button p{font-size:inherit}` 를 넣었지만, Streamlit 은 p 의 부모인
   [data-testid=stMarkdownContainer] 에 .875rem(12.25px)을 걸어 두어 p 가 button 이
   아니라 그 컨테이너를 상속한다(실측: [오늘] 라벨 12.25px). 공용 규칙은 수정 범위 밖이라
   이 화면 안에서만 컨테이너를 함께 잡는다 — 공용 보정 필요 사항으로 보고한다. */
.st-key-dash_seg button p, .st-key-dash_today button p,
.st-key-dash_seg button [data-testid="stMarkdownContainer"],
.st-key-dash_today button [data-testid="stMarkdownContainer"] {
  font-size:14px !important; line-height:1.2; }
.st-key-dash_seg button p { line-height:1; }
/* Streamlit·BaseWeb 기본 간격 정리 — 아래 값들은 자식이 하나거나 서로 상쇄돼 렌더 결과에
   영향이 없지만 §1.1 스케일 밖(7 · 9.1 · 3.5 · ±14px)이라 이 화면 범위에서만 토큰 값으로
   덮어 둔다. 공용 계층(modules/ui.py·views/common/erp)은 수정 범위 밖이라 손대지 않는다. */
.st-key-dash_qrow button span { gap:8px !important; }
.st-key-dash_chips { gap:8px !important; }
/* segval 안에는 date_input 하나뿐이라 범위가 닫혀 있다 — BaseWeb/Streamlit 위젯 내부의
   0.25rem(3.5px) 기본 간격을 토큰 값으로 통일한다. */
.st-key-dash_segval div { row-gap:4px !important; column-gap:4px !important; }
.st-key-dash_segval div[data-baseweb="input"] div { padding-right:0 !important; }
.st-key-dash_segval [data-testid="stMarkdownContainer"],
.st-key-dash_segval [data-testid="stMarkdownContainer"] p { margin-bottom:0 !important; }
/* [오늘] = 분리된 보조 버튼(세그먼트와 같은 바깥 높이 46 = 히트영역 44 + 테두리 2) */
.st-key-dash_today button {
  height:46px !important; min-height:46px !important; padding:0 16px;
  border:1px solid #e2ddd4 !important; border-radius:8px; background:#fff !important;
  color:#4a453d !important; font-size:14px; }
.st-key-dash_today button:hover { background:#f1eee8 !important; color:#1c1a17 !important; }
/* 부서 필터 칩(st.pills = stButtonGroup) — 선택은 오렌지 틴트 pill, 비선택은 중립 테두리.
   높이 46 = 히트영역 44(§1.4 cozy) + 테두리 2. 종전 32px 는 §1.4 의 어느 단계에도
   없는 값이었다(compact 조차 34~38). */
/* 칩 사이 간격 — 버튼은 stButtonGroup 의 **손자**라 그룹에만 gap 을 걸면 실제 간격은
   Streamlit 기본 0.25rem(3.5px)이 그린다(실측). 내부 래퍼까지 함께 잡는다. */
.st-key-dash_chips div[data-testid="stButtonGroup"],
.st-key-dash_chips div[data-testid="stButtonGroup"] > div { gap:8px !important; flex-wrap:wrap; }
.st-key-dash_chips div[data-testid="stButtonGroup"] button {
  min-height:46px; padding:0 16px; border-radius:999px;
  border:1px solid #e2ddd4 !important; background:#fff !important; color:#6b665d !important;
  font-size:14px !important; font-weight:400; }
.st-key-dash_chips div[data-testid="stButtonGroup"] button p { font-size:14px !important; }
.st-key-dash_chips div[data-testid="stButtonGroup"] button:hover {
  border-color:#cfc8bd !important; color:#1c1a17 !important; }
.st-key-dash_chips div[data-testid="stButtonGroup"] button[aria-checked="true"] {
  border-color:#c2410c !important; background:#fdf3ec !important; color:#b4451a !important;
  font-weight:600; }
.st-key-dash_chips div[data-testid="stButtonGroup"] button:focus-visible {
  outline:2px solid #c2410c; outline-offset:1px; }
/* ===== ③ 지표 스트립 — 좌측 2px 보더 + 모노 값(카드 없음) =====
   폭은 여기서 정하지 않는다. _kpi_strip_html 이 이번 run 의 라벨·값 최대 폭에서 역산해
   <style> 로 넘긴다(종전 flex:1 1 168px 은 남는 폭을 4등분해 한 자리 숫자에 311px 을
   줬다 — 1440 실측). 타이포는 §1.2 다섯 단계만: 값 20 · 라벨/단위 12.
   ※ 공용 키트 지표 타일(views/common/erp/kit.py `.erp-metric*`)은 아직 값 26 · 단위 11.5 ·
   padding 2/18 이라 이 화면과 값이 갈린다. 키트는 이 작업의 수정 범위 밖이라 손대지 않고
   보고한다(§1.2·§1.1 위반이 키트 쪽에 남아 있음). */
.dash-kpis { display:flex; flex-wrap:wrap; gap:16px; margin:0 0 24px; }
.dash-kpi { box-sizing:border-box; flex:0 0 auto; display:flex; flex-direction:column;
  gap:4px; padding:0 16px; }
.dash-klabel { font-size:12px; color:#6b665d; white-space:nowrap; }
.dash-kval-row { display:flex; align-items:baseline; gap:4px; }
.dash-kval { font-size:20px; font-weight:600; line-height:1.2; overflow-wrap:anywhere; }
.dash-kunit { font-size:12px; color:#6b665d; }
/* 구획 제목 — §1.2 label-strong(12/600 ink-2). 지표 스트립·내 근무·부서 헤더가 서로
   다른 계층임을 크기로 구분한다(구획 12/600 < 조직명 14/600 < 부서 20/600). */
.dash-slabel { font-size:12px; font-weight:600; color:#4a453d; margin:0 0 8px; }
/* ===== ⑤ 부서별 근무자 — 부서 → 조직 블록(줄바꿈 배치) → 버킷 열 ===== */
/* 부서(대분류)는 구획을 나누는 제목이라 §1.2 section(20/600). 종전 16px 은 §1.2 의
   네 단계(24/20/14/12) 밖이었다. */
.dorg-major { font-size:20px; font-weight:600; color:#1c1a17; padding-bottom:8px;
  border-bottom:1px solid #cfc8bd; margin-top:24px; }
.dorg { margin-top:0; --dorg-gap:24px; }
/* 조직 블록 줄바꿈 배치 — 블록 폭은 내용에서 나온 열 폭×열 수 그대로이고, 한 줄에
   들어가는 만큼 옆으로 채운다. 블록 사이 32 > 블록 안 열 사이 24 라 어느 열이 어느
   조직 것인지 근접성으로 읽힌다(§1.1 스케일). */
.dorg-grid { display:flex; flex-wrap:wrap; gap:0 32px; align-items:stretch; }
.dorg-org { box-sizing:border-box; flex:0 0 auto; min-width:0; max-width:100%;
  width:calc(var(--dorg-colw) * var(--dorg-n) + var(--dorg-gap) * (var(--dorg-n) - 1));
  padding:16px 0; border-bottom:1px solid #e6e2da; }
.dorg-ohead { display:flex; align-items:baseline; gap:12px; flex-wrap:wrap; }
.dorg-oname { font-size:14px; font-weight:600; color:#1c1a17; overflow-wrap:anywhere; }
.dorg-cols { display:flex; flex-wrap:wrap; gap:12px var(--dorg-gap); margin-top:12px; }
/* 폭은 _org_col_px 가 내용에서 역산해 <style> 로 넘긴다(종전 flex:1 1 190px 은 3열이
   남는 폭을 나눠 가져 1440 에서 408px 짜리 열이 됐다). */
.dorg-col { box-sizing:border-box; flex:0 0 auto; min-width:0; width:var(--dorg-colw); }
.dorg-chead { display:flex; align-items:center; gap:8px; padding-bottom:8px;
  border-bottom:1px solid #e0dbd2; }
.dorg-dot { width:8px; height:8px; border-radius:2px; flex:0 0 auto; }
.dorg-clabel { font-size:12px; font-weight:600; color:#4a453d; }
.dorg-cnum { margin-left:auto; font-size:12px; color:#6b665d; }
.dorg-name { font-size:14px; color:#1c1a17; padding:8px 0; overflow-wrap:anywhere;
  border-bottom:1px solid #efece6; }
/* 숫자 자릿수 정렬(§1.2: 모노 폐지, tabular-nums) — 인라인 font-family 는 Streamlit 이
   제거하므로 0,3,0 규칙으로 확정한다. */
.stApp [data-testid="stMarkdownContainer"] .dash-kval,
.stApp [data-testid="stMarkdownContainer"] .dash-dow,
.stApp [data-testid="stMarkdownContainer"] .dorg-cnum {
  font-family:"Pretendard","Malgun Gothic",-apple-system,sans-serif; font-variant-numeric:tabular-nums;
}
/* §3.4 브레이크포인트 — <599 / 599–1023 / >1023. 종전 768/640 은 §3.4 값이 아니었다. */
@media (max-width:598px) {
  /* 지표는 §3.4 대로 2열. 폭은 여전히 내용값이다 — grid track 을 max-content 로 두면
     타일이 남는 폭을 흡수하지 않고 제 폭만 쓴다. */
  .dash-kpis { display:grid; grid-template-columns:repeat(2,max-content); }
  /* 폰에서는 조직 블록이 1열(본문 폭)이고, 버킷 열은 항상 한 줄에 남는다(2026-08-13
     사용자 신고 "폰에서 주간·야간·휴무 줄바꿈" 재발 방지). 상한이 폭을 정하는 것이
     아니라 최악의 경우만 막는다 — 내용 폭이 상한보다 좁으면 내용 폭 그대로다. */
  .dorg-org { width:100%; }
  .dorg-col { max-width:calc((100% - var(--dorg-gap) * (var(--dorg-n) - 1)) / var(--dorg-n)); }
}
</style>
""".replace("__DATEW__", str(_DATE_W_PX)),
        unsafe_allow_html=True,
    )


def _my_duty_block(user: dict) -> None:
    """USER 의 '내 근무' 블록 — 근무 인원 위에 **한 블록**으로 둔다.

    종전에는 이 요약이 USER 화면 전체였고(역할별 다른 화면), 카드 5장이 근무 인원
    지표와 다른 모양이었다. 지금은 같은 지표 타일(:func:`_tiles_html`)을 써서 한
    화면 안에서 같은 계층이 같은 말투를 쓰게 한다. 값은 오늘 기준이며(라벨이 '오늘'·
    '이번 달'이라 조회 일자와 혼동되지 않는다) 조회 일자는 아래 근무 인원이 따른다.

    이 블록의 오류는 화면 전체를 접지 않는다 — 아래 근무 인원은 별개 조회다.
    """
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
        st.error("내 근무 정보를 불러오지 못했습니다. 잠시 후 다시 확인하세요.")
        return

    def _duty_label(code: str) -> str:
        """근무조건표(근무형태 관리) 약칭 표시 — 미등록 코드만 원문 폴백.
        조회 전용 값이라 약칭 중복(주/야 다수 코드)이어도 역해석 걱정이 없다
        (내 근무표와 같은 규칙 — 2026-08-20 DAY/NIGHT 코드 원문 노출 정정)."""
        short = str((work_types.get(str(code)) or {}).get("short_label") or "").strip()
        return short or str(code)

    today_rows = rows[rows["date"] == today] if not rows.empty else rows
    today_code = "미등록" if today_rows.empty else _duty_label(today_rows.iloc[0]["work_type_code"])

    future = rows[rows["date"] > today].sort_values("date") if not rows.empty else rows
    if future.empty:
        next_label, next_value = "다음 근무", "데이터 없음"
    else:
        next_row = future.iloc[0]
        next_date = next_row["date"]
        next_label = "내일 근무" if (next_date - today).days == 1 else f"다음 근무 ({next_date.month}/{next_date.day})"
        next_value = _duty_label(next_row["work_type_code"])

    counts = {"주간": 0, "야간": 0, "OFF": 0}
    for code, count in month_rows["work_type_code"].value_counts().items():
        group = db.classify_work_group(str(code), work_types.get(str(code), {}))
        if group in counts:
            counts[group] += int(count)

    items = [
        ("오늘 내 근무", today_code, "", True),
        (next_label, next_value, "", False),
        ("이번 달 주간", counts["주간"], "회", False),
        ("이번 달 야간", counts["야간"], "회", False),
        ("이번 달 OFF", counts["OFF"], "회", False),
    ]
    st.markdown(_section_label("내 근무"), unsafe_allow_html=True)
    st.markdown(_tiles_html(items, "dash-kpis-my"), unsafe_allow_html=True)
