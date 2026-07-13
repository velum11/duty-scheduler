"""공통 UI — App Shell + 화면 공통 컴포넌트 (DESIGN.md 구현).

App Shell 구조 (DESIGN.md §2):
  좌측 1차 메뉴 바(네이비 112px) + 좌측 2차 업무 메뉴 패널(196px)
  + 우측 메인 콘텐츠(상단 헤더 → 페이지 제목 → 조회 조건 → 요약 카드 → 그리드).

구현 방식: Streamlit 사이드바 하나를 CSS gradient 로 좌/우 영역으로 나누고,
내부를 컬럼 2개(아이콘 바 / 메뉴 패널)로 구성한다. CSS 는 이 모듈에서만 관리한다.

공개 API:
- setup_page      페이지 설정 + 전역 CSS (다른 st 호출보다 먼저)
- app_shell       사이드바 2단 메뉴 + 상단 헤더 렌더링, 선택된 page id 반환
- mobile_header   USER(모바일) 상단 헤더 (App Shell 미적용, DESIGN.md §17)
- page_header / page_title / card / summary_cards / empty_state / action_bar
- badge_html / legend_html / weekday_kr / weekend_color / role_label
"""
from datetime import date

import streamlit as st

from modules import auth, config, db, nav

_WEEKDAY = ["월", "화", "수", "목", "금", "토", "일"]

_ROLE_LABEL = {"ADMIN": "관리자", "MANAGER": "매니저", "USER": "직원"}

# 전체 폭은 유지하고 1차 메뉴명을 표시할 공간만 내부에서 재배분한다.
_RAIL_W = 112
_PANEL_W = 196
_SIDEBAR_W = _RAIL_W + _PANEL_W

