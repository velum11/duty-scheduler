"""공통 UI — App Shell + 화면 공통 컴포넌트 (DESIGN.md 구현).

App Shell 구조 (DESIGN.md §2):
  단일 다크 사이드바(232px: 브랜드 헤더 + 접이식 그룹 메뉴 + 하단 사용자 카드)
  + 우측 메인 콘텐츠(브레드크럼 → 페이지 제목 → 조회 조건 → 요약 카드 → 그리드).

구현 방식: st.sidebar 에 헤더/메뉴/사용자 카드를 렌더링하고 _SHELL_CSS 로 스타일링한다.
숨김 상태(st.session_state.sb_hidden)에서는 사이드바를 렌더링하지 않고
본문 브레드크럼 좌측에 열기 버튼(▤)을 표시한다. CSS 는 이 모듈에서만 관리한다.

공개 API:
- setup_page      페이지 설정 + 전역 CSS (다른 st 호출보다 먼저)
- app_shell       ADMIN/MANAGER 단일 다크 사이드바 + 본문 브레드크럼
- user_app_shell  USER 상단 정보 + 반응형 3개 메뉴
- page_header / page_title / card / summary_cards / empty_state / action_bar
- badge_html / legend_html / weekday_kr / weekend_color / role_label
"""
from datetime import date
from html import escape

import streamlit as st

from modules import auth, config, db, nav

_WEEKDAY = ["월", "화", "수", "목", "금", "토", "일"]

# 권한 표시명 (CLAUDE.md §6)
_ROLE_LABEL = {"ADMIN": "관리자", "MANAGER": "조장", "USER": "조원"}

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

