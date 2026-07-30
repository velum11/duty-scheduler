"""공통 UI — App Shell + 화면 공통 컴포넌트 (DESIGN.md 구현).

App Shell 구조 (DESIGN.md §2):
  단일 라이트 사이드바(236px, KPtech 메뉴트리 클론: 브랜드 헤더 + 검색 + 접이식
  그룹 트리 + 하단 사용자 카드) + 우측 메인 콘텐츠(브레드크럼 → 페이지 제목 →
  조회 조건 → 요약 카드 → 그리드).

구현 방식: st.sidebar 에 헤더/메뉴/사용자 카드를 렌더링하고 _SHELL_CSS 로 스타일링한다.
접힘 상태(st.session_state.sb_collapsed)에서는 사이드바를 66px 레일로 전환하고
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
from pathlib import Path

import streamlit as st

from modules import auth, config, db, nav

# 브라우저 파비콘 — 주간/야간(해·달) 투명 배경 PNG (assets/favicon.png)
_FAVICON = str(Path(__file__).resolve().parent.parent / "assets" / "favicon.png")

_WEEKDAY = ["월", "화", "수", "목", "금", "토", "일"]

# 권한 표시명 (CLAUDE.md §6)
_ROLE_LABEL = {"ADMIN": "관리자", "MANAGER": "조장", "USER": "조원"}

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans+KR:wght@300;400;500;600;700&display=swap');

/* ===== Claude Design 전역 토큰 (P1, ADOPTION_SPEC 정본) ===== */
:root {
  --cd-canvas:#f4f2ee; --cd-headbar:#fbfaf8; --cd-surface:#ffffff;
  --cd-ink:#1c1a17; --cd-ink-2:#4a453d; --cd-ink-3:#6b665d;
  --cd-ink-dim:#8b857c; --cd-ink-faint:#a09a90;
  --cd-line:#e6e2da; --cd-line-strong:#cfc8bd; --cd-line-section:#e0dbd2;
  --cd-accent:#c2410c; --cd-accent-hover:#a3350a; --cd-accent-text:#b4451a; --cd-accent-tint:#fdf3ec;
  --cd-sans:"IBM Plex Sans KR","Malgun Gothic","Apple SD Gothic Neo",-apple-system,
            BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;
  --cd-mono:"IBM Plex Mono","Consolas","Menlo",monospace;
}

/* ===== 기본 ===== */
/* 텍스트/위젯에만 IBM Plex 를 적용한다. Material Symbols 아이콘 폰트(stIconMaterial)는
   절대 덮지 않는다 — 넓은 [class*=" st-"] 선택자는 아이콘 span 의 폰트까지 바꿔 글리프가
   리터럴 텍스트("refresh" 등)로 깨지므로 쓰지 않는다. */
html, body, .stApp,
.stApp [data-testid="stMarkdownContainer"],
.stApp [data-testid="stMarkdownContainer"] *,
.stApp button, .stApp input, .stApp select, .stApp textarea,
.stApp [data-baseweb="select"], .stApp [data-baseweb="input"] {
  font-family: var(--cd-sans);
}
/* 아이콘 글리프 폰트 보존(위 규칙이 상속으로 새어도 재확정) */
.stApp span[data-testid="stIconMaterial"] {
  font-family: 'Material Symbols Rounded' !important;
}
html, body, .stApp { font-size: 14px; }
.stApp { background: var(--cd-canvas); color: var(--cd-ink); }
/* 모노: 사번·보고번호·시간·건수·브레드크럼(코드/숫자 계열) */
.cd-mono, .crumb { font-family: var(--cd-mono); font-feature-settings:"tnum" 1; }

/* Streamlit 기본 장식 숨김 — stToolbar 는 사이드바 펼침 버튼을 포함하므로 숨기지 않는다 */
#MainMenu, footer, .stAppDeployButton,
div[data-testid="stDecoration"],
div[data-testid="stStatusWidget"] { display: none !important; }

section[data-testid="stMain"] .block-container {
  padding: 0 1.25rem 2rem; max-width: 100%;
}
/* 메인 영역 블록 간격을 좁혀 업무 화면 정보 밀도를 높인다 */
section[data-testid="stMain"] div[data-testid="stVerticalBlock"] { gap: 0.65rem; }
section[data-testid="stMain"] div[data-testid="stHorizontalBlock"] { gap: 0.6rem; }

/* ===== 페이지 제목 (25px/600, -0.025em; 설명 13.5px) ===== */
.page-title { font-size: 25px; font-weight: 600; color: var(--cd-ink); margin: 0.1rem 0 0.1rem; letter-spacing: -0.025em; line-height: 1.2; }
.page-desc { font-size: 13.5px; color: var(--cd-ink-2); margin: 0 0 0.7rem; text-wrap: pretty; }

/* ===== 카드 (조회 조건/콘텐츠) — 흰 표면 + 헤어라인 ===== */
div[data-testid="stVerticalBlockBorderWrapper"] {
  background: var(--cd-surface); border-radius: 8px;
}
div[data-testid="stVerticalBlockBorderWrapper"] > div {
  border-color: var(--cd-line) !important; border-radius: 8px;
  padding: 0.75rem 0.9rem !important;
}

/* 패널 헤더 (카드 안 섹션 제목) */
.panel-head {
  display: flex; justify-content: space-between; align-items: baseline;
  font-size: 14px; font-weight: 600; color: var(--cd-ink);
  padding-bottom: 0.45rem; margin: 0 0 0.55rem;
  border-bottom: 1px solid var(--cd-line);
}

/* 요약 카드 — 좌측 액센트 보더 + 모노 숫자 */
.sum-card {
  background: var(--cd-surface); border: 1px solid var(--cd-line); border-left: 2px solid var(--cd-accent);
  border-radius: 6px; padding: 0.6rem 0.9rem 0.55rem;
}
.sum-value { font-family: var(--cd-mono); font-size: 1.35rem; font-weight: 600; color: var(--cd-ink); line-height: 1.2; }
.sum-label { font-size: 0.72rem; color: var(--cd-ink-2); margin-top: 0.15rem; letter-spacing: 0.02em; }

/* 데이터 그리드 영역 빈 상태 — 큰 빈 박스 대신 목록/그리드 프레임으로 표시 */
.empty-state {
  background: var(--cd-surface); border: 1px solid var(--cd-line); border-radius: 8px; overflow: hidden;
}
.empty-state .es-head {
  height: 32px; background: var(--cd-canvas); border-bottom: 1px solid var(--cd-line);
  display: flex; align-items: center; padding: 0 0.85rem;
  font-size: 0.75rem; font-weight: 600; color: var(--cd-ink-2); letter-spacing: 0.03em;
}
.empty-state .es-body {
  padding: 2.1rem 1rem; text-align: center; color: var(--cd-ink-2); font-size: 0.85rem;
}

/* ===== 폼 위젯 (Streamlit 기본 느낌 완화) ===== */
section[data-testid="stMain"] div[data-testid="stSelectbox"] label,
section[data-testid="stMain"] div[data-testid="stTextInput"] label,
section[data-testid="stMain"] div[data-testid="stDateInput"] label,
section[data-testid="stMain"] div[data-testid="stNumberInput"] label {
  font-size: 13px; font-weight: 500; color: var(--cd-ink-2);
  margin-bottom: 0.15rem; padding: 0;
}
section[data-testid="stMain"] div[data-baseweb="select"] > div,
section[data-testid="stMain"] div[data-testid="stTextInput"] input,
section[data-testid="stMain"] div[data-testid="stNumberInput"] input {
  min-height: 2.15rem; border-radius: 6px; border-color: var(--cd-line-strong);
  background: var(--cd-surface); font-size: 14.5px;
}
section[data-testid="stMain"] div[data-baseweb="select"] div[data-baseweb="select"] { font-size: 14.5px; }
/* focus 링 — 오렌지 액센트 (입력 식별 보조, WCAG 1.4.11) */
section[data-testid="stMain"] div[data-testid="stTextInput"] input:focus,
section[data-testid="stMain"] div[data-testid="stNumberInput"] input:focus {
  border-color: var(--cd-accent) !important;
  box-shadow: 0 0 0 3px rgba(194,65,12,.09) !important;
}

/* ===== 버튼 (메인 영역) — 오렌지 단일 액센트 ===== */
section[data-testid="stMain"] .stButton > button,
section[data-testid="stMain"] .stDownloadButton > button,
section[data-testid="stMain"] .stFormSubmitButton > button {
  min-height: 2.15rem; font-size: 0.85rem; font-weight: 600; border-radius: 6px;
}
section[data-testid="stMain"] .stButton > button[kind="primary"],
section[data-testid="stMain"] .stFormSubmitButton > button[kind="primary"] {
  background: var(--cd-accent); border: 1px solid var(--cd-accent); color: #FFFFFF;
}
section[data-testid="stMain"] .stButton > button[kind="primary"]:hover,
section[data-testid="stMain"] .stFormSubmitButton > button[kind="primary"]:hover {
  background: var(--cd-accent-hover); border-color: var(--cd-accent-hover);
}
section[data-testid="stMain"] .stButton > button[kind="secondary"],
section[data-testid="stMain"] .stDownloadButton > button {
  background: var(--cd-surface); border: 1px solid var(--cd-line-strong); color: var(--cd-ink);
}

/* ===== 데이터 그리드 (읽기 전용 표) ===== */
div[data-testid="stDataFrame"] {
  border: 1px solid var(--cd-line-strong); border-radius: 6px;
}
div[data-testid="stDataFrame"] [data-testid="stDataFrameResizable"] { border: none; }

/* ===== 근무코드 색상 뱃지 (색은 기준정보 DB SoT — 하드코딩 금지) ===== */
.duty-badge {
  display: inline-block; min-width: 34px; text-align: center;
  padding: 2px 10px; border-radius: 999px;
  color: #fff; font-size: 0.8rem; font-weight: 600; line-height: 1.6;
}
.duty-name { color: var(--cd-ink-2); font-size: 0.85rem; margin-left: 6px; }
.duty-legend { margin-top: 0.55rem; }
.duty-legend .duty-badge { margin-right: 6px; margin-bottom: 4px; }

/* 데이터 모드 안내 (하단, 눈에 띄지 않게) */
.data-mode-note { color: var(--cd-ink-2); font-size: 0.78rem; text-align: right; margin-top: 0.6rem; }
</style>
"""

