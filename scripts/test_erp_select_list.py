"""WORKLIST 목록 컴포넌트 `erp.select_list` 계약 테스트.

DESIGN §2 WORKLIST 가 강제하는 것을 컴포넌트가 실제로 지키는지 고정한다:
  - 행은 2줄 고정(상태로 줄 수가 달라지지 않음), 상태는 좌측 2px 보더로만 표현
  - 선택은 위치가 아니라 **자연키**로 오간다
  - 선택 표시는 select_grid 와 같은 어휘(틴트 + 좌측 바 navy) — 색 단독 아님
  - 편집 자산 없음(SELECT 는 편집 capability 가 아니다)

실행: PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/test_erp_select_list.py
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

from views.common import erp  # noqa: E402
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


print("공개 계약")
check("erp.select_list 노출", hasattr(erp, "select_list"))
check("erp.__all__ 등재", "select_list" in erp.__all__)
sig = inspect.signature(erp.select_list)
check("시그니처: key·items 위치인자", list(sig.parameters)[:2] == ["key", "items"])
for kw in ("selected", "empty", "height"):
    check(f"키워드 인자 [{kw}]", kw in sig.parameters)
check("반환 타입은 자연키(str) 또는 None",
      str(sig.return_annotation).replace(" ", "") in ("str|None", "'str|None'"))

print("컴포넌트 정의(§2 WORKLIST 골격)")
src = inspect.getsource(kit)
check("st.components.v2 로 만든다(select_grid cellRenderer 차단 우회 아님)",
      "st.components.v2.component" in src and "erp_select_list" in src)
check("select_grid 의 편집자산 화이트리스트는 그대로 유지",
      "_SELECT_COL_CONFIG_ALLOWED" in src and "cellRenderer" not in src.split("_SELECT_LIST")[1])
check("행이 2줄 구조(esl-l1/esl-l2)", ".esl-l1" in src and ".esl-l2" in src)
check("상태는 좌측 2px 보더로 표현", "border-left:2px solid transparent" in src)
check("선택은 틴트+좌측 바 이중부호화(색 단독 금지)",
      "selected-bg" in src and "border-left-color:{TOKENS['navy']}" in src)
check("선택 어휘가 select_grid 와 같은 navy 토큰",
      "TOKENS['navy']" in src)
check("긴 값은 말줄임(min-width:0 + ellipsis)",
      "min-width:0" in src and "text-overflow:ellipsis" in src)
check("키보드 포커스 링", "focus-visible" in src)

print("자연키 계약(순수 로직)")
body = inspect.getsource(erp.select_list)
check("자연키 없는 행은 싣지 않는다", 'if not k:' in body and "continue" in body)
check("키를 문자열로 정규화", 'str(it.get("key", "")).strip()' in body)
check("선택 상태 보관은 호출부 책임(컴포넌트는 표시·전달만)",
      "보관은 호출부" in body or "호출부" in body)
check("height 주면 목록 자체 스크롤(상세와 독립)", "height" in body)

print("JS 측 계약")
js = src.split("_SELECT_LIST")[1]
check("클릭이 자연키를 실어 보낸다", "setTriggerValue('pick'" in js and "dataset.key" in js)
check("XSS 방어 — 값 escape", "replace(/[&<>\"']/g" in js)
check("빈 목록은 안내 문구", "esl-empty" in js)
check("aria-pressed 로 선택 상태 노출", "aria-pressed" in js)

print(f"\n{'ALL PASSED' if not FAIL else 'FAILED'} ({PASS} checks)")
for name in FAIL:
    print(f"  - {name}")
sys.exit(1 if FAIL else 0)
