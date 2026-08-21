"""Stage 8 근무형태 관리 §1-E capture — default + dirty, 1366x900. sample mode :8531."""
import sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(".orca/artifacts/claude-design-adopt/stage8-worktypes")
OUT.mkdir(parents=True, exist_ok=True)
URL = "http://localhost:8532/"


def log(*a):
    print(*a, flush=True)


def find_button(page, text):
    for b in page.get_by_role("button").all():
        try:
            if text in (b.inner_text() or ""):
                return b
        except Exception:
            pass
    return None


def main():
    with sync_playwright() as p:
        br = p.chromium.launch()
        pg = br.new_page(viewport={"width": 1366, "height": 900})
        pg.goto(URL, wait_until="networkidle")
        time.sleep(2)

        # ---- login 사번 1001 (sample admin) ----
        inp = pg.get_by_role("textbox").first
        inp.fill("1001")
        inp.press("Enter")
        time.sleep(3)
        pg.wait_for_load_state("networkidle")
        time.sleep(1)

        # ---- sidebar nav: expand 기준정보 → 근무형태 관리 ----
        cat = find_button(pg, "기준정보")
        if cat:
            cat.click()
            time.sleep(1.5)
        btn = find_button(pg, "근무형태")
        if btn is None:
            log("!! 근무형태 nav button not found; buttons:")
            for b in pg.get_by_role("button").all()[:40]:
                log("   -", (b.inner_text() or "").replace("\n", " ")[:40])
            pg.screenshot(path=str(OUT / "nav_fail.png"))
            br.close(); sys.exit(2)
        btn.click()
        time.sleep(4)
        pg.wait_for_load_state("networkidle")
        time.sleep(2)

        pg.screenshot(path=str(OUT / "worktypes_default_1366.png"), full_page=False)
        pg.screenshot(path=str(OUT / "worktypes_default_full.png"), full_page=True)
        log("captured default")

        # ---- body font measure (grid cell) ----
        try:
            frame = None
            for f in pg.frames:
                if f.query_selector(".ag-root"):
                    frame = f; break
            if frame:
                cell = frame.query_selector('.ag-center-cols-container .ag-row .ag-cell')
                if cell:
                    fs = frame.evaluate(
                        "el => getComputedStyle(el).fontSize", cell)
                    ff = frame.evaluate(
                        "el => getComputedStyle(el).fontFamily", cell)
                    log("GRID_CELL font-size:", fs, "family:", ff)
                rh = frame.evaluate(
                    "() => { const r=document.querySelector('.ag-row'); "
                    "return r ? getComputedStyle(r).height : null; }")
                log("GRID_ROW height:", rh)
            else:
                log("!! ag-root frame not found")
        except Exception as e:
            log("font-measure error:", e)

        # ---- page horizontal overflow ----
        h_over = pg.evaluate(
            "() => document.documentElement.scrollWidth - "
            "document.documentElement.clientWidth")
        log("PAGE h_overflow(px):", h_over)

        # ---- dirty: click 행 추가 ----
        add = find_button(pg, "행 추가")
        if add:
            add.click()
            time.sleep(3)
            pg.wait_for_load_state("networkidle")
            time.sleep(1)
            pg.screenshot(path=str(OUT / "worktypes_dirty_1366.png"), full_page=False)
            log("captured dirty (행 추가)")
        else:
            log("!! 행 추가 button not found")

        # ---- 900px width variant ----
        pg.set_viewport_size({"width": 900, "height": 900})
        time.sleep(2)
        pg.screenshot(path=str(OUT / "worktypes_900.png"), full_page=False)
        h_over900 = pg.evaluate(
            "() => document.documentElement.scrollWidth - "
            "document.documentElement.clientWidth")
        log("PAGE h_overflow@900(px):", h_over900)

        br.close()
        log("DONE")


if __name__ == "__main__":
    main()