# ADMIN/MANAGER App Shell 전용 CSS — 단일 다크 사이드바 + 크림 본문.
# app_shell 에서만 주입하므로 USER 화면/로그인 화면에는 영향이 없다.
# 색·크기 값은 아래 :root 디자인 토큰(--sb-* 등)에서만 관리한다.
_SHELL_CSS = """
<style>
:root {
  --sb-w: 232px;            /* 사이드바 폭 */
  --sb-bg: #1B1B1D;         /* 사이드바 배경 (다크 차콜) */
  --sb-item: #C9C7C0;       /* 메뉴 기본 글자 */
  --sb-item-dim: #8A8880;   /* 그룹 라벨·보조 글자 */
  --sb-active-bg: #2B2B2E;  /* 활성 항목 배경 */
  --sb-hover-bg: #242427;   /* hover 배경 */
  --gold: #C9A26B;          /* 액센트 (로고·활성 도트·권한 표기) */
  --content-bg: #F1EEE9;    /* 본문 배경 (크림) */
  --card: #FFFFFF;          /* 카드 배경 */
  --line: #E7E3DB;          /* 경계선 */
}

/* 본문 배경 — ADMIN/MANAGER 화면만 크림으로 (전역 CSS 의 #F7F8FA 를 덮어쓴다) */
.stApp { background: var(--content-bg); }

/* ===== 사이드바 골격 ===== */
section[data-testid="stSidebar"] {
  width: var(--sb-w) !important; min-width: var(--sb-w) !important;
  max-width: var(--sb-w) !important;
  background: var(--sb-bg); border-right: none;
  transition: width 0.28s ease;
}
section[data-testid="stSidebar"] > div:first-child { width: var(--sb-w) !important; }
/* 기존 «/» 접기 토글 제거 — 숨김/열기는 ▤ 버튼 + st.session_state.sb_hidden 으로 제어 */
div[data-testid="stSidebarHeader"] { display: none !important; }
div[data-testid="stSidebarContent"] {
  padding: 0 !important; display: flex; flex-direction: column; height: 100%;
}
/* 사용자 카드를 맨 아래 고정하기 위한 세로 flex 체인
   (UserContent > 무명 래퍼 > stVerticalBlock > stLayoutWrapper > 컨테이너 구조) */
div[data-testid="stSidebarUserContent"] {
  padding: 0 !important; flex: 1; display: flex; flex-direction: column;
}
div[data-testid="stSidebarUserContent"] > div {
  flex: 1; display: flex; flex-direction: column;
}
div[data-testid="stSidebarUserContent"] > div > div[data-testid="stVerticalBlock"] { flex: 1; }
section[data-testid="stSidebar"] div[data-testid="stLayoutWrapper"]:has(> .st-key-sb_user) {
  margin-top: auto;
}
section[data-testid="stSidebar"] div[data-testid="stVerticalBlock"] { gap: 2px; }
section[data-testid="stSidebar"] div[data-testid="stHorizontalBlock"] {
  gap: 0.3rem !important; flex-wrap: nowrap;
}
section[data-testid="stSidebar"] div[data-testid="stColumn"] { min-width: 0 !important; }
section[data-testid="stSidebar"] div[data-testid="stMarkdownContainer"] { margin-bottom: 0 !important; }

/* ===== 사이드바 버튼 공통 ===== */
section[data-testid="stSidebar"] div.stButton > button {
  width: 100%; border: none !important; box-shadow: none !important;
  border-radius: 8px; justify-content: flex-start; text-align: left;
  transition: background-color 130ms ease;
}
/* 내부 래퍼까지 좌측 정렬 (라벨이 가운데로 몰리는 것 방지) */
section[data-testid="stSidebar"] div.stButton > button > div,
section[data-testid="stSidebar"] div.stButton > button > div > span {
  justify-content: flex-start; text-align: left;
}
section[data-testid="stSidebar"] div.stButton > button > div { flex: 1 1 auto; min-width: 0; }
section[data-testid="stSidebar"] div.stButton > button:focus,
section[data-testid="stSidebar"] div.stButton > button:focus-visible { outline: none !important; }
section[data-testid="stSidebar"] div.stButton > button[kind="secondary"],
section[data-testid="stSidebar"] div.stButton > button[kind="tertiary"] {
  background: transparent !important; color: var(--sb-item) !important;
}
section[data-testid="stSidebar"] div.stButton > button:hover {
  background: var(--sb-hover-bg) !important; color: #FFFFFF !important;
}
section[data-testid="stSidebar"] div.stButton > button[kind="primary"] {
  background: var(--sb-active-bg) !important; color: #FFFFFF !important; font-weight: 600;
}

/* ===== 사이드바 헤더 (로고 마크 + 앱명 2줄 + 숨김 버튼) ===== */
.st-key-sb_head { padding: 16px 12px 10px 16px; }
.sb-brand { display: flex; align-items: center; gap: 10px; min-width: 0; }
.sb-logo {
  flex: 0 0 auto; width: 34px; height: 34px; border-radius: 9px;
  display: inline-flex; align-items: center; justify-content: center;
  background: linear-gradient(135deg, #D5B27C, #B8905A);
  color: #1B1B1D; font-size: 15px; font-weight: 800;
}
.sb-title { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.sb-title-ko {
  color: #F0EEE9; font-size: 14px; font-weight: 700; line-height: 1.1; white-space: nowrap;
}
.sb-title-en { color: var(--sb-item-dim); font-size: 9.5px; letter-spacing: 0.18em; line-height: 1; }
.st-key-sb_hide div.stButton > button {
  width: 30px; min-height: 30px; height: 30px; padding: 0; justify-content: center;
  color: var(--sb-item-dim) !important;
}
.st-key-sb_hide div.stButton > button:hover {
  color: #FFFFFF !important; background: var(--sb-hover-bg) !important;
}
.st-key-sb_hide div.stButton > button [data-testid="stIconMaterial"] { font-size: 17px; }
/* 아이콘 전용 버튼은 내부 래퍼도 가운데 정렬 */
.st-key-sb_hide div.stButton > button > div, .st-key-sb_hide div.stButton > button > div > span,
.st-key-sb_show div.stButton > button > div, .st-key-sb_show div.stButton > button > div > span,
.st-key-sb_user div.stButton > button > div, .st-key-sb_user div.stButton > button > div > span {
  justify-content: center; text-align: center;
}

/* ===== 메뉴 ===== */
.st-key-sb_nav { padding: 4px 10px 8px; }
/* 단독 항목 (예: 대시보드) — 아이콘 16px + 글자 13.5px */
div[class*="st-key-sbs_"] div.stButton > button {
  height: 38px; min-height: 38px; padding: 0 10px;
  font-size: 13.5px; font-weight: 500; gap: 9px;
}
div[class*="st-key-sbs_"] div.stButton > button [data-testid="stIconMaterial"] { font-size: 16px; }
/* 그룹 라벨 — 정적 텍스트 (클릭 대상 아님) */
.sb-group-label {
  display: block; padding: 16px 10px 6px;
  font-size: 11px; font-weight: 600; letter-spacing: 0.05em;
  color: var(--sb-item-dim); line-height: 1.2;
}
/* 하위 항목 — 좌측 4px 도트 불릿 (활성 시 골드) */
div[class*="st-key-sbi_"] div.stButton > button {
  height: 36px; min-height: 36px; padding: 0 10px 0 16px;
  font-size: 13.5px; font-weight: 500;
}
div[class*="st-key-sbi_"] div.stButton > button::before {
  content: ""; flex: 0 0 auto; width: 4px; height: 4px; border-radius: 50%;
  background: #5E5C55; margin-right: 12px;
}
div[class*="st-key-sbi_"] div.stButton > button[kind="primary"]::before { background: var(--gold); }

/* ===== 하단 사용자 카드 (맨 아래 고정) ===== */
.st-key-sb_user {
  margin: 10px 12px 12px; margin-top: auto;
  background: #242427; border-radius: 10px; padding: 9px 10px;
}
.sb-uline { display: flex; align-items: center; gap: 9px; min-width: 0; }
.sb-ava {
  flex: 0 0 auto; width: 28px; height: 28px; border-radius: 50%;
  display: inline-flex; align-items: center; justify-content: center;
  background: linear-gradient(135deg, #D5B27C, #B8905A);
  color: #1B1B1D; font-size: 12.5px; font-weight: 700;
}
.sb-uinfo { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
.sb-uname {
  color: #FFFFFF; font-size: 12.5px; font-weight: 600; line-height: 1.2;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.sb-urole { color: var(--gold); font-size: 10px; letter-spacing: 0.08em; line-height: 1.2; }
.st-key-sb_user div.stButton { display: flex; justify-content: flex-end; }
.st-key-sb_user div.stButton > button {
  width: 28px; min-height: 28px; height: 28px; padding: 0; justify-content: center;
  color: var(--sb-item-dim) !important;
}
.st-key-sb_user div.stButton > button:hover {
  color: #FFFFFF !important; background: var(--sb-hover-bg) !important;
}
.st-key-sb_user div.stButton > button [data-testid="stIconMaterial"] { font-size: 16px; }

/* ===== 본문 상단 (브레드크럼, 52px) ===== */
.st-key-app_header {
  min-height: 52px; display: flex; flex-direction: column; justify-content: center;
}
.st-key-app_header div[data-testid="stHorizontalBlock"] { align-items: center; }
.crumb { font-size: 11px; font-weight: 600; color: #9A968C; letter-spacing: 0.06em; }
.crumb .crumb-sep { margin: 0 6px; color: #C9C3B8; font-weight: 400; }
/* 숨김 상태에서 브레드크럼 좌측에 표시되는 사이드바 열기 버튼 */
.st-key-sb_show div.stButton > button {
  width: 30px; min-height: 30px; height: 30px; padding: 0; justify-content: center;
  border: none !important; background: transparent !important; box-shadow: none !important;
  color: #9A968C !important;
}
.st-key-sb_show div.stButton > button:hover { color: #4B463D !important; }
.st-key-sb_show div.stButton > button [data-testid="stIconMaterial"] { font-size: 17px; }
</style>
"""

