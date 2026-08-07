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

from modules import db, nav, ui
from views.common import erp

ALL = "(전체)"

# §1-C 읽기 변형(월간 근무표) 전용 CSS — 조건 줄 헤어라인·컨텍스트 라인(모노 수치)·
# 표 흰 컨테이너(1px #cfc8bd·radius 8·내부 스크롤). 작은 의미 텍스트 ≥#6b665d(A-2), §2 팔레트.
_SV_CSS = """
<style>
.sv-hr { border-top:1px solid #e0dbd2; margin:2px 0 10px; }
.sv-ctx { display:flex; flex-wrap:wrap; align-items:center; gap:4px 14px; margin:2px 0 10px;
  font-size:12.5px; color:#4a453d; }
.sv-ctx .loc { font-weight:600; color:#1c1a17; }
.sv-ctx .num { font-family:'IBM Plex Mono',monospace; font-weight:600; color:#1c1a17; }
.sv-ctx .sep { color:#a09a90; margin:0 2px; }
.st-key-sv_gridwrap [data-testid="stCustomComponentV1"],
.st-key-sv_gridwrap div[data-testid="stAgGrid"] {
  border:1px solid #cfc8bd; border-radius:8px; overflow:hidden; background:#ffffff;
}
</style>
"""
RETIRED_LABEL = "(퇴직)"
# 퇴직 행 배경/글자색 — master_users.py 의 .ms-row-inactive 와 동일 토큰
# (surface-3 / ink-2, views/master/style.py TOKENS) 로 화면 간 시각 일관성을 맞춘다.
_RETIRED_ROW_CSS = "background-color:#F1EEE7; color:#5F5C55"


def work_type_display(wt_df: pd.DataFrame | None = None) -> tuple[dict, dict]:
    """근무형태 표시 계약 — (display_of, color_of).

    - display_of: 내부 코드 -> 화면 표시값(약칭). 약칭이 비었거나 같은 약칭이 여러
      코드에 걸리면(왕복 모호) 코드를 그대로 표시한다.
    - color_of: 표시값과 코드 양쪽을 색상(#RRGGBB)에 매핑 — 셀이 약칭으로 바뀌어도
      같은 코드는 같은 색을 유지한다(색은 코드에 귀속).
    조회 화면(월간·개인)이 셀을 약칭·색상으로 일관 표시하도록 공통으로 쓴다.

    wt_df: 이미 조회한 근무형태 프레임을 재사용하려는 호출자가 넘긴다(렌더 1회
    내 db.get_work_types() 중복 조회를 피하기 위함). 넘기지 않으면 직접 조회한다
    (기존 호출자 호환).
    """
    wt = wt_df if wt_df is not None else db.get_work_types()
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


def _work_types_map_from_df(wt_df: pd.DataFrame) -> dict:
    """db.work_types_map() 과 동일한 계약(근무코드 -> {name, category, color, is_work})을
    이미 조회해 둔 프레임에서 재구성한다 — db.work_types_map() 파사드 시그니처는 그대로
    두고(다른 화면의 호출부는 영향 없음), 같은 렌더 안에서 db.get_work_types() 를
    두 번째로 다시 조회하지 않기 위한 뷰 쪽 helper 다.
    """
    out = {}
    for _, r in wt_df.iterrows():
        out[r["code"]] = {
            "name": r["name"],
            "category": r.get("category", ""),
            "color": r["color"] or "#9AA0A6",
            "is_work": bool(r["is_work"]),
        }
    return out


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


