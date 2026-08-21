import sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from playwright.sync_api import sync_playwright
L = json.load(open(".orca/temp/labels.json", encoding="utf-8-sig"))
def click_nav(pg, name):
    loc=pg.locator("section[data-testid='stSidebar'] button", has_text=name)
    loc.first.wait_for(state="attached",timeout=15000)
    for h in loc.element_handles():
        if h.is_visible(): h.click(); return
with sync_playwright() as p:
    b=p.chromium.launch(); pg=b.new_context(viewport={"width":1366,"height":768}).new_page()
    pg.goto("http://localhost:8533",wait_until="domcontentloaded")
    pg.wait_for_selector("input[aria-label='%s']"%L["sabeon"],timeout=30000)
    pg.fill("input[aria-label='%s']"%L["sabeon"],"1001"); pg.keyboard.press("Enter")
    pg.wait_for_timeout(5000)
    click_nav(pg,L["module_nm"]); pg.wait_for_timeout(1000)
    click_nav(pg,L["submit"]); pg.wait_for_timeout(3000)
    for sel in ["[data-testid='stSelectbox']","div[data-baseweb='select']","[role='combobox']","[data-testid='stSelectbox'] div[role='combobox']","[data-baseweb='select'] input"]:
        print(sel, "=>", len(pg.query_selector_all(sel)))
    sb=pg.query_selector("[data-testid='stSelectbox']")
    if sb: print("SB html head:", sb.inner_html()[:300])
    b.close()
