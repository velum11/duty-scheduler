"""근무표/기준정보 업무 화면이 공유하는 공통 프레임과 헬퍼.

화면별 파일(schedule_edit, schedule_view, master_*)은 각자 render() 만 두고,
아래 공통 요소를 조합해 DESIGN.md §10 구조를 구성한다:
  페이지 제목 → 한 줄 설명 → 조회 조건 카드 → 요약 카드 → 데이터 그리드 → 하단 액션.

조회는 명시적 [조회] 버튼으로만 갱신하며(자동 조회 없음), 그리드는 읽기 전용으로
근무코드 색상을 입힌다. 기준정보/근무표의 등록·수정 저장 로직은 이후 단계에서
이 화면 위에 얹는다.
"""
import calendar
from datetime import date
from html import escape

import pandas as pd
import streamlit as st
from st_aggrid import AgGrid, DataReturnMode, GridOptionsBuilder, JsCode

from modules import db, ui

ALL = "(전체)"


def work_type_display() -> tuple[dict, dict]:
    """근무형태 표시 계약 — (display_of, color_of).

    - display_of: 내부 코드 -> 화면 표시값(약칭). 약칭이 비었거나 같은 약칭이 여러
      코드에 걸리면(왕복 모호) 코드를 그대로 표시한다.
    - color_of: 표시값과 코드 양쪽을 색상(#RRGGBB)에 매핑 — 셀이 약칭으로 바뀌어도
      같은 코드는 같은 색을 유지한다(색은 코드에 귀속).
    조회 화면(월간·개인)이 셀을 약칭·색상으로 일관 표시하도록 공통으로 쓴다.
    """
    wt = db.get_work_types()
    active = wt[wt["is_active"]] if not wt.empty else wt
    label_codes: dict[str, set] = {}
    for _, r in active.iterrows():
        code = str(r["code"]).strip()
        label = str(r["short_label"]).strip()
        if code and label:
            label_codes.setdefault(label, set()).add(code)
    display_of, color_of = {}, {}
    for _, r in active.iterrows():
        code = str(r["code"]).strip()
        label = str(r["short_label"]).strip()
        color = str(r["color"] or "").strip()
        disp = label if label and len(label_codes.get(label, set())) == 1 else code
        if code:
            display_of[code] = disp
            if color.startswith("#"):
                color_of[code] = color
                color_of[disp] = color
    return display_of, color_of


def editor_has_changes(key: str) -> bool:
    """data_editor의 미저장 추가·수정·삭제가 있는지 확인한다."""
    state = st.session_state.get(key)
    if not isinstance(state, dict):
        return False
    return any(state.get(field) for field in ("edited_rows", "added_rows", "deleted_rows"))


# ---------- 조회 상태 (명시적 [조회] 버튼으로만 갱신) ----------
def run_query(page_id: str, clicked: bool, params: dict):
    """[조회] 클릭 시 조건을 세션에 저장하고, 저장된 조건을 반환한다."""
    key = f"q_{page_id}"
    if clicked:
        st.session_state[key] = params
    return st.session_state.get(key)


def grid_height(nrows: int) -> int:
    return min(38 * nrows + 40, 560)


# ---------- 폼 기반 기준정보 (한글 IME 안전) ----------
def list_height(nrows: int) -> int:
    """읽기 전용 목록 그리드 높이 (내부 스크롤)."""
    return min(38 * max(nrows, 1) + 40, 420)


def pick_row(display_df: pd.DataFrame, key: str, height: int):
    """읽기 전용 목록 그리드에서 단일 행 선택. 선택 위치(int) 또는 None 반환.

    st.data_editor 셀 직접 입력(한글 IME 충돌)을 피하려고 목록은 조회·선택 전용으로
    쓰고, 실제 입력은 st.form 위젯에서 받는다. key 를 바꾸면 선택이 초기화된다."""
    event = st.dataframe(
        display_df,
        key=key,
        on_select="rerun",
        selection_mode="single-row",
        hide_index=True,
        width="stretch",
        height=height,
    )
    rows = event.selection["rows"]
    return rows[0] if rows else None


# ---------- 편집 화면 공통 (기준정보 등록/수정) ----------
def master_editor_height() -> int:
    """기준정보 편집기의 작은 화면용 안전한 최소 높이."""
    return 360


