"""Writes the website pages into docs/ (plain HTML, no build step on the server).  Run:  python tools/build_site.py

The look: an engineering drawing.  Paper, ink and hairlines; a live gear drawing on the home page (docs/drawing.js redraws it; the picture
written here is what a browser without scripts shows); the footer is a title block.  Pictures and videos are real ones made by the program.
This file needs nothing but Python (it also runs on the bare machine that builds the preview site).
"""
import math
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs")
REPO = "https://github.com/Bubbletoppoet47/OpenPara"
MAIL = "inquiries.openpara@gmail.com"
NAV = [("features.html", "Features"), ("guides.html", "Guides"), ("about.html", "About")]


def version():
    """The version of this copy of the program (the page's script replaces it with the newest release when it can)."""
    try:
        return re.search(r'__version__\s*=\s*"([^"]+)"', open(os.path.join(ROOT, "version.py"), encoding="utf-8").read()).group(1)
    except (OSError, AttributeError):
        return ""


VER = version()


# ------------------------------------------------------------------ the gear drawing (the same sums as docs/drawing.js)
def num(v):
    """A dimension as a draughtsman writes it: no trailing zeros."""
    return f"{v:.2f}".rstrip("0").rstrip(".")


def gear_outline(z, m, cx, cy, s, alpha=math.radians(20.0)):
    """SVG path of a spur gear with involute flanks: z teeth, module m (mm), drawn at s px per mm around (cx, cy)."""
    r = m * z / 2.0
    rb, ra, rf = r * math.cos(alpha), r + m, r - 1.25 * m
    inv = lambda phi: math.tan(phi) - phi
    half = math.pi / (2 * z) + inv(alpha)                 # half the tooth, as an angle, where the flank leaves the base circle
    r0 = max(rb, rf + 0.3 * m)                            # below this the flank runs into the root with a fillet
    flank = []
    for k in range(7):
        rho = r0 + (ra - r0) * k / 6.0
        flank.append((rho, half - inv(math.acos(min(1.0, rb / rho)))))
    a0, at = flank[0][1], flank[-1][1]
    fil = min(0.35 * m / rf, 0.8 * (math.pi / z - a0))    # the fillet, as an angle on the root circle
    pt = lambda rho, ang: f"{cx + s * rho * math.cos(ang):.2f} {cy + s * rho * math.sin(ang):.2f}"
    arc = lambda rad: f"A{s * rad:.2f} {s * rad:.2f} 0 0 1 "
    d = []
    for i in range(z):
        c = 2 * math.pi * i / z - math.pi / 2
        d.append(("M" if i == 0 else arc(rf)) + pt(rf, c - a0 - fil) + "Q" + pt(rf, c - a0) + " " + pt(r0, c - a0))
        d += ["L" + pt(rho, c - a) for rho, a in flank[1:]]
        d.append(arc(ra) + pt(ra, c + at))
        d += ["L" + pt(rho, c + a) for rho, a in reversed(flank[:-1])]
        d.append("Q" + pt(rf, c + a0) + " " + pt(rf, c + a0 + fil))
    d.append(arc(rf) + pt(rf, -math.pi / 2 - a0 - fil) + "Z")
    return "".join(d)


