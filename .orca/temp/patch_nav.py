import re
f = ".orca/temp/qa_driver.py"
s = open(f, encoding="utf-8").read()
s = s.replace("\r\n", "\n")
addfn = (
"def find_ag_frame(pg, tries=6):\n"
"    for _ in range(tries):\n"
"        for fr in pg.frames:\n"
"            try:\n"
"                if fr.query_selector('.ag-root'):\n"
"                    return fr\n"
"            except Exception:\n"
"                pass\n"
"        pg.wait_for_timeout(1500)\n"
"    return None\n\n"
)
newnav = (
"def nav(pg, module, child):\n"
"    loc = pg.locator(\"section[data-testid='stSidebar'] button\", has_text=child)\n"
"    vis = False\n"
"    try:\n"
"        vis = any(h.is_visible() for h in loc.element_handles())\n"
"    except Exception:\n"
"        vis = False\n"
"    if not vis:\n"
"        try:\n"
"            click_nav(pg, module); pg.wait_for_timeout(1200)\n"
"        except Exception:\n"
"            pass\n"
"    click_nav(pg, child); pg.wait_for_timeout(3200)\n"
)
# replace the nav function body (from 'def nav' up to the next top-level 'def ')
s = re.sub(r"def nav\(pg, module, child\):\n(?:.*\n)*?(?=def fill_label)", addfn + newnav + "\n", s)
open(f, "w", encoding="utf-8", newline="\n").write(s)
print("done; find_ag_frame present:", "def find_ag_frame" in s, "; idempotent nav:", "vis = False" in s)