"""피드백2 검증 — 헤더 아이콘 작동·클릭순환 제거·전체조회·라벨 겹침."""
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(".orca/artifacts/claude-design-adopt/feedback2")
OUT.mkdir(parents=True, exist_ok=True)
URL = "http://localhost:8561/"


def log(*a): print(*a, flush=True)


def btn(p, t):
    for b in p.get_by_role("button").all():
        try:
            if t in (b.inner_text() or ""): return b
        except Exception: pass
    return None


def gframe(page, tries=20):
    for _ in range(tries):
        for el in page.query_selector_all("iframe"):
            try:
                cf = el.content_frame()
                if cf and cf.query_selector(".ag-cell"): return cf
            except Exception: pass
        time.sleep(1)
    return None


def hdr_state(page):
    return page.evaluate("""()=>{
      const out={};
      for(const ic of ['add','refresh','delete','save','info']){
        const wrap=document.querySelector('.st-key-hdr_ic_on_'+ic+', .st-key-hdr_ic_off_'+ic);
        const b=wrap?wrap.querySelector('button'):null;
        const m=wrap?(wrap.className.match(/hdr_ic_(on|off)_/)||[]):[];
        out[ic]=b?{slot:m[1]||null, disabled:b.disabled}:null;
      }
      return out;}""")


def label_overlap(page):
    return page.evaluate("""()=>{
      const lbls=[...document.querySelectorAll('.erp-lbl')].slice(0,4);
      return lbls.map(l=>{const col=l.closest('[data-testid="stColumn"]')||l.parentElement;
        const w=col.querySelector('[data-baseweb="select"],input');
        const lr=l.getBoundingClientRect(); const wr=w?w.getBoundingClientRect():null;
        return {label:(l.textContent||'').trim(), gap: wr?Math.round(wr.top-lr.bottom):null};});}""")


def main():
    with sync_playwright() as p:
        br = p.chromium.launch()
        pg = br.new_context(viewport={"width": 1366, "height": 900}).new_page()
        pg.goto(URL, wait_until="networkidle"); time.sleep(2)
        pg.get_by_role("textbox").first.fill("1001"); pg.get_by_role("textbox").first.press("Enter")
        time.sleep(3); pg.wait_for_load_state("networkidle"); time.sleep(1.5)
        c = btn(pg, "근무표"); c.click(); time.sleep(1.2)
        b = btn(pg, "근무표 편성"); b.click(); time.sleep(3.5); pg.wait_for_load_state("networkidle"); time.sleep(2)

        # #4 라벨 겹침
        log("LABEL gaps:", label_overlap(pg))
        # 페이지 4단추 제거 확인
        keys = {b.key if hasattr(b, 'key') else '' for b in []}
        pagebtns = pg.evaluate("""()=>['se_add','se_go','se_del','se_save'].filter(k=>
          document.querySelector(`.st-key-${k}`)!==null)""")
        log("PAGE action buttons present (should be []):", pagebtns)
        # #1 헤더 아이콘 상태(초기: add/refresh 활성, delete/save 음영 — 선택0·dirty0)
        log("HDR state (initial):", hdr_state(pg))

        # 조회(전체 기본) — 헤더 새로고침 클릭
        rb = pg.query_selector('.st-key-hdr_ic_on_refresh button')
        if rb: rb.click(); time.sleep(3.5); pg.wait_for_load_state("networkidle"); time.sleep(2.5)
        pg.screenshot(path=str(OUT / "edit_all_scope_1366.png"), full_page=False)
        # #3 전체 조회 다부서 표시
        fr = gframe(pg)
        depts = []
        if fr:
            depts = fr.evaluate("""()=>{const s=new Set();
              document.querySelectorAll('.ag-cell[col-id="부서"]').forEach(c=>{
                const t=(c.textContent||'').trim(); if(t)s.add(t);}); return [...s];}""")
        log("ALL-scope distinct 부서:", depts)

        # #2 셀 클릭 순환 미발동: 첫 날짜 셀 값 클릭 전후 비교
        if fr:
            cell = fr.query_selector('.ag-cell[col-id="1(수)"]')
            if not cell:
                for c2 in fr.query_selector_all('.ag-cell'):
                    cid = c2.get_attribute("col-id") or ""
                    if cid and cid[0].isdigit(): cell = c2; break
            if cell:
                before = (cell.text_content() or "").strip()
                cell.click(); time.sleep(1.5)
                after = (cell.text_content() or "").strip()
                log("CELL click cycle (before==after → no cycle):", {"before": before, "after": after,
                    "nocycle": before == after})

        # #1 헤더 add 클릭 → 행 추가(행 수 증가)
        n0 = fr.evaluate("()=>document.querySelectorAll('.ag-center-cols-container .ag-row').length") if fr else 0
        ab = pg.query_selector('.st-key-hdr_ic_on_add button')
        if ab: ab.click(); time.sleep(3.5); pg.wait_for_load_state("networkidle"); time.sleep(2.5)
        fr2 = gframe(pg)
        n1 = fr2.evaluate("()=>document.querySelectorAll('.ag-center-cols-container .ag-row').length") if fr2 else 0
        log("HDR add: rows", n0, "->", n1, "(increased:", n1 > n0, ")")
        # add 후 dirty>0 → 저장 아이콘 활성화됐는지(다음 rerun 반영)
        log("HDR state (after add):", hdr_state(pg))
        pg.screenshot(path=str(OUT / "edit_header_actions_1366.png"), full_page=False)

        h = pg.evaluate("()=>document.documentElement.scrollWidth-document.documentElement.clientWidth")
        log("h_overflow:", h)
        br.close(); log("DONE")


if __name__ == "__main__":
    main()
