"""기준정보 3화면 공통 디자인 토큰 · CSS · 상태 시각(이중 부호화).

design-contract.md(§1~§25, 상태→시각 매트릭스)의 시각 계약을 실제 구현 자산으로
고정한다. 두 경계를 분리한다:
  - **페이지 크롬**(제목/필터바/액션바/배너/푸터): ``inject_page_styles`` 가 주입하는
    ``st.markdown('<style>')`` + ``.st-key-*`` 스코프.
  - **그리드 내부**(헤더/행/셀/상태): ``GRID_CSS`` (``AgGrid(custom_css=...)``) +
    ``master_row_class_rules`` / ``cell_error_rule`` 등 클래스 기반 규칙.

핵심 규칙(계약):
  - **색만으로 상태를 표시하지 않는다** — 모든 상태는 색 + (아이콘·배지·테두리·라벨)로
    이중 부호화한다. 컬러 이모지(💾🗑📁)는 상태 신호로 쓰지 않는다.
  - 배경 우선순위(상호 배타): ``error > delete_pending > new > inactive > selected > zebra``.
  - 모드 배지(데이터 연결)와 migration readiness(스키마 준비)는 색·의미를 섞지 않는다.
"""
from __future__ import annotations

from html import escape
from urllib.parse import quote

import streamlit as st

# ---------------------------------------------------------------------------
# §2 색상 토큰 (semantic) — 배지/칩 HTML 생성 시 파이썬에서도 참조한다.
# ---------------------------------------------------------------------------
TOKENS: dict[str, str] = {
    # Claude Design 채택 P1(ADOPTION_SPEC 정본). 캔버스 near-white 웜뉴트럴 #f4f2ee,
    # 오렌지 단일 액센트(navy 키는 하위호환 위해 유지하되 값은 액센트). 읽는 텍스트 대비 실측:
    # ink #1c1a17(15.53) · ink-2 #4a453d(8.50) · ink-3 #6b665d(5.1, 최저 읽기 회색).
    "canvas": "#f4f2ee",
    "surface": "#FFFFFF",
    "surface-2": "#fbfaf8",
    "surface-3": "#f1eee7",
    "line": "#e6e2da",
    "line-strong": "#cfc8bd",
    "ink": "#1c1a17",
    "ink-2": "#4a453d",
    "ink-3": "#6b665d",
    # 단일 오렌지 액센트 — navy/navy-hover 키는 소비처 호환 위해 남기고 값만 액센트로 교체.
    "navy": "#c2410c",
    "navy-hover": "#a3350a",
    "gold": "#8a6212",
    "gold-soft": "#fdf3ec",
    "info": "#2f4d99",
    "info-bg": "#eef2fb",
    "success": "#2f6b45",
    "success-bg": "#eef5f0",
    "warn": "#8a6212",
    "warn-bg": "#fdf3e3",
    "danger": "#9c3232",
    "danger-bg": "#fbeeee",
    "selected-bg": "#fdf3ec",
}

# ── 라이프사이클 상태 배지 표준 팔레트(ADOPTION_SPEC 정본, radius 999 / 12.5·600) ──
# 배경/글자/테두리 3색. 도메인(near_miss_*)이 status 코드로 조회한다. 색 신호는 보조이며
# 라벨 텍스트가 항상 함께 표시된다(이중부호화). 텍스트 대비 실측 4.98~7.09:1(전부 통과).
LIFECYCLE_BADGE: dict[str, dict[str, str]] = {
    "SUBMITTED": {"bg": "#fdf3e3", "text": "#8a6212", "border": "#f0dfbe"},
    "IN_REVIEW": {"bg": "#eef2fb", "text": "#2f4d99", "border": "#dbe3f4"},
    "EVALUATED": {"bg": "#eef5f0", "text": "#2f6b45", "border": "#d8e6dd"},
    "REJECTED": {"bg": "#fbeeee", "text": "#9c3232", "border": "#f0d9d9"},
    "CLOSED":   {"bg": "#f2f0ec", "text": "#5c564d", "border": "#e4e0d8"},
}


def lifecycle_badge_html(status_code: str, label: str) -> str:
    """라이프사이클 상태 배지 HTML(ADOPTION_SPEC 팔레트, radius 999 / 12.5px·600).

    ``status_code`` 는 SUBMITTED/IN_REVIEW/EVALUATED/REJECTED/CLOSED. 미지정 코드는
    중립(CLOSED) 팔레트로 안전 fallback. 라벨은 도메인이 한글화해 넘긴다(코드값 불변)."""
    pal = LIFECYCLE_BADGE.get(status_code, LIFECYCLE_BADGE["CLOSED"])
    return (
        f"<span style='display:inline-flex;align-items:center;padding:3px 11px;"
        f"border-radius:999px;font-size:12.5px;font-weight:600;line-height:1.4;"
        f"color:{pal['text']};background:{pal['bg']};"
        f"border:1px solid {pal['border']};white-space:nowrap;'>{escape(label)}</span>"
    )


def token(name: str) -> str:
    """토큰 값(색상)을 반환한다. 미정의 토큰은 그대로 돌려준다(임의 색 허용)."""
    return TOKENS.get(name, name)


# ---------------------------------------------------------------------------
# 손제작 라인 아이콘 글리프(단일 원천) — Feather/Lucide 계열: viewBox 24,
# stroke=currentColor, stroke-width 1.8, round cap/join. 두 툴바가 이 하나를 공유한다:
#   (1) 장식 타이틀 밴드 클러스터(`views/master/__init__::_TOOLBAR`) — 인라인 <svg> 로 렌더.
#   (2) 기능 아이콘 툴바(`.st-key-ms_iconbar`) — 아래 mask-image 로 같은 글리프를 칠한다
#       (st.button 클릭 계약은 그대로, Material 폰트 글리프만 이 SVG 라인 아이콘으로 교체).
# 값은 <svg> 안쪽 path 조각(래퍼·stroke 속성 제외)이라 두 소비 경로가 동일 룩을 낸다.
# 기존 5개(info/print/save/star/refresh)는 장식 클러스터에서 그대로 재사용, 신규 3개
# (globe/add/delete)는 동일 스타일로 신규 저작 — 섞여 보이지 않게 한다.
# ---------------------------------------------------------------------------
TOOLBAR_GLYPHS: dict[str, str] = {
    # ── 기존 재사용(장식 클러스터와 동일 path) ──
    "info": ("<circle cx='12' cy='12' r='9'/><line x1='12' y1='11' x2='12' y2='16'/>"
             "<line x1='12' y1='7.5' x2='12' y2='8'/>"),
    "print": ("<polyline points='6 9 6 3 18 3 18 9'/>"
              "<rect x='4' y='9' width='16' height='8' rx='1'/>"
              "<rect x='7' y='14' width='10' height='6'/>"),
    "save": ("<path d='M19 21H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h10l5 5v11a2 2 0 0 1-2 2z'/>"
             "<polyline points='17 21 17 13 8 13 8 21'/><polyline points='8 3 8 8 15 8'/>"),
    "star": ("<polygon points='12 3 14.9 8.9 21.5 9.8 16.7 14.4 17.9 20.9 12 17.8 6.1 20.9 "
             "7.3 14.4 2.5 9.8 9.1 8.9'/>"),
    "refresh": ("<polyline points='21 4 21 10 15 10'/>"
                "<path d='M19 13a7.5 7.5 0 1 1-1.8-6.2L21 10'/>"),
    # ── 신규 저작(동일 스타일 — globe/add(+)/delete(휴지통)) ──
    "globe": ("<circle cx='12' cy='12' r='9'/><line x1='3' y1='12' x2='21' y2='12'/>"
              "<path d='M12 3a14 14 0 0 1 3.6 9 14 14 0 0 1-3.6 9 14 14 0 0 1-3.6-9 "
              "14 14 0 0 1 3.6-9z'/>"),
    "add": "<line x1='12' y1='5' x2='12' y2='19'/><line x1='5' y1='12' x2='19' y2='12'/>",
    "delete": ("<polyline points='3 6 5 6 21 6'/>"
               "<path d='M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6'/>"
               "<path d='M10 6V4a2 2 0 0 1 2-2h0a2 2 0 0 1 2 2v2'/>"
               "<line x1='10' y1='11' x2='10' y2='17'/><line x1='14' y1='11' x2='14' y2='17'/>"),
}

