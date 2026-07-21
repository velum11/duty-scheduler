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

import streamlit as st

# ---------------------------------------------------------------------------
# §2 색상 토큰 (semantic) — 배지/칩 HTML 생성 시 파이썬에서도 참조한다.
# ---------------------------------------------------------------------------
TOKENS: dict[str, str] = {
    "canvas": "#EBE7DF",
    "surface": "#FFFFFF",
    "surface-2": "#F7F5F0",
    "surface-3": "#F1EEE7",
    "line": "#E4E0D8",
    "line-strong": "#D4CEC3",
    "ink": "#24262B",
    "ink-2": "#5F5C55",
    "ink-3": "#908C83",
    "navy": "#1E3A6E",
    "navy-hover": "#17305C",
    "gold": "#B4813F",
    "gold-soft": "#EFE9DC",
    "info": "#295D91",
    "info-bg": "#EAF1F8",
    "success": "#2F6B4F",
    "success-bg": "#E9F2EC",
    "warn": "#8A6A1C",
    "warn-bg": "#FBF2D8",
    "danger": "#9A3B2E",
    "danger-bg": "#FBEEEB",
    "selected-bg": "#E7EEF6",
}


def token(name: str) -> str:
    """토큰 값(색상)을 반환한다. 미정의 토큰은 그대로 돌려준다(임의 색 허용)."""
    return TOKENS.get(name, name)


# ---------------------------------------------------------------------------
# 페이지 크롬 CSS — page_id 와 무관하게 버튼 역할 접미사로 스코프한다.
# 액션바 버튼 key 는 `{page_id}__save/__del/__add/__addg/__refresh` 규칙을 쓰므로
# `[class*="__save"]` 같은 부분일치 선택자로 모든 화면·패널을 한 번에 스타일링한다.
# ---------------------------------------------------------------------------
_PAGE_CSS = """
<style>
:root {
  --ms-canvas:#EBE7DF; --ms-surface:#FFFFFF; --ms-surface-2:#F7F5F0; --ms-surface-3:#F1EEE7;
  --ms-line:#E4E0D8; --ms-line-strong:#D4CEC3; --ms-ink:#24262B; --ms-ink-2:#5F5C55; --ms-ink-3:#908C83;
  --ms-navy:#1E3A6E; --ms-navy-hover:#17305C; --ms-gold:#B4813F; --ms-gold-soft:#EFE9DC;
  --ms-info:#295D91; --ms-info-bg:#EAF1F8; --ms-success:#2F6B4F; --ms-success-bg:#E9F2EC;
  --ms-warn:#8A6A1C; --ms-warn-bg:#FBF2D8; --ms-danger:#9A3B2E; --ms-danger-bg:#FBEEEB;
}
/* §5 페이지 제목 + 한 줄 설명 + 모드 배지 */
.ms-head { display:flex; align-items:flex-start; justify-content:space-between; gap:1rem; margin:0 0 .1rem; }
.ms-crumb { font-size:.72rem; color:var(--ms-ink-3); margin:0 0 .12rem; letter-spacing:.01em; }
.ms-title { font-size:1.25rem; font-weight:700; color:var(--ms-ink); letter-spacing:-.01em; margin:0; line-height:1.6rem; }
.ms-desc { font-size:.81rem; color:var(--ms-ink-2); margin:.18rem 0 0; line-height:1.35; }
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
[class*="__filter"] label { font-size:.72rem !important; color:var(--ms-ink-3) !important; }
/* §7 액션바 */
[class*="__bar"] { margin:.15rem 0 .45rem; }
[class*="__bar"] div[data-testid="stHorizontalBlock"] { align-items:center; }
[class*="__bar"] div.stButton > button { min-height:2.2rem; height:2.2rem; padding:0 .72rem; border-radius:6px;
  font-size:.82rem; font-weight:600; white-space:nowrap; gap:.35rem; }
[class*="__bar"] div.stButton > button [data-testid="stIconMaterial"] { font-size:16px; }
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
.ms-chip.mute   { background:var(--ms-surface-3);  color:var(--ms-ink-3);   border:1px solid var(--ms-line); }
.ms-chip.lock   { background:var(--ms-surface-3);  color:var(--ms-ink-2);   border:1px solid var(--ms-line-strong); }
/* readiness 배지 — 모드 배지와 분리 */
.ms-ready { display:inline-flex; align-items:center; gap:.35rem; padding:.22rem .55rem; border-radius:6px;
  font-size:.72rem; font-weight:600; }
.ms-ready.ready { background:var(--ms-success-bg); color:var(--ms-success); }
.ms-ready.not   { background:var(--ms-warn-bg);    color:var(--ms-warn); }
.ms-ready.err   { background:var(--ms-danger-bg);  color:var(--ms-danger); }
</style>
"""


