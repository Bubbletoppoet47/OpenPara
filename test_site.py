"""The website (docs/, written by tools/build_site.py): every page is written, every local link, picture, video, font and script exists, the
inquiries address is on every page, the gear drawing of the home page is the one docs/drawing.js draws, and the preview copy is complete.
python test_site.py"""
import math
import os
import re
import runpy
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "docs")
ns = runpy.run_path(os.path.join(HERE, "tools", "build_site.py"))
PAGES = ["index.html", "download.html", "features.html", "guides.html", "about.html"]
MAIL = "inquiries.openpara@gmail.com"
assert ns["MAIL"] == MAIL

ids = {}
for pg in PAGES:
    t = open(os.path.join(DOCS, pg), encoding="utf-8").read()
    ids[pg] = set(re.findall(r'\bid="([^"]+)"', t))
for pg in PAGES:
    t = open(os.path.join(DOCS, pg), encoding="utf-8").read()
    assert t.count(f"mailto:{MAIL}") >= 1, f"{pg}: the inquiries address is missing"
    assert "coming soon" not in t and "(coming)" not in t, f"{pg}: a placeholder is left"
    for word in ("Visualize", "Motor Control", "ray-traced", "rendering"):       # not released yet (addons.NOT_RELEASED): the site shows what a download has
        assert word not in t, f"{pg}: mentions {word}, which is not in a normal OpenPara yet"
    assert "<h1" in t and t.count("<h1") == 1, pg
    for ref in re.findall(r'(?:href|src|poster)="([^"]+)"', t):
        if re.match(r"(https?:|mailto:)", ref):
            continue
        path, _, frag = ref.partition("#")
        target = path or pg
        assert os.path.isfile(os.path.join(DOCS, target)), f"{pg}: {ref} does not exist"
        if frag:
            assert frag in ids.get(target, ()), f"{pg}: {ref} points at nothing"
    for img in re.findall(r"<img [^>]*>", t):
        assert " alt=" in img and " width=" in img and " height=" in img, f"{pg}: {img}"
    for v in re.findall(r"<video [^>]*>", t):
        assert " muted" in v and " playsinline" in v and " poster=" in v and " aria-label=" in v, f"{pg}: {v}"
css = open(os.path.join(DOCS, "style.css"), encoding="utf-8").read()
for ref in re.findall(r"url\(([^)]+)\)", css):
    assert os.path.isfile(os.path.join(DOCS, ref.strip("'\""))), ref
assert os.path.isfile(os.path.join(DOCS, "assets", "fonts", "OFL.txt")), "the font licence travels with the fonts"
for v in ("fea-bracket", "cfd-wing"):
    for e in (".mp4", ".webm", ".jpg"):
        assert 0 < os.path.getsize(os.path.join(DOCS, "video", v + e)) < 1_500_000, f"{v}{e} is missing or too heavy for a web page"
home = open(os.path.join(DOCS, "index.html"), encoding="utf-8").read()
assert f'id="foot-ver">{ns["VER"]}<' in home and ns["VER"], "the footer starts with the version of this copy"
assert 'id="ver-btn"' in home and 'id="gear"' in home
feat = open(os.path.join(DOCS, "features.html"), encoding="utf-8").read()
for anchor in ("parts", "assemblies", "partgen", "truss", "simulation", "studies", "limits"):
    assert f'id="{anchor}"' in feat, anchor
assert "Parametric Studies" in home and "ui-study.webp" in feat
dl = open(os.path.join(DOCS, "download.html"), encoding="utf-8").read()
assert 'id="dl-exe"' in dl and 'id="dl-info"' in dl, "site.js fills these in"

# the gear: a closed outline with z teeth, its tips on the outside circle and its roots on the root circle
z, m, s = 20, 2.0, 7.0
d = ns["gear_outline"](z, m, 0.0, 0.0, s)
assert d.startswith("M") and d.endswith("Z")
pts = [(float(a), float(b)) for a, b in re.findall(r"(-?\d+\.\d+) (-?\d+\.\d+)(?=[LAQZ]|$)", d)]
rad = [math.hypot(*p) / s for p in pts]
assert abs(max(rad) - m * (z + 2) / 2) < 1e-2 and abs(min(rad) - m * (z - 2.5) / 2) < 1e-2, (max(rad), min(rad))
assert d.count("A") == 2 * z, "one tip arc and one root arc for each tooth"
js = open(os.path.join(DOCS, "drawing.js"), encoding="utf-8").read()
assert "0.3 * m" in js and "0.35 * m / rf" in js and "0.16 * d" in js, "drawing.js draws the same gear as build_site.py"
assert ns["num"](37.5877) == "37.59" and ns["num"](44.0) == "44" and ns["num"](2.5) == "2.5"

# the preview copy: everything but CNAME, a bar on every page, its own site.js, and the gear script untouched
out = tempfile.mkdtemp(prefix="opara_site_")
try:
    subprocess.check_call([sys.executable, os.path.join(HERE, "tools", "preview_site.py"), DOCS, os.path.join(out, "p")], stdout=subprocess.DEVNULL)
    P = os.path.join(out, "p")
    assert not os.path.exists(os.path.join(P, "CNAME"))
    for pg in PAGES:
        t = open(os.path.join(P, pg), encoding="utf-8").read()
        assert "Preview of the next version" in t and "(preview)</title>" in t, pg
    assert open(os.path.join(P, "drawing.js"), encoding="utf-8").read() == js
    assert "dev-" in open(os.path.join(P, "site.js"), encoding="utf-8").read()
    for f in ("video/fea-bracket.mp4", "video/cfd-wing.mp4", "assets/fonts/sofia-sans.woff2", "img/ui-part.webp"):
        assert os.path.isfile(os.path.join(P, f)), f
finally:
    shutil.rmtree(out, ignore_errors=True)
print("OK site")
