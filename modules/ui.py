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
- user_app_shell  USER 상단 고정 앱바(앱명/현재 화면명) + 햄버거 메뉴 시트(모바일 우선)
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
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard-dynamic-subset.css');

/* ===== Claude Design 전역 토큰 (P1, ADOPTION_SPEC 정본) ===== */
:root {
  --cd-canvas:#f4f2ee; --cd-headbar:#fbfaf8; --cd-surface:#ffffff;
  --cd-ink:#1c1a17; --cd-ink-2:#4a453d; --cd-ink-3:#6b665d;
  --cd-ink-dim:#8b857c; --cd-ink-faint:#a09a90;
  --cd-line:#e6e2da; --cd-line-strong:#cfc8bd; --cd-line-section:#e0dbd2;
  --cd-accent:#c2410c; --cd-accent-hover:#a3350a; --cd-accent-text:#b4451a; --cd-accent-tint:#fdf3ec;
  --cd-sans:"Pretendard","Pretendard Variable","Malgun Gothic","Apple SD Gothic Neo",-apple-system,
            BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;
  /* 모노 폐지(§1.2) — 토큰은 호출부 호환을 위해 남기고 값만 본문 글꼴로 맞춘다.
     자릿수 정렬은 font-variant-numeric: tabular-nums 가 담당한다. */
  --cd-mono:"Pretendard","Pretendard Variable","Malgun Gothic","Apple SD Gothic Neo",-apple-system,sans-serif;
}

/* ===== 기본 ===== */
/* 텍스트/위젯에만 IBM Plex 를 적용한다. Material Symbols 아이콘 폰트(stIconMaterial)는
   절대 덮지 않는다 — 넓은 [class*=" st-"] 선택자는 아이콘 span 의 폰트까지 바꿔 글리프가
   리터럴 텍스트("refresh" 등)로 깨지므로 쓰지 않는다. */
html, body, .stApp,
.stApp [data-testid="stMarkdownContainer"],
.stApp [data-testid="stMarkdownContainer"] *,
.stApp button, .stApp input, .stApp select, .stApp textarea,
/* st.caption 은 마크다운 컨테이너 밖(stCaptionContainer)이라 위 규칙에 안 걸려 Streamlit
   기본 Source Sans 로 렌더됐다 — 이 앱에서 유일한 비-Plex 서체였다(2026-08-14 전 화면
   검수 실측: 평가 관리 "첨부된 사진이 없습니다" 등). 화면들이 개별 우회하던 것을 여기서 닫는다. */
.stApp [data-testid="stCaptionContainer"],
.stApp [data-testid="stCaptionContainer"] *,
.stApp [data-baseweb="select"], .stApp [data-baseweb="input"] {
  font-family: var(--cd-sans);
}
/* 아이콘 글리프 폰트 보존(위 규칙이 상속으로 새어도 재확정) */
.stApp span[data-testid="stIconMaterial"] {
  font-family: 'Material Symbols Rounded' !important;
}
html, body, .stApp { font-size: 14px; }
/* 버튼 라벨을 그리는 것은 button 이 아니라 그 안의 <p> 다. Streamlit 기본값이
   0.875rem(=12.25px)이라, 화면이 button 에만 font-size 를 걸면 실제 글자는 그대로
   12.25px 로 남는다 — 대시보드·내 근무표·아차사고 등록이 각각 이 함정에 걸렸다.
   <p> 가 버튼의 값을 물려받게 해서 이 부류의 결함을 한 번에 없앤다(§1.2). */
/* 실측 체인(Streamlit 1.59.1):
     button(14px) > div > span > div[stMarkdownContainer](12.25px) > p(12.25px)
   12.25px 를 들고 있는 것은 중간 span 이 아니라 **버튼 안의 stMarkdownContainer** 다.
   그래서 p 에만 inherit 을 걸면 p 가 그 컨테이너(12.25)를 상속해 그대로 남는다 —
   컨테이너부터 상속시켜야 버튼 값(14px)이 글자까지 내려온다. 아이콘 span
   (stIconMaterial)은 다른 가지라 영향받지 않는다. */
.stApp div.stButton > button [data-testid="stMarkdownContainer"],
.stApp div.stButton > button [data-testid="stMarkdownContainer"] p,
.stApp div.stFormSubmitButton > button [data-testid="stMarkdownContainer"],
.stApp div.stFormSubmitButton > button [data-testid="stMarkdownContainer"] p,
.stApp div[data-testid="stButtonGroup"] button [data-testid="stMarkdownContainer"],
.stApp div[data-testid="stButtonGroup"] button [data-testid="stMarkdownContainer"] p {
  font-size: inherit !important; font-weight: inherit !important; }
.stApp { background: var(--cd-canvas); color: var(--cd-ink); }
/* 모노: 사번·보고번호·시간·건수·브레드크럼(코드/숫자 계열) */
.cd-mono, .crumb { font-family: var(--cd-mono); font-feature-settings:"tnum" 1; }

/* Streamlit 기본 장식 숨김 — stToolbar 는 사이드바 펼침 버튼을 포함하므로 숨기지 않는다 */
#MainMenu, footer, .stAppDeployButton,
div[data-testid="stDecoration"],
div[data-testid="stStatusWidget"] { display: none !important; }

/* 기본 헤더 밴드(header[data-testid="stHeader"]) 무력화 — **Streamlit Cloud 전용 회귀 차단**.
   이 밴드는 position:absolute; top:0; z-index:999990 로 앱 자체 52px 헤더 행(hdr_row, y≈28~60)
   위에 겹친다. 로컬은 툴바 액션이 없어 배경이 transparent 라 그냥 비쳐 보이지만, Cloud 는
   Share/편집/GitHub 버튼(stToolbarActions)을 넣으면서 **불투명 배경(#f4f2ee)** 을 칠해 앱
   헤더가 통째로 가려진다(2026-08-14 실측: 로컬 rgba(0,0,0,0) vs Cloud rgb(244,242,238)).
   그래서 로컬 검증만으로는 절대 재현되지 않는다 — 배경·그림자를 강제로 지우고 클릭도
   통과시켜 앱 헤더가 최상단을 차지하게 한다. 높이는 건드리지 않는다(레이아웃 흔들림 회피). */
header[data-testid="stHeader"] {
  background: transparent !important;
  box-shadow: none !important;
  pointer-events: none !important;
}
/* Cloud 툴바(Share·편집·GitHub)는 앱 헤더 아이콘과 같은 우상단을 차지해 시각 충돌을 만든다.
   앱 소유자는 share.streamlit.io 와 우하단 Manage app 으로 관리하므로 화면에서는 감춘다. */
header[data-testid="stHeader"] div[data-testid="stToolbarActions"] { display: none !important; }
/* 단, 네이티브 사이드바 펼침·접기는 모바일 드로어의 유일한 진입점이라 클릭을 살린다
   (위 pointer-events:none 의 예외 — ≤768px 복원 규칙과 짝을 이룬다).
   1.59 실측 testid 는 stExpandSidebarButton 이고, 구·신 버전 명칭을 함께 적어 둔다. */
[data-testid="stExpandSidebarButton"],
[data-testid="stSidebarCollapsedControl"],
div[data-testid="stSidebarHeader"] { pointer-events: auto !important; }

section[data-testid="stMain"] .block-container {
  padding: 0 1.25rem 2rem; max-width: 100%;
}
/* 메인 영역 블록 간격을 좁혀 업무 화면 정보 밀도를 높인다 */
section[data-testid="stMain"] div[data-testid="stVerticalBlock"] { gap: 0.65rem; }
section[data-testid="stMain"] div[data-testid="stHorizontalBlock"] { gap: 0.6rem; }