def seed_query_once(page_id: str, params: dict) -> None:
    """세션 최초 1회 기본 조건을 심어 진입 즉시 데이터가 로드되게 한다(U3 — 빈 안내 패널 해소).

    '최초 1회'만 심으며(매 rerun 자동조회가 아님), 이후 [조회]가 명시적으로 덮어쓴다. 조회만으로
    데이터를 쓰지 않으므로(읽기 전용) 자동 '읽기' 조회는 계약 위반이 아니다. 이미 조회 이력이
    있으면(세션 키 존재) 심지 않는다."""
    key = f"q_{page_id}"
    seed_key = f"q_{page_id}__seeded"
    if st.session_state.get(seed_key):
        return
    st.session_state[seed_key] = True
    if key not in st.session_state:
        st.session_state[key] = params


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
        // 키보드(WCAG 2.1.1): 네이티브 체크박스는 Space 로 이미 토글되며 click 을 발생시킨다.
        // Enter 는 기본 동작이 없으므로 click 으로 위임해 마우스와 동일 경로를 태운다.
        cb.addEventListener('keydown', (e) => {
          if (e.key === 'Enter' && !cb.disabled) { e.preventDefault(); cb.click(); }
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

# 첫 열 키보드 처리(WCAG 2.1.1) — AG Grid 셀 내비게이션은 .ag-cell 래퍼로만 Tab 이동하고
# cellRenderer 내부의 네이티브 입력은 Tab 순서에 없다. 포커스된 _action 셀에서 Enter/Space 가
# 마우스 클릭과 동일한 동작(기존 행=_sel 토글, 신규 행=_removed)을 하도록 한다.
# onCellClicked(마우스)는 그대로 두고, 여기서는 셀 데이터로 동작을 판정한다(포커스는 래퍼에
# 있어 e.event.target 이 입력 요소가 아니기 때문). preventDefault 로 AG Grid 기본 키 동작
# (Enter 세로 이동 등)을 막는다. _sel 은 숨김 컬럼이라 setDataValue 만으로는 체크박스 표시가
# 갱신되지 않으므로 해당 행 _action 셀을 강제 리렌더한다(마우스 클릭은 네이티브 토글로 이미 반영).
_ROW_ACTION_KEYDOWN = JsCode(
    """
    function(e) {
      if (!e.colDef || e.colDef.field !== '_action') { return; }
      const ev = e.event;
      if (!ev) { return; }
      const key = ev.key;
      if (key !== 'Enter' && key !== ' ' && key !== 'Spacebar') { return; }
      const d = (e.node && e.node.data) || {};
      if (d._row_state === 'group') { return; }
      ev.preventDefault();
      if (d._row_state === 'existing') {
        const cur = (d._sel === true || d._sel === 'true' || d._sel === 1);
        e.node.setDataValue('_sel', !cur);
        if (e.api) { e.api.refreshCells({ rowNodes: [e.node], columns: ['_action'], force: true }); }
      } else {
        e.node.setDataValue('_removed', '1');
      }
    }
    """
)

# _action 컬럼 전용 키 억제 — AG Grid 34.x 는 자체 셀 키 동작(Enter=아래 이동 등)을
# cellKeyDown 디스패치보다 먼저 처리하므로 onCellKeyDown 안의 preventDefault 만으로는
# 기본 내비게이션을 막지 못한다. suppressKeyboardEvent 는 기본 처리 이전에 호출되어
# Enter/Space 에 대해 true 를 반환하면 AG Grid 가 그 키의 기본 동작을 수행하지 않는다.
# 실제 _sel/_removed 동작은 여전히 _ROW_ACTION_KEYDOWN(onCellKeyDown)이 담당한다.
# Tab·화살표 등 다른 키는 false 로 통과시켜 셀 내비게이션을 보존한다.
_ACTION_SUPPRESS_KEYBOARD = JsCode(
    """
    function(params) {
      const ev = params.event;
      if (!ev) { return false; }
      const key = ev.key;
      return (key === 'Enter' || key === ' ' || key === 'Spacebar');
    }
    """
)

# 그리드 내부(iframe) 스타일 — 헤더/셀 가운데 정렬, 문자 셀 좌측 여백,
# 가로·세로 얇은 구분선, − 버튼/체크박스 정렬. 사이드바 계열 색만 사용(네이비 없음).
_MASTER_GRID_CSS = {
    ".ag-root-wrapper": {"border": "1px solid #CFC8BB"},
    ".ag-header": {"border-bottom": "1px solid #CFC8BB"},
    ".ag-header-cell": {"border-right": "1px solid rgba(30, 30, 30, 0.12)"},
    # Codex P2(§3·§8-6): 표 헤더 12.5px — AG 테마 기본(12px)이 .ag-header-cell-text 에
    # 걸려 있어 라벨·텍스트 둘 다 12.5px 로 못박는다(신원 헤더가 셀 14.5 와 정합).
    ".ag-header-cell-label": {"justify-content": "center", "font-size": "12.5px"},
    ".ag-header-cell-text": {"font-size": "12.5px"},
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
        "suppressKeyboardEvent": _ACTION_SUPPRESS_KEYBOARD,
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
        "onCellKeyDown": _ROW_ACTION_KEYDOWN,
        # 자동 빈 행 추가는 쓰지 않는다 — 신규 행은 [＋ 행 추가]/붙여넣기로만 생성.
    }
    if extra_grid_options:
        grid_options.update(extra_grid_options)

    ordered = ["_action"] + order + _META_COLUMNS

    def _mount():
        return AgGrid(
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

    # 편집 그리드는 key(f"{page}_grid_{nonce}") 가 조회·구조변경(remount) 때만 바뀐다.
    # fingerprint=key 로 두면 스켈레톤은 그 remount run 에서만 뜨고(이미 재마운트되는 시점),
    # 일반 편집 rerun(같은 key)에는 뜨지 않아 iframe in-place 유지 → 미저장 셀 입력 보존.
    response = erp.grid_shell(
        key, nrows=len(frame), ncols=len(order) + 1,
        fingerprint=key, render=_mount, height=height,
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
def schedule_screen(user: dict, page_id: str, band=None) -> None:
    scheds = db.get_schedules()
    depts = db.get_departments()
    teams = db.get_teams()
    today = date.today()

    months = sorted({s[:7] for s in scheds["duty_date"]}) if not scheds.empty else []
    years = sorted({int(m[:4]) for m in months} | {today.year})

    dept_names = {r["dept_code"]: r["dept_name"] for _, r in depts.iterrows()}
    manager_locked = user["role"] == "MANAGER" and user.get("dept_code")

    st.markdown(_SV_CSS, unsafe_allow_html=True)
    # 영역 순서(§1-C 읽기): 조건 줄(condition_panel) + 우측 [조회] → 헤어라인 → 컨텍스트 라인
    # → 표 → 범례. 조회/새로고침은 [조회] 버튼(구 밴드 search 아이콘 대체). 클릭 세대값을
    # 올려 콜드 스켈레톤 표출 대상에 포함한다(구 새로고침 동작 보존 — 조회 결과 동일).
    _rg_key = f"{page_id}_refreshgen"

    # condition_panel 의 select Field 는 index/value 인자를 받지 않고 항상 위젯 key 의
    # 세션 상태에 의존한다 — 최초 렌더(키 미존재)에서 기존 selectbox(index=...) 와 같은
    # 기본값(연도=올해·월=이번달)을 내려면 위젯 인스턴스화 전에 세션 상태를 선점해야 한다.
    y_key, m_key, d_key = f"{page_id}_y", f"{page_id}_m", f"{page_id}_d"
    if y_key not in st.session_state:
        st.session_state[y_key] = today.year
    if m_key not in st.session_state:
        st.session_state[m_key] = today.month

    # 부서→조 종속 옵션: 조 Field 를 만들기 전에 "현재" 부서 선택을 세션 상태에서
    # 읽는다(near_miss_view 의 period_on 선-조회 패턴과 동일 — 위젯 렌더 순서가 아니라
    # 세션 상태로 종속을 해석해, 사용자가 부서를 바꾼 그 rerun 에서 조 옵션이 갱신되게 한다).
    if manager_locked:
        cur_dept = user["dept_code"]
        dept_field = erp.Field(
            key="d", label="부서", kind="select",
            options=[user["dept_code"]], disabled=True, width=220,
            format_func=lambda c: dept_names.get(c, c),
        )
    else:
        cur_dept = st.session_state.get(d_key, ALL)
        dept_field = erp.Field(
            key="d", label="부서", kind="select",
            options=[ALL] + list(dept_names), width=220,
            format_func=lambda c: dept_names.get(c, c),
        )
    team_rows = teams[teams["dept_code"] == cur_dept] if cur_dept != ALL else teams.iloc[0:0]
    team_names = {r["team_code"]: r["team_name"] for _, r in team_rows.iterrows()}

    fields = [
        # format_func=str 명시: 키트 select 기본 포맷터(lambda x: x)는 항등함수라
        # int 옵션(연도)을 protobuf 문자열 필드에 그대로 넣으면 TypeError 가 난다
        # (일반 st.selectbox 는 format_func 미지정 시 내부에서 str() 로 감싸주지만,
        # 키트는 항등 폴백을 쓰므로 non-str 옵션에는 항상 format_func 를 명시해야
        # 한다 — 키트 자체는 손대지 않고 호출부에서 회피). str(int) 는 원래
        # selectbox 가 보여주던 "2026" 표시와 동일하다.
        # U4 content-fit: 짧은 코드값 select 는 내용 맞춤 폭, 검색(사번/성명) text 만 신축.
        erp.Field(key="y", label="연도", kind="select", options=years, format_func=str, width=110),
        erp.Field(key="m", label="월", kind="select", options=list(range(1, 13)),
                  format_func=lambda m: f"{m}월", width=100),
        dept_field,
        erp.Field(key="t", label="조", kind="select", width=150,
                  options=[ALL] + list(team_names), format_func=lambda c: team_names.get(c, c)),
        erp.Field(key="kw", label="사번 또는 성명", kind="text"),
    ]
    # 조건 줄 우측 [조회] 인라인(§1-E). U4: content_fit=True 로 짧은 select 는 내용 맞춤 폭·검색만 신축.
    v, clicked = erp.condition_panel(page_id, fields, content_fit=True, submit=("조회", f"{page_id}_go"))
    if clicked:
        st.session_state[_rg_key] = st.session_state.get(_rg_key, 0) + 1
    refresh_gen = st.session_state.get(_rg_key, 0)

    params = {
        "year": v["y"],
        "month": v["m"],
        "dept": v["d"],
        "team": v["t"],
        "keyword": str(v["kw"] or "").strip(),
    }
    # U3: 진입 시 세션 최초 1회 기본 조건(당월·범위 전체)으로 자동 조회 seed — 매 rerun 자동조회가
    # 아니라 최초 1회만, 이후 [조회]가 명시 갱신. 빈 안내 패널 대신 즉시 데이터가 보인다.
    seed_query_once(page_id, params)
    q = run_query(page_id, clicked, params)
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

    # 근무형태 프레임은 이 렌더에서 display_of/color_of 와 wt(맵) 양쪽이 필요하지만,
    # 같은 내용을 두 번 조회·순회하지 않도록 한 번만 가져와 재사용한다(값은 기존과 동일).
    # ── 화면 레벨 스켈레톤 표출 ──────────────────────────────────────────────
    # 콜드 잔상(Supabase 냉캐시 네트워크 로드 ~500–800ms) 구간을 스켈레톤으로 대체한다.
    # 핵심: 그리드에 실릴 콜드 데이터 fetch(db.get_work_types + _build_month_grid — 내부에서
    # get_users/get_month_schedules/get_month_assignments 등 네트워크 호출)를 grid_shell 의
    # prepare 로 넘긴다. 그러면 「스켈레톤 칠하기 → 느린 fetch(prepare) → 그리드로 교체」순서가
    # 되어, fetch 가 도는 그 구간에만 스켈레톤이 뜨고 낡은 그리드 형상을 덮는다.
    # fetch 이후의 클라이언트 AgGrid iframe 마운트(~700ms)는 가릴 수 없다(container 델타가
    # 나간 뒤 마운트가 진행됨) — 커버 대상은 서버측 데이터 로드 구간뿐(부분 개선).
    # fingerprint=load_gen: 조회·새로고침 클릭에서만 전환→스켈레톤. warm/미변경 순수 rerun 은
    # load_gen 불변이라 스켈레톤이 뜨지 않는다(무점멸). warm 로드는 fetch 가 빨라 자연 합쳐진다.
    def _cold_load():
        wt_df = db.get_work_types()
        display_of, color_of = work_type_display(wt_df)
        grid, month_rows = _build_month_grid(q, display_of)
        return wt_df, display_of, color_of, grid, month_rows

    def _render_body(loaded):
        wt_df, display_of, color_of, grid, month_rows = loaded
        if grid.empty:
            ui.empty_state("조회 조건에 해당하는 직원이 없습니다.", head="월별 근무표")
            return

        # §1-C 컨텍스트 라인 — YYYY-MM · 부서 · 조 · 인원·근무·실근무·휴무(모노 수치).
        wt = _work_types_map_from_df(wt_df)
        n_work = sum(1 for c in month_rows["work_type_code"] if wt.get(c, {}).get("is_work"))
        st.markdown(
            _view_context_html(q, dept_names, team_names, len(grid), len(month_rows), n_work),
            unsafe_allow_html=True,
        )

        # primary — 월간 근무표(근무 약칭 + 지정 색상, 읽기 전용).
        day_cols = [c for c in grid.columns if c[0].isdigit()]
        meta_cols = [c for c in grid.columns if c not in day_cols]

        # 퇴직 플래그는 read_grid 의 row_rules 가 참조하는 hidden field 로만 싣는다 —
        # _build_month_grid(불변) 출력을 그대로 복사해 표시용으로만 부가하며, 다운로드용
        # grid(원본)에는 이 컬럼을 남기지 않는다(엑셀 CSV 스키마를 바꾸지 않기 위함).
        grid_ui = grid.copy()
        grid_ui["_retired"] = grid_ui["성명"].astype(str).str.endswith(RETIRED_LABEL)
        # 색 규칙: _cell_style 과 동일하게 표시값(약칭)·코드 양쪽을 색에 매핑하는
        # color_of 를 그대로 재사용해 전 날짜 컬럼에 공유한다(전용 변환 불필요).
        color_rules = {day_col: color_of for day_col in day_cols}
        # 퇴직행 배경/글자색 — _RETIRED_ROW_CSS(불변, _retired_row_style 이 쓰는 값)를
        # row_rules 의 hex 인자 형태로 그대로 파싱해 재사용한다(새 색을 만들지 않는다).
        _retired_parts = dict(
            p.strip().split(":", 1) for p in _RETIRED_ROW_CSS.split(";") if ":" in p
        )
        retired_bg = _retired_parts["background-color"].strip()
        retired_ink = _retired_parts["color"].strip()
        # 폭 지정(pixel QA 로 실측 발견): 키트 기본값(미지정 컬럼 flex=1,minWidth=90) 은
        # 원래 st.dataframe(width="stretch") 의 자동 폭보다 좁아 "PET생산부(본동)" 같은
        # 긴 부서명이 잘렸다(scrollWidth>clientWidth 실측). 데이터·색은 그대로 두고
        # meta 컬럼만 넉넉한 폭으로 지정해 원 화면과 동등한 잘림 없는 표시를 보존한다.
        # 신원 4열은 sticky left(pinned) — §1-C 편성표와 동일한 고정 신원 열. 폭은 pixel QA
        # 실측값 유지(긴 부서명 잘림 방지). read_grid col_config 는 colDef 로 그대로 전달돼
        # pinned 도 지원한다(jscode 불요).
        meta_col_config = {
            "사번": {"width": 84, "pinned": "left"},
            "성명": {"minWidth": 108, "width": 108, "pinned": "left"},
            "부서": {"minWidth": 150, "width": 150, "pinned": "left"},
            "조": {"minWidth": 100, "width": 100, "pinned": "left"},
        }
        # §1-C 표: 흰 컨테이너(1px #cfc8bd·radius 8·내부 스크롤) — 편성표와 동일 시각. 컨테이너
        # 스타일은 iframe 바깥 래퍼(_SV_CSS 의 .st-key-sv_gridwrap)가 소유한다.
        # skeleton=False: 콜드 로드 표출은 상위 grid_shell(prepare) 가 담당(이중 shell 방지).
        with st.container(key="sv_gridwrap"):
            erp.read_grid(
                grid_ui, columns=meta_cols + day_cols, key=f"{page_id}_grid",
                color_rules=color_rules,
                col_config={c: meta_col_config[c] for c in meta_cols if c in meta_col_config},
                row_rules=[{
                    "when": "data['_retired'] === true",
                    "columns": meta_cols, "bg": retired_bg, "ink": retired_ink,
                }],
                hidden_fields=["_retired"],
                skeleton=False,
            )
        st.markdown(_label_legend_html(display_of, color_of), unsafe_allow_html=True)

        # 사용자별 집계 (전체 근무표 조회)
        if page_id == "schedule_view" and not month_rows.empty:
            st.write("")
            ui.panel_head("직원별 근무형태 집계")
            agg = _build_agg(grid, month_rows, wt, display_of)
            erp.read_grid(agg, key=f"{page_id}_agg", skeleton=False)

        # 하단 액션 — 다운로드(원본 grid, 상태/색 부가 없이 그대로 — CSV 스키마 불변).
        st.download_button(
            "엑셀 다운로드",
            grid.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"근무표_{q['year']}-{q['month']:02d}.csv",
            mime="text/csv",
            key=f"{page_id}_dl",
            width="stretch",
        )

    _ndays = calendar.monthrange(int(q["year"]), int(q["month"]))[1]
    # fingerprint = 조회조건 q + 새로고침 세대값. q 가 같으면(같은 데이터) 재전환하지 않아
    # warm/미변경 rerun 에 스켈레톤이 뜨지 않고(무점멸), q 변경/새로고침에만 콜드 표출된다.
    _fp = (tuple(sorted((str(k), str(v)) for k, v in q.items())), refresh_gen)
    erp.grid_shell(
        f"{page_id}_screen",
        nrows=7, ncols=min(_ndays + 4, 8),
        fingerprint=_fp, height=360,
        prepare=_cold_load, render=_render_body,
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
    """대상 월의 부서·조 편성 스냅샷 {emp_no: (dept_code, team_code, shift_group_code)}.

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
            snaps[emp] = (
                _clean(r.get("dept_code")), _clean(r.get("team_code")),
                _clean(r.get("shift_group_code")),
            )
    return snaps


def _build_month_grid(q: dict, display_of: dict | None = None):
    """해당 월/부서/조의 가로형 근무표 DataFrame 과 세로형 원본 레코드를 반환.

    부서·조는 대상 월의 편성 스냅샷(schedule_assignments)을 우선 사용하고, 없으면
    현재 사용자 소속으로 폴백한다(표시 전용·자동저장/백필 없음 — requirements.md §5).
    조회 조건의 부서·조 필터도 같은 스냅샷 기준으로 일관 적용해, 과거 월 조회 시
    인사이동한 직원이 현재 소속으로 오분류되지 않게 한다. 날짜 셀은 내부 코드가 아니라
    근무형태 약칭(display_of)으로 표시한다.

    재직자는 항상 포함한다. 퇴직(비활성)·퇴사일 경과 직원은 해당 월에 저장된 근무
    기록이 있는 경우에만 포함한다(requirements.md §5 조회·§7 소프트 삭제=참조 보존의
    취지 — 과거 기록 조회는 유지하되, 기록 없는 퇴직·퇴사자를 위한 빈 행은 만들지
    않는다). 포함된 퇴직·퇴사자는 성명에 RETIRED_LABEL 을 덧붙여 표시한다.

    퇴사자를 get_users(include_resigned=False)로 아예 빼면 과거 월의 저장된 근무까지
    조회에서 사라진다(2026-08-07 code-review P1) — 그래서 여기서는 전체를 조회한 뒤
    퇴사자를 '비활성과 같은 부류'(기록 있는 월에만 표시)로 접는다.
    """
    display_of = display_of or {}
    users = db.get_users()

    resigned_mask = users["resign_date"].map(db.is_resigned) if "resign_date" in users.columns \
        else pd.Series(False, index=users.index)
    active_mask = users["is_active"].astype(bool) & ~resigned_mask
    inactive_emp_nos = set(
        users.loc[~active_mask, "emp_no"].astype(str).str.strip()
    )
    all_emp_nos = users["emp_no"].astype(str).str.strip()
    scheds_all = db.get_month_schedules(all_emp_nos, q["year"], q["month"])
    emp_with_records = (
        set(scheds_all["emp_no"].astype(str).str.strip()) if not scheds_all.empty else set()
    )
    retired_with_records = inactive_emp_nos & emp_with_records

    users["_eff_active"] = active_mask  # 재직 = is_active AND 퇴사일 미경과
    keep_mask = active_mask | all_emp_nos.isin(retired_with_records)
    users = users[keep_mask].copy()
    users["_retired"] = ~users["_eff_active"].astype(bool)

    # 스냅샷 우선으로 '그 당시 부서/조'를 해석한다(없으면 현재 소속 폴백).
    snaps = _month_assignment_snapshot(q["year"], q["month"])
    eff_depts, eff_teams, eff_shifts = [], [], []
    for _, u in users.iterrows():
        emp = _clean(u.get("emp_no"))
        dept_code, team_code, shift_code = snaps.get(
            emp, (_clean(u.get("dept_code")), _clean(u.get("team_code")), "")
        )
        eff_depts.append(dept_code)
        eff_teams.append(team_code)
        eff_shifts.append(shift_code)
    users["_eff_dept"] = eff_depts
    users["_eff_team"] = eff_teams
    users["_eff_shift"] = eff_shifts

    if q["dept"] != ALL:
        users = users[users["_eff_dept"] == q["dept"]]
        if q["team"] != ALL:
            # 조 필터는 신 축(근무조 직접입력)과 레거시 축(운영단위) 어느 쪽이든 매치한다
            # — 과거 월(team_code 편성)과 새 편성(shift_group_code)이 한 화면에 공존한다.
            users = users[
                (users["_eff_team"] == q["team"]) | (users["_eff_shift"] == q["team"])
            ]
    keyword = str(q.get("keyword", "")).strip()
    if keyword:
        emp_match = users["emp_no"].astype(str).str.contains(
            keyword, case=False, na=False, regex=False,
        )
        name_match = users["name"].astype(str).str.contains(
            keyword, case=False, na=False, regex=False,
        )
        users = users[emp_match | name_match]
    # 정렬: 부서 → 표시순서(display_order, 근태표 등록 순서·NULL 뒤) → 조 → 사번
    # (2026-08-07 사용자 요구 — 파일 등록 순서 유지).
    _orders = []
    for value in users.get("display_order", pd.Series([None] * len(users))):
        try:
            _orders.append(db.normalize_display_order(value))
        except (TypeError, ValueError):
            _orders.append(None)
    users["_d_null"] = [1 if o is None else 0 for o in _orders]
    users["_d_order"] = [0 if o is None else o for o in _orders]
    users = users.sort_values(
        ["_eff_dept", "_d_null", "_d_order", "_eff_shift", "_eff_team", "emp_no"]
    )

    kept_emp_nos = set(users["emp_no"].astype(str).str.strip())
    scheds = (
        scheds_all[scheds_all["emp_no"].astype(str).str.strip().isin(kept_emp_nos)].copy()
        if not scheds_all.empty
        else scheds_all
    )

    lookup = {(r["emp_no"], r["duty_date"]): r["work_type_code"] for _, r in scheds.iterrows()}
    ndays = calendar.monthrange(q["year"], q["month"])[1]
    days = [date(q["year"], q["month"], d) for d in range(1, ndays + 1)]

    # 부서/조 이름은 프레임 전체를 매 행마다 필터링하지 않고, 렌더 1회에 한해
    # 코드->이름 dict 를 미리 만들어 재사용한다(db.dept_name/team_name 과 동일한
    # "첫 매치 우선·미매치 시 코드 그대로" 폴백을 그대로 재현한다).
    dept_name_by_code: dict = {}
    for _, d in db.get_departments().iterrows():
        code = d["dept_code"]
        if code not in dept_name_by_code:
            dept_name_by_code[code] = d["dept_name"]
    team_name_by_key: dict = {}
    for _, t in db.get_teams().iterrows():
        key = (t["dept_code"], t["team_code"])
        if key not in team_name_by_key:
            team_name_by_key[key] = t["team_name"]

    rows = []
    for _, u in users.iterrows():
        dept_code, team_code = u["_eff_dept"], u["_eff_team"]
        name = u["name"]
        if bool(u.get("_retired")):
            name = f"{name}{RETIRED_LABEL}"
        # 조 표시: 신 축(근무조 스냅샷 텍스트)이 있으면 그것, 없으면 레거시 운영단위명.
        shift_code = _clean(u.get("_eff_shift"))
        row = {
            "사번": u["emp_no"],
            "성명": name,
            "부서": dept_name_by_code.get(dept_code, dept_code),
            "조": shift_code or (
                team_name_by_key.get((dept_code, team_code), team_code)
                if team_code
                else ""
            ),
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


def _retired_row_style(row: pd.Series) -> list[str]:
    """퇴직자 행의 사번·성명·부서·조 셀에 음영을 입힌다(색+텍스트 라벨 이중부호화).

    성명에 RETIRED_LABEL 접미사가 붙은 행만 대상이며, 날짜 셀(근무형태 색상)에는
    적용하지 않는다 — 같은 셀에 두 배경 스타일이 겹치면 나중에 적용된 쪽이 우선돼
    _cell_style 의 근무형태 색상 구분이 사라지기 때문이다.
    """
    is_retired = str(row.get("성명", "")).strip().endswith(RETIRED_LABEL)
    css = _RETIRED_ROW_CSS if is_retired else ""
    return [css] * len(row)


def _view_context_html(q: dict, dept_names: dict, team_names: dict,
                       n_people: int, n_rows: int, n_work: int) -> str:
    """§1-C 컨텍스트 라인 — YYYY-MM · 부서 · 조 · 인원·근무·실근무·휴무(모노 수치)."""
    ym = f"{int(q['year'])}-{int(q['month']):02d}"
    dept = "전체 부서" if q.get("dept") == ALL else (dept_names.get(q.get("dept"), q.get("dept")) or "전체 부서")
    team = "전체 조" if q.get("team") == ALL else (team_names.get(q.get("team"), q.get("team")) or "전체 조")
    n_off = n_rows - n_work
    return (
        "<div class='sv-ctx'>"
        f"<span class='num'>{escape(ym)}</span><span class='sep'>·</span>"
        f"<span class='loc'>{escape(str(dept))}</span><span class='sep'>·</span>"
        f"<span class='loc'>{escape(str(team))}</span>"
        "<span class='sep'>|</span>"
        f"<span>인원 <span class='num'>{n_people}</span>명</span>"
        f"<span>근무 <span class='num'>{n_rows}</span>건</span>"
        f"<span>실근무 <span class='num'>{n_work}</span>건</span>"
        f"<span>휴무·휴가 <span class='num'>{n_off}</span>건</span>"
        "</div>"
    )


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
