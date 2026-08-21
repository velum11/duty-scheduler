"""Stage 9 아차사고 분석 §1-F — seed diverse-status data, then capture 1366+900."""
import sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(".orca/artifacts/claude-design-adopt/stage9-stats")
OUT.mkdir(parents=True, exist_ok=True)
URL = "http://localhost:8535/"

REPORTS = [
    ("원료실 계획서 부착 중 미끄러짐", "미끄러짐"),
    ("스태커 운반 중 근접 충돌", "부딪힘"),
    ("지게차 후진 접근", "부딪힘"),
    ("배관 용접 중 화상 위험", "화상"),
    ("점검 발판 추락 위험", "추락"),
]


def log(*a):
    print(*a, flush=True)


def btn(page, text):
    for b in page.get_by_role("button").all():
        try:
            if text in (b.inner_text() or ""):
                return b
        except Exception:
            pass
    return None


def fill_ph(page, ph, val):
    el = page.locator(f"[placeholder='{ph}']").first
    el.fill(val)


def nav_to(page, label):
    b = btn(page, label)
    if b is None:
        cat = btn(page, "아차사고 관리")
        if cat:
            cat.click(); time.sleep(1.2)
        b = btn(page, label)
    if b is None:
        log("!! nav not found:", label); return False
    b.click(); time.sleep(3.5)
    page.wait_for_load_state("networkidle"); time.sleep(1)
    return True


def submit_one(page, work, cause):
    fill_ph(page, "예: 3라인 컨베이어 벨트 점검", work)
    fill_ph(page, "원인을 구체적으로", f"{work} — 원인 상세")
    fill_ph(page, "무슨 일이 있었는지(아차사고 상황)를 구체적으로 적어 주세요", f"{work} 상황 서술.")
    fill_ph(page, "어떤 작업을 하고 있었는지", f"{work} 작업 서술.")
    fill_ph(page, "현장 상황 · 주변 환경", f"{work} 현장 서술.")
    fill_ph(page, "재발을 막기 위한 제안 대책", f"{work} 예방 대책.")
    # cause selectbox
    combos = page.get_by_role("combobox").all()
    if combos:
        combos[0].click(); time.sleep(0.6)
        opt = None
        for o in page.get_by_role("option").all():
            if cause in (o.inner_text() or ""):
                opt = o; break
        if opt:
            opt.click(); time.sleep(0.5)
        else:
            log("  !! cause option not found:", cause)
            page.keyboard.press("Escape")
    time.sleep(0.4)
    sb = btn(page, "제안서 제출")
    sb.click(); time.sleep(2.5)
    page.wait_for_load_state("networkidle"); time.sleep(0.8)


def main():
    with sync_playwright() as p:
        br = p.chromium.launch()
        pg = br.new_page(viewport={"width": 1366, "height": 900})
        pg.goto(URL, wait_until="networkidle"); time.sleep(2)
        pg.get_by_role("textbox").first.fill("1001")
        pg.get_by_role("textbox").first.press("Enter")
        time.sleep(3); pg.wait_for_load_state("networkidle"); time.sleep(1)

        # ---- seed submissions ----
        if not nav_to(pg, "아차사고 등록"):
            pg.screenshot(path=str(OUT / "nav_fail.png")); br.close(); sys.exit(2)
        for i, (work, cause) in enumerate(REPORTS):
            submit_one(pg, work, cause)
            log(f"submitted {i+1}/{len(REPORTS)}: {work}")
            again = btn(pg, "새 아차사고 등록") or btn(pg, "새 등록") or btn(pg, "등록 계속")
            if again and i < len(REPORTS) - 1:
                again.click(); time.sleep(2.5); pg.wait_for_load_state("networkidle"); time.sleep(0.8)
            elif i < len(REPORTS) - 1:
                nav_to(pg, "아차사고 등록")

        # ---- transitions for status diversity ----
        if nav_to(pg, "평가 관리"):
            # evaluate first case -> EVALUATED (grade B)
            gb = btn(pg, "B")
            if gb:
                gb.click(); time.sleep(1.5)
            ev = btn(pg, "평가확정")
            if ev and not ev.is_disabled():
                ev.click(); time.sleep(2.5); pg.wait_for_load_state("networkidle"); time.sleep(1)
                log("평가확정 done")
            # 검토착수 on next -> IN_REVIEW
            rv = btn(pg, "검토착수")
            if rv and not rv.is_disabled():
                rv.click(); time.sleep(2.5); pg.wait_for_load_state("networkidle"); time.sleep(1)
                log("검토착수 done")

        # ---- capture stats ----
        if not nav_to(pg, "아차사고 분석"):
            br.close(); sys.exit(3)
        time.sleep(1)
        pg.screenshot(path=str(OUT / "stats_default_1366.png"), full_page=False)
        pg.screenshot(path=str(OUT / "stats_default_full.png"), full_page=True)
        log("captured stats 1366")

        h_over = pg.evaluate(
            "() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
        log("PAGE h_overflow(px):", h_over)
        kval = pg.query_selector(".nmf-kval")
        if kval:
            fs = pg.evaluate("el => getComputedStyle(el).fontSize", kval)
            ff = pg.evaluate("el => getComputedStyle(el).fontFamily", kval)
            log("KPI value font-size:", fs, "family:", ff)
            log("KPI value style attr:", kval.get_attribute("style"))
        rlabel = pg.query_selector(".nmf-rlabel")
        if rlabel:
            col = pg.evaluate("el => getComputedStyle(el).color", rlabel)
            log("chart row-label color:", col)
        meta = pg.query_selector(".nmf-bmeta")
        if meta:
            log("chart meta color:", pg.evaluate("el => getComputedStyle(el).color", meta))
        nkpi = len(pg.query_selector_all(".nmf-kpi"))
        nblock = len(pg.query_selector_all(".nmf-block"))
        log("KPI tiles:", nkpi, "chart blocks:", nblock)

        # 900px
        pg.set_viewport_size({"width": 900, "height": 900}); time.sleep(1.5)
        pg.screenshot(path=str(OUT / "stats_900.png"), full_page=True)
        h900 = pg.evaluate(
            "() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
        log("PAGE h_overflow@900(px):", h900)

        br.close(); log("DONE")


if __name__ == "__main__":
    main()