/* ===== 페이지 제목 (25px/600, -0.025em; 설명 13.5px) ===== */
.page-title { font-size: 24px; font-weight: 600; color: var(--cd-ink); margin: 0.1rem 0 0.1rem; letter-spacing: -0.025em; line-height: 1.2; }
.page-desc { font-size: 12px; color: var(--cd-ink-3); margin: 0 0 0.7rem; text-wrap: pretty; }

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
.sum-value { font-size: 20px; font-weight: 600; color: var(--cd-ink); line-height: 1.2; }
.sum-label { font-size: 12px; color: var(--cd-ink-3); margin-top: 0.15rem; letter-spacing: 0.02em; }

/* 데이터 그리드 영역 빈 상태 — 큰 빈 박스 대신 목록/그리드 프레임으로 표시 */
.empty-state {
  background: var(--cd-surface); border: 1px solid var(--cd-line); border-radius: 8px; overflow: hidden;
}
.empty-state .es-head {
  height: 32px; background: var(--cd-canvas); border-bottom: 1px solid var(--cd-line);
  display: flex; align-items: center; padding: 0 0.85rem;
  font-size: 12px; font-weight: 600; color: var(--cd-ink-2);
}
.empty-state .es-body {
  padding: 2.1rem 1rem; text-align: center; color: var(--cd-ink-3); font-size: 14px;
}

/* ===== 폼 위젯 (Streamlit 기본 느낌 완화) ===== */
section[data-testid="stMain"] div[data-testid="stSelectbox"] label,
section[data-testid="stMain"] div[data-testid="stTextInput"] label,
section[data-testid="stMain"] div[data-testid="stDateInput"] label,
section[data-testid="stMain"] div[data-testid="stNumberInput"] label {
  font-size: 14px; font-weight: 400; color: var(--cd-ink-2);
  margin-bottom: 0.15rem; padding: 0;
}
section[data-testid="stMain"] div[data-baseweb="select"] > div,
section[data-testid="stMain"] div[data-testid="stTextInput"] input,
section[data-testid="stMain"] div[data-testid="stNumberInput"] input {
  min-height: 2.15rem; border-radius: 6px; border-color: var(--cd-line-strong);
  background: var(--cd-surface); font-size: 14px;
}
section[data-testid="stMain"] div[data-baseweb="select"] div[data-baseweb="select"] { font-size: 14px; }
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
  min-height: 2.15rem; font-size: 14px; font-weight: 600; border-radius: 6px;
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
  color: #fff; font-size: 12px; font-weight: 600; line-height: 1.6;
}
.duty-name { color: var(--cd-ink-2); font-size: 12px; margin-left: 6px; }
.duty-legend { margin-top: 0.55rem; }
.duty-legend .duty-badge { margin-right: 6px; margin-bottom: 4px; }

/* 데이터 모드 안내 (하단, 눈에 띄지 않게) */
.data-mode-note { color: var(--cd-ink-3); font-size: 12px; text-align: right; margin-top: 0.6rem; }

/* ── 모바일(≤768px) 표 가로 스크롤 어포던스 ──
   좁은 폭에서 표는 컨테이너 안에서 가로 스크롤한다(DESIGN §5). 그런데 모바일 브라우저의
   오버레이 스크롤바는 정지 상태에서 사라져, 6~9열 중 3열만 보이는 화면에 "오른쪽에 더
   있다"는 신호가 하나도 남지 않았다(390×844 실측: 내부 오버플로 392px, 신호 0).
   그리드 컨테이너 오른쪽 끝에 24px 엣지 그림자를 덮어 "여기서 잘렸다"를 드러낸다.
   - 장식이 아니라 스크롤 가능 표시다. 표면색(#fff)으로 페이드하면 흰 셀 위에서 아무것도
     보이지 않아(실측) 신호가 되지 않으므로, 잉크(--cd-ink) 10% 로 어둡게 깔아 경계를 만든다.
   - pointer-events:none — 스와이프·셀 클릭을 가리지 않는다.
   - 테두리(1px)와 라운드는 그대로 두려고 1px 안쪽으로 넣는다.
   - AgGrid 컴포넌트 iframe 을 가진 요소 컨테이너에만 붙는다(컴포넌트 이름 기준 — emotion
     해시 선택자 아님). PC 는 이 미디어쿼리 밖이라 그리드 외관 불변. */
@media (max-width: 768px) {
  div[data-testid="stElementContainer"]:has(iframe[title*="agGrid"]) { position: relative; }
  div[data-testid="stElementContainer"]:has(iframe[title*="agGrid"])::after {
    content: ""; position: absolute; top: 1px; right: 1px; bottom: 1px; width: 24px;
    pointer-events: none; border-radius: 0 7px 7px 0;
    background: linear-gradient(to right, rgba(28, 26, 23, 0), rgba(28, 26, 23, 0.10));
  }
}
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
  --mono: "Pretendard","Pretendard Variable","Malgun Gothic","Apple SD Gothic Neo",-apple-system,sans-serif;
}

/* 본문 배경 — ADMIN/MANAGER 화면 캔버스 */
.stApp { background: var(--content-bg); }

/* ===== 사이드바 골격 (다크 + 우측 구분선, 그림자 없음) ===== */
section[data-testid="stSidebar"] {
  background: var(--sb-col-bg);
  box-shadow: none;
  font-family: "Pretendard","Malgun Gothic",-apple-system,sans-serif, -apple-system, sans-serif;
  transition: width 0.28s ease;
}
/* 폭·테두리 고정은 **펼침 상태에서만** 건다(aria-expanded="true").
   Streamlit 1.59 의 네이티브 접힘은 사이드바 section 에 emotion 규칙
   `min-width:0; max-width:0; transform:translateX(-<저장폭>px)` 을 적용해 **자리를 비우는**
   방식이다(2026-08-14 CSSOM 실측). 여기서 폭을 무조건 !important 로 못 박으면 그 max-width:0
   이 무력화돼, 접어도 flex 자리는 236px(레일은 66px) 그대로 남고 사이드바만 화면 밖으로
   밀려난다 — 본문이 계속 오른쪽에 붙박인 채 좌측에 빈 띠가 남고 네이티브 확장 버튼(»)이
   그 띠 위에서 앱 헤더와 겹쳤다(1440×900 실측: 접힘인데 main x=236·w=1204).
   접힘 상태에서는 우리 규칙을 걷어 Streamlit 계약(폭 0)이 그대로 성립하게 한다. */
section[data-testid="stSidebar"][aria-expanded="true"] {
  width: var(--sb-w) !important; min-width: var(--sb-w) !important;
  max-width: var(--sb-w) !important;
  border-right: 1px solid var(--sb-border);
}
section[data-testid="stSidebar"][aria-expanded="true"] > div:first-child { width: var(--sb-w) !important; }
/* 기존 «/» 접기 토글 제거 — 접힘(66px 레일)/펼침은 아이콘 버튼 + st.session_state.sb_collapsed 로 제어 */
div[data-testid="stSidebarHeader"] { display: none !important; }
div[data-testid="stSidebarContent"] {
  /* 상단 여백(U1): 브랜드 블록이 화면 최상단 y=0 에 붙지 않도록 숨 쉴 공간을 준다. 사이드바
     배경(--sb-col-bg)과 브랜드 배경(--sb-brand-bg)이 동일(#1a1917)이라 이 여백은 이음매 없이
     채워진다. 펼침/접힘 레일 모두 같은 컨테이너라 함께 보정된다. */
  padding: 16px 0 0 0 !important; display: flex; flex-direction: column; height: 100%;
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
  background: var(--sb-accent); color: #FFFFFF; font-size: 14px; font-weight: 600;
}
.sb-title { display: flex; flex-direction: column; min-width: 0; }
.sb-title-ko {
  color: var(--sb-sel-text); font-size: 14px; font-weight: 600; line-height: 1.2; white-space: nowrap;
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
.st-key-sb_hide div.stButton button [data-testid="stIconMaterial"] { font-size: 20px; }
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
  color: var(--sb-sel-text) !important; font-size: 12px; padding: 0 8px 0 28px;
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
  font-weight: 600; color: var(--sb-sel-text) !important;
}
/* 단독 모듈(대시보드) 활성 = 선택 배경까지(직접 이동형 모듈, 캐럿 없음) */
div[class*="st-key-sbs_"] div.stButton > button[kind="primary"] {
  background: var(--sb-sel-bg) !important;
}