def master_editor_container():
    """뷰포트에 맞춰 확장되는 기준정보 편집기 컨테이너."""
    st.markdown(
        """
        <style>
        .st-key-master_editor div[data-testid="stDataFrame"],
        .st-key-master_editor div[data-testid="stDataFrameResizable"] {
          height: clamp(360px, calc(100dvh - 27rem), 760px) !important;
          min-height: 360px;
        }
        .st-key-master_editor div[data-testid="stDataFrame"] > div {
          height: 100% !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    return st.container(key="master_editor")


def master_data_editor(data, **kwargs):
    """공통 반응형 컨테이너 안에 기준정보 data_editor를 배치한다."""
    with master_editor_container():
        return st.data_editor(data, height=master_editor_height(), **kwargs)


# AG Grid community 는 다중 셀 clipboard 분배(processDataFromClipboard)가 없다
# (Enterprise 전용). 네이티브 paste 이벤트의 clipboardData 를 직접 파싱해
# 탭(열)/줄바꿈(행) 2차원 배열로 포커스 셀부터 분배한다. 권한 프롬프트가 없고
# Excel/한셀 등 표 형태 클립보드와 그대로 호환된다.
_NATIVE_PASTE_HANDLER = JsCode(
    """
    function(params) {
      const api = params.api;
      document.addEventListener('paste', function(event) {
        if (api.getEditingCells().length > 0) { return; }  // 셀 편집 중 = 단일 셀 입력
        const focused = api.getFocusedCell();
        if (!focused) { return; }
        const text = (event.clipboardData || window.clipboardData).getData('text/plain');
        if (!text) { return; }
        event.preventDefault();
        const lines = text.replace(/\\r/g, '').split('\\n');
        while (lines.length && lines[lines.length - 1] === '') { lines.pop(); }
        const table = lines.map(function(line) { return line.split('\\t'); });
        const missing = focused.rowIndex + table.length - api.getDisplayedRowCount();
        if (missing > 0) {
          api.applyTransaction({
            add: Array.from({ length: missing }, function() { return {}; }),
          });
        }
        const columns = api.getAllDisplayedColumns();
        const start = columns.findIndex(function(column) {
          return column.getColId() === focused.column.getColId();
        });
        table.forEach(function(values, rowOffset) {
          const node = api.getDisplayedRowAtIndex(focused.rowIndex + rowOffset);
          if (!node) { return; }
          values.forEach(function(value, columnOffset) {
            const column = columns[start + columnOffset];
            if (!column) { return; }
            const colDef = column.getColDef();
            const editable = typeof colDef.editable === 'function'
              ? colDef.editable({ node: node, data: node.data, column: column, colDef: colDef })
              : colDef.editable !== false;
            if (!editable) { return; }
            // 체크박스 컬럼은 Excel 의 TRUE/1/사용 등 텍스트를 boolean 으로 변환한다.
            // (기존 행은 boolean 타입으로 추론되어 문자열이 false 로 캐스팅됨)
            if (column.getColDef().cellEditor === 'agCheckboxCellEditor') {
              const flag = String(value).trim().toLowerCase();
              value = ['true', '1', 'y', 'yes', 't', 'on', '사용', '재직'].indexOf(flag) >= 0;
            }
            node.setDataValue(column.getColId(), value);
          });
        });
      });
    }
    """
)

# 마지막 행에서 편집을 마치면 즉시 새 빈 행을 붙여, 서버 rerun 을 기다리지 않고
# 연속으로 신규 행을 입력할 수 있게 한다 (서버측에서 빈 버퍼 행은 저장에서 제외).
_APPEND_ROW_ON_LAST_EDIT = JsCode(
    """
    function(params) {
      const api = params.api;
      if (params.rowIndex === api.getDisplayedRowCount() - 1) {
        api.applyTransaction({ add: [{}] });
      }
    }
    """
)


def editable_aggrid(
    data: pd.DataFrame,
    key: str,
    columns: dict,
    height: int | None = None,
    blank_rows: int = 1,
) -> pd.DataFrame:
    """Excel 범위 붙여넣기용 빈 행을 포함하는 기준정보 편집 그리드.

    AgGrid 커스텀 컴포넌트의 런타임 행 추가는 브라우저/버전별로 불안정할 수 있다.
    따라서 붙여넣기 대상이 될 빈 행을 미리 확보한다. 저장 검증은 완전히 빈 행을
    건너뛰므로 버퍼 행은 데이터로 저장되지 않는다.
    """
    frame = data.copy().reset_index(drop=True)
    for name, kind in columns.items():
        if name not in frame:
            frame[name] = False if kind == "bool" else 0 if kind == "number" else ""
        elif kind == "text":
            frame[name] = frame[name].fillna("").astype("string")
    text_columns = [name for name, kind in columns.items() if kind != "bool" and kind != "number"]
    # 이전 rerun 에서 반환된 빈 버퍼는 제거하고, 필요한 수만큼 다시 붙인다.
    # 이렇게 해야 반복 rerun 에도 빈 행이 누적되지 않는다.
    while not frame.empty and not any(
        str(frame.iloc[-1][name]).strip() for name in text_columns
    ):
        frame = frame.iloc[:-1].reset_index(drop=True)

    empty_row = {
        name: False if kind == "bool" else 0 if kind == "number" else ""
        for name, kind in columns.items()
    }
    if blank_rows > 0:
        frame = pd.concat(
            [frame, pd.DataFrame([empty_row] * blank_rows)],
            ignore_index=True,
        )

    builder = GridOptionsBuilder.from_dataframe(frame)
    builder.configure_default_column(editable=True, resizable=True, sortable=False, filter=False)
    builder.configure_grid_options(
        # 단일 클릭에서 편집을 시작하면 Ctrl+V가 브라우저 텍스트 입력으로 처리되어
        # 여러 행/열이 한 셀에 들어간다. 클릭은 선택만, 편집은 더블 클릭/Enter로 한다.
        singleClickEdit=False,
        stopEditingWhenCellsLoseFocus=True,
        enterNavigatesVertically=True,
        enterNavigatesVerticallyAfterEdit=True,
        onGridReady=_NATIVE_PASTE_HANDLER,
        onCellEditingStopped=_APPEND_ROW_ON_LAST_EDIT,
        suppressRowClickSelection=True,
    )
    for name, kind in columns.items():
        if kind == "bool":
            builder.configure_column(name, checkboxSelection=False, cellEditor="agCheckboxCellEditor")
        elif isinstance(kind, (list, tuple)):
            builder.configure_column(name, cellEditor="agSelectCellEditor", cellEditorParams={"values": list(kind)})
    response = AgGrid(
        frame,
        gridOptions=builder.build(),
        key=key,
        height=height or master_editor_height(),
        # 붙여넣기는 setDataValue 로 셀마다 cellValueChanged 를 발생시키므로
        # 짧은 debounce 로 한 번의 rerun 으로 묶는다.
        update_on=[("cellValueChanged", 300)],
        data_return_mode=DataReturnMode.AS_INPUT,
        allow_unsafe_jscode=True,
        theme="streamlit",
        show_toolbar=False,
        show_search=False,
    )
    result = response.data
    if not isinstance(result, pd.DataFrame):
        return frame
    # JS 쪽 행 추가(applyTransaction)로 생긴 undefined 필드는 NaN 으로 돌아온다.
    # 그대로 두면 str(nan)="nan" 이 빈 행 검사를 통과하므로 열 타입별로 정규화한다.
    result = result.copy()
    for name, kind in columns.items():
        if name not in result.columns:
            continue
        if kind == "bool":
            result[name] = result[name].fillna(False).map(grid_bool)
        elif kind == "number":
            result[name] = pd.to_numeric(result[name], errors="coerce").fillna(0).astype("int64")
        else:
            result[name] = result[name].fillna("").astype("string")
    return result


# 첫 열 렌더러 — 기존 행은 선택 체크박스, 신규 행은 − 제거 버튼.
# 선택 상태(_sel)는 사용자가 체크박스를 누를 때만 setDataValue 로 명시 기록되므로,
# 체크박스가 없는 신규 행에는 선택값이 실릴 수 없다(팬텀 선택 원천 차단).
# − 클릭은 _removed 플래그만 세팅하고, 실제 제거는 Python 이 권위 상태에서 처리한다.
# ag-grid-react 는 cellRenderer 함수가 문자열을 반환하면 이스케이프해 표시하고,
# DOM 엘리먼트를 반환하면 React 자식으로 처리하려다 실패한다(React #31). 따라서
# AG Grid 컴포넌트 인터페이스(class + getGui)로 DOM 을 직접 만든다. 클릭 처리는
# onCellClicked 에서 e.node / e.event.target 로 수행한다.
_ROW_ACTION_RENDERER = JsCode(
    """
    (class {
      init(params) {
        const d = params.data || {};
        const eGui = document.createElement('div');
        eGui.className = 'md-act';
        if (d._row_state === 'group') {
          // 가상 그룹 부모 행(조직 관리) — 선택/제거 대상이 아니므로 빈 셀.
          this.eGui = eGui;
          return;
        }
        if (d._row_state === 'existing') {
          const cb = document.createElement('input');
          cb.type = 'checkbox';
          cb.className = 'md-act-cb';
          cb.checked = (d._sel === true || d._sel === 'true' || d._sel === 1);
          eGui.appendChild(cb);
        } else {
          const btn = document.createElement('button');
          btn.type = 'button';
          btn.className = 'md-act-rm';
          btn.title = '이 신규 행 삭제';
          btn.textContent = '\\u2212';
          eGui.appendChild(btn);
        }
        this.eGui = eGui;
      }
      getGui() { return this.eGui; }
      refresh() { return false; }
    })
    """
)

# 선택 열 헤더의 전체 선택 체크박스 (3상태: 해제/indeterminate/체크).
# 대상은 "현재 필터 결과에 표시되는 기존(existing) 행"뿐이다 — 신규 행(− 버튼),
# 제거 표시된 행은 제외한다. Community 기능(forEachNodeAfterFilter)만 사용한다.
_SELECT_ALL_HEADER = JsCode(
    """
    (class {
      init(params) {
        this.params = params;
        const eGui = document.createElement('div');
        eGui.className = 'md-act';
        const cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.className = 'md-act-cb';
        cb.title = '표시된 기존 행 전체 선택';
        eGui.appendChild(cb);
        this.eGui = eGui;
        this.cb = cb;
        this.refreshState = this.refreshState.bind(this);
        cb.addEventListener('click', (e) => {
          e.stopPropagation();
          const target = cb.checked;  // 클릭 후 상태 기준으로 전체 적용
          params.api.forEachNodeAfterFilter((node) => {
            const d = node.data || {};
            if (d._row_state === 'existing' && String(d._removed || '') !== '1') {
              node.setDataValue('_sel', target);
            }
          });
          // _sel 은 숨김 컬럼이라 setDataValue 만으로는 _action 셀이 다시 그려지지
          // 않는다 — 행 체크박스 표시를 동기화하기 위해 강제 리렌더한다.
          params.api.refreshCells({ columns: ['_action'], force: true });
          this.refreshState();
        });
        params.api.addEventListener('cellValueChanged', this.refreshState);
        params.api.addEventListener('modelUpdated', this.refreshState);
        params.api.addEventListener('filterChanged', this.refreshState);
        setTimeout(this.refreshState, 0);
      }
      refreshState() {
        let total = 0, sel = 0;
        this.params.api.forEachNodeAfterFilter((node) => {
          const d = node.data || {};
          if (d._row_state === 'existing' && String(d._removed || '') !== '1') {
            total += 1;
            if (d._sel === true || d._sel === 'true' || d._sel === 1) { sel += 1; }
          }
        });
        this.cb.disabled = total === 0;
        this.cb.checked = total > 0 && sel === total;
        this.cb.indeterminate = sel > 0 && sel < total;
      }
      getGui() { return this.eGui; }
      destroy() {
        this.params.api.removeEventListener('cellValueChanged', this.refreshState);
        this.params.api.removeEventListener('modelUpdated', this.refreshState);
        this.params.api.removeEventListener('filterChanged', this.refreshState);
      }
    })
    """
)

# 첫 열 클릭 처리 — 기존 행 체크박스는 _sel, 신규 행 − 버튼은 _removed 를 명시 기록한다.
_ROW_ACTION_CLICK = JsCode(
    """
    function(e) {
      if (!e.colDef || e.colDef.field !== '_action') { return; }
      const t = e.event && e.event.target;
      if (!t || !t.classList) { return; }
      if (t.classList.contains('md-act-rm')) {
        e.node.setDataValue('_removed', '1');
      } else if (t.classList.contains('md-act-cb')) {
        e.node.setDataValue('_sel', !!t.checked);
      }
    }
    """
)

# 그리드 내부(iframe) 스타일 — 헤더/셀 가운데 정렬, 문자 셀 좌측 여백,
# 가로·세로 얇은 구분선, − 버튼/체크박스 정렬. 사이드바 계열 색만 사용(네이비 없음).
_MASTER_GRID_CSS = {
    ".ag-root-wrapper": {"border": "1px solid #CFC8BB"},
    ".ag-header": {"border-bottom": "1px solid #CFC8BB"},
    ".ag-header-cell": {"border-right": "1px solid rgba(30, 30, 30, 0.12)"},
    ".ag-header-cell-label": {"justify-content": "center"},
    ".ag-cell": {
        "border-right": "1px solid rgba(30, 30, 30, 0.10)",
        "display": "flex",
        "align-items": "center",
        "line-height": "normal",
    },
    ".ag-row": {"border-bottom": "1px solid rgba(30, 30, 30, 0.08)"},
    ".md-c-left": {"justify-content": "flex-start", "padding-left": "10px"},
    ".md-c-center": {"justify-content": "center", "padding-left": "0", "padding-right": "0"},
    ".md-act": {
        "display": "flex", "align-items": "center", "justify-content": "center",
        "width": "100%", "height": "100%",
    },
    ".md-act-cb": {"cursor": "pointer", "margin": "0"},
    ".md-act-rm": {
        "width": "20px", "height": "20px", "padding": "0", "line-height": "1",
        "border": "1px solid #E0CFC9", "border-radius": "4px",
        "background": "#FFFFFF", "color": "#9A3B2E", "cursor": "pointer",
        "font-size": "15px", "font-weight": "700",
    },
    ".md-act-rm:hover": {"background": "#F7EFEC", "border-color": "#C77B6B"},
    # 조직 관리 — 가상 그룹 부모 행(배경·굵게)과 부서 자식 들여쓰기.
    ".ms-group-row": {
        "background": "#EFECE4 !important", "font-weight": "700",
        "box-shadow": "inset 3px 0 #C9A26B",
    },
    ".ms-group-row .ag-cell": {"color": "#3D3A34"},
    ".ms-indent": {"padding-left": "26px !important"},
    ".ms-unit-shift": {
        "background": "rgba(30, 58, 110, 0.10) !important", "color": "#1E3A6E",
        "font-weight": "700", "border-radius": "4px", "justify-content": "center",
    },
    ".ms-unit-general": {
        "background": "rgba(61, 58, 52, 0.08) !important", "color": "#3D3A34",
        "font-weight": "700", "border-radius": "4px", "justify-content": "center",
    },
}

_META_COLUMNS = ["_row_id", "_row_state", "_sel", "_removed"]


def selectable_master_grid(
    frame: pd.DataFrame,
    key: str,
    columns: dict,
    height: int,
    order: list[str] | None = None,
    col_config: dict | None = None,
    select_all_header: bool = False,
    extra_grid_options: dict | None = None,
) -> pd.DataFrame:
    """행 상태 계약(_row_id/_row_state/_sel/_removed)을 갖춘 기준정보 편집 그리드.

    - 첫 열: 기존 행=선택 체크박스, 신규 행=− 제거 버튼 (_row_state 기반)
    - 선택은 _sel 데이터로 명시 기록 → 신규 행에는 선택이 실릴 수 없다(팬텀 차단)
    - Excel 여러 행·열 붙여넣기 지원(공용 paste handler 재사용)
    - 반환: 그리드 현재 데이터(메타 컬럼 포함). 구조 변경(붙여넣기/− 제거)의
      권위 반영은 호출부가 담당한다.

    columns: {표시명: "text"|"bool"} (표시 순서는 order 로 지정).
    col_config: {표시명: AG Grid 컬럼 속성 dict} — 폭·고정(pinned)·editable(JsCode 허용)
      등 화면별 설정을 기본값 위에 덮어쓴다 (미지정 화면은 기존 동작 유지).
    select_all_header: True 면 선택 열 헤더에 3상태 전체 선택 체크박스를 표시한다
      (표시 중인 기존 행만 대상 — 기본 False 로 기존 화면 무변경).
    extra_grid_options: gridOptions 에 덮어쓸 추가 옵션(dict). 조직 관리의
      rowClassRules(가상 그룹 부모 행 강조) 등 — 기본 None 으로 기존 화면 무변경.
    """
    frame = frame.copy().reset_index(drop=True)
    for meta, default in (("_row_id", ""), ("_row_state", "new"), ("_sel", False), ("_removed", "")):
        if meta not in frame:
            frame[meta] = default
    frame["_sel"] = frame["_sel"].map(grid_bool)
    frame["_removed"] = ""
    frame["_action"] = ""
    for name, kind in columns.items():
        if name not in frame:
            frame[name] = False if kind == "bool" else ""
        elif kind == "bool":
            frame[name] = frame[name].map(grid_bool)
        else:
            frame[name] = frame[name].fillna("").astype("string")

    order = order or list(columns)
    align_center = {"width": None}
    action_col = {
        "field": "_action",
        "headerName": "선택",
        "pinned": "left",
        "width": 66, "minWidth": 56, "maxWidth": 74,
        "editable": False, "sortable": False, "filter": False, "resizable": False,
        "suppressMovable": True,
        "cellRenderer": _ROW_ACTION_RENDERER,
        "headerClass": "md-h-center", "cellClass": "md-c-center",
    }
    if select_all_header:
        action_col["headerComponent"] = _SELECT_ALL_HEADER
    column_defs = [action_col]
    # 폭/정렬 기본값 — 문자 열은 flex 로 남는 폭 배분, 숫자/불리언은 좁은 고정
    widths = {
        "부서코드": {"flex": 1, "minWidth": 120, "cellClass": "md-c-left"},
        "부서명": {"flex": 2, "minWidth": 200, "cellClass": "md-c-left"},
        "표시순서": {"width": 108, "minWidth": 92, "maxWidth": 140, "cellClass": "md-c-center"},
        "사용": {"width": 82, "minWidth": 72, "maxWidth": 108, "cellClass": "md-c-center"},
    }
    overrides = col_config or {}
    for name in order:
        kind = columns[name]
        base = widths.get(name, {})
        override = overrides.get(name, {})
        col = {
            "field": name, "headerName": name, "editable": True,
            "sortable": False, "filter": False, "resizable": True,
            "headerClass": "md-h-center",
            "cellClass": override.get("cellClass", base.get("cellClass", "md-c-left")),
        }
        for source in (base, override):
            for k, v in source.items():
                if k != "cellClass":
                    col[k] = v
        if kind == "bool":
            col["cellEditor"] = "agCheckboxCellEditor"
        column_defs.append(col)
    for meta in _META_COLUMNS:
        column_defs.append({"field": meta, "hide": True, "editable": False, "suppressColumnsToolPanel": True})

    grid_options = {
        "columnDefs": column_defs,
        "defaultColDef": {"resizable": True, "sortable": False, "filter": False},
        "singleClickEdit": False,
        "stopEditingWhenCellsLoseFocus": True,
        "enterNavigatesVertically": True,
        "enterNavigatesVerticallyAfterEdit": True,
        "suppressRowClickSelection": True,
        "suppressDragLeaveHidesColumns": True,
        # 빈 목록 기본 문구(No Rows To Show)를 업무 화면 한글 문구로 교체.
        "overlayNoRowsTemplate": "<span style='color:#8A8880;font-size:0.82rem;'>표시할 데이터가 없습니다</span>",
        "onGridReady": _NATIVE_PASTE_HANDLER,
        "onCellClicked": _ROW_ACTION_CLICK,
        # 자동 빈 행 추가는 쓰지 않는다 — 신규 행은 [＋ 행 추가]/붙여넣기로만 생성.
    }
    if extra_grid_options:
        grid_options.update(extra_grid_options)

    ordered = ["_action"] + order + _META_COLUMNS
    response = AgGrid(
        frame[ordered],
        gridOptions=grid_options,
        key=key,
        height=height,
        update_on=[("cellValueChanged", 200)],
        data_return_mode=DataReturnMode.AS_INPUT,
        allow_unsafe_jscode=True,
        theme="streamlit",
        custom_css=_MASTER_GRID_CSS,
        show_toolbar=False,
        show_search=False,
    )
    result = response.data
    if not isinstance(result, pd.DataFrame):
        return frame
    result = result.copy()
    for name, kind in columns.items():
        if name not in result.columns:
            continue
        if kind == "bool":
            result[name] = result[name].map(grid_bool)
        else:
            result[name] = result[name].fillna("").astype("string")
    for meta in ("_row_id", "_row_state", "_removed"):
        if meta not in result.columns:
            result[meta] = ""
        result[meta] = result[meta].fillna("").astype(str)
    result["_sel"] = result["_sel"].map(grid_bool) if "_sel" in result.columns else False
    return result


# ---------- 기준정보 4화면 공통 레이아웃 (제목·설명·필터·버튼·그리드 높이·건수) ----------
# 사용자/부서/조/근무형태 관리가 동일한 화면 골격을 쓰도록 공용화한다.
# 한 번에 한 화면만 렌더되므로 공용 컨테이너/버튼 key(ms_*)를 재사용한다.
_MASTER_CSS = """
<style>
/* 제목 + 한 줄 설명 */
.ms-title { font-size: 1.18rem; font-weight: 700; color: #26241F; letter-spacing: -0.01em; margin: 0; line-height: 1.9rem; }
.ms-desc { font-size: 0.82rem; color: #8A8880; margin: 0 0 0.45rem; line-height: 1.35; }
/* 컴팩트 필터 행 */
.st-key-ms_filter { margin: 0 0 0.1rem; }
.st-key-ms_filter div[data-testid="stHorizontalBlock"] { align-items: flex-end; }
.st-key-ms_filter label { font-size: 0.72rem !important; color: #8A8880 !important; }
/* 공통 작업 버튼 행 (ms_*: 단일 화면 · od_*/ou_*: 조직 관리 좌/우 패널) */
.st-key-ms_bar, .st-key-od_bar, .st-key-ou_bar { margin: 0.1rem 0 0.4rem; }
.st-key-ms_bar div[data-testid="stHorizontalBlock"],
.st-key-od_bar div[data-testid="stHorizontalBlock"],
.st-key-ou_bar div[data-testid="stHorizontalBlock"] { align-items: center; }
.st-key-ms_bar div.stButton > button,
.st-key-od_bar div.stButton > button,
.st-key-ou_bar div.stButton > button {
  min-height: 2.2rem; height: 2.2rem; padding: 0 0.7rem; border-radius: 6px;
  font-size: 0.82rem; font-weight: 600; white-space: nowrap; gap: 0.35rem;
}
.st-key-ms_bar div.stButton > button [data-testid="stIconMaterial"],
.st-key-od_bar div.stButton > button [data-testid="stIconMaterial"],
.st-key-ou_bar div.stButton > button [data-testid="stIconMaterial"] { font-size: 17px; }
/* 저장 — 앱 네이비 primary (검정 금지) */
.st-key-ms_save button[kind="primary"], .st-key-od_save button[kind="primary"], .st-key-ou_save button[kind="primary"] { background: #1E3A6E !important; border: 1px solid #1E3A6E !important; color: #FFFFFF !important; }
.st-key-ms_save button[kind="primary"]:hover, .st-key-od_save button[kind="primary"]:hover, .st-key-ou_save button[kind="primary"]:hover { background: #17305C !important; border-color: #17305C !important; }
/* 행 추가 / 새로고침 — 중립 outline (od_addg = 조직 관리 [＋ 그룹]) */
.st-key-ms_add button, .st-key-ms_refresh button,
.st-key-od_add button, .st-key-od_addg button, .st-key-od_refresh button,
.st-key-ou_add button, .st-key-ou_refresh button { background: #FFFFFF !important; border: 1px solid #D8D2C7 !important; color: #3D3A34 !important; }
.st-key-ms_add button:hover, .st-key-ms_refresh button:hover,
.st-key-od_add button:hover, .st-key-od_addg button:hover, .st-key-od_refresh button:hover,
.st-key-ou_add button:hover, .st-key-ou_refresh button:hover { background: #F1EEE9 !important; border-color: #C9A26B !important; }
/* 삭제 — 중립 outline(빨강 계열 글자), 선택 없으면 disabled */
.st-key-ms_del button, .st-key-od_del button, .st-key-ou_del button { background: #FFFFFF !important; border: 1px solid #E0CFC9 !important; color: #9A3B2E !important; }
.st-key-ms_del button:hover:not(:disabled), .st-key-od_del button:hover:not(:disabled), .st-key-ou_del button:hover:not(:disabled) { background: #F7EFEC !important; border-color: #C77B6B !important; }
.st-key-ms_del button:disabled, .st-key-od_del button:disabled, .st-key-ou_del button:disabled { color: #B8B4AC !important; border-color: #E7E3DB !important; background: #FFFFFF !important; }
/* 조직 관리 좌/우 패널 제목 (부서/조 통합 화면 전용) */
.ms-panel { font-size: 0.92rem; font-weight: 700; color: #3D3A34; margin: 0.2rem 0 0.1rem; }
.ms-panel small { font-weight: 500; color: #8A8880; }
/* 건수 */
.ms-count { font-size: 0.76rem; color: #8A8880; margin: 0.4rem 0 0; }
.ms-count b { color: #3D3A34; font-weight: 600; }
</style>
"""


def master_screen_head(title: str, desc: str) -> None:
    """기준정보 공통 헤더 — 공용 CSS 주입 + 제목 + 한 줄 설명."""
    st.markdown(_MASTER_CSS, unsafe_allow_html=True)
    st.markdown(
        f"<div class='ms-title'>{escape(title)}</div>"
        f"<div class='ms-desc'>{escape(desc)}</div>",
        unsafe_allow_html=True,
    )


def master_grid_height(nrows: int) -> int:
    """행 수 기반 동적 그리드 높이(240~460px). 행이 적으면 과도하게 커지지 않고,
    많으면 그리드 내부 스크롤한다. 하단 큰 빈 공간·저장 버튼 겹침을 방지한다."""
    return max(240, min(35 * (int(nrows) + 1) + 64, 460))


def master_action_bar(sel_count: int, prefix: str = "ms") -> None:
    """공통 작업 버튼 행: 좌 [＋ 행 추가][삭제][저장] · 우 [새로고침].

    클릭은 세션 플래그({prefix}_add_req/_del_req/_save_req/_refresh_req)로 남긴다
    (셀 편집 blur 와 경합해도 다음 rerun 에서 반드시 처리). 삭제는 선택 행이 없으면
    disabled. 화면은 이 함수를 상단 배치용 placeholder 컨테이너(key='{prefix}_bar')
    안에서 호출한다. prefix 기본값 "ms" 는 기존 단일 그리드 화면용이며, 조직 관리
    화면은 좌/우 패널에 "od"/"ou" 를 사용한다 (버튼 스타일은 _MASTER_CSS 공유)."""
    def _flag(name: str):
        return lambda: st.session_state.update({f"{prefix}_{name}_req": True})

    a, d, s, _sp, r = st.columns([1.5, 1.3, 1.3, 3.4, 1.6], vertical_alignment="center")
    a.button("행 추가", key=f"{prefix}_add", icon=":material/add:", width="stretch",
             on_click=_flag("add"))
    d.button("삭제", key=f"{prefix}_del", icon=":material/delete:", width="stretch",
             disabled=int(sel_count) == 0,
             on_click=_flag("del"))
    s.button("저장", key=f"{prefix}_save", type="primary", width="stretch",
             on_click=_flag("save"))
    r.button("새로고침", key=f"{prefix}_refresh", icon=":material/refresh:", width="stretch",
             on_click=_flag("refresh"))


def master_count(existing: int, new: int, sel: int) -> None:
    """그리드 하단 건수 안내 — 총 N건 · 신규 M건 · 선택 K건."""
    new_txt = f" · 신규 <b>{int(new)}</b>건" if new else ""
    st.markdown(
        f"<div class='ms-count'>총 <b>{int(existing)}</b>건{new_txt} · 선택 <b>{int(sel)}</b>건</div>",
        unsafe_allow_html=True,
    )


def normalize_editor_text(df: pd.DataFrame, columns) -> pd.DataFrame:
    """data_editor의 텍스트 셀을 빈 문자열 기반 string dtype으로 정규화한다."""
    frame = df.copy()
    for column in columns:
        frame[column] = frame[column].fillna("").astype("string")
    return frame


def grid_bool(value) -> bool:
    """Excel 붙여넣기에서 들어오는 boolean 텍스트를 명시적으로 정규화한다."""
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "t", "yes", "y", "사용", "재직"}
    return bool(value)


def set_flash(page_id: str, kind: str, text: str) -> None:
    """저장 결과 메시지를 다음 rerun 에서 1회 표시하도록 세션에 담는다.

    kind 는 st 의 메서드명("success" / "warning" / "error")."""
    st.session_state[f"flash_{page_id}"] = (kind, text)


def show_flash(page_id: str) -> None:
    msg = st.session_state.pop(f"flash_{page_id}", None)
    if msg:
        kind, text = msg
        getattr(st, kind)(text)


def save_bar(page_id: str) -> bool:
    """편집 그리드 하단 [저장] 액션. 클릭 여부를 반환한다."""
    (save,) = ui.action_bar("save")
    with save:
        return st.button("저장", key=f"{page_id}_save", type="primary", width="stretch")


def master_download(view: pd.DataFrame, name: str, key: str) -> None:
    """하단 액션 버튼 영역 (기준정보 공통)."""
    (dl,) = ui.action_bar("download")
    with dl:
        st.download_button(
            "엑셀 다운로드",
            view.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"{name}.csv",
            mime="text/csv",
            key=key,
            width="stretch",
        )


# ---------- 근무표 등록/수정 · 전체 근무표 조회 (공통 본문) ----------
def schedule_screen(user: dict, page_id: str) -> None:
    scheds = db.get_schedules()
    depts = db.get_departments()
    teams = db.get_teams()
    today = date.today()

    months = sorted({s[:7] for s in scheds["duty_date"]}) if not scheds.empty else []
    years = sorted({int(m[:4]) for m in months} | {today.year})

    dept_names = {r["dept_code"]: r["dept_name"] for _, r in depts.iterrows()}
    manager_locked = user["role"] == "MANAGER" and user.get("dept_code")

    # 조회 조건 카드
    with ui.card():
        c1, c2, c3, c4, c5, c6 = st.columns(
            [0.9, 0.9, 1.5, 1.1, 1.6, 0.8],
            vertical_alignment="bottom",
        )
        year = c1.selectbox("연도", years, index=years.index(today.year), key=f"{page_id}_y")
        month = c2.selectbox(
            "월", list(range(1, 13)), index=today.month - 1,
            format_func=lambda m: f"{m}월", key=f"{page_id}_m",
        )
        if manager_locked:
            dept = c3.selectbox(
                "부서", [user["dept_code"]], format_func=lambda c: dept_names.get(c, c),
                key=f"{page_id}_d", disabled=True,
            )
        else:
            dept_opts = [ALL] + list(dept_names)
            dept = c3.selectbox(
                "부서", dept_opts, format_func=lambda c: dept_names.get(c, c),
                key=f"{page_id}_d",
            )
        team_rows = teams[teams["dept_code"] == dept] if dept != ALL else teams.iloc[0:0]
        team_names = {r["team_code"]: r["team_name"] for _, r in team_rows.iterrows()}
        team = c4.selectbox(
            "조", [ALL] + list(team_names), format_func=lambda c: team_names.get(c, c),
            key=f"{page_id}_t",
        )
        keyword = c5.text_input(
            "사번 또는 성명",
            key=f"{page_id}_kw",
            placeholder="전체",
        )
        clicked = c6.button("조회", key=f"{page_id}_go", type="primary", width="stretch")

    q = run_query(
        page_id,
        clicked,
        {
            "year": year,
            "month": month,
            "dept": dept,
            "team": team,
            "keyword": keyword.strip(),
        },
    )
    if not q:
        ui.empty_state("조회 조건을 선택한 후 조회하세요.", head="월별 근무표")
        return

    # MANAGER 권한범위 fail-closed 재적용: run_query 가 돌려준 저장 조회조건(이전
    # 사용자·타 부서·ALL 일 수 있음)에도 항상 본인 부서로 축소한다. 위젯 잠금만
    # 믿지 않는다(잠금은 UX, 실제 데이터 경계는 여기서 강제).
    #
    # scoped 되려면 본인 dept_code 가 (a) ALL 센티널이 아니고 (b) 실제 존재하는 부서
    # 코드여야 한다. 빈값·ALL 센티널("(전체)")·미존재 코드는 모두 차단(blocked)한다 —
    # 그러지 않으면 dept_code==ALL 인 부서를 배정/조작해 q["dept"]=ALL 로 부서 필터를
    # 통째 건너뛰는 전체 노출 우회가 가능하다(_build_month_grid 는 ALL 이면 필터 생략).
    role = str(user.get("role") or "").strip().upper()
    if role == "MANAGER":
        manager_dept = str(user.get("dept_code") or "").strip()
        if not manager_dept or manager_dept == ALL or manager_dept not in dept_names:
            ui.empty_state(
                "소속 부서가 유효하지 않아 근무표를 표시할 수 없습니다. "
                "관리자에게 부서 지정을 요청하세요.",
                head="월별 근무표",
            )
            return
        if str(q.get("dept") or "") != manager_dept:
            q = {**q, "dept": manager_dept, "team": ALL}  # 부서 밖 조 조건은 초기화

    display_of, color_of = work_type_display()
    grid, month_rows = _build_month_grid(q, display_of)
    if grid.empty:
        ui.empty_state("조회 조건에 해당하는 직원이 없습니다.", head="월별 근무표")
        return

    # 요약 카드
    wt = db.work_types_map()
    n_work = sum(1 for c in month_rows["work_type_code"] if wt.get(c, {}).get("is_work"))
    ui.summary_cards([
        ("대상 인원", f"{len(grid)}명"),
        ("근무 데이터", f"{len(month_rows)}건"),
        ("실근무", f"{n_work}건"),
        ("휴무·휴가", f"{len(month_rows) - n_work}건"),
    ])
    st.write("")

    # 데이터 그리드 (근무 약칭 + 지정 색상, 읽기 전용)
    day_cols = [c for c in grid.columns if c[0].isdigit()]
    ui.panel_head("월간 근무표", f"조회 결과 {len(grid)}건")
    styled = grid.style.map(lambda v: _cell_style(v, color_of), subset=day_cols)
    st.dataframe(styled, width="stretch", hide_index=True, height=grid_height(len(grid)))
    st.markdown(_label_legend_html(display_of, color_of), unsafe_allow_html=True)

    # 사용자별 집계 (전체 근무표 조회)
    if page_id == "schedule_view" and not month_rows.empty:
        st.write("")
        ui.panel_head("직원별 근무형태 집계")
        agg = _build_agg(grid, month_rows, wt, display_of)
        st.dataframe(agg, width="stretch", hide_index=True, height=grid_height(len(agg)))

    # 하단 액션
    (dl,) = ui.action_bar("download")
    with dl:
        st.download_button(
            "엑셀 다운로드",
            grid.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"근무표_{q['year']}-{q['month']:02d}.csv",
            mime="text/csv",
            key=f"{page_id}_dl",
            width="stretch",
        )


def _clean(value) -> str:
    """pandas NA-safe 문자열 정규화 — None/NaN/pd.NA → ''(폴백), 그 외 str.strip()."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass  # 배열·비스칼라 등 isna 판정 불가 값은 그대로 문자열화
    return str(value).strip()


def _month_assignment_snapshot(year: int, month: int) -> dict:
    """대상 월의 부서·조 편성 스냅샷 {emp_no: (dept_code, team_code)}.

    영속 저장(schedule_assignments — 직원·월 편성 1건)을 조회한다. 스냅샷은 근무표
    작성 당시의 소속을 보존하므로, 과거 월을 조회할 때 인사이동 이후의 현재 소속이
    아니라 그 당시 소속으로 표시·필터하기 위한 기준이다(requirements.md §5·불변계약).

    조회 계약(정상 빈 결과 vs repository 오류 구분): **정상 빈 월은 빈 맵({})** 으로
    폴백해 호출부가 현재 소속을 표시하게 하되, **repository 오류(네트워크·인증·매핑
    등 DATA_SOURCE_ERRORS)는 삼키지 않고 전파**한다 — app.main 상위 핸들러가 오류로
    표시하고, 스냅샷이 있는데 조회만 실패한 상황을 '빈 월'로 위장하지 않는다.
    dashboard._month_snapshot 와 동일한 무-스왈로우 패턴이며, 행 변환(맵 구성)도
    별도 try 로 감싸지 않아 매핑 오류까지 전파된다.
    """
    assigns = db.get_month_assignments(int(year), int(month))
    snaps: dict = {}
    if assigns is None or assigns.empty:
        return snaps
    for _, r in assigns.iterrows():
        emp = _clean(r.get("emp_no"))
        if emp:
            snaps[emp] = (_clean(r.get("dept_code")), _clean(r.get("team_code")))
    return snaps


def _build_month_grid(q: dict, display_of: dict | None = None):
    """해당 월/부서/조의 가로형 근무표 DataFrame 과 세로형 원본 레코드를 반환.

    부서·조는 대상 월의 편성 스냅샷(schedule_assignments)을 우선 사용하고, 없으면
    현재 사용자 소속으로 폴백한다(표시 전용·자동저장/백필 없음 — requirements.md §5).
    조회 조건의 부서·조 필터도 같은 스냅샷 기준으로 일관 적용해, 과거 월 조회 시
    인사이동한 직원이 현재 소속으로 오분류되지 않게 한다. 날짜 셀은 내부 코드가 아니라
    근무형태 약칭(display_of)으로 표시한다.
    """
    display_of = display_of or {}
    users = db.get_users()
    users = users[users["is_active"]].copy()

    # 스냅샷 우선으로 '그 당시 부서/조'를 해석한다(없으면 현재 소속 폴백).
    snaps = _month_assignment_snapshot(q["year"], q["month"])
    eff_depts, eff_teams = [], []
    for _, u in users.iterrows():
        emp = _clean(u.get("emp_no"))
        dept_code, team_code = snaps.get(
            emp, (_clean(u.get("dept_code")), _clean(u.get("team_code")))
        )
        eff_depts.append(dept_code)
        eff_teams.append(team_code)
    users["_eff_dept"] = eff_depts
    users["_eff_team"] = eff_teams

    if q["dept"] != ALL:
        users = users[users["_eff_dept"] == q["dept"]]
        if q["team"] != ALL:
            users = users[users["_eff_team"] == q["team"]]
    keyword = str(q.get("keyword", "")).strip()
    if keyword:
        emp_match = users["emp_no"].astype(str).str.contains(
            keyword, case=False, na=False, regex=False,
        )
        name_match = users["name"].astype(str).str.contains(
            keyword, case=False, na=False, regex=False,
        )
        users = users[emp_match | name_match]
    users = users.sort_values(["_eff_dept", "_eff_team", "emp_no"])

    scheds = db.get_month_schedules(users["emp_no"], q["year"], q["month"])

    lookup = {(r["emp_no"], r["duty_date"]): r["work_type_code"] for _, r in scheds.iterrows()}
    ndays = calendar.monthrange(q["year"], q["month"])[1]
    days = [date(q["year"], q["month"], d) for d in range(1, ndays + 1)]

    rows = []
    for _, u in users.iterrows():
        dept_code, team_code = u["_eff_dept"], u["_eff_team"]
        row = {
            "사번": u["emp_no"],
            "성명": u["name"],
            "부서": db.dept_name(dept_code),
            "조": db.team_name(dept_code, team_code),
        }
        for d in days:
            code = lookup.get((u["emp_no"], d.isoformat()), "")
            row[f"{d.day}({ui.weekday_kr(d)})"] = display_of.get(code, code) if code else ""
        rows.append(row)
    return pd.DataFrame(rows), scheds


def _build_agg(grid: pd.DataFrame, month_rows: pd.DataFrame, wt: dict, display_of: dict | None = None) -> pd.DataFrame:
    """직원별 근무형태 집계표: 성명 | 약칭별 건수 | 계 (열 머리글은 약칭)."""
    display_of = display_of or {}
    codes = [c for c in wt if c in set(month_rows["work_type_code"])]
    pivot = (
        month_rows.groupby(["emp_no", "work_type_code"]).size().unstack(fill_value=0)
    )
    rows = []
    for _, g in grid.iterrows():
        counts = pivot.loc[g["사번"]] if g["사번"] in pivot.index else None
        row = {"사번": g["사번"], "성명": g["성명"]}
        total = 0
        for c in codes:
            n = int(counts[c]) if counts is not None and c in counts else 0
            row[display_of.get(c, c)] = n
            total += n
        row["계"] = total
        rows.append(row)
    return pd.DataFrame(rows)


def _cell_style(value, color_of: dict) -> str:
    """날짜 셀 배경색 — 약칭/코드 어느 쪽으로 표시돼도 같은 색을 입힌다."""
    color = color_of.get(str(value).strip())
    if not color:
        return ""
    return f"background-color:{color}26; color:#1F2328; font-weight:600"


def _label_legend_html(display_of: dict, color_of: dict) -> str:
    """근무 약칭 범례 (표 하단). 셀 표시값(약칭)과 색을 그대로 보여준다."""
    seen, badges = set(), []
    for code, disp in display_of.items():
        if disp in seen:
            continue
        seen.add(disp)
        color = color_of.get(disp) or color_of.get(code) or "#9AA0A6"
        badges.append(ui.badge_html(disp, color))
    return f"<div class='duty-legend'>{''.join(badges)}</div>"