# 기능 아이콘 툴바 슬롯(0..7, icon_toolbar_specs 순서와 정합) → 글리프 이름.
# 0 정보 · 1 globe · 2 추가 · 3 조회/새로고침(=refresh 재사용) · 4 삭제 · 5 인쇄 · 6 저장 · 7 즐겨찾기.
_ICONBAR_SLOT_GLYPHS: list[str] = [
    "info", "globe", "add", "refresh", "delete", "print", "save", "star",
]


def _glyph_data_uri(paths: str) -> str:
    """path 조각을 mask-image 용 data-URI(완전한 SVG)로 만든다.

    mask-image 는 소스의 알파를 마스크로 쓰므로(mask-mode: match-source→alpha) stroke 는
    불투명 색이면 충분하다(실제 색은 background-color 가 칠함). standalone 이미지라
    ``xmlns`` 가 필수다. ``quote`` 로 전부 퍼센트 인코딩해 ``#``·``<``·``>``·따옴표·공백을
    안전하게 데이터 URI 에 싣는다.
    """
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' "
        "stroke='#000' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'>"
        + paths + "</svg>"
    )
    return "data:image/svg+xml," + quote(svg, safe="")


def _iconbar_mask_css() -> str:
    """기능 아이콘 툴바(`.st-key-ms_iconbar`)의 Material 폰트 글리프를 손제작 SVG 라인
    아이콘으로 교체하는 CSS(시각 전용 — 클릭/키/disabled 계약 무변경).

    스코프: 항상 ``.st-key-ms_iconbar`` 컨테이너 하위로 한정하고, 슬롯은 고정 컬럼 순서
    (``st.columns([1]*8)``)의 ``div[data-testid="stColumn"]:nth-child(N)`` 로 지정한다
    (위젯 key 는 화면마다 다르므로 화면 독립적인 컬럼 위치로 매핑). Material 글리프
    (``stIconMaterial``)는 숨기고, 버튼의 ``::before`` 의사요소를 17×17 상자로 만들어
    ``mask-image``(글리프) + ``background-color``(흰색/비활성 시 흐림)로 칠한다.
    """
    parts = [
        # Material 폰트 글리프 숨김 — 대신 ::before 마스크 상자를 칠한다.
        '.st-key-ms_iconbar div.stButton button [data-testid="stIconMaterial"]'
        '{display:none!important;}',
        # 마스크 상자는 **절대 위치로 버튼 중앙에 고정**한다. 버튼은 flex 컨테이너이고
        # 빈 라벨 래퍼(≈19px)가 flex 형제로 남아, ::before 를 flex 항목으로 두면 30px 버튼을
        # 넘겨 flex-shrink 로 아이콘이 17px 미만으로 눌린다(라이브 측정 실증). 절대 위치는
        # flex 흐름에서 빠져 항상 17×17(.ms-tool svg 와 동일)로 렌더된다. pointer-events:none
        # 으로 클릭은 버튼이 받는다(클릭 계약 무변경).
        '.st-key-ms_iconbar div.stButton button{position:relative;}',
        '.st-key-ms_iconbar div.stButton button::before{content:"";position:absolute;'
        'top:50%;left:50%;width:17px;height:17px;transform:translate(-50%,-50%);'
        'pointer-events:none;background-color:#4a453d;'  # 중립 스트립 위 단색 라인 아이콘(ink-2)
        '-webkit-mask-repeat:no-repeat;mask-repeat:no-repeat;'
        '-webkit-mask-position:center;mask-position:center;'
        '-webkit-mask-size:contain;mask-size:contain;}',
        # shaded/disabled(globe·인쇄·즐겨찾기·N/A) — 흐리게(비활성 룩, ink-3 반투명).
        '.st-key-ms_iconbar div.stButton button:disabled::before'
        '{background-color:rgba(107,102,93,.5);}',
    ]
    for i, name in enumerate(_ICONBAR_SLOT_GLYPHS, start=1):
        uri = _glyph_data_uri(TOOLBAR_GLYPHS[name])
        parts.append(
            f'.st-key-ms_iconbar div[data-testid="stColumn"]:nth-child({i}) '
            f'div.stButton button::before'
            f'{{-webkit-mask-image:url("{uri}");mask-image:url("{uri}");}}'
        )
    return "".join(parts)


_ICONBAR_MASK_CSS: str = _iconbar_mask_css()


