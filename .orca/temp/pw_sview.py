"""Stage 13 월간 근무표 §1-C 읽기 검증 — M/A 1366+900, USER 390, sticky·h_overflow."""
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(".orca/artifacts/claude-design-adopt/stage13-monthly")
OUT.mkdir(parents=True, exist_ok=True)
URL = "http://localhost:8549/"


def log(*a): print(*a, flush=True)


def btn(page, text):
    for b in page.get_by_role("button").all():
        try:
            if text in (b.inner_text() or ""): return b
        except Exception: pass
    return None


def login(page, emp):
    page.goto(URL, wait_until="networkidle"); time.sleep(2)
    page.get_by_role("textbox").first.fill(emp)
    page.get_by_role("textbox").first.press("Enter")
    time.sleep(3); page.wait_for_load_state("networkidle"); time.sleep(1.5)


def grid_frame(page, tries=20):
    for _ in range(tries):
        for el in page.query_selector_all("iframe"):
            try:
                cf = el.content_frame()
                if cf and cf.query_selector(".ag-cell"): return cf
            except Exception: pass
        time.sleep(1)
    return None


def open_monthly_ma(page):
    cat = btn(page, "근무표")
    if cat: cat.click(); time.sleep(1.2)
    b = btn(page, "월간 근무표")
    if b: b.click(); time.sleep(3); page.wait_for_load_state("networkidle"); time.sleep(1.5)
    go = page.query_selector('div[class*="st-key-schedule_view_go"] button')
    if go: go.click(); time.sleep(3.5); page.wait_for_load_state("networkidle"); time.sleep(2.5)


def measure(page, tag):
    fr = grid_frame(page)
    info = {"grid": False}
    if fr:
        cell = fr.query_selector('.ag-cell')
        pinned = fr.query_selector('.ag-pinned-left-cols-container')
        pinnedCells = fr.evaluate("()=>document.querySelectorAll('.ag-pinned-left-cols-container .ag-cell').length")
        cellFs = fr.evaluate("el=>getComputedStyle(el).fontSize", cell) if cell else None
        dutyBg = None
        for c in fr.query_selector_all('.ag-cell'):
            bg = fr.evaluate("el=>getComputedStyle(el).backgroundColor", c)
            if bg and bg not in ("rgba(0, 0, 0, 0)", "transparent") and "255, 255, 255" not in bg:
                dutyBg = bg; break
        info = {"grid": True, "cellFs": cellFs, "pinnedLeft": pinned is not None,
                "pinnedCells": pinnedCells, "dutyTintBg": dutyBg}
    # 흰 컨테이너
    wrap = page.evaluate("""()=>{const w=document.querySelector('.st-key-sv_gridwrap [data-testid="stCustomComponentV1"]');
      if(!w)return null;const s=getComputedStyle(w);return {border:s.borderTopWidth+' '+s.borderTopColor,
      radius:s.borderTopLeftRadius, bg:s.backgroundColor};}""")
    h = page.evaluate("()=>document.documentElement.scrollWidth-document.documentElement.clientWidth")
    log(f"{tag}:", info, "| container:", wrap, "| h_overflow:", h)


def main():
    with sync_playwright() as p:
        br = p.chromium.launch()

        # ===== M/A 셸 (ADMIN 1001) 1366 =====
        ctx1 = br.new_context(viewport={"width": 1366, "height": 900})
        pg = ctx1.new_page()
        login(pg, "1001")
        open_monthly_ma(pg)
        pg.screenshot(path=str(OUT / "monthly_ma_1366.png"), full_page=False)
        log("captured M/A 1366")
        measure(pg, "M/A-1366")
        # 900 폭
        pg.set_viewport_size({"width": 900, "height": 900}); time.sleep(2)
        pg.screenshot(path=str(OUT / "monthly_ma_900.png"), full_page=False)
        measure(pg, "M/A-900")
        ctx1.close()

        # ===== USER variant (USER 1003) =====
        ctx2 = br.new_context(viewport={"width": 900, "height": 900})
        pg2 = ctx2.new_page()
        login(pg2, "1003")
        b = btn(pg2, "월간 근무표")
        if b: b.click(); time.sleep(3); pg2.wait_for_load_state("networkidle"); time.sleep(1.5)
        go = pg2.query_selector('div[class*="st-key-schedule_view_go"] button')
        if go: go.click(); time.sleep(3.5); pg2.wait_for_load_state("networkidle"); time.sleep(2.5)
        pg2.screenshot(path=str(OUT / "monthly_user_900.png"), full_page=True)
        log("captured USER 900")
        measure(pg2, "USER-900")
        ctx2.close()

        br.close(); log("DONE")


if __name__ == "__main__":
    main()
