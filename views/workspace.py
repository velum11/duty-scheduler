"""근무표/기준정보 업무 화면이 공유하는 공통 프레임과 헬퍼.

화면별 파일(schedule_edit, schedule_view, master_*)은 각자 render() 만 두고,
아래 공통 요소를 조합해 DESIGN.md §10 구조를 구성한다:
  페이지 제목 → 한 줄 설명 → 조회 조건 카드 → 요약 카드 → 데이터 그리드 → 하단 액션.

조회 갱신 방식은 화면별로 다르다: 월간 근무표(:func:`schedule_screen`)는 조건 위젯
변경이 곧 조회이며(별도 [조회] 버튼 없음), 재조회는 상단 52px 헤더의 새로고침
아이콘이 담당한다. :func:`run_query`/:func:`seed_query_once` 게이트는 아직 명시적
[조회] 버튼을 쓰는 화면(아차사고 조회)이 그대로 사용한다. 그리드는 읽기 전용으로
근무코드 색상을 입힌다. 기준정보/근무표의 등록·수정 저장 로직은 이후 단계에서
이 화면 위에 얹는다.
"""
import calendar
from datetime import date
from functools import partial
from html import escape

import pandas as pd
import streamlit as st
from st_aggrid import AgGrid, DataReturnMode, GridOptionsBuilder, JsCode

from modules import db, nav, ui
from views.common import erp
from views.master.grid import CELL_COPY_OPTIONS

ALL = "(전체)"
# 조직 계층 표시(대분류·중분류) 폴백 라벨 — 조직 관리에 분류가 입력되지 않은(또는 마스터에
# 없는) 부서코드도 행을 감추지 않고 여기로 접어 **항상 마지막**에 둔다.
UNCLASSIFIED_LABEL = "무분류"

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
/* 컨텍스트 줄 + [엑셀 다운로드] 한 줄 — 버튼은 내용 맞춤(줄바꿈 금지), 컨텍스트만 신축.
   좁은 폭에서 컨텍스트가 먼저 wrap 되고 버튼 라벨은 온전히 남는다(겹침·2줄 방지). */
.st-key-sv_ctxrow { align-items:center; flex-wrap:nowrap !important; }
/* 컨텍스트 markdown(직계 첫 자식)이 잔여 폭을 흡수하고 내부에서 wrap 한다 —
   modules/ui.py::_breadcrumb_header 의 hdr_row 와 동일 패턴(검증된 참조). */
.st-key-sv_ctxrow > div:first-child { flex:1 1 auto; min-width:0; }
.st-key-sv_ctxdl { flex:0 0 auto; }
.st-key-sv_ctxdl button { white-space:nowrap; }
.st-key-sv_ctxrow .sv-ctx { margin:0; }
.st-key-sv_gridwrap [data-testid="stCustomComponentV1"],
.st-key-sv_gridwrap div[data-testid="stAgGrid"] {
  border:1px solid #cfc8bd; border-radius:8px; overflow:hidden; background:#ffffff;
}
/* 뷰포트 프로브(_VIEWPORT_PROBE) — 값을 읽기만 하는 0크기 요소다. display:none 은
   컴포넌트 마운트 여부를 브라우저 구현에 맡기게 되므로 쓰지 않고, 흐름에서만 빼
   (absolute) 세로 리듬(블록 gap)에 영향을 주지 않게 한다. */