# ---------------------------------------------------------------------------
# 페이지 크롬 CSS — page_id 와 무관하게 버튼 역할 접미사로 스코프한다.
# 액션바 버튼 key 는 `{page_id}__save/__del/__add/__addg/__refresh` 규칙을 쓰므로
# `[class*="__save"]` 같은 부분일치 선택자로 모든 화면·패널을 한 번에 스타일링한다.
# ---------------------------------------------------------------------------
_PAGE_CSS = """
<style>
:root {
  --ms-canvas:#f4f2ee; --ms-surface:#FFFFFF; --ms-surface-2:#fbfaf8; --ms-surface-3:#f1eee7;
  --ms-line:#e6e2da; --ms-line-strong:#cfc8bd; --ms-ink:#1c1a17; --ms-ink-2:#4a453d; --ms-ink-3:#6b665d;
  --ms-navy:#c2410c; --ms-navy-hover:#a3350a; --ms-gold:#8a6212; --ms-gold-soft:#fdf3ec;
  --ms-band:#fbfaf8; --ms-band-hover:#f1eee8; /* 중립 액션 스트립(파랑 밴드 제거, ADOPTION_SPEC §0.4) */
  --ms-accent:#c2410c; --ms-accent-hover:#a3350a; --ms-accent-tint:#fdf3ec;
  --ms-mono:"IBM Plex Mono","Consolas","Menlo",monospace;
  --ms-info:#2f4d99; --ms-info-bg:#eef2fb; --ms-success:#2f6b45; --ms-success-bg:#eef5f0;
  --ms-warn:#8a6212; --ms-warn-bg:#fdf3e3; --ms-danger:#9c3232; --ms-danger-bg:#fbeeee;
}
/* §5 페이지 타이틀 크롬 — 파랑 밴드 제거(ADOPTION_SPEC 항목5). 제목 25px/600(-0.025em) +
   설명 13.5px. 브레드크럼은 상단 52px 헤더(modules/ui.py)가 소유하므로 본문에선 숨긴다.
   ms-head/ms-title/ms-mode 클래스명은 계약상 유지(선택자 하위호환). */
.ms-head { display:flex; flex-direction:column; gap:.15rem; margin:0 0 .35rem; }
.ms-crumb { display:none; }
.ms-band { display:flex; flex-direction:column; gap:.15rem; }
.ms-band-main { display:flex; align-items:center; gap:.6rem; min-width:0; }
.ms-band-ico { display:none; }  /* 파랑 밴드 리딩 아이콘 제거 */
.ms-title { font-size:25px; font-weight:600; color:var(--ms-ink); letter-spacing:-.025em; margin:0;
  line-height:1.2; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.ms-desc { font-size:13.5px; color:var(--ms-ink-2); margin:0; line-height:1.35; text-wrap:pretty; }
/* 밴드 우측 툴바(프로토타입 장식) — 파랑 밴드 제거로 미사용(정적 head 는 아이콘 미렌더). */
.ms-band-tools { display:flex; align-items:center; gap:.1rem; flex:0 0 auto; }
.ms-band-tools .ms-mode { margin-right:.4rem; }
.ms-tool { display:inline-flex; align-items:center; justify-content:center;
  width:30px; height:30px; border-radius:6px; color:var(--ms-ink-2); cursor:default;
  transition:background-color 120ms ease; }
.ms-tool svg { width:17px; height:17px; display:block; }
.ms-tool:hover { background:var(--ms-band-hover); }
/* 모드 배지 — 데이터 연결 신호 전용(점 색: 연결 success / 오류 danger / 샘플 중립) */
.ms-mode { display:inline-flex; align-items:center; gap:.4rem; padding:.28rem .6rem; border-radius:999px;
  background:var(--ms-surface-2); border:1px solid var(--ms-line-strong); font-size:.74rem; font-weight:600;
  color:var(--ms-ink-2); white-space:nowrap; }
.ms-mode .dot { width:.5rem; height:.5rem; border-radius:50%; flex:0 0 auto; }
.ms-mode.on   .dot { background:var(--ms-success); }
.ms-mode.off  .dot { background:var(--ms-danger); }
.ms-mode.samp .dot { background:var(--ms-ink-3); }
/* §6 필터바 */
[class*="__filter"] { background:var(--ms-surface-2); border:1px solid var(--ms-line); border-radius:8px;
  padding:.5rem .65rem; margin:.55rem 0 .1rem; }
[class*="__filter"] div[data-testid="stHorizontalBlock"] { align-items:flex-end; }
[class*="__filter"] label { font-size:.72rem !important; color:var(--ms-ink-2) !important; } /* ink-3→ink-2: 대비 (§2, WCAG) */
/* §7 액션바 */
[class*="__bar"] { margin:.15rem 0 .45rem; }
[class*="__bar"] div[data-testid="stHorizontalBlock"] { align-items:center; }
/* 액션바 버튼 공통 형태 — 색 규칙(§8)과 동일하게 role-key(`__save/__del/__add/__addg/
   __refresh`) 부분일치로 스코프한다(파일 상단 주석의 계약). 화면이 버튼을 `__bar`
   컨테이너로 감싸든(사용자·근무형태) 감싸지 않든(조직 3시트) 균일 적용된다.
   후손 셀렉터(> 아님): disabled+help 시 Streamlit 이 button 위에 stTooltipHoverTarget
   래퍼를 끼워 넣어 직계자식이 끊겨도 사이즈/radius/weight 를 유지한다. 액션바 stButton 은
   버튼을 하나만 담으므로 후손 매칭이 안전하다. `__del`_ok/_cancel(2단계 확인 바)·
   `__discard`(폐기 바)는 별도 컴포넌트이므로 `:not([class*="__del_"])` 로 제외해 건드리지 않는다. */
/* 지오메트리는 밴드 툴(.st-key-ms_band_live) 과 동일 규격으로 맞춘다(콤팩트 툴 계열
   통일 — 조직 관리 인페이지 액션바가 남은 유일한 실사용처, 2026-07-26). 색상 규칙은
   아래 §8 원 규칙(주요/보조/위험)을 그대로 유지하며 크기·모양만 조정한다. */
[class*="__save"] div.stButton button,
[class*="__del"]:not([class*="__del_"]) div.stButton button,
[class*="__add"] div.stButton button,
[class*="__refresh"] div.stButton button { min-height:1.8rem; height:1.8rem; padding:0 .58rem; border-radius:4px;
  font-size:.78rem; font-weight:600; white-space:nowrap; gap:.26rem; line-height:1; }
[class*="__save"] div.stButton button [data-testid="stIconMaterial"],
[class*="__del"]:not([class*="__del_"]) div.stButton button [data-testid="stIconMaterial"],
[class*="__add"] div.stButton button [data-testid="stIconMaterial"],
[class*="__refresh"] div.stButton button [data-testid="stIconMaterial"] { font-size:15px; }
/* §8 주요(저장) — 앱 네이비, 검정 금지 */
[class*="__save"] button[kind="primary"] { background:var(--ms-navy) !important; border:1px solid var(--ms-navy) !important; color:#FFF !important; }
[class*="__save"] button[kind="primary"]:hover:not(:disabled) { background:var(--ms-navy-hover) !important; border-color:var(--ms-navy-hover) !important; }
[class*="__save"] button[kind="primary"]:disabled { background:#EDEAE3 !important; border-color:#E7E3DB !important; color:var(--ms-ink-3) !important; }
/* §8 보조(행 추가·그룹·새로고침) — 중립 outline */
[class*="__add"] button, [class*="__addg"] button, [class*="__refresh"] button {
  background:var(--ms-surface) !important; border:1px solid var(--ms-line-strong) !important; color:var(--ms-ink) !important; }
[class*="__add"] button:hover:not(:disabled), [class*="__addg"] button:hover:not(:disabled), [class*="__refresh"] button:hover:not(:disabled) {
  border-color:var(--ms-gold) !important; background:#F1EEE9 !important; }
/* §8 위험(삭제) — outline, 선택 0이면 disabled */
[class*="__del"] button { background:var(--ms-surface) !important; border:1px solid #E0CFC9 !important; color:var(--ms-danger) !important; }
[class*="__del"] button:hover:not(:disabled) { background:var(--ms-danger-bg) !important; border-color:#C77B6B !important; }
[class*="__del"] button:disabled { color:var(--ms-ink-3) !important; border-color:#E7E3DB !important; background:var(--ms-surface) !important; }
/* 포커스 링(키보드) */
[class*="__bar"] button:focus-visible { outline:2px solid var(--ms-navy) !important; outline-offset:1px; }
/* ── 라이브 액션 밴드(사용자 관리 파일럿, master_screen_head(toolbar=True)) ──
   파랑 타이틀 밴드 안에 실제 액션 버튼(＋추가·삭제·저장·새로고침)을 놓는다.
   밴드는 st.container(key='ms_band_live') → 컬럼([제목|배지+장식|추가|삭제|저장|새로고침]).
   버튼 위젯 key 는 인페이지 액션바와 동일한 {page}__add/__del/__save/__refresh 규칙이라
   전역 §8 색 규칙이 함께 매칭되지만, 아래 `.st-key-ms_band_live` 접두 규칙이 더 높은/
   같은 특이도 + 뒤 소스순서로 이 밴드 안에서만 이긴다. 다른 화면의 인페이지 액션바
   (조직·근무형태)는 이 클래스가 없어 영향받지 않는다. 이 블록은 §8 규칙 뒤에 둔다. */
/* 상단 52px 헤더(modules/ui.py app_header)가 MODULE / SCREEN 모노 브레드크럼을 소유한다
   (ADOPTION_SPEC 항목4). 종전 '.crumb 숨김 + 빈 헤더 접기'는 파랑 밴드가 브레드크럼을
   중복 표기하던 시절의 정리였고, 밴드 제거 후에는 헤더가 유일한 브레드크럼이므로 숨기지
   않는다. 헤더 스킨(52px·배경·pill·아이콘)은 modules/ui.py _SHELL_CSS 가 소유. */
/* 중립 액션 스트립 — 본문 스크롤 시 상단 고정(sticky). 파랑 밴드 제거로 배경은 중립
   (surface-2)이며 아래로 지나가는 그리드가 비치지 않게 solid + 하단 헤어라인. */
div[data-testid="stLayoutWrapper"]:has(> .st-key-ms_band_live),
div[data-testid="stLayoutWrapper"]:has(> .st-key-ms_iconband) { display:contents; }
.st-key-ms_band_live, .st-key-ms_iconband { background:var(--ms-surface-2);
  border:1px solid var(--ms-line); border-radius:8px;
  padding:.24rem .5rem .24rem .85rem; min-height:44px;
  position:sticky; top:0; z-index:30; }
.st-key-ms_band_live div[data-testid="stHorizontalBlock"] { align-items:center; }
/* ── KPtech 아이콘 전용 툴바(파일럿: 사용자 관리·근무표 편성, master_screen_head("icons")) ──
   좌: 제목+모드배지 / 우: 8개 정사각(32×32) 흰 아이콘. 라벨 없음·tooltip 로 기능명 노출.
   컨테이너 key 를 pill 밴드와 분리(ms_iconband/ms_iconbar)해 pill CSS 와 간섭하지 않는다. */
.st-key-ms_iconband div[data-testid="stHorizontalBlock"] { align-items:center; }
.st-key-ms_iconband .ms-band-main { min-width:0; }
/* 모드 배지는 밴드 우측(아이콘 툴바 바로 왼쪽)에 둔다 — pill/static 변종과 동일한 우측
   통일(2026-07-27 사용자 결정). 자체 컬럼에서 우측 정렬해 아이콘 클러스터에 붙인다
   (pill 의 .ms-band-tools .ms-mode margin-right 와 동일한 리듬). */
.st-key-ms_iconband .ms-band-badge { display:flex; justify-content:flex-end; margin-right:.4rem; }
/* 아이콘 영역·배지 컬럼은 콘텐츠 폭으로 고정하고 제목 컬럼이 대신 줄어들게 한다
   (min-width:0 + ms-title ellipsis). 좁은 폭(1024)에서 아이콘이 비율 컬럼에 눌려 겹치던
   문제(음수 gap)를 없앤다 — 아이콘은 항상 30px 슬롯(.ms-tool 과 동일), 제목은 말줄임. */
div[data-testid="stColumn"]:has(> div .st-key-ms_iconbar) { flex:0 0 auto !important; width:auto !important; }
div[data-testid="stColumn"]:has(> div .ms-band-badge) { flex:0 0 auto !important; width:auto !important; }
div[data-testid="stColumn"]:has(> div .ms-band-main) { min-width:0 !important; }
.st-key-ms_iconbar div[data-testid="stColumn"] {
  flex:0 0 34px !important; width:34px !important; min-width:34px !important; }
/* 기능 툴바 아이콘 간격 — 각 아이콘 버튼이 서로 붙지 않고 개별적으로 분리돼 보이도록
   벌린다(참고 이미지 방향, 2026-07-27 사용자 승인). st.columns 의 기본 컬럼 gap(emotion
   클래스, 라이브 측정 8.4px)은 !important 로 주입돼 특이도만으로는 이기지 못하므로 여기서도
   !important 로 강제한다. 과거 tight-pack(.1rem, 거의 붙음)을 .4rem(≈6.4px)로 넓혀 버튼이
   개별로 읽히게 한다(레이아웃/간격만 변경 — 슬롯 수·글리프·클릭 계약 무변경). */
.st-key-ms_iconbar div[data-testid="stHorizontalBlock"] { gap:.4rem !important; }
.st-key-ms_iconbar div.stButton { display:flex; justify-content:center; }
/* 기능 아이콘 버튼 — 중립 스트립 위 단색 라인 아이콘(파랑 밴드 제거). 히트영역 32px,
   시각 30px, hover #f1eee8(=--ms-band-hover). 아이콘색 ink-2, hover 시 ink. */
.st-key-ms_iconbar div.stButton button {
  width:32px !important; min-width:32px !important; height:32px !important; min-height:32px !important;
  padding:0 !important; border-radius:6px !important;
  background:transparent !important; border:none !important; box-shadow:none !important;
  color:var(--ms-ink-2) !important; transition:background-color 120ms ease !important; }
.st-key-ms_iconbar div.stButton button [data-testid="stIconMaterial"] {
  font-size:17px !important; color:var(--ms-ink-2) !important;
  font-variation-settings:'FILL' 0, 'wght' 400 !important; }
.st-key-ms_iconbar div.stButton button:hover:not(:disabled) {
  background:var(--ms-band-hover) !important; border:none !important; color:var(--ms-ink) !important; }
/* shaded(disabled): globe·인쇄·즐겨찾기(Phase2)·N/A 기능 — 아이콘을 흐리게(디스에이블 룩) */
.st-key-ms_iconbar div.stButton button:disabled { background:transparent !important; }
.st-key-ms_iconbar div.stButton button:disabled [data-testid="stIconMaterial"] {
  color:var(--ms-ink-3) !important; opacity:.45 !important; }
.st-key-ms_iconbar div.stButton button:focus-visible { outline:2px solid var(--ms-accent) !important; outline-offset:1px; }
/* 본문 브레드크럼(.ms-crumb)은 상단 52px 헤더가 소유하므로 숨긴다(항목4). 파랑 밴드
   제거로 ms-head 는 이제 25px 제목 크롬 컨테이너이며, 종전의 '밴드 없는 ms-head 접기'
   규칙(.ms-head:not(:has(.ms-band)))은 제목까지 숨겨 제거한다. */
.ms-crumb { display:none !important; }
.st-key-ms_band_live .ms-band-main { min-width:0; }
.st-key-ms_band_live .ms-band-tools { justify-content:flex-end; }
/* 콤팩트 액션 툴(밴드 표준) — 아이콘+짧은 라벨의 낮은 툴 버튼. 라벨 폭에 맞춰
   (width="content") 오밀조밀 클러스터하고, 각 액션 컬럼 안에서 우측 정렬해 큰 여백
   없이 붙인다. '큰 버튼' 인상을 없애는 게 핵심 — 높이·패딩·라운드를 줄인다.
   후손 셀렉터(div.stButton button)로 disabled+help 툴팁 래퍼가 껴도 유지한다. */
.st-key-ms_band_live div.stButton { display:flex; justify-content:flex-end; }
/* 지오메트리는 !important 로 강제한다 — 전역 §8 액션 규칙(특히 삭제
   `[class*="__del"]:not([class*="__del_"])` 는 :not 로 특이도가 더 높다)이 이 밴드 안에서도
   매칭돼 높이/라운드를 덮어써, 삭제만 큰 버튼으로 튀는 것을 막는다(밴드 스코프 한정). */
.st-key-ms_band_live div.stButton button { min-height:1.8rem !important; height:1.8rem !important;
  min-width:0 !important; padding:0 .58rem !important; border-radius:6px !important;
  font-size:.78rem !important; font-weight:600 !important; white-space:nowrap; gap:.26rem; line-height:1;
  background:var(--ms-surface) !important; border:1px solid var(--ms-line-strong) !important;
  color:var(--ms-ink) !important; }
.st-key-ms_band_live div.stButton button [data-testid="stIconMaterial"] { font-size:15px !important; }
.st-key-ms_band_live div.stButton button:hover:not(:disabled) {
  background:var(--ms-band-hover) !important; border-color:var(--ms-accent) !important; }
/* 저장(primary): 활성 시 오렌지 액센트 배경·흰 글자로 강조(단일 액센트) */
.st-key-ms_band_live [class*="__save"] button[kind="primary"] {
  background:var(--ms-accent) !important; border-color:var(--ms-accent) !important; color:#FFFFFF !important; }
.st-key-ms_band_live [class*="__save"] button[kind="primary"]:hover:not(:disabled) {
  background:var(--ms-accent-hover) !important; border-color:var(--ms-accent-hover) !important; }
/* 비활성(저장·삭제 등): 흐리게 — 클릭 불가 어포던스 */
.st-key-ms_band_live div.stButton button:disabled {
  background:#EDEAE3 !important; border-color:#E7E3DB !important;
  color:var(--ms-ink-3) !important; }
/* 포커스 링(키보드) — 밴드 대비 흰 링 */
.st-key-ms_band_live button:focus-visible { outline:2px solid var(--ms-accent) !important; outline-offset:1px; }
/* 조직 좌/우 패널 제목 */
.ms-panel { font-size:.94rem; font-weight:700; color:var(--ms-ink); margin:.2rem 0 .1rem; }
.ms-panel small { font-weight:500; color:var(--ms-ink-2); }
/* §20 상태 스트립(푸터) */
.ms-count { font-size:.76rem; color:var(--ms-ink-2); margin:.4rem 0 0; }
.ms-count b { color:var(--ms-ink); font-weight:600; }
/* §21/§22 배너 — 좌측 상태 바 + 아이콘 + 텍스트(색만으로 구분 금지) */
.ms-banner { display:flex; align-items:flex-start; gap:.5rem; padding:.55rem .7rem; border-radius:8px;
  border:1px solid var(--ms-line); margin:.35rem 0; font-size:.82rem; line-height:1.4; }
.ms-banner .glyph { font-weight:700; flex:0 0 auto; }
.ms-banner.info    { background:var(--ms-info-bg);    border-left:3px solid var(--ms-info);    color:var(--ms-ink); }
.ms-banner.success { background:var(--ms-success-bg); border-left:3px solid var(--ms-success); color:var(--ms-ink); }
.ms-banner.warn    { background:var(--ms-warn-bg);    border-left:3px solid var(--ms-warn);    color:var(--ms-ink); }
.ms-banner.danger  { background:var(--ms-danger-bg);  border-left:3px solid var(--ms-danger);  color:var(--ms-ink); }
.ms-banner .keys { margin-top:.25rem; display:flex; flex-wrap:wrap; gap:.3rem; }
/* 배지/칩 (텍스트 동반, 이모지 금지) */
.ms-chip { display:inline-flex; align-items:center; gap:.25rem; padding:.05rem .4rem; border-radius:4px;
  font-size:.68rem; font-weight:600; line-height:1.4; white-space:nowrap; }
.ms-chip.new    { background:var(--ms-info-bg);    color:var(--ms-info);    border:1px solid #C9DCEE; }
.ms-chip.del    { background:var(--ms-danger-bg);  color:var(--ms-danger);  border:1px solid #E7CDC7; }
.ms-chip.ok     { background:var(--ms-success-bg); color:var(--ms-success); border:1px solid #C7DfCF; }
.ms-chip.warn   { background:var(--ms-warn-bg);    color:var(--ms-warn);    border:1px solid #E7D9A8; }
.ms-chip.mute   { background:var(--ms-surface-3);  color:var(--ms-ink-2);   border:1px solid var(--ms-line); } /* ink-3→ink-2: surface-3 위 대비 2.89→5.76 (§2) */
.ms-chip.lock   { background:var(--ms-surface-3);  color:var(--ms-ink-2);   border:1px solid var(--ms-line-strong); }
/* readiness 배지 — 모드 배지와 분리 */
.ms-ready { display:inline-flex; align-items:center; gap:.35rem; padding:.22rem .55rem; border-radius:6px;
  font-size:.72rem; font-weight:600; }
.ms-ready.ready { background:var(--ms-success-bg); color:var(--ms-success); }
.ms-ready.not   { background:var(--ms-warn-bg);    color:var(--ms-warn); }
.ms-ready.err   { background:var(--ms-danger-bg);  color:var(--ms-danger); }
/* ===================================================================== */
/* 조직 3시트 [그룹][부서][조] 공유 레이아웃 (Wave2a)                       */
/* 시트는 org controller 가 st.columns(3) + st.container(key=f"{page_id}__sheet")  */
/* 로 렌더한다. 아래 규칙은 그 컨테이너 key(.st-key-*__sheet)와              */
/* 드릴다운 컨텍스트 스트립(.ms-ctx)·시트 헤더(.ms-sheet-*)·잠김 빈상태       */
/* (.ms-locked)를 스타일링한다. 사용자·근무형태 화면은 이 클래스를 쓰지 않으므로 */
/* 영향받지 않는다.                                                        */
/* 드릴다운 컨텍스트 스트립 — 그룹 › 부서 › 조 */
.ms-ctx { display:flex; align-items:center; gap:.5rem; flex-wrap:wrap; background:var(--ms-surface-2);
  border:1px solid var(--ms-line); border-radius:8px; padding:.42rem .7rem; margin:.2rem 0 .55rem;
  font-size:.78rem; color:var(--ms-ink-2); }
.ms-ctx b { color:var(--ms-ink); font-weight:700; }
.ms-ctx .pin { color:var(--ms-navy); font-weight:700; }
.ms-ctx .arw { color:var(--ms-ink-3); }
.ms-ctx .none { color:var(--ms-ink-2); font-weight:600; } /* ink-3→ink-2: 대비 (§2, WCAG) */
/* 시트 카드 — 컨테이너 key(.st-key-*__sheet)에 카드 외형을 입힌다 */
[class*="__sheet"] { background:var(--ms-surface); border:1px solid var(--ms-line-strong);
  border-radius:10px; padding:.2rem .1rem .1rem; box-shadow:0 1px 0 rgba(0,0,0,.02); }
[class*="__sheet"].ms-sheet-locked { background:var(--ms-surface-2); border-style:dashed; }
/* 시트 헤더(제목 + 건수 + 드릴다운 컨텍스트 칩) */
.ms-sheet-head { display:flex; align-items:center; gap:.5rem; padding:.55rem .7rem .5rem; }
.ms-sheet-head .t { font-size:.92rem; font-weight:700; color:var(--ms-ink); }
.ms-sheet-head .cnt { font-size:.7rem; font-weight:600; color:var(--ms-ink-2); background:var(--ms-surface-3);
  border:1px solid var(--ms-line); border-radius:999px; padding:.05rem .5rem; }
.ms-sheet-head .ctx { margin-left:auto; font-size:.7rem; font-weight:600; color:var(--ms-navy);
  background:#E5EAF2; border:1px solid #C6D2E4; border-radius:6px; padding:.1rem .45rem;
  max-width:60%; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.ms-sheet-head .lock { margin-left:auto; font-size:.7rem; font-weight:600; color:var(--ms-ink-2); /* ink-3→ink-2: 대비 (§2, WCAG) */
  display:inline-flex; align-items:center; gap:.3rem; }
/* 잠김/빈 상태 — 상위 미선택 시 하위 시트 (§ '그룹을 먼저 선택하세요') */
.ms-locked { display:flex; flex-direction:column; align-items:center; justify-content:center;
  gap:.5rem; text-align:center; padding:2.6rem 1rem; min-height:220px; color:var(--ms-ink-3); }
.ms-locked .glyph { font-size:1.4rem; line-height:1; color:var(--ms-line-strong); }
.ms-locked .t { font-size:.82rem; font-weight:700; color:var(--ms-ink-2); }
.ms-locked .s { font-size:.74rem; color:var(--ms-ink-2); line-height:1.45; } /* ink-3→ink-2: 대비 (§2, WCAG) */
/* 빈 상태(정상 empty, 오류 아님) — 표 본문 자리 */
.ms-empty { display:flex; flex-direction:column; align-items:center; justify-content:center;
  gap:.4rem; text-align:center; padding:2rem 1rem; color:var(--ms-ink-3); }
.ms-empty .t { font-size:.82rem; font-weight:600; color:var(--ms-ink-2); }
.ms-empty .s { font-size:.74rem; color:var(--ms-ink-2); } /* ink-3→ink-2: 콘텐츠 배경 위 대비 2.9→5.76 (§2, WCAG) */
/* ≤1100px: 3시트 세로 스택(드릴다운 연동 유지). st.columns 를 감싼 horizontal block 대상. */
@media (max-width:1100px){
  div[data-testid="stHorizontalBlock"]:has([class*="__sheet"]) { flex-direction:column; }
  div[data-testid="stHorizontalBlock"]:has([class*="__sheet"]) > div[data-testid="stColumn"]{
    width:100% !important; flex:1 1 100% !important; }
}
</style>
"""


