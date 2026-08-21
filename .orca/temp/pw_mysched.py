"""Stage 12 내 근무표 달력 검증 — M/A 셸 1366 + USER 셸 390, 월 이동 1회."""
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(".orca/artifacts/claude-design-adopt/stage12-mysched")
OUT.mkdir(parents=True, exist_ok=True)
URL = "http://localhost:8547/"


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


def month_label(page):
    # 월 라벨은 components.v2 컴포넌트(iframe) 안의 .month-title
    for f in page.frames:
        try:
            el = f.query_selector(".month-title")
            if el: return (el.inner_text() or "").strip(), f
        except Exception: pass
    return None, None


def shift_prev(page):
    for f in page.frames:
        try:
            b = f.query_selector(".wheel-nav .previous")
            if b: b.click(); return True
        except Exception: pass
    return False


def measure_cal(page, tag):
    info = page.evaluate("""()=>{
      const g=document.querySelector('.my-calendar-grid');
      const days=[...document.querySelectorAll('.my-day')].filter(d=>!d.classList.contains('empty'));
      const duty=document.querySelector('.my-duty:not(.is-empty)');
      const wd=document.querySelector('.my-weekday');
      const emp=document.querySelector('.my-emp');
      const tot=document.querySelector('.my-total .val');
      return {cols: g?getComputedStyle(g).gridTemplateColumns.split(' ').length:0,
        dayCells: days.length,
        dutyBg: duty?getComputedStyle(duty).backgroundColor:null,
        dutyColor: duty?getComputedStyle(duty).color:null,
        dutyText: duty?(duty.textContent||'').trim():null,
        weekdayColor: wd?getComputedStyle(wd).color:null,
        empColor: emp?getComputedStyle(emp).color:null,
        totMono: tot?getComputedStyle(tot).fontFamily:null};}""")
    h = page.evaluate("()=>document.documentElement.scrollWidth-document.documentElement.clientWidth")
    log(f"{tag} calendar:", info, "| h_overflow:", h)


def main():
    with sync_playwright() as p:
        br = p.chromium.launch()

        # ===== M/A 셸 (MANAGER 1002) 1366 =====
        ctx1 = br.new_context(viewport={"width": 1366, "height": 900})
        pg = ctx1.new_page()
        login(pg, "1002")
        cat = btn(pg, "근무표")
        if cat: cat.click(); time.sleep(1.2)
        b = btn(pg, "내 근무표")
        if b: b.click(); time.sleep(3.5); pg.wait_for_load_state("networkidle"); time.sleep(2)
        m0, _ = month_label(pg)
        log("M/A month label:", m0)
        pg.screenshot(path=str(OUT / "mysched_ma_1366.png"), full_page=False)
        measure_cal(pg, "M/A")
        # 월 이동 1회(‹)
        if shift_prev(pg):
            time.sleep(3); pg.wait_for_load_state("networkidle"); time.sleep(2)
            m1, _ = month_label(pg)
            log("M/A month after prev:", m1, "(changed:", m0 != m1, ")")
            pg.screenshot(path=str(OUT / "mysched_ma_prev_1366.png"), full_page=False)
        ctx1.close()

        # ===== USER 셸 (USER 1003) 390 좁은 폭 =====
        ctx2 = br.new_context(viewport={"width": 390, "height": 844})
        pg2 = ctx2.new_page()
        login(pg2, "1003")
        b2 = btn(pg2, "내 근무표")
        if b2: b2.click(); time.sleep(3.5); pg2.wait_for_load_state("networkidle"); time.sleep(2)
        um0, _ = month_label(pg2)
        log("USER month label:", um0)
        pg2.screenshot(path=str(OUT / "mysched_user_390.png"), full_page=True)
        measure_cal(pg2, "USER-390")
        if shift_prev(pg2):
            time.sleep(3); pg2.wait_for_load_state("networkidle"); time.sleep(2)
            um1, _ = month_label(pg2)
            log("USER month after prev:", um1, "(changed:", um0 != um1, ")")
        ctx2.close()

        br.close(); log("DONE")


if __name__ == "__main__":
    main()
