"""화면 유형 규약(DESIGN.md §0) 집행 계약 테스트.

§0 는 모든 화면이 4유형(EDIT_GRID/READ_VIEW/MATRIX_EDIT/DASHBOARD) 중 하나를
``SCREEN_ARCHETYPE`` 상수로 선언하고, 신규 화면의 페이지 크롬은 공용 스캐폴드
(``views/common/scaffold.py``) 또는 ``views/master`` 공통 기반으로만 만들도록
강제한다. 이 스위트는 그 집행 장치를 검증한다:

  (a) 알려진 화면 모듈(존재하는 것만 — 화면 추가·분리·통합은 자유)이 유효한
      ``SCREEN_ARCHETYPE`` 을 선언한다.
  (b) ``views/`` 최상위에 알려진 목록(9개 화면 + login + workspace) 밖의 **새**
      화면 .py 파일이 생기면, ``SCREEN_ARCHETYPE`` 선언 + 스캐폴드/공통 기반 사용이
      둘 다 없을 때 실패시킨다(신규 화면 강제 장치). 하위 패키지(views/master,
      views/common) 내부 파일은 대상이 아니다.
  (c) ``views/common/scaffold.py`` 의 archetype 검증(잘못된 유형 → ValueError).

실행: PYTHONUTF8=1 .venv/Scripts/python.exe scripts/test_screen_scaffold.py
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["DUTY_DATA_MODE"] = "sample"

from views.common import scaffold  # noqa: E402

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


# 규약 대상 9개 화면과 선언해야 할 유형.
EXPECTED = {
    "dashboard": "DASHBOARD",
    "schedule_edit": "MATRIX_EDIT",
    "schedule_view": "READ_VIEW",
    "my_schedule": "READ_VIEW",
    "master_users": "EDIT_GRID",
    "master_org": "EDIT_GRID",
    "master_work_types": "EDIT_GRID",
    "master_departments": "EDIT_GRID",
    "master_teams": "EDIT_GRID",
}
# 화면 규약 대상이 아닌 최상위 모듈(선언 불필요 — 화면 크롬 규약 밖).
NON_ARCHETYPE = {"login", "workspace"}
# 최상위에서 화면 모듈이 아닌 파일(패키지 init 등).
NOT_A_SCREEN = {"__init__"}


# ===========================================================================
# (a) 알려진 9개 화면이 유효한 SCREEN_ARCHETYPE 을 선언
# ===========================================================================
print("(a) 화면 유형 선언 — 존재하는 알려진 화면이 유효한 SCREEN_ARCHETYPE 선언")
# 화면 수는 규약 대상이 아니다(DESIGN.md §0) — 기준정보 화면의 추가·분리·통합은 자유이며,
# 제거·통합된 화면은 검사에서 제외한다. 새 화면은 (b) 강제 장치가 커버한다.
for name, expected in EXPECTED.items():
    if not (ROOT / "views" / f"{name}.py").exists():
        print(f"  (views.{name} 없음 — 통합/제거된 화면, 검사 생략)")
        continue
    mod = importlib.import_module(f"views.{name}")
    declared = getattr(mod, "SCREEN_ARCHETYPE", None)
    check(f"views.{name}: SCREEN_ARCHETYPE 선언됨", declared is not None)
    check(
        f"views.{name}: 유효 유형 (선언={declared!r})",
        declared in scaffold.ARCHETYPES,
    )
    check(
        f"views.{name}: 기대 유형 == {expected}",
        declared == expected,
    )


# ===========================================================================
# (b) views/ 최상위의 미등록 신규 화면 강제 장치
# ===========================================================================
print("(b) 신규 화면 강제 — 미등록 최상위 .py 는 유형 선언 + 스캐폴드/공통기반 사용")
KNOWN = set(EXPECTED) | NON_ARCHETYPE | NOT_A_SCREEN
top_level = sorted(p.stem for p in (ROOT / "views").glob("*.py"))
unknown = [stem for stem in top_level if stem not in KNOWN]
check("미등록 최상위 화면 모듈 목록 스캔 가능", top_level != [])
for stem in unknown:
    src = (ROOT / "views" / f"{stem}.py").read_text(encoding="utf-8")
    has_archetype = "SCREEN_ARCHETYPE" in src
    uses_scaffold = (
        "views.common.scaffold" in src
        or "from views.common" in src
        or "from views import master" in src
        or "from views.master" in src
    )
    check(
        f"신규 화면 views.{stem}: SCREEN_ARCHETYPE 선언 + 스캐폴드/공통기반 사용",
        has_archetype and uses_scaffold,
    )
if not unknown:
    print("  (미등록 신규 화면 없음 — 강제 장치는 새 파일 추가 시 동작)")


# ===========================================================================
# (c) 스캐폴드 archetype 검증 단위 검사
# ===========================================================================
print("(c) 스캐폴드 검증 — 잘못된 유형 ValueError / 목록 정합")
check(
    "ARCHETYPES == DESIGN.md §0 4유형",
    scaffold.ARCHETYPES == ("EDIT_GRID", "READ_VIEW", "MATRIX_EDIT", "DASHBOARD"),
)
try:
    scaffold._validate_archetype("NOT_A_TYPE")
    check("잘못된 유형은 ValueError", False)
except ValueError:
    check("잘못된 유형은 ValueError", True)
for good in scaffold.ARCHETYPES:
    check(f"유효 유형 통과 [{good}]", scaffold._validate_archetype(good) == good)


print()
if FAIL:
    print(f"FAILED {len(FAIL)}: {FAIL}")
    sys.exit(1)
print(f"ALL PASSED ({PASS} checks)")
