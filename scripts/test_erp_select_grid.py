"""SELECT 어댑터(views/common/erp/kit.select_grid) 단위 계약 — 07-28 2차 검수 GO-WITH-FIX.

선택 계약을 액션 문자열이 아니라 **구조**로 고정한다(AgGrid 마운트 없이 순수 헬퍼만 검사):
  1) col_config 화이트리스트 — 편집 자산(editable/cellRenderer 등) 주입 시 ValueError.
  2) key_field 자연키 — 존재·비어있지않음·행간유일·표시열 미포함(항상 hidden), 위반 시 ValueError.
  3) 편집 자산 부재·비-editable·checkboxSelection 이중부호화·allow_unsafe_jscode=False.
  4) 밀도(row_height 34/44) → rowHeight·그리드 높이 반영.
  5) 자연키 반환(_selected_key)·pre-select(selected_key→initialState, 사라지면 해제).
  6) 상세 순수 표시 primitive(status_badge_html/meta_col_html/field_block) escape·도메인무지.

실행: PYTHONUTF8=1 C:\\dev\\duty-scheduler\\.venv\\Scripts\\python.exe scripts/test_erp_select_grid.py
"""
from __future__ import annotations

import inspect
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["DUTY_DATA_MODE"] = "sample"

import pandas as pd  # noqa: E402

from views.common.erp import kit  # noqa: E402

PASS = 0
FAIL: list[str] = []


def check(name: str, cond: bool) -> None:
    global PASS
    if cond:
        PASS += 1
        print(f"  ok - {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL - {name}")


def raises(fn, exc=ValueError) -> bool:
    try:
        fn()
    except exc:
        return True
    except Exception:  # 다른 예외는 계약 위반이 아니라 오류 — 실패로 본다.
        return False
    return False


def sample_df() -> pd.DataFrame:
    return pd.DataFrame({
        "_k": ["r1", "r2", "r3"],
        "작업명": ["A", "B", "C"],
        "상태": ["제출됨", "검토중", "제출됨"],
    })


def build(df, **kw):
    return kit._build_select_gridoptions(
        df,
        key_field=kw.get("key_field", "_k"),
        columns=kw.get("columns"),
        selected_key=kw.get("selected_key"),
        color_rules=kw.get("color_rules"),
        col_config=kw.get("col_config"),
        row_rules=kw.get("row_rules"),
        hidden_fields=kw.get("hidden_fields"),
        row_height=kw.get("row_height", 34),
    )


EDIT_ASSETS = {
    "cellRenderer", "cellRendererParams", "cellEditor", "cellEditorParams",
    "valueSetter", "valueParser", "onCellValueChanged", "rowDrag", "editable_true",
}


# ===== 1) 해피패스 — 선택 계약 구조 =====
print("select_grid 기본 계약")
view, opts, custom = build(sample_df())
coldefs = opts["columnDefs"]
by_field = {c["field"]: c for c in coldefs}
check("rowSelection == 'single'", opts["rowSelection"] == "single")
check("행 클릭 선택 허용(suppressRowClickSelection False)", opts["suppressRowClickSelection"] is False)
check("선택 유지(suppressRowDeselection True)", opts["suppressRowDeselection"] is True)
check("rowHeight 기본 34(§0.6 읽기)", opts["rowHeight"] == 34)
check("headerHeight 36", opts["headerHeight"] == 36)
check("key_field 는 hidden 자연키", by_field["_k"].get("hide") is True)
check("key_field suppressColumnsToolPanel", by_field["_k"].get("suppressColumnsToolPanel") is True)
check("표시열은 전부 editable False", all(by_field[c].get("editable") is False for c in ("작업명", "상태")))
check("첫 표시열 checkboxSelection(마커 이중부호화)", by_field["작업명"].get("checkboxSelection") is True)
check("어떤 colDef 도 편집 렌더러/에디터 자산 없음",
      all(not (set(cd) & EDIT_ASSETS) for cd in coldefs))
check("editable=True 인 colDef 없음", all(cd.get("editable") is not True for cd in coldefs))
check("view 에 key_field 실려있음(hidden 반환용)", "_k" in view.columns)
check("초기 미선택 시 initialState 없음", "initialState" not in opts)
check("SELECT 배경 틴트 custom_css 병합(이중부호화)",
      any("ag-row-selected" in sel for sel in custom))


# ===== 2) 밀도 variant(row_height) =====
print("밀도 variant")
_, opts44, _ = build(sample_df(), row_height=44)
check("row_height=44 → rowHeight 44(USER·터치)", opts44["rowHeight"] == 44)
h34 = kit.read_grid_height(6, row_px=34)
h44 = kit.read_grid_height(6, row_px=44)
check("read_grid_height row_px 44 > 34(같은 행수)", h44 > h34)


# ===== 3) pre-select(자연키 위치 비의존) =====
print("pre-select")
_, opts_sel, _ = build(sample_df(), selected_key="r2")
check("selected_key='r2' → initialState rowSelection [1]",
      opts_sel.get("initialState") == {"rowSelection": [1]})
