"""AgGrid 편집판 — HTML 읽기전용판과 **같은 화면을 두 방식으로** 그려 비교한다.

이것이 이 데모의 마지막 미지수다. 목업의 격자는 페이지와 같은 DOM 에 사는 `<table>`
인데, Streamlit 에서 편집 가능한 격자는 AgGrid 뿐이고 AgGrid 는 iframe 안에서 돈다.

측정하려는 것 세 가지:
  ① iframe 이 부모의 웹폰트(Pretendard)를 받는가 — DESIGN §7.2-23 이 "못 받는다"고 실측해 뒀다
  ② 셀 칩(테두리 있는 작은 상자)을 그릴 수 있는가 — cellRenderer 없이
  ③ 행 높이·머리글 높이·1px 선을 목업과 맞출 수 있는가

운영 앱 규약을 따른다: **JsCode 셀 렌더러를 쓰지 않는다.**
`views/master/grid.py:255` 가 "JsCode 셀 렌더러는 Streamlit Cloud Python 3.14 배포
환경에서 실행되지 않는다"고 적어 뒀다. 그래서 문자열식 `cellClassRules` + `custom_css`
로만 색을 입힌다 — 그 제약이 곧 ②의 답이 된다.
"""
import pandas as pd
import streamlit as st
from st_aggrid import AgGrid, DataReturnMode

import data as D
import ui as U

FONT_STACK = "'Pretendard Variable',Pretendard,'Malgun Gothic',system-ui,sans-serif"

#: 목업 토큰을 AgGrid 내부 클래스에 옮긴 것. iframe 안이라 부모 CSS 가 닿지 않아
#: 전역 스타일을 여기에 **다시 적어야 한다**(중복의 출처).
_BASE_CSS = {
    ".ag-root-wrapper": {
        "border": f"1px solid {U.LINE_OUTER}", "border-radius": "0",
        "font-family": FONT_STACK,
    },
    ".ag-header": {"background": U.HEAD_BG, "border-bottom": f"1px solid {U.LINE_OUTER}"},
    ".ag-header-cell": {
        "border-right": f"1px solid {U.LINE_HEAD}", "padding-left": "8px",
        "padding-right": "8px",
    },
    ".ag-header-cell-label": {"justify-content": "center"},
    ".ag-header-cell-text": {
        "font-size": "11.5px", "font-weight": "700", "color": U.INK,
        "font-family": FONT_STACK,
    },
    ".ag-cell": {
        "font-size": "12.5px", "color": U.INK, "font-family": FONT_STACK,
        "border-right": f"1px solid {U.LINE_COL}",
        "display": "flex", "align-items": "center",
        "padding-left": "8px", "padding-right": "8px",
        "font-variant-numeric": "tabular-nums",
    },
    ".ag-row": {"border-bottom": f"1px solid {U.LINE_ROW}", "background": "#fff"},
    ".ag-row-hover": {"background": "#f7fafd"},
    ".ag-row-selected": {"background": f"{U.ROW_PICK} !important"},
    ".ag-cell-focus": {"outline": f"2px solid {U.ACCENT} !important", "outline-offset": "-2px"},
    ".ag-paging-panel": {"display": "none"},
}

#: 근무형태 색 — cellRenderer 없이 넣을 수 있는 최대치는 **글자색 + 옅은 배경**이다.
#: 목업의 "테두리 있는 칩"은 셀 안에 별도 span 이 필요해서 재현되지 않는다(측정 대상 ②).
_WT_CSS = {}
for _name, _st in D.WT.items():
    _WT_CSS[f".wt-{abs(hash(_name)) % 9999}"] = {}
_WT_KEY = {n: f"wt{i}" for i, n in enumerate(D.WT)}
for _name, _cls in _WT_KEY.items():
    _s = D.WT[_name]
    _WT_CSS[f".{_cls}"] = {
        "color": _s["fg"], "justify-content": "center",
        "font-size": "11.5px", "font-weight": "600",
        "padding-left": "2px", "padding-right": "2px",
    }
_WT_CSS = {k: v for k, v in _WT_CSS.items() if v}

_WT_RULES = {cls: f"x == '{name}'" for name, cls in _WT_KEY.items()}


def _center(width: int | None = None, **extra) -> dict:
    d = {"cellStyle": {"justifyContent": "center"}}
    if width:
        d |= {"width": width, "minWidth": width, "maxWidth": width}
    return d | extra


