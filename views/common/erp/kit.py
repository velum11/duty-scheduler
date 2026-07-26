"""중립 구조 키트 구현 (KP-standard §0.2) — 레이아웃 전용, 도메인 lifecycle 미포함.

영역 순서(§0.3): title → top actions(page) → conditions → primary → details → status.
읽기 화면(READ_VIEW)에 필요한 subset 먼저 제공한다. 편집(EDIT/SELECT/MATRIX) 어댑터는
후속. 그리드는 AgGrid 단일 렌더러를 쓰되 READ 는 편집 자산(action열·paste·editable·
allow_unsafe_jscode)을 넣지 않는다(§0.5). 색은 cellClassRules 문자열식 + custom_css 로만.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field as dc_field
from typing import Any, Callable

import pandas as pd
import streamlit as st
from st_aggrid import AgGrid, DataReturnMode

from views.common import scaffold
from views.master import style

TOKENS = style.TOKENS

# ── 밀도 토큰 (DESIGN.md §2 — 데스크톱 읽기 그리드) ──
_READ_ROW_PX = 34
_READ_HEADER_PX = 36
_READ_CHROME_PX = 16
_READ_MIN_PX = 120
_READ_MAX_PX = 460

_NO_ROWS = (
    "<span style='color:%s;font-size:.82rem;'>표시할 데이터가 없습니다</span>"
    % TOKENS["ink-3"]
)

# 한 번만 주입하는 키트 CSS(우측 인라인 라벨·요약 메트릭). st-key 스코프 불필요한
# 표현 요소만 담으며 사이드바·기존 화면 CSS를 건드리지 않는다.
_KIT_CSS = f"""
<style>
.erp-lbl {{
  text-align: right; color: {TOKENS['ink-2']}; font-size: 13px; font-weight: 600;
  line-height: 1.2; padding-right: 2px; white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis;
}}
.erp-metric {{
  border: 1px solid {TOKENS['line-strong']}; border-radius: 8px;
  background: {TOKENS['surface']}; padding: 10px 12px;
}}
.erp-metric-v {{ font-size: 20px; font-weight: 700; color: {TOKENS['ink']}; font-variant-numeric: tabular-nums; }}
.erp-metric-l {{ font-size: 12px; color: {TOKENS['ink-2']}; margin-top: 2px; }}
</style>
"""


def _inject_css() -> None:
    if not st.session_state.get("_erp_kit_css"):
        st.markdown(_KIT_CSS, unsafe_allow_html=True)
        st.session_state["_erp_kit_css"] = True


def read_grid_height(nrows: int) -> int:
    natural = _READ_HEADER_PX + max(int(nrows), 1) * _READ_ROW_PX + _READ_CHROME_PX
    return max(_READ_MIN_PX, min(natural, _READ_MAX_PX))


# ============================================================ screen_frame
def screen_frame(archetype: str, *, title: str, desc: str, breadcrumb: str,
                 badges: str | None = None) -> None:
    """화면 헤더(브레드크럼·제목·모드배지) — scaffold.page_chrome 위임(영역 순서의 title 슬롯).

    매 렌더마다 세션 플래그를 초기화해 키트 CSS를 이 run 에서 다시 주입한다."""
    st.session_state["_erp_kit_css"] = False
    scaffold.page_chrome(
        archetype, title=title, desc=desc, breadcrumb=breadcrumb,
        badges=badges if badges is not None else scaffold.mode_badge(),
    )
    _inject_css()


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


# ============================================================ condition_panel
@dataclass
class Field:
    """조건 패널의 한 필드. select/date/checkbox/text."""
    key: str
    label: str
    kind: str = "select"
    options: list = dc_field(default_factory=list)
    value: Any = None
    disabled: bool = False
    format_func: Callable | None = None
    help: str | None = None


def _render_widget(page_id: str, f: Field):
    wkey = f"{page_id}_{f.key}"
    if f.kind == "checkbox":
        return st.checkbox(f.label, value=bool(f.value), key=wkey,
                           label_visibility="collapsed", disabled=f.disabled, help=f.help)
    if f.kind == "date":
        return st.date_input(f.label, value=f.value, key=wkey,
                             label_visibility="collapsed", disabled=f.disabled, help=f.help)
    if f.kind == "text":
        return st.text_input(f.label, value=f.value or "", key=wkey,
                             label_visibility="collapsed", disabled=f.disabled, help=f.help)
    return st.selectbox(f.label, f.options, key=wkey,
                        format_func=f.format_func or (lambda x: x),
                        label_visibility="collapsed", disabled=f.disabled, help=f.help)


def condition_panel(page_id: str, fields: list[Field], *, cols: int = 3) -> dict:
    """col-N 우측 인라인 라벨 조건 패널(§0.6). 반환 ``{field.key: value}``.

    각 행은 ``[라벨,widget]`` 쌍을 cols 개 나열한 **단일** ``st.columns``(중첩 없음).
    라벨은 우측정렬 markdown, widget 은 실제 label + ``label_visibility='collapsed'``.
    """
    values: dict = {}
    ratios = [0.42, 1.0] * cols
    with st.container(border=True):
        for start in range(0, len(fields), cols):
            row = fields[start:start + cols]
            slots = st.columns(ratios, vertical_alignment="center")
            for j, f in enumerate(row):
                with slots[j * 2]:
                    st.markdown(f"<div class='erp-lbl'>{f.label}</div>",
                                unsafe_allow_html=True)
                with slots[j * 2 + 1]:
                    values[f.key] = _render_widget(page_id, f)
    return values


# ============================================================ read_grid
_READ_BASE_CSS = {
    ".ag-header-cell": {"font-weight": "600", "font-size": "12.5px"},
    ".ag-cell": {"font-size": "13px", "display": "flex", "align-items": "center"},
}


def read_grid(df: pd.DataFrame, *, columns: list[str] | None = None, key: str,
              color_rules: dict[str, dict[str, str]] | None = None,
              col_config: dict[str, dict] | None = None,
              height: int | None = None) -> None:
    """AgGrid READ 어댑터(§0.5) — 편집 자산 없음. 색은 cellClassRules 문자열식.

    ``color_rules``: ``{컬럼명: {값: hex색}}`` — 값 일치 시 배경(13% alpha)+ink+600.
    텍스트는 항상 유지(색은 보조 신호). 편집·paste·action열·allow_unsafe_jscode 없음.
    ``col_config``: ``{컬럼명: {width|flex|minWidth|maxWidth|cellClass ...}}`` — 폭·정렬 주입.
    미지정 컬럼은 ``flex=1, minWidth=90`` 으로 컨테이너 폭을 채운다(AgGrid 200px 기본값이
    다열에서 가로 오버플로를 만드는 문제 방지 — master 그리드가 폭을 지정하는 것과 동일 취지).
    """
    cols = list(columns) if columns else list(df.columns)
    frame = df.copy()
    for c in cols:
        if c not in frame.columns:
            frame[c] = ""
        frame[c] = frame[c].fillna("").astype(str)

    rules = color_rules or {}
    sizing = col_config or {}
    custom = dict(_READ_BASE_CSS)
    coldefs: list[dict] = []
    for ci, c in enumerate(cols):
        cd = {"field": c, "headerName": c, "editable": False, "sortable": False,
              "filter": False, "resizable": True}
        cfg = sizing.get(c)
        if cfg:
            cd.update(cfg)
        elif "width" not in cd:
            cd.setdefault("flex", 1)
            cd.setdefault("minWidth", 90)
        crule = rules.get(c)
        if crule:
            ccr: dict = {}
            for vi, (val, color) in enumerate(crule.items()):
                cls = f"erp-cc-{ci}-{vi}"
                # ag-grid cellClassRules 문자열식: x = 셀 값. JsCode 아님 → unsafe 불필요.
                ccr[cls] = f"x == {json.dumps(str(val))}"
                custom[f".{cls}"] = {
                    "background-color": f"{color}22",
                    "color": TOKENS["ink"],
                    "font-weight": "600",
                }
            cd["cellClassRules"] = ccr
        coldefs.append(cd)

    options = {
        "columnDefs": coldefs,
        "defaultColDef": {"resizable": True, "sortable": False, "filter": False},
        "rowHeight": _READ_ROW_PX, "headerHeight": _READ_HEADER_PX,
        "suppressRowClickSelection": True,
        "suppressDragLeaveHidesColumns": True,
        "overlayNoRowsTemplate": _NO_ROWS,
    }
    h = height if height is not None else read_grid_height(len(frame))
    AgGrid(
        frame[cols], gridOptions=options, key=key, height=h,
        data_return_mode=DataReturnMode.AS_INPUT,
        allow_unsafe_jscode=False, theme="streamlit",
        custom_css=custom, show_toolbar=False, show_search=False,
    )


# ============================================================ status_region
def status_region(summary: list[tuple[str, str]]) -> None:
    """요약 카드 행(§0.3 status 영역). ``summary``: ``[(label, value)]``.

    readiness 배너는 lifecycle 소관이라 여기서 렌더하지 않는다(호출부가 별도 처리).
    """
    if not summary:
        return
    _inject_css()
    cols = st.columns(len(summary))
    for col, (label, value) in zip(cols, summary):
        with col:
            st.markdown(
                f"<div class='erp-metric'><div class='erp-metric-v'>{value}</div>"
                f"<div class='erp-metric-l'>{label}</div></div>",
                unsafe_allow_html=True,
            )