_CSS = f"""
<style>
/* ===== 기본 ===== */
html, body, .stApp {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Malgun Gothic",
               "Apple SD Gothic Neo", Arial, sans-serif;
  font-size: 14px;
}}
.stApp {{ background: #F7F8FA; }}

/* Streamlit 기본 장식 숨김 — stToolbar 는 사이드바 펼침 버튼을 포함하므로 숨기지 않는다 */
#MainMenu, footer, .stAppDeployButton,
div[data-testid="stDecoration"],
div[data-testid="stStatusWidget"] {{ display: none !important; }}

section[data-testid="stMain"] .block-container {{
  padding: 0 1.25rem 2rem; max-width: 100%;
}}
/* 메인 영역 블록 간격을 좁혀 업무 화면 정보 밀도를 높인다 */
section[data-testid="stMain"] div[data-testid="stVerticalBlock"] {{ gap: 0.65rem; }}
section[data-testid="stMain"] div[data-testid="stHorizontalBlock"] {{ gap: 0.6rem; }}

/* ===== 좌측 사이드바 = 1차 아이콘 바(네이비) + 2차 메뉴 패널 ===== */
section[data-testid="stSidebar"] {{
  width: {_SIDEBAR_W}px !important; min-width: {_SIDEBAR_W}px !important;
  max-width: {_SIDEBAR_W}px !important;
  background: linear-gradient(90deg, #071527 0, #071527 {_RAIL_W}px, #F3F5F8 {_RAIL_W}px);
  border-right: 1px solid #D3DAE3;
}}
section[data-testid="stSidebar"] > div:first-child {{ width: {_SIDEBAR_W}px !important; }}
div[data-testid="stSidebarContent"] {{ padding: 0 !important; }}
div[data-testid="stSidebarUserContent"] {{ padding: 0 !important; }}
section[data-testid="stSidebar"] div[data-testid="stHorizontalBlock"] {{ gap: 0 !important; }}
section[data-testid="stSidebar"] div[data-testid="stVerticalBlock"] {{ gap: 0.1rem; }}

/* 1차 아이콘 메뉴 바 */
.st-key-nav_rail {{ padding-top: 0.75rem; }}
.st-key-nav_rail,
.st-key-nav_rail div[data-testid="stVerticalBlock"],
.st-key-nav_rail div.stButton {{
  overflow: visible !important;
}}
.st-key-nav_rail div.stButton {{
  position: relative;
}}
.st-key-nav_rail div.stButton > button {{
  display: flex; justify-content: flex-start; align-items: center; gap: 0.35rem;
  width: calc(100% - 12px); height: 42px; min-height: 42px; margin: 0 auto; padding: 0 0.55rem;
  border: none; border-radius: 8px;
  background: transparent; color: #8FA3BE;
  font-size: 0.74rem; font-weight: 600; white-space: nowrap; overflow: hidden;
}}
.st-key-nav_rail div.stButton > button:hover {{ background: #0F2A4A; color: #FFFFFF; }}
.st-key-nav_rail div.stButton > button[kind="primary"] {{ background: #12345A; color: #FFFFFF; }}
.st-key-nav_rail div.stButton > button [data-testid="stIconMaterial"] {{ font-size: 20px; flex: 0 0 auto; }}

/* 2차 업무 메뉴 패널 — ERP 메뉴 트리 */
.st-key-nav_menu {{ padding: 0.7rem 0.55rem 1rem 0.55rem; }}
.nav-appname {{
  font-size: 0.92rem; font-weight: 700; color: #1E3A6E; letter-spacing: -0.01em;
  padding: 0.1rem 0.5rem 0.55rem; border-bottom: 1px solid #D3DAE3; margin-bottom: 0.55rem;
}}
.nav-group-label {{
  display: block;
  font-size: 0.86rem; font-weight: 700; color: #1E3A6E; letter-spacing: -0.005em;
  line-height: 1.35; white-space: normal; overflow-wrap: anywhere;
  padding: 0.48rem 0.55rem 0.42rem;
  margin: 0.35rem 0.15rem 0.62rem;
  border-bottom: 1px solid #DDE3EA;
}}
.st-key-nav_menu div.stButton {{ margin-left: 0.35rem; border-left: 1px solid #DDE3EA; }}
.st-key-nav_menu div.stButton > button {{
  width: 100%; min-height: 1.95rem; padding: 0.18rem 0.6rem;
  justify-content: flex-start; text-align: left;
  border: none; border-left: 2px solid transparent; border-radius: 0 4px 4px 0;
  font-size: 0.83rem; font-weight: 500;
}}
.st-key-nav_menu div.stButton > button[kind="secondary"] {{ background: transparent; color: #3A3F45; }}
.st-key-nav_menu div.stButton > button[kind="secondary"]:hover {{
  background: #E7ECF3; color: #1E3A6E; border-left-color: #9FB2CE;
}}
.st-key-nav_menu div.stButton > button[kind="primary"] {{
  background: #1E3A6E; color: #FFFFFF; font-weight: 600; border-left-color: #0F2A4A;
}}

/* ===== 상단 헤더 (얇은 업무 시스템 헤더) ===== */
.st-key-app_header {{
  background: #FFFFFF; border-bottom: 1px solid #D3DAE3;
  margin: 0 -1.25rem 0.85rem; padding: 0.4rem 1.25rem 0.38rem;
}}
.hdr-screen {{ font-size: 0.92rem; font-weight: 600; color: #26282B; }}
.hdr-user {{ text-align: right; color: #6B7280; font-size: 0.8rem; }}
.hdr-user b {{ color: #26282B; font-weight: 600; }}
.st-key-app_header div.stButton > button,
.st-key-mobile_header div.stButton > button {{
  min-height: 1.75rem; padding: 0.05rem 0.8rem;
  font-size: 0.76rem; font-weight: 500; color: #4B5563;
  background: #FFFFFF; border: 1px solid #C9D2DE; border-radius: 4px;
}}

/* 모바일(USER) 상단 헤더 */
.st-key-mobile_header {{
  background: #FFFFFF; border-bottom: 1px solid #D3DAE3;
  margin-bottom: 0.8rem; padding: 0.55rem 0.2rem;
}}

/* ===== 페이지 제목 ===== */
.page-title {{ font-size: 1.28rem; font-weight: 700; color: #26282B; margin: 0.15rem 0 0.05rem; letter-spacing: -0.01em; }}
.page-desc {{ font-size: 0.82rem; color: #6B7280; margin: 0 0 0.7rem; }}

/* ===== 카드 (조회 조건/콘텐츠) ===== */
div[data-testid="stVerticalBlockBorderWrapper"] {{
  background: #FFFFFF; border-radius: 5px;
}}
/* 테두리 div 의 padding 을 직접 줄여 조회 조건/카드 영역을 컴팩트하게 */
div[data-testid="stVerticalBlockBorderWrapper"] > div {{
  border-color: #D3DAE3 !important; border-radius: 5px;
  padding: 0.75rem 0.9rem !important;
}}

/* 패널 헤더 (카드 안 섹션 제목) */
.panel-head {{
  display: flex; justify-content: space-between; align-items: baseline;
  font-size: 0.88rem; font-weight: 700; color: #26282B;
  padding-bottom: 0.45rem; margin: 0 0 0.55rem;
  border-bottom: 1px solid #EAEDF1;
}}

/* 요약 카드 — ERP KPI 타일 */
.sum-card {{
  background: #FFFFFF; border: 1px solid #D3DAE3; border-left: 3px solid #1E3A6E;
  border-radius: 4px; padding: 0.6rem 0.9rem 0.55rem;
}}
.sum-value {{ font-size: 1.35rem; font-weight: 700; color: #1E3A6E; line-height: 1.2; }}
.sum-label {{ font-size: 0.72rem; color: #6B7280; margin-top: 0.15rem; letter-spacing: 0.02em; }}

/* 데이터 그리드 영역 빈 상태 — 큰 빈 박스 대신 목록/그리드 프레임으로 표시 */
.empty-state {{
  background: #FFFFFF; border: 1px solid #D3DAE3; border-radius: 5px; overflow: hidden;
}}
.empty-state .es-head {{
  height: 32px; background: #F1F4F8; border-bottom: 1px solid #D3DAE3;
  display: flex; align-items: center; padding: 0 0.85rem;
  font-size: 0.75rem; font-weight: 600; color: #7A8494; letter-spacing: 0.03em;
}}
.empty-state .es-body {{
  padding: 2.1rem 1rem; text-align: center; color: #6B7280; font-size: 0.85rem;
}}

/* ===== 폼 위젯 (Streamlit 기본 느낌 완화) ===== */
section[data-testid="stMain"] div[data-testid="stSelectbox"] label,
section[data-testid="stMain"] div[data-testid="stTextInput"] label,
section[data-testid="stMain"] div[data-testid="stDateInput"] label,
section[data-testid="stMain"] div[data-testid="stNumberInput"] label {{
  font-size: 0.72rem; font-weight: 600; color: #6B7280;
  margin-bottom: 0.15rem; padding: 0;
}}
section[data-testid="stMain"] div[data-baseweb="select"] > div,
section[data-testid="stMain"] div[data-testid="stTextInput"] input,
section[data-testid="stMain"] div[data-testid="stNumberInput"] input {{
  min-height: 2.15rem; border-radius: 4px; border-color: #C9D2DE;
  background: #FFFFFF; font-size: 0.83rem;
}}
section[data-testid="stMain"] div[data-baseweb="select"] div[data-baseweb="select"] {{ font-size: 0.83rem; }}

/* ===== 버튼 (메인 영역) ===== */
section[data-testid="stMain"] .stButton > button,
section[data-testid="stMain"] .stDownloadButton > button,
section[data-testid="stMain"] .stFormSubmitButton > button {{
  min-height: 2.15rem; font-size: 0.83rem; font-weight: 600; border-radius: 4px;
}}
section[data-testid="stMain"] .stButton > button[kind="primary"],
section[data-testid="stMain"] .stFormSubmitButton > button[kind="primary"] {{
  background: #1E3A6E; border: 1px solid #1E3A6E; color: #FFFFFF;
}}
section[data-testid="stMain"] .stButton > button[kind="primary"]:hover {{
  background: #16294F; border-color: #16294F;
}}
section[data-testid="stMain"] .stButton > button[kind="secondary"],
section[data-testid="stMain"] .stDownloadButton > button {{
  background: #FFFFFF; border: 1px solid #C9D2DE; color: #26282B;
}}

/* ===== 데이터 그리드 (읽기 전용 표) ===== */
div[data-testid="stDataFrame"] {{
  border: 1px solid #D3DAE3; border-radius: 4px;
}}
div[data-testid="stDataFrame"] [data-testid="stDataFrameResizable"] {{ border: none; }}

/* ===== 근무코드 색상 뱃지 ===== */
.duty-badge {{
  display: inline-block; min-width: 34px; text-align: center;
  padding: 2px 10px; border-radius: 11px;
  color: #fff; font-size: 0.8rem; font-weight: 600; line-height: 1.6;
}}
.duty-name {{ color: #6B7280; font-size: 0.85rem; margin-left: 6px; }}
.duty-legend {{ margin-top: 0.55rem; }}
.duty-legend .duty-badge {{ margin-right: 6px; margin-bottom: 4px; }}

/* 데이터 모드 안내 (하단, 눈에 띄지 않게) */
.data-mode-note {{ color: #9AA0A6; font-size: 0.78rem; text-align: right; margin-top: 0.6rem; }}
</style>
"""


