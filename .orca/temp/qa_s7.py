import sys, io, json, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from playwright.sync_api import sync_playwright
PORT=8535; OUT=".orca/artifacts/claude-design-adopt/final-qa"
L=json.load(open(".orca/temp/labels.json",encoding="utf-8-sig"))
def P(*a): print(*a, flush=True)
def _pick(pg,scope,name):
    loc=pg.locator(scope,has_text=name); loc.first.wait_for(state="attached",timeout=15000)
    ve=va=ah=None
    for h in loc.element_handles():
        v=h.is_visible()
        if ah is None: ah=h
        if v and va is None: va=h
        if v and h.inner_text().replace(chr(10)," ").strip()==name: ve=h; break
    return ve or va or ah
def click_nav(pg,name): _pick(pg,"section[data-testid='stSidebar'] button",name).click()
def nav(pg,module,child):
    loc=pg.locator("section[data-testid='stSidebar'] button",has_text=child)
    try: vis=any(h.is_visible() for h in loc.element_handles())
    except Exception: vis=False
    if not vis:
        try: click_nav(pg,module); pg.wait_for_timeout(1200)
        except Exception: pass
    click_nav(pg,child); pg.wait_for_timeout(3500)
def ag(pg):
    for _ in range(8):
        for fr in pg.frames:
            try:
                if fr.query_selector(".ag-root"): return fr
            except Exception: pass
        pg.wait_for_timeout(1500)
    return None
with sync_playwright() as p:
    b=p.chromium.launch(); pg=b.new_context(viewport={"width":1366,"height":768}).new_page()
    pg.set_default_timeout(15000)
    pg.goto("http://localhost:%d"%PORT,wait_until="domcontentloaded")
    pg.wait_for_selector("input[aria-label='%s']"%L["sabeon"],timeout=30000)
    pg.fill("input[aria-label='%s']"%L["sabeon"],"1001"); pg.keyboard.press("Enter"); pg.wait_for_timeout(4500)
    nav(pg,L["module_sch"],L["sch_edit"])
    fr=ag(pg)
    P("ag frame:", bool(fr))
    if fr:
        # pick a day cell (col-id numeric) in first center row
        cell=fr.query_selector(".ag-center-cols-container .ag-row[row-index='0'] .ag-cell[col-id='1']") \
             or fr.query_selector(".ag-center-cols-container .ag-row[row-index='0'] .ag-cell:nth-child(1)")
        if cell:
            v0=cell.inner_text().strip()
            # single click - should NOT cycle value
            cell.click(); pg.wait_for_timeout(1200)
            c2=fr.query_selector(".ag-center-cols-container .ag-row[row-index='0'] .ag-cell[col-id='1']")
            v1=c2.inner_text().strip() if c2 else "?"
            P("single-click cycle check: before=%r after=%r same=%s"%(v0,v1,v0==v1))
            # double-click - should open editor
            c2.dblclick(); pg.wait_for_timeout(1000)
            ed=fr.query_selector(".ag-cell-inline-editing, .ag-popup-editor, input.ag-input-field-input, [role='listbox']")
            P("dblclick editor open:", bool(ed))
            # escape to avoid change
            pg.keyboard.press("Escape"); pg.wait_for_timeout(500)
        else:
            P("no day cell found")
        # header add-row icon active?
        addbtn=pg.query_selector(".st-key-app_hdr_add button")
        P("header add enabled:", (not addbtn.is_disabled()) if addbtn else "NA")
    pg.screenshot(path=OUT+"/v3_s7_sched.png", full_page=True)
    b.close()