import sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from playwright.sync_api import sync_playwright
L = json.load(open(".orca/temp/labels.json", encoding="utf-8-sig"))
with sync_playwright() as p:
    b = p.chromium.launch(); ctx=b.new_context(viewport={"width":1366,"height":768})
    pg=ctx.new_page()
    pg.goto("http://localhost:8533", wait_until="domcontentloaded")
    pg.wait_for_selector("input[aria-label='%s']"%L["sabeon"], timeout=30000)
    pg.fill("input[aria-label='%s']"%L["sabeon"], "1001"); pg.keyboard.press("Enter")
    pg.wait_for_timeout(5000)
    def vis():
        return pg.eval_on_selector_all("section[data-testid='stSidebar'] button",
            "els=>els.filter(e=>e.offsetParent!==null).map(e=>e.innerText.replace(/\s+/g,' ').trim())")
    print("VIS BEFORE:", json.dumps(vis(), ensure_ascii=False))
    loc = pg.locator("section[data-testid='stSidebar'] button", has_text=L["module_nm"])
    print("module matches:", loc.count())
    loc.locator("visible=true").first.click()
    pg.wait_for_timeout(1800)
    print("VIS AFTER:", json.dumps(vis(), ensure_ascii=False))
    b.close()
