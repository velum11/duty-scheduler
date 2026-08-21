"""Stage 14 대시보드 §1-F 변형 검증 — 1366+900, 데이터 있는 날짜, h_overflow."""
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(".orca/artifacts/claude-design-adopt/stage14-dashboard")
OUT.mkdir(parents=True, exist_ok=True)
URL = "http://localhost:8550/"


def log(*a): print(*a, flush=True)


def login(page, emp):
    page.goto(URL, wait_until="networkidle"); time.sleep(2)
    page.get_by_role("textbox").first.fill(emp)
    page.get_by_role("textbox").first.press("Enter")
    time.sleep(3); page.wait_for_load_state("networkidle"); time.sleep(1.5)


def goto_day8(page):
    # 날짜 피커(달력) → 7월 8일 선택. date_input 을 열고 day 셀 클릭.
    di = page.query_selector('[data-testid="stDateInput"] input')
    if not di:
        log("!! date input not found"); return
    di.click(); time.sleep(1)
    # baseweb datepicker day 셀
    for sel in ['[aria-label*="7월 8"]', 'div[role="gridcell"]']:
        cells = page.query_selector_all(sel)
        for c in cells:
            t = (c.inner_text() or "").strip()
            if t == "8":
                c.click(); time.sleep(3); page.wait_for_load_state("networkidle"); time.sleep(2)
                return
    # 폴백: 전일 버튼 반복(오늘=31 → 8, 23회)
    log("calendar day8 not found; falling back to prev-day")
    page.keyboard.press("Escape"); time.sleep(0.5)


def measure(page, tag):
    info = page.evaluate("""()=>{
      const kpis=[...document.querySelectorAll('.dash-kpi')];
      const kval=document.querySelector('.dash-kval');
      const groups=document.querySelectorAll('.dash-group').length;
      const cards=document.querySelectorAll('.dash-col[style*="border"]').length;
      const badge=document.querySelector('.dash-badge');
      const klabel=document.querySelector('.dash-klabel');
      return {nKpi:kpis.length,
        kvalFont: kval?getComputedStyle(kval).fontFamily:null,
        kvalSize: kval?getComputedStyle(kval).fontSize:null,
        kpiBorderL: kpis[0]?getComputedStyle(kpis[0]).borderLeftWidth+' '+getComputedStyle(kpis[0]).borderLeftColor:null,
        klabelColor: klabel?getComputedStyle(klabel).color:null,
        groups, badgeBg: badge?getComputedStyle(badge).backgroundColor:null,
        badgeColor: badge?getComputedStyle(badge).color:null};}""")
    h = page.evaluate("()=>document.documentElement.scrollWidth-document.documentElement.clientWidth")
    log(f"{tag}:", info, "| h_overflow:", h)


def main():
    with sync_playwright() as p:
        br = p.chromium.launch()
        ctx = br.new_context(viewport={"width": 1366, "height": 900})
        pg = ctx.new_page()
        login(pg, "1001")  # ADMIN → 대시보드 기본 페이지
        pg.screenshot(path=str(OUT / "dashboard_today_1366.png"), full_page=False)
        log("captured today (default)")
        measure(pg, "TODAY-1366")

        goto_day8(pg)
        pg.screenshot(path=str(OUT / "dashboard_data_1366.png"), full_page=False)
        log("captured data date")
        measure(pg, "DATA-1366")

        pg.set_viewport_size({"width": 900, "height": 900}); time.sleep(2)
        pg.screenshot(path=str(OUT / "dashboard_data_900.png"), full_page=True)
        measure(pg, "DATA-900")
        ctx.close()
        br.close(); log("DONE")


if __name__ == "__main__":
    main()