# ---------- 페이지 설정 ----------
def setup_page() -> None:
    user = st.session_state.get("user") or {}
    role = str(user.get("role", "")).strip().upper()
    st.set_page_config(
        page_title=config.APP_NAME,
        page_icon="🏭",
        layout="wide",
        initial_sidebar_state="collapsed" if role == "USER" else "expanded",
    )
    st.markdown(_CSS, unsafe_allow_html=True)


# ---------- App Shell ----------
def app_shell(user: dict) -> str:
    """좌측 2단 메뉴(1차 아이콘 바 + 2차 메뉴 패널)와 상단 헤더를 렌더링하고
    선택된 page id 를 반환한다. (ADMIN/MANAGER PC 화면 전용)"""
    groups = nav.visible_groups(user["role"])
    valid_pages = {c["id"] for g in groups for c in g["children"]}

    page = st.session_state.get("nav_page")
    if page not in valid_pages:
        page = nav.default_page(user["role"])
        st.session_state.nav_page = page
    cur_group = nav.group_of(page, user["role"])

    with st.sidebar:
        rail_col, menu_col = st.columns([_RAIL_W, _PANEL_W])

        # 1차 아이콘 메뉴 바
        with rail_col, st.container(key="nav_rail"):
            for g in groups:
                if st.button(
                    g["label"],
                    key=f"rail_{g['id']}",
                    icon=g["icon"],
                    help=g["label"],
                    type="primary" if g["id"] == cur_group["id"] else "secondary",
                    width="stretch",
                ):
                    st.session_state.nav_page = g["children"][0]["id"]
                    st.rerun()

        # 2차 업무 메뉴 패널
        with menu_col, st.container(key="nav_menu"):
            st.markdown(
                f"<div class='nav-appname'>{config.APP_NAME}</div>",
                unsafe_allow_html=True,
            )
            st.markdown(
                f"<div class='nav-group-label'>{cur_group['label']}</div>",
                unsafe_allow_html=True,
            )
            for child in cur_group["children"]:
                if st.button(
                    child["label"],
                    key=f"menu_{child['id']}",
                    type="primary" if child["id"] == page else "secondary",
                    width="stretch",
                ):
                    st.session_state.nav_page = child["id"]
                    st.rerun()

    _header(user, nav.page_label(page))
    return page


