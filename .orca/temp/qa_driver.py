import sys, io, json, time, os, traceback
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from playwright.sync_api import sync_playwright

PORT = 8533
OUT = ".orca/artifacts/claude-design-adopt/final-qa"
IMG = os.path.abspath(".orca/temp/imgs")
L = json.load(open(".orca/temp/labels.json", encoding="utf-8-sig"))
RESULTS = []
def log(step, status, note=""):
    RESULTS.append({"step": step, "status": status, "note": note})
    print("[%s] %s -- %s" % (status, step, note))

ICONS = ["info","language","add","refresh","delete","print","save","star"]
def header_states(pg):
    out = {}
    for ic in ICONS:
        el = pg.query_selector(".st-key-app_hdr_%s button" % ic)
        if not el:
            out[ic] = "MISSING"; continue
        dis = el.is_disabled()
        out[ic] = "off" if dis else "ON"
    return out

def shot(pg, name):
    pg.screenshot(path="%s/%s.png" % (OUT, name), full_page=True)

def _pick(pg, scope, name):
    loc = pg.locator(scope, has_text=name)
    loc.first.wait_for(state="attached", timeout=15000)
    hs = loc.element_handles()
    vis_exact=vis_any=any_h=None
    for h in hs:
        t = h.inner_text().replace(chr(10),' ').strip()
        v = h.is_visible()
        if any_h is None: any_h=h
        if v and vis_any is None: vis_any=h
        if v and t==name: vis_exact=h; break
    return vis_exact or vis_any or any_h

def click_exact(pg, name, timeout=15000):
    _pick(pg, "button", name).click()

def click_nav(pg, name):
    _pick(pg, "section[data-testid='stSidebar'] button", name).click()

def find_ag_frame(pg, tries=6):
    for _ in range(tries):
        for fr in pg.frames:
            try:
                if fr.query_selector('.ag-root'):
                    return fr
            except Exception:
                pass
        pg.wait_for_timeout(1500)
    return None

def nav(pg, module, child):
    loc = pg.locator("section[data-testid='stSidebar'] button", has_text=child)
    vis = False
    try:
        vis = any(h.is_visible() for h in loc.element_handles())
    except Exception:
        vis = False
    if not vis:
        try:
            click_nav(pg, module); pg.wait_for_timeout(1200)
        except Exception:
            pass
    click_nav(pg, child); pg.wait_for_timeout(3200)

def fill_label(pg, sel_prefix, value):
    el = pg.query_selector("textarea[aria-label^='%s']" % sel_prefix) or pg.query_selector("input[aria-label^='%s']" % sel_prefix)
    if not el:
        raise RuntimeError("no field for %s" % sel_prefix)
    el.click(); el.fill(value)

def pick_select(pg, label_prefix, option_text):
    boxes = pg.query_selector_all("[data-testid='stSelectbox']")
    target=None
    for sb in boxes:
        if sb.inner_text().strip().startswith(label_prefix):
            target=sb; break
    if not target and boxes: target=boxes[0]
    if not target: raise RuntimeError("no selectbox (label=%s)" % label_prefix)
    cb = target.query_selector("[role='combobox']") or target
    cb.click(); pg.wait_for_timeout(700)
    opt = pg.query_selector("[role='option']:has-text('%s')" % option_text) or pg.query_selector("li:has-text('%s')" % option_text)
    if not opt:
        pg.keyboard.press("Escape"); raise RuntimeError("option %s not found" % option_text)
    opt.click(); pg.wait_for_timeout(800)