_USER_SHELL_CSS = """
<style>
.st-key-user_app_header {
  background:#FFFFFF; border-bottom:1px solid #D3DAE3;
  margin:0 -1.25rem 0; padding:0.48rem 1.25rem;
}
.st-key-user_app_header div[data-testid="stHorizontalBlock"],
.st-key-user_nav div[data-testid="stHorizontalBlock"] { flex-wrap:nowrap; }
.st-key-user_app_header div[data-testid="stColumn"],
.st-key-user_nav div[data-testid="stColumn"] { min-width:0 !important; }
.user-header-line { display:flex; align-items:center; gap:1rem; min-width:0; }
.user-app-name { flex:0 0 auto; color:#1E3A6E; font-size:.92rem; font-weight:700; white-space:nowrap; }
.user-account { min-width:0; color:#6B7280; font-size:.78rem; line-height:1.35; overflow-wrap:anywhere; }
.user-account strong { color:#26282B; font-weight:600; }
.st-key-user_app_header div.stButton { display:flex; justify-content:flex-end; }
.st-key-user_app_header div.stButton > button {
  min-height:1.75rem; padding:.1rem .55rem; gap:.3rem; border:1px solid #C9D2DE;
  border-radius:4px; background:#FFFFFF; color:#4B5563; font-size:.74rem; font-weight:500;
  white-space:nowrap;
}
.st-key-user_app_header div.stButton > button [data-testid="stIconMaterial"] { font-size:16px; }
.st-key-user_nav {
  background:#FFFFFF; border-bottom:1px solid #D3DAE3;
  margin:0 -1.25rem .75rem; padding:.35rem 1.25rem;
}
.st-key-user_nav div[data-testid="stHorizontalBlock"] { gap:.4rem !important; }
.st-key-user_nav div[data-testid="stColumn"] { flex:1 1 0 !important; width:33.333% !important; }
.st-key-user_nav div.stButton > button {
  width:100%; min-height:2.25rem; border:1px solid transparent; border-radius:4px;
  justify-content:center; gap:.35rem; background:transparent; color:#667085;
  font-size:.8rem; font-weight:600; white-space:nowrap;
}
.st-key-user_nav div.stButton > button:hover { background:#F1F4F8; color:#1E3A6E; }
.st-key-user_nav div.stButton > button[kind="primary"] {
  border-color:#C9D5E6; background:#EAF0F8; color:#1E3A6E;
}
@media (max-width:768px) {
  section[data-testid="stMain"] .block-container {
    padding-left:.65rem; padding-right:.65rem;
    padding-bottom:calc(82px + env(safe-area-inset-bottom));
  }
  .st-key-user_app_header { margin:0 -.65rem 0; padding:.42rem .65rem; }
  .st-key-user_app_header div[data-testid="stHorizontalBlock"] { gap:.35rem !important; }
  .user-header-line { display:block; }
  .user-app-name { font-size:.86rem; }
  .user-account { margin-top:.12rem; font-size:.72rem; line-height:1.25; }
  .st-key-user_app_header div.stButton > button {
    min-height:1.9rem; padding:0 .5rem; gap:.25rem; font-size:.7rem; white-space:nowrap;
  }
  .st-key-user_nav {
    position:fixed; z-index:990; left:0; right:0; bottom:0;
    margin:0; padding:.32rem .35rem calc(.32rem + env(safe-area-inset-bottom));
    border-top:1px solid #D3DAE3; border-bottom:0;
    box-shadow:0 -2px 8px rgba(15,42,74,.08);
  }
  .st-key-user_nav div[data-testid="stHorizontalBlock"] { gap:.2rem !important; }
  .st-key-user_nav div.stButton > button {
    min-height:3.25rem; padding:.22rem .1rem; flex-direction:column; gap:.08rem;
    font-size:.68rem; line-height:1.1;
  }
  .st-key-user_nav div.stButton > button [data-testid="stIconMaterial"] { font-size:20px; }
}
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
    """단일 다크 사이드바(브랜드 헤더 + 접이식 그룹 메뉴 + 하단 사용자 카드)와
    본문 브레드크럼을 렌더링하고 선택된 page id 를 반환한다. (ADMIN/MANAGER PC 전용)"""
    groups = nav.visible_groups(user["role"])
    valid_pages = {c["id"] for g in groups for c in g["children"]}

    page = st.session_state.get("nav_page")
    if page not in valid_pages:
        page = nav.default_page(user["role"])
        st.session_state.nav_page = page

    st.session_state.setdefault("sb_hidden", False)

    # 이동 가드 안전장치: 가드 소유 화면이 아닌 곳에 남은 가드는 정리한다.
    guard = st.session_state.get("nav_guard")
    if guard and guard.get("owner") != page:
        st.session_state.pop("nav_guard", None)
        st.session_state.pop("nav_pending", None)

    st.markdown(_SHELL_CSS, unsafe_allow_html=True)

    if not st.session_state.sb_hidden:
        with st.sidebar:
            _sidebar_brand()
            _sidebar_nav(groups, page)
            _sidebar_user_card(user)

    _breadcrumb_header(user, page)
    return page


def _sidebar_brand() -> None:
    """사이드바 헤더: 골드 로고 마크 + 앱명 2줄 + 숨김(▤) 버튼."""
    with st.container(key="sb_head"):
        brand, toggle = st.columns([5, 1], vertical_alignment="center")
        brand.markdown(
            "<div class='sb-brand'><span class='sb-logo'>W</span>"
            "<span class='sb-title'><span class='sb-title-ko'>생산 근무표</span>"
            "<span class='sb-title-en'>WORKFORCE</span></span></div>",
            unsafe_allow_html=True,
        )
        with toggle:
            if st.button("", icon=":material/view_sidebar:", key="sb_hide",
                         type="tertiary", help="사이드바 숨기기"):
                st.session_state.sb_hidden = True
                st.rerun()


# ---------- 이동 가드 (미저장 변경 보호 — 기능 전용, 시각 요소 없음) ----------
# 화면이 st.session_state["nav_guard"] = {"owner": <page_id>} 를 설정해 두면,
# 사이드바 메뉴 이동·로그아웃은 즉시 수행되지 않고 nav_pending 으로 보류된다.
# 확인 대화(계속 편집 / 저장하지 않고 이동)는 가드 소유 화면이 렌더링하며,
# 이동 확정 시 apply_nav(pending) 을 호출한다.
def apply_nav(action: dict) -> None:
    """보류된 이동을 실제로 수행한다 (가드 소유 화면의 확인 후에도 사용)."""
    kind = action.get("type")
    if kind == "logout":
        auth.logout()
    elif kind == "page":
        st.session_state.nav_page = action.get("target")


def request_nav(action: dict) -> None:
    """이동 요청 공통 처리 — 가드가 있으면 보류, 없으면 즉시 수행 후 rerun.

    가드 보류 시에는 st.rerun 을 던지지 않고 현재 rerun 을 계속 진행한다.
    (여기서 중단하면 본문 위젯이 렌더되지 않아 세션 위젯 상태가 사라지고,
    조회 조건이 기본값으로 리셋되며 pending 이 덮어써질 수 있다.)
    """
    if action.get("type") == "page" and action.get("target") == st.session_state.get("nav_page"):
        return  # 현재 화면 재클릭은 이동이 아니므로 가드를 묻지 않는다
    if st.session_state.get("nav_guard"):
        st.session_state["nav_pending"] = action
        return  # 본문(가드 소유 화면)이 이 rerun 에서 확인 대화를 렌더링한다
    apply_nav(action)
    st.rerun()


def _sidebar_nav(groups: list, page: str) -> None:
    """메뉴 렌더링 — 하위 1개 그룹은 단독 항목, 나머지는 그룹 라벨 + 도트 하위 항목."""
    with st.container(key="sb_nav"):
        for g in groups:
            if len(g["children"]) == 1:
                child = g["children"][0]
                if st.button(
                    child["label"],
                    key=f"sbs_{child['id']}",
                    icon=g.get("icon"),
                    type="primary" if child["id"] == page else "secondary",
                    width="stretch",
                ):
                    request_nav({"type": "page", "target": child["id"]})
                continue

            st.markdown(
                f"<div class='sb-group-label'>{escape(g['label'])}</div>",
                unsafe_allow_html=True,
            )
            for child in g["children"]:
                if st.button(
                    child["label"],
                    key=f"sbi_{child['id']}",
                    type="primary" if child["id"] == page else "secondary",
                    width="stretch",
                ):
                    request_nav({"type": "page", "target": child["id"]})


def _sidebar_user_card(user: dict) -> None:
    """사이드바 맨 아래 고정 사용자 카드: 아바타 + 이름/사번 + 로그아웃."""
    name = str(user.get("name", "")) or "?"
    emp_no = str(user.get("emp_no", ""))
    with st.container(key="sb_user"):
        info, btn = st.columns([4.6, 1], vertical_alignment="center")
        info.markdown(
            f"<div class='sb-uline'><span class='sb-ava'>{escape(name[:1])}</span>"
            f"<span class='sb-uinfo'><span class='sb-uname'>{escape(name)}</span>"
            f"<span class='sb-urole'>{escape(emp_no)}</span></span></div>",
            unsafe_allow_html=True,
        )
        with btn:
            if st.button("", icon=":material/logout:", key="btn_logout",
                         type="tertiary", help="로그아웃"):
                request_nav({"type": "logout"})


def _breadcrumb_header(user: dict, page: str) -> None:
    """본문 상단 브레드크럼(그룹명). 사이드바 숨김 시 열기(▤) 버튼 표시."""
    cur_group = nav.group_of(page, user["role"])
    crumb_html = f"<span class='crumb'>{escape(cur_group['label'])}</span>"

    with st.container(key="app_header"):
        if st.session_state.get("sb_hidden"):
            btn, text = st.columns([0.45, 11], vertical_alignment="center")
            with btn:
                if st.button("", icon=":material/view_sidebar:", key="sb_show",
                             type="tertiary", help="사이드바 열기"):
                    st.session_state.sb_hidden = False
                    st.rerun()
            text.markdown(crumb_html, unsafe_allow_html=True)
        else:
            st.markdown(crumb_html, unsafe_allow_html=True)


def user_app_shell(user: dict) -> str:
    """USER 전용 상단 정보와 반응형 3개 메뉴를 렌더링한다."""
    menu = nav.user_menu()
    valid_pages = {item["id"] for item in menu}
    page = st.session_state.get("nav_page")
    if page not in valid_pages:
        page = nav.default_page("USER")
        st.session_state.nav_page = page

    st.markdown(_USER_SHELL_CSS, unsafe_allow_html=True)
    _user_header(user)
    with st.container(key="user_nav"):
        cols = st.columns(len(menu))
        for col, item in zip(cols, menu):
            with col:
                if st.button(
                    item["label"],
                    key=f"user_nav_{item['id']}",
                    icon=item["icon"],
                    type="primary" if item["id"] == page else "secondary",
                    width="stretch",
                ):
                    st.session_state.nav_page = item["id"]
                    st.rerun()
    return page


def _user_header(user: dict) -> None:
    dept = db.dept_name(user.get("dept_code", ""))
    team = db.team_name(user.get("dept_code", ""), user.get("team_code", ""))
    account = " · ".join(
        escape(str(value)) for value in (user.get("name", ""), dept, team) if value
    )
    with st.container(key="user_app_header"):
        info, logout = st.columns([5, 1.6], vertical_alignment="center")
        info.markdown(
            f"<div class='user-header-line'><span class='user-app-name'>{escape(config.APP_NAME)}</span>"
            f"<span class='user-account'><strong>{account}</strong></span></div>",
            unsafe_allow_html=True,
        )
        with logout:
            if st.button("LogOut", key="btn_logout_user", icon=":material/logout:", width="content"):
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
    """현재 데이터 모드를 민감정보 없이 표시한다."""
    if db.is_sample_mode():
        st.markdown(
            "<div class='data-mode-note'>로컬 데이터로 실행 중 — 저장 내용은 현재 세션에만 유지됩니다.</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            "<div class='data-mode-note'>Supabase 데이터로 실행 중</div>",
            unsafe_allow_html=True,
        )