def gear_drawing(z=20, m=2.0):
    """The hero drawing: outline, pitch circle, centre lines, the outside diameter as a dimension, a scale bar, and the table of sizes."""
    cx, cy, R = 260.0, 262.0, 168.0
    d, da, df, db = m * z, m * (z + 2), m * (z - 2.5), m * z * math.cos(math.radians(20.0))
    s = R / (da / 2.0)
    bar_mm = next((b for b in (50, 20, 10, 5, 2, 1) if b * s <= 120), 1)
    lx, ly = cx + s * d / 2 * math.cos(math.radians(38)), cy + s * d / 2 * math.sin(math.radians(38))
    by = cy + R + 24
    return f'''<figure class="sheet" id="gear">
<svg viewBox="0 0 520 470" role="img" aria-labelledby="gear-title">
<title id="gear-title">Drawing of a spur gear with its outside diameter and pitch diameter</title>
<path class="centre" d="M{cx - R - 16:g} {cy:g}H{cx + R + 16:g}M{cx:g} {cy - R - 16:g}V{cy + R + 16:g}"/>
<path id="g-out" class="part" d="{gear_outline(z, m, cx, cy, s)}"/>
<circle id="g-bore" class="part" cx="{cx:g}" cy="{cy:g}" r="{s * 0.16 * d:.2f}"/>
<circle id="g-pitch" class="pitch" cx="{cx:g}" cy="{cy:g}" r="{s * d / 2:.2f}"/>
<g class="dim"><path d="M{cx - R:g} {cy - 10:g}V46M{cx + R:g} {cy - 10:g}V46M{cx - R:g} 56H{cx + R:g}"/><path class="arrow" d="M{cx - R:g} 56l11 -3.6v7.2zM{cx + R:g} 56l-11 -3.6v7.2z"/>
<text id="g-da" x="{cx:g}" y="46" text-anchor="middle">&#8960; {num(da)}</text>
<path id="g-lead" d="M{lx:.1f} {ly:.1f}L{cx + R - 38:g} {cy + R - 2:g}h78"/><text id="g-d" x="{cx + R + 40:g}" y="{cy + R - 9:g}" text-anchor="end">pitch &#8960; {num(d)}</text>
<path id="g-bar" d="M40 {by - 7:g}v7h{bar_mm * s:.1f}v-7"/><text id="g-bar-t" x="40" y="{by - 13:g}">{bar_mm} mm</text></g>
</svg>
<div class="knobs" hidden>
<label for="k-z">Number of teeth <output id="o-z" for="k-z">{z}</output></label><input id="k-z" type="range" min="10" max="48" step="1" value="{z}">
<label for="k-m">Module <output id="o-m" for="k-m">{num(m)} mm</output></label><input id="k-m" type="range" min="1" max="6" step="0.5" value="{num(m)}">
</div>
<table class="sizes"><tbody>
<tr><th scope="row">Pitch diameter</th><td id="t-d">{num(d)} mm</td><th scope="row">Root diameter</th><td id="t-df">{num(df)} mm</td></tr>
<tr><th scope="row">Outside diameter</th><td id="t-da">{num(da)} mm</td><th scope="row">Base diameter</th><td id="t-db">{num(db)} mm</td></tr>
</tbody></table>
<figcaption>Drag a number and the gear is redrawn, with true involute teeth. The Part Generator in OpenPara builds the solid from the same few numbers.</figcaption>
</figure>'''


# ------------------------------------------------------------------ the page frame
def page(fn, title, desc, main, cls=""):
    nav = "".join(f'<a href="{h}"{" aria-current=page" if h == fn else ""}>{t}</a>' for h, t in NAV)
    html = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><meta name="description" content="{desc}"><meta name="theme-color" content="#0f2742">