# ADMIN/MANAGER App Shell 전용 CSS — Claude Design 다크 사이드바 + 52px 아이콘 헤더.
# app_shell 에서만 주입하므로 USER 화면/로그인 화면에는 영향이 없다.
# 사이드바 색은 아래 :root 의 --sb-* 토큰 한 블록에서만 관리한다(ADOPTION_SPEC 정본).
# 현행 트리 구조·검색·접힘(완전 숨김)·nav guard 는 그대로 — 66px 레일·모듈 클릭 접힘은 P4.
# 보조 텍스트 --sb-text-dim(#9a9284)은 #1a1917 위 5.70:1(≥4.5 실측). 브랜드 마크 오렌지 배경 W.
_SHELL_CSS = """
<style>
:root {
  /* ===== 사이드바 토큰 (Claude Design 다크 — 다크/시스템 테마는 이 토큰 블록만 오버라이드) ===== */
  --sb-w: 236px;             /* 사이드바 폭 */
  --sb-col-bg: #1a1917;      /* 사이드바 배경(다크) */
  --sb-tree-bg: #1a1917;     /* 트리 영역 배경(동일) */
  --sb-brand-bg: #1a1917;    /* 브랜드/검색 배경(동일) */
  --sb-border: #2b2925;      /* 구분선 */
  --sb-text: #a49d92;        /* 기본 글자 — 다크 위 6.54:1 */
  --sb-text-dim: #9a9284;    /* 사번 등 보조 글자 — 다크 위 5.70:1(≥4.5) */
  --sb-placeholder: #8b857c; /* 검색 placeholder 전용 (본문 텍스트 아님) */
  --sb-icon: #a49d92;        /* 캐럿 아이콘색(그룹 마커) */
  --sb-mark: #4a453d;        /* 모듈 6px 사각 마크(비활성) — 활성은 --sb-accent */
  --sb-dot: #4f4a43;         /* 리프 5px 점(비활성) — 활성은 --sb-accent */
  --sb-hover: #24221e;       /* row hover (배경보다 한 단계 밝게) */
  --sb-sel-bg: #2f2c26;      /* 선택 행 배경 */
  --sb-sel-text: #fdf3ec;    /* 선택 항목 밝은 텍스트 */
  --sb-accent: #c2410c;      /* 브랜드/액센트 오렌지 */
  --sb-focus: #c2410c;       /* 포커스 아웃라인 */
  --sb-radius: 6px;

  /* ===== 본문 토큰 (브레드크럼/헤더) ===== */
  --content-bg: #f4f2ee;     /* 본문 캔버스 */
  --headbar-bg: #fbfaf8;     /* 상단 52px 헤더 바 */
  --line: #e6e2da;           /* 헤어라인 */
  --line-strong: #cfc8bd;    /* 강조 헤어라인 */
  --ink: #1c1a17; --ink-2: #4a453d; --ink-3: #6b665d;
  --accent: #c2410c; --accent-hover: #a3350a; --accent-tint: #fdf3ec;
  --mono: "IBM Plex Mono","Consolas","Menlo",monospace;
}

/* 본문 배경 — ADMIN/MANAGER 화면 캔버스 */
.stApp { background: var(--content-bg); }

/* ===== 사이드바 골격 (다크 + 우측 구분선, 그림자 없음) ===== */
section[data-testid="stSidebar"] {
  width: var(--sb-w) !important; min-width: var(--sb-w) !important;
  max-width: var(--sb-w) !important;
  background: var(--sb-col-bg);
  border-right: 1px solid var(--sb-border); box-shadow: none;
  font-family: "IBM Plex Sans KR", "Malgun Gothic", "Apple SD Gothic Neo", -apple-system, sans-serif;
  transition: width 0.28s ease;
}
section[data-testid="stSidebar"] > div:first-child { width: var(--sb-w) !important; }
/* 기존 «/» 접기 토글 제거 — 접힘(66px 레일)/펼침은 아이콘 버튼 + st.session_state.sb_collapsed 로 제어 */
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
section[data-testid="stSidebar"] div[data-testid="stVerticalBlock"] { gap: 1px; }
section[data-testid="stSidebar"] div[data-testid="stHorizontalBlock"] {
  gap: 0.3rem !important; flex-wrap: nowrap;
}
section[data-testid="stSidebar"] div[data-testid="stColumn"] { min-width: 0 !important; }
section[data-testid="stSidebar"] div[data-testid="stMarkdownContainer"] { margin-bottom: 0 !important; }

/* ===== 사이드바 버튼 공통 (다크: 투명 배경 + 밝은 회색 글자 + 옅은 hover) ===== */
section[data-testid="stSidebar"] div.stButton > button {
  width: 100%; border: none !important; box-shadow: none !important;
  border-radius: var(--sb-radius); justify-content: flex-start; text-align: left;
  background: transparent !important; color: var(--sb-text) !important;
  transition: background-color 120ms ease;
}
/* 내부 래퍼까지 좌측 정렬 (라벨이 가운데로 몰리는 것 방지) */
section[data-testid="stSidebar"] div.stButton > button > div,
section[data-testid="stSidebar"] div.stButton > button > div > span {
  justify-content: flex-start; text-align: left;
}
section[data-testid="stSidebar"] div.stButton > button > div { flex: 1 1 auto; min-width: 0; }
section[data-testid="stSidebar"] div.stButton > button:focus,
section[data-testid="stSidebar"] div.stButton > button:focus-visible { outline: none !important; }
section[data-testid="stSidebar"] div.stButton > button:focus-visible {
  outline: 2px solid var(--sb-focus) !important; outline-offset: -2px;
}
section[data-testid="stSidebar"] div.stButton > button:hover {
  background: var(--sb-hover) !important; color: var(--sb-sel-text) !important;
}

/* ===== 사이드바 헤더 (50px: 오렌지 로고 마크 + 앱명 + 접기 버튼) ===== */
.st-key-sb_head {
  background: var(--sb-brand-bg); border-bottom: 1px solid var(--sb-border);
  height: 50px; padding: 0 8px 0 14px; display: flex; align-items: center;
}
.st-key-sb_head div[data-testid="stHorizontalBlock"] { width: 100%; }
.sb-brand { display: flex; align-items: center; gap: 9px; min-width: 0; }
.sb-logo {
  flex: 0 0 auto; width: 26px; height: 26px; border-radius: 5px;
  display: inline-flex; align-items: center; justify-content: center;
  background: var(--sb-accent); color: #FFFFFF; font-size: 14px; font-weight: 800;
}
.sb-title { display: flex; flex-direction: column; min-width: 0; }
.sb-title-ko {
  color: var(--sb-sel-text); font-size: 15px; font-weight: 700; line-height: 1.2; white-space: nowrap;
}
/* 접기 버튼 — 심플 아이콘 전용. 기본 투명·무테두리, hover 때만 옅은 배경. */
.st-key-sb_hide div.stButton button {
  width: 32px; min-height: 32px; height: 32px; padding: 0; justify-content: center;
  color: var(--sb-text) !important;
  background: transparent !important; border: 1px solid transparent !important; border-radius: 6px;
}
.st-key-sb_hide div.stButton button:hover {
  color: var(--sb-sel-text) !important; background: var(--sb-hover) !important;
}
.st-key-sb_hide div.stButton button:focus-visible {
  outline: 2px solid var(--sb-focus) !important; outline-offset: 1px;
}
.st-key-sb_hide div.stButton button [data-testid="stIconMaterial"] { font-size: 18px; }
/* 아이콘 전용 버튼(접기/로그아웃)은 내부 래퍼도 가운데 정렬 */
.st-key-sb_hide div.stButton button > div, .st-key-sb_hide div.stButton button > div > span,
.st-key-sb_user div.stButton button > div, .st-key-sb_user div.stButton button > div > span {
  justify-content: center; text-align: center;
}

/* ===== 검색 상자 (다크 위, 6px 테두리 + 돋보기 아이콘) ===== */
.st-key-sb_search {
  background: var(--sb-brand-bg); border-bottom: 1px solid var(--sb-border);
  padding: 7px 10px;
}
.st-key-sb_search div[data-testid="stTextInput"] > div { border: none !important; }
.st-key-sb_search div[data-baseweb="input"],
.st-key-sb_search div[data-baseweb="base-input"] { background: transparent !important; }
.st-key-sb_search div[data-testid="stTextInput"] input {
  height: 32px; min-height: 32px; border-radius: var(--sb-radius);
  border: 1px solid var(--sb-border) !important; background: #24221e !important;
  color: var(--sb-sel-text) !important; font-size: 12.5px; padding: 0 8px 0 28px;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='13' height='13' viewBox='0 0 24 24' fill='none' stroke='%238b857c' stroke-width='2' stroke-linecap='round'%3E%3Ccircle cx='11' cy='11' r='7'/%3E%3Cline x1='21' y1='21' x2='16.65' y2='16.65'/%3E%3C/svg%3E") !important;
  background-repeat: no-repeat !important; background-position: 8px center !important;
}
.st-key-sb_search div[data-testid="stTextInput"] input::placeholder { color: var(--sb-placeholder); }
.st-key-sb_search div[data-testid="stTextInput"] input:focus {
  border-color: var(--sb-accent) !important; box-shadow: none !important;
}

/* ===== 메뉴 트리 (DESIGN §4·§7: 폴더 아이콘 금지 — 모듈=6px 사각 마크+캐럿, 리프=5px 점) ===== */
.st-key-sb_nav { background: var(--sb-tree-bg); padding: 6px 0 10px; }
.sb-empty { padding: 12px 20px; font-size: 12px; color: var(--sb-text-dim); }

/* 최상위 항목: 그룹 헤더(sbg_) + 단독 모듈(sbs_) 공통 32px·14px */
div[class*="st-key-sbg_"] div.stButton > button,
div[class*="st-key-sbs_"] div.stButton > button {
  height: 32px; min-height: 32px; padding: 0 12px 0 12px;
  font-size: 14px; font-weight: 600; color: var(--sb-text) !important; gap: 9px;
}
/* 모듈 좌측 6px 사각 마크(활성 오렌지) — 폴더 아이콘 대체(§7) */
div[class*="st-key-sbg_"] div.stButton > button::before,
div[class*="st-key-sbs_"] div.stButton > button::before {
  content: ""; flex: 0 0 6px; width: 6px; height: 6px; border-radius: 2px;
  background: var(--sb-mark);
}
div[class*="st-key-sbg_"] div.stButton > button[kind="primary"]::before,
div[class*="st-key-sbs_"] div.stButton > button[kind="primary"]::before {
  background: var(--sb-accent);
}
/* 그룹 헤더 우측 캐럿 › — 열림 시 90° 회전(라벨 div flex:1 이 밀어낸다) */
div[class*="st-key-sbg_"] div.stButton > button::after {
  content: "\\203A"; flex: 0 0 auto; margin-left: 8px;
  font-size: 14px; line-height: 1; color: var(--sb-text-dim);
  transform: rotate(0deg); transition: transform 0.15s ease;
}
div[class*="_grpopen"] div.stButton > button::after { transform: rotate(90deg); }
/* 활성 경로 그룹(현재 페이지의 부모) = 밝은 텍스트 + 굵게 */
div[class*="st-key-sbg_"] div.stButton > button[kind="primary"],
div[class*="st-key-sbs_"] div.stButton > button[kind="primary"] {
  font-weight: 700; color: var(--sb-sel-text) !important;
}
/* 단독 모듈(대시보드) 활성 = 선택 배경까지(직접 이동형 모듈, 캐럿 없음) */
div[class*="st-key-sbs_"] div.stButton > button[kind="primary"] {
  background: var(--sb-sel-bg) !important;
}

/* 리프(페이지, sbi_) — 28px·13px, 들여쓰기 + 좌측 5px 점(§4). 가이드선 없음. */
div[class*="st-key-sbi_"] div.stButton > button {
  height: 28px; min-height: 28px; padding: 0 12px 0 18px;
  font-size: 13px; font-weight: 400; color: var(--sb-text) !important; gap: 10px;
}
div[class*="st-key-sbi_"] div.stButton > button::before {
  content: ""; flex: 0 0 5px; width: 5px; height: 5px; border-radius: 50%;
  background: var(--sb-dot);
}
/* 활성 리프(현재 페이지) = 밝은 텍스트 + 굵게 + 선택 배경 + 오렌지 점 + 좌측 오렌지 바 */
div[class*="st-key-sbi_"] div.stButton > button[kind="primary"] {
  color: var(--sb-sel-text) !important; font-weight: 700; background: var(--sb-sel-bg) !important;
  box-shadow: inset 2px 0 0 var(--sb-accent);
}
div[class*="st-key-sbi_"] div.stButton > button[kind="primary"]::before {
  background: var(--sb-accent);
}

/* ===== 하단 사용자 카드 (다크, 맨 아래 고정: 좌측 정보 + 우측 로그아웃 아이콘) ===== */
.st-key-sb_user {
  margin-top: auto; padding: 8px 10px;
  background: var(--sb-col-bg); border-top: 1px solid var(--sb-border);
}
.sb-uline { display: flex; align-items: center; gap: 9px; min-width: 0; }
.sb-ava {
  flex: 0 0 auto; width: 28px; height: 28px; border-radius: 5px;
  display: inline-flex; align-items: center; justify-content: center;
  background: var(--sb-accent); color: #FFFFFF; font-size: 12.5px; font-weight: 700;
}
.sb-uinfo { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
.sb-uname {
  color: var(--sb-sel-text); font-size: 12.5px; font-weight: 600; line-height: 1.2;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.sb-urole { font-family: var(--mono); color: var(--sb-text-dim); font-size: 11px; letter-spacing: 0.02em; line-height: 1.2; }
/* 로그아웃 — 카드 우측 작은 아이콘 전용. 기본 투명, hover 때만 옅은 배경. */
.st-key-sb_user div.stButton { display: flex; justify-content: flex-end; }
.st-key-sb_user div.stButton button {
  width: 32px; min-height: 32px; height: 32px; padding: 0; justify-content: center;
  color: var(--sb-text) !important;
  background: transparent !important; border: 1px solid transparent !important; border-radius: 6px;
}
.st-key-sb_user div.stButton button:hover {
  color: var(--sb-sel-text) !important; background: var(--sb-hover) !important;
}
.st-key-sb_user div.stButton button:focus-visible {
  outline: 2px solid var(--sb-focus) !important; outline-offset: 1px;
}
.st-key-sb_user div.stButton button [data-testid="stIconMaterial"] { font-size: 17px; }

/* ===== 본문 상단 52px 아이콘 헤더 (MODULE / SCREEN 모노 브레드크럼 + 연결 pill + 실기능 아이콘) ===== */
.st-key-app_header {
  min-height: 52px; background: var(--headbar-bg); border-bottom: 1px solid var(--line);
  margin: 0 -1.25rem 0.6rem; padding: 0 1.25rem;
  display: flex; flex-direction: column; justify-content: center;
}
.st-key-app_header div[data-testid="stHorizontalBlock"] { align-items: center; flex-wrap: nowrap; }
.st-key-app_header div[data-testid="stColumn"] { min-width: 0 !important; }
/* MODULE / SCREEN 모노 브레드크럼 (11.5px) */
.crumb { font-family: var(--mono); font-size: 11.5px; font-weight: 500; color: var(--ink-3);
  letter-spacing: 0.06em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.crumb .crumb-mod { color: var(--ink-2); }
.crumb .crumb-sep { margin: 0 7px; color: var(--line-strong); }
.crumb .crumb-scr { color: var(--ink); font-weight: 600; }
/* 연결 상태 pill (Supabase 초록 / 샘플 중립) */
.cd-conn-wrap { display: flex; justify-content: flex-end; }
.cd-conn { display: inline-flex; align-items: center; gap: 0.4rem; padding: 0.22rem 0.6rem;
  border-radius: 999px; font-size: 11.5px; font-weight: 600; white-space: nowrap;
  border: 1px solid var(--line-strong); background: var(--cd-surface, #fff); color: var(--ink-2); }
.cd-conn .dot { width: 0.5rem; height: 0.5rem; border-radius: 50%; flex: 0 0 auto; }
.cd-conn.on { background: #eef5f0; border-color: #d8e6dd; color: #2f6b45; }
.cd-conn.on .dot { background: #2f6b45; }
.cd-conn.samp { background: #f2f0ec; border-color: #e4e0d8; color: #5c564d; }
.cd-conn.samp .dot { background: #8b857c; }
/* 헤더 우측 표준 아이콘 8종 — 상시 노출. 히트영역 32px, hover #f1eee8. 활성/음영은
   색+커서+tooltip 이중부호화(활성=ink-2·pointer / 음영=ink-3 반투명·not-allowed). */
.st-key-app_header div.stButton { display: flex; justify-content: flex-end; }
div[class*="st-key-hdr_ic_"] div.stButton button {
  width: 32px; min-height: 32px; height: 32px; padding: 0; justify-content: center;
  background: transparent !important; border: 1px solid transparent !important; border-radius: 6px;
  box-shadow: none !important;
}
div[class*="st-key-hdr_ic_"] div.stButton button [data-testid="stIconMaterial"] { font-size: 18px; }
/* 활성(실기능) — ink-2, hover 옅은 배경, pointer */
div[class*="st-key-hdr_ic_on_"] div.stButton button { color: var(--ink-2) !important; cursor: pointer; }
div[class*="st-key-hdr_ic_on_"] div.stButton button:hover {
  color: var(--ink) !important; background: #f1eee8 !important;
}
div[class*="st-key-hdr_ic_on_"] div.stButton button:focus-visible {
  outline: 2px solid var(--accent) !important; outline-offset: 1px;
}
/* 음영(비활성) — ink-3 반투명 톤, not-allowed, hover 무반응(무동작) */
div[class*="st-key-hdr_ic_off_"] div.stButton button:disabled,
div[class*="st-key-hdr_ic_off_"] div.stButton button[disabled] {
  color: var(--ink-3) !important; opacity: 0.45 !important; cursor: not-allowed !important;
  background: transparent !important;
}
</style>
"""

