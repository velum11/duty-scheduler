"""셸 — 토큰 · 전역 CSS · 상단 2단 바 · 사이드바 메뉴.

값은 전부 `docs/mockup/WorkOps 최종 목업.dc.html` 실측이다. 이 파일에서 새 값을 만들지 않는다.

**이 파일이 데모의 판정 대상이다.** 목업의 셸을 Streamlit 위에 얹는 데 CSS 가 얼마나
필요한지, 어디서 Streamlit DOM 을 직접 건드려야 하는지가 여기 다 드러난다.
Streamlit 내부 선택자(`data-testid`)를 쓴 곳마다 `# [ST-INTERNAL]` 을 달아 세어 두었다.
"""
import streamlit as st

# ── 토큰 (목업 실측) ────────────────────────────────────────────────
ACCENT = "#b8460d"
ACCENT_HOVER = "#963a0a"
ACCENT_TINT = "#fdf0e8"
SIDEBAR_BG = "#faf9f6"
INK, INK2, INK3, INK4 = "#222", "#333", "#555", "#666"
MUTED = "#8a857e"
LINE_OUTER = "#b5b1aa"     # 표 바깥 테두리 · 헤더 밑선
LINE_ROW = "#e6e4df"       # 본문 행 밑선
LINE_COL = "#ecebe6"       # 본문 열 세로선
LINE_HEAD = "#cfccc6"      # 헤더 열 세로선
LINE_PANEL = "#e3e1dc"     # 조회조건 밑선
HEAD_BG = "#eceae5"        # 표 헤더 배경
INPUT_BD = "#c9c5be"
REQUIRED_BG = "#fdf6f1"    # 필수 조회조건 (국내 ERP 살구색 관례)
ROW_PICK = "#fdf6f1"

GNB_H = 56
RIBBON_H = 40
TOP_H = GNB_H + RIBBON_H
SIDEBAR_W = 206            # 목업 state.sbw
ROW_H = 29
CTRL_H = 28

PRETENDARD = (
    "https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9"
    "/dist/web/variable/pretendardvariable.min.css"
)

# ── 메뉴 (목업 사이드바 그대로) ──────────────────────────────────────
MENU = [
    {"id": "dash", "label": "근무 현황"},
    {"gid": "ws", "label": "근무표", "children": [
        ("plan", "근무표 편성"), ("roster", "월간 근무표"), ("mycal", "내 근무표")]},
    {"gid": "near", "label": "아차사고 관리", "children": [
        ("nearReg", "아차사고 등록"), ("myNear", "내 아차사고"),
        ("near", "아차사고 조회"), ("nearStat", "아차사고 분석")]},
    {"gid": "req", "label": "업무요청", "children": [
        ("reqReg", "업무요청 등록"), ("myreq", "내 업무요청"),
        ("reqProc", "업무요청 현황"), ("reqWork", "업무요청 처리 등록")]},
    {"gid": "stay", "label": "숙소 예약", "children": [
        ("stayReq", "숙소 예약 신청"), ("myStay", "내 숙소 예약"),
        ("stayAppr", "숙소 예약 승인"), ("cal", "예약 캘린더")]},
    {"gid": "base", "label": "기준정보", "children": [
        ("user", "사용자 관리"), ("org", "조직 관리"), ("wtm", "근무형태 관리")]},
]

TITLES = {i["id"]: i["label"] for i in MENU if "id" in i}
TITLES.update({cid: lbl for i in MENU if "children" in i for cid, lbl in i["children"]})

#: 데모가 실제로 구현한 화면. 나머지는 자리표시자를 그린다 — 안 만든 것을 만든 척하지 않는다.
IMPLEMENTED = {"dash", "plan", "user", "nearReg"}

#: 화면별 액션 버튼 — 목업 script `gActs` (1422행). (라벨, 주액션여부)
ACTIONS = {
    "plan": [("편성 확정", True), ("임시저장", False), ("되돌리기", False)],
    "user": [("비밀번호 초기화", False), ("퇴직 처리", False)],
    "nearReg": [("제출", True), ("임시저장", False), ("초기화", False)],
}


def page_setup() -> None:
    st.set_page_config(
        page_title="WorkOps", page_icon="W",
        layout="wide", initial_sidebar_state="expanded",
    )


