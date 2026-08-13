"""내 아차사고 컬럼형 표 계약 회귀 (2026-08-13 "컬럼 나눠줘 — 조회 테이블 참조").

한 줄 요약 아코디언 → **컬럼형 표 + 전체폭 상세** 전환의 표시·선택 계약을 고정한다.
표시 라벨/색은 아차사고 조회(``views/near_miss_view``)와 같은 계열이어야 하고, 선택은
자연키(보고서 id)로 오가며 상세 진입 경로(행 클릭 → ``_render_detail``)가 보존돼야 한다.

  1) 컬럼 구성 — 조회 9열에서 신고자·소속만 뺀 7열, 순서 동일.
  2) 표시 서식 — 보고번호 모노, 발생일 ISO 원문, 빈 등급 '-', 상태·원인 한글 라벨.
  3) 색 규칙 — 상태·등급 색이 조회 화면과 **같은 값**(같은 상태가 화면마다 다른 색 금지).
  4) 선택 계약 — hidden 자연키(_report_id), 상세 여는 체크박스 없음(§0-1),
     USER·터치 행 피치 44px, 자연키 유일·비표시.
  5) 상세 진입 보존 — 선택된 자연키의 건이 _render_detail 로 전달되고, 앵커에 보고번호가
     노출된다. 목록에서 사라진 stale 선택은 조용히 해제된다.

실행: PYTHONUTF8=1 C:\\dev\\workops\\.venv\\Scripts\\python.exe scripts/test_near_miss_my_table.py
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
import streamlit as st  # noqa: E402

from views import near_miss_my as nmy  # noqa: E402
from views import near_miss_view as nmv  # noqa: E402
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


REPORTS = pd.DataFrame([
    {"id": "NM-1", "report_no": "202608-0004", "status": "SUBMITTED",
     "work_name": "전동밸브 점검", "incident_date": "2026-08-11",
     "proposed_grade": "C", "confirmed_grade": None, "cause_code": "BURN"},
    {"id": "NM-2", "report_no": "202607-0002", "status": "EVALUATED",
     "work_name": "설비 청소", "incident_date": "2026-07-21",
     "proposed_grade": "C", "confirmed_grade": "B", "cause_code": "SLIP"},
    {"id": "NM-3", "report_no": "202606-0001", "status": "CLOSED",
     "work_name": "", "incident_date": "2026-06-02",
     "proposed_grade": None, "confirmed_grade": "D", "cause_code": "DROP"},
])


# ===== 1) 컬럼 구성 — 조회 9열 − (신고자·소속) =====
print("컬럼 구성(조회 참조)")
check("표시 7열", len(nmy._DISPLAY_COLUMNS) == 7)
check("신고자 열 없음(본인 전용 화면)", "신고자" not in nmy._DISPLAY_COLUMNS)
check("소속 열 없음(본인 전용 화면)", "소속" not in nmy._DISPLAY_COLUMNS)
check("조회 컬럼 순서 보존(신고자·소속 제외 시 동일)",
      nmy._DISPLAY_COLUMNS
      == [c for c in nmv._DISPLAY_COLUMNS if c not in ("신고자", "소속")])
check("모든 표시 열이 조회 화면 열의 부분집합",
      set(nmy._DISPLAY_COLUMNS) <= set(nmv._DISPLAY_COLUMNS))
check("모든 표시 열에 폭 지정(_COL_CONFIG)",
      all(c in nmy._COL_CONFIG for c in nmy._DISPLAY_COLUMNS))
check("보고번호는 모노(조회와 동일 서식)",
      "Mono" in str(nmy._COL_CONFIG["보고번호"].get("cellStyle", {})))
check("작업명만 잔여 폭 흡수(flex)",
      [c for c, cfg in nmy._COL_CONFIG.items() if "flex" in cfg] == ["작업명"])


# ===== 2) 표시 서식(_to_display) =====
print("표시 서식")
disp = nmy._to_display(REPORTS)
check("행 수 보존", len(disp) == 3)
check("컬럼 = 자연키 + 표시 7열",
      list(disp.columns) == [nmy._KEY_FIELD] + nmy._DISPLAY_COLUMNS)
r0 = disp.iloc[0].to_dict()
check("보고번호 원문", r0["보고번호"] == "202608-0004")
check("발생일 ISO 원문(YYYY-MM-DD)", r0["발생일"] == "2026-08-11")
check("상태 한글 라벨", r0["상태"] == nmy._STATUS_LABEL["SUBMITTED"])
check("원인 한글 라벨", r0["원인"] == nmy._CAUSE_LABEL["BURN"])
check("빈 확정등급은 '-'(코드 노출·빈칸 금지)", r0["확정등급"] == "-")
check("빈 제안등급도 '-'", disp.iloc[2]["제안등급"] == "-")
check("작업명 빈값 폴백", disp.iloc[2]["작업명"] == "(제목 없음)")
check("자연키는 보고서 id 문자열", list(disp[nmy._KEY_FIELD]) == ["NM-1", "NM-2", "NM-3"])
check("원시 상태코드 미노출", "EVALUATED" not in set(disp["상태"]))
check("원시 원인코드 미노출", "SLIP" not in set(disp["원인"]))


# ===== 3) 색 규칙 — 조회 화면과 같은 값 =====
print("상태·등급 색(조회와 동일 값)")
for code in ("SUBMITTED", "IN_REVIEW", "EVALUATED", "CLOSED", "REJECTED"):
    check(f"상태색 {code} 조회와 동일",
          nmy._STATUS_COLOR[code] == nmv._STATUS_COLOR[code])
check("상태 5종 전부 색 보유", set(nmy._STATUS_COLOR) == set(nmy._STATUS_LABEL))
check("등급색 매핑이 조회와 동일", nmy._GRADE_COLOR == nmv._GRADE_COLOR)


# ===== 4) 선택 계약(select_grid 옵션 실제 빌드) =====
print("선택 계약")
list_src = inspect.getsource(nmy._render_list)
check("목록은 공용 select_grid 어휘 사용", "erp.select_grid(" in list_src)
check("상세 여는 체크박스 없음(§0-1)", "checkbox_marker=False" in list_src)
check("USER·터치 행 피치 44px", "row_height=44" in list_src)
check("자연키는 표시 컬럼이 아님", nmy._KEY_FIELD not in nmy._DISPLAY_COLUMNS)

view, options, _css = kit._build_select_gridoptions(
    disp, key_field=nmy._KEY_FIELD, columns=nmy._DISPLAY_COLUMNS,
    selected_key="NM-2", color_rules={
        "제안등급": nmy._GRADE_COLOR, "확정등급": nmy._GRADE_COLOR,
        "상태": {lab: nmy._STATUS_COLOR[c] for c, lab in nmy._STATUS_LABEL.items()},
    },
    col_config=nmy._COL_CONFIG, row_rules=None, hidden_fields=None,
    row_height=44, checkbox_marker=False,
)
check("grid 옵션 rowHeight=44", options["rowHeight"] == 44)
check("단일 선택(rowSelection=single)", options["rowSelection"] == "single")
check("행 클릭이 선택(suppressRowClickSelection=False)",
      options["suppressRowClickSelection"] is False)
check("첫 열에 checkboxSelection 미주입",
      "checkboxSelection" not in options["columnDefs"][0])
check("자연키 컬럼은 hidden", any(cd["field"] == nmy._KEY_FIELD and cd.get("hide")
                              for cd in options["columnDefs"]))
check("표시 컬럼 순서 그대로 colDef",
      [cd["field"] for cd in options["columnDefs"] if not cd.get("hide")]
      == nmy._DISPLAY_COLUMNS)
check("선택 자연키 pre-select(위치 비의존, NM-2 → index 1)",
      options.get("initialState", {}).get("rowSelection") == ["1"])
# 좁은 폭 계약: 고정폭 합 + 작업명 minWidth 가 390px 를 넘으므로 AgGrid 가 **표 안에서**
# 가로 스크롤한다(§5 "표는 overflow-x:auto"). 페이지 가로 스크롤은 실측(Playwright)이 담당.
min_total = sum(cfg.get("width") or cfg.get("minWidth", 0)
                for cfg in nmy._COL_CONFIG.values())
check("표 최소 폭 > 390(좁은 폭에서 표 내부 가로 스크롤)", min_total > 390)


# ===== 5) 상세 진입 보존 =====
print("상세 진입 보존")
check("선택 시 _render_detail 호출", "_render_detail(" in list_src)
check("선택은 자연키로 행 복원(id 매칭)", 'frame["id"].astype(str) == selected' in list_src)
check("stale 선택은 세션에서 해제(pop)", "_SEL_KEY, None" in list_src)
check("빈 안내 패널을 그리지 않는다(§8-2 — empty_state/detail_empty 미호출)",
      "empty_state(" not in list_src and "detail_empty(" not in list_src)
check("미선택이면 상세 미렌더(빈 패널 금지 §8-2)", "if not selected:" in list_src)

anchor = nmy._detail_anchor_html(REPORTS.iloc[1].to_dict(), "EVALUATED")
check("상세 앵커에 보고번호 노출", "202607-0002" in anchor)
check("상세 앵커에 상태 배지(라벨) 노출", nmy._STATUS_LABEL["EVALUATED"] in anchor)
check("앵커 배지는 공용 kit primitive(status_badge_html) 사용",
      "status_badge_html" in inspect.getsource(nmy._detail_anchor_html))
detail_src = inspect.getsource(nmy._render_detail)
check("상세 첫 블록이 앵커", detail_src.index("_detail_anchor_html")
      < detail_src.index("_steps_html"))
# 워크플로 계약 불변(표현만 교체) — 수정 진입·사진·배너 경로 보존.
check("SUBMITTED 자기수정 진입 보존", "_render_edit_entry" in detail_src)
check("사진 섹션 보존", "_render_my_photos" in detail_src)
check("보완요청 배너 보존", "_render_revision_banner" in detail_src)

# 구 아코디언 잔재 제거(행 버튼 CSS·토글 키) — 회귀 방지.
check("구 행 버튼(myrow_) 잔재 없음", "myrow_" not in inspect.getsource(nmy))
check("아코디언 토글 rerun 잔재 없음", "st.rerun()" not in list_src)


# ===== 6) 행위: 선택 자연키가 세션에 남고 stale 은 해제 =====
print("선택 상태(세션) 행위")
st.session_state[nmy._SEL_KEY] = "NM-없는건"
_orig = nmy.erp.select_grid
_seen = {}
try:
    def _fake_grid(df, **kw):
        _seen["selected_key"] = kw.get("selected_key")
        _seen["columns"] = kw.get("columns")
        return None
    nmy.erp.select_grid = _fake_grid
    nmy._render_detail = lambda *a, **k: _seen.setdefault("detail", a)  # type: ignore
    nmy._render_list({"emp_no": "1003"}, REPORTS)
    check("목록에 없는 stale 선택은 세션에서 제거",
          nmy._SEL_KEY not in st.session_state)
    check("stale 선택은 grid 에 pre-select 로 넘기지 않음",
          _seen.get("selected_key") is None)
    check("stale 선택이면 상세 미렌더", "detail" not in _seen)
    check("grid 에 표시 7열 전달", _seen.get("columns") == nmy._DISPLAY_COLUMNS)
finally:
    nmy.erp.select_grid = _orig
    st.session_state.pop(nmy._SEL_KEY, None)


print()
if FAIL:
    print(f"FAILED {len(FAIL)}: {FAIL}")
    sys.exit(1)
print(f"ALL PASSED ({PASS} checks)")