# 66px 접힘 레일 CSS — collapsed 일 때 _SHELL_CSS 뒤에 주입(폭·글리프 스타일만 덮음).
# 브랜드 W·모듈 2글자 글리프·유저 아바타·로그아웃을 세로 스택으로, 히트영역 ≥40px(≥32 강제),
# 모든 글리프 버튼은 help(tooltip/접근성 이름) 필수(표현 계층·접근성). §2 팔레트만.
_RAIL_CSS = """
<style>
section[data-testid="stSidebar"],
section[data-testid="stSidebar"] > div:first-child {
  width: 66px !important; min-width: 66px !important; max-width: 66px !important;
}
/* 레일 상단: 브랜드 W + 펼치기 토글(세로 중앙) */
.st-key-sb_rail_head {
  background: var(--sb-brand-bg); border-bottom: 1px solid var(--sb-border);
  padding: 8px 0; display: flex; flex-direction: column; align-items: center; gap: 6px;
}
.sb-rail-logo {
  width: 30px; height: 30px; border-radius: 7px; background: var(--sb-accent);
  color: #fff; font-size: 14px; font-weight: 800;
  display: inline-flex; align-items: center; justify-content: center;
}
.st-key-sb_expand div.stButton button {
  width: 40px; height: 40px; min-height: 40px; padding: 0; justify-content: center;
  color: var(--sb-text) !important; background: transparent !important;
  border: 1px solid transparent !important; border-radius: 7px; margin: 0 auto;
}
.st-key-sb_expand div.stButton button:hover {
  color: var(--sb-sel-text) !important; background: var(--sb-hover) !important;
}
.st-key-sb_expand div.stButton button:focus-visible {
  outline: 2px solid var(--sb-focus) !important; outline-offset: 1px;
}
.st-key-sb_expand div.stButton button [data-testid="stIconMaterial"] { font-size: 18px; }
/* 레일 모듈 글리프 스택 — 2글자 글리프, 히트영역 44px, 활성=오렌지 */
.st-key-sb_rail_nav { background: var(--sb-tree-bg); padding: 8px 0; }
/* help(tooltip) 가 붙은 버튼은 button 이 div.stButton 의 직계가 아니므로(툴팁 래퍼 개입)
   자손 결합자(descendant)로 선택한다 — 직계 '>' 는 매치되지 않는다. */
div[class*="st-key-sbr_"] div.stButton button {
  width: 44px; height: 44px; min-height: 44px; margin: 3px auto; padding: 0;
  justify-content: center !important; text-align: center;
  border-radius: 8px; font-size: 12px; font-weight: 600; letter-spacing: -0.03em;
  color: var(--sb-text) !important; background: #26241f !important;
}
div[class*="st-key-sbr_"] div.stButton button > div,
div[class*="st-key-sbr_"] div.stButton button > div > span {
  justify-content: center; text-align: center;
}
div[class*="st-key-sbr_"] div.stButton button:hover {
  color: var(--sb-sel-text) !important; background: var(--sb-hover) !important;
}
div[class*="st-key-sbr_"] div.stButton button[kind="primary"] {
  background: var(--sb-accent) !important; color: #fff !important;
}
div[class*="st-key-sbr_"] div.stButton button:focus-visible {
  outline: 2px solid var(--sb-focus) !important; outline-offset: -2px;
}
/* 레일 하단: 유저 아바타 + 로그아웃(세로 중앙, 맨 아래 고정) */
section[data-testid="stSidebar"] div[data-testid="stLayoutWrapper"]:has(> .st-key-sb_rail_user) {
  margin-top: auto;
}
.st-key-sb_rail_user {
  margin-top: auto; padding: 8px 0; background: var(--sb-col-bg);
  border-top: 1px solid var(--sb-border);
  display: flex; flex-direction: column; align-items: center; gap: 6px;
}
.sb-rail-ava {
  width: 30px; height: 30px; border-radius: 50%; background: #33302a;
  color: #ddd6cb; font-size: 12.5px; font-weight: 700;
  display: inline-flex; align-items: center; justify-content: center;
}
.st-key-sb_rail_user div.stButton button {
  width: 40px; height: 40px; min-height: 40px; padding: 0; justify-content: center;
  color: var(--sb-text) !important; background: transparent !important;
  border: 1px solid transparent !important; border-radius: 7px; margin: 0 auto;
}
.st-key-sb_rail_user div.stButton button:hover {
  color: var(--sb-sel-text) !important; background: var(--sb-hover) !important;
}
.st-key-sb_rail_user div.stButton button:focus-visible {
  outline: 2px solid var(--sb-focus) !important; outline-offset: 1px;
}
.st-key-sb_rail_user div.stButton button [data-testid="stIconMaterial"] { font-size: 17px; }
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
/* 메뉴 항목 수와 무관하게 동일 폭 분배 (flex-basis 0 → grow 로 균등, nowrap 유지).
   데스크톱 폭에선 7개(아차사고 base 4 포함)도 라벨이 열 안에 들어간다. 좁은 폭(≤768px,
   하단 고정바)에서는 열 폭이 급감해 nowrap 라벨이 넘쳐 겹치므로, 모바일 미디어쿼리에서
   라벨 줄바꿈(white-space:normal + keep-all + overflow:hidden)으로 겹침을 없앤다. */
.st-key-user_nav div[data-testid="stColumn"] { flex:1 1 0 !important; width:auto !important; min-width:0 !important; }
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
  .st-key-user_nav div[data-testid="stHorizontalBlock"] { gap:.16rem !important; }
  .st-key-user_nav div.stButton > button {
    min-height:3.25rem; padding:.22rem .1rem; flex-direction:column; gap:.06rem;
    font-size:.63rem; line-height:1.02; white-space:normal; word-break:keep-all;
    text-align:center; overflow:hidden;
  }
  /* 라벨(마크다운 컨테이너·p)을 버튼 폭(100%)에 맞춰 줄바꿈시킨다 — 항목 수가 많아도
     (아차사고 base 4 포함 7개) 라벨이 좁은 열 안에서 2줄로 접혀 이웃 열로 넘치거나
     겹치지 않는다. width:100% 가 없으면 shrink-to-fit 로 한 줄을 유지해 버튼 밖으로
     삐져나오므로 반드시 100% 로 폭을 고정한다. keep-all 로 단어 중간 끊김을 막고,
     overflow:hidden 으로 최악의 경우에도 열 밖으로 새지 않는다(390px 하단 고정바
     오버플로/겹침 회귀 수정). */
  .st-key-user_nav div.stButton > button div[data-testid="stMarkdownContainer"],
  .st-key-user_nav div.stButton > button p {
    white-space:normal !important; word-break:keep-all; line-height:1.02;
    text-align:center; width:100%; max-width:100%;
  }
  .st-key-user_nav div.stButton > button [data-testid="stIconMaterial"] { font-size:19px; }
}
</style>
"""


