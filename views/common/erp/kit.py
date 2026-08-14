"""중립 구조 키트 구현 (KP-standard §0.2) — 레이아웃 전용, 도메인 lifecycle 미포함.

영역 순서(§0.3): title → top actions(page) → conditions → primary → details → status.
읽기(READ_VIEW)·단일 선택(MASTER_DETAIL) subset 을 제공한다 — ``read_grid``·``select_grid``
출하됨. EDIT/MATRIX 편집 어댑터는 후속. 그리드는 AgGrid 단일 렌더러를 쓰되 READ/SELECT 는
편집 자산(action열·paste·editable·unsafe jscode)을 넣지 않는다(§0.5). 색은 cellClassRules
문자열식 + custom_css 로만.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field as dc_field
from html import escape
from typing import Any, Callable

import pandas as pd
import streamlit as st
from st_aggrid import AgGrid, DataReturnMode

from views.common import scaffold
from views.master import style
from views.master.grid import CELL_COPY_OPTIONS

TOKENS = style.TOKENS

# ── 밀도 토큰 (DESIGN.md §2·§0.6 — 데스크톱 읽기/선택 그리드) ──
_READ_ROW_PX = 34          # read_grid 기본(§2 읽기 32–34) — schedule_view 등 무변경.
_SELECT_ROW_PX = 32        # select_grid 기본(M/A 큐 밀도, §0.6 실측 31–32) — USER 는 44 variant.
_READ_HEADER_PX = 36       # 헤더 34–36(§2) — 그리드 헤더 계약(test_erp_select_grid) 고정.
_READ_CHROME_PX = 16
_READ_MIN_PX = 120
_READ_MAX_PX = 460

# 카드 단일 토큰(§0.6 박스 상한: radius·보더·padding 단일화 — 8/5/4px 혼재 금지, §2 L1=8px).
# kit 스코프 전용. kit 밖 전역(modules/ui.py 대시보드 카드 등)은 건드리지 않는다.
_CARD_RADIUS = "8px"

_NO_ROWS = (
    "<span style='color:%s;font-size:.82rem;'>표시할 데이터가 없습니다</span>"
    % TOKENS["ink-3"]
)

# 한 번만 주입하는 키트 CSS(우측 인라인 라벨·요약 스트립·빈상태·조건 스트립). st-key 스코프
# 불필요한 표현 요소만 담으며 사이드바·기존 화면(modules/ui.py) 전역 CSS를 건드리지 않는다.
# §0.6 실측 기준 잠금(2026-07-29): 카드 나열 금지 → 한 줄 요약 스트립·한 줄 빈상태·얇은
# 조건 필터 스트립. 카드 radius/보더/padding 은 단일 토큰(_CARD_RADIUS = 8px)으로 통일한다.
_KIT_CSS = f"""
<style>
/* §1-E 필터 라벨 — 상단 정렬 12.5/500(dc isUsers). 입력은 아래(_render_widget).
   라벨-입력 겹침 방지: 라벨 블록 높이 확보 + 하단 여백. */
.erp-lbl {{
  display: block; text-align: left; color: {TOKENS['ink-2']}; font-size: 12.5px;
  font-weight: 500; line-height: 1.3; height: 17px; margin: 0 0 5px; white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis;
}}
/* 라벨 markdown 컨테이너가 접혀 위젯과 겹치지 않게 여백 확보(전역 margin-bottom:0 보정). */
[class*="st-key-erpcond_"] [data-testid="stMarkdownContainer"]:has(.erp-lbl) {{ margin-bottom: 5px !important; }}
/* 요약/KPI = 한 줄 스트립(§0.6 강제): 독립 카드 나열이 아니라 hairline 구분 단일 박스.
   높이 ≤72px(padding 8+8 + 값 ~20 + 라벨 ~14 ≈ 50px). 카드 겹침의 근본 해결 — 항목이
   행을 넘지 않는다. */
.erp-strip {{
  display: flex; align-items: stretch; flex-wrap: nowrap;
  border: 1px solid {TOKENS['line-strong']}; border-radius: {_CARD_RADIUS};
  background: {TOKENS['surface']}; overflow: hidden;
}}
.erp-strip-i {{
  flex: 1 1 0; min-width: 0; display: flex; flex-direction: column;
  justify-content: center; gap: 1px; padding: 8px 14px;
  border-left: 1px solid {TOKENS['line']};
}}
.erp-strip-i:first-child {{ border-left: 0; }}
.erp-strip-v {{
  font-size: 18px; font-weight: 700; color: {TOKENS['ink']};
  font-variant-numeric: tabular-nums; line-height: 1.15;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}}