def _header(user: dict, screen_name: str) -> None:
    """상단 헤더: 현재 화면명 | 사용자명 · 부서 · 조 · 권한 [로그아웃] (DESIGN.md §9)."""
    dept = db.dept_name(user.get("dept_code", ""))
    team = db.team_name(user.get("dept_code", ""), user.get("team_code", ""))
    who = " · ".join(x for x in (dept, team, role_label(user["role"])) if x)

    with st.container(key="app_header"):
        left, right, btn = st.columns([5, 4, 0.9], vertical_alignment="center")
        left.markdown(f"<div class='hdr-screen'>{screen_name}</div>", unsafe_allow_html=True)
        right.markdown(
            f"<div class='hdr-user'><b>{user['name']}</b> · {who}</div>",
            unsafe_allow_html=True,
        )
        with btn:
            if st.button("로그아웃", key="btn_logout", width="stretch"):
                auth.logout()
                st.rerun()


def mobile_header(user: dict) -> None:
    """USER(모바일) 상단 헤더 — App Shell 없이 앱명 + 로그아웃만 (DESIGN.md §17)."""
    with st.container(key="mobile_header"):
        c1, c2 = st.columns([3, 1.1], vertical_alignment="center")
        c1.markdown(
            f"<div class='hdr-screen' style='color:#1E3A6E'>{config.APP_NAME}</div>",
            unsafe_allow_html=True,
        )
        with c2:
            if st.button("로그아웃", key="btn_logout_m", width="stretch"):
                auth.logout()
                st.rerun()