# ---------- 페이지 설정 ----------
def setup_page() -> None:
    user = st.session_state.get("user") or {}
    role = str(user.get("role", "")).strip().upper()
    st.set_page_config(
        page_title="교대 근무표",
        page_icon=_FAVICON if Path(_FAVICON).exists() else "🏭",
        layout="wide",
        initial_sidebar_state="collapsed" if role == "USER" else "expanded",
    )
    st.markdown(_CSS, unsafe_allow_html=True)


# ---------- App Shell ----------
def app_shell(user: dict) -> str:
    """단일 라이트 사이드바(KPtech 메뉴트리 클론: 브랜드 헤더 + 검색 + 접이식 그룹
    트리 + 하단 사용자 카드)와 본문 브레드크럼을 렌더링하고 선택된 page id 를
    반환한다. (ADMIN/MANAGER PC 전용)"""
    caps = _menu_caps(user)
    groups = _shell_groups(user["role"], caps)
    valid_pages = {c["id"] for g in groups for c in g["children"]}

    page = st.session_state.get("nav_page")
    if page not in valid_pages:
        page = nav.default_page(user["role"], caps)
        st.session_state.nav_page = page

    collapsed = st.session_state.setdefault("sb_collapsed", False)

    # 이동 가드 안전장치: 가드 소유 화면이 아닌 곳에 남은 가드는 정리한다.
    guard = st.session_state.get("nav_guard")
    if guard and guard.get("owner") != page:
        st.session_state.pop("nav_guard", None)
        st.session_state.pop("nav_pending", None)

    st.markdown(_SHELL_CSS, unsafe_allow_html=True)
    # 접힘(66px 레일)은 완전 숨김이 아니라 폭·내용 전환(DESIGN §4). 사이드바는 항상
    # 렌더하고, 레일 CSS 를 _SHELL_CSS 뒤에 주입해 폭·글리프 스타일만 덮는다(표현 계층).
    if collapsed:
        st.markdown(_RAIL_CSS, unsafe_allow_html=True)

    with st.sidebar:
        if collapsed:
            _sidebar_rail(groups, page, user)
        else:
            _sidebar_brand()
            query = _sidebar_search()
            _sidebar_nav(groups, page, query)
            _sidebar_user_card(user)

    _breadcrumb_header(user, page)
    return page