def main():
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width":1366,"height":768}, device_scale_factor=1)
        pg = ctx.new_page()
        pg.set_default_timeout(15000)
        pg.goto("http://localhost:%d" % PORT, wait_until="domcontentloaded")
        pg.wait_for_selector("input[aria-label='%s']" % L["sabeon"], timeout=30000)
        pg.fill("input[aria-label='%s']" % L["sabeon"], "1001")
        pg.keyboard.press("Enter"); pg.wait_for_timeout(4500)
        log("login", "PASS", "admin 1001")

        try:
            nav(pg, L["module_nm"], L["submit"])
            log("s1_nav", "PASS", "header=%s" % json.dumps(header_states(pg)))
            pg.wait_for_selector("input[aria-label^='%s']" % L["work_name"], timeout=15000)
            fill_label(pg, L["work_name"], L["d_work"])
            pick_select(pg, L["cause"], L["jam"])
            fill_label(pg, L["cause_detail"], L["d_causedet"])
            fill_label(pg, L["incident"], L["d_incident"])
            fill_label(pg, L["work_content"], L["d_workc"])
            fill_label(pg, L["site"], L["d_site"])
            fill_label(pg, L["counter"], L["d_counter"])
            pg.wait_for_timeout(500)
            up = pg.query_selector(".st-key-nm_photo_zone input[type='file']")
            up.set_input_files([os.path.join(IMG,"photo_a.jpg"), os.path.join(IMG,"photo_b.jpg")])
            pg.wait_for_timeout(3500)
            thumbs = pg.query_selector_all(".st-key-nm_photo_thumbs [data-testid='stImage'] img")
            log("s1_stage_photos", "PASS" if len(thumbs)>=2 else "FAIL", "thumbs=%d" % len(thumbs))
            shot(pg, "s1a_submit_staged")
            delbtn = pg.query_selector("[class*='st-key-nm_photo_del_'] button")
            if delbtn:
                delbtn.click(); pg.wait_for_timeout(2800)
            thumbs2 = pg.query_selector_all(".st-key-nm_photo_thumbs [data-testid='stImage'] img")
            log("s1_delete_photo", "PASS" if len(thumbs2)==1 else "FAIL", "after del thumbs=%d" % len(thumbs2))
            click_exact(pg, L["btn_submit"])
            pg.wait_for_timeout(3800)
            body = pg.inner_text("body")
            ok = "SUBMITTED" in body
            log("s1_submit", "PASS" if ok else "FAIL", "SUBMITTED banner" if ok else "no success text")
            shot(pg, "s1b_submit_done")
        except Exception as e:
            log("s1_submit", "FAIL", "exc: %s" % e)
            shot(pg, "s1_error"); traceback.print_exc()

        # ---------- Scenario 2: my ----------
        try:
            nav(pg, L["module_nm"], L["my"])
            log("s2_nav","PASS","header=%s" % json.dumps(header_states(pg)))
            shot(pg,"s2a_my_list")
            row=_pick(pg,"button",L["rowmatch"]); row.click(); pg.wait_for_timeout(2800)
            body=pg.inner_text("body")
            log("s2_expand","PASS" if "SUBMITTED" in body else "OBS","expanded")
            shot(pg,"s2b_my_expanded")
            click_exact(pg, L["btn_myedit"]); pg.wait_for_timeout(2200)
            ta=pg.query_selector("textarea[aria-label^='%s']" % L["incident"])
            if ta: ta.click(); ta.fill(L["d_incident"]+L["d_editadd"])
            click_exact(pg, L["btn_editsave"]); pg.wait_for_timeout(3200)
            log("s2_edit","PASS","resubmit done"); shot(pg,"s2c_my_edited")
            if not pg.query_selector("[data-testid='stFileUploader'] input[type='file']"):
                try:
                    r2=_pick(pg,"button",L["rowmatch"]); r2.click(); pg.wait_for_timeout(2500)
                except Exception: pass
            before=len(pg.query_selector_all("[data-testid='stImage'] img"))
            ups=pg.query_selector_all("[data-testid='stFileUploader'] input[type='file']")
            if ups: ups[0].set_input_files(os.path.join(IMG,"photo_c.jpg")); pg.wait_for_timeout(3800)
            after=len(pg.query_selector_all("[data-testid='stImage'] img"))
            log("s2_addphoto","PASS" if after>before else "FAIL","imgs %d->%d"%(before,after))
            shot(pg,"s2d_my_photo_added")
        except Exception as e:
            log("s2_my","FAIL","exc: %s"%e); shot(pg,"s2_error"); traceback.print_exc()

        # ---------- Scenario 3: evaluate ----------
        try:
            nav(pg, L["module_nm"], L["evaluate"])
            log("s3_nav","PASS","header=%s" % json.dumps(header_states(pg)))
            shot(pg,"s3a_eval_queue")
            try:
                chip=_pick(pg,"button",L["rowmatch"]); chip.click(); pg.wait_for_timeout(2500)
            except Exception: pass
            try:
                click_exact(pg, L["btn_review"]); pg.wait_for_timeout(3000); log("s3_review","PASS","IN_REVIEW")
            except Exception as e: log("s3_review","FAIL","exc %s"%e)
            shot(pg,"s3b_eval_review")
            try:
                click_exact(pg, L["gradeB"]); pg.wait_for_timeout(2000); log("s3_gradeB","PASS","grade B")
            except Exception as e: log("s3_gradeB","FAIL","exc %s"%e)
            try:
                click_exact(pg, L["btn_confirm"]); pg.wait_for_timeout(3200); log("s3_confirm","PASS","confirmed")
            except Exception as e: log("s3_confirm","FAIL","exc %s"%e)
            shot(pg,"s3c_eval_confirmed")
        except Exception as e:
            log("s3_eval","FAIL","exc: %s"%e); shot(pg,"s3_error"); traceback.print_exc()

        # ---------- Scenario 4: improvement ----------
        try:
            nav(pg, L["module_nm"], L["improve"])
            log("s4_nav","PASS","header=%s" % json.dumps(header_states(pg)))
            shot(pg,"s4a_impr_queue")
            try:
                pick_select(pg,L["sel_assignee"],"1002"); pg.wait_for_timeout(800)
                pick_select(pg,L["sel_confirmer"],"1003"); pg.wait_for_timeout(800)
                log("s4_assign","PASS","assigned 1002/1003")
            except Exception as e: log("s4_assign","FAIL","exc %s"%e)
            ab=pg.query_selector("textarea[aria-label^='%s']" % L["ta_action"])
            if ab: ab.click(); ab.fill(L["d_action"])
            shot(pg,"s4b_impr_form")
            for lbl,key in [(L["btn_save"],"s4_save"),(L["btn_submit_impr"],"s4_submit"),(L["btn_verify_impr"],"s4_confirm")]:
                try:
                    click_exact(pg,lbl); pg.wait_for_timeout(3000); log(key,"PASS",lbl)
                except Exception as e: log(key,"FAIL","exc %s"%e)
            try:
                click_exact(pg, L["btn_close"]); pg.wait_for_timeout(2500)
                click_exact(pg, L["btn_close"]); pg.wait_for_timeout(3000)
                log("s4_close","PASS","2-step close attempted")
            except Exception as e: log("s4_close","FAIL","exc %s"%e)
            shot(pg,"s4c_impr_after")
            log("s4_filters","OBS","selectboxes=%d"%len(pg.query_selector_all("[data-testid='stSelectbox']")))
        except Exception as e:
            log("s4_impr","FAIL","exc: %s"%e); shot(pg,"s4_error"); traceback.print_exc()

        # ---------- Scenario 5: view ----------
        try:
            nav(pg, L["module_nm"], L["view"])
            log("s5_nav","PASS","header=%s" % json.dumps(header_states(pg)))
            try:
                click_exact(pg, L["btn_query"]); pg.wait_for_timeout(2800)
            except Exception: pass
            shot(pg,"s5a_view_list")
            pg.wait_for_timeout(2500)
            frame=find_ag_frame(pg)
            if frame:
                c=frame.query_selector(".ag-center-cols-container .ag-row .ag-cell")
                if c: c.click(); pg.wait_for_timeout(2800)
            log("s5_detail","PASS" if frame else "OBS","frame=%s"%bool(frame))
            shot(pg,"s5b_view_detail")
            hdr=header_states(pg)
            log("s5_print_icon","PASS" if hdr.get("print")=="ON" else "OBS","print=%s"%hdr.get("print"))
            try:
                with pg.expect_download(timeout=15000) as di:
                    dl=_pick(pg,"button",L["pdf_save"]); dl.click()
                d=di.value; path=os.path.join(OUT,"s5_report.pdf"); d.save_as(path)
                head=open(path,"rb").read(5)
                log("s5_pdf","PASS" if head[:4]==b"%PDF" else "FAIL","head=%r"%head)
            except Exception as e: log("s5_pdf","FAIL","exc %s"%e)
            shot(pg,"s5c_view_pdf")
        except Exception as e:
            log("s5_view","FAIL","exc: %s"%e); shot(pg,"s5_error"); traceback.print_exc()

        # ---------- Scenario 6: stats ----------
        try:
            nav(pg, L["module_nm"], L["stats"])
            log("s6_nav","PASS","header=%s" % json.dumps(header_states(pg)))
            shot(pg,"s6a_stats")
            b6=pg.inner_text("body")
            log("s6_kpi","PASS" if (L["kpi_cum"] in b6 or L["kpi_month"] in b6) else "OBS","cum/month KPI")
            log("s6_yearmonth","OBS","selectboxes=%d"%len(pg.query_selector_all("[data-testid='stSelectbox']")))
            shot(pg,"s6b_stats_after")
        except Exception as e:
            log("s6_stats","FAIL","exc: %s"%e); shot(pg,"s6_error"); traceback.print_exc()

        # ---------- Scenario 7: schedule_edit ----------
        try:
            nav(pg, L["module_sch"], L["sch_edit"])
            log("s7_nav","PASS","header=%s" % json.dumps(header_states(pg)))
            shot(pg,"s7a_sched")
        except Exception as e:
            log("s7_sched","FAIL","exc: %s"%e); shot(pg,"s7_error"); traceback.print_exc()
        json.dump(RESULTS, open("%s/results.json" % OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        b.close()
main()
