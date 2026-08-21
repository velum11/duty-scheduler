"""Stage 10 셸 §4 검증 — 펼침/모듈접힘/66px 레일 3상태 + 1366·900, 히트영역·tooltip·대비."""
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(".orca/artifacts/claude-design-adopt/stage10-shell")
OUT.mkdir(parents=True, exist_ok=True)
URL = "http://localhost:8543/"

CONTRAST_JS = """
(sel) => {
  const el=document.querySelector(sel); if(!el)return null;
  const btn=el.querySelector('button')||el;
  function lum(c){const f=x=>{x/=255;return x<=0.03928?x/12.92:Math.pow((x+0.055)/1.055,2.4);};
    return 0.2126*f(c[0])+0.7152*f(c[1])+0.0722*f(c[2]);}
  function parse(s){const m=s.match(/\\d+(\\.\\d+)?/g);return m?m.slice(0,3).map(Number):null;}
  function bgOf(e){let n=e;while(n){const b=getComputedStyle(n).backgroundColor;
    if(b&&b!=='rgba(0, 0, 0, 0)'&&b!=='transparent')return parse(b);n=n.parentElement;}return[26,25,23];}
  const fg=parse(getComputedStyle(btn).color), bg=bgOf(btn);
  const L1=lum(fg)+0.05,L2=lum(bg)+0.05;
  return {color:getComputedStyle(btn).color, bg:'rgb('+bg.join(',')+')',
          ratio:Math.round(Math.max(L1,L2)/Math.min(L1,L2)*100)/100,
          text:(btn.textContent||'').trim().slice(0,10)};
}
"""


def log(*a): print(*a, flush=True)


def sb_btn(page, key_prefix):
    return page.query_selector(f'div[class*="st-key-{key_prefix}"] button')


def main():
    with sync_playwright() as p:
        br = p.chromium.launch()
        pg = br.new_page(viewport={"width": 1366, "height": 900})
        pg.goto(URL, wait_until="networkidle"); time.sleep(2)
        pg.get_by_role("textbox").first.fill("1001")
        pg.get_by_role("textbox").first.press("Enter")
        time.sleep(3); pg.wait_for_load_state("networkidle"); time.sleep(1.5)

        # ===== 상태 A: 펼침 + 근무표 모듈 열기 =====
        b = sb_btn(pg, "sbg_schedule")
        if b: b.click(); time.sleep(2); pg.wait_for_load_state("networkidle"); time.sleep(1)
        pg.screenshot(path=str(OUT / "expanded_open_1366.png"), full_page=False)
        log("captured expanded (module open)")
        # 대비 실측 — 모듈 라벨·리프 라벨
        log("CONTRAST module label:", pg.evaluate(CONTRAST_JS, 'div[class*="st-key-sbg_schedule"]'))
        log("CONTRAST leaf label:", pg.evaluate(CONTRAST_JS, 'div[class*="st-key-sbi_schedule_edit"]'))
        # folder icon 제거 확인 — sbg 버튼 ::before 는 6px 마크(배경만), background-image 없음
        markinfo = pg.evaluate(
            "()=>{const b=document.querySelector('div[class*=\"st-key-sbg_schedule\"] button');"
            "if(!b)return null;const bs=getComputedStyle(b,'::before');"
            "return {w:bs.width,h:bs.height,radius:bs.borderRadius,bgimg:bs.backgroundImage,bg:bs.backgroundColor};}")
        log("MODULE mark ::before:", markinfo)
        caret = pg.evaluate(
            "()=>{const b=document.querySelector('div[class*=\"st-key-sbg_schedule\"] button');"
            "if(!b)return null;const a=getComputedStyle(b,'::after');"
            "return {content:a.content,transform:a.transform};}")
        log("MODULE caret ::after:", caret)

        # ===== 상태 B: 근무표 모듈 접기 =====
        b = sb_btn(pg, "sbg_schedule")
        if b: b.click(); time.sleep(2); pg.wait_for_load_state("networkidle"); time.sleep(1)
        pg.screenshot(path=str(OUT / "expanded_collapsed_1366.png"), full_page=False)
        log("captured expanded (module collapsed)")

        # ===== 상태 C: 66px 레일 =====
        hide = sb_btn(pg, "sb_hide")
        if hide: hide.click(); time.sleep(2.5); pg.wait_for_load_state("networkidle"); time.sleep(1.5)
        pg.screenshot(path=str(OUT / "rail_1366.png"), full_page=False)
        log("captured 66px rail")
        # 사이드바 폭
        sbw = pg.evaluate("()=>{const s=document.querySelector('section[data-testid=\"stSidebar\"]');"
                          "return s?Math.round(s.getBoundingClientRect().width):null;}")
        log("RAIL sidebar width(px):", sbw)
        # 레일 글리프 히트영역 + 접근성 이름 + tooltip
        glyph = pg.evaluate(
            "()=>{const b=document.querySelector('div[class*=\"st-key-sbr_schedule\"] button');"
            "if(!b)return null;const r=b.getBoundingClientRect();"
            "const tip=b.getAttribute('title')||b.getAttribute('aria-label')||"
            "(b.closest('[data-testid=\"stTooltipHoverTarget\"]')?'has-tooltip-wrapper':null);"
            "return {w:Math.round(r.width),h:Math.round(r.height),text:(b.textContent||'').trim(),"
            "title:b.getAttribute('title'),aria:b.getAttribute('aria-label')};}")
        log("RAIL glyph button:", glyph)
        # tooltip 래퍼 존재(Streamlit help)
        tipwrap = pg.evaluate(
            "()=>{const c=document.querySelector('div[class*=\"st-key-sbr_schedule\"]');"
            "if(!c)return null;return {hasTooltipTarget: !!c.querySelector('[data-testid=\"stTooltipHoverTarget\"]'),"
            "html: c.querySelector('[data-testid]')?c.querySelector('[data-testid]').getAttribute('data-testid'):null};}")
        log("RAIL tooltip wrapper:", tipwrap)
        log("CONTRAST rail glyph:", pg.evaluate(CONTRAST_JS, 'div[class*="st-key-sbr_schedule"]'))
        railbtns = pg.evaluate("()=>document.querySelectorAll('div[class*=\"st-key-sbr_\"] button').length")
        log("RAIL module glyph count:", railbtns)

        # 900px 레일
        pg.set_viewport_size({"width": 900, "height": 900}); time.sleep(1.5)
        pg.screenshot(path=str(OUT / "rail_900.png"), full_page=False)
        # 펼침 복원 후 900
        exp = sb_btn(pg, "sb_expand")
        if exp: exp.click(); time.sleep(2.5); pg.wait_for_load_state("networkidle"); time.sleep(1.5)
        pg.screenshot(path=str(OUT / "expanded_900.png"), full_page=False)
        log("captured 900 (rail + expanded)")

        h = pg.evaluate("()=>document.documentElement.scrollWidth-document.documentElement.clientWidth")
        log("PAGE h_overflow@900(px):", h)
        br.close(); log("DONE")


if __name__ == "__main__":
    main()