def _menu_caps(user: dict) -> set:
    """메뉴 필터링용 능력 집합을 세션 사용자에서 계산한다(nav 는 DEPENDENCY-FREE —
    능력 판정은 호출부인 여기서 하고 nav 필터에 caps 로 넘긴다). app.py::_caps_for 와
    동일 계약(같은 caps 를 메뉴 렌더와 route guard 가 공유해야 노출·차단이 일치한다).

    개선조치 접근은 배정 기반 동적 판정(has_near_miss_improvement_access)이라 평가 능력과
    별개로 계산한다 — 배정된 담당자·지정 확인자(일반 USER)도 개선조치 메뉴가 노출된다."""
    caps = set()
    if auth.can_evaluate_near_miss(user):
        caps.add(nav.CAP_EVALUATE_NEAR_MISS)
    if db.has_near_miss_improvement_access(user):
        caps.add(nav.CAP_ACCESS_NEAR_MISS_IMPROVEMENT)
    return caps


def _shell_groups(role: str, caps=None) -> list:
    """기준정보의 부서/조 메뉴를 통합 조직 관리 항목 하나로 표시한다.

    caps(선택): 능력 게이트 그룹(예: 평가 관리)을 admit 하기 위해 nav.visible_groups 로
    전달한다. 미전달 시 role 기준만 적용(테스트가 role 만으로 호출하는 경로 보존)."""
    groups = []
    for group in nav.visible_groups(role, caps):
        if group["id"] != "master":
            groups.append(group)
            continue
        children = []
        for child in group["children"]:
            if child["id"] == "master_departments":
                children.append({
                    "id": "master_org",
                    "label": "조직 관리",
                    "desc": "그룹, 부서와 운영단위를 관리합니다.",
                })
            elif child["id"] != "master_teams":
                children.append(child)
        groups.append({**group, "children": children})
    return groups


