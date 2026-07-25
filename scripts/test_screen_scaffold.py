"""화면 유형 규약(DESIGN.md §0) 집행 계약 테스트 — AST 기반, 우회 불가.

§0 는 모든 화면이 4유형(EDIT_GRID/READ_VIEW/MATRIX_EDIT/DASHBOARD) 중 하나를
``SCREEN_ARCHETYPE`` 상수로 선언하고, 페이지 크롬을 공용 스캐폴드
(``views/common/scaffold.py`` 의 ``page_chrome``/``page_chrome_for``) 또는
``views/master`` 공통 기반의 **실제 호출**로만 만들도록 강제한다. 이 스위트는
그 집행 장치를 순수 AST 분석으로 검증한다(문자열 존재 검사 금지).

집행 범위와 우회 차단
---------------------
Codex 감사(P2-5)가 지적한 4개 우회 경로를 각각 다음으로 차단한다:

  1. **최상위만 스캔** → route 연결 기반 + ``views/`` 전체 ``rglob('*.py')`` 재귀
     스캔. 인프라 패키지(``views/master/``·``views/common/``)와 비화면 모듈
     (``__init__``·``workspace``·``login``)만 제외하므로, ``views/xxx/new_page.py``
     같은 새 하위 패키지 화면도 걸린다.
  2. **문자열 존재 검사** → 순수 AST. ``SCREEN_ARCHETYPE`` 는 모듈 레벨 ``Assign``
     노드 + ``Constant`` 문자열 값일 때만 인정한다. 주석 속 선언·docstring 언급은
     AST 에 노드가 없어 잡히지 않는다.
  3. **호출 미확인** → 크롬 생성은 AST ``Call`` 노드 존재로 검증한다. 미사용
     ``import scaffold`` 나 문자열 언급만으로는 통과하지 못한다.
  4. **EDIT_GRID 스택 미검증** → EDIT_GRID 는 헤더(``master_screen_head`` 또는
     ``page_chrome`` 계열) + ``render_master_grid`` + (``master_action_bar`` 또는
     ``run_save``) 의 ``Call`` 이 모두 존재해야 한다.

의도적으로 강제하지 **않는** 것(정직한 한계)
--------------------------------------------
- 화면 **개수**·파일 존재를 강제하지 않는다(§0: 화면 추가·분리·통합 자유). 알려진
  화면의 기대 유형 맵은 "존재하는 경우에만" 검증한다.
- 유형별 **전체 크롬의 순서·구성**(필터바→그리드→액션바→상태 스트립 등)은 코드로
  강제하지 않는다. scaffold 는 헤더 크롬만 생성한다. 전체 크롬 순서·간격·대비의
  최종 게이트는 이 계약 테스트(선언·실호출·EDIT_GRID 스택) + visual-qa 측정 +
  사용자 실브라우저 sign-off 다.
- ``my_schedule`` 는 ``user_app_shell`` 기반 USER 셸 화면으로 DESIGN §0 의 명문
  예외다 — 유형 선언(AST)은 검사하되, 크롬 호출 검사는 **면제**한다(셸이 헤더
  크롬을 제공하므로 화면이 page_chrome 을 직접 호출하지 않는다).

위임 화면
---------
다른 화면 모듈의 ``render(...)`` 만 호출하는 레거시 위임(예:
``master_departments`` → ``master_org``)은, 위임 대상이 규약 준수 화면이면
통과시킨다.

실행: .venv/Scripts/python.exe scripts/test_screen_scaffold.py (stdout 은 UTF-8 자동 설정)
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

# Windows 기본 콘솔(cp949)에서도 유형표·em dash 출력이 UnicodeEncodeError 로
# 멈추지 않도록 stdout 을 UTF-8 로 재설정한다(PYTHONUTF8=1 없이도 실행 가능).
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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


# ===========================================================================
# 순수 AST 검사 프리미티브 — 모두 소스 "문자열" 입력으로 단위 검증 가능(음성검증용).
# ===========================================================================

def module_archetype(src: str) -> str | None:
    """모듈 레벨 ``SCREEN_ARCHETYPE = "<문자열 상수>"`` 할당의 값을 반환한다.

    AST 만 본다 — 주석·docstring·문자열 속 ``SCREEN_ARCHETYPE`` 은 노드가 없어
    잡히지 않는다(우회 경로 2 차단). 상수 문자열 값이 아니면(예: 표현식·변수)
    ``None`` 을 반환한다.
    """
    tree = ast.parse(src)
    for node in tree.body:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
            value = node.value
        else:
            continue
        for tgt in targets:
            if isinstance(tgt, ast.Name) and tgt.id == "SCREEN_ARCHETYPE":
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    return value.value
                return None
    return None


def called_names(src: str) -> set[str]:
    """모듈 내 모든 ``Call`` 의 피호출 단순 이름 집합.

    ``foo(...)`` → ``foo`` ; ``mod.foo(...)`` → ``foo`` (attribute 의 말단 이름).
    미사용 import·문자열 언급은 ``Call`` 노드가 아니므로 포함되지 않는다
    (우회 경로 3 차단).
    """
    tree = ast.parse(src)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


def render_delegation_targets(src: str) -> set[str]:
    """``X.render(...)`` 형태로 호출된 모듈 이름 ``X`` 집합(위임 대상 후보)."""
    tree = ast.parse(src)
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            f = node.func
            if f.attr == "render" and isinstance(f.value, ast.Name):
                targets.add(f.value.id)
    return targets


def _has_head(names: set[str]) -> bool:
    return bool(names & {"master_screen_head", "page_chrome", "page_chrome_for"})


def _has_page_chrome(names: set[str]) -> bool:
    return bool(names & {"page_chrome", "page_chrome_for"})


def has_editgrid_stack(names: set[str]) -> bool:
    """EDIT_GRID 전체 스택: 헤더 + 그리드 + (액션바 | 저장) 실호출이 모두 존재."""
    head = _has_head(names)
    grid = "render_master_grid" in names
    action = bool(names & {"master_action_bar", "run_save"})
    return head and grid and action


def chrome_own_ok(archetype: str, src: str) -> bool:
    """자기 자신의 크롬 실호출이 유형 규약을 충족하는지(위임 미고려)."""
    names = called_names(src)
    if archetype == "EDIT_GRID":
        return has_editgrid_stack(names)
    return _has_page_chrome(names)


# 크롬 호출 검사를 면제하는 화면(USER 셸 기반 명문 예외 — 위 docstring 참조).
CHROME_EXEMPT = {"my_schedule"}


def chrome_ok(name: str, src: str, archetype: str, sources_by_stem: dict[str, str]) -> bool:
    """유형 선언이 유효한 화면의 크롬 실호출 충족 여부(면제·위임 포함)."""
    if name in CHROME_EXEMPT:
        return True  # USER 셸이 헤더 크롬 제공 — page_chrome 직접 호출 면제.
    if chrome_own_ok(archetype, src):
        return True
    # 위임: 대상 화면이 규약(유효 유형 + 자기 크롬)을 준수하면 통과.
    for target in render_delegation_targets(src):
        tsrc = sources_by_stem.get(target)
        if tsrc is None:
            continue
        t_arch = module_archetype(tsrc)
        if t_arch in scaffold.ARCHETYPES and chrome_own_ok(t_arch, tsrc):
            return True
    return False


# ===========================================================================
# 화면 집합 발견 — route 연결(1차) + views/ 재귀 스캔(rglob).
# ===========================================================================

INFRA_DIRS = {"master", "common"}          # views 하위 인프라 패키지(화면 아님).
NON_SCREEN = {"__init__", "workspace", "login"}  # 비화면 모듈.


def route_connected_screens(app_src: str) -> set[str]:
    """``app.py`` 의 실제 라우팅에 연결된 화면 모듈 stem 집합(AST).

    - ``from views import (...)`` 로 들여온 이름을 화면 후보로 본다.
    - ``_PAGES`` dict 리터럴의 값(모듈 Name) + dispatch 의 직접 ``mod.render(...)``
      호출 대상을 route 연결 화면으로 수집한다.
    """
    tree = ast.parse(app_src)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "views":
            for alias in node.names:
                imported.add(alias.asname or alias.name)
    routed: set[str] = set()
    for node in ast.walk(tree):
        # _PAGES = { "...": module, ... }
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "_PAGES":
                    if isinstance(node.value, ast.Dict):
                        for v in node.value.values:
                            if isinstance(v, ast.Name) and v.id in imported:
                                routed.add(v.id)
        # mod.render(...) 직접 분기
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            f = node.func
            if f.attr == "render" and isinstance(f.value, ast.Name) and f.value.id in imported:
                routed.add(f.value.id)
    return routed


def screen_label_for(parts: tuple[str, ...]) -> str | None:
    """``views`` 기준 상대 경로 조각으로 화면 라벨을 만들거나 제외 시 ``None``.

    인프라 패키지(``master``·``common``) 하위 전부와 비화면 모듈
    (``__init__``·``workspace``·``login``)은 제외한다. 그 외는 dotted 라벨
    (top-level 은 stem, 하위 패키지는 ``pkg.mod``)을 반환한다 — 새 하위 패키지
    화면(``views/xxx/new_page.py``)도 포함되어 우회 경로 1 을 차단한다.
    """
    if not parts:
        return None
    if parts[0] in INFRA_DIRS:
        return None
    if parts[-1] in NON_SCREEN:
        return None
    return ".".join(parts)


def discover_screens() -> list[tuple[str, Path]]:
    """화면 (label, path) 목록: route 연결 ∪ views/ 재귀 스캔, 인프라/비화면 제외.

    label 은 ``views`` 기준 상대 dotted 경로(top-level 은 stem). 새 하위 패키지
    화면(``views/xxx/new_page.py``)도 rglob 로 포함된다(우회 경로 1 차단).
    """
    views_dir = ROOT / "views"
    found: dict[str, Path] = {}

    # rglob 재귀 스캔
    for path in views_dir.rglob("*.py"):
        rel = path.relative_to(views_dir)
        label = screen_label_for(rel.with_suffix("").parts)
        if label is None:
            continue
        found[label] = path

    # route 연결 화면(1차 출처) — top-level stem 기준으로 보강(제외 대상은 배제)
    app_src = (ROOT / "app.py").read_text(encoding="utf-8")
    for stem in route_connected_screens(app_src):
        if stem in NON_SCREEN:
            continue
        p = views_dir / f"{stem}.py"
        if p.exists():
            found.setdefault(stem, p)

    return sorted(found.items())


# 규약 대상 알려진 화면과 기대 유형(존재하는 경우에만 검증 — 개수 강제 아님).
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


# ===========================================================================
# (a) 발견된 모든 화면: 유효 SCREEN_ARCHETYPE 선언 + 크롬 실호출(유형별)
# ===========================================================================
print("(a) 화면 발견(route+rglob) — 유형 선언(AST) + 크롬 실호출(Call 노드)")
screens = discover_screens()
sources_by_stem = {
    p.stem: p.read_text(encoding="utf-8")
    for p in (ROOT / "views").glob("*.py")
}
check("화면 집합 발견됨(route 연결 + rglob 재귀)", len(screens) > 0)

for label, path in screens:
    src = path.read_text(encoding="utf-8")
    arch = module_archetype(src)
    # ① 유형 선언(AST) — 주석/문자열이 아니라 실제 모듈 레벨 상수 할당
    check(f"{label}: SCREEN_ARCHETYPE 상수 할당(AST)", arch is not None)
    check(f"{label}: 유효 유형(값={arch!r})", arch in scaffold.ARCHETYPES)
    # ②③ 크롬 실호출(면제·위임·EDIT_GRID 스택 반영)
    if arch in scaffold.ARCHETYPES:
        stem = path.stem
        note = " [면제:USER셸]" if stem in CHROME_EXEMPT else ""
        check(
            f"{label}: 크롬 실호출 규약 충족{note}",
            chrome_ok(stem, src, arch, sources_by_stem),
        )


# ===========================================================================
# (b) 알려진 화면 기대 유형 맵 — 존재하는 경우에만(파일 존재 강제 아님)
# ===========================================================================
print("(b) 기대 유형 맵 — 존재하는 알려진 화면만 검증(개수/존재 강제 없음)")
for name, expected in EXPECTED.items():
    p = ROOT / "views" / f"{name}.py"
    if not p.exists():
        print(f"  (views.{name} 없음 — 통합/제거된 화면, 검사 생략)")
        continue
    arch = module_archetype(p.read_text(encoding="utf-8"))
    check(f"views.{name}: 기대 유형 == {expected}", arch == expected)


# ===========================================================================
# (c) 스캐폴드 archetype 검증 단위 검사(기존 유지)
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


# ===========================================================================
# (d) 음성 검증 — 우회 샘플이 검사 함수에서 FAIL 나는지(문자열 입력 단위 테스트)
#     views/ 에 실파일을 만들지 않고, 검사 로직을 문자열로 구동한다.
# ===========================================================================
print("(d) 음성 검증 — 4개 우회 경로 각각이 검사에서 차단되는지")

# 우회 2: 주석 속 선언 + docstring 언급 → module_archetype 는 None(미탐)
BYPASS_COMMENT_ONLY = (
    '"""가짜 화면 — SCREEN_ARCHETYPE 를 docstring 에서만 언급."""\n'
    "# SCREEN_ARCHETYPE = \"EDIT_GRID\"  # 주석 선언(가짜)\n"
    "import views.common.scaffold as scaffold  # 미사용 import\n"
    "def render(user):\n"
    "    pass\n"
)
check(
    "우회2: 주석/문자열 선언은 유형 미탐(None)",
    module_archetype(BYPASS_COMMENT_ONLY) is None,
)

# 우회 3: 유효 선언 + 미사용 import + 'page_chrome' 문자열 언급 → 크롬 실호출 없음
BYPASS_IMPORT_ONLY = (
    'SCREEN_ARCHETYPE = "READ_VIEW"\n'
    "import views.common.scaffold as scaffold  # 미사용\n"
    "HINT = 'page_chrome_for is the api'  # 문자열 언급뿐\n"
    "def render(user):\n"
    "    return None\n"
)
check(
    "우회3: 미사용 import·문자열 언급만으로는 크롬 실호출 불충족",
    not chrome_own_ok("READ_VIEW", BYPASS_IMPORT_ONLY),
)

# 우회 4: EDIT_GRID 인데 헤더만 호출, 그리드/액션 없음 → 스택 불충족
BYPASS_PARTIAL_STACK = (
    'SCREEN_ARCHETYPE = "EDIT_GRID"\n'
    "from views.common import scaffold\n"
    "def render(user):\n"
    "    scaffold.page_chrome_for('x', SCREEN_ARCHETYPE)\n"  # 헤더만
    "    return None\n"
)
check(
    "우회4: EDIT_GRID 헤더만 호출(그리드/액션 없음)은 스택 불충족",
    not chrome_own_ok("EDIT_GRID", BYPASS_PARTIAL_STACK),
)

# 우회 1: 하위 패키지 화면은 라벨링되고(검사 대상), 인프라/비화면은 제외되는지.
check(
    "우회1: 하위 패키지 화면(views/xxx/new_page.py)도 검사 대상(라벨 부여)",
    screen_label_for(("xxx", "new_page")) == "xxx.new_page",
)
check(
    "우회1: 인프라 패키지(views/master/*·views/common/*)는 제외",
    screen_label_for(("master", "grid")) is None
    and screen_label_for(("common", "scaffold")) is None,
)
check(
    "우회1: 비화면 모듈(__init__·workspace·login)은 제외",
    screen_label_for(("__init__",)) is None
    and screen_label_for(("workspace",)) is None
    and screen_label_for(("login",)) is None,
)

# 양성 대조군: 온전한 EDIT_GRID 스택은 통과해야 한다.
GOOD_EDITGRID = (
    'SCREEN_ARCHETYPE = "EDIT_GRID"\n'
    "from views.master import master_screen_head, render_master_grid, run_save\n"
    "def render(user):\n"
    "    master_screen_head('t', 'd')\n"
    "    render_master_grid(spec, frame)\n"
    "    run_save(state)\n"
)
check("대조군: 온전한 EDIT_GRID 스택은 통과", chrome_own_ok("EDIT_GRID", GOOD_EDITGRID))

# 양성 대조군: 위임 화면은 대상이 준수하면 통과.
GOOD_DELEGATE = 'SCREEN_ARCHETYPE = "EDIT_GRID"\ndef render(user):\n    master_org.render(user)\n'
check(
    "대조군: 위임 화면은 준수 대상으로 위임 시 통과",
    chrome_ok("fake_delegate", GOOD_DELEGATE, "EDIT_GRID", {"master_org": GOOD_EDITGRID}),
)


print()
if FAIL:
    print(f"FAILED {len(FAIL)}: {FAIL}")
    sys.exit(1)
print(f"ALL PASSED ({PASS} checks)")
