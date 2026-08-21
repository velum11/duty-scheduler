"""일괄 보정 검증 — schedule 폰트/잘림, 평가 오버라인 대비, 사용자 재직 tooltip."""
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(".orca/artifacts/claude-design-adopt/fixes")
OUT.mkdir(parents=True, exist_ok=True)
URL = "http://localhost:8541/"

CONTRAST_JS = """
(sel) => {
  function lum(c){const f=x=>{x/=255;return x<=0.03928?x/12.92:Math.pow((x+0.055)/1.055,2.4);};
    return 0.2126*f(c[0])+0.7152*f(c[1])+0.0722*f(c[2]);}
  function parse(s){const m=s.match(/\\d+/g);return m?m.slice(0,3).map(Number):null;}
  function bgOf(el){let e=el;while(e){const b=getComputedStyle(e).backgroundColor;
    if(b&&b!=='rgba(0, 0, 0, 0)'&&b!=='transparent'){return parse(b);}e=e.parentElement;}
    return [244,242,238];}
  const TAGS=['WHAT','TASK','SITE','CAUSE','ACTION','NOTE'];
  let el=null;
  for(const s of document.querySelectorAll('span')){
    if(TAGS.includes((s.textContent||'').trim())){el=s;break;}}
  if(!el)return null;
  const fg=parse(getComputedStyle(el).color), bg=bgOf(el);
  const L1=lum(fg)+0.05, L2=lum(bg)+0.05;
  const ratio=(Math.max(L1,L2)/Math.min(L1,L2));
  return {tag:el.textContent.trim(), color:getComputedStyle(el).color, bg:'rgb('+bg.join(',')+')',
          ratio:Math.round(ratio*100)/100};
}
"""


def log(*a): print(*a, flush=True)


def btn(page, text):
    for b in page.get_by_role("button").all():
        try:
            if text in (b.inner_text() or ""): return b
        except Exception: pass
    return None


def nav_to(page, group, label):
    b = btn(page, label)
    if b is None:
        c = btn(page, group)
        if c: c.click(); time.sleep(1.2)
        b = btn(page, label)
    if b is None:
        log("!! nav not found:", label); return False
    b.click(); time.sleep(3.5); page.wait_for_load_state("networkidle"); time.sleep(1)
    return True


def grid_frame(page, tries=20):
    # streamlit-aggrid 는 component iframe 으로 렌더된다. iframe element 의 content_frame() 로
    # 접근하고 .ag-cell 이 실제로 붙을 때까지 재시도한다(rerun detach/reattach 내성).
    for _ in range(tries):
        for el in page.query_selector_all("iframe"):
            try:
                cf = el.content_frame()
                if cf and cf.query_selector(".ag-cell"):
                    return cf
            except Exception:
                pass
        time.sleep(1)
    return None


def fill_ph(page, ph, val):
    page.locator(f"[placeholder='{ph}']").first.fill(val)


def seed_one(page):
    if not nav_to(page, "아차사고 관리", "아차사고 등록"): return
    fill_ph(page, "예: 3라인 컨베이어 벨트 점검", "지게차 후진 접근 위험")
    fill_ph(page, "원인을 구체적으로", "후방 사각 · 경보 미흡")
    fill_ph(page, "무슨 일이 있었는지(아차사고 상황)를 구체적으로 적어 주세요", "지게차 후진 중 작업자 근접.")
    fill_ph(page, "어떤 작업을 하고 있었는지", "상차장 검수 작업.")
    fill_ph(page, "현장 상황 · 주변 환경", "3번 도크 후방 사각.")
    fill_ph(page, "재발을 막기 위한 제안 대책", "후진 경보·유도자 배치.")
    combos = page.get_by_role("combobox").all()
    if combos:
        combos[0].click(); time.sleep(0.6)
        for o in page.get_by_role("option").all():
            if "부딪힘" in (o.inner_text() or ""): o.click(); break
        time.sleep(0.4)
    sb = btn(page, "제안서 제출")
    if sb: sb.click(); time.sleep(2.5); page.wait_for_load_state("networkidle"); time.sleep(0.8)