/* 리프(페이지, sbi_) — 28px·13px, 들여쓰기 + 좌측 5px 점(§4). 가이드선 없음. */
div[class*="st-key-sbi_"] div.stButton > button {
  height: 28px; min-height: 28px; padding: 0 12px 0 18px;
  font-size: 14px; font-weight: 400; color: var(--sb-text) !important; gap: 10px;
}
div[class*="st-key-sbi_"] div.stButton > button::before {
  content: ""; flex: 0 0 5px; width: 5px; height: 5px; border-radius: 50%;
  background: var(--sb-dot);
}
/* 활성 리프(현재 페이지) = 밝은 텍스트 + 굵게 + 선택 배경 + 오렌지 점 + 좌측 오렌지 바 */
div[class*="st-key-sbi_"] div.stButton > button[kind="primary"] {
  color: var(--sb-sel-text) !important; font-weight: 600; background: var(--sb-sel-bg) !important;
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
  background: var(--sb-accent); color: #FFFFFF; font-size: 12px; font-weight: 600;
}
.sb-uinfo { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
.sb-uname {
  color: var(--sb-sel-text); font-size: 12px; font-weight: 600; line-height: 1.2;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.sb-urole { color: var(--sb-text-dim); font-size: 12px; letter-spacing: 0.02em; line-height: 1.2; }
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
.st-key-sb_user div.stButton button [data-testid="stIconMaterial"] { font-size: 20px; }

/* ===== 본문 상단 52px 아이콘 헤더 (MODULE / SCREEN 모노 브레드크럼 + 연결 pill + 실기능 아이콘) ===== */
.st-key-app_header {
  min-height: 52px; background: var(--headbar-bg); border-bottom: 1px solid var(--line);
  margin: 0 -1.25rem 0.6rem; padding: 0 1.25rem;
  display: flex; flex-direction: column; justify-content: center;
}
.st-key-app_header div[data-testid="stHorizontalBlock"] { align-items: center; flex-wrap: nowrap; }
.st-key-app_header div[data-testid="stColumn"] { min-width: 0 !important; }
/* MODULE / SCREEN 모노 브레드크럼 (11.5px) */
.crumb { font-size: 12px; font-weight: 400; color: var(--ink-3);
  letter-spacing: 0.06em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.crumb .crumb-mod { color: var(--ink-2); }
/* 구분자에 선 토큰(--line-strong #cfc8bd)을 쓰면 텍스트 대비 1.59:1 로 §5 하한 미달.
   색 선언을 두지 않고 부모 .crumb 의 --ink-3(캔버스 위 5.10:1)를 상속한다. */
.crumb .crumb-sep { margin: 0 7px; }
.crumb .crumb-scr { color: var(--ink); font-weight: 600; }
/* 헤더 우측 날짜/범위 스탬프 (화면이 채우는 슬롯 — 비면 폭 0) */
.hdr-stamp { font-size: 12px; font-weight: 400; color: var(--ink-2);
  letter-spacing: 0.02em; white-space: nowrap; }
/* 연결 상태 pill (Supabase 초록 / 샘플 중립) */
.cd-conn-wrap { display: flex; justify-content: flex-end; }
.cd-conn { display: inline-flex; align-items: center; gap: 0.4rem; padding: 0.22rem 0.6rem;
  border-radius: 999px; font-size: 12px; font-weight: 600; white-space: nowrap;
  border: 1px solid var(--line-strong); background: var(--cd-surface, #fff); color: var(--ink-2); }
.cd-conn .dot { width: 0.5rem; height: 0.5rem; border-radius: 50%; flex: 0 0 auto; }
.cd-conn.on { background: #eef5f0; border-color: #d8e6dd; color: #2f6b45; }
.cd-conn.on .dot { background: #2f6b45; }
.cd-conn.samp { background: #f2f0ec; border-color: #e4e0d8; color: #5c564d; }
.cd-conn.samp .dot { background: #8b857c; }
/* 헤더 우측 표준 아이콘 8종 — 상시 노출. 히트영역 32px, hover #f1eee8. 활성/음영은
   색+커서+tooltip 이중부호화(활성=ink-2·pointer / 음영=ink-3 반투명·not-allowed). */
.st-key-app_header div.stButton { display: flex; justify-content: flex-end; }
/* 한 줄 flex: 브레드크럼 신축 + 스탬프·pill·아이콘 내용폭 고정(좁은 폭 겹침 방지). 아이콘 슬롯 2px. */
.st-key-hdr_row { align-items: center; flex-wrap: nowrap !important; gap: 2px !important; }
/* 자식 지정은 nth-child 순번이 아니라 **:has(키)** 로 한다 — ① 순번 의존은 스탬프 슬롯이
   비는 화면에서 순번이 밀려 헤더가 무너지고(2026-08-11 편성 실측 회귀), ② 이 Streamlit
   버전은 st-key 클래스를 직계 래퍼가 아니라 내부 블록에 달아 키 직접 지정도 안 먹는다
   (직계 래퍼 실측: 클래스 없음·전폭 1220px). 브레드크럼(항상 첫 자식)만 위치 기반. */
.st-key-hdr_row > div:first-child { flex: 1 1 auto !important; min-width: 0 !important; overflow: hidden; }
.st-key-hdr_row > div:has(.st-key-hdr_stamp) { flex: 0 0 auto !important; width: auto !important; }
.st-key-hdr_stamp:not(:empty) { margin-right: 14px; }
.st-key-hdr_row > div:has(.st-key-hdr_conn) { flex: 0 0 auto !important; width: auto !important; margin-right: 12px; }  /* 연결 pill */
/* 8종 아이콘 래퍼. 내용폭 32px 고정 → 2px 연속 배치. */
.st-key-hdr_row > div:has([class*="st-key-hdr_ic_"]) { flex: 0 0 32px !important; width: 32px !important; min-width: 32px !important; }
div[class*="st-key-hdr_ic_"] div.stButton { justify-content: center; }
div[class*="st-key-hdr_ic_"] div.stButton button {
  width: 32px; min-height: 32px; height: 32px; padding: 0; justify-content: center;
  background: transparent !important; border: 1px solid transparent !important; border-radius: 6px;
  box-shadow: none !important;
}
div[class*="st-key-hdr_ic_"] div.stButton button [data-testid="stIconMaterial"] { font-size: 20px; }
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

/* ── 모바일(≤768px): PC 전용 사이드바 셸 보정 ──
   좁은 화면에서 사이드바는 initial_sidebar_state="auto" 로 화면 밖으로 자동 접히고(본문 전폭),
   좌상단 «»(stSidebarCollapsedControl)로 오버레이 드로어처럼 연다. 단 PC 에선 숨기는
   네이티브 접기(X, stSidebarHeader)를 모바일에서만 복원해, 연 드로어를 다시 닫을 수 있게 한다
   (없으면 한 번 열면 본문을 덮은 채 못 닫는 회귀). 데스크톱 동작은 미디어쿼리 밖이라 불변. */
@media (max-width: 768px) {
  div[data-testid="stSidebarHeader"] {
    display: flex !important; justify-content: flex-end;
    padding: 0.25rem 0.4rem 0 !important;
  }
  section[data-testid="stSidebar"] { box-shadow: 2px 0 16px rgba(15, 42, 74, 0.28); }

  /* 헤더를 **정확히 두 줄**로 접는다 — 1행: 메타(브레드크럼·날짜 스탬프·연결 pill),
     2행: 아이콘 8종 우측 정렬.
     390px 실측(2026-08-14): 아이콘 8개는 32px 슬롯 + 2px 간격으로 270px 를 쓰는데,
     날짜 스탬프(157px)와 연결 pill(85px)이 앞에 붙는 대시보드에서는 한 줄 합이 본문
     폭(350px)을 넘어 새로고침 이후 5개가 뷰포트 밖으로 잘리고 페이지 가로 스크롤도
     없어 **도달 자체가 불가능**했다(§0-3 아이콘 툴바는 헤더 안에만 — 본문으로 뺄 수 없다).
     기능을 숨기지 않고 §5 반응형(wrap)으로 해결한다: 아이콘 그룹만 다음 줄로 내려
     8개 전부 350px 안에 들어온다(270 ≤ 350).
     **배치는 자식 구성과 무관하게 결정적이어야 한다**: order 를 지정받지 못한 자식이
     생기면 초기값 0 이라 메타보다 앞(1행 맨 앞)으로 끼어들기 때문에, 순번·개별 키 열거가
     아니라 **모든 직계 자식 기본 order:1 + 아이콘만 order:3** 으로 분류한다. 앞으로 헤더에
     자식이 추가돼도 그 자식은 메타 줄 끝에 붙을 뿐 줄 구조가 깨지지 않는다.
     헤더 밴드는 min-height 52px 라 두 줄에서 자연히 늘어난다. PC 는 이 블록 밖이라 불변. */
  .st-key-hdr_row { flex-wrap: wrap !important; row-gap: 2px; justify-content: flex-end; }
  /* ① 기본값: 모든 직계 자식은 메타 줄 */
  .st-key-hdr_row > div { order: 1; }
  /* ② 100% 폭 브레이크 — 여기서 반드시 줄이 바뀐다(높이 0) */
  .st-key-hdr_row::before { content: ""; order: 2; flex: 0 0 100%; height: 0; }
  /* ③ 아이콘 슬롯만 브레이크 뒤로 */
  .st-key-hdr_row > div:has([class*="st-key-hdr_ic_"]) { order: 3; }
  /* 브레드크럼이 메타 줄의 유일한 신축 항목(flex-basis 0)이다. 줄바꿈 계산에서 폭 0 으로
     잡히므로 스탬프·pill 이 **항상 같은 줄에 남고**(basis auto 면 브레드크럼이 남는 폭을 다
     먹어 pill 이 3행으로 떨어졌다 — 390 실측 91px), 남는 폭만 차지하다 좁아지면 말줄임된다.
     좌측 26px 들여쓰기는 접힌 상태에서 좌상단에 뜨는 네이티브 사이드바 펼침 버튼
     (»: x 16~41 실측) 자리를 비워 브레드크럼 첫 글자와 겹치지 않게 한다. */
  .st-key-hdr_row > div:first-child {
    flex: 1 1 0 !important; min-width: 0 !important; padding-left: 26px;
  }
  /* 줄어든 브레드크럼은 글자 중간 하드 클립이 아니라 말줄임으로 끝나야 한다 — .crumb 은
     인라인 span 이라 overflow/text-overflow 가 먹지 않는다(390 실측: "홈 / 대시"에서 잘림).
     블록으로 바꿔 컨테이너 폭에 묶으면 기존 ellipsis 선언이 그대로 동작한다.
     전체 경로는 바로 아래 25px 페이지 제목이 항상 온전히 보여 준다. */
  .st-key-hdr_row > div:first-child .crumb { display: block; max-width: 100%; }
  /* 스탬프의 PC 용 오른쪽 여백(14px)은 좁은 폭에서 메타 줄을 그만큼 잡아먹으므로 0 으로 둔다. */
  .st-key-hdr_stamp:not(:empty) { margin-right: 0; }
}
</style>
"""

# 66px 접힘 레일 CSS — collapsed 일 때 _SHELL_CSS 뒤에 주입(폭·글리프 스타일만 덮음).
# 브랜드 W·모듈 2글자 글리프·유저 아바타·로그아웃을 세로 스택으로, 히트영역 ≥40px(≥32 강제),
# 모든 글리프 버튼은 help(tooltip/접근성 이름) 필수(표현 계층·접근성). §2 팔레트만.
_RAIL_CSS = """
<style>
/* 레일 폭도 펼침 상태에서만 고정한다 — 네이티브 접힘(aria-expanded="false")에서는
   폭 규칙을 걷어야 Streamlit 의 max-width:0 이 살아난다(_SHELL_CSS 골격 주석 참조). */
section[data-testid="stSidebar"][aria-expanded="true"],
section[data-testid="stSidebar"][aria-expanded="true"] > div:first-child {
  width: 66px !important; min-width: 66px !important; max-width: 66px !important;
}
/* 레일 상단: 브랜드 W + 펼치기 토글(세로 중앙) */
.st-key-sb_rail_head {
  background: var(--sb-brand-bg); border-bottom: 1px solid var(--sb-border);
  padding: 8px 0; display: flex; flex-direction: column; align-items: center; gap: 6px;
}
.sb-rail-logo {
  width: 30px; height: 30px; border-radius: 7px; background: var(--sb-accent);
  color: #fff; font-size: 14px; font-weight: 600;
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
.st-key-sb_expand div.stButton button [data-testid="stIconMaterial"] { font-size: 20px; }
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
  color: #ddd6cb; font-size: 12px; font-weight: 600;
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
.st-key-sb_rail_user div.stButton button [data-testid="stIconMaterial"] { font-size: 20px; }
</style>
"""

# USER 전용 셸 CSS — 상단 고정 앱바(52px, ADMIN 헤더와 같은 높이) + 햄버거 메뉴 시트(st.popover).
# 2026-08-13 사용자 지시로 하단 고정 탭바를 제거했다: USER 메뉴는 능력에 따라 7~9개까지
# 늘어나 좁은 폭(≤490px)에서 열당 52px 로 쪼그라들며 라벨이 잘렸고, 마지막 두 항목이
# Streamlit Cloud 우하단 'Manage app' 오버레이(≈88×36 + 여백)와 겹쳤다. 내비게이션은
# 상단 앱바의 햄버거 시트 하나로 통일한다(모바일·데스크톱 동일 구조 — 진입점 이중화 없음).
# 색은 전역 --cd-* 토큰(DESIGN §2)만 쓴다(구 파랑 계열 #1E3A6E/#D3DAE3 등 팔레트 밖 색 제거).
_USER_SHELL_CSS = """
<style>
/* CSS 주입용 markdown(스타일 태그만 든 요소)은 화면에 보이지 않으면서도 18px 를 차지해
   앱바를 아래로 민다. USER 셸에서만, '자식이 style 하나뿐인' 마크다운 컨테이너에 한정해
   숨긴다 — display:none 안의 <style> 규칙은 그대로 적용된다(내용 있는 마크다운 불변). */
div[data-testid="stElementContainer"]:has(div[data-testid="stMarkdownContainer"] > style:only-child) {
  display:none !important;
}
/* ===== 상단 고정 앱바 — 스크롤해도 메뉴에 항상 닿는다 =====
   sticky 는 가로 블록 자신이 아니라 **부모 레이아웃 래퍼**에 건다: 래퍼는 자식(앱바)과
   높이가 같아 앱바에 직접 걸면 미끄러질 여지가 없어 그냥 함께 스크롤된다(실측 회귀).
   래퍼의 컨테이닝 블록은 본문 전체 세로 블록이라 정상적으로 상단에 고정된다.
   자식 지정은 순번이 아니라 :has(> 키) 로 한다(ADMIN 사이드바와 동일 패턴). */
div[data-testid="stLayoutWrapper"]:has(> .st-key-user_topbar) {
  position:sticky; top:0; z-index:900;
}
.st-key-user_topbar {
  background:var(--cd-headbar); border-bottom:1px solid var(--cd-line);
  margin:0 -1.25rem .55rem; padding:.25rem 1.25rem;
  min-height:52px; align-items:center;
  flex-wrap:nowrap !important; gap:.5rem !important;
}
/* Streamlit 마크다운 블록의 하단 음수 마진(-14px)은 앱바에서 상자 높이를 23px→9px 로
   줄여 텍스트를 잘라먹는다(실측). 앱바 안에서만 0 으로 되돌린다. */
.st-key-user_topbar div[data-testid="stMarkdownContainer"] { margin-bottom:0 !important; }
.st-key-user_title { min-width:0; }
.ub-title {
  display:flex; align-items:baseline; gap:.4rem; min-width:0; white-space:nowrap;
}
.ub-app { flex:0 0 auto; font-size:12px; font-weight:600; color:var(--cd-ink-3); letter-spacing:.01em; }
/* 위와 같은 사유 — 선 토큰이 아니라 ink-3 를 쓴다(§5 대비 하한). */
.ub-sep { flex:0 0 auto; font-size:12px; color:var(--cd-ink-3); }
.ub-screen {
  min-width:0; font-size:14px; font-weight:600; color:var(--cd-ink); letter-spacing:-.01em;
  overflow:hidden; text-overflow:ellipsis;
}
.ub-acct { display:flex; align-items:baseline; gap:.35rem; white-space:nowrap; }
.ub-acct-name { font-size:12px; font-weight:600; color:var(--cd-ink-2); }
.ub-acct-meta { font-size:12px; color:var(--cd-ink-3); }
.ub-acct-meta:not(:empty)::before { content:"·"; margin-right:.35rem; color:var(--cd-line-strong); }
/* 햄버거(메뉴 트리거) — 터치 히트영역 44px(§4 USER 터치 기준), 좌측 고정 */
.st-key-user_menu_pop div[data-testid="stPopover"] { display:flex; }
.st-key-user_menu_pop button {
  min-height:44px; height:44px; padding:0 .6rem; gap:.35rem;
  border:1px solid var(--cd-line-strong) !important; border-radius:6px;
  background:var(--cd-surface); color:var(--cd-ink-2);
  font-size:12px; font-weight:600; white-space:nowrap; box-shadow:none !important;
}
.st-key-user_menu_pop button:hover { background:#f1eee8; color:var(--cd-ink); }
.st-key-user_menu_pop button:focus-visible { outline:2px solid var(--cd-accent); outline-offset:1px; }
.st-key-user_menu_pop button [data-testid="stIconMaterial"] { font-size:20px; }

/* ===== 햄버거 메뉴 시트(popover 본문) — 전체 메뉴 + 로그아웃 =====
   popover 본문은 portal 로 body 직속에 렌더되어 stMain 스코프 CSS 가 닿지 않는다.
   시트 안 마커(.um-sheet)로 한정해, 다른 화면의 popover(기준정보 아이콘 툴바)에는
   영향이 없게 한다. */
div[data-testid="stPopoverBody"]:has(.um-sheet) {
  min-width:264px; max-width:min(86vw, 320px); padding:.4rem .4rem .45rem !important;
  /* 낮은 뷰포트(가로 모드 등)에서도 시트가 화면 밖으로 넘치지 않게 자체 스크롤 */
  max-height:calc(100vh - 64px); overflow-y:auto;
}
/* 항목 사이는 2px — 시트가 세로로 늘어져 스크롤되지 않게 한다(정보 밀도) */
div[data-testid="stPopoverBody"]:has(.um-sheet) div[data-testid="stVerticalBlock"] { gap:2px !important; }
div[data-testid="stPopoverBody"]:has(.um-sheet) div[data-testid="stMarkdownContainer"] { margin-bottom:0 !important; }
.um-acct {
  display:flex; flex-direction:column; gap:1px;
  padding:.15rem .55rem .45rem; margin-bottom:.35rem;
  border-bottom:1px solid var(--cd-line);
}
.um-acct-name { font-size:14px; font-weight:600; color:var(--cd-ink); }
.um-acct-meta { font-size:12px; color:var(--cd-ink-3); }
/* 메뉴 항목 — 44px 터치 타깃, 좌측 정렬 아이콘 + 라벨. 현재 화면은 오렌지 틴트 + 좌측 바. */
div[class*="st-key-user_nav_"] div.stButton > button {
  width:100%; min-height:44px; justify-content:flex-start; text-align:left; gap:.55rem;
  padding:0 .55rem; border:1px solid transparent !important; border-radius:6px;
  background:transparent; color:var(--cd-ink-2); font-size:14px; font-weight:400;
  white-space:nowrap; box-shadow:none !important;
}
div[class*="st-key-user_nav_"] div.stButton > button > div { flex:1 1 auto; min-width:0; justify-content:flex-start; }
div[class*="st-key-user_nav_"] div.stButton > button:hover { background:#f1eee8; color:var(--cd-ink); }
div[class*="st-key-user_nav_"] div.stButton > button:focus-visible {
  outline:2px solid var(--cd-accent); outline-offset:-2px;
}
div[class*="st-key-user_nav_"] div.stButton > button[kind="primary"] {
  background:var(--cd-accent-tint); color:var(--cd-accent-text); font-weight:600;
  box-shadow:inset 2px 0 0 var(--cd-accent) !important;
}
div[class*="st-key-user_nav_"] div.stButton > button [data-testid="stIconMaterial"] { font-size:20px; }
/* 로그아웃 — 시트 맨 아래, 헤어라인으로 구분(파괴적 액션 아님: 중립 표면 버튼) */
.st-key-btn_logout_user { border-top:1px solid var(--cd-line); margin-top:.35rem; padding-top:.4rem; }
.st-key-btn_logout_user div.stButton > button {
  width:100%; min-height:40px; justify-content:flex-start; gap:.55rem; padding:0 .55rem;
  border:1px solid var(--cd-line-strong) !important; border-radius:6px;
  background:var(--cd-surface); color:var(--cd-ink-2); font-size:14px; font-weight:600;
}
.st-key-btn_logout_user div.stButton > button:hover { background:#f1eee8; color:var(--cd-ink); }
.st-key-btn_logout_user div.stButton > button:focus-visible {
  outline:2px solid var(--cd-accent); outline-offset:-2px;
}
.st-key-btn_logout_user div.stButton > button [data-testid="stIconMaterial"] { font-size:20px; }

/* ===== 모바일(≤768px) — 본문 좌우 여백만 좁힌다(하단 고정바 없음 → 하단 패딩 불요) ===== */
@media (max-width:768px) {
  section[data-testid="stMain"] .block-container { padding-left:.65rem; padding-right:.65rem; }
  .st-key-user_topbar { margin:0 -.65rem .5rem; padding:.25rem .65rem; gap:.4rem !important; }
  /* 좁은 폭에서는 계정 상세(부서·조)를 감추고 이름만 남긴다 — 전체 계정은 메뉴 시트가 보여준다 */
  .ub-acct-meta { display:none; }
  .ub-app { font-size:12px; }
  .ub-screen { font-size:14px; }
}
</style>
"""


# ---------- 페이지 설정 ----------
def setup_page() -> None:
    user = st.session_state.get("user") or {}
    role = str(user.get("role", "")).strip().upper()
    st.set_page_config(
        page_title="WorkOps",
        page_icon=_FAVICON if Path(_FAVICON).exists() else "🟧",
        layout="wide",
        # USER=상단/하단 nav 셸(사이드바 미사용) → collapsed. ADMIN/MANAGER=사이드바 셸이지만
        # "auto" 로 두어 좁은 화면(모바일)에서는 Streamlit 이 자동으로 접어 본문을 가리지 않게 한다
        # (PC 폭에서는 auto=펼침이라 기존 데스크톱 동작 유지). 모바일 접기/펼치기 컨트롤은
        # _SHELL_CSS 의 @media 블록에서 복원한다.
        initial_sidebar_state="collapsed" if role == "USER" else "auto",
    )
    st.markdown(_CSS, unsafe_allow_html=True)
    _inject_component_font()


# 표(AG Grid)는 컴포넌트 iframe 안에서 그려진다. iframe 은 부모 문서의 웹폰트를
# 상속받지 못하고 font-family 선언만 남긴 채 조용히 폴백한다(2026-08-19 실측:
# 같은 문자열이 부모 115.93px / 표 123.76px). Streamlit theme.fontFaces 도,
# st_aggrid custom_css 의 @font-face 도 iframe 에 닿지 않는 것을 확인했다.
# 남은 경로는 같은 출처인 iframe 문서에 <link> 를 직접 넣는 것뿐이다.
# 사이드바 드로어 자동닫힘과 같은 브리지 방식을 쓴다. 렌더러는 st.iframe 이다 —
# components.v1.html 은 1.59 에서 deprecated(2026-06-01 제거 예정)이고 이 저장소는
# 이미 그 계약을 테스트로 고정하고 있다(scripts/test_sidebar_ui.py S-04).
_FONT_HREF = ("https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9"
              "/dist/web/static/pretendard-dynamic-subset.css")

_FONT_BRIDGE = """
<script>
(function () {
  var HREF = "%s";
  function inject(doc) {
    if (!doc || doc.getElementById("wo-font")) return;
    var l = doc.createElement("link");
    l.id = "wo-font"; l.rel = "stylesheet"; l.href = HREF;
    (doc.head || doc.documentElement).appendChild(l);
  }
  function sweep() {
    var top = window.parent && window.parent.document;
    if (!top) return 0;
    var n = 0;
    top.querySelectorAll("iframe").forEach(function (f) {
      try { if (f.contentDocument) { inject(f.contentDocument); n++; } } catch (e) {}
    });
    return n;
  }
  sweep();
  // 그리드는 스크립트 실행 뒤에 마운트되므로 잠깐 동안만 반복해서 훑는다.
  var tries = 0;
  var t = setInterval(function () { sweep(); if (++tries > 20) clearInterval(t); }, 500);
})();
</script>
""" % _FONT_HREF


def _inject_component_font() -> None:
    """컴포넌트 iframe(표 등)에 본문과 같은 웹폰트를 로드한다."""
    st.iframe(_FONT_BRIDGE, height=1)


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
        _drawer_autoclose_bridge()

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
    """사이드바 헤더: 오렌지 로고 마크 + 앱명(WorkOps) + 접기(66px 레일) 버튼.

    표시명은 브랜드 'WorkOps' 단독이다(2026-08-18 사용자 결정). 종전 한글 부제
    '현장운영'(2026-08-13 확정)은 폐기했다 — 근무표·아차사고에 더해 시험성적서·
    계측기 주기관리·숙소예약·업무요청서까지 들어오면서 '현장 운영'이 범위를 좁게
    규정하게 됐고, 모듈이 계속 늘어나는 한 어떤 한글 부제도 같은 문제를 겪는다.
    부제를 두지 않아 범위를 규정하지 않는다. config.APP_NAME('WorkOps')이 공식 원천."""
    with st.container(key="sb_head"):
        brand, toggle = st.columns([5, 1.15], vertical_alignment="center")
        brand.markdown(
            "<div class='sb-brand'><span class='sb-logo'>W</span>"
            "<span class='sb-title'><span class='sb-title-ko'>WorkOps</span></span></div>",
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


# ---------- 모바일 드로어 자동 닫힘 (선택 → 닫힘, USER 셸 메뉴 시트와 동일 계약) ----------
#: 사이드바에서 화면을 고른 그 rerun 에서만 소비하는 1회성 신호.
_DRAWER_CLOSE_FLAG = "_sb_drawer_close"
#: 브리지 재마운트 강제용 일련번호(같은 HTML 이면 iframe 이 재사용돼 스크립트가 안 돈다).
_DRAWER_CLOSE_SEQ = "_sb_drawer_close_seq"

# 모바일(≤768px)에서 사이드바는 본문을 덮는 오버레이 드로어다(03dcb6b). 메뉴를 골라도
# 드로어가 그대로 남아 새 화면을 가리는 문제를 닫힘으로 정합한다(USER 셸 햄버거 시트의
# _user_menu_go 와 같은 "선택 = 닫힘" 계약).
#
# Streamlit 1.59 에는 **열려 있는 사이드바를 서버에서 접는 API가 없다** — rerun 마다
# set_page_config(initial_sidebar_state="collapsed") 를 다시 호출해도 이미 열린 드로어는
# aria-expanded="true" 그대로다(2026-08-14 격리 실험 실측). 그래서 화면을 고른 그 rerun 에만
# 같은 오리진 컴포넌트를 1회 띄워 네이티브 접기 컨트롤을 눌러 준다.
#   * 폭 게이트(parent innerWidth ≤ 768) — PC 사이드바/레일 동작은 손대지 않는다.
#   * 이미 닫혀 있으면 즉시 종료, 컨트롤을 못 찾으면 2초 후 포기 → 실패해도 현행 동작
#     (드로어 유지)으로 남을 뿐 화면이 깨지지 않는다.
#   * 접기 컨트롤은 ≤768px 에서만 노출되는 네이티브 X(_SHELL_CSS @media 복원분)이다.
_DRAWER_CLOSE_JS = """
<script>
(function () {
  var d = window.parent && window.parent.document;
  if (!d || (window.parent.innerWidth || 0) > 768) return;
  var tries = 0;
  var timer = setInterval(function () {
    tries += 1;
    var sb = d.querySelector('section[data-testid="stSidebar"]');
    if (!sb || sb.getAttribute('aria-expanded') !== 'true') { clearInterval(timer); return; }
    var btn = d.querySelector('[data-testid="stSidebarCollapseButton"] button')
           || d.querySelector('div[data-testid="stSidebarHeader"] button');
    if (btn) { btn.click(); clearInterval(timer); return; }
    if (tries > 20) clearInterval(timer);
  }, 100);
})();
</script>
"""


def _drawer_autoclose_bridge() -> bool:
    """이동 신호가 남아 있으면 드로어 닫기 브리지를 1회 렌더하고 True 를 돌려준다.

    발화 여부는 반환값과 :data:`_DRAWER_CLOSE_SEQ`(누적 발화 횟수) 둘 다로 관측된다 —
    신호는 렌더 직전에 소비(pop)되므로 "신호가 남아 있는지"만으로는 발화를 구분할 수 없다.

    HTML 이 직전과 같으면 Streamlit 이 기존 iframe 을 그대로 재사용해 스크립트가 다시
    실행되지 않는다 — 실제로 두 번째 메뉴 이동에서 드로어가 안 닫혔다(2026-08-14 실측).
    매 호출마다 일련번호를 실어 재마운트를 강제한다.

    렌더러는 :func:`st.iframe` 이다 — 구 ``components.v1.html`` 은 1.59 에서 deprecated
    (2026-06-01 제거 예정)이고, 실브라우저에서 st.iframe 도 raw HTML 의 스크립트를 실행하고
    parent DOM 에 접근함을 확인했다. 높이 0 은 ``StreamlitInvalidHeightError`` 라 1px 을
    쓴다(사이드바 맨 아래 1px — 실측 레이아웃 영향 없음)."""
    if not st.session_state.pop(_DRAWER_CLOSE_FLAG, False):
        return False
    seq = int(st.session_state.get(_DRAWER_CLOSE_SEQ, 0)) + 1
    st.session_state[_DRAWER_CLOSE_SEQ] = seq
    st.iframe(f"<!-- nav {seq} -->{_DRAWER_CLOSE_JS}", height=1)
    return True


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

    화면 이동 요청이면 모바일 드로어 닫기 신호를 남긴다(:data:`_DRAWER_CLOSE_FLAG`).
    현재 화면 재클릭·가드 보류에서도 남긴다 — 어느 경우든 모바일에서는 드로어가 본문
    (가드 확인 대화 포함)을 덮고 있어 닫는 것이 맞다. PC 에서는 브리지가 무동작이다.
    """
    if action.get("type") == "page":
        st.session_state[_DRAWER_CLOSE_FLAG] = True
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


#: 상단 52px 헤더 우측 스탬프 슬롯(이번 run 한정). 세션 스코프라 다른 접속자와 섞이지 않는다.
_HEADER_STAMP_SLOT = "_app_header_stamp_slot"


def header_stamp(text: str) -> None:
    """상단 헤더 우측에 조회 맥락 스탬프(예: ``2026-08-11 (화) · 전사``)를 채운다.

    화면 본문 렌더 중 호출한다 — 헤더가 이번 run 에서 만들어 둔 슬롯에 그대로 쓰므로
    조회 조건과 값이 어긋나지 않는다. 헤더가 없는 경로(USER 셸·단위 테스트 등)에서는
    아무 것도 하지 않는다(조용한 무동작). 표시 전용이며 어떤 상태도 바꾸지 않는다.
    """
    slot = st.session_state.get(_HEADER_STAMP_SLOT)
    if slot is None or not str(text).strip():
        return
    with slot:
        st.markdown(
            f"<span class='hdr-stamp'>{escape(str(text))}</span>", unsafe_allow_html=True
        )


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

# 단일 범위 화면(부속서 A-5 활성 허용)에서 헤더 아이콘이 실작동하는 페이지 매핑.
# {page: {icon(role): 세션 플래그 키}} — 헤더 아이콘 클릭이 그 화면의 기존 flag 계약을
# 발화하고(action_requester 와 동일 의미), 화면 render 가 소비한다(실행 경로·확인 게이트 불변).
# 기준정보 3화면은 views/master 의 page-scoped flag(`{page_id}:action:{name}`)를 그대로
# 쏜다 — 인페이지 액션바 버튼(on_click=state.action_requester)과 **같은 플래그**라 저장·
# 삭제 확인 게이트·재적재 경로가 한 벌로 유지된다(두 진입점, 한 실행 경로).
# 조직 관리는 2026-08-07 단일 시트(부서, DraftState "org_dept") 전환으로 단일 범위 화면이다.
_PAGE_HEADER_ACTIONS = {
    "schedule_edit": {
        "add": "se_add_req", "refresh": "se_go_req",
        "delete": "se_del_req", "save": "se_save_req",
    },
    "master_users": {
        "add": "master_users:action:add", "delete": "master_users:action:delete",
        "save": "master_users:action:save", "refresh": "master_users:action:refresh",
    },
    "master_work_types": {
        "add": "master_work_types:action:add", "delete": "master_work_types:action:delete",
        "save": "master_work_types:action:save", "refresh": "master_work_types:action:refresh",
    },
    "master_org": {
        "add": "org_dept:action:add", "delete": "org_dept:action:delete",
        "save": "org_dept:action:save", "refresh": "org_dept:action:refresh",
    },
    # 아차사고 조회: 상세 선택 시 인쇄(=PDF 생성·다운로드) 활성. add/delete/save 는 READ 라 미매핑(음영).
    "near_miss_view": {"print": "nmv_print_req"},
    # 월간 근무표(READ): 화면 안 [조회] 버튼을 없앤 뒤(2026-08-13 사용자 요구) 재조회 진입점은
    # 이 새로고침 아이콘 하나다. 조건 변경은 위젯 rerun 으로 즉시 반영되고, 이 플래그는
    # workspace.schedule_screen 이 렌더 첫머리에서 소비해 읽기 캐시를 비우고 재적재한다.
    # add/delete/save/print 는 미매핑 → 종전대로 음영(READ 화면).
    "schedule_view": {"refresh": "schedule_view_refresh_req"},
}
# 대상 유무(선택·dirty·쓰기가능)에 따라 음영이 갱신되는 아이콘과 그 **미발행 기본값**.
# True=화면이 아직 상태를 발행하지 않았으면 음영(안전측). add 는 대상이 필요 없는 액션이라
# 기본 활성이지만, 화면이 쓰기 차단(readiness/폐기 게이트)을 발행하면 그 값이 이긴다.
# 전부 True(음영) = fail-closed 대칭 — 화면이 publish_header_actions 를 아직 발행하지
# 않은 첫 렌더에서 add 만 활성이면 NOT_READY 등 쓰기 게이트를 한 렌더 우회한다
# (code-review P3). 발행 즉시 화면별 실상태로 덮인다.
_HDR_DEFAULT_DISABLED = {"delete": True, "save": True, "print": True, "add": True}
_HDR_STATE_PREFIX = "hdr_state:"


def publish_header_actions(page: str, states: dict) -> None:
    """화면이 상단 52px 헤더 아이콘의 음영/사유를 발행한다 — {icon: (disabled, help)}.

    **page 로 스코프**한다(구 전역 ``hdr_dis_{icon}`` 대체): 전역 키는 화면을 옮긴 첫
    렌더에서 헤더가 이전 화면의 값을 읽어 다른 화면의 선택/변경 상태로 음영을 그리는
    누수가 있었다(헤더는 본문보다 먼저 렌더된다). page 스코프면 그 화면이 아직 한 번도
    발행하지 않은 동안에만 :data:`_HDR_DEFAULT_DISABLED` 기본값이 쓰인다.

    화면은 인페이지 액션바와 **같은 활성 규칙**(``views/master.page_action_specs`` 등)의
    결과를 그대로 넘겨야 한다 — 두 진입점의 활성/사유가 갈리면 그 자체가 불일치다.
    """
    st.session_state[_HDR_STATE_PREFIX + str(page)] = {
        str(icon): (bool(disabled), help_text)
        for icon, (disabled, help_text) in dict(states).items()
    }


def _hdr_icon_state(page: str, icon: str, default_active: bool):
    """헤더 아이콘 한 개의 (active, enabled, on_click, help) 을 페이지별로 계산한다.

    페이지 매핑에 role 이 있으면 실작동(클릭=세션 플래그). 음영/사유는 화면이
    :func:`publish_header_actions` 로 발행한 값을 쓰고, 미발행이면
    :data:`_HDR_DEFAULT_DISABLED` 기본값(안전측)을 쓴다. 그 외 화면은 기존 기본
    (새로고침만 활성=rerun, 나머지 음영)."""
    flag = _PAGE_HEADER_ACTIONS.get(page, {}).get(icon)
    if flag is not None:
        published = st.session_state.get(_HDR_STATE_PREFIX + str(page)) or {}
        if icon in published:
            disabled, help_text = published[icon]
        else:
            disabled, help_text = _HDR_DEFAULT_DISABLED.get(icon, False), None
        return True, not disabled, (lambda f=flag: st.session_state.update({f: True})), help_text
    if icon == "refresh":  # 기본 새로고침(그 외 화면) — 클릭=rerun
        return True, True, None, None
    return False, False, None, None


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

    # 한 줄 가로 flex: 브레드크럼(flex:1 신축) + 연결 pill + 8종 아이콘(내용폭 고정). 아이콘은
    # 슬롯 2px 연속 배치(dc 원본), pill 과는 약간 여백. 좁은 폭에서도 pill·아이콘 폭이 고정돼
    # 브레드크럼만 줄어 겹치지 않는다(히트영역 32px 는 슬롯 크기로 충족).
    with st.container(key="app_header"):
        with st.container(key="hdr_row", horizontal=True, gap="small",
                          vertical_alignment="center"):
            st.markdown(crumb_html, unsafe_allow_html=True)
            # 날짜/범위 스탬프 슬롯 — 값은 화면 본문이 같은 run 에서 채운다(header_stamp).
            # 헤더는 본문보다 먼저 그려지므로 세션에 '발행'하면 한 프레임 늦는다. 슬롯을
            # 넘겨 두면 조회 조건과 항상 같은 값이 실린다(화면 내부 KPI 슬롯과 같은 패턴).
            # 채우지 않는 화면에서는 빈 컨테이너라 폭 0 이다(다른 화면 무변경).
            st.session_state[_HEADER_STAMP_SLOT] = st.container(
                key="hdr_stamp", width="content"
            )
            # 연결 pill 은 키 컨테이너로 감싼다 — CSS 가 순번이 아니라 키로 지정하게(위 주석).
            with st.container(key="hdr_conn", width="content"):
                st.markdown(conn_html, unsafe_allow_html=True)
            for label, icon, default_active in _HEADER_ICONS:
                # 상시 노출 + 음영: 활성이지만 비활성(삭제/저장 대상 없음)이면 음영(disabled).
                active, enabled, on_click, reason = _hdr_icon_state(page, icon, default_active)
                slot = "on" if (active and enabled) else "off"
                if not active:
                    tip = f"{label} — 이 화면에서는 사용하지 않습니다"
                elif enabled:
                    tip = label
                elif reason:  # 화면이 발행한 사유(인페이지 액션바 tooltip 과 동일 문구)
                    tip = f"{label} — {reason}"
                elif icon == "delete":
                    tip = f"{label} — 삭제할 행을 먼저 선택하세요"
                elif icon == "save":
                    tip = f"{label} — 저장할 변경이 없습니다"
                elif icon == "print":
                    tip = f"{label} — 보고서를 먼저 선택하세요"
                else:
                    tip = label
                with st.container(key=f"hdr_ic_{slot}_{icon}"):
                    clicked = st.button(
                        "", icon=f":material/{icon}:", key=f"app_hdr_{icon}",
                        type="tertiary", disabled=not (active and enabled),
                        help=tip, on_click=on_click,
                    )
                    # 기본 새로고침(on_click 없음)만 클릭 시 rerun. 실작동 아이콘은 on_click
                    # 이 플래그를 세팅하고 Streamlit 이 자동 rerun → 화면 render 가 소비.
                    if on_click is None and clicked and icon == "refresh":
                        st.rerun()


#: USER 햄버거 메뉴(popover) 위젯 키. ``on_change="rerun"`` 이라 열림/닫힘이
#: ``st.session_state[_USER_MENU_KEY]`` 에 담기고, 메뉴 항목 콜백이 이 값을 False 로
#: 되돌려 **이동 후 시트가 닫힌 상태**를 보장한다(Streamlit 기본 동작은 내부 위젯을
#: 눌러도 popover 를 열어 둔 채 rerun 한다 — st.popover docstring).
#: 위젯 값은 콜백(위젯 인스턴스화 이전)에서만 쓸 수 있다 — 렌더 본문에서 대입하면
#: StreamlitAPIException(cannot be modified after the widget ... is instantiated).
_USER_MENU_KEY = "user_menu_pop"


def _user_menu_go(page_id: str) -> None:
    """메뉴 시트에서 화면 이동 — 이동 후 시트를 닫는다(on_click 콜백)."""
    st.session_state.nav_page = page_id
    st.session_state[_USER_MENU_KEY] = False


def _user_menu_logout() -> None:
    """메뉴 시트 로그아웃 — 세션 정리 후 시트를 닫는다(on_click 콜백)."""
    st.session_state[_USER_MENU_KEY] = False
    auth.logout()


def user_app_shell(user: dict) -> str:
    """USER 전용 셸 — 상단 고정 앱바(앱명 · 현재 화면명 · 계정) + 햄버거 메뉴 시트.

    모바일 우선 구조다(USER 는 현장 단말 비중이 높다). 내비게이션 진입점은 앱바의
    햄버거 하나이며, 시트에는 이 사용자가 접근 가능한 화면 전부(nav.user_menu — 능력
    게이트 포함)와 로그아웃이 들어간다. 하단 고정 탭바는 두지 않는다(잘림·오버레이
    겹침 제거, _USER_SHELL_CSS 주석 참조). 반환값은 선택된 page id 로 종전과 같다.
    """
    caps = _menu_caps(user)
    menu = nav.user_menu(caps)
    valid_pages = {item["id"] for item in menu}
    page = st.session_state.get("nav_page")
    if page not in valid_pages:
        page = nav.default_page("USER", caps)
        st.session_state.nav_page = page

    st.markdown(_USER_SHELL_CSS, unsafe_allow_html=True)
    account = _user_account(user)
    sheet = _user_topbar(account, page)
    with sheet:
        _user_menu_sheet(account, menu, page)
    return page


def _user_account(user: dict) -> tuple:
    """(이름, '부서 · 조') — 앱바와 메뉴 시트가 같은 계정 표기를 쓰도록 한 곳에서 만든다."""
    dept = db.dept_name(user.get("dept_code", ""))
    team = db.team_name(user.get("dept_code", ""), user.get("team_code", ""))
    return str(user.get("name", "")), " · ".join(str(v) for v in (dept, team) if v)


def _user_topbar(account: tuple, page: str):
    """상단 고정 앱바 한 줄 — [햄버거] 앱명 / 현재 화면명 … 계정. 메뉴 시트 컨테이너 반환.

    폭 배분은 순번 선택자가 아니라 파이썬 width 계약으로 정한다(햄버거·계정=content,
    제목=stretch). 좁은 폭에서는 제목이 먼저 줄고 ellipsis 로 잘린다."""
    name, meta = account
    title_html = (
        f"<div class='ub-title'><span class='ub-app'>{escape(config.APP_NAME)}</span>"
        f"<span class='ub-sep'>/</span>"
        f"<span class='ub-screen'>{escape(nav.page_label(page))}</span></div>"
    )
    acct_html = (
        f"<div class='ub-acct'><span class='ub-acct-name'>{escape(name)}</span>"
        f"<span class='ub-acct-meta'>{escape(meta)}</span></div>"
    )
    with st.container(key="user_topbar", horizontal=True, gap="small",
                      vertical_alignment="center"):
        with st.container(key="user_menu_slot", width="content"):
            # 네이티브 popover: 열기는 프레임워크가 처리하고, 닫기는 항목 콜백이 소유한다.
            # 내용은 닫힌 상태에서도 실행된다(위젯 계약 유지 — btn_logout_user 등).
            sheet = st.popover(
                "메뉴", icon=":material/menu:", key=_USER_MENU_KEY,
                on_change="rerun", width="content", help="전체 메뉴 열기",
            )
        with st.container(key="user_title", width="stretch"):
            st.markdown(title_html, unsafe_allow_html=True)
        with st.container(key="user_acct", width="content"):
            st.markdown(acct_html, unsafe_allow_html=True)
    return sheet


def _user_menu_sheet(account: tuple, menu: list, page: str) -> None:
    """햄버거 시트 본문 — 계정 헤더 + 접근 가능 화면 전부 + 로그아웃.

    항목은 ``modules/nav.py`` 의 USER 메뉴(능력 게이트 반영)를 그대로 쓴다(하드코딩 금지).
    현재 화면은 primary 로 표시하고, 클릭은 on_click 콜백에서 이동 + 시트 닫기를 함께
    처리한다(콜백 뒤 Streamlit 이 자동 rerun 하므로 st.rerun 을 별도로 던지지 않는다).
    ``.um-sheet`` 마커는 이 시트의 popover 본문만 CSS 로 한정하기 위한 훅이다."""
    name, meta = account
    st.markdown(
        "<div class='um-sheet'></div>"
        f"<div class='um-acct'><span class='um-acct-name'>{escape(name)}</span>"
        f"<span class='um-acct-meta'>{escape(meta)}</span></div>",
        unsafe_allow_html=True,
    )
    for item in menu:
        # 위젯 key 는 종전 셸과 동일(user_nav_{id}) — st-key 클래스가 곧 CSS 훅이다.
        st.button(
            item["label"],
            key=f"user_nav_{item['id']}",
            icon=item["icon"],
            type="primary" if item["id"] == page else "secondary",
            width="stretch",
            on_click=_user_menu_go,
            args=(item["id"],),
        )
    st.button(
        "로그아웃",
        key="btn_logout_user",
        icon=":material/logout:",
        width="stretch",
        on_click=_user_menu_logout,
    )


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