# ---------- 화면 공통 컴포넌트 ----------
def page_header(page_id: str) -> None:
    """페이지 제목 + 한 줄 업무 설명 (메뉴 정의의 label/desc 사용)."""
    page_title(nav.page_label(page_id), nav.page_desc(page_id))


def page_title(title: str, desc: str = None) -> None:
    st.markdown(f"<div class='page-title'>{title}</div>", unsafe_allow_html=True)
    if desc:
        st.markdown(f"<div class='page-desc'>{desc}</div>", unsafe_allow_html=True)


def card():
    """카드형 컨테이너 (조회 조건/콘텐츠 영역)."""
    return st.container(border=True)


def summary_cards(items) -> None:
    """요약 카드 영역. items = [(라벨, 값), ...] 3~4개 권장 (DESIGN.md §12)."""
    cols = st.columns(len(items))
    for col, (label, value) in zip(cols, items):
        col.markdown(
            f"<div class='sum-card'><div class='sum-value'>{value}</div>"
            f"<div class='sum-label'>{label}</div></div>",
            unsafe_allow_html=True,
        )


def empty_state(message: str, head: str = "데이터 목록") -> None:
    """데이터 그리드 영역의 조회 전/결과 없음 안내.

    큰 빈 박스 대신 헤더 스트립이 있는 목록/그리드 프레임으로 표시해
    업무 시스템의 데이터 영역처럼 보이게 한다."""
    st.markdown(
        f"<div class='empty-state'><div class='es-head'>{head}</div>"
        f"<div class='es-body'>{message}</div></div>",
        unsafe_allow_html=True,
    )


def panel_head(title: str, right: str = "") -> None:
    """카드 내부 섹션 제목 (하단 구분선 있는 ERP 패널 헤더)."""
    right_html = f"<span class='duty-name'>{right}</span>" if right else ""
    st.markdown(
        f"<div class='panel-head'><span>{title}</span>{right_html}</div>",
        unsafe_allow_html=True,
    )


def action_bar(*specs):
    """하단 액션 버튼 영역 — 우측 정렬. specs 개수만큼 우측 컬럼을 반환한다."""
    n = len(specs) if specs else 1
    cols = st.columns([10 - 1.6 * n] + [1.6] * n)
    return cols[1:]


def centered(ratio=(1, 2, 1)):
    """가운데 정렬용 컬럼 반환 (로그인/모바일 화면 폭 제한)."""
    cols = st.columns(ratio)
    return cols[1]


# ---------- 근무코드/날짜 표시 ----------
def weekday_kr(d: date) -> str:
    return _WEEKDAY[d.weekday()]


def weekend_color(d: date) -> str:
    if d.weekday() == 5:   # 토
        return "#1E6FD9"
    if d.weekday() == 6:   # 일
        return "#D93025"
    return "#26282B"


def badge_html(code: str, color: str = "#9AA0A6", name: str = None) -> str:
    color = color or "#9AA0A6"
    html = f"<span class='duty-badge' style='background:{color}'>{code}</span>"
    if name:
        html += f"<span class='duty-name'>{name}</span>"
    return html


def legend_html(work_types: dict) -> str:
    """근무코드 범례 (표 하단 표시용). work_types = db.work_types_map()."""
    badges = "".join(badge_html(code, info.get("color")) for code, info in work_types.items())
    return f"<div class='duty-legend'>{badges}</div>"


def role_label(role: str) -> str:
    return _ROLE_LABEL.get(role, role)


def sample_mode_banner() -> None:
    """Supabase 미설정 시 로컬 데이터 모드 안내 (screens.md §5)."""
    if db.is_sample_mode():
        st.markdown(
            "<div class='data-mode-note'>로컬 데이터로 실행 중 — 저장 내용은 현재 세션에만 유지됩니다.</div>",
            unsafe_allow_html=True,
        )
