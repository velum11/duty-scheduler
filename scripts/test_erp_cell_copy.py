"""셀 텍스트 선택·복사 계약 — 네 그리드 백엔드의 **최종 gridOptions** 로 고정한다.

사용자 요구(2026-08-07): "각 화면에서 복사가 안돼 … 모든 화면 복사되게".
AG Grid 는 기본값에서 셀에 ``user-select:none`` 을 걸고(Community 는 클립보드 모듈도
없음) 셀 값을 드래그 선택·복사할 수 없다. 표시 계층 옵션 2개
(:data:`views.master.grid.CELL_COPY_OPTIONS`)로 해결하며, 이 스위트는 그 옵션이
"소스에 문자열로 존재"하는 수준이 아니라 **각 빌더가 실제로 반환/전달하는 최종 옵션
딕셔너리**에 실리는지 검사한다. 동시에 기존 계약(범위 붙여넣기 handshake·행 선택·
편집 게이트·READ/SELECT 의 편집 자산 부재)이 그대로 남아 있는지 함께 고정한다.

대상 4곳:
  1. ``views/master/grid.py::_build_grid_options``        — 기준정보 편집 그리드(3화면)
  2. ``views/common/erp/kit.py::_build_read_gridoptions`` — READ 그리드(월간 근무표 등)
  3. ``views/common/erp/kit.py::_build_select_gridoptions``— SELECT 그리드(아차사고 조회 등)
  4. ``views/workspace.py::selectable_master_grid``       — 근무표 편성 그리드
     (모듈 지역 dict 라 AgGrid 호출을 가로채 실제 전달 옵션을 캡처한다)

실행: PYTHONUTF8=1 .venv/Scripts/python.exe scripts/test_erp_cell_copy.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["DUTY_DATA_MODE"] = "sample"

import pandas as pd  # noqa: E402

from views import workspace as ws  # noqa: E402
from views.common.erp import kit  # noqa: E402
from views.master import grid as mgrid  # noqa: E402

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


def copy_enabled(options: dict) -> bool:
    """최종 옵션에 셀 복사 2옵션이 True 로 실려 있는가."""
    return (options.get("enableCellTextSelection") is True
            and options.get("ensureDomOrder") is True)


# ===== 0) 단일 원천 =====
print("셀 복사 옵션 단일 원천(views/master/grid.py::CELL_COPY_OPTIONS)")
check("CELL_COPY_OPTIONS 는 2옵션 dict",
      mgrid.CELL_COPY_OPTIONS == {"enableCellTextSelection": True, "ensureDomOrder": True})
check("키트가 같은 상수를 재사용(리터럴 복제 아님)",
      kit.CELL_COPY_OPTIONS is mgrid.CELL_COPY_OPTIONS)
check("편성 그리드도 같은 상수를 재사용",
      ws.CELL_COPY_OPTIONS is mgrid.CELL_COPY_OPTIONS)


# ===== 1) 기준정보 편집 그리드 =====
print("편집 그리드(_build_grid_options) — 복사 허용 + 붙여넣기·행선택 계약 보존")
spec = mgrid.MasterGridSpec(
    page_id="unit_test",
    columns={"코드": "text", "사용": "bool"},
    order=["코드", "사용"],
)
edit_opts = mgrid._build_grid_options(spec)
check("편집 그리드 최종 옵션에 셀 복사 2옵션", copy_enabled(edit_opts))
# 기존 계약이 밀려나지 않았는가 — Excel 범위 붙여넣기 handshake(paste.apply_paste_options).
check("붙여넣기 handshake 유지(onGridReady)", "onGridReady" in edit_opts)
check("편집 확정 handshake 유지(stopEditingWhenCellsLoseFocus)",
      edit_opts.get("stopEditingWhenCellsLoseFocus") is True)
check("단일클릭 편집 금지 유지(붙여넣기 오입력 방지)",
      edit_opts.get("singleClickEdit") is False)
check("행 선택/제거 클릭 경로 유지(onCellClicked)", "onCellClicked" in edit_opts)
check("행 선택 키보드 경로 유지(onCellKeyDown)", "onCellKeyDown" in edit_opts)
check("행 클릭=선택 억제 유지(suppressRowClickSelection)",
      edit_opts.get("suppressRowClickSelection") is True)
_action = [c for c in edit_opts["columnDefs"] if c.get("field") == "_action"]
check("_action 열(선택 체크박스/− 제거) 유지", len(_action) == 1)
check("_action 열 Enter/Space 억제 유지", "suppressKeyboardEvent" in _action[0])

# 화면별 grid_options 오버라이드가 있어도 복사 옵션은 유지된다(근무형태 rowHeight 등).
spec_over = mgrid.MasterGridSpec(
    page_id="unit_test2", columns={"코드": "text"}, order=["코드"],
    grid_options={"rowHeight": 42},
)
check("화면 grid_options 오버라이드 후에도 복사 옵션 유지",
      copy_enabled(mgrid._build_grid_options(spec_over)))


# ===== 2) READ 그리드(키트) =====
print("READ 그리드(_build_read_gridoptions) — 복사 허용 + 편집 자산 없음")
read_opts = kit._build_read_gridoptions([{"field": "성명"}])
check("READ 최종 옵션에 셀 복사 2옵션", copy_enabled(read_opts))
check("READ 는 행 클릭 선택 없음 유지", read_opts.get("suppressRowClickSelection") is True)
check("READ 에 편집/붙여넣기 자산 없음",
      not any(k in read_opts for k in ("onGridReady", "singleClickEdit", "rowSelection")))
check("READ 빈 상태 오버레이 유지", "overlayNoRowsTemplate" in read_opts)


# ===== 3) SELECT 그리드(키트) =====
print("SELECT 그리드(_build_select_gridoptions) — 복사 허용 + 단일 선택 계약 보존")
sel_df = pd.DataFrame({"_k": ["r1", "r2"], "작업명": ["A", "B"]})
_view, sel_opts, _css = kit._build_select_gridoptions(
    sel_df, key_field="_k", columns=["작업명"], selected_key=None,
    color_rules=None, col_config=None, row_rules=None, hidden_fields=None,
    row_height=32,
)
check("SELECT 최종 옵션에 셀 복사 2옵션", copy_enabled(sel_opts))
check("SELECT 단일 행선택 유지", sel_opts.get("rowSelection") == "single")
check("SELECT 행 클릭 선택 유지", sel_opts.get("suppressRowClickSelection") is False)
check("SELECT 선택 해제 억제 유지", sel_opts.get("suppressRowDeselection") is True)
check("SELECT 에 편집 자산 없음",
      not any(k in sel_opts for k in ("onGridReady", "singleClickEdit", "onCellKeyDown")))


# ===== 4) 근무표 편성 그리드(workspace) =====
print("편성 그리드(selectable_master_grid) — AgGrid 에 전달된 실제 옵션 캡처")
_captured: dict = {}


class _Resp:
    def __init__(self, data):
        self.data = data


def _fake_aggrid(frame, **kwargs):
    _captured.update(kwargs)
    return _Resp(frame)


_orig_aggrid = ws.AgGrid
_orig_shell = ws.erp.grid_shell
try:
    ws.AgGrid = _fake_aggrid
    ws.erp.grid_shell = lambda key, **kw: kw["render"]()   # 스켈레톤/세션 우회
    ws.selectable_master_grid(
        pd.DataFrame({"코드": ["A"], "사용": [True]}),
        key="unit_test_roster",
        columns={"코드": "text", "사용": "bool"},
        height=200,
        select_all_header=True,
    )
finally:
    ws.AgGrid = _orig_aggrid
    ws.erp.grid_shell = _orig_shell

roster_opts = _captured.get("gridOptions", {})
check("편성 그리드가 AgGrid 에 gridOptions 전달", bool(roster_opts))
check("편성 최종 옵션에 셀 복사 2옵션", copy_enabled(roster_opts))
check("편성 붙여넣기 핸들러 유지(onGridReady)", "onGridReady" in roster_opts)
check("편성 단일클릭 편집 금지 유지", roster_opts.get("singleClickEdit") is False)
check("편성 행 클릭=선택 억제 유지",
      roster_opts.get("suppressRowClickSelection") is True)
check("편성 _action 열 유지",
      any(c.get("field") == "_action" for c in roster_opts.get("columnDefs", [])))
check("편성 그리드 AgGrid 는 여전히 JsCode 허용(allow_unsafe_jscode)",
      _captured.get("allow_unsafe_jscode") is True)


print()
if FAIL:
    print(f"FAILED {len(FAIL)}: {FAIL}")
    sys.exit(1)
print(f"ALL PASSED ({PASS} checks)")