_, opts_gone, _ = build(sample_df(), selected_key="zzz")
check("결과에서 사라진 selected_key → initialState 없음(자동 미선택)",
      "initialState" not in opts_gone)


# ===== 4) col_config 화이트리스트(편집 자산 주입 차단) =====
print("col_config 화이트리스트")
try:
    build(sample_df(), col_config={"작업명": {"flex": 1.7, "minWidth": 128, "cellClass": "md-c-left"}})
    check("허용 표현 속성(flex/minWidth/cellClass) 통과", True)
except ValueError:
    check("허용 표현 속성(flex/minWidth/cellClass) 통과", False)
check("col_config editable=True 거부(ValueError)",
      raises(lambda: build(sample_df(), col_config={"작업명": {"editable": True}})))
check("col_config cellRenderer 거부",
      raises(lambda: build(sample_df(), col_config={"작업명": {"cellRenderer": "x"}})))
check("col_config cellEditor 거부",
      raises(lambda: build(sample_df(), col_config={"작업명": {"cellEditor": "x"}})))
check("col_config valueSetter(paste 계열) 거부",
      raises(lambda: build(sample_df(), col_config={"작업명": {"valueSetter": "x"}})))
check("col_config 비-dict 값 거부",
      raises(lambda: build(sample_df(), col_config={"작업명": "flex"})))


# ===== 5) key_field 자연키 검증 =====
print("key_field 자연키 검증")
check("미존재 컬럼 key_field 거부",
      raises(lambda: build(sample_df(), key_field="nope")))
_df_empty = sample_df()
_df_empty.loc[1, "_k"] = ""
check("빈 자연키 행 거부", raises(lambda: build(_df_empty)))
_df_ws = sample_df()
_df_ws.loc[1, "_k"] = "   "
check("공백뿐 자연키 행 거부(strip 후 빈값)", raises(lambda: build(_df_ws)))
_df_dup = sample_df()
_df_dup.loc[2, "_k"] = "r1"
check("행 간 중복 자연키 거부", raises(lambda: build(_df_dup)))
check("key_field 가 표시 columns 에 포함되면 거부(항상 hidden)",
      raises(lambda: build(sample_df(), columns=["_k", "작업명"])))
_empty = pd.DataFrame(columns=["_k", "작업명", "상태"])
_view_e, _opts_e, _ = build(_empty)
check("빈 df 는 자연키 값검증 공허 통과", "_k" in _view_e.columns)


# ===== 6) _selected_key 반환 추출 =====
print("_selected_key 추출")
check("선택행 자연키 반환",
      kit._selected_key(pd.DataFrame({"_k": ["r2"], "작업명": ["B"]}), "_k") == "r2")
check("None → None", kit._selected_key(None, "_k") is None)
check("빈 프레임 → None", kit._selected_key(pd.DataFrame(columns=["_k"]), "_k") is None)
check("공백 strip", kit._selected_key(pd.DataFrame({"_k": ["  r5  "]}), "_k") == "r5")
check("key_field 부재 프레임 → None", kit._selected_key(pd.DataFrame({"x": ["a"]}), "_k") is None)


# ===== 7) allow_unsafe_jscode·편집 자산 부재(소스 불변식) =====
print("unsafe jscode·편집 자산 부재")
sel_src = inspect.getsource(kit.select_grid)
check("select_grid allow_unsafe_jscode=False", "allow_unsafe_jscode=False" in sel_src)
check("select_grid 에 allow_unsafe_jscode=True 없음", "allow_unsafe_jscode=True" not in sel_src)
build_src = inspect.getsource(kit._build_select_gridoptions)
check("gridoptions 빌더에 JsCode 없음", "JsCode" not in build_src)
check("gridoptions 빌더에 editable=True 리터럴 없음",
      "'editable': True" not in build_src and '"editable": True' not in build_src)


# ===== 8) 상세 순수 표시 primitive(도메인 무지·escape) =====
print("상세 표시 primitive")
_badge = kit.status_badge_html("검토중", "#B4813F")
check("status_badge_html 라벨·색 포함", "검토중" in _badge and "#B4813F" in _badge)
check("status_badge_html HTML escape(주입 방어)", "&lt;b&gt;" in kit.status_badge_html("<b>", "#000000"))
badge_src = inspect.getsource(kit.status_badge_html)
check("status_badge_html 도메인 매핑 없음(status→색은 화면 소유)",
      "SUBMITTED" not in badge_src and "_STATUS" not in badge_src)
_meta = kit.meta_col_html([("신고자", "홍길동")])
check("meta_col_html 라벨/값 포함", "신고자" in _meta and "홍길동" in _meta)
check("meta_col_html 빈값 '-' 대체", "-" in kit.meta_col_html([("부서", "")]))
check("meta_col_html escape", "&lt;" in kit.meta_col_html([("x", "<i>")]))
fb_src = inspect.getsource(kit.field_block)
check("field_block escape 사용(순수 표시)", "escape(" in fb_src)
check("field_block 도메인/facade 호출 없음", "db." not in fb_src and "auth." not in fb_src)


print()
if FAIL:
    print(f"FAILED {len(FAIL)}: {FAIL}")
    sys.exit(1)
print(f"ALL PASSED ({PASS} checks)")