<link rel="icon" type="image/svg+xml" href="assets/openpara-logo-small.svg"><link rel="apple-touch-icon" href="icon.png">
<meta property="og:type" content="website"><meta property="og:title" content="{title}"><meta property="og:description" content="{desc}"><meta property="og:image" content="img/planetary.jpg">
<link rel="preload" href="assets/fonts/sofia-sans.woff2" as="font" type="font/woff2" crossorigin>
<link rel="preload" href="assets/fonts/sofia-sans-condensed.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="style.css"></head><body{f' class="{cls}"' if cls else ""}>
<a class="skip" href="#main">Skip to the content</a>
<header class="top"><div class="wrap"><a class="brand" href="index.html"><img src="assets/openpara-logo-small.svg" width="30" height="30" alt="">OpenPara</a>
<nav aria-label="Main">{nav}<a href="{REPO}">GitHub</a><a class="get" href="download.html"{" aria-current=page" if fn == "download.html" else ""}>Download</a></nav></div></header>
<main id="main">{main}</main>
<footer><div class="wrap"><div class="block">
<div class="cell wide"><span class="k">Project</span><span class="v name"><img src="assets/openpara-logo-small.svg" width="26" height="26" alt="">OpenPara</span><span class="s">Free, open-source parametric CAD for hobbyists, students and engineers.</span></div>
<div class="cell"><span class="k">Licence</span><span class="v"><a href="about.html#licence">GNU GPL v3</a></span><span class="s">Use it, study it, change it, share it.</span></div>
<div class="cell"><span class="k">Version</span><span class="v" id="foot-ver">{VER}</span><span class="s"><a href="{REPO}/releases">All releases</a></span></div>
<div class="cell wide"><span class="k">Pages</span><span class="links"><a href="download.html">Download</a><a href="features.html">Features</a><a href="guides.html">Guides</a><a href="about.html">About</a></span></div>
<div class="cell"><span class="k">Source</span><span class="links"><a href="{REPO}">GitHub</a><a href="{REPO}/issues">Report a problem</a></span></div>
<div class="cell"><span class="k">Inquiries</span><span class="links"><a href="mailto:{MAIL}">{MAIL}</a></span></div>
</div></div></footer>
<script src="site.js"></script><script src="drawing.js"></script></body></html>'''
    open(os.path.join(OUT, fn), "w", encoding="utf-8").write(html)


def pagehead(title, lead):
    return f'<div class="page-head"><div class="wrap"><h1>{title}</h1><p>{lead}</p></div></div>'


def clip(name, w, h, alt, caption):
    """A short silent video made by the program's own Export animation.  It plays by itself and repeats; drawing.js stops it for people
    who asked their device for less motion (they get the player's own buttons instead)."""
    return (f'<figure class="clip"><video autoplay loop muted playsinline preload="metadata" width="{w}" height="{h}" poster="video/{name}.jpg" aria-label="{alt}">'
            f'<source src="video/{name}.mp4" type="video/mp4"><source src="video/{name}.webm" type="video/webm"></video><figcaption>{caption}</figcaption></figure>')


def shot(src, w, h, alt, caption, lazy=True):
    return (f'<figure class="shot"><img src="img/{src}" width="{w}" height="{h}" alt="{alt}"{" loading=lazy" if lazy else ""}>'
            f'<figcaption>{caption}</figcaption></figure>')


FEA_CLIP = clip("fea-bracket", 960, 640, "Animation: the stress in a wall bracket grows as the load on its arm is raised",
                "2D FEA. A steel wall bracket held at three bolt holes while the load on the end of its arm is raised to about 890 N. "
                "The colour is the von Mises stress; the bending is drawn larger than it is.")
CFD_CLIP = clip("cfd-wing", 960, 640, "Animation: tracer particles follow the air around a wing section",
                "2D CFD. Air passing a wing section set at an angle. The colour is the speed of the air; the tracer particles show where it goes.")

# ------------------------------------------------------------------ home
home = f'''<section class="hero"><div class="wrap"><div class="say">
<h1>Parametric CAD,<br>free for everyone.</h1>
<p class="lede">OpenPara is an open-source modeller for parts and assemblies. Draw a sketch, give it dimensions, and build on it. Change a number later and everything that depends on it is rebuilt.</p>
<div class="btns"><a class="btn go" href="download.html">Download for Windows <span id="ver-btn">{f"({VER})" if VER else ""}</span></a><a class="more" href="features.html">See what it does</a></div>
<p class="fine">No account and no subscription. Linux and macOS run it from source.</p></div>
{gear_drawing()}</div></section>

<section class="plain"><div class="wrap">
{shot("ui-part.webp", 1440, 860, "The OpenPara window: the feature tree on the left and a helical gear in the 3D view", "OpenPara with a helical gear from the Part Generator. It is an ordinary part: add a keyway, cut a pocket, or use it in an assembly.", lazy=False)}
</div></section>

