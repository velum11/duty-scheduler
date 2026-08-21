import sys, io, json, os, traceback
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from playwright.sync_api import sync_playwright
PORT=8534
OUT=".orca/artifacts/claude-design-adopt/final-qa"
IMG=os.path.abspath(".orca/temp/imgs")
L=json.load(open(".orca/temp/labels.json",encoding="utf-8-sig"))
def P(*a): print(*a, flush=True)
def _pick(pg,scope,name):
    loc=pg.locator(scope,has_text=name); loc.first.wait_for(state="attached",timeout=15000)
    ve=va=ah=None
    for h in loc.element_handles():
        t=h.inner_text().replace(chr(10)," ").strip(); v=h.is_visible()
        if ah is None: ah=h
        if v and va is None: va=h
        if v and t==name: ve=h; break
    return ve or va or ah
def click_exact(pg,name): _pick(pg,"button",name).click()
def click_nav(pg,name): _pick(pg,"section[data-testid='stSidebar'] button",name).click()
def nav(pg,module,child):
    loc=pg.locator("section[data-testid='stSidebar'] button",has_text=child)
    try: vis=any(h.is_visible() for h in loc.element_handles())
    except Exception: vis=False
    if not vis:
        try: click_nav(pg,module); pg.wait_for_timeout(1200)
        except Exception: pass
    click_nav(pg,child); pg.wait_for_timeout(3200)
def fill_label(pg,pfx,val):
    el=pg.query_selector("textarea[aria-label^='%s']"%pfx) or pg.query_selector("input[aria-label^='%s']"%pfx)
    el.click(); el.fill(val)
def pick_cause(pg):
    for sb in pg.query_selector_all("[data-testid='stSelectbox']"):
        if sb.inner_text().strip().startswith(L["cause"]):
            (sb.query_selector("[role='combobox']") or sb).click(); pg.wait_for_timeout(700)
            o=pg.query_selector("[role='option']:has-text('%s')"%L["jam"])
            if o: o.click(); pg.wait_for_timeout(700)
            return
with sync_playwright() as p:
    b=p.chromium.launch(); pg=b.new_context(viewport={"width":1366,"height":768}).new_page()
    pg.set_default_timeout(15000)
    pg.goto("http://localhost:%d"%PORT,wait_until="domcontentloaded")
    pg.wait_for_selector("input[aria-label='%s']"%L["sabeon"],timeout=30000)
    pg.fill("input[aria-label='%s']"%L["sabeon"],"1001"); pg.keyboard.press("Enter"); pg.wait_for_timeout(4500)
    # submit
    nav(pg,L["module_nm"],L["submit"])
    pg.wait_for_selector("input[aria-label^='%s']"%L["work_name"],timeout=15000)
    fill_label(pg,L["work_name"],L["d_work"]); pick_cause(pg)
    for pfx,key in [(L["cause_detail"],"d_causedet"),(L["incident"],"d_incident"),(L["work_content"],"d_workc"),(L["site"],"d_site"),(L["counter"],"d_counter")]:
        fill_label(pg,pfx,L[key])
    click_exact(pg,L["btn_submit"]); pg.wait_for_timeout(3500)
    # evaluate
    nav(pg,L["module_nm"],L["evaluate"])
    try: _pick(pg,"button",L["rowmatch"]).click(); pg.wait_for_timeout(2000)
    except Exception: pass
    click_exact(pg,L["btn_review"]); pg.wait_for_timeout(2500)
    click_exact(pg,L["gradeB"]); pg.wait_for_timeout(1500)
    click_exact(pg,L["btn_confirm"]); pg.wait_for_timeout(3000)
    # improvement - inspect assignee selectbox
    nav(pg,L["module_nm"],L["improve"])
    boxes=pg.query_selector_all("[data-testid='stSelectbox']")
    P("SELECTBOX COUNT:", len(boxes))
    for i,sb in enumerate(boxes):
        P(i, "label:", sb.inner_text().replace(chr(10)," ")[:40])
    # target CAPA assignee
    target=None
    for sb in boxes:
        if sb.inner_text().strip().startswith(L["sel_assignee"]): target=sb; break
    if target:
        cb=target.query_selector("[role='combobox']")
        P("combobox found:", bool(cb), "enabled:", (not cb.is_disabled()) if cb else "NA")
        (cb or target).click(); pg.wait_for_timeout(1000)
        opts=pg.query_selector_all("[role='option']")
        P("OPTIONS OPENED:", len(opts))
        for o in opts[:12]:
            P("  opt:", o.inner_text().replace(chr(10)," ")[:30])
        # click option containing 1002
        chosen=None
        for o in opts:
            if "1002" in o.inner_text(): chosen=o; break
        if chosen:
            chosen.click(); pg.wait_for_timeout(1200)
            P("AFTER SELECT assignee text:", target.inner_text().replace(chr(10)," ")[:40])
        else:
            P("no 1002 option; pressing Escape"); pg.keyboard.press("Escape")
    # stats header probe
    nav(pg,L["module_nm"],L["stats"])
    hdr=pg.query_selector(".st-key-app_header")
    crumb=pg.query_selector(".st-key-app_header .crumb, [class*='crumb']")
    icons=len(pg.query_selector_all(".st-key-app_hdr_refresh button"))
    P("STATS header container:", bool(hdr), "crumb:", bool(crumb), "refresh-icon-count:", icons)
    # also check another screen for comparison
    nav(pg,L["module_nm"],L["view"])
    hdr2=pg.query_selector(".st-key-app_header")
    icons2=len(pg.query_selector_all(".st-key-app_hdr_refresh button"))
    P("VIEW header container:", bool(hdr2), "refresh-icon-count:", icons2)
    b.close()