def _sidebar_brand() -> None:
    """사이드바 헤더: 오렌지 로고 마크 + 앱명(교대 근무표) + 접기(66px 레일) 버튼."""
    with st.container(key="sb_head"):
        brand, toggle = st.columns([5, 1.15], vertical_alignment="center")
        brand.markdown(
            "<div class='sb-brand'><span class='sb-logo'>W</span>"
            "<span class='sb-title'><span class='sb-title-ko'>교대 근무표</span></span></div>",
            unsafe_allow_html=True,
        )
        with toggle:
            if st.button("", icon=":material/view_sidebar:", key="sb_hide",
                         type="tertiary", help="사이드바 접기(66px 레일)"):
                st.session_state.sb_collapsed = True
                st.rerun()


# ---------- 모듈 글리프(66px 레일 전용) ----------
_MODULE_GLYPH = {
    "home": "홈", "schedule": "근무", "near_miss": "아차", "master": "기준",
}


def _module_glyph(group: dict) -> str:
    """레일 모듈 2글자 글리프 — 고정 매핑, 미지정 그룹은 라벨 앞 2글자 폴백."""
    return _MODULE_GLYPH.get(group["id"], (group["label"] or "·")[:2])


def _sidebar_rail(groups: list, page: str, user: dict) -> None:
    """66px 접힘 레일(DESIGN §4) — 브랜드 W·모듈 2글자 글리프·유저 아바타·로그아웃 세로 스택.

    표현 계층만(Codex): 모든 글리프는 help(tooltip/접근성 이름) 필수. 모듈 글리프 클릭은
    라우팅·권한 로직을 재사용한다 — 단독 모듈(홈)은 request_nav 로 그 페이지 이동(가드 준수),
    다자식 모듈은 사이드바를 펼치고(sb_collapsed=False) 해당 그룹을 열어 리프를 고르게 한다.
    메뉴 숨김은 접근 제어가 아니며 route 권한 재검증은 불변이다."""
    # 브랜드 W + 펼치기 토글(세로)
    with st.container(key="sb_rail_head"):
        st.markdown("<div class='sb-rail-logo'>W</div>", unsafe_allow_html=True)
        if st.button("", icon=":material/view_sidebar:", key="sb_expand",
                     type="tertiary", help="사이드바 펼치기(234px)"):
            st.session_state.sb_collapsed = False
            st.rerun()

    # 모듈 글리프 스택
    with st.container(key="sb_rail_nav"):
        for g in groups:
            gid = g["id"]
            active = any(c["id"] == page for c in g["children"])
            if st.button(
                _module_glyph(g),
                key=f"sbr_{gid}",
                type="primary" if active else "secondary",
                help=g["label"],
                width="stretch",
            ):
                if len(g["children"]) == 1:
                    request_nav({"type": "page", "target": g["children"][0]["id"]})
                else:
                    st.session_state.sb_collapsed = False
                    st.session_state[f"sb_grp_{gid}"] = True
                    st.rerun()

    # 유저 아바타 + 로그아웃(하단 세로 스택)
    name = str(user.get("name", "")) or "?"
    with st.container(key="sb_rail_user"):
        st.markdown(
            f"<div class='sb-rail-ava' title='{escape(name)}'>{escape(name[:1])}</div>",
            unsafe_allow_html=True,
        )
        if st.button("", icon=":material/logout:", key="btn_logout",
                     type="tertiary", help="로그아웃"):
            request_nav({"type": "logout"})


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