<section><div class="wrap"><div class="intro"><h2>What is in it</h2><p>The modeller is the core. The rest are add-ons that install from inside the program, so you only carry what you use.</p></div>
<table class="parts"><thead><tr><th scope="col">Part of the program</th><th scope="col">What it is for</th><th scope="col">Comes as</th></tr></thead><tbody>
<tr><th scope="row"><a href="features.html#parts">Parts</a></th><td>Constrained sketches, then extrude, cut, revolve, sweep, loft, fillet and chamfer. Named variables and formulas drive the dimensions.</td><td>Built in</td></tr>
<tr><th scope="row"><a href="features.html#assemblies">Assemblies</a></th><td>Parts and sub-assemblies held together by mates. Positions, mate values and pattern spacing can be formulas.</td><td>Built in</td></tr>
<tr><th scope="row"><a href="features.html#partgen">Part Generator</a></th><td>Spur, helical, herringbone and ring gears, gear trains and planetary sets, from a few numbers.</td><td>Add-on</td></tr>
<tr><th scope="row"><a href="features.html#truss">Truss Generator</a></th><td>Turns the lines of a sketch into members cut to length with angled ends, and exports the cut list.</td><td>Add-on</td></tr>
<tr><th scope="row"><a href="features.html#simulation">Simulation</a></th><td>Frames and trusses (1D FEA), flat parts under load (2D FEA) and flow around a profile (2D CFD).</td><td>Add-on</td></tr>
<tr><th scope="row"><a href="features.html#visualize">Visualize</a></th><td>Lit previews and ray-traced pictures and videos of a part or an assembly.</td><td>Add-on</td></tr>
</tbody></table></div></section>

<section><div class="wrap"><div class="intro"><h2>Test it before you build it</h2><p>The Simulation add-on works on a sketch or on a slice of a part, so a question about strength or flow can be answered while the design is still easy to change.</p></div>
<div class="pair">{FEA_CLIP}{CFD_CLIP}</div>
<p class="after">Both clips were drawn by OpenPara. <a href="features.html#simulation">What the solvers do</a>, and <a href="features.html#limits">what they do not</a>.</p></div></section>

<section><div class="wrap"><div class="split">
<div><h2>Gears that fit the space you have</h2>
<p>Type the centre distance you have room for. OpenPara picks the tooth counts, adds the profile shift needed to reach that distance exactly, and tells you where to put each gear.</p>
<ul class="list"><li>Trains of up to three gears, straight or bent at the middle gear</li><li>Planetary sets, with the planet counts that work and the ratios for each way of holding it</li><li>Each gear opens as its own part, ready to edit</li></ul>
<p><a href="guides.html#train">Read the gear train guide</a></p></div>
{shot("train.jpg", 980, 840, "A train of three helical gears generated in OpenPara", "A train of three helical gears from the Part Generator.")}</div></div></section>

<section><div class="wrap"><div class="paths">
<div><h2>New to CAD?</h2><p>You do not need an engineering degree. Type a few numbers into the Part Generator and get a real, accurate gear. Then open it and change it.</p><p><a href="guides.html#first">Make your first part</a></p></div>
<div><h2>Want the details?</h2><p>Constraints, formulas, units and mates in one place, and a plain account of what has been checked and what has not.</p><p><a href="features.html#limits">Read what is checked</a></p></div></div></div></section>

