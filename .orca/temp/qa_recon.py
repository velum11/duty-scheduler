import sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from playwright.sync_api import sync_playwright

PORT = 8533
OUT = ".orca/artifacts/claude-design-adopt/final-qa"

def main():
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width":1366,"height":768}, device_scale_factor=1)
        pg = ctx.new_page()
        pg.goto("http://localhost:%d" % PORT, wait_until="domcontentloaded")
        pg.wait_for_selector("input[aria-label='사번']", timeout=30000)
        pg.fill("input[aria-label='사번']", "1001")
        pg.keyboard.press("Enter")
        pg.wait_for_timeout(4500)
        btns = pg.eval_on_selector_all("section[data-testid='stSidebar'] button",
            "els => els.map(e => e.innerText)")
        btns = [b.replace("\n"," ").strip() for b in btns if b.strip()]
        print("SIDEBAR:", json.dumps(btns, ensure_ascii=False))
        hdr = pg.eval_on_selector_all("button[title]",
            "els => els.map(e => e.getAttribute('title') + '|' + e.disabled)")
        print("HDR_TITLED:", json.dumps(hdr, ensure_ascii=False))
        pg.screenshot(path="%s/00_recon_dashboard.png" % OUT, full_page=True)
        b.close()
main()