def plan_grid() -> None:
    """근무표 편성 — 31일 편집 격자. 목업 대비 무엇이 남고 무엇이 빠지는지 본다."""
    n_days = 31
    rows = []
    for i, (emp, name, dept, team, pat) in enumerate(D.PEOPLE, 1):
        row = {"No": i, "사번": emp, "성명": name, "부서": dept, "조": team or "—"}
        for d, t in enumerate(D.PATTERNS[pat][:n_days], 1):
            row[str(d)] = t
        rows.append(row)
    df = pd.DataFrame(rows)

    cols = [
        {"field": "No", "pinned": "left", "width": 42, "minWidth": 42, "maxWidth": 42,
         "editable": False, "cellStyle": {"justifyContent": "center", "color": U.MUTED,
                                          "fontSize": "11px"}},
        {"field": "사번", "pinned": "left", "width": 92, "minWidth": 92, "editable": False},
        {"field": "성명", "pinned": "left", "width": 76, "minWidth": 76, "editable": False,
         "cellStyle": {"fontWeight": "600"}},
        {"field": "부서", "width": 124, "minWidth": 124, "editable": False,
         "cellStyle": {"color": U.INK3}},
        {"field": "조", "width": 50, "minWidth": 50, "editable": False,
         "cellStyle": {"justifyContent": "center", "color": U.INK3}},
    ]
    for d in range(1, n_days + 1):
        w = D.WEEKDAYS[(d - 1) % 7]
        cols.append({
            "field": str(d), "headerName": f"{d} {w}",
            "width": 44, "minWidth": 44, "maxWidth": 44,
            "editable": True,                       # ← 여기가 HTML 판과 갈리는 지점
            "cellEditor": "agSelectCellEditor",
            "cellEditorParams": {"values": list(D.WT)},
            "cellClassRules": _WT_RULES,
        })

    options = {
        "defaultColDef": {"resizable": True, "sortable": False, "filter": False,
                          "suppressMovable": True},
        "columnDefs": cols,
        "rowHeight": U.ROW_H,          # 29 — 목업과 같은 값
        "headerHeight": U.ROW_H,
        "suppressFieldDotNotation": True,
        "enableRangeSelection": True,   # Excel 붙여넣기의 전제
        "suppressMovableColumns": True,
    }
    AgGrid(
        df, gridOptions=options, key="ag_plan",
        height=U.ROW_H * (len(df) + 1) + 2,
        theme="streamlit", custom_css=_BASE_CSS | _WT_CSS,
        update_on=[("cellValueChanged", 200)],
        data_return_mode=DataReturnMode.AS_INPUT,
        allow_unsafe_jscode=False, show_toolbar=False, show_search=False,
        fit_columns_on_grid_load=False,
    )


def user_grid() -> None:
    """사용자 관리 — 기준정보 편집 격자(EDIT_GRID)."""
    df = pd.DataFrame(
        D.USERS,
        columns=["사번", "성명", "부서", "부서코드", "직급", "권한", "이메일",
                 "입사일", "퇴사일", "표시순서", "재직"])

    role_rules = {"role-admin": "x == '관리자'", "role-mgr": "x == '매니저'",
                  "role-safe": "x == '안전담당'"}
    cols = [
        {"field": "사번", "width": 108, "editable": False, "checkboxSelection": True,
         "headerCheckboxSelection": True},
        {"field": "성명", "width": 84, "editable": True, "cellStyle": {"fontWeight": "600"}},
        {"field": "부서", "width": 168, "editable": True,
         "cellEditor": "agSelectCellEditor",
         "cellEditorParams": {"values": D.DEPARTMENTS[1:]}},
        {"field": "부서코드", "width": 100, "editable": False} | _center(),
        {"field": "직급", "width": 68, "editable": True} | _center(),
        {"field": "권한", "width": 92, "editable": True,
         "cellEditor": "agSelectCellEditor",
         "cellEditorParams": {"values": ["관리자", "매니저", "안전담당", "조원"]},
         "cellClassRules": role_rules} | _center(),
        {"field": "이메일", "width": 210, "editable": True,
         "cellStyle": {"color": U.INK3}},
        {"field": "입사일", "width": 100, "editable": True} | _center(),
        {"field": "퇴사일", "width": 100, "editable": True,
         "cellClassRules": {"leave-date": "x != '—'"}} | _center(),
        {"field": "표시순서", "width": 84, "editable": True,
         "cellStyle": {"justifyContent": "flex-end", "color": "#777"}},
        {"field": "재직", "width": 68, "editable": True,
         "cellEditor": "agSelectCellEditor", "cellEditorParams": {"values": ["재직", "퇴직"]},
         "cellClassRules": {"leave-date": "x == '퇴직'"}} | _center(),
    ]
    options = {
        "defaultColDef": {"resizable": True, "sortable": True, "filter": False,
                          "suppressMovable": True},
        "columnDefs": cols,
        "rowHeight": U.ROW_H, "headerHeight": U.ROW_H,
        "rowSelection": "multiple", "suppressRowClickSelection": True,
        "enableRangeSelection": True,
    }
    extra = {
        ".role-admin": {"color": U.ACCENT, "font-weight": "700", "justify-content": "center"},
        ".role-mgr": {"color": "#1c6b41", "font-weight": "700", "justify-content": "center"},
        ".role-safe": {"color": "#17457f", "font-weight": "700", "justify-content": "center"},
        ".leave-date": {"color": "#a3282a", "justify-content": "center"},
    }
    AgGrid(
        df, gridOptions=options, key="ag_user",
        height=U.ROW_H * (len(df) + 1) + 2,
        theme="streamlit", custom_css=_BASE_CSS | extra,
        update_on=[("cellValueChanged", 200)],
        data_return_mode=DataReturnMode.AS_INPUT,
        allow_unsafe_jscode=False, show_toolbar=False, show_search=False,
        fit_columns_on_grid_load=False,
    )