def inject_page_styles() -> None:
    """페이지 크롬 CSS 를 1회 주입한다(화면 render 시작에서 호출)."""
    st.markdown(_PAGE_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# §9~§16, 상태 매트릭스 — 그리드 내부(iframe) custom_css.
# 배경 우선순위는 master_row_class_rules 의 상호배타 규칙 + 아래 색으로 함께 보장한다.
# ---------------------------------------------------------------------------
GRID_CSS: dict[str, dict] = {
    ".ag-root-wrapper": {"border": "1px solid " + TOKENS["line-strong"], "border-radius": "8px"},
    ".ag-header": {"background": TOKENS["surface-2"], "border-bottom": "1px solid " + TOKENS["line-strong"]},
    ".ag-header-cell": {"border-right": "1px solid rgba(0,0,0,.08)"},
    ".ag-header-cell-label": {"justify-content": "center", "font-size": "12.5px",
                              "font-weight": "600", "color": TOKENS["ink-2"]},
    ".ag-cell": {
        "border-right": "1px solid rgba(0,0,0,.06)",
        "display": "flex", "align-items": "center", "line-height": "normal",
        "font-size": "13px", "color": TOKENS["ink"],
    },
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
    # ---- 행 상태(상호 배타, 우선순위: error>delete>new>inactive>selected) ----
    ".ms-row-selected .ag-cell": {"background": TOKENS["selected-bg"] + " !important"},
    ".ms-row-inactive .ag-cell": {"background": TOKENS["surface-3"] + " !important",
                                  "color": TOKENS["ink-3"] + " !important"},
    ".ms-row-new .ag-cell": {"background": TOKENS["info-bg"] + " !important",
                             "box-shadow": "inset 3px 0 " + TOKENS["info"]},
    ".ms-row-delete .ag-cell": {"background": TOKENS["danger-bg"] + " !important",
                                "box-shadow": "inset 3px 0 " + TOKENS["danger"]},
    ".ms-row-error .ag-cell": {"background": TOKENS["danger-bg"] + " !important",
                               "box-shadow": "inset 3px 0 " + TOKENS["danger"]},
    # §25 드릴다운 활성(조직) — 신규와 물리적으로 구분(네이비 틴트 + 우측 칩)
    ".ms-row-linked .ag-cell": {"background": "rgba(30,58,110,.10) !important"},
    # ---- 셀 상태 ----
    ".ms-cell-error": {"box-shadow": "inset 0 0 0 1.5px " + TOKENS["danger"], "background": "#FFF6F4"},
    ".ms-cell-dirty": {"box-shadow": "inset 2px 0 " + TOKENS["warn"]},
    # 드롭다운 셀 ▾ 표식(선택형임을 상시 노출)
    ".ms-cell-select": {"position": "relative"},
    ".ms-cell-select::after": {"content": "'\\25BE'", "position": "absolute", "right": "8px",
                               "color": TOKENS["ink-3"], "font-size": "10px", "pointer-events": "none"},
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
    return "<span class='ms-ready not'>migration 미적용</span>"
