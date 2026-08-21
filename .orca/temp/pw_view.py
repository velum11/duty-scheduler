"""Stage 11B 아차사고 조회 §1-E 검증 — seed → 조회 목록 → 행클릭 상세, 1366·900."""
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(".orca/artifacts/claude-design-adopt/stage11-view")
OUT.mkdir(parents=True, exist_ok=True)
URL = "http://localhost:8546/"
REPORTS = [
    ("원료실 계획서 부착 중 미끄러짐", "미끄러짐"),
    ("스태커 운반 중 근접 충돌", "부딪힘"),
    ("지게차 후진 접근", "부딪힘"),
    ("배관 용접 중 화상 위험", "화상"),
]


def log(*a): print(*a, flush=True)


def btn(page, text):
    for b in page.get_by_role("button").all():
        try:
            if text in (b.inner_text() or ""): return b
        except Exception: pass
    return None


def fill_ph(page, ph, val):
    page.locator(f"[placeholder='{ph}']").first.fill(val)


def nav_to(page, label):
    b = btn(page, label)
    if b is None:
        c = btn(page, "아차사고 관리")
        if c: c.click(); time.sleep(1.2)
        b = btn(page, label)
    if b is None:
        log("!! nav not found:", label); return False
    b.click(); time.sleep(3.5); page.wait_for_load_state("networkidle"); time.sleep(1)
    return True


def submit_one(page, work, cause):
    fill_ph(page, "예: 3라인 컨베이어 벨트 점검", work)
    fill_ph(page, "원인을 구체적으로", f"{work} 원인 상세")
    fill_ph(page, "무슨 일이 있었는지(아차사고 상황)를 구체적으로 적어 주세요", f"{work} 상황 서술.")
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


def grid_frame(page, tries=20):
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
        pg = br.new_page(viewport={"width": 1366, "height": 900})
        pg.goto(URL, wait_until="networkidle"); time.sleep(2)
        pg.get_by_role("textbox").first.fill("1001")
        pg.get_by_role("textbox").first.press("Enter")
        time.sleep(3); pg.wait_for_load_state("networkidle"); time.sleep(1.5)

        # seed
        if not nav_to(pg, "아차사고 등록"):
            br.close(); return
        for i, (w, c) in enumerate(REPORTS):
            submit_one(pg, w, c); log(f"submitted {i+1}")
            again = btn(pg, "새 아차사고 등록")
            if again and i < len(REPORTS) - 1:
                again.click(); time.sleep(2.5); pg.wait_for_load_state("networkidle"); time.sleep(0.8)
            elif i < len(REPORTS) - 1:
                nav_to(pg, "아차사고 등록")

        # 아차사고 조회 → 조회
        if not nav_to(pg, "아차사고 조회"):
            br.close(); return
        go = pg.query_selector('div[class*="st-key-near_miss_view_go"] button')
        if go: go.click(); time.sleep(3); pg.wait_for_load_state("networkidle"); time.sleep(2)
        pg.screenshot(path=str(OUT / "view_list_1366.png"), full_page=False)
        log("captured list")

        # 표 §1-E 실측: 셀 폰트·헤더 배경·보고번호 폰트·체크박스 유무
        fr = grid_frame(pg)
        if fr:
            cell = fr.query_selector('.ag-cell')
            if cell:
                log("VIEW cell font-size:", fr.evaluate("el=>getComputedStyle(el).fontSize", cell))
            rep = fr.query_selector('.ag-cell[col-id="보고번호"]')
            if rep:
                log("VIEW 보고번호 font:", fr.evaluate("el=>getComputedStyle(el).fontFamily", rep))
            hdr = fr.query_selector('.ag-header')
            if hdr:
                log("VIEW header bg:", fr.evaluate("el=>getComputedStyle(el).backgroundColor", hdr))
            cb = fr.query_selector('.ag-selection-checkbox')
            log("VIEW checkbox marker present:", cb is not None)
            # 행 클릭 → 상세
            row = fr.query_selector('.ag-center-cols-container .ag-row .ag-cell')
            if row:
                row.click(); time.sleep(2.5); pg.wait_for_load_state("networkidle"); time.sleep(1.5)
                log("clicked first row")
        pg.screenshot(path=str(OUT / "view_detail_1366.png"), full_page=True)
        log("captured detail")

        h = pg.evaluate("()=>document.documentElement.scrollWidth-document.documentElement.clientWidth")
        log("PAGE h_overflow(px):", h)

        pg.set_viewport_size({"width": 900, "height": 900}); time.sleep(1.5)
        pg.screenshot(path=str(OUT / "view_900.png"), full_page=True)
        h9 = pg.evaluate("()=>document.documentElement.scrollWidth-document.documentElement.clientWidth")
        log("PAGE h_overflow@900(px):", h9)
        br.close(); log("DONE")


if __name__ == "__main__":
    main()