def inject_css() -> None:
    # 웹폰트는 st.html 로 못 넣는다 — **실측**: st.html 은 <link> 와 @import 를 둘 다
    # 제거한다(주입 후 문서의 @font-face 규칙 0건, Pretendard 폭 == 미설치 폰트 폭).
    # 그래서 폰트만 legacy 경로(st.markdown + unsafe_allow_html)로 넣는다. 한 줄이라
    # 마크다운 파서가 자르지 않는다 — 여러 줄 CSS 를 이 경로로 넣으면 빈 줄마다 잘린다.
    st.markdown(f'<style>@import url("{PRETENDARD}");</style>', unsafe_allow_html=True)
    st.html(f"""
<style>
/* ── 1. 글꼴·기준 크기 ─────────────────────────────────────────────
   목업 본문은 12px 이다. Streamlit 기본은 16px html / 14px 위젯이라
   전역과 위젯을 따로 눌러야 한다. */
html, body, .stApp,
.stApp [data-testid="stMarkdownContainer"], .stApp [data-testid="stMarkdownContainer"] *,   /* [ST-INTERNAL] */
.stApp button, .stApp input, .stApp select, .stApp textarea,
.stApp [data-baseweb="select"], .stApp [data-baseweb="input"] {{                            /* [ST-INTERNAL] */
  font-family:'Pretendard Variable',Pretendard,'Malgun Gothic',system-ui,sans-serif;
}}
html, body, .stApp {{ font-size:12px; }}
.stApp {{ background:#fff; color:{INK}; }}
* {{ box-sizing:border-box; }}
td, th {{ font-variant-numeric:tabular-nums; }}

/* ── 2. Streamlit 크롬 제거 ────────────────────────────────────────
   목업에는 Streamlit 의 헤더·푸터·배포버튼·상태위젯이 존재하지 않는다.
   전부 내부 testid 로만 지목할 수 있다. */
#MainMenu, footer, .stAppDeployButton,
header[data-testid="stHeader"],                        /* [ST-INTERNAL] */
div[data-testid="stDecoration"],                       /* [ST-INTERNAL] */
div[data-testid="stStatusWidget"],                     /* [ST-INTERNAL] */
div[data-testid="stSidebarHeader"],                    /* [ST-INTERNAL] */
div[data-testid="stSidebarCollapseButton"],            /* [ST-INTERNAL] */
[data-testid="stSidebarCollapsedControl"] {{           /* [ST-INTERNAL] */
  display:none !important;
}}

/* ── 3. 본문 프레임 ────────────────────────────────────────────────
   목업은 여백 0 · 전폭이다. Streamlit 은 block-container 에 큰 패딩과
   max-width 를 준다. 상단 고정바(96px) 만큼 위를 비운다. */
section[data-testid="stMain"] .block-container {{      /* [ST-INTERNAL] */
  padding:{TOP_H}px 0 0 0 !important; max-width:none !important;
}}
section[data-testid="stMain"] div[data-testid="stVerticalBlock"] {{ gap:0; }}    /* [ST-INTERNAL] */
section[data-testid="stMain"] div[data-testid="stHorizontalBlock"] {{ gap:0; }}  /* [ST-INTERNAL] */
section[data-testid="stMain"] div[data-testid="stElementContainer"] {{           /* [ST-INTERNAL] */
  margin:0; }}
/* Streamlit 컬럼은 **비율만** 받고 좁아지면 줄어드는 대신 넘친다. 목업은 두 군데에서
   줄바꿈으로 이 문제를 푼다 — 조회조건 줄은 `grid auto-fit minmax(230px,1fr)`,
   구획 제목의 액션 버튼 줄은 `flex-wrap:wrap`. 전역 nowrap 은 폐기하고(그게 좁은 폭에서
   버튼을 겹치게 만든 원인) 두 군데를 각각 목업 규칙에 맞춘다. */
section[data-testid="stMain"] div[data-testid="stColumn"] {{      /* [ST-INTERNAL] */
  min-width:0; }}

/* ── 4. 사이드바 ──────────────────────────────────────────────────
   폭 206px(목업 state.sbw), 배경 #faf9f6, 패딩 0, 상단 고정바만큼 내림. */
section[data-testid="stSidebar"] {{                    /* [ST-INTERNAL] */
  width:{SIDEBAR_W}px !important; min-width:{SIDEBAR_W}px !important;
  background:{SIDEBAR_BG}; border-right:1px solid {LINE_OUTER};
  padding-top:{TOP_H}px;
}}
section[data-testid="stSidebar"] > div {{ padding:0 !important; }}               /* [ST-INTERNAL] */
div[data-testid="stSidebarUserContent"] {{ padding:2px 0 10px !important; }}     /* [ST-INTERNAL] */
section[data-testid="stSidebar"] div[data-testid="stVerticalBlock"] {{ gap:0; }} /* [ST-INTERNAL] */
section[data-testid="stSidebar"] div[data-testid="stElementContainer"] {{        /* [ST-INTERNAL] */
  margin:0; }}

/* ── 5. 사이드바 메뉴 행 ──────────────────────────────────────────
   목업: 그룹 31px/12.5px, 하위 28px/12px(들여쓰기 27px), 좌측 점 마커,
   그룹 우측 ▸/▾. st.button 으로 만들어야 클릭이 Python 에 닿는데,
   버튼 하나로 이 모양이 안 나와서 ::before/::after 로 마커를 붙인다. */
section[data-testid="stSidebar"] .stButton > button {{
  height:31px; min-height:31px; width:100%;
  display:flex; align-items:center; justify-content:flex-start;
  gap:8px; padding:0 12px; margin:0;
  border:0; border-radius:0; background:transparent; box-shadow:none;
  font-size:12.5px; font-weight:400; color:#4a463f; white-space:nowrap;
}}
section[data-testid="stSidebar"] .stButton > button:hover {{
  background:#f0ede7; color:#4a463f; border:0;
}}
section[data-testid="stSidebar"] .stButton > button:focus,
section[data-testid="stSidebar"] .stButton > button:active {{
  color:#4a463f; box-shadow:none; outline:none;
}}
section[data-testid="stSidebar"] .stButton > button p {{
  font-size:inherit; font-weight:inherit; line-height:1;
}}
/* 라벨 정렬 — 버튼에 flex-start 를 줘도 안쪽 stMarkdownContainer 가 폭을 다 먹어
   가운데로 보인다. 컨테이너를 flex:none 으로 만들어야 ::after 의 margin-left:auto 가 산다. */
section[data-testid="stSidebar"] .stButton > button {{ text-align:left; }}
section[data-testid="stSidebar"] .stButton > button > div,
section[data-testid="stSidebar"] .stButton > button span,
section[data-testid="stSidebar"] .stButton > button div[data-testid="stMarkdownContainer"] {{
  flex:none; width:auto; text-align:left; display:block;      /* [ST-INTERNAL] */
}}
/* 그룹 행: 좌측 점 + 우측 화살표 */
[class*="st-key-grp_"] .stButton > button::before {{
  content:''; flex:none; width:5px; height:5px; border-radius:50%; background:#c9c5be;
}}
[class*="st-key-grp_"] .stButton > button::after {{
  content:'\\25B8'; margin-left:auto; font-size:9px; color:{MUTED};
}}
/* 단독 행(근무 현황)도 점을 가진다 */
.st-key-nav_dash .stButton > button::before {{
  content:''; flex:none; width:5px; height:5px; border-radius:50%; background:#c9c5be;
}}
/* 하위 행: 28px · 12px · 들여쓰기 27px · 마커 없음 */
[class*="st-key-nav_"]:not(.st-key-nav_dash) .stButton > button {{
  height:28px; min-height:28px; padding:0 12px 0 27px; font-size:12px;
}}

/* ── 6. 조회조건 줄 ───────────────────────────────────────────────
   목업: padding 11px 14px · 밑선 · 라벨 62px 우측정렬 12px/700 ·
   컨트롤 28px/12px/radius 2px. Streamlit 위젯 기본은 40px/14px 이라
   selectbox 는 baseweb 내부까지 내려가서 눌러야 한다. */
.st-key-filterbar {{ padding:11px 14px; border-bottom:1px solid {LINE_PANEL}; }}
/* 목업 `repeat(auto-fit, minmax(230px,1fr))` 근사 — 폭이 모자라면 다음 줄로 접힌다 */
.st-key-filterbar > div[data-testid="stHorizontalBlock"] {{         /* [ST-INTERNAL] */
  flex-wrap:wrap; row-gap:7px; }}
.st-key-filterbar > div[data-testid="stHorizontalBlock"]
  > div[data-testid="stColumn"] {{ flex:1 1 230px; min-width:230px; }}   /* [ST-INTERNAL] */
/* 안쪽 라벨/컨트롤 줄은 접히면 안 된다 — 목업은 62px 라벨을 끝까지 옆에 둔다 */
.st-key-filterbar div[data-testid="stColumn"]
  div[data-testid="stHorizontalBlock"] {{ flex-wrap:nowrap !important; }}  /* [ST-INTERNAL] */
/* 라벨 열은 목업이 62px 고정이다. 비율로 두면 좁은 폭에서 "사번·성명"이 잘린다 */
.st-key-filterbar div[data-testid="stColumn"]
  div[data-testid="stColumn"]:first-child {{                        /* [ST-INTERNAL] */
  flex:0 0 66px !important; min-width:66px !important; }}
.st-key-filterbar div[data-testid="stColumn"]
  div[data-testid="stColumn"]:last-child {{                         /* [ST-INTERNAL] */
  flex:1 1 auto !important; min-width:0 !important; }}
.st-key-dashbar {{ padding:11px 14px; border-bottom:1px solid {LINE_PANEL}; }}
.wo-flabel {{ font-size:12px; font-weight:700; color:{INK2}; text-align:right;
  white-space:nowrap; padding-right:8px; }}
.wo-datebox {{ height:30px; display:inline-flex; align-items:center; justify-content:center;
  padding:0 4px; border:1px solid {INPUT_BD}; border-radius:2px; background:#fff;
  font-size:12px; font-weight:600; color:{INK}; white-space:nowrap; }}
.wo-dateline {{ display:inline-flex; align-items:center; gap:8px; }}
.wo-dateline .wo-flabel {{ padding-right:0; }}

/* ⚠ Streamlit 1.59 는 selectbox 를 BaseWeb → react-aria 로 갈아치웠다.
   `div[data-baseweb="select"]` 는 이 버전에 **존재하지 않는다**(운영 앱 modules/ui.py
   가 아직 그 선택자를 7곳에서 쓴다 — 그 규칙들은 지금 죽어 있다).
   그래서 role="group" + .react-aria-ComboBox 로 다시 잡는다. */
section[data-testid="stMain"] [data-testid="stSelectbox"] div[role="group"],   /* [ST-INTERNAL] */
section[data-testid="stMain"] [data-testid="stTextInput"] div[role="group"],   /* [ST-INTERNAL] */
section[data-testid="stMain"] div[data-testid="stTextInputRootElement"] {{     /* [ST-INTERNAL] */
  min-height:{CTRL_H}px !important; height:{CTRL_H}px !important;
  border-radius:2px !important; border:1px solid {INPUT_BD} !important;
  background:#fff; box-shadow:none !important;
}}
section[data-testid="stMain"] [data-testid="stSelectbox"] input,               /* [ST-INTERNAL] */
section[data-testid="stMain"] [data-testid="stTextInput"] input {{             /* [ST-INTERNAL] */
  height:26px !important; min-height:26px !important; padding:0 9px !important;
  font-size:12px !important; color:{INK}; }}
section[data-testid="stMain"] [data-testid="stSelectbox"] button {{            /* [ST-INTERNAL] */
  height:26px; min-height:26px; border:0; background:transparent; }}
/* 첫 칸은 필수 조회조건 — 국내 ERP 살구색 관례 (목업 실측 #fdf6f1) */
.st-key-filterbar div[data-testid="stColumn"]:first-child                      /* [ST-INTERNAL] */
  div[role="group"] {{ background:{REQUIRED_BG} !important; }}
.st-key-filterbar div[data-testid="stColumn"]:first-child input {{             /* [ST-INTERNAL] */
  background:{REQUIRED_BG} !important; }}

/* ── 7. 구획 제목 + 액션 버튼 ─────────────────────────────────────*/
[class*="st-key-sechead"] {{ padding:8px 14px 0; }}
.wo-sechead {{ display:flex; align-items:baseline; gap:10px; }}
.wo-sectitle {{ font-size:12px; font-weight:700; color:{INK2}; white-space:nowrap; }}
.wo-secsub {{ font-size:11.5px; color:{INK4}; white-space:nowrap; }}

section[data-testid="stMain"] .stButton > button {{
  height:{CTRL_H}px; min-height:{CTRL_H}px; padding:0 13px; border-radius:2px;
  font-size:11.5px; font-weight:400; border:1px solid {INPUT_BD};
  background:#fff; color:{INK2}; white-space:nowrap;
}}
section[data-testid="stMain"] .stButton > button p {{
  font-size:11.5px; font-weight:inherit; line-height:1; }}
section[data-testid="stMain"] .stButton > button:hover {{
  background:#f7f5f1; color:{INK2}; border-color:{INPUT_BD}; }}
section[data-testid="stMain"] .stButton > button[kind="primary"],
section[data-testid="stMain"] button[data-testid="stBaseButton-primary"] {{  /* [ST-INTERNAL] */
  background:{ACCENT}; border-color:{ACCENT}; color:#fff; font-weight:600; }}
section[data-testid="stMain"] .stButton > button[kind="primary"]:hover,
section[data-testid="stMain"] button[data-testid="stBaseButton-primary"]:hover {{
  background:{ACCENT_HOVER}; border-color:{ACCENT_HOVER}; color:#fff; }}

/* 버튼 줄 — 목업은 `display:flex; gap:5px; flex-wrap:wrap` 에 버튼이 **내용 폭**이다.
   Streamlit 은 버튼마다 블록 컨테이너를 만들므로 그 컨테이너를 flex 아이템으로 되돌린다.
   이렇게 해야 좁은 폭에서 글자가 잘리지 않고 다음 줄로 접힌다. */
/* ⚠ st.container(key=...) 의 `st-key-*` 클래스는 stVerticalBlock **자신**에 붙는다.
   자손 선택자로 쓰면 매치되지 않는다(첫 시도가 그래서 실패했고, 버튼이 세로로 쌓였다).
   그리고 한글·공백 key 는 `btnrow_2026-08-------` 처럼 치환되므로 부분일치로 잡는다. */
div[class*="st-key-btnrow_"] {{                                    /* [ST-INTERNAL] */
  flex-direction:row !important; flex-wrap:wrap; justify-content:flex-end;
  align-items:center; gap:5px !important; }}
div[class*="st-key-btnrow_"] > div[data-testid="stElementContainer"] {{  /* [ST-INTERNAL] */
  width:auto !important; flex:0 0 auto; }}
div[class*="st-key-btnrow_"] .stButton,
div[class*="st-key-btnrow_"] .stButton > button {{ width:auto !important; }}
div[class*="st-key-btnrow_left"] {{ justify-content:flex-start; gap:8px !important; }}

/* ── 8. 표 렌더 방식 토글 (데모 전용 장치) ───────────────────────*/
[class*="st-key-modebar_"] {{ padding:6px 14px 0; }}
.wo-modehint {{ font-size:11px; color:{MUTED}; text-align:right; padding-right:8px;
  line-height:28px; }}

/* ── 9. FORM_ENTRY ────────────────────────────────────────────────
   목업: 라벨 셀 132px · 배경 #eceae5 · 우측 구분선 · 11.5px/700,
   값 영역 padding 5px 8px, 하단 액션바 배경 #faf9f6. */
.st-key-formwrap {{ padding:8px 14px 14px; }}
.st-key-formpanel {{ border:1px solid {LINE_OUTER}; }}
[class*="st-key-frow_"] {{ border-bottom:1px solid {LINE_ROW}; }}
[class*="st-key-frow_"] div[data-testid="stColumn"]:last-child {{   /* [ST-INTERNAL] */
  padding:5px 8px; }}
.wo-fcell {{ height:38px; display:flex; align-items:center; padding:0 10px;
  background:{HEAD_BG}; border-right:1px solid {LINE_HEAD};
  font-size:11.5px; font-weight:700; color:{INK2}; white-space:nowrap; }}
.st-key-formacts {{ background:{SIDEBAR_BG}; padding:8px 10px; }}
.wo-filechip {{ display:inline-flex; align-items:center; height:28px; padding:0 10px;
  border:1px solid {LINE_PANEL}; border-radius:2px; background:{SIDEBAR_BG};
  font-size:11.5px; color:{INK4}; white-space:nowrap; }}
.wo-fhint {{ font-size:11px; color:{MUTED}; display:flex; align-items:center; height:28px; }}
.wo-sidepanel {{ border:1px solid {LINE_OUTER}; }}
.wo-sidehead {{ height:27px; display:flex; align-items:center; justify-content:space-between;
  padding:0 10px; background:{HEAD_BG}; border-bottom:1px solid {LINE_OUTER};
  font-size:11.5px; font-weight:700; color:{INK}; }}
.wo-siderow {{ display:flex; flex-direction:column; gap:3px; padding:8px 10px;
  border-bottom:1px solid {LINE_ROW}; cursor:pointer; }}
.wo-siderow:hover {{ background:{ROW_PICK}; }}
.wo-siderow-top {{ display:flex; align-items:center; justify-content:space-between;
  gap:8px; font-size:11px; color:{MUTED}; }}
.wo-sidefoot {{ display:flex; justify-content:flex-end; padding:8px 10px;
  background:{SIDEBAR_BG}; font-size:11.5px; }}
</style>
""")


