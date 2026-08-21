"""Streamlit 내부 선택자 생존 검사 — 소스에서 뽑아 실렌더에서 센다.

왜 필요한가
-----------
Streamlit 은 마이너 버전에서 위젯의 내부 DOM 을 바꾼다. 1.59 는 ``selectbox``·
``text_input`` 을 BaseWeb 에서 react-aria 로 갈아치웠고, 그 순간
``div[data-baseweb="select"]`` 계열 규칙이 **문법은 멀쩡한 채 아무것도 매치하지
않는 상태**가 됐다(2026-08-21 실측). CSS 는 매치 0 을 오류로 알리지 않으므로
화면은 조용히 Streamlit 기본값으로 되돌아간다 — 실제로 조회조건 selectbox 가
테두리 ``#fbfaf8``(배경과 동색 = 무테)·radius 7px 로 남아 같은 줄 버튼
(``#cfc8bd``·6px)과 갈렸는데도 아무 검사도 울지 않았다.

`DESIGN.md` §7.2-10 이 "사람이 아니라 검사가 막아야 하는 종류"라고 적은 드리프트와
같은 부류다. 이 스크립트가 그 검사다.

무엇을 하는가
-------------
1. **정적 추출** — ``modules/``·``views/`` 의 ``<style>`` 블록에서 규칙 프렐류드를
   파싱해 개별 선택자로 쪼갠다. f-string 이스케이프(``{{``/``}}``)를 되돌리고
   ``{placeholder}`` 는 와일드카드로 치환한 뒤, Streamlit **내부** 훅
   (:data:`INTERNAL_HOOKS`)을 참조하는 선택자만 남긴다.
2. **실렌더 계수** — 앱에 로그인해 사이드바로 도달 가능한 모든 화면을 순회하며
   선택자별 ``querySelectorAll`` 매치 수를 세고 화면 간 최대값을 취한다.
3. **판정** — 매치 0 이면서 **같은 파일의 다른 선택자는 매치한** 경우만 ``DEAD``
   로 올린다. 파일 전체가 0 이면 그 화면이 렌더되지 않았다는 뜻이므로
   ``UNVERIFIED`` 로 분리한다 — 도달 불가 화면을 결함으로 오인하지 않기 위해서다.

사용법
------
sample 모드 앱을 먼저 띄운다(``.claude/launch.json`` 의 ``workops-sample-verify``)::

    python scripts/check_streamlit_selectors.py
    python scripts/check_streamlit_selectors.py --static-only    # 브라우저 없이 목록만
    python scripts/check_streamlit_selectors.py --url http://localhost:8510 --emp 1001

엔진 훅(:data:`ENGINE_HOOKS`) 선택자가 죽어 있으면 exit 1.
``--strict`` 는 testid 훅까지 게이트에 넣는다.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import time
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = ("modules", "views")

#: **엔진 훅** — 위젯을 구현한 UI 라이브러리가 그대로 새는 지점이라 Streamlit 이
#: 라이브러리를 갈아치우면 통째로 사라진다. 1.59 의 BaseWeb → react-aria 전환이
#: 정확히 이 부류였다. 기본 게이트는 여기에만 건다.
ENGINE_HOOKS = ("data-baseweb", "react-aria", "st-emotion")

#: **testid 훅** — Streamlit 이 비교적 안정적으로 유지하는 계약이다. 죽으면 보고하되
#: 조건부 렌더(popover 열림·expander 펼침 등)로 0 이 나오는 경우가 많아 기본 게이트에서
#: 뺀다. ``--strict`` 로 함께 게이트할 수 있다.
TESTID_HOOK = 'data-testid="st'

INTERNAL_HOOKS = ENGINE_HOOKS + (TESTID_HOOK,)

#: 의도적으로 남긴 선택자 — 매치 0 이어도 실패로 올리지 않는다. 사유를 반드시 적는다.
ALLOWLIST: dict[str, str] = {
    # multiselect 는 1.59 기준 아직 BaseWeb 이지만 expander 안에 있어 화면에 따라
    # 렌더되지 않는다(사용자 관리 권한 편집). 죽은 것이 아니라 조건부 렌더다.
    'section[data-testid="stMain"] div[data-baseweb="select"] > div':
        "multiselect(BaseWeb 잔존) — expander 열림 상태에서만 렌더",
    '[class*="st-key-erpcond_"] [data-baseweb="select"] div':
        "조회조건에 multiselect 가 놓일 때를 위한 예비 — 현재 화면엔 없음",
    # near_miss_submit 이 주석으로 명시한 버전 전이 보험.
    '[class*="st-key-nmrow_"] div[data-baseweb="select"] > div':
        "버전 전이 보험(주석 명시) — react-aria 선택자가 같은 규칙에 함께 있음",
    '[class*="st-key-nm_impr_flt_"] div[data-baseweb="select"] > div':
        "버전 전이 보험 — react-aria 선택자가 같은 규칙에 함께 있음",
    '[class*="st-key-nm_impr_assignee_"] div[data-baseweb="select"] > div':
        "버전 전이 보험 — react-aria 선택자가 같은 규칙에 함께 있음",
    '[class*="st-key-nm_impr_confirmer_"] div[data-baseweb="select"] > div':
        "버전 전이 보험 — react-aria 선택자가 같은 규칙에 함께 있음",
    '[class*="st-key-work_request_handle_"] div[data-baseweb="select"] > div':
        "버전 전이 보험 — react-aria 선택자가 같은 규칙에 함께 있음",
    '[class*="st-key-wrh_"] div[data-baseweb="select"] > div':
        "버전 전이 보험 — react-aria 선택자가 같은 규칙에 함께 있음",
    '[class*="st-key-work_request_my_"] div[data-baseweb="select"] > div':
        "버전 전이 보험 — react-aria 선택자가 같은 규칙에 함께 있음",
}

_STYLE_RE = re.compile(r"<style>(.*?)</style>", re.S)
_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)
_PLACEHOLDER_RE = re.compile(r"\{[A-Za-z_][A-Za-z0-9_\[\]'\"\.]*\}")


def extract_selectors(path: Path) -> list[str]:
    """한 파일의 ``<style>`` 블록에서 Streamlit 내부 훅을 쓰는 선택자를 뽑는다."""
    try:
        src = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    found: list[str] = []
    for block in _STYLE_RE.findall(src):
        css = _COMMENT_RE.sub(" ", block)
        # f-string 이스케이프 복원. 순서 주의 — {{ 를 먼저 풀면 placeholder 와 섞인다.
        css = _PLACEHOLDER_RE.sub("PLACEHOLDER", css)
        css = css.replace("{{", "\x01").replace("}}", "\x02")
        css = css.replace("{", "\x01").replace("}", "\x02")
        css = css.replace("\x01", "{").replace("\x02", "}")

        depth = 0
        prelude: list[str] = []
        for ch in css:
            if ch == "{":
                if depth == 0:
                    found.extend(_split_prelude("".join(prelude)))
                prelude = []
                depth += 1
            elif ch == "}":
                depth = max(0, depth - 1)
                prelude = []
            elif depth == 0:
                prelude.append(ch)
    return found


def _split_prelude(prelude: str) -> list[str]:
    """규칙 프렐류드를 개별 선택자로 쪼개고 내부 훅을 쓰는 것만 남긴다."""
    out = []
    for raw in prelude.split(","):
        sel = " ".join(raw.split())
        if not sel or sel.startswith("@") or "PLACEHOLDER" in sel:
            continue
        if not any(h in sel for h in INTERNAL_HOOKS):
            continue
        # <style> 태그가 짝이 안 맞는 파일에서 파이썬 코드가 프렐류드로 딸려온다.
        # CSS 선택자에 나타날 수 없는 토큰이 있으면 파싱 실패로 보고 버린다.
        if len(sel) > 160 or any(t in sel for t in (";", '"""', "def ", "return ", "# ")):
            continue
        # :hover/:focus-within 등 상태는 정적 DOM 에서 매치되지 않으므로 벗긴다.
        base = re.sub(r"::?[a-z-]+(\([^)]*\))?", "", sel).strip()
        if base and any(h in base for h in INTERNAL_HOOKS):
            out.append(base)
    return out