def _sidebar_search() -> str:
    """메뉴 검색 입력창(라이트, 흰 배경). 공백 제거한 소문자 검색어를 반환한다.

    빈 문자열이면 검색 아님(전체 트리 표시). 검색 시 트리는 일치 항목만 남기고
    해당 그룹을 강제로 펼친다(_sidebar_nav 참조)."""
    with st.container(key="sb_search"):
        query = st.text_input(
            "메뉴 검색",
            key="sb_search_q",
            label_visibility="collapsed",
            placeholder="메뉴 검색",
        )
    return (query or "").strip().lower()


def _sidebar_leaf(child: dict, page: str, *, key_prefix: str) -> None:
    """트리 항목(리프 sbi_ 또는 단독 최상위 sbs_) 한 개 — 클릭 시 request_nav 이동.

    활성(현재 페이지)은 type='primary' 로 표시하고 CSS 가 파랑+굵게(배경 강조 없음)로
    렌더한다. 아이콘·불릿 없이 KPtech 텍스트 트리를 재현한다."""
    if st.button(
        child["label"],
        key=f"{key_prefix}{child['id']}",
        type="primary" if child["id"] == page else "secondary",
        width="stretch",
    ):
        request_nav({"type": "page", "target": child["id"]})


def _sidebar_nav(groups: list, page: str, query: str = "") -> None:
    """KPtech 라이트 메뉴트리 — 접이식 그룹(아코디언) + 리프 항목.

    - 단독 항목(예: 홈→대시보드): chevron 없는 최상위 항목(sbs_)으로 렌더한다.
    - 다자식 그룹: 그룹 헤더(sbg_, chevron ▸/▾) 클릭으로 ``sb_grp_{gid}`` 토글.
      현재 페이지를 포함한 그룹은 기본 펼침, **접힌 그룹은 자식을 하나도 렌더하지
      않는다**(ghost 없음). 활성 경로 그룹은 굵게(검정) 표시한다.
    - 검색어가 있으면 라벨 부분일치 항목만 남기고 해당 그룹을 강제로 펼친다.
    """
    with st.container(key="sb_nav"):
        shown = 0
        for g in groups:
            all_children = g["children"]
            vis = [c for c in all_children if query in c["label"].lower()] if query else all_children
            if not vis:
                continue

            # 단독 항목(홈 등) — chevron 없는 최상위 항목
            if len(all_children) == 1:
                shown += 1
                _sidebar_leaf(all_children[0], page, key_prefix="sbs_")
                continue

            # 접이식 그룹
            gid = g["id"]
            state_key = f"sb_grp_{gid}"
            contains_active = any(c["id"] == page for c in all_children)
            st.session_state.setdefault(state_key, contains_active)
            expanded = bool(query) or st.session_state[state_key]

            # 그룹 헤더 버튼 — 열림/닫힘을 key 접미사로 인코딩해 CSS chevron(▸/▾)을 전환한다.
            hkey = f"sbg_{gid}_grp" + ("open" if expanded else "shut")
            if st.button(
                g["label"],
                key=hkey,
                type="primary" if contains_active else "secondary",
                width="stretch",
            ):
                st.session_state[state_key] = not st.session_state[state_key]
                st.rerun()

            # 접힌 그룹은 자식을 렌더하지 않는다(ghost 방지)
            if expanded:
                shown += len(vis)
                for child in vis:
                    _sidebar_leaf(child, page, key_prefix="sbi_")

        if query and shown == 0:
            st.markdown("<div class='sb-empty'>검색 결과가 없습니다.</div>",
                        unsafe_allow_html=True)


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


