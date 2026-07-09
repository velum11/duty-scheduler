"""공통 UI — App Shell + 화면 공통 컴포넌트 (DESIGN.md 구현).

App Shell 구조 (DESIGN.md §2):
  좌측 1차 아이콘 메뉴 바(네이비 60px) + 좌측 2차 업무 메뉴 패널(248px)
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

# 사이드바 폭: 1차 아이콘 바 60px + 2차 메뉴 패널 248px
_RAIL_W = 60
_PANEL_W = 248
_SIDEBAR_W = _RAIL_W + _PANEL_W

_CSS = f"""
<style>
/* ===== 기본 ===== */
html, body, .stApp {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Malgun Gothic",
               "Apple SD Gothic Neo", Arial, sans-serif;
}}
.stApp {{ background: #F7F8FA; }}

/* Streamlit 기본 장식 숨김: 헤더/툴바/푸터/사이드바 접기 */
#MainMenu, footer, .stAppDeployButton,
header[data-testid="stHeader"],
div[data-testid="stToolbar"], div[data-testid="stDecoration"],
div[data-testid="stStatusWidget"],
div[data-testid="stSidebarHeader"],
div[data-testid="stSidebarCollapseButton"],
div[data-testid="collapsedControl"] {{ display: none !important; }}

section[data-testid="stMain"] .block-container {{
  padding: 0 1.75rem 3rem; max-width: 100%;
}}

/* ===== 좌측 사이드바 = 1차 아이콘 바(네이비) + 2차 메뉴 패널 ===== */
section[data-testid="stSidebar"] {{
  width: {_SIDEBAR_W}px !important; min-width: {_SIDEBAR_W}px !important;
  max-width: {_SIDEBAR_W}px !important;
  background: linear-gradient(90deg, #071527 0, #071527 {_RAIL_W}px, #F3F5F8 {_RAIL_W}px);
  border-right: 1px solid #DDE3EA;
}}
section[data-testid="stSidebar"] > div:first-child {{ width: {_SIDEBAR_W}px !important; }}
div[data-testid="stSidebarContent"] {{ padding: 0 !important; }}
div[data-testid="stSidebarUserContent"] {{ padding: 0 !important; }}
section[data-testid="stSidebar"] div[data-testid="stHorizontalBlock"] {{ gap: 0 !important; }}
section[data-testid="stSidebar"] div[data-testid="stVerticalBlock"] {{ gap: 0.15rem; }}

/* 1차 아이콘 메뉴 바 */
.st-key-nav_rail {{ padding-top: 0.9rem; }}
.st-key-nav_rail div.stButton > button {{
  display: flex; justify-content: center; align-items: center;
  width: 42px; height: 42px; min-height: 42px; margin: 0 auto; padding: 0;
  border: none; border-radius: 8px;
  background: transparent; color: #8FA3BE;
}}
.st-key-nav_rail div.stButton > button:hover {{ background: #0F2A4A; color: #FFFFFF; }}
.st-key-nav_rail div.stButton > button[kind="primary"] {{ background: #12345A; color: #FFFFFF; }}
.st-key-nav_rail div.stButton > button [data-testid="stIconMaterial"] {{ font-size: 22px; }}

/* 2차 업무 메뉴 패널 */
.st-key-nav_menu {{ padding: 0.85rem 0.75rem 1rem 0.85rem; }}
.nav-appname {{
  font-size: 0.95rem; font-weight: 700; color: #1E3A6E;
  padding: 0.1rem 0.4rem 0.65rem; border-bottom: 1px solid #DDE3EA; margin-bottom: 0.7rem;
}}
.nav-group-label {{
  font-size: 0.7rem; font-weight: 700; color: #6B7280; letter-spacing: 0.05em;
  margin: 0.15rem 0 0.35rem 0.4rem;
}}
.st-key-nav_menu div.stButton > button {{
  width: 100%; min-height: 2.05rem; padding: 0.2rem 0.7rem;
  justify-content: flex-start; text-align: left;
  border: none; border-radius: 5px;
  font-size: 0.85rem; font-weight: 500;
}}
.st-key-nav_menu div.stButton > button[kind="secondary"] {{ background: transparent; color: #3A3F45; }}
.st-key-nav_menu div.stButton > button[kind="secondary"]:hover {{ background: #E4E9F0; color: #1E3A6E; }}
.st-key-nav_menu div.stButton > button[kind="primary"] {{ background: #1E3A6E; color: #FFFFFF; }}

/* ===== 상단 헤더 ===== */
.st-key-app_header {{
  background: #FFFFFF; border-bottom: 1px solid #DDE3EA;
  margin: 0 -1.75rem 1.15rem; padding: 0.55rem 1.75rem;
}}
.hdr-screen {{ font-size: 1rem; font-weight: 600; color: #26282B; }}
.hdr-user {{ text-align: right; color: #6B7280; font-size: 0.82rem; }}
.hdr-user b {{ color: #26282B; font-weight: 600; }}
.st-key-app_header div.stButton > button,
.st-key-mobile_header div.stButton > button {{
  min-height: 1.9rem; padding: 0.1rem 0.85rem;
  font-size: 0.78rem; color: #4B5563;
  background: #FFFFFF; border: 1px solid #C9D2DE; border-radius: 4px;
}}

/* 모바일(USER) 상단 헤더 */
.st-key-mobile_header {{
  background: #FFFFFF; border-bottom: 1px solid #DDE3EA;
  margin-bottom: 0.8rem; padding: 0.55rem 0.2rem;
}}

/* ===== 페이지 제목 ===== */
.page-title {{ font-size: 1.45rem; font-weight: 700; color: #26282B; margin: 0.2rem 0 0.05rem; }}
.page-desc {{ font-size: 0.85rem; color: #6B7280; margin: 0 0 1rem; }}

/* ===== 카드 (조회 조건/콘텐츠) ===== */
div[data-testid="stVerticalBlockBorderWrapper"] {{
  background: #FFFFFF; border-radius: 6px;
}}
div[data-testid="stVerticalBlockBorderWrapper"] > div {{
  border-color: #DDE3EA !important; border-radius: 6px;
}}

/* 요약 카드 */
.sum-card {{
  background: #FFFFFF; border: 1px solid #DDE3EA; border-radius: 6px;
  padding: 0.8rem 1rem 0.7rem;
}}
.sum-value {{ font-size: 1.45rem; font-weight: 700; color: #1E3A6E; line-height: 1.25; }}
.sum-label {{ font-size: 0.75rem; color: #6B7280; margin-top: 0.15rem; }}

/* 데이터 영역 빈 상태 안내 */
.empty-state {{
  background: #FFFFFF; border: 1px solid #DDE3EA; border-radius: 6px;
  padding: 2.8rem 1rem; text-align: center; color: #6B7280; font-size: 0.88rem;
}}

/* ===== 버튼 (메인 영역) ===== */
section[data-testid="stMain"] .stButton > button,
section[data-testid="stMain"] .stDownloadButton > button,
section[data-testid="stMain"] .stFormSubmitButton > button {{
  min-height: 2.35rem; font-size: 0.85rem; font-weight: 600; border-radius: 5px;
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
    st.set_page_config(
        page_title=config.APP_NAME,
        page_icon="🏭",
        layout="wide",
        initial_sidebar_state="expanded",
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
    cur_group = nav.group_of(page)

    with st.sidebar:
        rail_col, menu_col = st.columns([_RAIL_W, _PANEL_W])

        # 1차 아이콘 메뉴 바
        with rail_col, st.container(key="nav_rail"):
            for g in groups:
                if st.button(
                    g["icon"],
                    key=f"rail_{g['id']}",
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


def empty_state(message: str) -> None:
    """데이터 그리드 영역의 조회 전/결과 없음 안내."""
    st.markdown(f"<div class='empty-state'>{message}</div>", unsafe_allow_html=True)


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