.st-key-sv_vp { position:absolute; width:0; height:0; overflow:hidden; }
/* 모바일 세로 한 줄 안내(가로 전환 제안) — 장식·아이콘 없이 보조 텍스트 1줄(§A-2 #6b665d). */
.sv-rotate { font-size:12.5px; color:#6b665d; margin:0 0 6px; line-height:1.35; }
/* 모바일 가로(낮은 뷰포트): 표가 화면을 최대로 쓰도록 상하 여백을 압축한다.
   폰트·색·컨트롤 크기(히트영역)는 그대로다(§3 타이포·§4 44px 불변) — 줄이는 것은
   여백과 '한 줄 설명'뿐이다(제목·조건·표·범례는 모두 남는다). 이 화면이 렌더되는
   동안에만 주입되며, 세로·데스크톱에는 적용되지 않는다. */
@media (orientation:landscape) and (max-height:540px) {
  section[data-testid="stMain"] .block-container { padding-bottom:.5rem !important; }
  /* 제목 아래 한 줄 설명 — 폰 가로에서는 접는다(제목은 상단 앱바·본문 양쪽에 남는다).
     블록 간 gap(0.65rem)은 건드리지 않는다: Streamlit 마크다운 컨테이너의 음수 하단
     마진과 겹쳐 제목이 조건 줄 라벨 위로 올라타는 겹침이 실측됐다. */
  .ms-desc { display:none !important; }
  [class*="st-key-erpcond_"] { padding-bottom:6px !important; margin-bottom:6px !important; }
  [class*="st-key-erpcond_"] [data-testid="stVerticalBlock"] { gap:2px !important; }
  .st-key-sv_ctxrow .sv-ctx { margin:0 !important; }
  .duty-legend { margin-top:4px !important; }
}
</style>
"""
# 일자 열 밀도(§1-C "셀 min-width 34px" + 편성표 col_config 실값 44/34 정합). 읽기 표는
# 헤더가 "31(일)" 한 줄이라 편성표(2줄 헤더 컴포넌트)보다 하한이 조금 크다 — 아래 값은
# 실렌더 측정(헤더 라벨 잘림 없음)으로 잡았다. 상한은 넓은 화면에서 표가 다시 벌어지지
# 않게 하는 캡이다.
_DAY_COL_MIN_PX = 40
_DAY_COL_MAX_PX = 52
# 표 높이 — 행 수에 따라 늘되 §1-C(≈62vh) 상한 안에서 내부 스크롤(편성표와 같은 규칙).
_GRID_MIN_PX, _GRID_MAX_PX = 240, 500
# 좁은 폭(모바일)에서의 표 높이 하한 — 폰 가로는 뷰포트 높이가 ~390px 라 데스크톱 하한
# (240)을 그대로 쓰면 표가 화면 밖으로 밀린다. 헤더 + 3행 정도가 보이는 값.
_GRID_MIN_COMPACT_PX = 150
# 좁은 폭에서 표 위·아래가 쓰는 화면 크롬 높이(390×844 / 844×390 실측값) — 표 높이를
# "뷰포트 - 크롬" 으로 잘라 표가 화면 밖으로 밀리지 않게 한다. 세로는 앱바 52 + 제목·설명
# + 조건(폰 폭에서 여러 줄로 접힘) + 컨텍스트 줄 + 안내 줄 + 범례, 가로는 같은 요소를
# CSS(@media orientation:landscape)로 압축한 뒤의 값이다. 조건 줄은 폭에 따라 접히는
# 줄 수가 달라지므로 정확한 합이 아니라 **상한을 정하는 근사값**이다.
_COMPACT_CHROME_PORTRAIT_PX = 493
_COMPACT_CHROME_LANDSCAPE_PX = 258
# 좁은 폭 판정 기준 — 폭이 좁거나(세로 폰) 짧은 변이 작을 때(가로 폰) 모두 '모바일'이다.
# 폭만 보면 폰 가로(844×390)가 데스크톱으로 잡혀, 정작 가로로 돌린 사용자가 신원 5열에
# 화면을 다 빼앗긴다(폰 세로 폭 390 < 신원 5열 합계 488px).
_COMPACT_MAX_W = 768
_COMPACT_MAX_MIN_SIDE = 540
# 모바일에서 남기는 신원 열 — 사용자 요구(2026-08-13): "모바일은 이름, 근무표만".
# 표시만 줄이며 데이터(_build_month_grid 결과)와 CSV 다운로드 원본은 그대로다.
_COMPACT_META_COLS = ("성명",)

# 뷰포트 프로브 — 좁은 폭/방향/높이를 파이썬으로 올린다(CCv2: iframe 이 아니라 그림자 DOM
# 이라 window 값이 실제 뷰포트다). AgGrid 는 components.v1 iframe 이라 페이지 CSS 가 표
# 내부에 닿지 않고, 열 표시/표 높이는 gridOptions(서버측)로만 정할 수 있다 — 그래서 폭을
# CSS 가 아니라 값으로 받는다. 전송은 '파이썬이 아는 값과 달라졌을 때'만 한다(폰 주소창
# 접힘 같은 작은 높이 변화 ±120px 는 무시) — 리렌더 폭주 방지.
_VIEWPORT_PROBE = partial(
    st.components.v2.component,
    "duty_viewport_probe",
    html="<span aria-hidden='true'></span>",
    js="""
    export default function (component) {
      const { data, setTriggerValue } = component;
      const MAX_W = %(max_w)d, MAX_MIN_SIDE = %(max_min_side)d, H_TOLERANCE = 120;
      const read = () => {
        const w = window.innerWidth || document.documentElement.clientWidth || 0;
        const h = window.innerHeight || document.documentElement.clientHeight || 0;
        return {
          w: w, h: h, landscape: w > h,
          compact: w <= MAX_W || Math.min(w, h) <= MAX_MIN_SIDE,
        };
      };
      const send = () => {
        const now = read();
        const last = data || {};
        if (last.compact === now.compact && last.landscape === now.landscape
            && Math.abs((last.h || 0) - now.h) <= H_TOLERANCE) { return; }
        setTriggerValue('viewport', now);
      };
      send();
      let timer = null;
      const onResize = () => { clearTimeout(timer); timer = setTimeout(send, 250); };
      window.addEventListener('resize', onResize);
      window.addEventListener('orientationchange', onResize);
      return () => {
        clearTimeout(timer);
        window.removeEventListener('resize', onResize);
        window.removeEventListener('orientationchange', onResize);
      };
    }
    """ % {"max_w": _COMPACT_MAX_W, "max_min_side": _COMPACT_MAX_MIN_SIDE},
)

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
    # 행 드래그 핸들 — AG Grid 는 rowDrag 를 켠 열의 .ag-cell-wrapper 안에 드래그 핸들 →
    # 셀 값 순으로 넣는다. 래퍼(.ag-cell-wrapper) 자체는 enableCellTextSelection 때문에
    # **모든 셀**에 생기므로(실측), 반드시 _action 열로 한정해야 한다 — 전역으로 걸면
    # md-c-left(사번·성명·부서·조) 좌측 정렬이 가운데로 무너진다.
    '.ag-cell[col-id="_action"] .ag-cell-wrapper': {
        "width": "100%", "display": "flex", "align-items": "center",
        "justify-content": "center", "gap": "4px",
    },
    '.ag-cell[col-id="_action"] .ag-cell-value': {"flex": "0 0 auto", "width": "auto"},
    ".ag-row-drag": {"cursor": "grab", "opacity": "0.62", "margin": "0"},
    ".ag-row-drag:hover": {"opacity": "1"},
    ".ag-row-drag:active": {"cursor": "grabbing", "opacity": "1"},
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
    row_drag: bool = False,
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
    row_drag: True 면 선택 열(_action)에 AG Grid 내장 드래그 핸들을 붙이고 관리형 행
      이동(rowDragManaged)을 켠다. 반환 프레임의 행 순서가 곧 화면 순서이며, 이동 확정은
      rowDragEnd 로 서버에 통지된다(호출부가 권위 상태를 그 순서로 확정해야 한다).
      전용 핸들 방식이라 셀 텍스트 선택(enableCellTextSelection)·− 제거/체크박스 클릭
      분기와 경쟁하지 않는다. 기본 False 로 기존 화면 무변경.
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
    if row_drag:
        # 핸들은 셀 렌더러(체크박스/− 버튼) 앞에 들어간다 — 폭을 그만큼 넓혀 잘림을 막는다.
        action_col["rowDrag"] = True
        action_col["headerTooltip"] = "행 앞 핸들을 잡고 끌어 순서를 바꿉니다"
        action_col.update({"width": 88, "minWidth": 80, "maxWidth": 96})
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
        # 셀 텍스트 선택·복사(편집·범위 붙여넣기 무영향) — views/master/grid.py 단일 원천.
        **CELL_COPY_OPTIONS,
    }
    if row_drag:
        # 관리형 이동 — AG Grid 가 clientSide 행 모델의 순서를 직접 바꾸므로 반환 노드
        # 순서가 곧 화면 순서다. 이 그리드는 정렬·필터·페이지네이션이 모두 꺼져 있어
        # (sortable/filter False) 관리형 이동의 전제 조건을 충족한다.
        grid_options["rowDragManaged"] = True
        grid_options["rowDragEntireRow"] = False  # 행 아무 데나가 아니라 핸들에서만 시작
    if extra_grid_options:
        grid_options.update(extra_grid_options)

    ordered = ["_action"] + order + _META_COLUMNS
    # 값 편집 외에 '이동 확정'도 서버로 올린다 — 드래그 후 rerun 이 없으면 다음 remount 에서
    # 순서가 소실된다. 디바운스는 편집과 동일 200ms.
    update_on = [("cellValueChanged", 200)] + ([("rowDragEnd", 200)] if row_drag else [])

    def _mount():
        return AgGrid(
            frame[ordered],
            gridOptions=grid_options,
            key=key,
            height=height,
            update_on=update_on,
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


# ---------- 근태(근무표) 등록 대상 부서 범위 ----------
# 조직 관리에서 지정한 근태 등록 대상 부서(departments.tracks_attendance, migration 011)를
# 이 조회 화면의 범위로 쓴다(2026-08-14 사용자 요구: "근태에서는 해당 조직만 목록이나 조회").
# 데이터 계층 계약(modules/db)은 그대로 소비만 한다.
#
# 이 화면의 판단(조회 화면 = 과거 이력 보존 우선):
#   1) 대상 집합은 ``db.attendance_dept_codes(is_active=None)`` 을 쓴다 — **사용 중지된
#      부서라도 근태 대상 지정이 남아 있으면 과거 근무 기록을 계속 조회**한다. 조직이
#      폐지됐다는 이유로 그 달의 저장된 근무표가 사라지면 자료가 소실된 것처럼 보인다.
#      (편성 같은 쓰기 화면은 반대로 활성 대상만 써야 한다 — 화면별 판단이다.)
#   2) 제한은 '허용 목록'이 아니라 **차단 목록**으로 표현한다: 부서 마스터에 있으면서
#      근태 대상이 아닌 부서만 감춘다. 마스터에 없는 부서코드(삭제된 부서의 과거 편성
#      스냅샷)와 부서 미배정(빈 코드) 행은 **지정 여부를 판정할 수 없으므로 감추지
#      않는다** — org_labels 의 "무분류로 접되 행을 감추지 않는다"(근무 기록을 조용히
#      버리지 않는다)와 같은 규율이며, db 파사드의 fail-open 방향과도 일치한다.
#   3) 지정 컬럼을 판독할 수 없는 배포(``db.attendance_flag_ready() is False``)에서는
#      차단 목록이 비어 종전과 동일하게 전 부서를 조회한다.
def attendance_dept_options(dept_names: dict, tracked: set | None) -> dict:
    """부서 조회 옵션 — 근태 등록 대상 부서만 남긴 {코드: 부서명}(순수).

    ``tracked`` 가 ``None`` 이면(지정 컬럼 미적용 폴백) 원본을 그대로 돌려준다.
    """
    if tracked is None:
        return dict(dept_names)
    return {code: name for code, name in dept_names.items() if _clean(code) in tracked}


def attendance_blocked_depts(dept_names: dict, tracked: set | None) -> tuple[str, ...]:
    """조회에서 감출 부서코드 — 마스터에 있으면서 근태 대상이 **아닌** 부서만(순수).

    반환은 정렬 고정 튜플이다(조회 지문·표시 흔들림 방지). ``tracked`` 가 ``None``
    이면 빈 튜플 = 제한 없음(종전 동작).
    """
    if tracked is None:
        return ()
    return tuple(sorted(
        code for code in (_clean(c) for c in dept_names) if code and code not in tracked
    ))


def month_empty_message(q: dict, tracked: set | None) -> str:
    """빈 결과 안내 문구 — 근태 대상 지정 때문에 비었으면 이유와 다음 행동을 알린다(순수).

    행이 0건인 이유가 "조건에 맞는 사람이 없음"인지 "그 부서가 근태 대상이 아님"인지
    구분되지 않으면 사용자는 자료가 사라진 것으로 읽는다. 한 줄 안내 안에서만 구분한다
    (§0.6 빈 상태 1줄 — 별도 배너·박스를 만들지 않는다).
    """
    if tracked is not None:
        if not tracked:
            return ("근태 등록 대상 부서가 아직 지정되지 않았습니다. "
                    "조직 관리에서 대상 부서를 지정하면 조회됩니다.")
        dept = _clean(q.get("dept"))
        if dept and dept != ALL and dept not in tracked:
            return ("선택한 부서는 근태 등록 대상이 아닙니다. "
                    "조직 관리에서 지정하면 조회됩니다.")
    return "조회 조건에 해당하는 직원이 없습니다."


# ---------- 좁은 폭(모바일) 레이아웃 · 조회조건 기본값 ----------
def scope_defaults(user: dict, dept_names: dict, assigns: pd.DataFrame | None) -> tuple[str, str]:
    """최초 진입 시 심을 (부서, 조) 기본값 — 없으면 빈 문자열(= 전체 폴백)을 돌려준다(순수).

    **부서**: 사용자 레코드(`users.dept_code`)다. ``dept_names`` 에 없는 코드면 시드하지
    않는다 — 조회 결과가 0건이 되는 조건을 기본값으로 심지 않기 위해서다. 호출부가 넘기는
    ``dept_names`` 는 **부서 조회 옵션과 같은 집합**(근태 등록 대상 부서)이므로, 로그인
    사용자의 부서가 근태 비대상이면 시드 자체가 일어나지 않고 '(전체)'로 열린다 — 옵션에
    없는 값이 조건에 실려 빈 화면이 되는 경로를 위젯 생성 전에 차단한다.

    **조**: 조 축은 기준정보가 아니라 편성 스냅샷(`schedule_assignments.shift_group_code`)
    이므로 대상 월 **본인 편성**을 1순위 원천으로 쓴다. 해석 순서는 이 화면이 표에서 쓰는
    유효 조(:func:`_build_month_grid` 의 ``_eff_shift``/``_eff_team``)와 같다:

      1. 스냅샷 근무조 ``shift_group_code`` (신 축, 편성 직접입력)
      2. 스냅샷 운영단위 ``team_code`` (과거 월 레거시 축)
      3. 편성이 없으면 ``users.team_code`` — 스냅샷이 없는 월에 표가 쓰는 현재 소속
         폴백과 **같은 값**이라, 심은 조건 안에 본인이 반드시 포함된다.

    옵션 집합에 없는 값은 호출부(위젯 생성 전 유효성 검사)가 '(전체)'로 되돌린다.
    """
    dept = _clean(user.get("dept_code"))
    seed_dept = dept if dept and dept in dept_names else ""
    seed_team = ""
    if assigns is not None and not assigns.empty:
        row = assigns.iloc[0]
        seed_team = _clean(row.get("shift_group_code")) or _clean(row.get("team_code"))
    if not seed_team:
        seed_team = _clean(user.get("team_code"))
    return seed_dept, seed_team


def _seed_scope_defaults(user: dict, page_id: str, dept_names: dict, year: int, month: int) -> None:
    """조회조건(부서·조)에 **선택값이 없을 때만** 로그인 사용자 소속을 심는다.

    규율은 연·월 기본값(위 ``y_key``/``m_key`` 선점)과 같다 — 값이 있는 위젯 키는 절대
    덮어쓰지 않으므로, 화면에 머무는 동안 사용자가 바꾼 선택('전체 부서' 포함)은 그대로
    유지된다. 위젯 인스턴스화 **전**에만 세션 키를 쓸 수 있어 조건 패널 렌더 앞에서 부른다.

    '세션 1회 플래그' 대신 값 유무로 판단하는 이유(실측): Streamlit 은 어떤 실행에서
    렌더되지 않은 위젯의 상태를 정리한다. 다른 화면에 갔다 오면 이 화면의 조건 위젯 값이
    모두 사라지므로(연·월도 today 로 되돌아온다), 플래그로 1회만 심으면 재진입 때 부서·조만
    '(전체)'로 남아 기본값 계약이 깨진다. 값이 없을 때 심으면 첫 진입·재진입 모두 내
    부서·조로 열리고, 머무는 동안의 선택은 그대로다.
    """
    d_key, t_key = f"{page_id}_d", f"{page_id}_t"
    if d_key in st.session_state and t_key in st.session_state:
        return
    emp = _clean(user.get("emp_no"))
    assigns = db.get_month_assignments(int(year), int(month), emp) if emp else None
    seed_dept, seed_team = scope_defaults(user, dept_names, assigns)
    if seed_dept and d_key not in st.session_state:
        st.session_state[d_key] = seed_dept
    if seed_team and t_key not in st.session_state:
        st.session_state[t_key] = seed_team


def viewport_state(page_id: str) -> dict:
    """이 세션에서 마지막으로 확인된 뷰포트({w,h,landscape,compact}) — 없으면 빈 dict.

    값은 :func:`mount_viewport_probe` 가 갱신한다. 화면 상단에서는 **읽기만** 한다.
    """
    return st.session_state.get(f"{page_id}_viewport") or {}


def mount_viewport_probe(page_id: str) -> None:
    """뷰포트 프로브를 화면 **본문 마지막**에 붙이고, 값이 바뀌었으면 다시 그린다.

    본문 끝에 두는 이유: 컴포넌트 트리거는 진행 중인 스크립트 실행을 중단시키고 리런을
    건다. 조건 위젯보다 **앞**에서 마운트하면 첫 진입 리런이 조건 위젯 생성 전에 실행을
    끊어, 그 실행에서 심어 둔 조회조건 기본값(연·월·부서·조)이 위젯에 실리지 못하는
    경합이 생긴다(실측). 마지막에 두면 위젯이 모두 만들어진 뒤에만 리런이 걸린다.

    값이 바뀐 rerun 에서는 :func:`st.rerun` 으로 한 번 더 그린다 — 표시 열·표 높이는
    화면 위쪽(표)에서 이미 쓰였기 때문에, 새 값으로 다시 그려야 반영된다.
    """
    store = f"{page_id}_viewport"
    known = st.session_state.get(store) or {}
    with st.container(key="sv_vp"):
        result = _VIEWPORT_PROBE()(
            key=f"{page_id}_vp", data=known, on_viewport_change=lambda: None,
            width="content", height="content",
        )
    payload = result.get("viewport") if result is not None else None
    if not isinstance(payload, dict):
        return
    fresh = {
        "w": int(payload.get("w") or 0), "h": int(payload.get("h") or 0),
        "landscape": bool(payload.get("landscape")),
        "compact": bool(payload.get("compact")),
    }
    if fresh == known:
        return
    st.session_state[store] = fresh
    # 표시가 실제로 달라지는 변화일 때만 다시 그린다 — 넓은 폭에서는 방향·높이가 표에
    # 쓰이지 않으므로(데스크톱 규칙 그대로) 첫 값 수신에도 추가 리런을 만들지 않는다.
    def _layout(state: dict) -> tuple:
        compact = bool(state.get("compact"))
        if not compact:
            return (False,)
        return (True, bool(state.get("landscape")), int(state.get("h") or 0))

    if _layout(fresh) != _layout(known):
        st.rerun()


def month_grid_columns(meta_cols: list[str], day_cols: list[str], *, compact: bool) -> list[str]:
    """표에 **표시할** 열 — 좁은 폭이면 성명 + 일자만 남긴다(순수).

    데이터 프레임(``_build_month_grid`` 결과)과 CSV 다운로드 원본은 그대로이며 표시 열만
    줄인다. 남길 신원 열이 실제 프레임에 없으면(스키마 변화) 기존 신원 열을 유지한다.
    """
    if not compact:
        return list(meta_cols) + list(day_cols)
    kept = [c for c in meta_cols if c in _COMPACT_META_COLS]
    return (kept or list(meta_cols)) + list(day_cols)


def month_grid_height(nrows: int, *, compact: bool, landscape: bool, viewport_h: int) -> int:
    """표 높이 — 행 수만큼 늘되 화면(뷰포트) 밖으로 넘치지 않게 자른다(순수).

    데스크톱은 종전 규칙(행 34px + 여백, 240~500) 그대로다. 좁은 폭에서는 뷰포트 높이에서
    화면 크롬을 뺀 '남는 높이'로 한 번 더 자른다 — 폰 가로처럼 낮은 뷰포트에서 표가 화면
    밖으로 밀리지 않고, 표 안 스크롤로 날짜를 보게 된다.
    """
    natural = 34 * max(int(nrows), 1) + 52
    height = max(_GRID_MIN_PX, min(natural, _GRID_MAX_PX))
    if not compact:
        return height
    chrome = _COMPACT_CHROME_LANDSCAPE_PX if landscape else _COMPACT_CHROME_PORTRAIT_PX
    room = int(viewport_h) - chrome if viewport_h else 0
    if room <= 0:
        return max(_GRID_MIN_COMPACT_PX, min(natural, _GRID_MAX_PX))
    return max(_GRID_MIN_COMPACT_PX, min(natural, _GRID_MAX_PX, room))


# ---------- 근무표 등록/수정 · 전체 근무표 조회 (공통 본문) ----------
def schedule_screen(user: dict, page_id: str, band=None) -> None:
    # 상단 52px 헤더의 새로고침 아이콘(modules/ui.py::_PAGE_HEADER_ACTIONS) 의도를
    # **이 화면의 첫 조회 이전에** 소비한다 — 읽기 캐시(supabase 30s·sample 로더)를 비운
    # 뒤 이어지는 db.get_* 가 모두 신선한 값을 읽게 하기 위해서다. 아래 조회 세대값
    # (_rg_key)도 함께 올려 콜드 스켈레톤 표출 대상에 포함한다(구 [조회] 동작 보존).
    if st.session_state.pop(f"{page_id}_refresh_req", False):
        st.cache_data.clear()
        st.session_state[f"{page_id}_refreshgen"] = (
            st.session_state.get(f"{page_id}_refreshgen", 0) + 1
        )

    scheds = db.get_schedules()
    depts = db.get_departments()
    teams = db.get_teams()
    today = date.today()

    months = sorted({s[:7] for s in scheds["duty_date"]}) if not scheds.empty else []
    years = sorted({int(m[:4]) for m in months} | {today.year})

    dept_names = {r["dept_code"]: r["dept_name"] for _, r in depts.iterrows()}
    # 근태 등록 대상 부서(조직 관리 지정) — 이 화면의 조회 범위. 판단 근거는 위
    # '근태(근무표) 등록 대상 부서 범위' 절 주석 참조(이력 보존: is_active=None,
    # 판정 불가 코드 미차단, 지정 컬럼 미적용 배포는 전 부서).
    tracked_depts = (
        db.attendance_dept_codes(is_active=None) if db.attendance_flag_ready() else None
    )
    # 옵션·시드는 대상 부서만, 라벨(dept_names)은 전 부서 그대로 — 과거 기록의 부서명이
    # 컨텍스트 줄·MANAGER 판정에서 코드로 깨져 보이지 않게 한다(권한 계약 무변경).
    option_dept_names = attendance_dept_options(dept_names, tracked_depts)
    blocked_depts = attendance_blocked_depts(dept_names, tracked_depts)
    manager_locked = user["role"] == "MANAGER" and user.get("dept_code")

    st.markdown(_SV_CSS, unsafe_allow_html=True)
    # 영역 순서(§1-C 읽기): 조건 줄(condition_panel) → 헤어라인 → 컨텍스트 라인 → 표 → 범례.
    # 조건 위젯 변경이 곧 조회다(2026-08-13 사용자 요구 — [조회] 버튼 제거). 같은 조건의
    # 재조회(원본 데이터 재적재)는 상단 헤더 새로고침 아이콘이 담당한다(위 세대값).
    _rg_key = f"{page_id}_refreshgen"

    # condition_panel 의 select Field 는 index/value 인자를 받지 않고 항상 위젯 key 의
    # 세션 상태에 의존한다 — 최초 렌더(키 미존재)에서 기존 selectbox(index=...) 와 같은
    # 기본값(연도=올해·월=이번달)을 내려면 위젯 인스턴스화 전에 세션 상태를 선점해야 한다.
    y_key, m_key, d_key = f"{page_id}_y", f"{page_id}_m", f"{page_id}_d"
    if y_key not in st.session_state:
        st.session_state[y_key] = today.year
    if m_key not in st.session_state:
        st.session_state[m_key] = today.month

    # 화면 폭/방향 — 표시 열·표 높이를 정하는 값(아래 _render_body). 프로브 마운트는
    # 본문 마지막(mount_viewport_probe)이고 여기서는 세션에 남은 값을 읽기만 한다.
    vp = viewport_state(page_id)
    compact = bool(vp.get("compact"))
    landscape = bool(vp.get("landscape"))

    # 조회조건 기본값(2026-08-13 사용자 요구) — 선택값이 없을 때 내 부서·조를 심는다.
    # 사용자가 바꾼 선택은 덮어쓰지 않는다(위젯 상태 계약). MANAGER 는 아래에서 본인
    # 부서로 잠기고 fail-closed 재적용도 그대로라 이 시드가 권한범위를 넓히지 않는다.
    # 시드 원천은 **부서 조회 옵션과 같은 집합**이다 — 내 부서가 근태 비대상이면 시드하지
    # 않고 '(전체)'로 열린다(옵션 밖 값이 조건에 실려 빈 화면이 되는 경로 차단).
    _seed_scope_defaults(user, page_id, option_dept_names,
                         int(st.session_state[y_key]), int(st.session_state[m_key]))

    # 부서→조 종속 옵션: 조 Field 를 만들기 전에 "현재" 부서 선택을 세션 상태에서
    # 읽는다(near_miss_view 의 period_on 선-조회 패턴과 동일 — 위젯 렌더 순서가 아니라
    # 세션 상태로 종속을 해석해, 사용자가 부서를 바꾼 그 rerun 에서 조 옵션이 갱신되게 한다).
    if manager_locked:
        cur_dept = user["dept_code"]
        # 이전 사용자(예: ADMIN)가 남긴 부서 위젯 값이 MANAGER 옵션(본인 부서 1개) 밖이면
        # 위젯 생성 전에 비운다 — 조건이 곧 조회가 된 뒤로는 잔존 위젯 값이 그대로 조회
        # 조건이 되기 때문이다(데이터 경계는 아래 fail-closed 재적용이 별도로 강제한다).
        if st.session_state.get(d_key) not in (None, cur_dept):
            st.session_state.pop(d_key, None)
        dept_field = erp.Field(
            key="d", label="부서", kind="select",
            options=[user["dept_code"]], disabled=True, width=220,
            format_func=lambda c: dept_names.get(c, c),
        )
    else:
        # 삭제·비활성으로 사라진 부서 **또는 근태 대상에서 해제된 부서**가 위젯에 남아
        # 있으면 '(전체)'로 되돌린다(조 필터와 동일 규칙 — 없어진 조건이 남아 결과가
        # 0건이 되는 혼선 방지). 시드가 심은 값도 이 게이트를 함께 통과한다.
        if st.session_state.get(d_key) not in ([None, ALL] + list(option_dept_names)):
            st.session_state.pop(d_key, None)
        cur_dept = st.session_state.get(d_key, ALL)
        dept_field = erp.Field(
            key="d", label="부서", kind="select",
            options=[ALL] + list(option_dept_names), width=220,
            # '(전체)' 센티널은 라벨을 명시한다(근무표 편성 화면과 동일 표기) — 원값
            # 그대로 노출하면 코드 같은 괄호 문자열이 부서명 자리에 섞여 읽힌다.
            format_func=lambda c: "전체 부서" if c == ALL else dept_names.get(c, c),
        )
    # 조 옵션은 '대상 월의 실제 조 축'에서 만든다 — 조 축이 shift_group_code 로 옮겨간 뒤
    # teams 마스터만 보면 실DB(teams 0행)에서 옵션이 '(전체)'뿐이 되고, 부서=(전체) 에서는
    # 종전 코드가 옵션을 통째로 비웠다. 연/월 위젯 값은 세션 키에서 선-조회한다(부서와 동일
    # 패턴) — 위젯 렌더 순서와 무관하게 같은 rerun 에서 옵션이 갱신된다.
    # 조 옵션도 같은 범위로 좁힌다 — 근태 비대상 부서에만 있는 조가 목록에 남으면 고를
    # 수는 있는데 결과는 0건이 되어, 조건 줄이 적용되지 않은 조건을 단언하게 된다.
    team_names = _team_filter_options(
        int(st.session_state.get(y_key, today.year)),
        int(st.session_state.get(m_key, today.month)),
        cur_dept, teams, blocked_depts,
    )
    # 옵션 집합이 바뀌어 이전 선택이 사라졌으면 '(전체)'로 되돌린다(위젯 생성 전이라
    # 세션 키 수정이 허용된다). 없어진 조가 조건에 남아 결과가 0건이 되는 혼선을 막는다.
    t_key = f"{page_id}_t"
    if st.session_state.get(t_key) not in ([ALL] + list(team_names)):
        st.session_state.pop(t_key, None)

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
                  options=[ALL] + list(team_names),
                  format_func=lambda c: "전체 조" if c == ALL else team_names.get(c, c)),
        erp.Field(key="kw", label="사번 또는 성명", kind="text"),
    ]
    # 조건 줄(§1-E). U4: content_fit=True 로 짧은 select 는 내용 맞춤 폭·검색만 신축.
    # [조회] 버튼은 두지 않는다(2026-08-13 사용자 요구) — 위젯 변경이 rerun 을 일으키고
    # 그 값이 곧 조회 조건이라, 조회는 별도 확인 클릭 없이 즉시 반영된다(읽기 전용 조회라
    # 자동 조회가 계약 위반이 아니다). 같은 조건의 재적재는 헤더 새로고침 아이콘 담당.
    v = erp.condition_panel(page_id, fields, content_fit=True)
    refresh_gen = st.session_state.get(_rg_key, 0)

    q = {
        "year": v["y"],
        "month": v["m"],
        "dept": v["d"],
        "team": v["t"],
        "keyword": str(v["kw"] or "").strip(),
        # 근태 비대상 부서(마스터에 있고 지정되지 않은 부서)는 표 행에서도 제외한다.
        # 빈 튜플이면 종전과 완전히 동일한 조회다(폴백·전 부서 지정 포함).
        "excluded_depts": blocked_depts,
    }

    # MANAGER 권한범위 fail-closed 재적용: 위젯에서 온 조회조건(잔존 세션 값·타 부서·
    # ALL 일 수 있음)에도 항상 본인 부서로 축소한다. 위젯 잠금만 믿지 않는다(잠금은 UX,
    # 실제 데이터 경계는 여기서 강제).
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
            ui.empty_state(month_empty_message(q, tracked_depts), head="월별 근무표")
            return

        # §1-C 컨텍스트 라인 — YYYY-MM · 부서 · 조 · 인원·근무·실근무·휴무(모노 수치).
        # 화면 버튼은 상단(조건 줄·컨텍스트 줄)에 모은다: 조회는 조건 줄 우측 [조회],
        # 내보내기는 이 컨텍스트 줄 우측 [엑셀 다운로드]. 표 아래 전폭 버튼은 두지 않는다
        # (CSV 스키마·파일명·데이터는 불변 — 위치와 폭만 바뀐다).
        wt = _work_types_map_from_df(wt_df)
        n_work = sum(1 for c in month_rows["work_type_code"] if wt.get(c, {}).get("is_work"))
        # 컨텍스트 줄 + [엑셀 다운로드] 한 줄 배치. 종전 st.columns([1,0.22]) 는 버튼 폭이
        # 화면 폭에 비례해 줄어들어 좁은 폭에서 라벨이 2줄로 접히고(실측 ≤880px 에서 버튼
        # 48px 2줄) 컨텍스트 줄과 세로로 엉켰다. 버튼은 내용 맞춤(content) 으로 고정하고
        # 컨텍스트 줄만 신축시켜, 좁아지면 컨텍스트가 먼저 wrap 되고 버튼은 온전히 남는다
        # (§0.6 컨트롤 폭 내용 맞춤 — condition_panel content_fit 과 같은 패턴).
        with st.container(key="sv_ctxrow", horizontal=True, gap="small",
                          vertical_alignment="center"):
            st.markdown(
                _view_context_html(q, dept_names, team_names,
                                   len(grid), len(month_rows), n_work,
                                   tracked_depts),
                unsafe_allow_html=True,
            )
            with st.container(key="sv_ctxdl", width="content"):
                st.download_button(
                    "엑셀 다운로드",
                    grid.to_csv(index=False).encode("utf-8-sig"),
                    file_name=f"근무표_{q['year']}-{q['month']:02d}.csv",
                    mime="text/csv",
                    key=f"{page_id}_dl",
                    icon=":material/download:",
                    width="content",
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
        # 폭 지정(pixel QA 실측 기준): 키트 기본값(미지정 컬럼 flex=1,minWidth=90)을 그대로
        # 두면 신원 열은 좁아 잘리고 **일자 열은 한 글자(주·야·OFF)에 90px** 이 배정돼 표가
        # 지나치게 벌어진다. 신원 5열은 sticky left(pinned)로 고정 폭을, 일자 열은 §1-C 밀도
        # (셀 min-width 34px)에 맞춘 좁은 폭을 준다. read_grid col_config 는 colDef 로 그대로
        # 전달되므로 pinned·cellStyle 도 jscode 없이 지원된다.
        # 폭은 실렌더 측정(scrollWidth>clientWidth = 잘림)으로 잡았다: 성명은 퇴직 접미사
        # 포함, 중분류는 분류 미입력 시의 부서명 폴백(가장 긴 값)까지 수용한다.
        meta_col_config = {
            "사번": {"width": 84, "minWidth": 84, "pinned": "left"},
            "성명": {"width": 100, "minWidth": 100, "pinned": "left"},
            "대분류": {"width": 104, "minWidth": 104, "pinned": "left"},
            "중분류": {"width": 140, "minWidth": 140, "pinned": "left"},
            "조": {"width": 60, "minWidth": 60, "pinned": "left"},
        }
        # 일자 열: 고정 폭이 아니라 flex + 상·하한 — 좁은 화면에서는 하한(밀도)을 지키고,
        # 넓은 화면에서는 남는 폭을 균등 배분하되 상한을 넘겨 벌어지지 않게 한다.
        # 헤더는 2줄(숫자/요일)로 접어 좁은 폭에서도 잘리지 않게 한다(§1-C 편성표의 2줄
        # 일자 헤더와 같은 표현). **표시 라벨만** 바꾸므로 field(=CSV 열 이름 "1(수)")는
        # 그대로다 — 엑셀 다운로드 스키마 불변.
        day_col_config = {
            c: {"flex": 1, "minWidth": _DAY_COL_MIN_PX, "maxWidth": _DAY_COL_MAX_PX,
                "headerName": c.replace("(", " ").replace(")", ""),
                "wrapHeaderText": True, "autoHeaderHeight": True,
                "cellStyle": {"paddingLeft": "2px", "paddingRight": "2px",
                              "justifyContent": "center"}}
            for c in day_cols
        }
        # 표시 열 — 좁은 폭(모바일)은 성명 + 일자만(2026-08-13 사용자 요구). 프레임과 CSV
        # 원본은 그대로이고 **표시만** 줄인다(신원 5열 합계 488px 이 폰 폭 390px 을 넘어
        # 날짜가 화면 밖으로 밀리는 문제). 좁은 폭에서는 성명 열 폭도 한 단계 줄인다.
        shown_meta = month_grid_columns(meta_cols, [], compact=compact)
        if compact:
            meta_col_config = {**meta_col_config, "성명": {"width": 84, "minWidth": 84,
                                                          "pinned": "left"}}
            # 모바일 세로: 한 화면에 담기는 날짜가 적으므로 가로 전환을 한 줄로 안내한다
            # (표 위, 보조 텍스트 1줄 — 장식·아이콘 없음).
            if not landscape:
                st.markdown(
                    "<div class='sv-rotate'>가로로 돌리면 한 번에 더 많은 날짜를 볼 수 있습니다</div>",
                    unsafe_allow_html=True,
                )
        # §1-C 표: 흰 컨테이너(1px #cfc8bd·radius 8·내부 스크롤) — 편성표와 동일 시각. 컨테이너
        # 스타일은 iframe 바깥 래퍼(_SV_CSS 의 .st-key-sv_gridwrap)가 소유한다.
        # skeleton=False: 콜드 로드 표출은 상위 grid_shell(prepare) 가 담당(이중 shell 방지).
        with st.container(key="sv_gridwrap"):
            erp.read_grid(
                grid_ui, columns=shown_meta + day_cols, key=f"{page_id}_grid",
                color_rules=color_rules,
                col_config={**{c: meta_col_config[c] for c in shown_meta
                               if c in meta_col_config}, **day_col_config},
                row_rules=[{
                    "when": "data['_retired'] === true",
                    "columns": shown_meta, "bg": retired_bg, "ink": retired_ink,
                }],
                hidden_fields=["_retired"],
                # 키트 기본 높이 상한(460)보다 한 화면에 더 담되 §1-C 상한은 지킨다 —
                # 행 피치(34px)는 키트 읽기 밀도 토큰이 소유한다(화면에서 바꾸지 않는다).
                # 좁은 폭에서는 뷰포트 높이에도 맞춘다(폰 가로에서 표가 화면을 최대로 사용).
                height=month_grid_height(len(grid_ui), compact=compact, landscape=landscape,
                                         viewport_h=int(vp.get("h") or 0)),
                skeleton=False,
            )
        st.markdown(_label_legend_html(display_of, color_of), unsafe_allow_html=True)

        # 사용자별 집계 (전체 근무표 조회) — 좁은 폭에서는 두지 않는다: 사용자 요구가
        # "모바일은 이름·근무표만" 이고, 폰에서 두 번째 그리드(별도 iframe)는 표 아래
        # 화면을 통째로 차지한다. 데이터·집계 로직은 그대로이며 넓은 폭에서는 종전과 같다.
        if page_id == "schedule_view" and not month_rows.empty and not compact:
            st.write("")
            ui.panel_head("직원별 근무형태 집계")
            agg = _build_agg(grid, month_rows, wt, display_of)
            erp.read_grid(agg, key=f"{page_id}_agg", skeleton=False)

    _ndays = calendar.monthrange(int(q["year"]), int(q["month"]))[1]
    # fingerprint = 조회조건 q + 새로고침 세대값. q 가 같으면(같은 데이터) 재전환하지 않아
    # warm/미변경 rerun 에 스켈레톤이 뜨지 않고(무점멸), q 변경/새로고침에만 콜드 표출된다.
    # 폭 구간·방향도 지문에 넣는다 — 표시 열/표 높이가 바뀌는 전환이라 스켈레톤으로
    # 덮어야 낡은 형상(신원 5열)이 잠깐 남지 않는다. 높이 값 자체는 넣지 않는다
    # (주소창 접힘 같은 잔변화로 스켈레톤이 깜빡이지 않게).
    _fp = (tuple(sorted((str(k), str(v)) for k, v in q.items())), refresh_gen,
           compact, landscape)
    erp.grid_shell(
        f"{page_id}_screen",
        nrows=7, ncols=min(_ndays + 4, 8),
        fingerprint=_fp, height=360,
        prepare=_cold_load, render=_render_body,
    )
    # 화면 폭/방향 프로브는 본문의 **맨 끝**에 둔다(위 mount_viewport_probe 주석 참조).
    mount_viewport_probe(page_id)


def team_filter_options(assigns: pd.DataFrame | None, teams: pd.DataFrame | None,
                        dept: str, blocked_depts=None) -> dict:
    """조 필터 옵션 {값: 표시라벨} — 대상 월 편성 스냅샷의 조 축을 우선 원천으로 만든다(순수).

    조 축이 ``teams``(운영단위 마스터)에서 ``schedule_assignments.shift_group_code``
    (근무표 편성 직접입력)로 옮겨간 뒤, teams 마스터만 보는 옵션 소스는 실DB(teams 0행)
    에서 '(전체)' 하나만 남고 부서=(전체) 에서는 아예 비어 조 필터가 무력화됐다. 그래서
    옵션을 다음 3원천의 합집합으로 만든다 — 필터 매칭 로직(_eff_team/_eff_shift 양축)은
    그대로 두고 **옵션 소스만** 바꾼다:

      1. 스냅샷 근무조(``shift_group_code``) — 신 축. 값이 곧 표시 라벨이다.
      2. 스냅샷 운영단위(``team_code``) — 레거시 축(과거 월 편성). 라벨은 teams 마스터의
         조명, 없으면 코드 그대로.
      3. teams 마스터의 조 — 편성이 아직 없는 월에도 기존 조로 좁혀볼 수 있게 유지한다
         (부서=(전체) 면 전 부서의 조. 종전 코드는 이 경우 옵션을 통째로 비웠다).

    ``dept`` 가 ``ALL`` 이 아니면 스냅샷은 그 부서 편성 행만, teams 는 그 부서 조만 본다.
    반환 순서는 정렬 고정(표시 흔들림 방지)이며, 값은 매칭 축과 같은 원본 문자열이다.

    ``blocked_depts`` (근태 비대상 부서코드)에 속한 부서의 조는 옵션에서 제외한다 —
    표 행 필터(:func:`_build_month_grid` 의 ``excluded_depts``)와 **같은 집합**이라
    "고를 수는 있는데 결과가 0건"인 조가 목록에 남지 않는다. 라벨 맵(teams 마스터)은
    차단 여부와 무관하게 채워, 과거 편성의 조 이름 표시는 그대로 유지한다.
    """
    options: dict[str, str] = {}
    labels: dict[str, str] = {}
    blocked = set(blocked_depts or ())
    if teams is not None and not teams.empty:
        for _, t in teams.iterrows():
            code = _clean(t.get("team_code"))
            if not code:
                continue
            labels.setdefault(code, _clean(t.get("team_name")) or code)
            if _clean(t.get("dept_code")) in blocked:
                continue
            if dept == ALL or _clean(t.get("dept_code")) == dept:
                options[code] = labels[code]
    if assigns is not None and not assigns.empty:
        for _, a in assigns.iterrows():
            if _clean(a.get("dept_code")) in blocked:
                continue
            if dept != ALL and _clean(a.get("dept_code")) != dept:
                continue
            shift = _clean(a.get("shift_group_code"))
            if shift:
                options.setdefault(shift, shift)
            team = _clean(a.get("team_code"))
            if team:
                options.setdefault(team, labels.get(team, team))
    return {code: options[code] for code in sorted(options)}


def _team_filter_options(year: int, month: int, dept: str, teams: pd.DataFrame,
                         blocked_depts=None) -> dict:
    """:func:`team_filter_options` 의 조회 래퍼 — 대상 월 편성 스냅샷을 읽어 넘긴다.

    ``db.get_month_assignments`` 는 supabase 모드에서 30초 캐시(``modules/db``)라 같은
    렌더 안의 재조회는 네트워크를 다시 치지 않는다. 조회 실패(네트워크·권한)는 여기서
    삼키지 않고 그대로 올린다 — 옵션이 조용히 빈 상태로 위장되면 사용자가 '조 없음'을
    데이터 사실로 오독한다(모듈 계약: 오류를 sample/빈 결과로 숨기지 않는다).
    """
    return team_filter_options(
        db.get_month_assignments(int(year), int(month)), teams, dept, blocked_depts
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


def org_labels(depts: pd.DataFrame | None = None) -> tuple[dict, list]:
    """부서코드 → (대분류, 중분류) 표시 라벨 맵과 대분류 노출 순서를 만든다(순수).

    계층 용어는 대시보드와 같다 — 조직 관리에서 사람이 입력하는 ``major_category``
    (대분류) · ``minor_category``(중분류, migration 009)가 그대로 화면 계층이다.

    - 대분류가 비었거나 마스터에 없는 부서코드는 :data:`UNCLASSIFIED_LABEL` 로 접고
      순서상 **마지막**이다(행을 감추지 않는다 — 근무 기록을 조용히 버리지 않는다).
    - 중분류가 비면 부서명(없으면 부서코드)을 폴백 라벨로 쓴다(dashboard 와 동일 규칙).
    - 대분류 순서는 **데이터에서 유도**한다: 부서 마스터의 ``sort_order``(같으면 조회
      순서)가 앞선 부서가 속한 대분류가 먼저다. 특정 대분류 이름을 코드에 고정하지
      않으므로 조직 관리에서 순서를 바꾸면 화면 순서도 따라간다.

    ``depts`` 는 테스트 주입용이며, 미지정이면 ``db.get_org_departments()`` 를 1회 조회한다.
    """
    frame = db.get_org_departments() if depts is None else depts
    labels: dict = {}
    majors: list = []
    if frame is None or frame.empty:
        return labels, majors
    rows = []
    for seq, (_, r) in enumerate(frame.iterrows()):
        code = _clean(r.get("dept_code"))
        if not code:
            continue
        order = pd.to_numeric(r.get("sort_order"), errors="coerce")
        rows.append((
            0 if pd.isna(order) else int(order), seq, code,
            _clean(r.get("major_category")),
            _clean(r.get("minor_category")),
            _clean(r.get("dept_name")),
        ))
    for _order, _seq, code, major, minor, name in sorted(rows):
        if code not in labels:  # 같은 코드가 여러 행이면 첫 매치 우선(db.dept_name 과 동일)
            labels[code] = (major or UNCLASSIFIED_LABEL, minor or name or code)
        if major and major not in majors:
            majors.append(major)
    return labels, majors


def _org_label_of(code, labels: dict) -> tuple[str, str]:
    """부서코드 한 개의 (대분류, 중분류) — 마스터에 없으면 무분류 + 코드 그대로."""
    key = _clean(code)
    if key in labels:
        return labels[key]
    return UNCLASSIFIED_LABEL, key


def _team_sort_key(value) -> tuple:
    """조 정렬 키 — A조 → B조 → C조 … → 그 밖(기타 표기) → 빈 조(마지막).

    사용자 확정 순서(정렬기준 ②)를 조 이름 목록으로 하드코딩하지 않고 값에서 유도한다:
    영문 머리글자(A/B/C…)를 알파벳 순으로 먼저, 그 밖의 표기(1팀·상시 등)를 그 다음,
    조가 비어 있는 행을 마지막에 둔다. 조 축은 부서 독립 자유 텍스트라(편성 직접입력)
    기준정보 정렬순서를 쓸 수 없다.
    """
    text = _clean(value)
    if not text:
        return (2, "")
    head = text[:1].upper()
    if "A" <= head <= "Z":
        return (0, text.upper())
    return (1, text)


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

    ``q["excluded_depts"]`` (근태 비대상 부서코드, 선택)이 있으면 그 부서 소속으로 판정된
    행을 먼저 제외한다 — 조직 관리에서 지정한 근태 등록 대상 부서만 조회하기 위함이다
    (기본값 없음 = 종전과 동일한 전 부서 조회).

    부서·조는 대상 월의 편성 스냅샷(schedule_assignments)을 우선 사용하고, 없으면
    현재 사용자 소속으로 폴백한다(표시 전용·자동저장/백필 없음 — requirements.md §5).
    조회 조건의 부서·조 필터도 같은 스냅샷 기준으로 일관 적용해, 과거 월 조회 시
    인사이동한 직원이 현재 소속으로 오분류되지 않게 한다. 날짜 셀은 내부 코드가 아니라
    근무형태 약칭(display_of)으로 표시한다.

    소속 표시 열은 **대분류·중분류**다(2026-08-13 사용자 요구) — 스냅샷의 부서코드를
    부서 마스터의 조직 계층으로 해석하고(:func:`org_labels`), 분류가 없거나 마스터에
    없는 코드는 무분류로 접어 마지막에 둔다. 필터·스냅샷 계약(부서코드 기준)은 그대로다.
    행 정렬은 대분류 → 조 → 등록순(display_order) → 사번 순이다.

    해당 월에 저장된 근무 기록이 있는 직원만 행으로 포함한다(2026-08-11 사용자 결정
    — 근무가 없는 사람은 재직 여부와 무관하게 월간 근무표에서 제외, 빈 행을 만들지
    않는다). 포함된 퇴직·퇴사자는 성명에 RETIRED_LABEL 을 덧붙여 표시한다(§7 소프트
    삭제=참조 보존 — 과거 기록 조회 유지).

    퇴사자를 get_users(include_resigned=False)로 아예 빼면 과거 월의 저장된 근무까지
    조회에서 사라진다(2026-08-07 code-review P1) — 그래서 여기서는 전체를 조회한 뒤
    퇴사자를 '비활성과 같은 부류'(기록 있는 월에만 표시)로 접는다.
    """
    display_of = display_of or {}
    users = db.get_users()

    resigned_mask = users["resign_date"].map(db.is_resigned) if "resign_date" in users.columns \
        else pd.Series(False, index=users.index)
    active_mask = users["is_active"].astype(bool) & ~resigned_mask
    all_emp_nos = users["emp_no"].astype(str).str.strip()
    scheds_all = db.get_month_schedules(all_emp_nos, q["year"], q["month"])
    emp_with_records = (
        set(scheds_all["emp_no"].astype(str).str.strip()) if not scheds_all.empty else set()
    )

    users["_eff_active"] = active_mask  # 재직 = is_active AND 퇴사일 미경과
    # 근무 기록 보유가 포함 조건(재직·퇴직 공통) — 2026-08-11 사용자 결정.
    keep_mask = all_emp_nos.isin(emp_with_records)
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

    # 근태 등록 대상 부서 범위(조직 관리 지정) — 부서 조건보다 **먼저** 적용한다.
    # 차단 목록 방식이라 마스터에 없는 부서코드·부서 미배정 행은 감추지 않는다(판정
    # 불가는 이력 보존 쪽으로 — 위 '근태(근무표) 등록 대상 부서 범위' 절 참조).
    # 스냅샷 기준(_eff_dept)이라 과거 월은 그 당시 부서로 판정된다.
    blocked_depts = set(q.get("excluded_depts") or ())
    if blocked_depts:
        users = users[~users["_eff_dept"].isin(blocked_depts)]

    if q["dept"] != ALL:
        users = users[users["_eff_dept"] == q["dept"]]
    if q["team"] != ALL:
        # 조 필터는 신 축(근무조 직접입력)과 레거시 축(운영단위) 어느 쪽이든 매치한다
        # — 과거 월(team_code 편성)과 새 편성(shift_group_code)이 한 화면에 공존한다.
        # 부서 분기 **밖**이다(code-review P1): 조 축은 부서 독립 자유 텍스트라
        # 부서=(전체)에서도 적용돼야 하며, 안 그러면 옵션은 뜨는데 필터가 무력화되어
        # 컨텍스트 줄·CSV 가 적용되지 않은 조건을 단언하게 된다.
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
    # 표시 라벨(대분류·중분류·조)을 정렬 **전에** 확정한다 — 정렬 기준과 화면에 보이는
    # 값이 어긋나지 않게 하기 위해서다(조는 신 축 shift_group_code 우선, 없으면 레거시
    # 운영단위명). 조/부서 이름 맵은 렌더 1회만 만들어 행마다 재조회하지 않는다.
    labels, majors = org_labels()
    major_rank = {name: i for i, name in enumerate(majors)}
    team_name_by_key: dict = {}
    for _, t in db.get_teams().iterrows():
        key = (t["dept_code"], t["team_code"])
        if key not in team_name_by_key:
            team_name_by_key[key] = t["team_name"]

    majors_col, minors_col, teams_col = [], [], []
    for _, u in users.iterrows():
        major, minor = _org_label_of(u["_eff_dept"], labels)
        majors_col.append(major)
        minors_col.append(minor)
        shift_code = _clean(u.get("_eff_shift"))
        team_code = _clean(u.get("_eff_team"))
        teams_col.append(shift_code or (
            team_name_by_key.get((u["_eff_dept"], team_code), team_code) if team_code else ""
        ))
    users["_major"] = majors_col
    users["_minor"] = minors_col
    users["_team_label"] = teams_col

    # 정렬(2026-08-13 사용자 확정): ① 대분류(데이터 유도 순서·무분류 마지막)
    # → ② 조(A→B→C→기타→빈 조) → ③ 등록순(display_order, 없으면 뒤) → 사번.
    users["_m_rank"] = [major_rank.get(m, len(major_rank)) for m in majors_col]
    _t_keys = [_team_sort_key(v) for v in teams_col]
    users["_t_rank"] = [k[0] for k in _t_keys]
    users["_t_key"] = [k[1] for k in _t_keys]
    _orders = []
    for value in users.get("display_order", pd.Series([None] * len(users))):
        try:
            _orders.append(db.normalize_display_order(value))
        except (TypeError, ValueError):
            _orders.append(None)
    users["_d_null"] = [1 if o is None else 0 for o in _orders]
    users["_d_order"] = [0 if o is None else o for o in _orders]
    users = users.sort_values(
        ["_m_rank", "_t_rank", "_t_key", "_d_null", "_d_order", "emp_no"]
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

    rows = []
    for _, u in users.iterrows():
        name = u["name"]
        if bool(u.get("_retired")):
            name = f"{name}{RETIRED_LABEL}"
        # 소속 표시는 조직 관리 계층(대분류·중분류)이다 — 스냅샷의 부서코드를 부서
        # 마스터의 분류로 해석하며(위 org_labels), 분류가 없으면 무분류/부서명 폴백.
        row = {
            "사번": u["emp_no"],
            "성명": name,
            "대분류": u["_major"],
            "중분류": u["_minor"],
            "조": u["_team_label"],
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
                       n_people: int, n_rows: int, n_work: int,
                       tracked: set | None = None) -> str:
    """§1-C 컨텍스트 라인 — YYYY-MM · 부서 · 조 · 인원·근무·실근무·휴무(모노 수치).

    ``tracked`` 가 있으면(근태 대상 지정이 살아 있는 배포) '(전체)' 선택의 표기를
    '근태 대상 부서'로 쓴다 — 대상 부서만 담은 화면에 '전체 부서'라고 쓰면 컨텍스트 줄이
    사실과 다른 말을 한다(dashboard._scope_label 의 '근태 대상' 스탬프와 같은 규율).
    폴백(지정 판독 불가)에서는 종전대로 '전체 부서'다.
    """
    ym = f"{int(q['year'])}-{int(q['month']):02d}"
    all_label = "근태 대상 부서" if tracked is not None else "전체 부서"
    dept = all_label if q.get("dept") == ALL else (dept_names.get(q.get("dept"), q.get("dept")) or all_label)
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
