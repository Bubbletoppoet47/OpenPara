"""render_boards.py <design dir> <out dir> [scale] [board.dc.html ...]

Renders the boards of a Design artifact to PNG, offline, with Chromium (Playwright).

<design dir> holds project/ (the boards and canvas.json), optionally _blob/ (the pictures a board
refers to as /_blob/<id>, saved as <id>.png) and artifact-type/dc-runtime.js. The runtime is the one
the Design artifact type publishes; it is not kept in this repository. If it is not in the design
dir, point the environment variable DC_RUNTIME at a copy. The runtime is copied beside the boards
as support.js, which is what the boards load.

Only boards listed in project/canvas.json are rendered; name some to render only those.
Use scale 2 for pictures a person will read (PNG at twice the board's size).
Boards load Inter from Google Fonts; offline, Chromium falls back to an installed Inter or a system font.
A board that imports another (dc-import) does not render offline: render the board it imports.
"""
import json, os, re, shutil, sys, tempfile
from playwright.sync_api import sync_playwright
src, out = sys.argv[1], sys.argv[2]
scale = float(sys.argv[3]) if len(sys.argv) > 3 else 2.0
only = set(sys.argv[4:])
canvas = json.load(open(os.path.join(src, "project", "canvas.json")))
tmp = tempfile.mkdtemp()
for f in os.listdir(os.path.join(src, "project")):
    if f.endswith(".html"):
        t = open(os.path.join(src, "project", f), encoding="utf-8").read()
        t = re.sub(r'/_blob/([0-9a-f]{32})', r'_blob/\1.png', t)
        open(os.path.join(tmp, f), "w", encoding="utf-8").write(t)
    else:
        shutil.copy(os.path.join(src, "project", f), tmp)
if os.path.isdir(os.path.join(src, "_blob")):
    shutil.copytree(os.path.join(src, "_blob"), os.path.join(tmp, "_blob"))
rt = os.path.join(src, "artifact-type", "dc-runtime.js")
if not os.path.exists(rt):
    rt = os.environ["DC_RUNTIME"]
shutil.copy(rt, os.path.join(tmp, "support.js"))
os.makedirs(out, exist_ok=True)
with sync_playwright() as p:
    b = p.chromium.launch()
    for name, bd in canvas["boards"].items():
        if only and name not in only:
            continue
        pg = b.new_page(viewport={"width": int(bd["w"]), "height": int(bd["h"])}, device_scale_factor=scale)
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto("file://" + os.path.join(tmp, name))
        pg.wait_for_timeout(1500)
        dest = os.path.join(out, name.replace(".dc.html", "") + ".png")
        pg.screenshot(path=dest, full_page=False)
        print(name, bd["w"], bd["h"], os.path.getsize(dest), "errors:", errs[:2])
        pg.close()
    b.close()
shutil.rmtree(tmp)
