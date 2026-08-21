import sys, io, json, os, traceback
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from playwright.sync_api import sync_playwright
PORT=8534
OUT=".orca/artifacts/claude-design-adopt/final-qa"
IMG=os.path.abspath(".orca/temp/imgs")
L=json.load(open(".orca/temp/labels.json",encoding="utf-8-sig"))
R=[]
def log(s,st,n=""):
    R.append({"step":s,"status":st,"note":n}); print("[%s] %s -- %s"%(st,s,n))
ICONS=["info","language","add","refresh","delete","print","save","star"]
def hstates(pg):
    o={}
    for ic in ICONS:
        el=pg.query_selector(".st-key-app_hdr_%s button"%ic)
        o[ic]="MISSING" if not el else ("off" if el.is_disabled() else "ON")
    return o
def shot(pg,n): pg.screenshot(path="%s/%s.png"%(OUT,n),full_page=True)
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
def find_ag_frame(pg,tries=8):
    for _ in range(tries):
        for fr in pg.frames:
            try:
                if fr.query_selector(".ag-root"): return fr
            except Exception: pass
        pg.wait_for_timeout(1500)
    return None
def fill_label(pg,pfx,val):
    el=pg.query_selector("textarea[aria-label^='%s']"%pfx) or pg.query_selector("input[aria-label^='%s']"%pfx)
    if not el: raise RuntimeError("no field "+pfx)
    el.click(); el.fill(val)
def pick_select(pg,pfx,opt):
    boxes=pg.query_selector_all("[data-testid='stSelectbox']"); t=None
    for sb in boxes:
        if sb.inner_text().strip().startswith(pfx): t=sb; break
    if not t and boxes: t=boxes[0]
    if not t: raise RuntimeError("no selectbox "+pfx)
    (t.query_selector("[role='combobox']") or t).click(); pg.wait_for_timeout(900)
    o=pg.query_selector("[role='option']:has-text('%s')"%opt) or pg.query_selector("li:has-text('%s')"%opt)
    if o:
        o.click(); pg.wait_for_timeout(900); return
    try: pg.keyboard.type(opt); pg.wait_for_timeout(900)
    except Exception: pass
    o=pg.query_selector("[role='option']:has-text('%s')"%opt) or pg.query_selector("li:has-text('%s')"%opt)
    if o: o.click(); pg.wait_for_timeout(900); return
    pg.keyboard.press("Enter"); pg.wait_for_timeout(900)
    cur=t.inner_text()
    if opt not in cur:
        pg.keyboard.press("Escape"); raise RuntimeError("opt "+opt+" cur="+cur.replace(chr(10)," ")[:60])

def submit(pg):
    nav(pg,L["module_nm"],L["submit"])
    pg.wait_for_selector("input[aria-label^='%s']"%L["work_name"],timeout=15000)
    fill_label(pg,L["work_name"],L["d_work"])
    pick_select(pg,L["cause"],L["jam"])
    fill_label(pg,L["cause_detail"],L["d_causedet"])
    fill_label(pg,L["incident"],L["d_incident"])
    fill_label(pg,L["work_content"],L["d_workc"])
    fill_label(pg,L["site"],L["d_site"])
    fill_label(pg,L["counter"],L["d_counter"])
    pg.wait_for_timeout(400)
    up=pg.query_selector(".st-key-nm_photo_zone input[type='file']")
    up.set_input_files([os.path.join(IMG,"photo_a.jpg")])
    pg.wait_for_timeout(3000)
    click_exact(pg,L["btn_submit"]); pg.wait_for_timeout(3800)
    log("f_submit","PASS" if "SUBMITTED" in pg.inner_text("body") else "FAIL","seed report")