def inject_page_styles() -> None:
    """페이지 크롬 CSS 를 1회 주입한다(화면 render 시작에서 호출)."""
    st.markdown(_PAGE_CSS, unsafe_allow_html=True)
    # 기능 아이콘 툴바의 Material 글리프 → 손제작 SVG 라인 아이콘(mask-image) 교체.
    # 별도 <style> 로 원 규칙 뒤에 두어 stIconMaterial 숨김이 소스순서로 확실히 이긴다.
    st.markdown(f"<style>{_ICONBAR_MASK_CSS}</style>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# §9~§16, 상태 매트릭스 — 그리드 내부(iframe) custom_css.
# 배경 우선순위는 master_row_class_rules 의 상호배타 규칙 + 아래 색으로 함께 보장한다.
# ---------------------------------------------------------------------------
GRID_CSS: dict[str, dict] = {
    ".ag-root-wrapper": {"border": "1px solid " + TOKENS["line-strong"], "border-radius": "8px"},
    # §1-E: 표 헤더 배경 없음 + 하단 1px #cfc8bd(line-strong). 공용(3화면 공유) — 7단계에서
    # 승인된 예외로 surface-2 배경을 제거해 헤더가 흰 표 본문과 자연스레 이어지게 한다.
    ".ag-header": {"background": "transparent", "border-bottom": "1px solid " + TOKENS["line-strong"]},
    ".ag-header-cell": {"border-right": "1px solid rgba(0,0,0,.08)"},
    ".ag-header-cell-label": {"justify-content": "center", "font-size": "12.5px",
                              "font-weight": "600", "color": TOKENS["ink-2"]},
    # 기본 셀: 테두리·타이포는 편집 중에도 유지. 레이아웃(flex)만 편집셀에서 제외한다.
    ".ag-cell": {
        "border-right": "1px solid rgba(0,0,0,.06)",
        "line-height": "normal", "font-size": "13px", "color": TOKENS["ink"],
    },
    # 표시(비편집) 셀만 flex 정렬 — 편집 중(.ag-cell-inline-editing)엔 flex 를 걸지 않아
    # 편집 input 이 클리핑되지 않는다(F1). 정렬 클래스(md-c-*)는 이 flex 위에서 동작한다.
    ".ag-cell:not(.ag-cell-inline-editing)": {"display": "flex", "align-items": "center"},
    ".ag-row": {"border-bottom": "1px solid " + TOKENS["line"]},
    ".ag-row-hover": {"background": "#F1EFEA"},
    # 정렬 클래스
    ".md-c-left": {"justify-content": "flex-start", "padding-left": "10px"},
    ".md-c-center": {"justify-content": "center", "padding-left": "0", "padding-right": "0"},
    ".ms-num": {"font-variant-numeric": "tabular-nums"},
    # 첫 열 액션(선택 체크박스 / − 제거 버튼)
    ".md-act": {"display": "flex", "align-items": "center", "justify-content": "center",
                "width": "100%", "height": "100%"},
    ".md-act-cb": {"cursor": "pointer", "margin": "0", "width": "16px", "height": "16px"},
    # §8 클릭영역 — 시각 20px, 히트영역 32px(투명 패딩)
    ".md-act-rm": {
        "width": "20px", "height": "20px", "padding": "0", "line-height": "1",
        "border": "1px solid #E0CFC9", "border-radius": "4px",
        "background": TOKENS["surface"], "color": TOKENS["danger"], "cursor": "pointer",
        "font-size": "15px", "font-weight": "700",
        "box-shadow": "0 0 0 6px transparent", "outline-offset": "6px",
    },
    ".md-act-rm:hover": {"background": TOKENS["danger-bg"], "border-color": "#C77B6B"},
    # ---- native bool 체크박스(cellDataType='boolean') — accent=테마 primaryColor(navy) ----
    # JsCode 없이 ag-grid 자체 렌더러가 전 행 일관 체크박스를 그린다(배포 3.14 회귀 방지).
    # 편집 가능 셀은 포인터, 보호/비활성 행은 흐림으로 읽기전용 어포던스(상태 cascade 와 정합).
    ".ag-checkbox-input-wrapper": {"cursor": "pointer"},
    ".ms-row-inactive .ag-checkbox-input-wrapper, "
    ".ms-row-protected .ag-checkbox-input-wrapper": {"opacity": ".5", "cursor": "default"},
    # ---- 행 상태 배경(상호 배타, 우선순위: error>delete>new>inactive>selected) ----
    # 합성 규칙(#5/#6): 배경은 셀(.ag-cell)에, 좌측 상태 바는 행(.ag-row)에 둔다. 상태 바와
    # 셀 box-shadow(dirty/error)가 서로 다른 요소를 써 box-shadow 슬롯이 겹치지 않으므로,
    # 행 상태와 셀 dirty/error 신호가 동시에 사라지지 않고 함께 유지된다.
    ".ms-row-selected .ag-cell": {"background": TOKENS["selected-bg"] + " !important"},
    # 비활성/보호 행 본문: 상태 배경(surface-3) 위에서도 본문 대비 ≥4.5:1 을 유지해야 하므로
    # 가장 옅은 ink-3(surface-3 위 2.89:1, 선택 틴트 위 2.87:1 — §2 위반)이 아니라 대응 진한색
    # ink-2(surface-3 위 5.76:1, 선택 틴트 위 5.70:1)를 쓴다. '미사용/퇴직/보호' 배지로 상태를
    # 이중부호화하므로 톤을 낮추되 글자는 읽힌다(§2 본문 대비·색만으로 상태표현 금지 동시 충족).
    ".ms-row-inactive .ag-cell": {"background": TOKENS["surface-3"] + " !important",
                                  "color": TOKENS["ink-2"] + " !important"},
    ".ms-row-new .ag-cell": {"background": TOKENS["info-bg"] + " !important"},
    ".ms-row-delete .ag-cell": {"background": TOKENS["danger-bg"] + " !important"},
    ".ms-row-error .ag-cell": {"background": TOKENS["danger-bg"] + " !important"},
    # §25 드릴다운 활성(조직) — 신규와 물리적으로 구분(네이비 틴트 + 우측 칩)
    ".ms-row-linked .ag-cell": {"background": "rgba(30,58,110,.10) !important"},
    # 좌측 상태 바(행 요소) — error/delete/new 상호배타. 조직 그룹행(.ms-group-row)과 동일 패턴.
    ".ag-row.ms-row-new": {"box-shadow": "inset 3px 0 " + TOKENS["info"]},
    ".ag-row.ms-row-delete": {"box-shadow": "inset 3px 0 " + TOKENS["danger"]},
    ".ag-row.ms-row-error": {"box-shadow": "inset 3px 0 " + TOKENS["danger"]},
    # ---- 보호행/읽기전용 어포던스(항상 유지 신호 — 상태 배경 위에 겹침) ----
    # 보호행: 선택/삭제 불가. 상태색을 덮지 않게 배경 대신 커서·액션열 흐림으로 표식한다.
    ".ms-row-protected .ag-cell": {"cursor": "default"},
    ".ms-row-protected .md-act": {"opacity": ".5"},
    # 읽기전용 셀: 편집 불가 어포던스(중립 틴트 + 기본 커서). 상태 행 배경(!important)이 우선.
    ".ms-cell-readonly": {"background": TOKENS["surface-2"], "cursor": "default",
                          "color": TOKENS["ink-2"]},
    # ---- 셀 상태(행 배경/좌측 바 위에 겹침 — dirty/error 가 함께 유지) ----
    ".ms-cell-error": {"box-shadow": "inset 0 0 0 1.5px " + TOKENS["danger"], "background": "#FFF6F4"},
    ".ms-cell-dirty": {"box-shadow": "inset 2px 0 " + TOKENS["warn"]},
    # 드롭다운 셀 ▾ 표식(선택형임을 상시 노출).
    # 주의: .ag-cell 은 AG Grid 가 position:absolute 로 배치하므로 여기서 position 을
    # 재지정하면 안 된다(relative 지정 시 셀이 flow 로 떨어져 이후 컬럼 전체가 행 아래로
    # 밀리는 레이아웃 붕괴 — 2026-07-25 사용자 관리 화면 실증). ::after 앵커는 이미
    # positioned 인 .ag-cell 에 그대로 걸린다.
    ".ms-cell-select::after": {"content": "'\\25BE'", "position": "absolute", "right": "8px",
                               "color": TOKENS["ink-3"], "font-size": "10px", "pointer-events": "none"},
    # ---- 그리드 내부 칩(cellRenderer HTML 용) — iframe 은 --ms-* var 를 못 보므로 리터럴 색 ----
    # 페이지 크롬 .ms-chip 과 시각이 일치하도록 동일 팔레트. 색+텍스트 이중부호화(이모지 금지).
    ".ms-chip": {"display": "inline-flex", "align-items": "center", "gap": "3px",
                 "padding": "1px 7px", "border-radius": "5px", "font-size": "10.5px",
                 "font-weight": "600", "line-height": "1.5", "white-space": "nowrap"},
    ".ms-chip.new": {"background": TOKENS["info-bg"], "color": TOKENS["info"], "border": "1px solid #C9DCEE"},
    ".ms-chip.del": {"background": TOKENS["danger-bg"], "color": TOKENS["danger"], "border": "1px solid #E7CDC7"},
    ".ms-chip.ok": {"background": TOKENS["success-bg"], "color": TOKENS["success"], "border": "1px solid #C7DFCF"},
    ".ms-chip.warn": {"background": TOKENS["warn-bg"], "color": TOKENS["warn"], "border": "1px solid #E7D9A8"},
    # mute 칩: surface-3 배경 위 ink-3 은 2.89:1 로 §2(보조 ≥3:1) 미만 → 대응 진한 ink-2(5.76:1).
    ".ms-chip.mute": {"background": TOKENS["surface-3"], "color": TOKENS["ink-2"], "border": "1px solid " + TOKENS["line"]},
    ".ms-chip.lock": {"background": TOKENS["surface-3"], "color": TOKENS["ink-2"], "border": "1px solid " + TOKENS["line-strong"]},
    # ---- 렌더러 상태 배지(행 상태색 인지) — 인라인 #FFFFFF 배경 대신 이 class 사용 ----
    # 배경 transparent 로 행 상태 배경(선택/신규/삭제/오류)을 그대로 상속하고, 색/테두리는
    # 렌더러가 element.style.color 한 번만 지정한다(테두리 currentColor). 색+텍스트 이중부호화.
    ".ms-badge": {"display": "inline-flex", "align-items": "center", "gap": "3px",
                  "padding": "0 5px", "border-radius": "4px", "font-size": "11px",
                  "font-weight": "600", "line-height": "1.5", "white-space": "nowrap",
                  "background": "transparent", "border": "1px solid currentColor"},
    # ---- 조직 전용(기존 자산 계승) ----
    ".ms-group-row": {"background": TOKENS["gold-soft"] + " !important", "font-weight": "700",
                      "box-shadow": "inset 3px 0 " + TOKENS["gold"]},
    ".ms-group-row .ag-cell": {"color": TOKENS["ink"]},
    ".ms-indent": {"padding-left": "26px !important"},
    ".ms-unit-shift": {"background": "rgba(30,58,110,.10) !important", "color": TOKENS["navy"],
                       "font-weight": "700", "border-radius": "4px", "justify-content": "center"},
    ".ms-unit-general": {"background": "rgba(61,58,52,.08) !important", "color": "#3D3A34",
                         "font-weight": "700", "border-radius": "4px", "justify-content": "center"},
    # 포커스 링
    ".ag-cell-focus": {"outline": "2px solid " + TOKENS["navy"] + " !important", "outline-offset": "-2px"},
}


# ---------------------------------------------------------------------------
# rowClassRules / cellClassRules 빌더
# ---------------------------------------------------------------------------
# 그리드 표현식은 (data,node,...) 스코프만 참조 가능 — 헬퍼 함수를 인라인한다.
_HAS_ERROR = "(data._error != null && data._error !== '' && data._error !== '{}')"
_IS_DELETE = "(data._delete === '1' || data._delete === 1)"
_IS_NEW = "(data._row_state === 'new')"
_IS_INACTIVE = "(data._inactive === '1' || data._inactive === 1)"
_IS_SELECTED = "(data._sel === true || data._sel === 'true' || data._sel === 1)"
_IS_LINKED = "(data._linked === '1' || data._linked === 1)"


def _guarded(cond: str, higher: list[str]) -> str:
    """상위 우선순위 조건이 모두 거짓일 때만 참이 되는 상호배타 표현식."""
    if not higher:
        return cond
    negations = " && ".join(f"!{h}" for h in higher)
    return f"{cond} && {negations}"


def master_row_class_rules(*, include_group: bool = False, include_linked: bool = False) -> dict:
    """상태 매트릭스(부록)의 배경 우선순위를 상호배타 rowClassRules 로 만든다.

    우선순위: error > delete_pending > new > inactive > selected > (zebra).
    ``_dirty``/``_protected`` 등 항상 유지 신호는 배경 위에 겹치므로 여기서 배제하지 않는다.
    조직 화면은 ``include_group``/``include_linked`` 로 그룹행·드릴다운 규칙을 켠다.
    """
    chain = [
        ("ms-row-error", _HAS_ERROR),
        ("ms-row-delete", _IS_DELETE),
        ("ms-row-new", _IS_NEW),
        ("ms-row-inactive", _IS_INACTIVE),
        ("ms-row-selected", _IS_SELECTED),
    ]
    rules: dict[str, str] = {}
    higher: list[str] = []
    for cls, cond in chain:
        rules[cls] = _guarded(cond, higher)
        higher.append(cond)
    if include_linked:
        # 드릴다운 활성은 신규/선택과 시각적으로 구분되는 별도 신호(네이비 틴트).
        rules["ms-row-linked"] = _guarded(_IS_LINKED, [_HAS_ERROR, _IS_DELETE, _IS_NEW])
    if include_group:
        rules["ms-group-row"] = "data._row_state === 'group'"
    return rules


def cell_error_rule(field: str) -> dict:
    """해당 필드가 ``_error`` JSON 에 포함될 때 셀 오류 테두리를 켜는 cellClassRules."""
    needle = '"' + field.replace('"', '\\"') + '"'
    return {"ms-cell-error": f"data._error && data._error.indexOf('{needle}') >= 0"}


def cell_dirty_rule(field: str) -> dict:
    """해당 필드가 ``_dirty_fields`` 에 포함될 때 변경 인셋을 켜는 cellClassRules."""
    needle = '"' + field.replace('"', '\\"') + '"'
    return {"ms-cell-dirty": f"data._dirty_fields && data._dirty_fields.indexOf('{needle}') >= 0"}


SELECT_CELL_RULE: dict = {"ms-cell-select": "true"}
"""드롭다운(선택형) 셀에 ▾ 표식을 상시 노출하는 cellClassRules."""


# ---------------------------------------------------------------------------
# HTML 조각 헬퍼 (배지·배너·모드/readiness) — 색+텍스트 이중 부호화
# ---------------------------------------------------------------------------
def chip_html(text: str, kind: str = "mute") -> str:
    """상태 칩. kind: new|del|ok|warn|mute|lock. 항상 텍스트 라벨을 동반한다."""
    return f"<span class='ms-chip {escape(kind)}'>{escape(text)}</span>"


_BANNER_GLYPH = {"info": "•", "success": "✔", "warn": "⚠", "danger": "✕"}


def banner_html(kind: str, text: str, extra: str = "") -> str:
    """표 위 결과/상태 배너 HTML. kind: info|success|warn|danger.

    좌측 상태 바 + 텍스트 글리프(원색 픽토그램 아님) + 텍스트. ``extra`` 는 키 칩 등
    추가 HTML(신뢰된 조각)을 배너 하단에 붙인다.
    """
    glyph = _BANNER_GLYPH.get(kind, "•")
    body = f"<div><div>{escape(text)}</div>{extra}</div>" if extra else f"<div>{escape(text)}</div>"
    return f"<div class='ms-banner {escape(kind)}'><span class='glyph'>{glyph}</span>{body}</div>"


def banner(kind: str, text: str, extra: str = "") -> None:
    """``banner_html`` 을 렌더한다."""
    st.markdown(banner_html(kind, text, extra), unsafe_allow_html=True)


def mode_badge_html(*, connected: bool | None, sample: bool) -> str:
    """§5 모드 배지 — **데이터 모드(persistence 연결) 전용**.

    sample=True → 중립 점 + '샘플 데이터'(저장은 세션에만). 아니면 connected 로
    'Supabase 연결'(success)/'연결 오류'(danger). migration/probe 경고를 여기에 섞지 않는다.
    """
    if sample:
        return ("<span class='ms-mode samp' title='저장은 이 세션에만 유지됩니다'>"
                "<span class='dot'></span>샘플 데이터</span>")
    if connected:
        return "<span class='ms-mode on'><span class='dot'></span>Supabase 연결</span>"
    return "<span class='ms-mode off'><span class='dot'></span>연결 오류</span>"


def readiness_badge_html(state: str) -> str:
    """§25 readiness 배지 — 모드 배지와 분리. state: READY|NOT_READY|PROBE_ERROR."""
    if state == "READY":
        return "<span class='ms-ready ready'>스키마 준비됨</span>"
    if state == "PROBE_ERROR":
        return "<span class='ms-ready err'>상태 확인 실패</span>"
    return "<span class='ms-ready not'>스키마 미준비</span>"


# ---------------------------------------------------------------------------
# 조직 3시트 [그룹][부서][조] 공유 컴포넌트 (Wave2a)
#   org controller 가 st.columns(3) + st.container(key=f"{page_id}__sheet") 안에서
#   호출한다. 사용자·근무형태 화면은 사용하지 않으므로 회귀 영향 없음.
# ---------------------------------------------------------------------------
def drilldown_context_html(items: list[tuple[str, str | None]]) -> str:
    """드릴다운 컨텍스트 스트립 HTML — 그룹 › 부서 › 조 계층 선택 상태.

    ``items`` 는 ``[(role_label, value|None), ...]`` 순서열(예:
    ``[("그룹", "PET계열"), ("부서", "PET생산부"), ("조", None)]``). 값이 None 이면
    "미선택"(회색)으로 표시하고, 마지막 선택된 단계는 navy 로 강조한다. 표시 라벨은
    escape 하며, 실제 컨텍스트 키(group_uid/dept_code)는 controller 가 별도 보관한다.
    """
    last_selected = -1
    for i, (_role, val) in enumerate(items):
        if val:
            last_selected = i
    segs: list[str] = []
    for i, (role, val) in enumerate(items):
        role_e = escape(role)
        if val:
            cls = "pin" if i == last_selected else "sel"
            segs.append(f"<span>{role_e} <b class='{cls}'>{escape(val)}</b></span>")
        else:
            segs.append(f"<span class='none'>{role_e} —</span>")
    joined = "<span class='arw'>›</span>".join(segs)
    return f"<div class='ms-ctx'><span>드릴다운</span><span class='arw'>·</span>{joined}</div>"


def drilldown_context(items: list[tuple[str, str | None]]) -> None:
    """``drilldown_context_html`` 을 렌더한다."""
    st.markdown(drilldown_context_html(items), unsafe_allow_html=True)


def sheet_head_html(title: str, *, count: int | None = None, context: str | None = None,
                    locked: bool = False) -> str:
    """시트 헤더 HTML — 제목 + (건수 칩) + (드릴다운 컨텍스트 칩 또는 잠김 표식).

    ``context`` 는 상위 선택으로 이 시트가 열려 있을 때의 컨텍스트명(예: 부서 시트의
    "PET계열"). ``locked=True`` 면 오른쪽에 잠김 표식을 보인다(컨텍스트 칩과 상호배타).
    """
    cnt = f"<span class='cnt'>{int(count)}개</span>" if count is not None else ""
    if locked:
        right = "<span class='lock'>▸ 잠김</span>"
    elif context:
        right = f"<span class='ctx'>▸ {escape(context)}</span>"
    else:
        right = ""
    return (f"<div class='ms-sheet-head'><span class='t'>{escape(title)}</span>{cnt}{right}</div>")


def sheet_head(title: str, *, count: int | None = None, context: str | None = None,
               locked: bool = False) -> None:
    """``sheet_head_html`` 을 렌더한다."""
    st.markdown(sheet_head_html(title, count=count, context=context, locked=locked),
                unsafe_allow_html=True)


def sheet_locked_html(title: str, hint: str | None = None) -> str:
    """상위 미선택 시 하위 시트의 잠김/빈 상태 HTML (§ '그룹을 먼저 선택하세요').

    정상 empty(오류 아님)로 렌더한다. 이 컴포넌트를 표시하는 시트는 controller 가
    행 추가·삭제·저장 등 **쓰기 컨트롤을 함께 비활성**(``master_action_bar(can_write=False)``)
    해야 한다. 색만으로 상태를 표시하지 않으며 자물쇠 글리프+텍스트로 이중부호화한다.
    """
    sub = f"<div class='s'>{escape(hint)}</div>" if hint else ""
    lock_svg = (
        "<svg class='glyph' width='26' height='26' viewBox='0 0 24 24' fill='none' "
        "stroke='currentColor' stroke-width='1.5' stroke-linecap='round' stroke-linejoin='round'>"
        "<rect x='5' y='11' width='14' height='9' rx='1.5'/><path d='M8 11V8a4 4 0 0 1 8 0v3'/></svg>"
    )
    return (f"<div class='ms-locked'>{lock_svg}"
            f"<div class='t'>{escape(title)}</div>{sub}</div>")


def sheet_locked(title: str, hint: str | None = None) -> None:
    """``sheet_locked_html`` 을 렌더한다(잠긴 하위 시트 본문 자리)."""
    st.markdown(sheet_locked_html(title, hint), unsafe_allow_html=True)


def empty_state_html(title: str, hint: str | None = None) -> str:
    """정상 빈 상태(데이터 0 / 필터 결과 0) HTML — 오류로 위장하지 않는다(§18)."""
    sub = f"<div class='s'>{escape(hint)}</div>" if hint else ""
    return f"<div class='ms-empty'><div class='t'>{escape(title)}</div>{sub}</div>"


def empty_state(title: str, hint: str | None = None) -> None:
    """``empty_state_html`` 을 렌더한다."""
    st.markdown(empty_state_html(title, hint), unsafe_allow_html=True)
