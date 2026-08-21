import sys, io, json, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from playwright.sync_api import sync_playwright
PORT=8535; OUT=".orca/artifacts/claude-design-adopt/final-qa"; IMG=os.path.abspath(".orca/temp/imgs")
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
def sel_capa(pg, pfx, needle):
    target=None
    for sb in pg.query_selector_all("[data-testid='stSelectbox']"):
        if sb.inner_text().strip().startswith(pfx): target=sb; break
    if not target: return "no-box"
    cb=target.query_selector("[role='combobox']") or target
    cb.scroll_into_view_if_needed(); pg.wait_for_timeout(400)
    cb.click(); pg.wait_for_timeout(1200)
    opts=pg.query_selector_all("[role='option']")
    if not opts:
        # keyboard approach
        pg.keyboard.type(needle); pg.wait_for_timeout(1000)
        opts=pg.query_selector_all("[role='option']")
    for o in opts:
        if needle in o.inner_text():
            o.click(); pg.wait_for_timeout(1200); return "OK:"+target.inner_text().replace(chr(10)," ")[:30]
    pg.keyboard.press("Escape"); return "opts=%d nohit"%len(opts)
with sync_playwright() as p:
    b=p.chromium.launch(); pg=b.new_context(viewport={"width":1366,"height":768}).new_page()
    pg.set_default_timeout(15000)
    pg.goto("http://localhost:%d"%PORT,wait_until="domcontentloaded")
    pg.wait_for_selector("input[aria-label='%s']"%L["sabeon"],timeout=30000)
    pg.fill("input[aria-label='%s']"%L["sabeon"],"1001"); pg.keyboard.press("Enter"); pg.wait_for_timeout(4500)
    nav(pg,L["module_nm"],L["submit"])
    pg.wait_for_selector("input[aria-label^='%s']"%L["work_name"],timeout=15000)
    fill_label(pg,L["work_name"],L["d_work"]); pick_cause(pg)
    for pfx,key in [(L["cause_detail"],"d_causedet"),(L["incident"],"d_incident"),(L["work_content"],"d_workc"),(L["site"],"d_site"),(L["counter"],"d_counter")]:
        fill_label(pg,pfx,L[key])
    click_exact(pg,L["btn_submit"]); pg.wait_for_timeout(3500)
    nav(pg,L["module_nm"],L["evaluate"])
    try: _pick(pg,"button",L["rowmatch"]).click(); pg.wait_for_timeout(2000)
    except Exception: pass
    click_exact(pg,L["btn_review"]); pg.wait_for_timeout(2500)
    click_exact(pg,L["gradeB"]); pg.wait_for_timeout(1500)
    click_exact(pg,L["btn_confirm"]); pg.wait_for_timeout(3000)
    nav(pg,L["module_nm"],L["improve"])
    P("assignee:", sel_capa(pg, L["sel_assignee"], "1002"))
    pg.wait_for_timeout(2500)
    ab=pg.query_selector("textarea[aria-label^='%s']"%L["ta_action"])
    if ab: ab.click(); ab.fill(L["d_action"])
    rb=pg.query_selector("textarea[aria-label^='조치 결과']")
    if rb: rb.click(); rb.fill("완료 확인 QA")
    for lbl in [L["btn_save"], L["btn_submit_impr"]]:
        try: click_exact(pg,lbl); pg.wait_for_timeout(3000); P("clicked", lbl)
        except Exception as e: P("FAIL", lbl, str(e)[:50])
    pg.screenshot(path=OUT+"/v3_s4_submitted.png", full_page=True)
    pg.wait_for_timeout(2000)
    try: click_exact(pg,L["btn_verify_impr"]); pg.wait_for_timeout(3500); P("clicked verify")
    except Exception as e: P("verify FAIL", str(e)[:60])
    pg.screenshot(path=OUT+"/v3_s4_verified.png", full_page=True)
    try:
        click_exact(pg,L["btn_close"]); pg.wait_for_timeout(2500)
        pg.screenshot(path=OUT+"/v3_s4_close1.png", full_page=True)
        click_exact(pg,L["btn_close"]); pg.wait_for_timeout(3000)
        P("clicked close x2")
    except Exception as e: P("close FAIL", str(e)[:60])
    P("BODY_HAS_CLOSED:", "종결" in pg.inner_text("body"))
    pg.screenshot(path=OUT+"/v3_s4_closed.png", full_page=True)
    b.close()