.erp-strip-l {{ font-size: 11.5px; color: {TOKENS['ink-2']}; line-height: 1.2;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
/* 상세 메타 스트립(§3.2 handoff): 라벨(작게·ink-2) 위 / 값(진하게·ink) 아래 —
   4개 상세 상단을 일관된 읽기 메타 스트립으로 통일. 카드·그림자 없이 hairline 1개.
   erp-strip 과 동일 지오메트리(≤72px: 7+7 padding + 라벨~14 + 값~17 ≈ 45px). */
.erp-meta {{
  display: flex; align-items: stretch; flex-wrap: nowrap;
  border: 1px solid {TOKENS['line-strong']}; border-radius: {_CARD_RADIUS};
  background: {TOKENS['surface']}; overflow: hidden;
}}
.erp-meta-i {{
  flex: 1 1 0; min-width: 0; display: flex; flex-direction: column;
  justify-content: center; gap: 2px; padding: 7px 14px;
  border-left: 1px solid {TOKENS['line']};
}}
.erp-meta-i:first-child {{ border-left: 0; }}
.erp-meta-l {{ font-size: 11.5px; color: {TOKENS['ink-2']}; line-height: 1.2;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.erp-meta-v {{ font-size: 13px; font-weight: 600; color: {TOKENS['ink']}; line-height: 1.3;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
/* 등급 마크(§3.1 handoff): 셰브런(방향/개수) + 색 텍스트, 배경 없음 — 색 + 방향
   이중부호화(색약 안전). pill 아님(한 행 pill 형식 ≤1축 강제). */
.erp-grade {{ display: inline-flex; align-items: center; gap: 4px; font-weight: 600;
  font-size: 13px; font-variant-numeric: tabular-nums; line-height: 1.2; }}
.erp-grade .gm {{ font-size: 10px; letter-spacing: -1.5px; }}
/* 예외 큐 스트립(§3.5 handoff): 지금 처리할 예외(미평가·검토중·기한초과 CAPA). 옅은
   danger-bg 틴트(값>0)로 예외 현황만 표시한다(순수 표시 스트립 — 클릭/이동 어포던스 없음;
   이동은 각 화면 메뉴로 충분, 과배선 금지·거짓 어포던스 방지, V1 QA Medium#1). 각 항목 ≤72px. */
.erp-attn {{ display: flex; align-items: stretch; flex-wrap: nowrap;
  border: 1px solid {TOKENS['line-strong']}; border-radius: {_CARD_RADIUS}; overflow: hidden; }}
.erp-attn-i {{ flex: 1 1 0; min-width: 0; display: flex; align-items: center; gap: 10px;
  padding: 9px 14px; border-left: 1px solid {TOKENS['line']}; background: {TOKENS['surface']}; }}
.erp-attn-i:first-child {{ border-left: 0; }}
.erp-attn-i.on {{ background: {TOKENS['danger-bg']}; }}
.erp-attn-tx {{ display: flex; flex-direction: column; gap: 1px; min-width: 0; }}
.erp-attn-v {{ font-size: 16px; font-weight: 700; font-variant-numeric: tabular-nums;
  line-height: 1.15; color: {TOKENS['ink-2']}; }}
.erp-attn-i.on .erp-attn-v {{ color: {TOKENS['danger']}; }}
.erp-attn-l {{ font-size: 11.5px; color: {TOKENS['ink-2']}; line-height: 1.2;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
/* 빈 상태 = 한 줄 안내(§0.6 강제): 대형 점선 placeholder 금지, 높이 ≤72px. */
.erp-empty {{
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  min-height: 42px; padding: 10px 13px;
  border: 1px solid {TOKENS['line']}; border-radius: {_CARD_RADIUS};
  background: {TOKENS['surface-2']};
}}
.erp-empty-t {{ font-size: 13px; font-weight: 600; color: {TOKENS['ink-2']}; }}
.erp-empty-b {{ font-size: 12px; color: {TOKENS['ink-2']}; line-height: 1.4; }}
/* §1-F/§1-A 지표 타일 스트립(분석 화면 표준·사용자 채택): 좌측 2px 보더 + 26px 모노 값
   + 라벨(카드 박스 없음, 2줄: 라벨 + 값). 요약 수치가 있는 화면 공통 어휘. */
.erp-metrics {{ display: flex; flex-wrap: wrap; gap: 12px; margin: .3rem 0 1rem; }}
.erp-metric {{ flex: 1 1 130px; min-width: 0; display: flex; flex-direction: column;
  gap: 4px; padding: 2px 18px; }}
.erp-metric-label {{ font-size: 12px; color: #6b665d; }}
.erp-metric-vrow {{ display: flex; align-items: baseline; gap: 4px; }}
.erp-metric-val {{ font-size: 26px; font-weight: 600; letter-spacing: -0.03em; color: {TOKENS['ink']}; }}
.erp-metric-unit {{ font-size: 11.5px; color: #6b665d; }}
/* 모노 강제(값) — Streamlit 이 인라인 font-family 를 제거하므로 0,3,0 규칙으로. */
.stApp [data-testid="stMarkdownContainer"] .erp-metric-val {{
  font-family: 'IBM Plex Mono','Consolas','Menlo',monospace; font-variant-numeric: tabular-nums;
}}
/* §1-E 필터 줄(§0-5 카드 금지): 카드 박스 없이 헤어라인+여백만. 하단 헤어라인으로 표와 구획. */
[class*="st-key-erpcond_"] {{
  border: 0 !important; background: transparent !important; padding: 0 !important;
  border-bottom: 1px solid #e0dbd2 !important; padding-bottom: 10px !important;
  margin-bottom: 10px !important;
}}
[class*="st-key-erpcond_submit_"] {{
  border: 0 !important; border-bottom: 0 !important; padding: 0 !important; margin: 6px 0 0 !important;
}}
[class*="st-key-erpcond_"] [data-testid="stVerticalBlock"] {{ gap: 8px !important; }}
[class*="st-key-erpcond_"] [data-testid="stHorizontalBlock"] {{ gap: .6rem !important; }}
/* §1-E 입력 14.5 (dc): 필터 입력 폰트 통일 */
[class*="st-key-erpcond_"] input, [class*="st-key-erpcond_"] [data-baseweb="select"] div {{
  font-size: 14.5px;
}}
/* help(툴팁) 래퍼가 씌워진 버튼도 앱 기본 버튼 크기를 따르게 — modules/ui.py 의 직계자식
   선택자(.stButton > button)가 툴팁 DOM 체인을 못 잡아 생기는 높이 불일치 보정(detail_actions
   처럼 help 유무가 섞인 버튼을 한 행에 둘 때 가시화). 크기만 맞추는 저위험 규칙. */
.stTooltipHoverTarget > button {{ min-height: 2.15rem; font-size: 0.83rem; }}
</style>
"""


def read_grid_height(nrows: int, *, row_px: int = _READ_ROW_PX) -> int:
    natural = _READ_HEADER_PX + max(int(nrows), 1) * int(row_px) + _READ_CHROME_PX
    return max(_READ_MIN_PX, min(natural, _READ_MAX_PX))


# ============================================================ screen_frame
def screen_frame(archetype: str, *, title: str, desc: str, breadcrumb: str,
                 badges: str | None = None, toolbar: bool = False):
    """화면 헤더(브레드크럼·제목·모드배지) — scaffold.page_chrome 위임(영역 순서의 title 슬롯).

    키트 CSS(우측 라벨·메트릭)를 이 진입점에서 매 렌더 주입한다 — 모든 화면이 screen_frame
    을 먼저 호출하므로 이후 condition_panel/status_region 의 클래스가 항상 스타일을 받는다.

    ``toolbar=True`` 면 헤더 밴드에 실제 액션 버튼 슬롯을 만들고 그 핸들
    (:class:`~views.master.BandToolbar`)을 반환한다(사용자 관리 파일럿 — EDIT_GRID 의
    추가·삭제·저장·새로고침을 밴드로 승격). 기본 ``False`` 면 종전처럼 ``None`` 반환."""
    band = scaffold.page_chrome(
        archetype, title=title, desc=desc, breadcrumb=breadcrumb,
        badges=badges if badges is not None else scaffold.mode_badge(),
        toolbar=toolbar,
    )
    st.markdown(_KIT_CSS, unsafe_allow_html=True)
    return band if toolbar else None


# ============================================================ top_action_bar
def top_action_bar(page_id: str, actions: list[tuple[str, str]]) -> dict:
    """페이지 액션을 상단 우측에 그룹화해 렌더(위치·어휘 고정 = 일관성 앵커, §0.4).

    actions: ``[(label, kind)]`` — kind ∈ {"primary","default"}. 반환 ``{label: clicked}``.
    범위 액션(추가/삭제/저장)은 여기가 아니라 소유 섹션에 둔다.
    """
    if not actions:
        return {}
    n = len(actions)
    cols = st.columns([8.0] + [1.4] * n, vertical_alignment="center")
    clicks: dict = {}
    for i, (label, kind) in enumerate(actions):
        with cols[i + 1]:
            clicks[label] = st.button(
                label, key=f"{page_id}_act_{i}",
                type="primary" if kind == "primary" else "secondary",
                width="stretch",
            )
    return clicks


# ============================================================ form_submit
def form_submit(label: str, *, disabled: bool = False, help: str | None = None) -> bool:
    """FORM_ENTRY 제출 앵커 — ``st.form_submit_button`` 래퍼(위치·타입·어휘 고정, §0.4).

    FORM_ENTRY 는 상단 액션바(top_action_bar) 대신 이 버튼이 유일한 제출 지점이다.
    **반드시 호출부의 ``st.form(...)`` 컨텍스트 안에서 호출**한다 — 이 함수는 폼을 열지
    않는다(중첩 폼은 Streamlit 금지, 폼 개설은 화면 소관). 도메인 검증·저장은 호출부가
    소유하며 여기서는 클릭 bool 만 돌려준다(readiness 등으로 계산한 ``disabled`` 전달).
    """
    return st.form_submit_button(
        label, type="primary", disabled=disabled, help=help, use_container_width=False,
    )


# ============================================================ condition_panel
@dataclass
class Field:
    """조건 패널의 한 필드. select/date/checkbox/text.

    ``key``: 반환 dict(``condition_panel`` 결과)의 논리 키.
    ``widget_key``: 지정 시 st 세션 위젯 키를 **정확히 그 값**으로 쓴다(기본은
    ``f"{page_id}_{key}"``). 기존 화면이 load-bearing 세션 키(예: revert 로직·테스트가
    이름으로 직접 참조하는 ``og_active``/``se_y`` 등)를 유지해야 할 때 사용한다.
    """
    key: str
    label: str
    kind: str = "select"
    options: list = dc_field(default_factory=list)
    value: Any = None
    disabled: bool = False
    format_func: Callable | None = None
    help: str | None = None
    widget_key: str | None = None
    placeholder: str | None = None
    #: 컨트롤 폭 힌트(§0.6 강제 — 내용 맞춤). int 픽셀(짧은 코드값 select 는 ~140)이나
    #: "stretch"/"content". None 이면 열 폭을 채운다(종전 동작 = "stretch").
    width: int | str | None = None


def _render_widget(page_id: str, f: Field):
    wkey = f.widget_key if f.widget_key else f"{page_id}_{f.key}"
    w = f.width if f.width is not None else "stretch"  # §0.6 내용 맞춤 폭(없으면 종전=열 채움).
    if f.kind == "checkbox":
        return st.checkbox(f.label, value=bool(f.value), key=wkey,
                           label_visibility="collapsed", disabled=f.disabled, help=f.help)
    if f.kind == "date":
        return st.date_input(f.label, value=f.value, key=wkey, width=w,
                             label_visibility="collapsed", disabled=f.disabled, help=f.help)
    if f.kind == "text":
        return st.text_input(f.label, value=f.value or "", key=wkey, width=w,
                             label_visibility="collapsed", disabled=f.disabled,
                             help=f.help, placeholder=f.placeholder)
    return st.selectbox(f.label, f.options, key=wkey, width=w,
                        format_func=f.format_func or (lambda x: x),
                        label_visibility="collapsed", disabled=f.disabled,
                        help=f.help, placeholder=f.placeholder)


def condition_panel(page_id: str, fields: list[Field], *, cols: int = 3,
                    submit: tuple[str, str] | None = None, content_fit: bool = False,
                    submit_icon: str | None = None):
    """§1-E 필터 줄(dc isUsers 참조) — 라벨 상단 정렬(12.5/500) + 입력 아래.

    카드 박스가 아니라 헤어라인+여백만(§0-5 카드 금지). 반환 ``{field.key: value}``.

    레이아웃 2모드:
      - 기본(``content_fit=False``): 한 행에 cols 개, ``st.columns([1]*cols)`` 등폭 열(종전 동작).
      - ``content_fit=True`` (U4·§0.6 "컨트롤 폭 내용 맞춤"): 가로 flex 로 흘려 짧은 코드값
        셀렉트(연도·월·상태·등급 등)는 **내용 맞춤 폭**(Field.width), 검색 text 인풋만 신축한다.
        cols 는 무시하고 좁아지면 자연 wrap. 소비 화면이 명시적으로 opt-in 할 때만 쓴다
        (기본 False 라 기존 소비 화면은 무영향).

    ``submit=(label, key)`` 를 주면 필터 줄 우측에 primary 버튼([조회] 등)을 인라인 렌더하고
    ``(values, clicked)`` 튜플을 반환한다(미지정이면 dict 반환).

    ``submit_icon`` 은 그 제출 버튼의 Material 아이콘(예: ``":material/search:"``)이다.
    조회 액션에 돋보기 아이콘을 붙여 상단 헤더의 새로고침(원형 화살표)과 의미가 섞이지
    않게 한다. 기본 ``None`` 이면 종전처럼 라벨만 렌더한다(기존 호출부 무영향)."""
    values: dict = {}
    clicked = False
    with st.container(key=f"erpcond_{page_id}"):
        if content_fit:
            with st.container(key=f"erpcondfit_{page_id}", horizontal=True,
                              gap="medium", vertical_alignment="bottom"):
                for f in fields:
                    # text(검색)만 신축, 나머지(짧은 코드값 select·date)는 내용 맞춤 폭.
                    cell_w = "stretch" if f.kind == "text" else "content"
                    with st.container(key=f"erpcf_{page_id}_{f.key}", width=cell_w):
                        st.markdown(f"<div class='erp-lbl'>{f.label}</div>",
                                    unsafe_allow_html=True)
                        values[f.key] = _render_widget(page_id, f)
        else:
            for start in range(0, len(fields), cols):
                row = fields[start:start + cols]
                slots = st.columns([1] * cols, vertical_alignment="top")
                for j, f in enumerate(row):
                    with slots[j]:
                        st.markdown(f"<div class='erp-lbl'>{f.label}</div>",
                                    unsafe_allow_html=True)
                        values[f.key] = _render_widget(page_id, f)
        if submit is not None:
            slabel, skey = submit
            with st.container(key=f"erpcond_submit_{page_id}"):
                bcols = st.columns([1, 0.26], vertical_alignment="center")
                with bcols[1]:
                    clicked = st.button(slabel, key=skey, type="primary", width="stretch",
                                        icon=submit_icon)
    if submit is None:
        return values
    return values, clicked


# ============================================================ grid skeleton (표현 요소, §0 아키타입 아님)
# 무거운 그리드가 rerun/전환될 때 이전 실행의 낡은 그리드 형상이 남아 보이는 문제를
# 중립 회색 셔머 스켈레톤으로 가린다(사용자: "전환 중 형상이 남아 보기 불편").
# 라이트 전용 — 토큰은 master.style.TOKENS 재사용, 다크는 --skel-* var 오버라이드로
# 나중에(라이트 우선 결정). 스켈레톤은 primary 영역의 표현 요소일 뿐 새 아키타입이 아니다.
_SKEL_MIN_ROWS, _SKEL_MAX_ROWS = 3, 7
_SKEL_MIN_COLS, _SKEL_MAX_COLS = 3, 8
_SKEL_COL_W = (46, 62, 40, 70, 52, 64, 44, 58)  # 셀 내부 막대 폭(%) — 다열 그리드 밀도 근사
_SKEL_UNSET = object()

# 스켈레톤 CSS. var 기본값은 TOKENS(라이트) 를 그대로 주입하고(팔레트 새로 만들지 않음),
# 구조/키프레임은 순수 문자열(중괄호 리터럴 그대로)로 둔다. 다크는 var 만 오버라이드하면 됨.
_SKEL_CSS = (
    "<style>"
    ".erp-skel{"
    f"--skel-surface:{TOKENS['surface']};--skel-surface2:{TOKENS['surface-2']};"
    f"--skel-line:{TOKENS['line-strong']};--skel-hair:{TOKENS['line']};"
    f"--skel-base:{TOKENS['line-strong']};--skel-base2:{TOKENS['ink-3']};"
    f"--skel-hi:{TOKENS['surface-2']};"
    "border:1px solid var(--skel-line);border-radius:2px;background:var(--skel-surface);overflow:hidden}"
    ".erp-skel-hd{display:flex;height:36px;background:var(--skel-surface2);"
    "border-bottom:1px solid var(--skel-line)}"
    ".erp-skel-rw{display:flex;height:34px;border-bottom:1px solid var(--skel-hair)}"
    ".erp-skel-rw:last-child{border-bottom:0}"
    ".erp-skel-cell{flex:1 1 0;display:flex;align-items:center;padding:0 12px;"
    "min-width:0;border-right:1px solid var(--skel-hair)}"
    ".erp-skel-cell:last-child{border-right:0}"
    ".erp-skel-cell.k{flex:0 0 54px;justify-content:center;padding:0}"
    ".erp-skel-b{height:10px;border-radius:2px;background:var(--skel-base);"
    "position:relative;overflow:hidden;max-width:100%}"
    ".erp-skel-hd .erp-skel-b{height:11px;background:var(--skel-base2);opacity:.55}"
    ".erp-skel-b::after{content:'';position:absolute;inset:0;"
    "background:linear-gradient(90deg,transparent,var(--skel-hi),transparent);"
    "transform:translateX(-100%);animation:erp-skel-sweep 1.25s ease-in-out infinite}"
    "@keyframes erp-skel-sweep{100%{transform:translateX(100%)}}"
    "@media (prefers-reduced-motion:reduce){.erp-skel-b::after{animation:none}}"
    # 다크 테마 훅(라이트 우선 — 지금은 튜닝하지 않음). 향후 --skel-* 만 오버라이드.
    ":root[data-theme='dark'] .erp-skel{/* dark --skel-* TBD */}"
    "@media (prefers-color-scheme:dark){/* .erp-skel dark override TBD — ship light */}"
    "</style>"
)


def _skel_cells(ncols: int) -> str:
    # 첫 셀은 좁은 액션/인덱스열 모사(체크박스 크기 사각), 이후는 셀 내부 막대.
    cells = ["<span class='erp-skel-cell k'><i class='erp-skel-b' style='width:16px'></i></span>"]
    for i in range(1, ncols):
        w = _SKEL_COL_W[i % len(_SKEL_COL_W)]
        cells.append(f"<span class='erp-skel-cell'><i class='erp-skel-b' style='width:{w}%'></i></span>")
    return "".join(cells)


def grid_skeleton_html(nrows: int, ncols: int, *, height: int | None = None) -> str:
    """헤더 밴드 + N개 자리행(READ 행높이 34px 근사) + 열 블록의 회색 셔머 스켈레톤 HTML.

    행/열 수는 실제 그리드가 아무리 커도 작은 상한(행 3~7·열 3~8)으로 잘라 과다 도색을
    막는다. ``height`` 를 주면 컨테이너 min-height 로 맞춰 그리드로 교체될 때 레이아웃
    점프를 줄인다. 자체 완결형(<style> 동봉) — 그리드로 교체되면 style 도 함께 사라진다.
    """
    r = max(_SKEL_MIN_ROWS, min(int(nrows or 0), _SKEL_MAX_ROWS))
    c = max(_SKEL_MIN_COLS, min(int(ncols or 0), _SKEL_MAX_COLS))
    head = f"<div class='erp-skel-hd'>{_skel_cells(c)}</div>"
    body = "".join(f"<div class='erp-skel-rw'>{_skel_cells(c)}</div>" for _ in range(r))
    mh = f" style='min-height:{int(height)}px'" if height else ""
    return f"{_SKEL_CSS}<div class='erp-skel' role='presentation' aria-hidden='true'{mh}>{head}{body}</div>"


def grid_shell(key: str, *, nrows: int, ncols: int, fingerprint, render,
               prepare=None, height: int | None = None):
    """무거운 그리드를 st.empty 자리표시자 안에서 렌더하되, **전환 시에만** 스켈레톤을 먼저
    칠해 낡은 형상을 가린다(app.py 의 nav pivot st.empty+spinner 선례와 같은 발상).

    전환 판정: (이 key 최초 등장) 또는 (fingerprint 변화). 전환일 때만 markdown(스켈레톤)을
    empty 에 칠하고, **그다음** ``prepare`` (느린 데이터 준비)를 실행한 뒤 container 로 교체한다.
    스켈레톤이 실제로 화면에 뜨는 유일한 구간은 이 「칠하기 → 느린 prepare → container 교체」
    사이의 서버측 지연이다(라이브 실측: 지연 0 이면 델타가 합쳐져 스켈레톤이 안 뜨고, 유의미한
    지연이 있어야 뜬다). 따라서 **낡은 형상을 실제로 가리려면 느린 준비를 ``prepare`` 로 넘겨야
    한다** — 준비가 이미 끝난 뒤 grid_shell 을 호출하면(현재 read_grid/selectable_master_grid 의
    호출부 준비) 스켈레톤 칠하기와 container 교체 사이에 지연이 없어 스켈레톤이 뜨지 않는다.

    ``prepare`` 미지정 시엔 안전 래퍼로만 동작한다: 비전환 run 은 ``st.empty().container()``
    안에서 그대로 렌더하므로(app.py 전체 본문이 이미 쓰는 안전 패턴) 그리드 iframe 이 in-place
    갱신되어 미저장 편집이 보존된다 — 편집 그리드(schedule_edit)는 이 비전환 경로로만 도므로 셀
    입력이 리셋되지 않는다. ``render`` 는 AgGrid 를 호출해 반환을 돌려주는 콜러블이며, ``prepare``
    를 준 경우 그 반환값을 인자로 받는다(``render(prepared)``). key·JsCode·selection·col config
    등 그리드 계약은 전적으로 render 안에서 유지된다.
    """
    ph = st.empty()
    sk = f"_grid_skel::{key}"
    prev = st.session_state.get(sk, _SKEL_UNSET)
    transition = prev is _SKEL_UNSET or prev != fingerprint
    st.session_state[sk] = fingerprint
    if transition:
        ph.markdown(grid_skeleton_html(nrows, ncols, height=height), unsafe_allow_html=True)
    prepared = prepare() if prepare is not None else None  # 느린 준비 — 이 사이에만 스켈레톤이 보인다
    with ph.container():
        return render(prepared) if prepare is not None else render()


# ============================================================ read_grid / select_grid
# §1-E 표형: 헤더 무배경 + 하단 1px 헤어라인, 행 구분 헤어라인, 본문 14.5px(DESIGN §3).
_READ_BASE_CSS = {
    ".ag-header": {"background-color": "transparent",
                   "border-bottom": "1px solid " + TOKENS["line-strong"]},
    ".ag-header-cell": {"font-weight": "600", "font-size": "12.5px"},
    ".ag-cell": {"font-size": "14.5px", "display": "flex", "align-items": "center"},
    ".ag-row": {"border-bottom": "1px solid " + TOKENS["line"]},
}
# 단일 선택 그리드(select_grid) 전용 — 네이티브 single-selection 의 선택행 이중부호화.
# 선택행 = 오렌지 좌측 바(§1-E 선택 명료) + selected-bg 배경 틴트(색만 아님, 형태+색 이중부호화).
# 색은 기준정보 토큰 재사용(새 색 없음). 체크박스 마커는 호출부 선택(checkbox_marker) —
# 행 클릭이 곧 선택인 §0-1 준수 화면은 마커를 끈다.
_SELECT_CSS = {
    ".ag-row-selected .ag-cell": {"background-color": TOKENS["selected-bg"] + " !important"},
    ".ag-row.ag-row-selected": {"box-shadow": "inset 3px 0 " + TOKENS["navy"]},
    ".ag-cell .ag-selection-checkbox": {"margin-right": "8px"},
}

# 가로 스크롤 어포던스(옵트인 — ``scroll_affordance=True``).
# 좁은 폭에서 표는 컨테이너 안에서 가로 스크롤한다(DESIGN §5). 그런데 모바일 브라우저는
# **오버레이 스크롤바**라 스크롤 중에만 잠깐 뜨고, 정지 상태에서는 "오른쪽에 열이 더 있다"는
# 신호가 화면에 하나도 없다(2026-08-14 390×844 실측: 6열 중 3열만 보이는데 내부 오버플로
# 392px, 스크롤바·페이드 없음). ``::-webkit-scrollbar`` 를 칠하면 그 스크롤러가 오버레이가
# 아닌 **상시 노출 스크롤바**로 바뀌어 신호가 생긴다.
#
# 스코프: AG Grid 는 가로 오버플로가 있을 때만 ``.ag-body-horizontal-scroll`` 을 보이게 하고,
# 넘치지 않으면 ``visibility:hidden`` 이다(PC 1440 실측). 즉 이 규칙은 **넘칠 때만** 눈에
# 보이고, 넘치지 않는 그리드(=현행 PC 아차사고 목록)의 외관은 그대로다. 자리(16px 스크롤 행)는
# AG Grid 가 이미 잡아 두므로 표 높이도 변하지 않는다. 색은 §2 팔레트 토큰만 쓴다.
#
# ``scrollbar-width``/``scrollbar-color`` 는 함께 쓰지 않는다 — 표준 속성이 있으면 Chromium 이
# ``::-webkit-scrollbar`` 규칙을 무시해 지정한 팔레트 색이 적용되지 않는다(2026-08-14 4변형
# 실측: webkit 전용만 의도한 thumb 색으로 칠해짐).
_HSCROLL_AFFORDANCE_CSS = {
    ".ag-body-horizontal-scroll-viewport::-webkit-scrollbar": {
        "height": "10px", "-webkit-appearance": "none"},
    ".ag-body-horizontal-scroll-viewport::-webkit-scrollbar-track": {
        "background": TOKENS["canvas"]},
    ".ag-body-horizontal-scroll-viewport::-webkit-scrollbar-thumb": {
        "background": TOKENS["line-strong"], "border-radius": "999px",
        "border": "2px solid " + TOKENS["canvas"]},
    ".ag-body-horizontal-scroll-viewport::-webkit-scrollbar-thumb:hover": {
        "background": TOKENS["ink-3"]},
}


def _prepare_read_frame(df: pd.DataFrame, cols: list[str], hidden: list[str]) -> pd.DataFrame:
    """표시 컬럼은 빈문자 string 으로, 숨김 컬럼은 원형 그대로 보정한 프레임 사본."""
    frame = df.copy()
    for c in cols:
        if c not in frame.columns:
            frame[c] = ""
        frame[c] = frame[c].fillna("").astype(str)
    for h in hidden:
        if h not in frame.columns:
            frame[h] = None  # 행-규칙/선택키가 참조하는 값(불리언·id 등)은 원형 그대로 싣는다.
    return frame


def _build_read_coldefs(cols: list[str], hidden: list[str],
                        color_rules: dict[str, dict[str, str]] | None,
                        col_config: dict[str, dict] | None,
                        row_rules: list[dict] | None) -> tuple[list[dict], dict]:
    """READ/SELECT 공통 colDef + custom_css 빌더(편집 자산 없음, 문자열식 cellClassRules 만).

    read_grid 와 select_grid 가 동일 색/폭/행규칙 로직을 공유하되(§0.5 capability 는 분리),
    편집 렌더러·action열·paste·unsafe jscode 는 어느 쪽에도 넣지 않는다.
    """
    rules = color_rules or {}
    sizing = col_config or {}
    custom = dict(_READ_BASE_CSS)

    # 색 클래스는 색상 단위로 dedup(전 컬럼 공유). 컬럼별 규칙식은 각 colDef 에서 값을 OR 로 묶는다.
    _color_cls: dict[str, str] = {}

    def _cls_for_color(color: str) -> str:
        cls = _color_cls.get(color)
        if cls is None:
            cls = f"erp-c{len(_color_cls)}"
            _color_cls[color] = cls
            custom[f".{cls}"] = {
                "background-color": f"{color}22", "color": TOKENS["ink"], "font-weight": "600",
            }
        return cls

    # 행-조건부 오버레이 클래스(컬럼군 한정).
    row_defs: list[tuple[str, str, set]] = []
    for ri, rr in enumerate(row_rules or []):
        cls = f"erp-rr-{ri}"
        css: dict = {}
        if rr.get("bg"):
            css["background-color"] = rr["bg"]
        if rr.get("ink"):
            css["color"] = rr["ink"]
        custom[f".{cls}"] = css
        row_defs.append((cls, rr["when"], set(rr.get("columns") or [])))

    # 상호배타 강제: 같은 컬럼이 color_rules(셀 값 색)와 row_rules(행 오버레이)에 동시에 지정되면
    # 한 셀에 두 배경 클래스가 겹쳐 결과가 삽입 순서에 좌우된다(정의되지 않은 시각). 호출부 책임을
    # 문구가 아니라 구조로 강제해 schedule_view 같은 day/meta 분리 실수를 빌드 시점에 차단한다.
    _color_cols = set(rules)
    for _cls, _when, _rcols in row_defs:
        _dup = _color_cols & _rcols
        if _dup:
            raise ValueError(
                "read/select grid: 컬럼이 color_rules 와 row_rules 에 동시에 지정됨(상호배타 위반): "
                f"{sorted(_dup)}"
            )

    coldefs: list[dict] = []
    for c in cols:
        cd = {"field": c, "headerName": c, "editable": False, "sortable": False,
              "filter": False, "resizable": True}
        cfg = sizing.get(c)
        if cfg:
            cd.update(cfg)
        else:
            cd.setdefault("flex", 1)
            cd.setdefault("minWidth", 90)
        ccr: dict = {}
        crule = rules.get(c)
        if crule:
            by_color: dict[str, list] = {}
            for val, color in crule.items():
                by_color.setdefault(color, []).append(val)
            for color, vals in by_color.items():
                # ag-grid cellClassRules 문자열식: x = 셀 값(JsCode 아님 → unsafe 불필요).
                ccr[_cls_for_color(color)] = " || ".join(
                    f"x == {json.dumps(str(v))}" for v in vals
                )
        for cls, when, rcols in row_defs:
            if c in rcols:
                ccr[cls] = when
        if ccr:
            cd["cellClassRules"] = ccr
        coldefs.append(cd)
    for h in hidden:
        coldefs.append({"field": h, "hide": True, "suppressColumnsToolPanel": True})
    return coldefs, custom


def _build_read_gridoptions(coldefs: list[dict]) -> dict:
    """READ 그리드의 최종 gridOptions(AgGrid 마운트 없이 순수 구성).

    :func:`read_grid` 가 그대로 넘기는 값이며, 셀 텍스트 선택·복사 옵션
    (:data:`~views.master.grid.CELL_COPY_OPTIONS`)이 실제 최종 옵션에 실리는지를
    단위 테스트가 이 반환값으로 고정한다(편집 자산은 여전히 없음 — §0.5).
    """
    return {
        "columnDefs": coldefs,
        "defaultColDef": {"resizable": True, "sortable": False, "filter": False},
        "rowHeight": _READ_ROW_PX, "headerHeight": _READ_HEADER_PX,
        "suppressRowClickSelection": True,
        "suppressDragLeaveHidesColumns": True,
        "overlayNoRowsTemplate": _NO_ROWS,
        # 읽기 표에서도 셀 값을 드래그 선택해 복사할 수 있어야 한다(전 화면 공통).
        **CELL_COPY_OPTIONS,
    }


def read_grid(df: pd.DataFrame, *, columns: list[str] | None = None, key: str,
              color_rules: dict[str, dict[str, str]] | None = None,
              col_config: dict[str, dict] | None = None,
              row_rules: list[dict] | None = None,
              hidden_fields: list[str] | None = None,
              height: int | None = None,
              skeleton: bool = True) -> None:
    """AgGrid READ 어댑터(§0.5) — 편집 자산 없음. 색은 cellClassRules 문자열식.

    ``color_rules``: ``{컬럼명: {값: hex색}}`` — 셀 값 일치 시 배경(13% alpha)+ink+600.
      텍스트는 항상 유지(색은 보조 신호). 같은 색은 클래스 하나로 dedup 되어, 31일 매트릭스처럼
      전 컬럼이 동일 매핑을 공유해도 custom_css/규칙이 폭증하지 않는다.
    ``col_config``: ``{컬럼명: {width|flex|minWidth|maxWidth|cellClass ...}}`` — 폭·정렬 주입.
      미지정 컬럼은 ``flex=1, minWidth=90`` 으로 컨테이너 폭을 채운다(AgGrid 200px 기본값이
      다열에서 가로 오버플로를 만드는 문제 방지).
    ``row_rules``: ``[{"when": <행-참조 문자열식>, "columns": [적용 컬럼], "bg": hex, "ink": hex}]``
      — 셀 값이 아니라 **행 데이터**(``data['필드']``)에 따라 지정 컬럼군에만 배경을 입힌다
      (예: 퇴직행 오버레이를 meta 컬럼에만). 색 컬럼과 오버레이 컬럼을 분리해 두 규칙이 같은
      셀에 겹치지 않게 하는 것이 호출부 책임이다(상호배타를 우선순위가 아니라 구조로 보장).
    ``hidden_fields``: 표시하지 않지만 데이터로 실려(``data['필드']`` 참조 가능) 행-규칙에 쓰는 컬럼.
    ``row_rules``/``hidden_fields`` 모두 문자열식만 쓰므로 ``allow_unsafe_jscode`` 는 False 유지.
    편집·paste·action열 없음.
    """
    cols = list(columns) if columns else list(df.columns)
    hidden = [h for h in (hidden_fields or []) if h not in cols]
    frame = _prepare_read_frame(df, cols, hidden)
    coldefs, custom = _build_read_coldefs(cols, hidden, color_rules, col_config, row_rules)

    options = _build_read_gridoptions(coldefs)
    h = height if height is not None else read_grid_height(len(frame))
    view = frame[cols + hidden]

    def _mount():
        AgGrid(
            view, gridOptions=options, key=key, height=h,
            data_return_mode=DataReturnMode.AS_INPUT,
            allow_unsafe_jscode=False, theme="streamlit",
            custom_css=custom, show_toolbar=False, show_search=False,
        )

    if not skeleton:
        # 화면(호출부)이 상위 grid_shell(prepare=콜드로드) 로 이미 감싼 경우 — 이중 shell 을
        # 피하려고 여기서는 스켈레톤/전환판정을 하지 않고 AgGrid 만 in-place 로 렌더한다.
        _mount()
        return
    # 전환(조회/필터 변경으로 표시 데이터가 바뀜) 판정용 지문 — 읽기 그리드는 key 가 고정이라
    # 데이터 해시로 전환을 감지한다. 다만 느린 준비가 read_grid 상류에 있으면 이 shell 은 지연이
    # 없어 스켈레톤이 합쳐져 안 뜬다(화면 레벨 grid_shell(prepare=...) 가 실제 표출 담당).
    try:
        fp = int(pd.util.hash_pandas_object(view, index=False).sum())
    except Exception:
        fp = (len(view), tuple(cols))
    grid_shell(key, nrows=len(view), ncols=len(cols), fingerprint=fp, render=_mount, height=h)


# select_grid 의 ``col_config`` 는 조회+행선택 전용 **표현 속성**만 허용한다(§0.5). 편집 자산
# (editable·cellRenderer·cellEditor·valueSetter·paste 훅 등)을 col_config 로 주입할 수 없게
# 화이트리스트로 구조적 차단한다 — SELECT 는 편집 capability 가 아니므로 편집 자산은 문구가
# 아니라 구조로 불가해야 한다(위반 시 ValueError). 색/행규칙은 별도 인자(color_rules/row_rules).
_SELECT_COL_CONFIG_ALLOWED = frozenset({
    "width", "flex", "minWidth", "maxWidth", "cellClass", "cellStyle",
    "headerName", "headerTooltip", "tooltipField", "hide", "type",
})


def _validate_select_col_config(col_config: dict[str, dict] | None) -> None:
    """col_config 가 SELECT 허용 표현 속성만 담는지 검증(편집 자산 주입 차단)."""
    if not col_config:
        return
    for col, cfg in col_config.items():
        if not isinstance(cfg, dict):
            raise ValueError(f"select_grid: col_config[{col!r}] 는 dict 여야 합니다")
        bad = [k for k in cfg if k not in _SELECT_COL_CONFIG_ALLOWED]
        if bad:
            raise ValueError(
                "select_grid: col_config 에 SELECT 밖 속성 주입 금지(조회+행선택 전용) — "
                f"{col!r}: {sorted(bad)} (허용: {sorted(_SELECT_COL_CONFIG_ALLOWED)})"
            )


def _validate_select_key_field(df: pd.DataFrame, key_field: str, cols: list[str]) -> None:
    """자연키 계약: 존재·비어있지않음·행간 유일·표시 컬럼 미포함(항상 hidden)."""
    if key_field in cols:
        raise ValueError(
            f"select_grid: key_field {key_field!r} 는 표시 컬럼에 포함될 수 없습니다"
            " — 자연키는 항상 hidden 입니다"
        )
    if key_field not in df.columns:
        raise ValueError(f"select_grid: key_field {key_field!r} 컬럼이 데이터에 없습니다")
    if df.empty:
        return  # 빈 큐 — 행 값 검증은 공허(성립)
    keys = df[key_field].apply(lambda v: "" if pd.isna(v) else str(v).strip())
    if (keys == "").any():
        raise ValueError(
            f"select_grid: key_field {key_field!r} 에 빈 자연키 행이 있습니다(선택 반환 불가)"
        )
    dup = keys[keys.duplicated()].unique().tolist()
    if dup:
        raise ValueError(
            f"select_grid: key_field {key_field!r} 자연키가 행 간 유일하지 않습니다: {sorted(dup)}"
        )


def _build_select_gridoptions(df: pd.DataFrame, *, key_field: str,
                              columns: list[str] | None,
                              selected_key: str | None,
                              color_rules: dict[str, dict[str, str]] | None,
                              col_config: dict[str, dict] | None,
                              row_rules: list[dict] | None,
                              hidden_fields: list[str] | None,
                              row_height: int,
                              checkbox_marker: bool = True,
                              scroll_affordance: bool = False) -> tuple[pd.DataFrame, dict, dict]:
    """SELECT 그리드의 view·gridOptions·custom_css 를 (AgGrid 호출 없이) 구성한다.

    불변식 검증(col_config 화이트리스트·key_field 자연키 계약)을 여기서 먼저 강제하므로
    위반은 AgGrid 마운트 전에 ValueError 로 실패한다(단위 테스트가 이 함수를 직접 고정한다).
    """
    cols = list(columns) if columns else [c for c in df.columns if c != key_field]
    _validate_select_col_config(col_config)
    _validate_select_key_field(df, key_field, cols)

    hidden = [h for h in (hidden_fields or []) if h not in cols]
    if key_field not in hidden:
        hidden = hidden + [key_field]
    frame = _prepare_read_frame(df, cols, hidden)
    frame[key_field] = frame[key_field].fillna("").astype(str)
    coldefs, custom = _build_read_coldefs(cols, hidden, color_rules, col_config, row_rules)
    custom = {**custom, **_SELECT_CSS}
    if scroll_affordance:
        custom = {**custom, **_HSCROLL_AFFORDANCE_CSS}
    # 첫 표시 열에 네이티브 선택 체크박스(마커) — 기본 켬. 행 클릭이 곧 선택인(§0-1) 화면은
    # checkbox_marker=False 로 끄고 선택행 오렌지 바+틴트로만 이중부호화한다(상세 열기용
    # 체크박스 금지 준수 — 클릭 선택은 rowSelection=single 로 유지).
    if coldefs and cols and checkbox_marker:
        coldefs[0]["checkboxSelection"] = True

    view = frame[cols + hidden].reset_index(drop=True)
    # 자연키 → 현재 표시 프레임의 iloc(위치). 정렬/필터 뒤에도 key_field 로 다시 찾으므로
    # 위치 자체를 세션에 저장하지 않는다(위치 비의존 선택 계약).
    pre_selected: list[int] = []
    if selected_key is not None and key_field in view.columns:
        keys = view[key_field].astype(str).tolist()
        target = str(selected_key)
        pre_selected = [i for i, v in enumerate(keys) if v == target][:1]

    options = {
        "columnDefs": coldefs,
        "defaultColDef": {"resizable": True, "sortable": False, "filter": False},
        "rowHeight": int(row_height), "headerHeight": _READ_HEADER_PX,
        "suppressDragLeaveHidesColumns": True,
        "overlayNoRowsTemplate": _NO_ROWS,
        # 네이티브 single-selection(행 클릭으로 선택). 한 번 선택하면 유지(ctrl 해제 억제) —
        # 미선택→선택은 클릭, 선택 해제는 화면 로직(stale/필터 이탈)이 담당한다.
        "rowSelection": "single",
        "suppressRowClickSelection": False,
        "rowMultiSelectWithClick": False,
        "suppressRowDeselection": True,
        # 셀 텍스트 선택·복사. 행 선택은 클릭 이벤트 경로라 영향 없다(단일 선택 계약 유지).
        **CELL_COPY_OPTIONS,
    }
    if pre_selected:
        # AG Grid setSelectionState 는 initialState.rowSelection 을 **node.id 문자열 집합**
        # (Set(e).has(node.id))으로 매칭한다. getRowId 미지정이면 node.id 는 행 인덱스의
        # 문자열("0","1",…)이므로 정수 인덱스를 그대로 넘기면 0 !== "0" 로 항상 불일치해
        # pre-select 가 그리드에 시각 반영되지 않는다(틴트·체크 미표시 = §4 이중부호화 미적용).
        # 자동선택(단건 큐)처럼 클릭 없이 세션으로만 선택되는 경로에서 특히 문제였다.
        options["initialState"] = {"rowSelection": [str(i) for i in pre_selected]}
    return view, options, custom


def _selected_key(selected, key_field: str) -> str | None:
    """AgGrid 응답의 selected_rows 에서 선택행 자연키(문자열)를 뽑는다. 미선택 → None."""
    if selected is None or getattr(selected, "empty", True):
        return None
    if key_field not in selected.columns:
        return None
    value = str(selected.iloc[0][key_field]).strip()
    return value or None


def select_grid(df: pd.DataFrame, *, key: str, key_field: str,
                columns: list[str] | None = None,
                selected_key: str | None = None,
                color_rules: dict[str, dict[str, str]] | None = None,
                col_config: dict[str, dict] | None = None,
                row_rules: list[dict] | None = None,
                hidden_fields: list[str] | None = None,
                height: int | None = None,
                row_height: int = _SELECT_ROW_PX,
                checkbox_marker: bool = True,
                scroll_affordance: bool = False) -> str | None:
    """AgGrid 단일 선택 목록 어댑터(§0.5 — read_grid 와 별개 capability, 편집 자산 없음).

    MASTER_DETAIL 목록(큐)에서 한 행을 선택해 그 **자연키**(``key_field`` 값)를 돌려준다.
    편집 그리드(``render_master_grid``)의 ``_action`` 열·paste·hidden 편집메타·unsafe jscode 를
    쓰지 않는다 — 색/폭 규칙은 read_grid 와 같은 문자열식 빌더(:func:`_build_read_coldefs`)를
    공유하되 ``allow_unsafe_jscode=False`` 를 유지한다.

    불변식(구조적 강제)
    -------------------
    - ``col_config`` 는 :data:`_SELECT_COL_CONFIG_ALLOWED` 표현 속성만 허용한다 — ``editable``·
      ``cellRenderer``·``cellEditor`` 등 편집 자산을 주입하면 :class:`ValueError`(SELECT 는
      편집 capability 가 아니다).
    - ``key_field`` 는 존재·비어있지않음·행 간 유일·표시 컬럼 미포함을 만족해야 한다(위반 시
      :class:`ValueError`). 항상 hidden 으로 실려 표시 컬럼을 오염시키지 않는다.

    선택 계약
    ---------
    - AgGrid 네이티브 ``rowSelection="single"`` + 첫 열 checkboxSelection(마커) — JsCode 불요.
      선택행은 배경 틴트(``selected-bg``)와 체크(네이티브)로 **이중부호화**(§4)한다.
    - ``selected_key`` 가 주어지면 그 자연키에 해당하는 행을 pre-select 해 rerun 후에도 선택을
      복원한다(위치 비의존 — 표시 데이터에서 key_field 로 iloc 을 되찾는다). 자연키가 현재
      결과에서 사라졌으면 pre-select 대상이 없어 자동으로 미선택으로 떨어진다.
    - ``update_on=["selectionChanged"]`` — 선택 변경 시에만 rerun. 반환은 선택행
      ``selected_rows`` 의 ``key_field`` 문자열이며, 선택이 없으면 ``None``.
    - **rerun 유발원이 곧 이 반환**이므로 호출부는 이 값을 상세 렌더 **전에** 소비해 추가
      ``st.rerun`` 없이 상세를 그린다(선택 즉시 상세).

    ``row_height``: 행 피치(§0.6 실측 잠금). 기본 32(데스크톱 M/A 큐 밀도). USER·터치
    variant 는 44 를 준다(32×32 히트영역 계약과 정합).

    ``scroll_affordance``: 가로로 넘칠 때 스크롤바를 상시 노출로 칠한다
    (:data:`_HSCROLL_AFFORDANCE_CSS`). 모바일 오버레이 스크롤바 때문에 "오른쪽에 열이 더
    있다"는 신호가 사라지는 화면(USER 소관 목록)에서 켠다. 기본 꺼짐 — 다른 호출부의
    그리드 외관은 그대로다.
    """
    view, options, custom = _build_select_gridoptions(
        df, key_field=key_field, columns=columns, selected_key=selected_key,
        color_rules=color_rules, col_config=col_config, row_rules=row_rules,
        hidden_fields=hidden_fields, row_height=row_height,
        checkbox_marker=checkbox_marker, scroll_affordance=scroll_affordance,
    )
    h = height if height is not None else read_grid_height(len(view), row_px=row_height)

    response = AgGrid(
        view, gridOptions=options, key=key, height=h,
        update_on=["selectionChanged"],
        data_return_mode=DataReturnMode.AS_INPUT,
        allow_unsafe_jscode=False, theme="streamlit",
        custom_css=custom, show_toolbar=False, show_search=False,
    )
    return _selected_key(response.selected_rows, key_field)


# ============================================================ status_region
def status_region(summary: list[tuple[str, str]]) -> None:
    """요약/KPI = 한 줄 스트립(§0.3 status·§0.6 강제). ``summary``: ``[(label, value)]``.

    독립 카드 나열(구 ``erp-metric`` × N)이 아니라 hairline 구분 **단일 박스** 한 행으로
    렌더한다 — 카드가 행 높이를 넘어 겹치던 문제(4px)를 카드 자체를 없애 근본 해결한다.
    높이 ≤72px, 2행 이상 쌓지 않는다. readiness 배너는 lifecycle 소관이라 여기서 렌더하지
    않는다(호출부가 별도 처리)."""
    if not summary:
        return
    items = "".join(
        f"<div class='erp-strip-i'><span class='erp-strip-v'>{escape(str(value))}</span>"
        f"<span class='erp-strip-l'>{escape(str(label))}</span></div>"
        for label, value in summary
    )
    st.markdown(f"<div class='erp-strip'>{items}</div>", unsafe_allow_html=True)


def metric_strip(items: list[tuple]) -> None:
    """§1-F/§1-A 지표 타일 스트립(분석 화면 표준) — 좌측 2px 보더 + 라벨 + 26px 모노 값의
    2줄 타일. 제목 바로 아래 첫 블록(§0-4)에 둔다. 요약 수치가 있는 화면 공통 어휘.

    ``items``: ``[(label, value, unit, note, accent)]`` — accent True 면 오렌지 보더+값.
    ``note``(구 영문 오버라인)는 호환을 위해 튜플에 남겨두지만 더 이상 렌더하지 않는다
    (라벨과 중복이라 3줄→2줄로 축소). 새 지표를 발명하지 않고 기존 데이터 파생 수치만
    넘긴다(호출부 책임). CSS 는 _KIT_CSS(screen_frame 주입)가 소유하며 값 모노는
    0,3,0 규칙으로 강제한다."""
    if not items:
        return
    cells = []
    for label, value, unit, _note, accent in items:  # _note(영문 오버라인)은 더 이상 렌더하지 않음
        border = "#c2410c" if accent else "#e0dbd2"
        vcolor = "#b4451a" if accent else TOKENS["ink"]
        unit_html = (f"<span class='erp-metric-unit'>{escape(str(unit))}</span>"
                     if unit else "")
        cells.append(
            f"<div class='erp-metric' style='border-left:2px solid {border};'>"
            f"<span class='erp-metric-label'>{escape(str(label))}</span>"
            f"<div class='erp-metric-vrow'>"
            f"<span class='erp-metric-val' style='color:{vcolor};'>{escape(str(value))}</span>"
            f"{unit_html}</div></div>"
        )
    st.markdown(f"<div class='erp-metrics'>{''.join(cells)}</div>",
                unsafe_allow_html=True)


# ============================================================ master-detail (MASTER_DETAIL)
def master_detail_frame(*, list_ratio: float = 1.5, detail_ratio: float = 1.0,
                        gap: str = "medium"):
    """MASTER_DETAIL 의 primary(목록)+details(상세) 영역 split(§0.3). ``(list_col, detail_col)`` 반환.

    순수 레이아웃 — 그리드·데이터·선택 상태를 소유하지 않는다(선택 id·조회·readiness·
    쓰기 lifecycle 은 화면 소관, EDIT_GRID 에서 DraftState/run_save 가 화면 소관인 것과 동일 분리).
    """
    return tuple(st.columns([list_ratio, detail_ratio], gap=gap, vertical_alignment="top"))


def detail_empty(title: str, body: str) -> None:
    """상세 영역 '선택 없음 / 선택 만료' 안내 — 한 줄 스트립(§0.6 강제, ≤72px, 점선 대형 박스 금지).

    모든 MASTER_DETAIL 화면이 같은 문구·시각을 쓴다."""
    st.markdown(
        f"<div class='erp-empty'><span class='erp-empty-t'>{escape(title)}</span>"
        f"<span class='erp-empty-b'>{escape(body)}</span></div>",
        unsafe_allow_html=True,
    )


# ── 상세 순수 표시 primitive(§0.3 details·§2 토큰) ──
# MASTER_DETAIL 상세 패널의 **순수 표시** 조각: 상태 badge·짧은 메타 2열·전폭 읽기 필드.
# kit 은 도메인을 모른다 — status→색/라벨 매핑, 역할·인가·액션·facade 호출은 각 화면이 소유하고
# 여기엔 계산된 label/color/value 만 넘어온다. 다른 MASTER_DETAIL 화면이 복제 없이 재사용한다.
def status_badge_html(label: str, color: str) -> str:
    """상태 배지 HTML(색+라벨 이중부호화, §2 badge 11/600). 색·라벨은 호출부가 도메인에서 계산.

    중립 배지(color=``--ink-3``)는 읽는 라벨 글자색만 ``--ink-2`` 로 clamp 한다
    (DESIGN §159: 읽는 텍스트에 ``--ink-3`` 금지). 배경·테두리는 전달 색을 그대로 써
    중립 상태의 낮은 시각 강도를 유지한다. 색 신호가 있는 상태는 전달 색을 그대로 쓴다.
    """
    text = TOKENS["ink-2"] if color == TOKENS["ink-3"] else color
    # Claude Design 배지(ADOPTION_SPEC 항목6): pill 형태 radius 999 · 12.5px/600 · padding 3×11.
    # 색은 도메인이 넘긴 status 색을 배경 옅은 틴트(≈8%)+저채도 테두리(≈33%)로 파생한다
    # (라이프사이클 5종 정확 팔레트는 style.LIFECYCLE_BADGE — P3 도메인 배선에서 채택).
    return (
        f"<span style='display:inline-flex;align-items:center;padding:3px 11px;"
        f"border-radius:999px;font-size:12.5px;font-weight:600;line-height:1.4;color:{text};"
        f"border:1px solid {color}55;background:{color}14;white-space:nowrap;'>{escape(label)}</span>"
    )


# 등급 마크 셰브런 사다리(§3.1 handoff) — level 이 높을수록 상위 위험. 형식만 규정하고
# level→등급 매핑(S 가 최상위인지 등)은 도메인(화면) 소관이다. 색 + 방향/개수 이중부호화.
_GRADE_GLYPH = {4: "▲▲", 3: "▲", 2: "▴", 1: "▸", 0: "▽"}


def grade_mark_html(label: str, color: str, *, level: int | None = None) -> str:
    """등급 마크 HTML(§3.1 handoff) — 셰브런(방향/개수) + 색 텍스트, 배경 없음.

    pill 이 아니다(한 행/패널에 pill 형식 ≤1축 강제 — lifecycle 상태만 pill). 색약 안전을
    위해 색 + 셰브런 방향/개수로 이중부호화한다. ``level`` 이 ``None`` 이면(미확정 등)
    중립 점 마커로 렌더하고 글자색을 ``--ink-2`` 로 clamp 한다(읽는 텍스트 대비).
    ``label``·``color``·``level`` 은 호출부(도메인 owner)가 계산해 넘긴다."""
    glyph = "·" if level is None else _GRADE_GLYPH.get(int(level), "▸")
    # 읽는 텍스트에 --ink-3 금지(DESIGN §159) — 가장 옅은 중립색은 ink-2 로 clamp.
    text = TOKENS["ink-2"] if color == TOKENS["ink-3"] else color
    return (
        f"<span class='erp-grade' style='color:{text};'>"
        f"<span class='gm'>{glyph}</span>{escape(str(label))}</span>"
    )


def metadata_strip(cells: list[tuple]) -> None:
    """상세 상단 읽기 메타 스트립(§3.2 handoff) — 라벨(작게·ink-2) 위 / 값(진하게) 아래.

    ``cells``: ``[(label, value)]`` (value 는 평문 — escape) 또는 ``[(label, value, "html")]``
    (value 는 신뢰된 HTML — status_badge_html / grade_mark_html 결과 등). 핵심 컨텍스트를
    접지 않고 상시 노출하며(§0.6), 카드·그림자 없이 hairline 1개로 본문과 분리한다."""
    if not cells:
        return
    parts = []
    for cell in cells:
        label = cell[0]
        value = cell[1]
        is_html = len(cell) > 2 and cell[2] == "html"
        v = value if is_html else escape(str(value if value not in (None, "") else "-"))
        parts.append(
            f"<div class='erp-meta-i'><span class='erp-meta-l'>{escape(str(label))}</span>"
            f"<span class='erp-meta-v'>{v}</span></div>"
        )
    st.markdown(f"<div class='erp-meta'>{''.join(parts)}</div>", unsafe_allow_html=True)


def attention_strip(items: list[tuple]) -> None:
    """예외 현황 스트립(§3.5 handoff) — 지금 처리할 예외를 값>0 이면 danger-bg 틴트로 표시한다.

    **순수 표시 스트립**이다: 클릭/이동 어포던스(셰브런 등)를 두지 않는다 — 배선 없는 셰브런은
    거짓 어포던스가 되고(V1 QA Medium#1), 실제 이동은 각 화면 메뉴로 충분하므로 과배선하지
    않는다. ``items``: ``[(label, value, urgent)]`` — ``urgent`` 이 참이면 옅은 danger 틴트로
    강조, 거짓이면 중립. 값은 도메인(파사드)이 계산한 실집계만 싣는다(허수 금지). KPI 스트립과
    형제 스트립이며 각 항목 ≤72px(§0.6 정합)."""
    if not items:
        return
    parts = []
    for label, value, urgent in items:
        on = " on" if urgent else ""
        parts.append(
            f"<div class='erp-attn-i{on}'>"
            f"<span class='erp-attn-tx'><span class='erp-attn-v'>{escape(str(value))}</span>"
            f"<span class='erp-attn-l'>{escape(str(label))}</span></span></div>"
        )
    st.markdown(f"<div class='erp-attn'>{''.join(parts)}</div>", unsafe_allow_html=True)


def meta_col_html(pairs: list[tuple[str, str]]) -> str:
    """상세 메타 열 HTML(라벨 ``--ink-2`` + 값 ``--ink``, §2). 한 ``st.columns`` 셀 안에 쌓는다.

    레이아웃(2열 split)은 호출부 소관 — 이 함수는 한 열의 라벨/값 스택 HTML 만 만든다.
    """
    return "".join(
        f"<div style='margin:2px 0;line-height:1.5;'>"
        f"<span style='color:{TOKENS['ink-2']};font-size:12.5px;'>{escape(label)}</span> "
        f"<span style='color:{TOKENS['ink']};font-size:13px;font-weight:600;'>"
        f"{escape(value or '-')}</span></div>"
        for label, value in pairs
    )


def field_block(label: str, value: str) -> None:
    """긴 서술 전폭 읽기 필드 렌더(라벨 ``--ink-2`` + 본문 ``--ink``, 줄바꿈 보존). 순수 표시."""
    body = escape(value) if str(value or "").strip() else "-"
    st.markdown(
        f"<div style='margin:6px 0 0;'>"
        f"<div style='color:{TOKENS['ink-2']};font-size:12.5px;font-weight:600;"
        f"margin-bottom:1px;'>{escape(label)}</div>"
        f"<div style='color:{TOKENS['ink']};font-size:13px;line-height:1.5;"
        f"white-space:pre-wrap;'>{body}</div></div>",
        unsafe_allow_html=True,
    )


def detail_actions(page_id: str, actions: list[tuple]) -> dict:
    """상세 영역의 scope 쓰기 액션 행(§0.4: scope 액션은 소유 영역에 두되 공통 컴포넌트로).

    ``actions``: ``[(label, kind, disabled, help)]`` — kind ∈ {"primary","default"}; disabled/help 생략 가능.
    반환 ``{label: clicked}``. **순수 UI** — facade 호출·``current_user`` 전달·오류/stale 처리는
    전적으로 호출부 소관이다(이 함수는 ``db.*``·``auth.*`` 를 호출하지 않는다 — 신원 전송 계약을
    모호하게 만들지 않기 위함). FORM_ENTRY 의 form_submit 과 달리 폼이 아닌 일반 rerun 버튼이다.
    """
    if not actions:
        return {}
    cols = st.columns(len(actions))
    clicks: dict = {}
    for i, act in enumerate(actions):
        label = act[0]
        kind = act[1] if len(act) > 1 else "default"
        disabled = act[2] if len(act) > 2 else False
        help_ = act[3] if len(act) > 3 else None
        with cols[i]:
            clicks[label] = st.button(
                label, key=f"{page_id}_da_{i}",
                type="primary" if kind == "primary" else "secondary",
                disabled=disabled, help=help_, use_container_width=True,
            )
    return clicks
