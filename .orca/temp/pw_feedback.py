"""피드백 3건 검증 — 헤더 아이콘 간격·조회 필터+지표·내 아차사고 지표, 1366."""
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(".orca/artifacts/claude-design-adopt/feedback1")
OUT.mkdir(parents=True, exist_ok=True)
URL = "http://localhost:8556/"
REPORTS = [("원료실 미끄러짐", "미끄러짐"), ("스태커 충돌", "부딪힘"),
           ("지게차 후진", "부딪힘"), ("배관 화상 위험", "화상")]


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
        for grp in ("아차사고 관리","기준정보","근무표"):
            c = btn(page, grp)
            if c: c.click(); time.sleep(1.0)
            if btn(page, label): break
        b = btn(page, label)
    if b is None: log("!! nav not found", label); return False
    b.click(); time.sleep(3.5); page.wait_for_load_state("networkidle"); time.sleep(1.5)
    return True


def submit_one(page, work, cause):
    fill_ph(page, "예: 3라인 컨베이어 벨트 점검", work)
    fill_ph(page, "원인을 구체적으로", f"{work} 원인")
    fill_ph(page, "무슨 일이 있었는지(아차사고 상황)를 구체적으로 적어 주세요", f"{work} 상황.")
    fill_ph(page, "어떤 작업을 하고 있었는지", f"{work} 작업.")
    fill_ph(page, "현장 상황 · 주변 환경", f"{work} 현장.")
    fill_ph(page, "재발을 막기 위한 제안 대책", f"{work} 대책.")
    combos = page.get_by_role("combobox").all()
    if combos:
        combos[0].click(); time.sleep(0.6)
        for o in page.get_by_role("option").all():
            if cause in (o.inner_text() or ""): o.click(); break
        time.sleep(0.4)
    sb = btn(page, "제안서 제출")
    if sb: sb.click(); time.sleep(2.5); page.wait_for_load_state("networkidle"); time.sleep(0.8)


def main():
    with sync_playwright() as p:
        br = p.chromium.launch()
        pg = br.new_context(viewport={"width": 1366, "height": 900}).new_page()
        pg.goto(URL, wait_until="networkidle"); time.sleep(2)
        pg.get_by_role("textbox").first.fill("1001"); pg.get_by_role("textbox").first.press("Enter")
        time.sleep(3); pg.wait_for_load_state("networkidle"); time.sleep(1.5)

        # #1 헤더 아이콘 간격
        pg.screenshot(path=str(OUT / "header_icons_1366.png"), full_page=False,
                      clip={"x": 234, "y": 0, "width": 1132, "height": 90})
        gaps = pg.evaluate("""()=>{
          const btns=[...document.querySelectorAll('div[class*="st-key-hdr_ic_"] button')].filter(b=>b.offsetWidth>0);
          const rects=btns.map(b=>b.getBoundingClientRect());
          const g=[]; for(let i=1;i<rects.length;i++) g.push(Math.round(rects[i].left-rects[i-1].right));
          const pill=document.querySelector('.cd-conn'); const pr=pill?pill.getBoundingClientRect():null;
          return {nIcons:rects.length, gaps:g, iconW:rects[0]?Math.round(rects[0].width):null,
                  pillToFirst: (pr&&rects[0])?Math.round(rects[0].left-pr.right):null};}""")
        log("HEADER icon gaps:", gaps)

        # seed
        if nav_to(pg, "아차사고 등록"):
            for i,(w,c) in enumerate(REPORTS):
                submit_one(pg, w, c)
                again = btn(pg, "새 아차사고 등록")
                if again and i < len(REPORTS)-1:
                    again.click(); time.sleep(2.5); pg.wait_for_load_state("networkidle"); time.sleep(0.8)
                elif i < len(REPORTS)-1: nav_to(pg, "아차사고 등록")

        # #3+#2 아차사고 조회: 필터 §1-E + 지표
        if nav_to(pg, "아차사고 조회"):
            go = pg.query_selector('div[class*="st-key-near_miss_view_go"] button')
            if go: go.click(); time.sleep(3); pg.wait_for_load_state("networkidle"); time.sleep(2)
            pg.screenshot(path=str(OUT / "view_filter_metrics_1366.png"), full_page=False)
            info = pg.evaluate("""()=>{
              const cond=document.querySelector('[class*="st-key-erpcond_"]');
              const cs=cond?getComputedStyle(cond):null;
              const lbl=document.querySelector('.erp-lbl');
              const metrics=[...document.querySelectorAll('.erp-metric')];
              const mval=document.querySelector('.erp-metric-val');
              return {condBorder: cs?cs.borderTopWidth:null, condBg: cs?cs.backgroundColor:null,
                condBorderBottom: cs?cs.borderBottomWidth+' '+cs.borderBottomColor:null,
                lblAlign: lbl?getComputedStyle(lbl).textAlign:null, lblWeight: lbl?getComputedStyle(lbl).fontWeight:null,
                nMetrics: metrics.length, mvalFont: mval?getComputedStyle(mval).fontFamily:null,
                mvalSize: mval?getComputedStyle(mval).fontSize:null,
                goInline: !!document.querySelector('[class*="st-key-erpcond_submit_"] button')};}""")
            log("VIEW filter+metrics:", info)
            h = pg.evaluate("()=>document.documentElement.scrollWidth-document.documentElement.clientWidth")
            log("VIEW h_overflow:", h)

        # #2 내 아차사고 지표
        if nav_to(pg, "내 아차사고"):
            pg.screenshot(path=str(OUT / "my_metrics_1366.png"), full_page=False)
            info2 = pg.evaluate("""()=>{const m=[...document.querySelectorAll('.erp-metric')];
              const v=document.querySelector('.erp-metric-val');
              return {nMetrics:m.length, mvalFont:v?getComputedStyle(v).fontFamily:null};}""")
            log("MY metrics:", info2)

        # 마스터 필터 정상성(사용자 관리)
        if nav_to(pg, "사용자 관리"):
            info3 = pg.evaluate("""()=>{const c=document.querySelector('[class*="st-key-erpcond_"]');
              const cs=c?getComputedStyle(c):null; const l=document.querySelector('.erp-lbl');
              return {condBorder:cs?cs.borderTopWidth:null, condBg:cs?cs.backgroundColor:null,
                lblAlign:l?getComputedStyle(l).textAlign:null};}""")
            h3 = pg.evaluate("()=>document.documentElement.scrollWidth-document.documentElement.clientWidth")
            log("MASTER users filter:", info3, "| h_overflow:", h3)
            pg.screenshot(path=str(OUT / "master_users_filter_1366.png"), full_page=False)

        br.close(); log("DONE")


if __name__ == "__main__":
    main()