def _nav_state_css(current: str, open_groups: set) -> str:
    """선택·펼침 상태는 렌더마다 달라지므로 규칙을 그때그때 만들어 넣는다.

    st.button 에는 '선택됨' 상태가 없다 — key 로 생기는 `st-key-*` 클래스를
    유일한 손잡이로 삼는다.
    """
    rules = [
        # 선택된 항목: 액센트 틴트 + 좌측 3px 표시
        f".st-key-nav_{current} .stButton > button {{"
        f"background:{ACCENT_TINT} !important; color:{ACCENT} !important;"
        f"font-weight:700 !important; box-shadow:inset 3px 0 0 {ACCENT} !important; }}",
        f".st-key-nav_{current} .stButton > button::before {{ background:{ACCENT} !important; }}",
    ]
    for gid in open_groups:
        rules.append(f".st-key-grp_{gid} .stButton > button::after {{ content:'\\25BE'; }}")
        rules.append(
            f".st-key-grp_{gid} .stButton > button {{ font-weight:700; color:{INK2}; }}")
        rules.append(f".st-key-grp_{gid} .stButton > button::before {{ background:{ACCENT}; }}")
    return "<style>" + "".join(rules) + "</style>"


def sidebar_nav() -> str:
    """사이드바 메뉴를 그리고 현재 화면 id 를 돌려준다."""
    cur = st.session_state.setdefault("wo_page", "plan")
    groups = st.session_state.setdefault("wo_groups", {"ws"})

    st.sidebar.html(_nav_state_css(cur, groups))

    with st.sidebar:
        for item in MENU:
            if "id" in item:
                if st.button(item["label"], key=f"nav_{item['id']}", width="stretch"):
                    st.session_state.wo_page = item["id"]
                    st.rerun()
                continue
            gid = item["gid"]
            if st.button(item["label"], key=f"grp_{gid}", width="stretch"):
                groups.symmetric_difference_update({gid})
                st.rerun()
            if gid in groups:
                for cid, label in item["children"]:
                    if st.button(label, key=f"nav_{cid}", width="stretch"):
                        st.session_state.wo_page = cid
                        st.rerun()

        # 하단 사용자 블록 — 클릭이 없으므로 HTML 로 둔다
        st.html(f"""
<div style="display:flex;align-items:center;gap:7px;padding:9px 12px;
            border-top:1px solid #ddd8d0;margin-top:6px">
  <span style="width:22px;height:22px;border-radius:50%;background:#e5e1d8;display:flex;
               align-items:center;justify-content:center;font-size:10.5px;font-weight:600;
               color:#4a463f">이</span>
  <div style="display:flex;flex-direction:column;gap:1px;min-width:0">
    <span style="font-size:11.5px;font-weight:600;color:#2e2a26">이광호</span>
    <span style="font-size:10.5px;color:{MUTED}">전산팀 · PET1</span>
  </div>
</div>""")

    return st.session_state.wo_page