def main():
    with sync_playwright() as p:
        br = p.chromium.launch()
        pg = br.new_page(viewport={"width": 1366, "height": 900})
        pg.goto(URL, wait_until="networkidle"); time.sleep(2)
        pg.get_by_role("textbox").first.fill("1001")
        pg.get_by_role("textbox").first.press("Enter")
        time.sleep(3); pg.wait_for_load_state("networkidle"); time.sleep(1)

        # ===== FIX #2: 편성표 폰트/잘림 =====
        if nav_to(pg, "근무표", "근무표 편성"):
            go = btn(pg, "조회")
            if go: go.click(); time.sleep(3); pg.wait_for_load_state("networkidle"); time.sleep(1)
            fr = grid_frame(pg)
            if fr:
                cell = fr.query_selector('.ag-cell[col-id="사번"]')
                if cell:
                    fs = fr.evaluate("el=>getComputedStyle(el).fontSize", cell)
                    # 실측 잘림 + 10자리 사번(2008082501) 폭을 셀 폰트로 canvas 측정해 clientWidth 대비
                    clip = fr.evaluate(
                        "el=>{const cs=getComputedStyle(el);"
                        "const cv=document.createElement('canvas').getContext('2d');"
                        "cv.font=cs.fontWeight+' '+cs.fontSize+' '+cs.fontFamily;"
                        "const w10=cv.measureText('2008082501').width;"
                        "const pad=parseFloat(cs.paddingLeft)+parseFloat(cs.paddingRight);"
                        "return {sw:el.scrollWidth, cw:el.clientWidth, txt:(el.textContent||'').trim(),"
                        " w10:Math.round(w10*10)/10, avail:Math.round((el.clientWidth-pad)*10)/10,"
                        " fits10:(w10 <= el.clientWidth-pad)};}", cell)
                    log("SCHEDULE 사번 cell font-size:", fs, "| clip/10자리:", clip)
                hdr = fr.query_selector('.ag-header-cell-label')
                if hdr:
                    log("SCHEDULE header font-size:", fr.evaluate("el=>getComputedStyle(el).fontSize", hdr))
                # 실제 근무 셀(col-id 이 'N(요일)' — _action/신원 열 제외)
                dayfs = fr.evaluate(
                    "()=>{for(const e of document.querySelectorAll('.ag-cell')){"
                    "const c=e.getAttribute('col-id')||'';"
                    "if(/^\\d+\\(/.test(c)) return {col:c, fs:getComputedStyle(e).fontSize,"
                    " t:(e.textContent||'').trim()};}return null;}")
                log("SCHEDULE day cell:", dayfs)
            pg.screenshot(path=str(OUT / "schedule_edit_1366.png"), full_page=False)
            log("captured schedule")

        # ===== FIX #1: 평가 관리 오버라인 대비 =====
        seed_one(pg)
        if nav_to(pg, "아차사고 관리", "평가 관리"):
            time.sleep(1)
            res = pg.evaluate(CONTRAST_JS, "span")
            log("EVALUATE overline contrast:", res)
            pg.screenshot(path=str(OUT / "evaluate_1366.png"), full_page=False)
            log("captured evaluate")

        # ===== FIX #3: 사용자 재직 pill tooltip =====
        if nav_to(pg, "기준정보", "사용자 관리"):
            time.sleep(2)
            fr = grid_frame(pg)
            if fr:
                info = fr.evaluate(
                    "()=>{let c=document.querySelector('.ag-cell[col-id=\"재직\"] span');"
                    "if(!c){for(const s of document.querySelectorAll('.ag-cell span')){"
                    "const t=(s.textContent||'').trim(); if(t==='재직'||t==='퇴직'){c=s;break;}}}"
                    "if(!c)return {err:'재직 pill span not found', cols:[...new Set("
                    "[...document.querySelectorAll('.ag-cell')].map(e=>e.getAttribute('col-id')))]};"
                    "return {title:c.getAttribute('title'),cursor:getComputedStyle(c).cursor,"
                    "txt:(c.textContent||'').trim()};}")
                log("USERS 재직 pill:", info)
            else:
                log("USERS grid frame not found")
            pg.screenshot(path=str(OUT / "users_1366.png"), full_page=False)
            log("captured users")

        h = pg.evaluate("()=>document.documentElement.scrollWidth-document.documentElement.clientWidth")
        log("PAGE h_overflow(px):", h)
        br.close(); log("DONE")


if __name__ == "__main__":
    main()