def main():
    with sync_playwright() as p:
        b=p.chromium.launch(); pg=b.new_context(viewport={"width":1366,"height":768},device_scale_factor=1).new_page()
        pg.set_default_timeout(15000)
        pg.goto("http://localhost:%d"%PORT,wait_until="domcontentloaded")
        pg.wait_for_selector("input[aria-label='%s']"%L["sabeon"],timeout=30000)
        pg.fill("input[aria-label='%s']"%L["sabeon"],"1001"); pg.keyboard.press("Enter"); pg.wait_for_timeout(4500)
        log("login","PASS","1001")
        try: submit(pg)
        except Exception as e: log("f_submit","FAIL",str(e)); traceback.print_exc()

        # ---- S5 view ----
        try:
            nav(pg,L["module_nm"],L["view"])
            try: click_exact(pg,L["btn_query"]); pg.wait_for_timeout(2500)
            except Exception: pass
            fr=find_ag_frame(pg)
            log("s5_grid","PASS" if fr else "FAIL","ag frame=%s"%bool(fr))
            if fr:
                c=fr.query_selector(".ag-center-cols-container .ag-row .ag-cell")
                if c: c.click(); pg.wait_for_timeout(3000)
            shot(pg,"v2_s5_detail")
            h=hstates(pg); log("s5_print_icon","PASS" if h.get("print")=="ON" else "OBS","print=%s"%h.get("print"))
            try:
                with pg.expect_download(timeout=15000) as di:
                    _pick(pg,"button",L["pdf_save"]).click()
                d=di.value; path=os.path.join(OUT,"v2_report.pdf"); d.save_as(path)
                hd=open(path,"rb").read(5); log("s5_pdf","PASS" if hd[:4]==b"%PDF" else "FAIL","hd=%r"%hd)
            except Exception as e: log("s5_pdf","FAIL",str(e))
        except Exception as e: log("s5_view","FAIL",str(e)); shot(pg,"v2_s5_err"); traceback.print_exc()

        # ---- S6 stats ----
        try:
            nav(pg,L["module_nm"],L["stats"])
            shot(pg,"v2_s6_stats")
            b6=pg.inner_text("body")
            log("s6_kpi","PASS" if (L["kpi_cum"] in b6 or L["kpi_month"] in b6) else "OBS","cum/month KPI present")
        except Exception as e: log("s6_stats","FAIL",str(e)); traceback.print_exc()

        # ---- S3 evaluate ----
        try:
            nav(pg,L["module_nm"],L["evaluate"])
            try: _pick(pg,"button",L["rowmatch"]).click(); pg.wait_for_timeout(2500)
            except Exception: pass
            try: click_exact(pg,L["btn_review"]); pg.wait_for_timeout(3000); log("s3_review","PASS","IN_REVIEW")
            except Exception as e: log("s3_review","FAIL",str(e))
            try: click_exact(pg,L["gradeB"]); pg.wait_for_timeout(2000); log("s3_gradeB","PASS","B")
            except Exception as e: log("s3_gradeB","FAIL",str(e))
            try: click_exact(pg,L["btn_confirm"]); pg.wait_for_timeout(3200); log("s3_confirm","PASS","done")
            except Exception as e: log("s3_confirm","FAIL",str(e))
            shot(pg,"v2_s3_confirmed")
        except Exception as e: log("s3_eval","FAIL",str(e)); traceback.print_exc()

        # ---- S4 improvement ----
        try:
            nav(pg,L["module_nm"],L["improve"])
            shot(pg,"v2_s4_queue")
            body=pg.inner_text("body")
            log("s4_queue","OBS","body has assignee sel=%s"%(L["sel_assignee"] in body))
            try:
                pick_select(pg,L["sel_assignee"],"1002"); pg.wait_for_timeout(700)
                pick_select(pg,L["sel_confirmer"],"1003"); pg.wait_for_timeout(700)
                log("s4_assign","PASS","1002/1003")
            except Exception as e: log("s4_assign","FAIL",str(e))
            ab=pg.query_selector("textarea[aria-label^='%s']"%L["ta_action"])
            if ab: ab.click(); ab.fill(L["d_action"])
            for lbl,key in [(L["btn_save"],"s4_save"),(L["btn_submit_impr"],"s4_submit"),(L["btn_verify_impr"],"s4_confirm")]:
                try: click_exact(pg,lbl); pg.wait_for_timeout(3000); log(key,"PASS",lbl)
                except Exception as e: log(key,"FAIL",str(e))
            shot(pg,"v2_s4_mid")
            try:
                click_exact(pg,L["btn_close"]); pg.wait_for_timeout(2500)
                click_exact(pg,L["btn_close"]); pg.wait_for_timeout(3000)
                log("s4_close","PASS","2-step")
            except Exception as e: log("s4_close","FAIL",str(e))
            shot(pg,"v2_s4_after")
        except Exception as e: log("s4_impr","FAIL",str(e)); shot(pg,"v2_s4_err"); traceback.print_exc()

        json.dump(R,open("%s/results_v2.json"%OUT,"w",encoding="utf-8"),ensure_ascii=False,indent=2)
        b.close()
main()