<section class="get-it"><div class="wrap"><div><h2>Get OpenPara</h2><p>Free to download. The installer needs no administrator rights.</p></div><a class="btn go" href="download.html">Go to the download</a></div></section>'''
page("index.html", "OpenPara - free parametric CAD", "OpenPara is a free, open-source parametric CAD modeller for parts and assemblies, with add-ons for gears, trusses, simulation and rendering.", home, "home")

# ------------------------------------------------------------------ download
dl = pagehead("Download", "Free. No account needed.") + f'''<section class="first"><div class="wrap"><div class="prose">
<div class="dl"><div><h2>OpenPara for Windows</h2><p>Installs for your user only, with its own Python and every package it needs. Adds a Start-menu entry.</p><p class="meta" id="dl-info">Latest version: see the releases page.</p></div>
<a class="btn go" id="dl-exe" href="{REPO}/releases/latest">Download the installer</a></div>
<h2>Install in three steps</h2>
<ol class="steps"><li><b>Download and run</b> <code>OpenPara-Setup-&lt;version&gt;.exe</code>. No administrator rights are needed.</li><li><b>Start OpenPara</b> from the Start menu.</li><li><b>Stay up to date</b> with <b>Help &gt; Check for updates</b>. New versions install for you, and your settings and material library are kept.</li></ol>
<h2>Linux and macOS, or from source</h2><p>OpenPara is written in Python. Install the packages and run it:</p>
<pre><code>git clone {REPO}.git
cd OpenPara
pip install -r requirements.txt
python gpd_app.py</code></pre>
<p class="note"><b>Tested on Windows.</b> The Windows installer is the tested way to run OpenPara. Running from source on Linux or macOS should work but has had less testing.</p>
<h2>Other versions</h2><p>Every release is on the <a href="{REPO}/releases">releases page</a>, each with its notes.</p>
<h2>Questions</h2><p>Write to <a href="mailto:{MAIL}">{MAIL}</a>. For a fault in the program, the <a href="{REPO}/issues">issues page</a> is the quickest way to get it looked at.</p></div></div></section>'''
page("download.html", "Download - OpenPara", "Download the OpenPara Windows installer, or run it from source.", dl)


# ------------------------------------------------------------------ features
def spec(anchor, title, kind, items, extra=""):
    lis = "".join(f"<li>{i}</li>" for i in items)
    return (f'<div class="spec" id="{anchor}"><div class="what"><h2>{title}</h2><p class="kind">{kind}</p></div>'
            f'<div class="has"><ul class="list">{lis}</ul>{extra}</div></div>')


feat = pagehead("Features", "What is in OpenPara today.") + f'''<section class="first"><div class="wrap">
{spec("parts", "Parts", "Built in", [
    "2D sketches with a constraint solver and dimensions",
    "Extrude, cut, revolve, sweep (including twisted sweeps) and loft, each as a boss or a cut",
    "Fillet, chamfer, patterns, mirrors, reference planes and axes; right-click a plane or a face to sketch on it",
    "Named variables (Globals), formulas and configurations",
    "One program-wide unit system: mm, cm, m, in, ft, N, kN, kip and more",
    "STEP and STL export, and STEP import",
    "Add-ons install from File &gt; Add-ons and update on their own"],
    shot("ui-part.webp", 1440, 860, "The OpenPara window with the feature tree and a helical gear in the 3D view", "The part window: the ribbon, the feature tree and the 3D view."))}
{spec("assemblies", "Assemblies", "Built in", [
    "Mates, sub-assemblies and patterns",
    "Variables of their own",
    "Positions, mate values and pattern spacing can be formulas"])}
{spec("partgen", "Part Generator", "Add-on", [
    "Spur, helical, herringbone and internal ring gears with true involute teeth and exact tooth counts",
    "Size by module, diametral pitch, pitch diameter or outside diameter; optional profile shift, backlash and bore",
    "Gear trains of up to three gears, sized from centre distances, ratios or tooth counts",
    "Planetary sets (sun, planets, ring) with valid planet counts and the ratios for each way of holding them",
    "Each gear opens as its own part. OpenPara gives you the centre distances and turn angles; you build the assembly"],
    shot("planetary.jpg", 1360, 790, "A planetary gear set with a sun gear, three planet gears and a ring gear", "A planetary set made with the Part Generator."))}
{spec("truss", "Truss Generator", "Add-on", [
    "Builds the members of a truss from the lines of a sketch: each member is a profile cut to length with angled ends",
    "Import a sketch from any open part tab, then change the sketch and refresh to rebuild",
    "Exports a cut list",
    "A truss is saved as its own .truss folder, so it is always clear what the members came from"])}
{spec("simulation", "Simulation", "Add-on", [
    "<b>1D FEA</b> for frames and trusses: members with real cross-sections, rigid or pinned joints, supports, point and line loads, wind and snow. It shows displacement, stress, the factor of safety, and the bending moment, shear force and axial force diagrams",
    "<b>2D FEA</b> for flat parts in plane stress or plane strain: supports, forces, pressures, bolts and contact, with a linear solver and a nonlinear one that follows yielding",
    "<b>2D CFD</b> for the flow around a profile, laminar or with the k-omega SST turbulence model: speed, pressure and vorticity, the forces on the body, and tracer particles",
    "Each works on a sketch, or on a slice of a part or an assembly, and keeps its own copy of it",
    "Any result can be saved as an animation (WebP, PNG, GIF or MP4)"],
    f'<div class="pair">{FEA_CLIP}{CFD_CLIP}</div>'
    + shot("ui-fea1d.webp", 1440, 860, "The 1D FEA tab with a roof truss coloured by stress and its deflected shape drawn dashed", "1D FEA of a roof truss under three loads: the von Mises stress in each member, and the deflected shape drawn dashed."))}
{spec("visualize", "Visualize", "Add-on", [
    "A live, lit preview of a part or an assembly",
    "Ray-traced pictures and videos, with sun, lights, a floor and cameras",
    "A Visualize project keeps its own copy of the model"])}
{spec("more", "More add-ons", "Add-ons", [
    "<b>Annotator</b>: draw boxes on photos and video frames to build an image dataset, and share it as a zip",
    "<b>Trainer</b>: train a YOLO model on Annotator datasets, in the background",
    "<b>Motor Control</b>: set up, calibrate and test a motor on an ODESC or ODrive-style board, with live plots"])}
{spec("open", "Open source", "GPL-3.0", [
    "Read the code, change it, share it",
    "Built on build123d (OpenCascade), PyQt6, and pyvista / VTK",
    f'All the code is on <a href="{REPO}">GitHub</a>'])}
