"""출력 기능 검증 — 인쇄 아이콘 활성/음영·PDF 다운로드(상세 버튼·헤더 아이콘)."""
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(".orca/artifacts/claude-design-adopt/print")
OUT.mkdir(parents=True, exist_ok=True)
URL = "http://localhost:8562/"
REPORTS = [("원료실 미끄러짐", "미끄러짐"), ("스태커 충돌", "부딪힘"), ("배관 화상 위험", "화상")]


def log(*a): print(*a, flush=True)


def btn(p, t):
    for b in p.get_by_role("button").all():
        try:
            if t in (b.inner_text() or ""): return b
        except Exception: pass
    return None


def fill_ph(p, ph, v): p.locator(f"[placeholder='{ph}']").first.fill(v)


def nav_to(page, label):
    b = btn(page, label)
    if b is None:
        c = btn(page, "아차사고 관리")
        if c: c.click(); time.sleep(1.1)
        b = btn(page, label)
    if b is None: log("!! nav", label); return False
    b.click(); time.sleep(3.5); page.wait_for_load_state("networkidle"); time.sleep(1.5)
    return True


def submit_one(page, work, cause):
    fill_ph(page, "예: 3라인 컨베이어 벨트 점검", work)
    fill_ph(page, "원인을 구체적으로", f"{work} 원인 상세")
    fill_ph(page, "무슨 일이 있었는지(아차사고 상황)를 구체적으로 적어 주세요", f"{work} 상황 서술입니다.")
    fill_ph(page, "어떤 작업을 하고 있었는지", f"{work} 작업 서술.")
    fill_ph(page, "현장 상황 · 주변 환경", f"{work} 현장 서술.")
    fill_ph(page, "재발을 막기 위한 제안 대책", f"{work} 예방 대책.")
    combos = page.get_by_role("combobox").all()
    if combos:
        combos[0].click(); time.sleep(0.6)
        for o in page.get_by_role("option").all():
            if cause in (o.inner_text() or ""): o.click(); break
        time.sleep(0.4)
    sb = btn(page, "제안서 제출")
    if sb: sb.click(); time.sleep(2.5); page.wait_for_load_state("networkidle"); time.sleep(0.8)


def print_state(page):
    return page.evaluate("""()=>{
      const w=document.querySelector('.st-key-hdr_ic_on_print, .st-key-hdr_ic_off_print');
      const b=w?w.querySelector('button'):null;
      return b?{slot:(w.className.match(/hdr_ic_(on|off)_/)||[])[1], disabled:b.disabled}:null;}""")


def gframe(page, tries=20):
    for _ in range(tries):
        for el in page.query_selector_all("iframe"):
            try:
                cf = el.content_frame()
                if cf and cf.query_selector(".ag-cell"): return cf
            except Exception: pass
        time.sleep(1)
    return None


def main():
    with sync_playwright() as p:
        br = p.chromium.launch()
        ctx = br.new_context(viewport={"width": 1366, "height": 900}, accept_downloads=True)
        pg = ctx.new_page()
        pg.goto(URL, wait_until="networkidle"); time.sleep(2)
        pg.get_by_role("textbox").first.fill("1001"); pg.get_by_role("textbox").first.press("Enter")
        time.sleep(3); pg.wait_for_load_state("networkidle"); time.sleep(1.5)
        if nav_to(pg, "아차사고 등록"):
            for i, (w, c) in enumerate(REPORTS):
                submit_one(pg, w, c)
                again = btn(pg, "새 아차사고 등록")
                if again and i < len(REPORTS)-1:
                    again.click(); time.sleep(2.5); pg.wait_for_load_state("networkidle"); time.sleep(0.8)
                elif i < len(REPORTS)-1: nav_to(pg, "아차사고 등록")

        if not nav_to(pg, "아차사고 조회"):
            br.close(); return
        go = pg.query_selector('div[class*="st-key-near_miss_view_go"] button')
        if go: go.click(); time.sleep(3); pg.wait_for_load_state("networkidle"); time.sleep(2)

        log("PRINT icon (no selection):", print_state(pg))  # 음영 기대

        # 행 클릭 → 상세
        fr = gframe(pg)
        if fr:
            row = fr.query_selector('.ag-center-cols-container .ag-row .ag-cell')
            if row: row.click(); time.sleep(3.5); pg.wait_for_load_state("networkidle"); time.sleep(3)
        # 다운로드 버튼(상세) 렌더 대기
        for _ in range(10):
            if pg.query_selector('.st-key-nmv_pdf_dl button'): break
            time.sleep(1)
        pg.screenshot(path=str(OUT / "view_detail_print_1366.png"), full_page=True)

        # 상세 다운로드 버튼 → PDF 캡처
        dlbtn = pg.query_selector('.st-key-nmv_pdf_dl button')
        if dlbtn:
            with pg.expect_download() as di:
                dlbtn.click()
            d = di.value
            path = OUT / (d.suggested_filename or "report.pdf")
            d.save_as(str(path))
            log("DETAIL download saved:", path.name, path.stat().st_size, "bytes")
        else:
            log("DETAIL download button not found")

        # 선택 후 헤더 인쇄 활성 반영엔 1-rerun 지연 → 새로고침 아이콘으로 rerun 유발 후 확인.
        rf = pg.query_selector('.st-key-hdr_ic_on_refresh button')
        if rf: rf.click(); time.sleep(3); pg.wait_for_load_state("networkidle"); time.sleep(2.5)
        log("PRINT icon (after select + rerun):", print_state(pg))

        # 헤더 인쇄 아이콘 → 자동 다운로드
        pbtn = pg.query_selector('.st-key-hdr_ic_on_print button')
        if pbtn and not pbtn.is_disabled():
            try:
                with pg.expect_download(timeout=8000) as di2:
                    pbtn.click()
                d2 = di2.value
                path2 = OUT / ("header_" + (d2.suggested_filename or "report.pdf"))
                d2.save_as(str(path2))
                log("HEADER print download saved:", path2.name, path2.stat().st_size, "bytes")
            except Exception as e:
                log("HEADER print download: no download captured —", str(e)[:60])
        else:
            log("HEADER print icon not active/clickable")

        h = pg.evaluate("()=>document.documentElement.scrollWidth-document.documentElement.clientWidth")
        log("h_overflow:", h)
        br.close(); log("DONE")


if __name__ == "__main__":
    main()