# ── 상단 2단 바 ────────────────────────────────────────────────────
_RIBBON_ICONS = """
<span title="정보" class="wo-ic"><svg width="20" height="20" viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="8.5" fill="#fff"/><rect x="9" y="8.6" width="2" height="5.9" rx="1" fill="#b8460d"/><circle cx="10" cy="6" r="1.2" fill="#b8460d"/></svg></span>
<span title="언어" class="wo-ic"><svg width="20" height="20" viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="8.5" fill="#fff"/><g stroke="#b8460d" stroke-width="1.1" fill="none"><path d="M10 1.5v17M1.5 10h17"/><ellipse cx="10" cy="10" rx="4.2" ry="8.5"/><path d="M2.9 5.5h14.2M2.9 14.5h14.2"/></g></svg></span>
<span title="추가" class="wo-ic"><svg width="20" height="20" viewBox="0 0 20 20" fill="none"><rect x="2.4" y="2.4" width="15.2" height="15.2" rx="1.2" stroke="#fff" stroke-width="1.5"/><path d="M10 6.2v7.6M6.2 10h7.6" stroke="#fff" stroke-width="1.5" stroke-linecap="round"/></svg></span>
<span title="조회" class="wo-ic"><svg width="20" height="20" viewBox="0 0 20 20" fill="none"><rect x="2.2" y="2.6" width="12.8" height="14.8" rx="1.2" stroke="#fff" stroke-width="1.5"/><circle cx="12.8" cy="10.2" r="4.7" fill="#b8460d"/><circle cx="12.8" cy="10.2" r="3.2" stroke="#fff" stroke-width="1.5"/><path d="M15.2 12.7l2.4 2.5" stroke="#fff" stroke-width="1.7" stroke-linecap="round"/></svg></span>
<span title="삭제" class="wo-ic"><svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M3.6 5.6h12.8" stroke="#fff" stroke-width="1.5" stroke-linecap="round"/><path d="M7.8 5.4V4.2a1 1 0 011-1h2.4a1 1 0 011 1v1.2" stroke="#fff" stroke-width="1.4"/><path d="M5.5 8h9l-.62 8.6a1.5 1.5 0 01-1.5 1.4H7.62a1.5 1.5 0 01-1.5-1.4L5.5 8z" stroke="#fff" stroke-width="1.5"/></svg></span>
<span title="저장" class="wo-ic"><svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M3.4 2.8h10.4l3.4 3.4v10.4a.6.6 0 01-.6.6H3.4a.6.6 0 01-.6-.6V3.4a.6.6 0 01.6-.6z" stroke="#fff" stroke-width="1.5"/><path d="M6.6 2.8v4.4h6.8V2.8" stroke="#fff" stroke-width="1.4"/><rect x="10.9" y="3.6" width="1.7" height="2.6" fill="#fff"/><rect x="6" y="10.8" width="8" height="6.4" stroke="#fff" stroke-width="1.4"/></svg></span>
<span title="즐겨찾기" class="wo-ic"><svg width="22" height="22" viewBox="0 0 20 20" fill="none"><path d="M10 1.4l2.6 5.5 6 .8-4.4 4.15 1.1 5.95L10 14.9l-5.3 2.9 1.1-5.95L1.4 7.7l6-.8L10 1.4z" fill="#ffd24a"/></svg></span>
"""