def _conn_pill_html() -> str:
    """상단 헤더 우측 연결 상태 pill — 데이터 모드(persistence 연결) 전용 신호.

    Supabase 연결이면 초록, 샘플이면 중립. 저장/삭제/전역 액션과 섞지 않는다(§0.4)."""
    if db.is_sample_mode():
        return ("<div class='cd-conn-wrap'><span class='cd-conn samp' "
                "title='저장은 이 세션에만 유지됩니다'><span class='dot'></span>샘플 데이터</span></div>")
    return ("<div class='cd-conn-wrap'><span class='cd-conn on'>"
            "<span class='dot'></span>Supabase 연결</span></div>")


# 상단 52px 헤더 표준 아이콘 8종(DESIGN 부속서 A-5, 사용자 지시). 모든 M/A 화면에 상시
# 노출하고, 그 화면에서 기능 없는 아이콘은 음영(disabled)으로 둔다 — 색+커서+tooltip 이중
# 부호화. 실기능(새로고침)만 활성이며, 추가·삭제·저장·인쇄·언어·즐겨찾기·정보는 전역
# 헤더 수준에서 안전한 실행 경로가 없으므로 음영(데이터 오조작 금지 — 불명확하면 음영).
# (label, material icon, 활성 여부, tooltip)
_HEADER_ICONS = [
    ("정보", "info", False),
    ("언어", "language", False),
    ("추가", "add", False),
    ("새로고침", "refresh", True),
    ("삭제", "delete", False),
    ("인쇄", "print", False),
    ("저장", "save", False),
    ("즐겨찾기", "star", False),
]


def _breadcrumb_header(user: dict, page: str) -> None:
    """본문 상단 52px 아이콘 헤더 — 좌측 MODULE / SCREEN 모노 브레드크럼,
    우측 연결 상태 pill + 표준 아이콘 8종(실기능 활성·나머지 음영).

    사이드바는 항상 렌더된다(접힘=66px 레일, 완전 숨김 없음) — 헤더에 별도 '열기'
    버튼을 두지 않는다(펼치기는 레일 내부 토글이 소유)."""
    if page == "master_org":
        module_label, screen_label = "기준정보", "조직 관리"
    else:
        grp = nav.group_of(page, user["role"])
        module_label = grp["label"]
        screen_label = nav.page_label(page)
    crumb_html = (
        f"<span class='crumb'><span class='crumb-mod'>{escape(module_label)}</span>"
        f"<span class='crumb-sep'>/</span>"
        f"<span class='crumb-scr'>{escape(screen_label)}</span></span>"
    )
    conn_html = _conn_pill_html()

    with st.container(key="app_header"):
        cols = st.columns([5.6, 2.2] + [0.5] * len(_HEADER_ICONS),
                          vertical_alignment="center")
        cols[0].markdown(crumb_html, unsafe_allow_html=True)
        cols[1].markdown(conn_html, unsafe_allow_html=True)
        for i, (label, icon, active) in enumerate(_HEADER_ICONS):
            with cols[2 + i]:
                # 상시 노출 + 음영: 비활성 아이콘은 disabled(클릭 무동작)+음영 tooltip 로
                # '이 화면에서는 사용하지 않음'을 이중부호화한다. 활성은 실기능 tooltip.
                slot = "on" if active else "off"
                with st.container(key=f"hdr_ic_{slot}_{icon}"):
                    clicked = st.button(
                        "", icon=f":material/{icon}:", key=f"app_hdr_{icon}",
                        type="tertiary", disabled=not active,
                        help=(f"{label}" if active else f"{label} — 이 화면에서는 사용하지 않습니다"),
                    )
                    if clicked and icon == "refresh":
                        st.rerun()


def user_app_shell(user: dict) -> str:
    """USER 전용 상단 정보와 반응형 3개 메뉴를 렌더링한다."""
    caps = _menu_caps(user)
    menu = nav.user_menu(caps)
    valid_pages = {item["id"] for item in menu}
    page = st.session_state.get("nav_page")
    if page not in valid_pages:
        page = nav.default_page("USER", caps)
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


def _badge_text_color(color: str) -> str:
    """solid 배지 배경색(``#RRGGBB``) 위에서 4.5:1 이상을 보장하는 텍스트색(흰/검) 선택.

    WCAG 상대명도를 계산해 흰색(#FFFFFF)과 순수 검정(#000000) 중 대비가 큰 쪽을 고른다.
    두 후보 중 큰 값은 배경 명도 전 구간에서 ≈4.5:1 이상이라 항상 기준을 만족한다
    (views/master_work_types.py::_text_on 과 동일 로직 — 배지 저대비 보수).
    배경색 파싱에 실패하면 기존 기본 배지색(#9AA0A6)에 맞춰 흰색 대신 어두운 텍스트로
    안전 측(더 밝은 배경 가정)으로 fallback한다.
    """
    try:
        r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
    except (ValueError, IndexError, TypeError):
        return "#1F2937"

    def _lin(v: int) -> float:
        c = v / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    lum = 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)
    contrast_white = 1.05 / (lum + 0.05)
    contrast_black = (lum + 0.05) / 0.05
    return "#FFFFFF" if contrast_white >= contrast_black else "#000000"


def badge_html(code: str, color: str = "#9AA0A6", name: str = None) -> str:
    color = color or "#9AA0A6"
    text_color = _badge_text_color(color)
    html = (
        f"<span class='duty-badge' style='background:{color};color:{text_color}'>"
        f"{code}</span>"
    )
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
