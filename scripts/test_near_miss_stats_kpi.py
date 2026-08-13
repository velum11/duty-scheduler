"""아차사고 분석(near_miss_stats) KPI 스트립 표시 계약 — 2줄 타일 + 행 간 카드 폭 통일.

집계·권한 로직은 다루지 않는다(그건 test_near_miss_ui_gates / test_near_miss_error_surfacing
소관). 여기서는 **표시만** 고정한다:
  1) 타일은 라벨+값 2줄 — 영문 오버라인(ALL/PENDING/DONE ...)은 렌더되지 않는다.
     호출부 튜플 계약 ``(label, value, unit, note, accent)`` 은 유지된다(note 는 미렌더).
  2) 누적(6)·당월(4) 두 행이 같은 그리드 트랙 수를 공유한다 — 트랙 수는 가장 지표가 많은
     그룹에서 파생하고 상수로 박지 않으며, 지표가 적은 행은 늘어나지 않고 칸을 비운다.
  3) 값·집계 문자열은 종전과 동일(표시 전용 변경 — 회귀 방지).

실행: PYTHONUTF8=1 C:\\dev\\workops\\.venv\\Scripts\\python.exe scripts/test_near_miss_stats_kpi.py
"""
from __future__ import annotations

import inspect
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["DUTY_DATA_MODE"] = "sample"

from views import near_miss_stats as nms  # noqa: E402

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


STATUS_CUM = {"SUBMITTED": 1, "IN_REVIEW": 0, "EVALUATED": 1, "CLOSED": 1}
STATUS_CUR = {"SUBMITTED": 1, "IN_REVIEW": 0, "EVALUATED": 0, "CLOSED": 0}

cum_label, cum_items = nms._kpi_cards_cumulative(STATUS_CUM, 3, 0, "2026-08")
cur_label, cur_items = nms._kpi_cards_current(STATUS_CUR, 1, "2026-08")

# ===== 1) 값 계약 불변(표시 전용 변경) =====
print("KPI 값 계약 불변")
check("누적 그룹 라벨 '누적 · 2026.08까지'", cum_label == "누적 · 2026.08까지")
check("당월 그룹 라벨 '당월 · 2026.08'", cur_label == "당월 · 2026.08")
check("누적 6지표 유지", len(cum_items) == 6)
check("당월 4지표 유지", len(cur_items) == 4)
check("누적 라벨 순서 불변",
      [i[0] for i in cum_items]
      == ["총 건수", "평가 대기", "검토중", "평가완료", "기한초과", "보고서 종결률"])
check("당월 라벨 순서 불변",
      [i[0] for i in cur_items] == ["당월 발생", "미평가", "평가완료", "종결"])
check("누적 값: 총3·대기1·검토0·완료1·기한초과 0건·종결률 50%",
      [i[1] for i in cum_items] == ["3", "1", "0", "1", "0건", "50%"])
check("당월 값: 발생1·미평가1·완료0·종결0",
      [i[1] for i in cur_items] == ["1", "1", "0", "0"])
check("튜플 계약 5요소 유지(note 자리 보존)",
      all(len(i) == 5 for i in cum_items + cur_items))

# ===== 2) 2줄 타일 — 영문 오버라인 미렌더 =====
print("2줄 타일(영문 오버라인 미렌더)")
html_cum = nms._kpi_group_html(cum_label, cum_items)
html_cur = nms._kpi_group_html(cur_label, cur_items)
both = html_cum + html_cur
check("nmf-knote(3번째 줄) 요소 없음", "nmf-knote" not in both)
for token in ("ALL", "PENDING", "IN REVIEW", "DONE", "OVERDUE", "CLOSED", "MONTH"):
    check(f"영문 오버라인 '{token}' 미노출", f">{token}<" not in both)
check("라벨 줄은 그대로 렌더", "nmf-klabel" in html_cum and "총 건수" in html_cum)
check("값 줄은 그대로 렌더", "nmf-kval" in html_cum and "50%" in html_cum)
check("단위(건)는 값 옆에 유지", "nmf-kunit" in html_cum)
style_src = inspect.getsource(nms._inject_style)
check("nmf-knote CSS 규칙도 제거", "nmf-knote" not in style_src)

# ===== 3) 두 행 카드 폭 통일(공유 그리드 트랙) =====
print("누적·당월 카드 폭 통일")
css = nms._kpi_grid_css(6)
cols = re.findall(r"repeat\((\d+),minmax\(0,1fr\)\)", css)
check("데스크톱 트랙 수 = 최대 지표 수(6)", cols and cols[0] == "6")
check("좁은 폭 단계 존재(3열·2열)", cols[1:] == ["3", "2"])
check("트랙 수는 인자로 파생(4 지표면 4열)",
      re.findall(r"repeat\((\d+),minmax\(0,1fr\)\)", nms._kpi_grid_css(4))[0] == "4")
check("2열 이하로는 더 쪼개지 않음",
      re.findall(r"repeat\((\d+),minmax\(0,1fr\)\)", nms._kpi_grid_css(2)) == ["2", "2", "2"])
check("스트립은 grid(타일이 flex-grow 로 늘어나지 않음)",
      "display:grid" in style_src and "flex:1 1 130px" not in style_src)
section_src = inspect.getsource(nms._kpi_section)
check("트랙 수는 그룹 중 최대치에서 파생(상수 하드코딩 없음)",
      "max(len(items)" in section_src)
check("두 그룹을 한 번의 markdown 으로 렌더(같은 CSS 트랙 공유)",
      section_src.count("st.markdown") == 1)
render_src = inspect.getsource(nms.render)
check("render 는 _kpi_section 으로 두 그룹을 함께 넘긴다",
      "_kpi_section(" in render_src
      and "_kpi_cards_cumulative(" in render_src and "_kpi_cards_current(" in render_src)

print()
if FAIL:
    print(f"FAILED {len(FAIL)}: {FAIL}")
    sys.exit(1)
print(f"ALL PASSED ({PASS} checks)")
