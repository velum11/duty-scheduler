"""공통 선택형 편집 그리드 어댑터 — ``MasterGridSpec`` + ``render_master_grid``.

Phase2 §2 의 "공통 AgGrid helper 책임"만 담는다:
  메타 컬럼 보정 · bool 정규화 · 기존 행만 체크(신규 행은 − 제거) · select-all 헤더 ·
  native TSV paste(paste.py) · 반환 column/order 정규화.
**검증 · 삭제 정책 · DB 저장은 포함하지 않는다**(lifecycle.py / 화면 controller 몫).

화면별 renderer/editor/컬럼 폭/enum 은 ``col_config`` 로 주입한다(동일 컬럼 구성 강제 금지).
상태 시각은 style.py 의 클래스 기반 규칙(rowClassRules/cellClassRules)만 사용한다 —
임의 DOM 조작을 하지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
from st_aggrid import AgGrid, DataReturnMode, JsCode

from views.master import paste, style

# ---------------------------------------------------------------------------
# 메타 · view-model 컬럼 계약
# ---------------------------------------------------------------------------
# 권위 메타(기존 계약): 행 정체성/상태/선택/제거.
CORE_META = ["_row_id", "_row_state", "_sel", "_removed"]
# 확장 view-model(§25 B5): rowClassRules/cellClassRules 가 읽는 상태 필드.
# controller 가 채우며 미지정 시 안전 기본값('')으로 채워 그리드에 숨김 전달한다.
VIEW_META = ["_delete", "_persist", "_error", "_dirty_fields", "_inactive", "_linked", "_protected"]
META_COLUMNS = CORE_META + VIEW_META

_STRING_META = [m for m in META_COLUMNS if m != "_sel"]


def grid_bool(value) -> bool:
    """Excel 붙여넣기로 들어오는 boolean 텍스트를 명시적으로 정규화한다."""
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "t", "yes", "y", "사용", "재직"}
    return bool(value)


def live_rows(grid_df: pd.DataFrame) -> pd.DataFrame:
    """− 제거 표시된 행을 뺀 유효 행. (권위 상태 반영 전 계산용)"""
    if grid_df is None or "_removed" not in grid_df.columns:
        return grid_df
    return grid_df[grid_df["_removed"].fillna("").astype(str).str.strip() != "1"]


# 그리드 높이 산정·gridOptions 공통 단일 소스 — _build_grid_options 가 아래 상수를
# headerHeight/rowHeight 로 그대로 사용한다(리터럴 중복 제거, 높이 계산과 값 불일치 방지).
_GRID_HEADER_PX = 44   # headerHeight
_GRID_ROW_PX = 40      # rowHeight
_GRID_CHROME_PX = 16   # 테두리·가로 스크롤바 여유(불필요한 세로 스크롤바 방지)
_GRID_MIN_PX = 132     # 0~1행에서도 헤더+빈 상태 오버레이가 답답하지 않은 적정 최소
_GRID_MAX_PX = 460     # 다수 행: 이 이상은 그리드 내부에서 스크롤


# ---------------------------------------------------------------------------
# 셀 텍스트 선택·복사 (전 그리드 공통 단일 원천)
# ---------------------------------------------------------------------------
# 문제: AG Grid 는 기본값 ``enableCellTextSelection=false`` 에서 셀에 ``user-select:none``
# 을 걸어 셀 안의 글자를 드래그 선택할 수 없고, 클립보드 모듈은 Enterprise 전용이라
# Community 에서는 Ctrl+C 도 동작하지 않는다 → "화면에서 입력값을 복사할 수 없다".
#
# 해법(표시 계층 2옵션, 데이터·편집 계약 무변경):
#   - ``enableCellTextSelection``: 셀 텍스트 드래그 선택을 허용한다. AG Grid 34 는 이 값이
#     참이면 자체 Ctrl+C 처리(onCtrlAndC)를 건너뛰어 **브라우저 기본 복사**에 양보한다.
#   - ``ensureDomOrder``: 셀/행 DOM 순서를 화면 순서와 일치시켜 여러 셀에 걸친 선택을
#     복사했을 때 순서가 뒤섞이지 않게 한다(부수효과: 행 애니메이션 비활성 — 밀집 ERP
#     표에서는 오히려 바람직).
#
# 편집·붙여넣기·행선택과의 충돌이 없는 이유:
#   - 셀 편집은 더블클릭/Enter 로 에디터 input 이 열리고 그 input 이 포커스를 가지므로
#     텍스트 선택 허용과 무관하다(``singleClickEdit=False`` 유지).
#   - 범위 붙여넣기(paste.py)는 document 의 paste 이벤트 + ``api.getFocusedCell()`` 기반이며
#     편집 중/IME 조합 중을 먼저 양보한다 — 선택 가능 여부는 이 경로에 관여하지 않는다.
#   - 행 선택(_action 열 체크박스 · select_grid 의 네이티브 rowSelection)은 클릭 이벤트로
#     처리되며 텍스트 선택과 별개 경로다.
#
# read/select 키트(``views/common/erp/kit.py``)와 편성 그리드(``views/workspace.py``)가
# 같은 값을 쓰도록 여기 한 곳에서만 정의한다(리터럴 중복 금지).
CELL_COPY_OPTIONS: dict = {
    "enableCellTextSelection": True,
    "ensureDomOrder": True,
}


def master_grid_height(nrows: int) -> int:
    """헤더+실제 행 수에 맞춘 동적 높이(≈132~460px).

    소수 행(0~1건)일 때 큰 빈 표가 남지 않도록 실제 행 수에 적응하되, 빈 상태에서도
    답답하지 않은 최소를 유지하고 다수 행은 그리드 내부 스크롤로 넘긴다.
    """
    natural = _GRID_HEADER_PX + max(int(nrows), 1) * _GRID_ROW_PX + _GRID_CHROME_PX
    return max(_GRID_MIN_PX, min(natural, _GRID_MAX_PX))


# ---------------------------------------------------------------------------
# 첫 열 렌더러 — 기존 행=선택 체크박스, 신규 행=− 제거 버튼(팬텀 선택 차단).
# 그룹 부모 행(조직)은 빈 셀. (검증된 자산을 계승)
# ---------------------------------------------------------------------------
_ROW_ACTION_RENDERER = JsCode(
    """
    (class {
      init(params) {
        const d = params.data || {};
        const eGui = document.createElement('div');
        eGui.className = 'md-act';
        if (d._row_state === 'group') { this.eGui = eGui; return; }
        if (d._row_state === 'existing') {
          const cb = document.createElement('input');
          cb.type = 'checkbox'; cb.className = 'md-act-cb';
          cb.checked = (d._sel === true || d._sel === 'true' || d._sel === 1);
          if (d._protected === '1' || d._protected === 1) { cb.disabled = true; cb.title = '보호된 행'; }
          eGui.appendChild(cb);
        } else {
          const btn = document.createElement('button');
          btn.type = 'button'; btn.className = 'md-act-rm';
          btn.title = '이 신규 행 삭제'; btn.setAttribute('aria-label', '신규 행 삭제');
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

_SELECT_ALL_HEADER = JsCode(
    """
    (class {
      init(params) {
        this.params = params;
        const eGui = document.createElement('div'); eGui.className = 'md-act';
        const cb = document.createElement('input');
        cb.type = 'checkbox'; cb.className = 'md-act-cb';
        cb.title = '표시된 기존 행 전체 선택'; cb.setAttribute('aria-label', '표시된 기존 행 전체 선택');
        eGui.appendChild(cb);
        this.eGui = eGui; this.cb = cb;
        this.refreshState = this.refreshState.bind(this);
        cb.addEventListener('click', (e) => {
          e.stopPropagation();
          const target = cb.checked;
          params.api.forEachNodeAfterFilter((node) => {
            const d = node.data || {};
            if (d._row_state === 'existing' && String(d._removed || '') !== '1'
                && !(d._protected === '1' || d._protected === 1)) {
              node.setDataValue('_sel', target);
            }
          });
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
          if (d._row_state === 'existing' && String(d._removed || '') !== '1'
              && !(d._protected === '1' || d._protected === 1)) {
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

_ROW_ACTION_CLICK = JsCode(
    """
    function(e) {
      if (!e.colDef || e.colDef.field !== '_action') { return; }
      const t = e.event && e.event.target;
      if (!t || !t.classList) { return; }
      const d = e.node && e.node.data || {};
      if (t.classList.contains('md-act-rm')) {
        e.node.setDataValue('_removed', '1');
      } else if (t.classList.contains('md-act-cb')) {
        if (d._protected === '1' || d._protected === 1) { return; }
        e.node.setDataValue('_sel', !!t.checked);
      }
    }
    """
)

# 첫 열 키보드 처리(WCAG 2.1.1) — AG Grid 셀 내비게이션은 .ag-cell 래퍼로만 Tab 이동하고
# cellRenderer 내부의 네이티브 입력은 Tab 순서에 없다. 포커스된 _action 셀에서 Enter/Space 가
# 마우스 클릭과 동일한 동작(기존 행=_sel 토글, 신규 행=_removed)을 하도록 한다.
# onCellClicked(마우스)는 그대로 두고, 여기서는 셀 데이터로 동작을 판정한다(포커스는 래퍼에
# 있어 e.event.target 이 입력 요소가 아니기 때문). preventDefault 로 AG Grid 기본 키 동작을
# 막는다. 보호된 행은 클릭과 동일하게 무시한다. _sel 은 숨김 컬럼이라 setDataValue 만으로는
# 체크박스 표시가 갱신되지 않으므로 해당 행 _action 셀을 강제 리렌더한다.
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
      if (d._row_state === 'existing' && (d._protected === '1' || d._protected === 1)) { return; }
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

# ---------------------------------------------------------------------------
# [LEGACY / 미사용] 공통 bool 표시 렌더러(JsCode). **더 이상 기본 적용하지 않는다.**
# JsCode 셀 렌더러는 Streamlit Cloud Python 3.14 배포 환경에서 실행되지 않아 체크박스가
# 행마다 사라지는 High 회귀가 있었다(로컬 3.13 만 정상). 그래서 bool 표시는 native
# ``cellDataType='boolean'``(ag-grid 자체 렌더러 — 환경·버전 무관)로 전환했다.
# 이 심볼은 하위호환(외부 import 안전)을 위해 남겨두나 신규 사용 금지 — 배포에서 깨진다.
# ---------------------------------------------------------------------------
BOOL_DISPLAY_RENDERER = JsCode(
    """
    (class {
      init(p) {
        const v = (p.value === true || p.value === 'true' || p.value === 1
                   || p.value === '사용' || p.value === '재직');
        const g = document.createElement('div');
        g.style.display='flex'; g.style.alignItems='center'; g.style.justifyContent='center'; g.style.height='100%';
        const cb = document.createElement('input');
        cb.type='checkbox'; cb.checked=v; cb.style.width='16px'; cb.style.height='16px';
        cb.style.margin='0'; cb.style.accentColor='#1E3A6E'; cb.style.pointerEvents='none';
        cb.tabIndex=-1; cb.setAttribute('aria-hidden','true');
        g.appendChild(cb); this.eGui = g;
      }
      getGui() { return this.eGui; }
      refresh() { return false; }
    })
    """
)

_NO_ROWS = ("<span style='color:%s;font-size:.82rem;'>표시할 데이터가 없습니다</span>"
            % style.TOKENS["ink-3"])

# 화면 지정이 없을 때의 폭/정렬 기본값(문자=flex, 숫자/불리언=좁은 고정).
_DEFAULT_WIDTHS = {
    "부서코드": {"flex": 1, "minWidth": 120, "cellClass": "md-c-left"},
    "부서명": {"flex": 2, "minWidth": 200, "cellClass": "md-c-left"},
    "표시순서": {"width": 108, "minWidth": 92, "maxWidth": 140, "cellClass": "md-c-center ms-num"},
    "사용": {"width": 82, "minWidth": 72, "maxWidth": 108, "cellClass": "md-c-center"},
}


@dataclass
class MasterGridSpec:
    """한 그리드의 표시·동작 계약. 화면(controller)이 만들어 ``render_master_grid`` 에 넘긴다.

    - ``page_id``: paste uid·기본 로깅 스코프.
    - ``columns``: {표시명: "text"|"bool"} — 값 정규화 종류.
    - ``order``: 표시 순서(메타 컬럼 제외한 데이터 컬럼).
    - ``col_config``: {표시명: AgGrid 컬럼 속성} — 폭·pinned·editable(JsCode)·cellRenderer·
      cellEditor·cellClassRules 등 화면별 주입. (renderer/editor 주입 지점)
    - ``select_all``: 선택 열 헤더 3상태 전체선택(표시 중 기존 행만).
    - ``row_class_rules``: None 이면 style.master_row_class_rules() 기본 적용.
    - ``grid_options``: 최종 gridOptions 에 덮어쓸 추가 옵션(rowClassRules 병합 대상 아님).
    - ``height``: None 이면 행 수 기반 자동.
    """

    page_id: str
    columns: dict
    order: list[str]
    col_config: dict = field(default_factory=dict)
    select_all: bool = True
    row_class_rules: dict | None = None
    grid_options: dict = field(default_factory=dict)
    height: int | None = None
    include_group_rows: bool = False
    include_linked_rows: bool = False


def prepare_frame(spec: MasterGridSpec, frame: pd.DataFrame) -> pd.DataFrame:
    """그리드 입력 프레임을 메타·view-model·데이터 컬럼 계약으로 보정한다.

    - 메타 컬럼을 채우고(_sel bool, 나머지 문자열) _removed 는 매 렌더 초기화한다.
    - 데이터 컬럼은 bool→grid_bool, text→빈문자 string 으로 정규화한다.
    누락 컬럼은 안전 기본값으로 생성해 KeyError 없이 렌더된다.
    """
    frame = frame.copy().reset_index(drop=True)
    defaults = {"_row_id": "", "_row_state": "new", "_sel": False}
    for meta in META_COLUMNS:
        if meta not in frame:
            frame[meta] = defaults.get(meta, "")
    frame["_sel"] = frame["_sel"].map(grid_bool)
    frame["_removed"] = ""  # 반환 데이터의 stale 제거 표식이 재유입되지 않게 초기화
    for meta in _STRING_META:
        frame[meta] = frame[meta].fillna("").astype(str)
    frame["_action"] = ""
    for name, kind in spec.columns.items():
        if name not in frame:
            frame[name] = False if kind == "bool" else ""
        elif kind == "bool":
            frame[name] = frame[name].map(grid_bool)
        else:
            frame[name] = frame[name].fillna("").astype("string")
    return frame


def _build_column_defs(spec: MasterGridSpec) -> list[dict]:
    action_col = {
        "field": "_action", "headerName": "선택", "pinned": "left",
        "width": 66, "minWidth": 56, "maxWidth": 74,
        "editable": False, "sortable": False, "filter": False, "resizable": False,
        "suppressMovable": True, "cellRenderer": _ROW_ACTION_RENDERER,
        "suppressKeyboardEvent": _ACTION_SUPPRESS_KEYBOARD,
        "headerClass": "md-h-center", "cellClass": "md-c-center",
    }
    if spec.select_all:
        action_col["headerComponent"] = _SELECT_ALL_HEADER
    defs = [action_col]
    overrides = spec.col_config or {}
    for name in spec.order:
        kind = spec.columns[name]
        base = _DEFAULT_WIDTHS.get(name, {})
        override = overrides.get(name, {})
        col = {
            "field": name, "headerName": name, "editable": True,
            "sortable": False, "filter": False, "resizable": True,
            "headerClass": "md-h-center",
            "cellClass": override.get("cellClass", base.get("cellClass", "md-c-left")),
        }
        for src in (base, override):
            for k, v in src.items():
                if k != "cellClass":
                    col[k] = v
        if kind == "bool":
            # native bool: ag-grid 자체 boolean 렌더러/에디터를 쓴다(JsCode 미실행 배포에서도
            # 전 행 일관 체크박스). 자동 타입추론에 맡기지 않고 명시해 빈 그리드·신규 행에서도
            # text 로 흐르지 않게 한다. 화면 col_config 의 cellRenderer/cellDataType 는 우선.
            col.setdefault("cellDataType", "boolean")
            col.setdefault("cellEditor", "agCheckboxCellEditor")
        defs.append(col)
    for meta in META_COLUMNS:
        defs.append({"field": meta, "hide": True, "editable": False,
                     "suppressColumnsToolPanel": True})
    return defs


def _build_grid_options(spec: MasterGridSpec) -> dict:
    rules = spec.row_class_rules
    if rules is None:
        rules = style.master_row_class_rules(
            include_group=spec.include_group_rows,
            include_linked=spec.include_linked_rows,
        )
    options = {
        "columnDefs": _build_column_defs(spec),
        "defaultColDef": {"resizable": True, "sortable": False, "filter": False},
        "suppressRowClickSelection": True,
        "suppressDragLeaveHidesColumns": True,
        "rowHeight": _GRID_ROW_PX, "headerHeight": _GRID_HEADER_PX,
        "overlayNoRowsTemplate": _NO_ROWS,
        # 열 폭은 내용에서 역산하지만(§3.1) 합이 그리드 폭보다 작으면 표 안에 빈 띠가
        # 남아 "표가 화면보다 작아" 보인다. fitGridWidth 는 남는 폭을 각 열의 지정 폭에
        # **비례해** 나눠 주므로 한 열만 커지던 flex 방식과 달리 열 사이 비율이 유지된다.
        # 좁은 폭에서는 minWidth 까지만 줄이고 그 아래로는 표 내부 가로 스크롤로 떨어진다.
        "autoSizeStrategy": {"type": "fitGridWidth"},
        "onCellClicked": _ROW_ACTION_CLICK,
        "onCellKeyDown": _ROW_ACTION_KEYDOWN,
        "rowClassRules": rules,
        # 셀 텍스트 선택·복사(편집/붙여넣기/행선택 무영향) — CELL_COPY_OPTIONS 주석 참조.
        **CELL_COPY_OPTIONS,
    }
    # paste/IME/commit handshake 옵션(onGridReady 포함) 병합.
    paste.apply_paste_options(options, _paste_uid(spec))
    # 화면별 추가 옵션(예: 조직 rowClassRules 확장/이벤트) 덮어쓰기.
    if spec.grid_options:
        options.update(spec.grid_options)
    return options


def _paste_uid(spec: MasterGridSpec) -> str:
    return f"msgrid::{spec.page_id}"


def normalize_result(spec: MasterGridSpec, result) -> pd.DataFrame | None:
    """AgGrid 반환 데이터를 컬럼/타입 안정화한다(메타 문자열, _sel bool)."""
    if not isinstance(result, pd.DataFrame):
        return None
    result = result.copy()
    for name, kind in spec.columns.items():
        if name not in result.columns:
            continue
        if kind == "bool":
            result[name] = result[name].map(grid_bool)
        else:
            result[name] = result[name].fillna("").astype("string")
    for meta in _STRING_META:
        if meta not in result.columns:
            result[meta] = ""
        result[meta] = result[meta].fillna("").astype(str)
    result["_sel"] = result["_sel"].map(grid_bool) if "_sel" in result.columns else False
    return result


def render_master_grid(spec: MasterGridSpec, frame: pd.DataFrame, *, key: str) -> pd.DataFrame:
    """스펙에 따라 편집 그리드를 렌더하고 정규화된 현재 데이터를 반환한다.

    반환 프레임은 메타·view-model 컬럼을 포함한다. 구조 변경(붙여넣기/− 제거/신규 id
    부여)의 권위 반영은 호출부(state.next_rid + set_rows)가 담당한다 — 여기서는 하지 않는다.
    """
    prepared = prepare_frame(spec, frame)
    options = _build_grid_options(spec)
    ordered = ["_action"] + list(spec.order) + META_COLUMNS
    height = spec.height if spec.height is not None else master_grid_height(len(prepared))
    response = AgGrid(
        prepared[ordered],
        gridOptions=options,
        key=key,
        height=height,
        update_on=[("cellValueChanged", 200)],
        data_return_mode=DataReturnMode.AS_INPUT,
        allow_unsafe_jscode=True,
        theme="streamlit",
        custom_css=style.GRID_CSS,
        show_toolbar=False,
        show_search=False,
    )
    normalized = normalize_result(spec, response.data)
    return normalized if normalized is not None else prepared
