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
.erp-detail-empty {{
  border: 1px dashed {TOKENS['line-strong']}; border-radius: 8px;
  background: {TOKENS['surface-2']}; padding: 20px 16px; text-align: center;
}}
.erp-detail-empty-t {{ font-size: 14px; font-weight: 600; color: {TOKENS['ink-2']}; }}
.erp-detail-empty-b {{ font-size: 12.5px; color: {TOKENS['ink-2']}; margin-top: 4px; line-height: 1.5; }}
/* help(툴팁) 래퍼가 씌워진 버튼도 앱 기본 버튼 크기를 따르게 — modules/ui.py 의 직계자식
   선택자(.stButton > button)가 툴팁 DOM 체인을 못 잡아 생기는 높이 불일치 보정(detail_actions
   처럼 help 유무가 섞인 버튼을 한 행에 둘 때 가시화). 크기만 맞추는 저위험 규칙. */
.stTooltipHoverTarget > button {{ min-height: 2.15rem; font-size: 0.83rem; }}
</style>
"""


def read_grid_height(nrows: int) -> int:
    natural = _READ_HEADER_PX + max(int(nrows), 1) * _READ_ROW_PX + _READ_CHROME_PX
    return max(_READ_MIN_PX, min(natural, _READ_MAX_PX))


# ============================================================ screen_frame
def screen_frame(archetype: str, *, title: str, desc: str, breadcrumb: str,
                 badges: str | None = None) -> None:
    """화면 헤더(브레드크럼·제목·모드배지) — scaffold.page_chrome 위임(영역 순서의 title 슬롯).

    키트 CSS(우측 라벨·메트릭)를 이 진입점에서 매 렌더 주입한다 — 모든 화면이 screen_frame
    을 먼저 호출하므로 이후 condition_panel/status_region 의 클래스가 항상 스타일을 받는다."""
    scaffold.page_chrome(
        archetype, title=title, desc=desc, breadcrumb=breadcrumb,
        badges=badges if badges is not None else scaffold.mode_badge(),
    )
    st.markdown(_KIT_CSS, unsafe_allow_html=True)


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


def _render_widget(page_id: str, f: Field):
    wkey = f.widget_key if f.widget_key else f"{page_id}_{f.key}"
    if f.kind == "checkbox":
        return st.checkbox(f.label, value=bool(f.value), key=wkey,
                           label_visibility="collapsed", disabled=f.disabled, help=f.help)
    if f.kind == "date":
        return st.date_input(f.label, value=f.value, key=wkey,
                             label_visibility="collapsed", disabled=f.disabled, help=f.help)
    if f.kind == "text":
        return st.text_input(f.label, value=f.value or "", key=wkey,
                             label_visibility="collapsed", disabled=f.disabled,
                             help=f.help, placeholder=f.placeholder)
    return st.selectbox(f.label, f.options, key=wkey,
                        format_func=f.format_func or (lambda x: x),
                        label_visibility="collapsed", disabled=f.disabled,
                        help=f.help, placeholder=f.placeholder)


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
              row_rules: list[dict] | None = None,
              hidden_fields: list[str] | None = None,
              height: int | None = None) -> None:
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
    frame = df.copy()
    for c in cols:
        if c not in frame.columns:
            frame[c] = ""
        frame[c] = frame[c].fillna("").astype(str)
    for h in hidden:
        if h not in frame.columns:
            frame[h] = None  # 행-규칙이 참조하는 플래그(불리언 등)는 원형 그대로 싣는다.

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
                "read_grid: 컬럼이 color_rules 와 row_rules 에 동시에 지정됨(상호배타 위반): "
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
        frame[cols + hidden], gridOptions=options, key=key, height=h,
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
    cols = st.columns(len(summary))
    for col, (label, value) in zip(cols, summary):
        with col:
            st.markdown(
                f"<div class='erp-metric'><div class='erp-metric-v'>{value}</div>"
                f"<div class='erp-metric-l'>{label}</div></div>",
                unsafe_allow_html=True,
            )


# ============================================================ master-detail (MASTER_DETAIL)
def master_detail_frame(*, list_ratio: float = 1.5, detail_ratio: float = 1.0,
                        gap: str = "medium"):
    """MASTER_DETAIL 의 primary(목록)+details(상세) 영역 split(§0.3). ``(list_col, detail_col)`` 반환.

    순수 레이아웃 — 그리드·데이터·선택 상태를 소유하지 않는다(선택 id·조회·readiness·
    쓰기 lifecycle 은 화면 소관, EDIT_GRID 에서 DraftState/run_save 가 화면 소관인 것과 동일 분리).
    """
    return tuple(st.columns([list_ratio, detail_ratio], gap=gap, vertical_alignment="top"))


def detail_empty(title: str, body: str) -> None:
    """상세 영역 '선택 없음 / 선택 만료' 안내 — 모든 MASTER_DETAIL 화면이 같은 문구·시각을 쓰도록."""
    st.markdown(
        f"<div class='erp-detail-empty'><div class='erp-detail-empty-t'>{title}</div>"
        f"<div class='erp-detail-empty-b'>{body}</div></div>",
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