def collect() -> dict[str, set[str]]:
    """선택자 → 그 선택자를 쓰는 소스 파일 집합."""
    table: dict[str, set[str]] = {}
    for d in SCAN_DIRS:
        for path in sorted((ROOT / d).rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            for sel in extract_selectors(path):
                table.setdefault(sel, set()).add(rel)
    return table


# ---------------------------------------------------------------- 실렌더 계수
CENSUS_JS = (
    "(sels)=>{const o={};for(const s of sels){"
    "try{o[s]=document.querySelectorAll(s).length}catch(e){o[s]=-1}}return o}"
)


def census_live(url: str, emp: str, selectors: list[str], verbose: bool) -> dict[str, int]:
    from playwright.sync_api import sync_playwright

    best = {s: 0 for s in selectors}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_selector('[data-testid="stTextInput"] input', timeout=90_000)
        time.sleep(1.5)
        boxes = page.query_selector_all('[data-testid="stTextInput"] input')
        boxes[0].fill(emp)
        boxes[min(1, len(boxes) - 1)].fill(emp)
        boxes[min(1, len(boxes) - 1)].press("Enter")
        for _ in range(60):
            time.sleep(1)
            if "사번과 비밀번호" not in page.inner_text("body"):
                break
        else:
            raise SystemExit(f"로그인 실패 — 사번 {emp} 로 진입하지 못했다.")

        def absorb() -> None:
            for sel, n in page.evaluate(CENSUS_JS, selectors).items():
                if n == -1:
                    raise SystemExit(f"선택자 문법 오류: {sel}")
                best[sel] = max(best[sel], n)

        absorb()
        seen: set[str] = set()
        for _ in range(4):
            labels = []
            for el in page.query_selector_all(
                    'section[data-testid="stSidebar"] .stButton > button'):
                text = (el.inner_text() or "").strip().replace("\n", " ")
                if text and text != "로그아웃":
                    labels.append(text)
            fresh = [l for l in labels if l not in seen]
            if not fresh:
                break
            for label in fresh:
                seen.add(label)
                btn = page.query_selector(
                    f'section[data-testid="stSidebar"] .stButton > button:has-text("{label}")')
                if not btn:
                    continue
                try:
                    btn.click()
                except Exception:  # noqa: BLE001 — 메뉴가 재렌더로 사라진 경우
                    continue
                time.sleep(2.8)
                absorb()
                if verbose:
                    print(f"  방문: {label}", flush=True)
        browser.close()
    return best


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default="http://localhost:8510")
    ap.add_argument("--emp", default="1001")
    ap.add_argument("--static-only", action="store_true")
    ap.add_argument("--strict", action="store_true",
                    help="testid 훅 선택자까지 게이트에 포함한다(조건부 렌더 오탐 다수).")
    ap.add_argument("--json", dest="as_json", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    table = collect()
    selectors = sorted(table)
    print(f"정적 추출: Streamlit 내부 선택자 {len(selectors)}개 "
          f"({len({f for fs in table.values() for f in fs})}개 파일)")
    if args.static_only:
        for sel in selectors:
            print(f"  {sel}\n      ← {', '.join(sorted(table[sel]))}")
        return 0

    counts = census_live(args.url, args.emp, selectors, args.verbose)

    # 파일이 실제로 렌더됐는지: 그 파일의 선택자 중 하나라도 매치했으면 렌더된 것.
    rendered = {f for sel, fs in table.items() if counts[sel] > 0 for f in fs}

    dead, unverified, allowed = [], [], []
    is_engine = lambda x: any(h in x for h in ENGINE_HOOKS)  # noqa: E731
    for sel in selectors:
        if counts[sel] > 0:
            continue
        if sel in ALLOWLIST:
            allowed.append(sel)
        elif table[sel] <= rendered:
            dead.append(sel)
        else:
            unverified.append(sel)

    if args.as_json:
        print(json.dumps({"counts": counts, "dead": dead, "unverified": unverified,
                          "allowed": allowed}, indent=1, ensure_ascii=False))
    else:
        live = len(selectors) - len(dead) - len(unverified) - len(allowed)
        print(f"\nlive {live} · DEAD {len(dead)} · "
              f"UNVERIFIED {len(unverified)} · allowlist {len(allowed)}")
        if dead:
            print("\n[DEAD] 렌더된 파일에 있는데 아무것도 매치하지 않는다:")
            for sel in dead:
                kind = "엔진" if is_engine(sel) else "testid"
                print(f"  [{kind}] {sel}\n      ← {', '.join(sorted(table[sel]))}")
        if unverified:
            print("\n[UNVERIFIED] 해당 화면이 렌더되지 않아 판정 불가:")
            for sel in unverified:
                print(f"  {sel}\n      ← {', '.join(sorted(table[sel]))}")

    gated = dead if args.strict else [s for s in dead if is_engine(s)]
    if gated:
        print(f"\nFAIL — 게이트 대상 죽은 선택자 {len(gated)}개"
              f"{'' if args.strict else ' (엔진 훅만; 전체는 --strict)'}. "
              f"현재 DOM 으로 다시 잡거나 의도적 잔존이면 ALLOWLIST 에 사유와 함께 등록한다.")
        return 1
    print(f"\nPASS — 엔진 훅({'/'.join(ENGINE_HOOKS)}) 기준 죽은 선택자 없음."
          + (f" (testid 훅 {len(dead)}개는 보고만)" if dead else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