def top_bars(title: str) -> None:
    """GNB(56px) + 리본(40px). 사이드바 위까지 덮어야 해서 position:fixed 다.

    목업에서는 이 둘이 사이드바와 같은 flex 프레임의 형제다. Streamlit 에서는
    사이드바가 최상단부터 시작하는 별도 형제라 같은 프레임에 넣을 수 없다 —
    그래서 고정 배치로 덮고, 사이드바·본문에 padding-top 96px 을 주어 자리를 비운다.
    """
    st.html(f"""
<style>
.wo-top {{ position:fixed; top:0; left:0; right:0; z-index:999999; }}
.wo-gnb {{ height:{GNB_H}px; display:flex; align-items:center; gap:12px;
  padding:0 16px 0 0; background:#fff; border-bottom:1px solid #d9d5ce; }}
.wo-brand {{ flex:none; width:{SIDEBAR_W}px; display:flex; align-items:center; gap:9px;
  padding-left:16px; white-space:nowrap; }}
.wo-tab {{ height:34px; display:flex; align-items:center; gap:8px; padding:0 10px 0 13px;
  border:1px solid {ACCENT}; border-radius:6px; background:#fff;
  font-size:13px; font-weight:600; color:{ACCENT}; white-space:nowrap; }}
.wo-ribbon {{ height:{RIBBON_H}px; display:flex; align-items:stretch; background:{ACCENT}; }}
.wo-search {{ flex:none; width:{SIDEBAR_W}px; display:flex; align-items:center;
  padding:0 12px 0 16px; border-right:1px solid {ACCENT_HOVER}; }}
.wo-ic {{ width:28px; height:28px; display:flex; align-items:center; justify-content:center;
  border-radius:3px; cursor:pointer; }}
.wo-ic:hover {{ background:rgba(255,255,255,.2); }}
</style>
<div class="wo-top">
  <div class="wo-gnb">
    <div class="wo-brand">
      <span style="width:30px;height:30px;border-radius:6px;background:{ACCENT};color:#fff;
        display:flex;align-items:center;justify-content:center;font-size:16px;font-weight:800">W</span>
      <span style="font-size:21px;font-weight:800;color:#1c1a17;letter-spacing:-0.03em">Work<span
        style="color:{ACCENT}">Ops</span></span>
    </div>
    <span class="wo-tab"><span style="font-size:10px;color:#d18a5e">&#9019;</span>{title}
      <span style="width:15px;height:15px;margin-left:1px;display:flex;align-items:center;
        justify-content:center;font-size:11px;color:#c07a51;cursor:pointer">&#10005;</span></span>
    <div style="margin-left:auto;display:flex;align-items:center;gap:14px">
      <span style="display:flex;align-items:center;gap:6px;height:24px;padding:0 10px;
        border:1px solid #cfe0d3;border-radius:4px;background:#f2f8f3;font-size:11.5px;
        color:#2f6b4f;white-space:nowrap">데모 모드</span>
      <span style="display:flex;align-items:center;gap:7px;height:32px;padding:0 10px 0 6px;
        border:1px solid #ded9d1;border-radius:4px;white-space:nowrap">
        <span style="width:24px;height:24px;border-radius:50%;background:#efece5;display:flex;
          align-items:center;justify-content:center;font-size:11px;font-weight:700;
          color:#6b655d">이</span>
        <span style="font-size:12.5px;font-weight:700;color:#2e2a26">이광호</span>
        <span style="font-size:9px;color:{MUTED}">&#9662;</span></span>
    </div>
  </div>
  <div class="wo-ribbon">
    <div class="wo-search">
      <div style="flex:1;height:28px;display:flex;align-items:center;justify-content:space-between;
        gap:6px;padding:0 9px 0 11px;border:1px solid #e6a684;border-radius:2px;background:#fff;
        box-shadow:inset 0 1px 2px rgba(90,40,10,.14)">
        <span style="font-size:11.5px;font-weight:600;color:#4a463f">메뉴 검색</span>
        <span style="font-size:11px;color:{MUTED}">&#9776;&#8981;</span></div>
    </div>
    <div style="flex:1;min-width:0;display:flex;align-items:center;justify-content:space-between;
      padding:0 14px">
      <div style="display:flex;align-items:center;gap:8px">
        <span style="display:flex;align-items:center;justify-content:center;width:19px;height:19px;
          border-radius:3px;background:rgba(255,255,255,.22);font-size:11px;color:#fff">&#9638;</span>
        <span style="font-size:15px;font-weight:700;color:#fff;letter-spacing:-0.01em">{title}</span>
      </div>
      <div style="display:flex;align-items:center;gap:3px">{_RIBBON_ICONS}</div>
    </div>
  </div>
</div>
""")


def placeholder(title: str) -> None:
    st.html(f"""
<div style="padding:40px 14px;color:{INK4};font-size:12px">
  <div style="font-size:12px;font-weight:700;color:{INK2};margin-bottom:6px">■ {title}</div>
  이 데모는 <b>근무 현황 · 근무표 편성 · 사용자 관리</b> 3화면만 구현했습니다.
  나머지 메뉴는 사이드바 동작 확인용입니다.
</div>""")
