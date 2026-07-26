"""화면 유형 규약(DESIGN.md §0) 집행 계약 테스트 — AST 기반, 우회 불가.

§0 는 모든 화면이 5유형(EDIT_GRID/READ_VIEW/MATRIX_EDIT/DASHBOARD/FORM_ENTRY) 중
하나를 ``SCREEN_ARCHETYPE`` 상수로 선언하고, 페이지 크롬을 공용 스캐폴드
(``views/common/scaffold.py`` 의 ``page_chrome``/``page_chrome_for``) 또는
``views/master`` 공통 기반의 **실제 호출**로만 만들도록 강제한다. 이 스위트는
그 집행 장치를 순수 AST 분석으로 검증한다(문자열 존재 검사 금지).

집행 범위와 우회 차단
---------------------
Codex 감사(P2-5)가 지적한 4개 우회 경로 + 후속 감사(Opus recon + Codex)가 지적한
3개 잔여 약점을 각각 다음으로 차단한다.

  1. **최상위만 스캔** → route dispatch 연결 기반(1차) + ``views/`` 전체
     ``rglob('*.py')`` 재귀 스캔(보강 그물). 인프라 패키지(``views/master/``·
     ``views/common/``)와 명시적 비화면 모듈(``__init__``·``workspace``·``login``)만
     제외하므로, ``views/xxx/new_page.py`` 같은 새 하위 패키지 화면도 걸린다.
  2. **문자열 존재 검사** → 순수 AST. ``SCREEN_ARCHETYPE`` 는 모듈 레벨 ``Assign``
     노드 + ``Constant`` 문자열 값일 때만 인정한다. 주석 속 선언·docstring 언급은
     AST 에 노드가 없어 잡히지 않는다.
  3. **호출 미확인** → 크롬 생성은 AST ``Call`` 노드 존재로 검증한다. 미사용
     ``import scaffold`` 나 문자열 언급만으로는 통과하지 못한다.
  4. **EDIT_GRID 스택 미검증** → EDIT_GRID 는 헤더(``master_screen_head`` 또는
     ``page_chrome`` 계열) + ``render_master_grid`` + (``master_action_bar`` 또는
     ``run_save``) 의 ``Call`` 이 모두 존재해야 한다.

후속 감사가 닫은 3개 잔여 약점(gap):

  5. **크롬 호출이 render 경로 위에 있음이 미증명(false pass)** → 크롬 ``Call`` 을
     모듈 어디서든 수집하면, ``render()`` 가 절대 부르지 않는 죽은 코드·미사용
     헬퍼 속 크롬 호출도 통과했다. 이제 모듈의 ``render(...)`` 진입점에서 출발하는
     **모듈 내 호출 그래프**(render + render 에서 전이적으로 호출되는 모듈 레벨
     함수)를 만들어, 크롬 ``Call`` 이 그 도달 집합 안에 있을 때만 규약 충족으로
     인정한다. render 에서 도달 불가한 크롬 호출·render 진입점 부재는 불충족이다
     (:func:`render_reachable`).
  6. **``login`` 등이 암묵(디렉터리/이름 패턴)으로 제외됨** → 실제 화면을 은폐할 수
     있는 조용한 패턴 대신, 비화면/인프라 제외를 **사유가 붙은 명시적 집합**
     (:data:`NON_SCREEN_REASONS`)으로 선언한다. 또한 제외 모듈이 ``SCREEN_ARCHETYPE``
     를 선언하면(=실제 화면인데 제외 목록에 숨은 경우) (e) 가드가 FAIL 시킨다.
  7. **화면 발견이 ``views/`` 에 고정됨** → ``app.py`` 밖(예: ``views/`` 외부 파일)에
     사는 라우팅 화면이 그물을 완전히 빠져나갈 수 있었다. 이제 발견을 ``app.py`` 의
     실제 route dispatch(``_PAGES`` 매핑 + dispatch 의 ``mod.render(...)`` 분기 —
     실제로 ``.render()`` 되는 것)로 구동하고, 각 라우팅 이름을 실제 import 문으로
     모듈 파일에 해소한다(파일 위치 무관). 해소 불가한 라우팅 화면은 조용히 건너뛰지
     않고 **FAIL 로 표면화**한다. ``views/**`` rglob 는 보강 그물로 유지한다.

의도적으로 강제하지 **않는** 것(정직한 한계)
--------------------------------------------
- 화면 **개수**·파일 존재를 강제하지 않는다(§0: 화면 추가·분리·통합 자유). 알려진
  화면의 기대 유형 맵은 "존재하는 경우에만" 검증한다.
- 유형별 **전체 크롬의 순서·구성**(필터바→그리드→액션바→상태 스트립 등)은 코드로
  강제하지 않는다. scaffold 는 헤더 크롬만 생성한다. 전체 크롬 순서·간격·대비의
  최종 게이트는 이 계약 테스트(선언·실호출·EDIT_GRID 스택·render 도달성) +
  visual-qa 측정 + 사용자 실브라우저 sign-off 다.
- 도달성은 **모듈 내 정적 호출 그래프**로만 판정한다(순수 AST, import/exec 없음).
  런타임 분기·간접 호출(``getattr``·콜백 등록·딕셔너리 디스패치)은 추적하지 않으므로,
  크롬을 그런 간접 경로로만 부르는 화면은 도달 불가로 보고 불충족 처리한다 — 현재
  모든 실화면은 크롬을 render 또는 render 가 직접 부르는 헬퍼에서 호출하므로 문제가
  없으나, 미래 화면이 간접 디스패치를 쓰면 이 한계를 인지해야 한다.
- route 발견의 모듈 해소는 ``app.py`` 의 정적 import 문(``from pkg import name`` /
  ``import a.b``)만 따른다. 동적 import(``importlib``·문자열 모듈명)는 추적하지 않는다.
- ``my_schedule`` 는 ``user_app_shell`` 기반 USER 셸 화면으로 DESIGN §0 의 명문
  예외다 — 유형 선언(AST)은 검사하되, 크롬 호출 검사는 **면제**한다(셸이 헤더
  크롬을 제공하므로 화면이 page_chrome 을 직접 호출하지 않는다). 면제는
  :data:`CHROME_EXEMPT_REASONS` 에 사유와 함께 명시된 이름 집합이다.

위임 화면
---------
다른 화면 모듈의 ``render(...)`` 만 호출하는 레거시 위임(예:
``master_departments`` → ``master_org``)은, 그 위임 호출이 **render 경로에서
도달 가능**하고 위임 대상이 규약 준수 화면이면 통과시킨다.

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


def _call_names_in(node: ast.AST) -> tuple[set[str], set[str]]:
    """``node`` 서브트리 내 ``Call`` 의 (단순 이름 집합, ``X.render()`` 위임 대상 집합).

    ``foo(...)`` → ``foo`` ; ``mod.foo(...)`` → ``foo`` (attribute 말단 이름).
    ``X.render(...)`` 의 ``X`` 는 위임 대상 후보로 별도 수집한다.
    미사용 import·문자열 언급은 ``Call`` 노드가 아니므로 포함되지 않는다.
    """
    names: set[str] = set()
    deleg: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            func = n.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
                if func.attr == "render" and isinstance(func.value, ast.Name):
                    deleg.add(func.value.id)
    return names, deleg


def render_reachable(src: str) -> tuple[set[str] | None, set[str]]:
    """``render(...)`` 진입점에서 도달 가능한 (호출 이름 집합, 위임 대상 집합).

    모듈 내 정적 호출 그래프를 만든다: ``render`` 본문에서 호출된 이름 + 그중
    모듈 레벨 함수인 것을 **전이적으로** 따라가며 호출 이름을 누적한다. 이렇게
    render 에서 실제로 도달하는 호출만 크롬 규약 판정에 쓰므로, 죽은 코드·미사용
    헬퍼 속 크롬 호출은 규약을 충족시키지 못한다(gap 5 차단).

    모듈에 모듈 레벨 ``render`` 가 없으면 ``(None, set())`` 을 반환한다 — 진입점이
    없으면 어떤 크롬 호출도 render-path 로 인정하지 않는다(실화면은 모두 render 를
    가지므로 정상 화면에는 영향이 없다).
    """
    tree = ast.parse(src)
    funcs: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.setdefault(node.name, node)
    if "render" not in funcs:
        return None, set()

    reach_names: set[str] = set()
    reach_deleg: set[str] = set()
    seen: set[str] = set()
    stack: list[str] = ["render"]
    while stack:
        fname = stack.pop()
        if fname in seen:
            continue
        seen.add(fname)
        fnode = funcs.get(fname)
        if fnode is None:
            continue
        names, deleg = _call_names_in(fnode)
        reach_names |= names
        reach_deleg |= deleg
        for nm in names:
            if nm in funcs and nm not in seen:
                stack.append(nm)
    return reach_names, reach_deleg


# 크롬 진입점: 직접 호출(page_chrome/page_chrome_for) 또는 공용 중립 키트의
# ``screen_frame``(KP-standard §0.2 — 내부에서 page_chrome 을 실호출하는 헤더 진입점).
_CHROME_ENTRIES = {"page_chrome", "page_chrome_for", "screen_frame"}


def _has_head(names: set[str]) -> bool:
    return bool(names & ({"master_screen_head"} | _CHROME_ENTRIES))


def _has_page_chrome(names: set[str]) -> bool:
    return bool(names & _CHROME_ENTRIES)


def has_editgrid_stack(names: set[str]) -> bool:
    """EDIT_GRID 전체 스택: 헤더 + 그리드 + (액션바 | 저장) 실호출이 모두 존재."""
    head = _has_head(names)
    grid = "render_master_grid" in names
    action = bool(names & {"master_action_bar", "run_save"})
    return head and grid and action


def chrome_own_ok(archetype: str, src: str) -> bool:
    """자기 자신의 크롬 실호출이 유형 규약을 충족하는지(render 경로 한정, 위임 미고려).

    크롬 ``Call`` 은 ``render`` 진입점에서 도달 가능한 것만 인정한다(gap 5). render
    진입점이 없으면 불충족이다.
    """
    names, _ = render_reachable(src)
    if names is None:
        return False
    if archetype == "EDIT_GRID":
        return has_editgrid_stack(names)
    return _has_page_chrome(names)


# 크롬 호출 검사를 면제하는 화면(USER 셸 기반 명문 예외 — 위 docstring 참조).
# 사유를 붙인 명시적 집합으로 선언한다(암묵 패턴 금지, gap 6).
CHROME_EXEMPT_REASONS: dict[str, str] = {
    "my_schedule": "USER user_app_shell 셸이 헤더 크롬 제공 — page_chrome 직접 호출 안 함",
}
CHROME_EXEMPT = set(CHROME_EXEMPT_REASONS)


def chrome_ok(name: str, src: str, archetype: str, sources_by_stem: dict[str, str]) -> bool:
    """유형 선언이 유효한 화면의 크롬 실호출 충족 여부(면제·위임 포함).

    위임은 **render 경로에서 도달 가능한** ``X.render(...)`` 대상만 인정한다(gap 5) —
    죽은 코드 속 가짜 위임 호출로는 통과하지 못한다.
    """
    if name in CHROME_EXEMPT:
        return True  # USER 셸이 헤더 크롬 제공 — page_chrome 직접 호출 면제.
    if chrome_own_ok(archetype, src):
        return True
    # 위임: render 도달 대상 화면이 규약(유효 유형 + 자기 크롬)을 준수하면 통과.
    _, deleg_targets = render_reachable(src)
    for target in deleg_targets:
        tsrc = sources_by_stem.get(target)
        if tsrc is None:
            continue
        t_arch = module_archetype(tsrc)
        if t_arch in scaffold.ARCHETYPES and chrome_own_ok(t_arch, tsrc):
            return True
    return False


# ===========================================================================
# 명시적 제외/발견 레지스트리 — 암묵 패턴이 아니라 사유가 붙은 선언(gap 6).
# ===========================================================================

INFRA_DIRS = {"master", "common"}          # views 하위 인프라 패키지(화면 아님).

# 명시적 비화면/인프라 제외 목록 — 각 항목에 사유를 단다(암묵 패턴 금지, gap 6).
# 여기 없는 top-level 모듈은 화면으로 간주되어 §0 검사를 받는다. 실제 화면을
# 은폐하지 않도록, 이 목록의 모듈이 SCREEN_ARCHETYPE 를 선언하면 (e) 가드가
# FAIL 시켜 표면화한다.
NON_SCREEN_REASONS: dict[str, str] = {
    "__init__": "패키지 초기화 모듈 — 화면 아님",
    "workspace": "화면 간 공유 근무표 위젯 — dispatch 로 직접 라우팅되지 않음(schedule_* 가 함수로 호출)",
    "login": "인증 게이트 — dispatch 이전 auth 단계에서 렌더되는 비업무 화면",
}
NON_SCREEN = set(NON_SCREEN_REASONS)


# ===========================================================================
# 화면 집합 발견 — route dispatch 연결(1차) + views/ 재귀 스캔(rglob 보강 그물).
# ===========================================================================

def route_import_map(app_src: str) -> dict[str, str]:
    """``app.py`` 의 정적 import 로 바인딩된 로컬 이름 → 점표기 모듈 경로(gap 7).

    - ``from pkg import name`` / ``from pkg import name as alias`` →
      ``alias(또는 name) : "pkg.name"``.
    - ``import a.b.c`` / ``import a.b as x`` → ``x : "a.b"`` (asname 있을 때).

    이 매핑으로 라우팅 이름을 파일 위치와 무관하게 실제 모듈 경로에 해소한다.
    상대 import(``from . import x``, ``level>0``)와 동적 import 는 추적하지 않는다.
    """
    tree = ast.parse(app_src)
    mapping: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for alias in node.names:
                local = alias.asname or alias.name
                mapping[local] = f"{node.module}.{alias.name}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    mapping[alias.asname] = alias.name
                else:
                    # `import a.b.c` 는 로컬 이름 `a` 로 바인딩(속성 접근으로 사용).
                    mapping[alias.name.split(".")[0]] = alias.name.split(".")[0]
    return mapping


def routed_screen_names(app_src: str) -> set[str]:
    """``app.py`` 에서 실제로 ``.render()`` 되는 라우팅 화면 로컬 이름 집합(gap 7).

    - ``_PAGES = { "...": module, ... }`` dict 리터럴의 값(import 된 모듈 Name).
    - ``mod.render(...)`` 직접 분기(dispatch 의 명시 branch, import 된 모듈 Name).

    import 된 이름만 후보로 삼는다(로컬 함수 등 오탐 배제). ``login`` 처럼 인증
    단계에서 렌더되는 이름도 여기 포함될 수 있으나, 발견 단계에서 명시적
    :data:`NON_SCREEN` 으로 제외한다.
    """
    tree = ast.parse(app_src)
    imported = set(route_import_map(app_src))
    routed: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "_PAGES" and isinstance(node.value, ast.Dict):
                    for v in node.value.values:
                        if isinstance(v, ast.Name) and v.id in imported:
                            routed.add(v.id)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            f = node.func
            if f.attr == "render" and isinstance(f.value, ast.Name) and f.value.id in imported:
                routed.add(f.value.id)
    return routed


def resolve_module_path(dotted: str | None) -> Path | None:
    """점표기 모듈 경로 → ROOT 아래 실존 파일 ``Path`` 또는 ``None``(gap 7).

    ``pkg.mod`` → ``ROOT/pkg/mod.py`` 우선, 없으면 ``ROOT/pkg/mod/__init__.py``.
    해소 불가하면 ``None`` 을 반환한다(발견 단계가 FAIL 로 표면화).
    """
    if not dotted:
        return None
    parts = dotted.split(".")
    cand = ROOT.joinpath(*parts).with_suffix(".py")
    if cand.exists():
        return cand
    pkg = ROOT.joinpath(*parts, "__init__.py")
    if pkg.exists():
        return pkg
    return None


def screen_label_for(parts: tuple[str, ...]) -> str | None:
    """``views`` 기준 상대 경로 조각으로 화면 라벨을 만들거나 제외 시 ``None``.

    인프라 패키지(``master``·``common``) 하위 전부와 비화면 모듈
    (:data:`NON_SCREEN`)은 제외한다. 그 외는 dotted 라벨(top-level 은 stem,
    하위 패키지는 ``pkg.mod``)을 반환한다 — 새 하위 패키지 화면
    (``views/xxx/new_page.py``)도 포함되어 우회 경로 1 을 차단한다.
    """
    if not parts:
        return None
    if parts[0] in INFRA_DIRS:
        return None
    if parts[-1] in NON_SCREEN:
        return None
    return ".".join(parts)


def _label_for_path(views_dir: Path, path: Path) -> str:
    """발견된 화면 파일의 라벨: views 내부면 dotted 상대(top-level 은 stem),
    views 외부면 ROOT 기준 dotted 경로."""
    try:
        rel = path.relative_to(views_dir)
        lbl = screen_label_for(rel.with_suffix("").parts)
        if lbl:
            return lbl
    except ValueError:
        pass
    rel2 = path.relative_to(ROOT)
    return ".".join(rel2.with_suffix("").parts)


def discover_screens() -> tuple[list[tuple[str, Path]], list[str]]:
    """화면 (label, path) 목록과 **미해소 라우팅 이름** 목록을 반환한다.

    1차 출처는 ``app.py`` 의 route dispatch(:func:`routed_screen_names`)이며, 각
    이름을 실제 import 문(:func:`route_import_map`)으로 모듈 파일에 해소한다 —
    파일 위치가 ``views/`` 밖이어도 발견된다(gap 7). 해소 불가한 라우팅 화면은
    조용히 건너뛰지 않고 ``unresolved`` 로 반환해 발견 단계가 FAIL 로 표면화한다.

    보강 그물로 ``views/**`` 를 rglob 재귀 스캔해, dispatch 에 아직 연결되지 않은
    하위 패키지 화면도 포함한다(우회 경로 1).
    """
    views_dir = ROOT / "views"
    found: dict[str, Path] = {}
    unresolved: list[str] = []

    # 1차: route dispatch 연결 화면 — 실제 import 로 모듈 파일에 해소(위치 무관).
    app_src = (ROOT / "app.py").read_text(encoding="utf-8")
    import_map = route_import_map(app_src)
    for name in routed_screen_names(app_src):
        if name in NON_SCREEN:
            continue  # 명시적 비화면 제외(login 등) — gap 6.
        path = resolve_module_path(import_map.get(name))
        if path is None:
            unresolved.append(name)  # 라우팅되는데 모듈 미해소 → 표면화(gap 7).
            continue
        found.setdefault(_label_for_path(views_dir, path), path)

    # 보강 그물: views/ 재귀 스캔(rglob) — 새 하위 패키지 화면도 포함.
    for path in views_dir.rglob("*.py"):
        rel = path.relative_to(views_dir)
        label = screen_label_for(rel.with_suffix("").parts)
        if label is None:
            continue
        found.setdefault(label, path)

    return sorted(found.items()), sorted(set(unresolved))


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
# (a) 발견된 모든 화면: 유효 SCREEN_ARCHETYPE 선언 + 크롬 실호출(render 경로)
# ===========================================================================
print("(a) 화면 발견(route dispatch+rglob) — 유형 선언(AST) + 크롬 render-path 실호출")
screens, unresolved = discover_screens()
sources_by_stem = {
    p.stem: p.read_text(encoding="utf-8")
    for p in (ROOT / "views").glob("*.py")
}
check("화면 집합 발견됨(route dispatch 연결 + rglob 재귀)", len(screens) > 0)
# gap 7: 라우팅되는데 모듈로 해소 안 되는 화면은 조용히 건너뛰지 않고 FAIL.
check(f"모든 라우팅 화면이 모듈 파일로 해소됨(미해소={unresolved})", not unresolved)

for label, path in screens:
    src = path.read_text(encoding="utf-8")
    arch = module_archetype(src)
    # ① 유형 선언(AST) — 주석/문자열이 아니라 실제 모듈 레벨 상수 할당
    check(f"{label}: SCREEN_ARCHETYPE 상수 할당(AST)", arch is not None)
    check(f"{label}: 유효 유형(값={arch!r})", arch in scaffold.ARCHETYPES)
    # ②③ 크롬 실호출(render 경로 도달·면제·위임·EDIT_GRID 스택 반영)
    if arch in scaffold.ARCHETYPES:
        stem = path.stem
        note = " [면제:USER셸]" if stem in CHROME_EXEMPT else ""
        check(
            f"{label}: 크롬 render-path 실호출 규약 충족{note}",
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
    "ARCHETYPES == DESIGN.md §0 5유형",
    scaffold.ARCHETYPES == ("EDIT_GRID", "READ_VIEW", "MATRIX_EDIT", "DASHBOARD", "FORM_ENTRY"),
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

# 양성 대조군: 온전한 EDIT_GRID 스택(모두 render 직접 호출)은 통과해야 한다.
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


# ===========================================================================
# (e) gap 5 — 크롬 호출이 render 경로 위에 있음을 증명(도달성). 죽은 코드 불인정.
# ===========================================================================
print("(e) gap 5 음성/양성 — 크롬 호출의 render-path 도달성")

# gap5-neg-1: 크롬 호출이 render 가 부르지 않는 헬퍼(죽은 코드)에만 있음 → 불충족.
BYPASS_DEADCODE_CHROME = (
    'SCREEN_ARCHETYPE = "READ_VIEW"\n'
    "from views.common import scaffold\n"
    "def render(user):\n"
    "    return None\n"                                   # render 는 아무것도 호출 안 함
    "def _unused(user):\n"
    "    scaffold.page_chrome_for('x', SCREEN_ARCHETYPE)\n"  # 도달 불가한 크롬 호출
)
check(
    "gap5: render 도달 불가한 크롬 호출(죽은 코드)은 불충족",
    not chrome_own_ok("READ_VIEW", BYPASS_DEADCODE_CHROME),
)

# gap5-neg-2: EDIT_GRID 그리드 호출이 죽은 헬퍼에만 있음 → 스택 불충족.
BYPASS_STACK_UNREACHABLE = (
    'SCREEN_ARCHETYPE = "EDIT_GRID"\n'
    "from views.master import master_screen_head, render_master_grid, master_action_bar\n"
    "def render(user):\n"
    "    master_screen_head('t', 'd')\n"
    "    master_action_bar(state)\n"
    "def _dead():\n"
    "    render_master_grid(spec, frame)\n"               # 그리드가 render 도달 불가
)
check(
    "gap5: EDIT_GRID 그리드 호출이 render 도달 불가면 스택 불충족",
    not chrome_own_ok("EDIT_GRID", BYPASS_STACK_UNREACHABLE),
)

# gap5-neg-3: render 진입점이 없으면(모듈 레벨 크롬 호출) render-path 로 인정 안 함.
BYPASS_NO_RENDER = (
    'SCREEN_ARCHETYPE = "READ_VIEW"\n'
    "from views.common import scaffold\n"
    "scaffold.page_chrome_for('x', 'READ_VIEW')\n"        # 모듈 레벨, render 정의 없음
)
check(
    "gap5: render() 진입점 부재 시 크롬 호출을 render-path 로 인정 안 함",
    not chrome_own_ok("READ_VIEW", BYPASS_NO_RENDER),
)

# gap5-neg-4: 위임 호출도 render 도달 불가(죽은 코드)면 위임 통과 안 됨.
BYPASS_DEADCODE_DELEGATE = (
    'SCREEN_ARCHETYPE = "EDIT_GRID"\n'
    "def render(user):\n"
    "    return None\n"                                   # 실제 render 는 위임 안 함
    "def _unused(user):\n"
    "    master_org.render(user)\n"                        # 죽은 코드 속 위임
)
check(
    "gap5: render 도달 불가한 위임 호출은 위임 통과 불가",
    not chrome_ok("fake", BYPASS_DEADCODE_DELEGATE, "EDIT_GRID", {"master_org": GOOD_EDITGRID}),
)

# gap5-pos-1: render→helper 로 전이 도달하는 크롬 호출은 충족(master_org 패턴 축약).
GOOD_HELPER_CHROME = (
    'SCREEN_ARCHETYPE = "READ_VIEW"\n'
    "from views.common import scaffold\n"
    "def render(user):\n"
    "    _body(user)\n"
    "def _body(user):\n"
    "    scaffold.page_chrome_for('x', SCREEN_ARCHETYPE)\n"
)
check(
    "대조군: render→helper 전이 도달 크롬 호출은 충족",
    chrome_own_ok("READ_VIEW", GOOD_HELPER_CHROME),
)

# gap5-pos-2: EDIT_GRID 헤더는 render 직접, 그리드+액션은 render 가 부르는 sheet 헬퍼.
#             (실제 master_org 구조: render→master_screen_head, render→_render_*_sheet
#              →render_master_grid/master_action_bar)
GOOD_EDITGRID_TRANSITIVE = (
    'SCREEN_ARCHETYPE = "EDIT_GRID"\n'
    "from views.master import master_screen_head, render_master_grid, master_action_bar\n"
    "def render(user):\n"
    "    master_screen_head('t', 'd')\n"
    "    _sheet()\n"
    "def _sheet():\n"
    "    render_master_grid(spec, frame)\n"
    "    master_action_bar(state)\n"
)
check(
    "대조군: EDIT_GRID 전이 스택(render→sheet 헬퍼)도 충족",
    chrome_own_ok("EDIT_GRID", GOOD_EDITGRID_TRANSITIVE),
)


# ===========================================================================
# (f) gap 6 — 비화면 제외는 사유 붙은 명시적 집합. 제외 모듈이 실화면이면 표면화.
# ===========================================================================
print("(f) gap 6 — 명시적 제외 집합 + 은폐된 실화면 가드")
check(
    "제외 목록은 사유가 붙은 명시적 집합(암묵 패턴 아님)",
    NON_SCREEN == {"__init__", "workspace", "login"}
    and all(NON_SCREEN_REASONS[m] for m in NON_SCREEN),
)
check(
    "면제 목록도 사유가 붙은 명시적 집합",
    CHROME_EXEMPT == {"my_schedule"} and all(CHROME_EXEMPT_REASONS[m] for m in CHROME_EXEMPT),
)
# 가드: 제외 top-level 모듈이 실제로 SCREEN_ARCHETYPE 를 선언하면(=은폐된 실화면)
# FAIL 로 표면화한다. 지금은 어떤 제외 모듈도 유형을 선언하지 않아야 한다.
for stem in sorted(NON_SCREEN):
    p = ROOT / "views" / f"{stem}.py"
    if not p.exists():
        continue
    arch = module_archetype(p.read_text(encoding="utf-8"))
    check(
        f"제외 모듈 views.{stem} 은 유형 미선언(은폐된 실화면 아님)",
        arch is None,
    )
# 음성: 제외 모듈이 유형을 선언하면 가드가 이를 은폐하지 않고 잡아냄을 검증.
HIDDEN_SCREEN = 'SCREEN_ARCHETYPE = "EDIT_GRID"\ndef render(user):\n    pass\n'
check(
    "gap6: 제외 모듈이 유형 선언 시 가드가 은폐 실화면으로 탐지",
    module_archetype(HIDDEN_SCREEN) == "EDIT_GRID",
)


# ===========================================================================
# (g) gap 7 — 발견은 route dispatch 로 구동. views/ 밖 화면 발견 + 미해소 표면화.
# ===========================================================================
print("(g) gap 7 — route dispatch 구동 발견 + views 밖 화면 + 미해소 표면화")

# gap7-pos-1: views 밖에서 라우팅되는 화면도 dispatch 기반으로 발견(모듈 경로 도출).
EXTERNAL_APP = (
    "from screens import external_page\n"
    "from views import dashboard\n"
    "_PAGES = {'ext': external_page, 'dash': dashboard}\n"
    "def dispatch(page, user):\n"
    "    _PAGES[page].render(user)\n"
)
_ext_map = route_import_map(EXTERNAL_APP)
_ext_routed = routed_screen_names(EXTERNAL_APP)
check(
    "gap7: views 밖 라우팅 화면도 dispatch 로 발견 + 모듈 경로 도출",
    "external_page" in _ext_routed and _ext_map.get("external_page") == "screens.external_page",
)

# gap7-pos-2: _PAGES 밖 직접 mod.render() 분기(dashboard/my_schedule)도 라우팅 포착.
DIRECT_DISPATCH_APP = (
    "from views import dashboard, my_schedule\n"
    "def dispatch(page, user):\n"
    "    if page == 'dashboard':\n"
    "        dashboard.render(user)\n"
    "    elif page == 'my_schedule':\n"
    "        my_schedule.render(user)\n"
)
check(
    "gap7: _PAGES 밖 직접 mod.render() 분기도 라우팅으로 포착",
    {"dashboard", "my_schedule"} <= routed_screen_names(DIRECT_DISPATCH_APP),
)

# gap7-neg-1: 해소 불가한 모듈 경로는 None → discover 가 unresolved 로 FAIL 표면화.
check(
    "gap7: 해소 불가한 라우팅 모듈 경로는 None(→ discover 가 FAIL 로 표면화)",
    resolve_module_path("no.such.module.zzz") is None,
)

# gap7-pos-3: 실존 모듈 경로는 해소됨(양성 대조군).
check(
    "대조군: 실존 모듈 경로는 해소됨(views.dashboard)",
    resolve_module_path("views.dashboard") is not None,
)

# gap7-pos-4: 실제 app.py 의 라우팅 화면 집합이 알려진 업무 화면을 모두 포함.
_APP_SRC = (ROOT / "app.py").read_text(encoding="utf-8")
check(
    "실제 app.py: 알려진 업무 화면이 route dispatch 로 발견됨",
    {"dashboard", "schedule_edit", "schedule_view", "master_users",
     "master_org", "master_work_types"} <= routed_screen_names(_APP_SRC),
)


# ===========================================================================
# (h) FORM_ENTRY — 5번째 §0 유형(단건 입력·제출 폼). 크롬 계약: 유형 선언 +
#     page_chrome/page_chrome_for 실호출(render 경로). EDIT_GRID 스택은 불필요.
# ===========================================================================
print("(h) FORM_ENTRY — 단건 폼 유형: 유형 선언 + 헤더 크롬 실호출(그리드 스택 불요)")

# 유효 유형 등록 확인(§0 표·scaffold.ARCHETYPES 정합).
check("FORM_ENTRY 는 유효 유형(scaffold.ARCHETYPES 등록)", "FORM_ENTRY" in scaffold.ARCHETYPES)

# 유형 상수 탐지(AST) — 주석이 아니라 실제 모듈 레벨 상수.
FORM_DECL = 'SCREEN_ARCHETYPE = "FORM_ENTRY"\ndef render(user):\n    pass\n'
check("FORM_ENTRY: 모듈 레벨 SCREEN_ARCHETYPE 상수 탐지(AST)", module_archetype(FORM_DECL) == "FORM_ENTRY")

# 양성: 온전한 FORM_ENTRY — render 경로에서 page_chrome_for 실호출 → 크롬 충족.
GOOD_FORM_ENTRY = (
    'SCREEN_ARCHETYPE = "FORM_ENTRY"\n'
    "from views.common import scaffold\n"
    "def render(user):\n"
    "    scaffold.page_chrome_for('near_miss_new', SCREEN_ARCHETYPE)\n"
    "    _form_body()\n"          # 라벨드 필드·첨부(시각 게이트)
    "    _submit_and_banner()\n"  # 제출 + 저장 결과 배너(시각 게이트)
    "def _form_body():\n"
    "    return None\n"
    "def _submit_and_banner():\n"
    "    return None\n"
)
check("대조군: 온전한 FORM_ENTRY(page_chrome_for 실호출)은 크롬 충족",
      chrome_own_ok("FORM_ENTRY", GOOD_FORM_ENTRY))

# 양성: FORM_ENTRY 는 EDIT_GRID 그리드 스택이 불필요 — 헤더 크롬만으로 충족.
FORM_NO_GRID = (
    'SCREEN_ARCHETYPE = "FORM_ENTRY"\n'
    "from views.common import scaffold\n"
    "def render(user):\n"
    "    scaffold.page_chrome('FORM_ENTRY', title='니어미스 신청')\n"
)
check("대조군: FORM_ENTRY 는 그리드/액션 스택 없이 헤더 크롬만으로 충족",
      chrome_own_ok("FORM_ENTRY", FORM_NO_GRID)
      and not has_editgrid_stack(render_reachable(FORM_NO_GRID)[0] or set()))

# 양성: 전체 경로(chrome_ok, 비면제 화면)도 통과.
check("대조군: FORM_ENTRY 전체 크롬 규약(chrome_ok, 비면제)도 충족",
      chrome_ok("near_miss_new", GOOD_FORM_ENTRY, "FORM_ENTRY", {}))

# 양성: render→helper 전이 도달 크롬 호출도 충족(간접 구성 허용).
FORM_TRANSITIVE = (
    'SCREEN_ARCHETYPE = "FORM_ENTRY"\n'
    "from views.common import scaffold\n"
    "def render(user):\n"
    "    _head(user)\n"
    "def _head(user):\n"
    "    scaffold.page_chrome_for('near_miss_new', SCREEN_ARCHETYPE)\n"
)
check("대조군: FORM_ENTRY render→helper 전이 크롬 호출도 충족",
      chrome_own_ok("FORM_ENTRY", FORM_TRANSITIVE))

# 음성: 크롬 호출이 아예 없으면(폼만 그림) 불충족.
FORM_NO_CHROME = (
    'SCREEN_ARCHETYPE = "FORM_ENTRY"\n'
    "def render(user):\n"
    "    st.text_input('사유')\n"      # 헤더 크롬 미호출
    "    st.button('제출')\n"
)
check("음성: FORM_ENTRY 헤더 크롬 미호출은 불충족",
      not chrome_own_ok("FORM_ENTRY", FORM_NO_CHROME))

# 음성: 크롬 호출이 render 도달 불가한 죽은 헬퍼에만 있으면 불충족(gap5 정합).
FORM_DEADCODE_CHROME = (
    'SCREEN_ARCHETYPE = "FORM_ENTRY"\n'
    "from views.common import scaffold\n"
    "def render(user):\n"
    "    return None\n"
    "def _unused(user):\n"
    "    scaffold.page_chrome_for('near_miss_new', SCREEN_ARCHETYPE)\n"
)
check("음성: FORM_ENTRY 크롬 호출이 render 도달 불가(죽은 코드)면 불충족",
      not chrome_own_ok("FORM_ENTRY", FORM_DEADCODE_CHROME))

# 음성: master_screen_head 만 부르고 page_chrome/page_chrome_for 미호출은 불충족
#       (FORM_ENTRY 계약은 공용 스캐폴드 크롬 API 실호출을 요구).
FORM_RAW_HEAD_ONLY = (
    'SCREEN_ARCHETYPE = "FORM_ENTRY"\n'
    "from views.master import master_screen_head\n"
    "def render(user):\n"
    "    master_screen_head('니어미스 신청', '단건 제출')\n"
)
check("음성: FORM_ENTRY 가 page_chrome 계열 대신 master_screen_head 만 호출하면 불충족",
      not chrome_own_ok("FORM_ENTRY", FORM_RAW_HEAD_ONLY))


print()
if FAIL:
    print(f"FAILED {len(FAIL)}: {FAIL}")
    sys.exit(1)
print(f"ALL PASSED ({PASS} checks)")