</div></section>
<section id="limits"><div class="wrap"><div class="split top"><div><h2>What is checked, and what is not</h2><p>We would rather tell you than have you find out.</p></div>
<ul class="list">
<li>The gear geometry is checked against textbook values and against the real solids: meshing gears do not overlap, and a deliberately wrong spacing does. That is a geometry check, not a strength or life calculation.</li>
<li>The simulation tools are 1D and 2D. They are for understanding a design early and comparing options. They do not replace a full 3D analysis, a design-code check or a test.</li>
<li>OpenPara is young software under active development. Expect rough edges, and please report them.</li></ul></div></div></section>'''
page("features.html", "Features - OpenPara", "Parametric parts and assemblies in one free program, with add-ons for gears, trusses, simulation and rendering.", feat)

# ------------------------------------------------------------------ guides
guides = pagehead("Guides", "Start where you are.") + f'''<section class="first"><div class="wrap"><div class="layout"><nav class="toc" aria-label="On this page"><a href="#first">Your first part</a><a href="#train">A gear train</a><a href="#planetary">A planetary set</a></nav>
<div class="prose">
<h2 id="first">Your first part: a gear</h2><p>About ten minutes, and no CAD experience needed.</p>
<ol class="steps"><li>Start OpenPara and press <b>Part Generator</b> on the ribbon.</li><li>Choose <b>Spur gear</b>. Leave Module at 2 and Number of teeth at 20.</li><li>Look at the 3D preview. The numbers on the right (pitch diameter, outside diameter and so on) update as you type.</li><li>Change the face width and the bore diameter to what you need.</li><li>Press <b>OK</b>. The gear is added as one feature. Double-click it in the tree any time to change the numbers.</li><li>Save with <b>File &gt; Save</b>.</li></ol>
<h2 id="train">A gear train from centre distances</h2>
<ol class="steps"><li>In the Part Generator, open the <b>Gear systems</b> tab and choose <b>Gear train</b>.</li><li>Define gear 1: module, teeth, pressure angle, width and bore. Use a helix angle above 0 for helical gears; the hands alternate for you.</li><li>For gear 2, choose <b>Centre distance</b> and type the distance you have room for. OpenPara picks the nearest whole tooth count and uses profile shift to make up the small remainder.</li><li>For a third gear, choose another distance, a ratio, or the total of both distances. You can bend the chain at the middle gear.</li><li>Read the results: centre distances, ratios, and each gear's position and turn angle.</li><li>Press <b>Open the parts</b>. Each gear opens as its own part, unsaved. Put them together in an assembly using the positions and turn angles shown.</li></ol>
<p class="note">If a distance cannot be reached with whole teeth and a small shift, OpenPara says so and tells you the nearest distance it can reach.</p>
<h2 id="planetary">A planetary set</h2>
<ol class="steps"><li>In <b>Gear systems</b>, choose <b>Planetary set</b>.</li><li>Choose which two gears set the size, for example sun and planet teeth. The ring always has sun + 2 &times; planet teeth.</li><li>Choose the number of planets. They must be equally spaced, so the sun plus ring teeth must divide evenly. If your choice does not work, OpenPara lists the counts that do.</li><li>Read the ratios for holding the ring, the sun or the carrier still.</li><li>Press <b>Open the parts</b>: three parts open (sun, planet, ring). Make the assembly yourself, adding as many planets as you chose, using the angles and radius shown. There is no carrier part.</li></ol>
{shot("planetary.jpg", 1360, 790, "A planetary gear set with a sun gear, three planet gears and a ring gear", "A planetary set made with the Part Generator.")}
</div></div></div></section>'''
page("guides.html", "Guides - OpenPara", "Step-by-step guides: your first part, gear trains and planetary sets.", guides)

# ------------------------------------------------------------------ about
about = pagehead("About OpenPara", "Free software, built in the open.") + f'''<section class="first"><div class="wrap"><div class="prose">
<p class="lede">OpenPara aims to be a parametric CAD program that anyone can use: someone making a part for a home project, a student, or an engineer who wants a modeller they can read and extend.</p>
<h2 id="licence">Licence</h2><p>OpenPara is free software under the <a href="https://www.gnu.org/licenses/gpl-3.0.html">GNU General Public License, version 3</a>. You may use it, study it, change it and share it, and if you share a changed version it must stay free in the same way. The full text is in the <a href="{REPO}/blob/main/LICENSE">LICENSE</a> file.</p>
<h2 id="contact">Contact</h2><p>For questions about the project, working together, or anything that is not a fault report, write to <a href="mailto:{MAIL}">{MAIL}</a>.</p>
<h2>Get involved</h2><ul class="list"><li><b>Try it and tell us.</b> Report problems and ideas on the <a href="{REPO}/issues">issues page</a>.</li><li><b>Read or change the code.</b> It is all on <a href="{REPO}">GitHub</a>.</li><li><b>Share your parts and guides.</b> More generators (keyways, bore shapes and other families) are planned.</li></ul>
<h2>Built with</h2><p><a href="https://github.com/gumyr/build123d">build123d</a> and OpenCascade for geometry, PyQt6 for the interface, and pyvista / VTK for 3D views. Thank you to everyone who made those. The website is set in Sofia Sans, under the SIL Open Font License.</p>
</div></div></section>'''
page("about.html", "About - OpenPara", "OpenPara is free software under the GPL-3.0. How to get in touch and how to get involved.", about)
