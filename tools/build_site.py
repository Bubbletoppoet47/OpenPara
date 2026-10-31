"""Writes the website pages into docs/ (plain HTML, no build step on the server).  Run:  python tools/build_site.py"""
import os

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")
REPO = "https://github.com/Bubbletoppoet47/OpenPara"
NAV = [("index.html", "Home"), ("download.html", "Download"), ("features.html", "Features"), ("guides.html", "Guides"), ("about.html", "About")]

ICONS = {
    "cube": '<path d="M12 2.5l8.5 4.7v9.6L12 21.5l-8.5-4.7V7.2z"/><path d="M12 12l8.5-4.8M12 12v9.5M12 12L3.5 7.2"/>',
    "layers": '<path d="M12 3l9 4.8-9 4.8-9-4.8z"/><path d="M3 12.2l9 4.8 9-4.8"/><path d="M3 16.4l9 4.8 9-4.8"/>',
    "gear": '<circle cx="12" cy="12" r="3.2"/><path d="M12 2.8v3M12 18.2v3M2.8 12h3M18.2 12h3M5.5 5.5l2.1 2.1M16.4 16.4l2.1 2.1M18.5 5.5l-2.1 2.1M7.6 16.4l-2.1 2.1"/>',
    "wave": '<path d="M3 17c2.5 0 2.5-10 5-10s2.5 10 5 10 2.5-10 5-10 1.5 5 3 5"/><path d="M3 21h18"/>',
    "camera": '<rect x="3" y="6.5" width="18" height="13" rx="2.5"/><circle cx="12" cy="13" r="3.6"/><path d="M8.5 6.5l1.2-2.5h4.6l1.2 2.5"/>',
    "code": '<path d="M8.5 7L3.5 12l5 5M15.5 7l5 5-5 5M13.5 5l-3 14"/>',
    "play": '<circle cx="12" cy="12" r="10"/><path d="M10 8.5l6 3.5-6 3.5z"/>',
    "dl": '<path d="M12 3.5v12M7 11l5 5 5-5M4 20h16"/>',
}


def icon(name, cls="ico"):
    return f'<div class="{cls}"><svg viewBox="0 0 24 24" aria-hidden="true">{ICONS[name]}</svg></div>'


def svg(name):
    return f'<svg viewBox="0 0 24 24" aria-hidden="true" style="fill:none;stroke:currentColor;stroke-width:1.9;stroke-linecap:round;stroke-linejoin:round">{ICONS[name]}</svg>'


def page(fn, title, desc, main, head=None):
    nav = "".join(f'<a href="{h}"{" class=on aria-current=page" if h == fn else ""}>{t}</a>' for h, t in NAV)
    html = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><meta name="description" content="{desc}"><meta name="theme-color" content="#071f3a">
<link rel="icon" type="image/svg+xml" href="assets/openpara-logo-small.svg"><link rel="apple-touch-icon" href="icon.png">
<meta property="og:type" content="website"><meta property="og:title" content="{title}"><meta property="og:description" content="{desc}"><meta property="og:image" content="img/planetary.jpg">
<link rel="stylesheet" href="style.css"></head><body>
<a class="skip" href="#main">Skip to the content</a>
<header class="nav"><div class="wrap"><a class="brand" href="index.html"><img src="assets/openpara-logo-small.svg" alt="">OpenPara</a><nav aria-label="Main">{nav}<a class="gh" href="{REPO}">GitHub</a></nav></div></header>
<main id="main">{head or ""}{main}</main>
<footer><div class="wrap"><div class="cols">
<div><div class="b"><img src="assets/openpara-logo-small.svg" alt="">OpenPara</div><p style="margin:0;max-width:300px">Free, open-source parametric CAD for everyone from hobbyists to engineers.</p></div>
<div><h4>Project</h4><a href="download.html">Download</a><a href="features.html">Features</a><a href="guides.html">Guides</a><a href="about.html">About</a></div>
<div><h4>Community</h4><a href="{REPO}">Source code</a><a href="{REPO}/releases">Releases</a><a href="{REPO}/issues">Report a problem</a></div>
<div><h4>Legal</h4><a href="about.html#licence">GNU GPL v3 licence</a><a href="{REPO}/blob/main/LICENSE">Licence text</a></div></div>
<div class="legal"><span>OpenPara is free software: you can use, study, change and share it.</span><span>Version <span id="foot-ver">0.4</span></span></div></div></footer>
<script src="site.js"></script></body></html>'''
    open(os.path.join(OUT, fn), "w", encoding="utf-8").write(html)


def pagehead(title, lead):
    return f'<div class="page-head"><div class="wrap"><h1>{title}</h1><p>{lead}</p></div></div>'


# ------------------------------------------------------------------ home
hero = f'''<div class="hero"><div class="wrap"><div>
<span class="badge"><i></i>Free and open source &middot; GPL-3.0</span>
<h1>Parametric CAD that is <em>free for everyone</em></h1>
<p class="lede">From a first sketch to a finished, simulated and rendered design. OpenPara is an open-source modeller for hobbyists, students and engineers: constraints, assemblies, a gear generator, simulation and a photorealistic renderer in one program.</p>
<div class="btns"><a class="btn p" href="download.html">{svg("dl")}Download for Windows <span id="ver-btn" style="opacity:.75;font-weight:600"></span></a><a class="btn s" href="features.html">See what it does</a></div>
<div class="fine">Windows installer. Linux and macOS can run it from source.</div></div>
<figure class="shot"><div class="frame"><img src="img/planetary.jpg" width="1360" height="790" alt="A planetary gear set with a sun gear, three planet gears and a ring gear, generated in OpenPara"></div><figcaption>A planetary set made with the Part Generator</figcaption></figure></div></div>'''

home = f'''
<section><div class="wrap"><div class="head"><div class="eyebrow">What is inside</div><h2>Everything in one program</h2><p class="lead">Model it, assemble it, test it and show it, without switching tools.</p></div>
<div class="grid">
<div class="card">{icon("cube")}<h3>Parametric parts</h3><p>Constrained sketches, extrude, cut, revolve, sweep, loft, fillet and chamfer. Change a dimension or a named variable and the part rebuilds.</p></div>
<div class="card">{icon("layers")}<h3>Assemblies</h3><p>Mates, sub-assemblies and variables of their own. Positions, mate values and pattern spacing can be formulas.</p></div>
<div class="card">{icon("gear")}<h3>Part Generator</h3><p>True involute spur, helical, herringbone and ring gears from a few numbers, plus gear trains and planetary sets sized for you.</p></div>
<div class="card">{icon("wave")}<h3>Simulation</h3><p>1D beam and frame analysis, 2D finite-element analysis and 2D flow, with results you can slice and inspect.</p></div>
<div class="card">{icon("camera")}<h3>Photorealistic renderer</h3><p>Sun and sky from a date, time and place, lights, several cameras, still pictures and MP4 videos.</p></div>
<div class="card">{icon("code")}<h3>Open and free</h3><p>GPL-3.0. Read the code, change it, share it. No account, no subscription, no limits.</p></div></div></div></section>

<section style="padding-top:0"><div class="wrap"><div class="split">
<div><div class="eyebrow">Part Generator</div><h2>Gears that fit, from the numbers you have</h2>
<p class="lead">Type the centre distance you have room for. OpenPara picks the tooth counts, adds the profile shift needed to hit the distance exactly, and tells you where to put each gear.</p>
<ul class="checks"><li>Trains of up to three gears, straight or bent at the middle gear</li><li>Planetary sets with the planet counts that work and the ratios for each way of holding it</li><li>Each gear opens as its own part, ready to edit</li></ul>
<a class="btn o" href="guides.html#train">Read the gear guide</a></div>
<img src="img/train.jpg" width="980" height="840" alt="A train of three helical gears generated in OpenPara" loading="lazy"></div></div></section>

<section class="tight" style="background:var(--card);border-block:1px solid var(--line)"><div class="wrap"><div class="paths">
<div class="path"><div class="eyebrow">Hobbyists and students</div><h3>New to CAD?</h3><p>You do not need an engineering degree. Type a few numbers into the Part Generator and get a real, accurate gear. Then open it and change it.</p><a class="btn p" href="guides.html#first">Make your first part</a></div>
<div class="path"><div class="eyebrow">Engineers</div><h3>Want the details?</h3><p>Constraints, formulas, units, mates and simulations in one place, and a plain account of what has been checked and what has not.</p><a class="btn o" href="features.html#honest">Read the details</a></div></div></div></section>

<section><div class="wrap"><div class="band"><div><h2>Try OpenPara today</h2><p>Free to download. The installer needs no administrator rights.</p></div><a class="btn p" href="download.html">{svg("dl")}Get the installer</a></div></div></section>'''
page("index.html", "OpenPara - free parametric CAD", "OpenPara is a free, open-source parametric CAD modeller with assemblies, a gear generator, simulation and a photorealistic renderer.", home, hero)

# ------------------------------------------------------------------ download
dl = f'''<section style="padding-top:56px"><div class="wrap prose" style="max-width:860px">
<div class="dl"><img src="assets/openpara-logo-small.svg" alt=""><div class="t"><h2>OpenPara for Windows</h2><p>Installs for your user only, with its own Python and every package it needs. Adds a Start-menu entry.</p><div class="meta" id="dl-info">Latest version: see the releases page.</div></div>
<a class="btn p" id="dl-exe" href="{REPO}/releases/latest">{svg("dl")}Download the installer</a></div>
<h2>Install in three steps</h2>
<ol class="steps"><li><b>Download and run</b> <code>OpenPara-Setup-&lt;version&gt;.exe</code>. No administrator rights are needed.</li><li><b>Start OpenPara</b> from the Start menu.</li><li><b>Stay up to date</b> with <b>Help &gt; Check for updates</b>. New versions install for you, and your settings and material library are kept.</li></ol>
<h2>Linux and macOS, or from source</h2><p>OpenPara is written in Python. Install the packages and run it:</p>
<pre><code>git clone {REPO}.git
cd OpenPara
pip install -r requirements.txt
python gpd_app.py</code></pre>
<div class="note"><div><b>Tested on Windows.</b> The Windows installer is the tested way to run OpenPara. Running from source on Linux or macOS should work but has had less testing.</div></div>
<h2>Other versions</h2><p>Every release is on the <a href="{REPO}/releases">releases page</a>, each with its notes.</p></div></section>'''
page("download.html", "Download - OpenPara", "Download the OpenPara Windows installer, or run it from source.", dl, pagehead("Download", "Free. No account needed."))

# ------------------------------------------------------------------ features
def block(ico, title, items):
    return f'<div class="card">{icon(ico)}<h3>{title}</h3><ul style="margin:10px 0 0;padding-left:20px;color:var(--mut);font-size:16px">' + "".join(f"<li style='margin:6px 0'>{i}</li>" for i in items) + "</ul></div>"

feat = f'''<section><div class="wrap"><div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(330px,1fr))">
{block("cube","Parts",["2D sketches with a constraint solver and dimensions","Extrude, cut, revolve, sweep (including twisted sweeps) and loft, each as a boss or a cut","Fillet, chamfer, patterns, mirrors, reference planes and axes","Named variables (Globals), formulas and configurations","One program-wide unit system: mm, cm, m, in, ft, N, kN, kip and more"])}
{block("gear","Part Generator",["Spur, helical, herringbone and internal ring gears with true involute teeth and exact tooth counts","Size by module, diametral pitch, pitch diameter or outside diameter; optional profile shift, backlash and bore","Gear trains of up to three gears, sized from centre distances, ratios or tooth counts","Planetary sets (sun, planets, ring) with valid planet counts and the ratios for each way of holding them","Each gear opens as its own part. OpenPara gives you the centre distances and turn angles; you build the assembly"])}
{block("layers","Assemblies",["Mates, sub-assemblies and patterns","Variables of their own","Positions, mate values and pattern spacing can be formulas"])}
{block("wave","Simulation",["1D beam and frame analysis","2D finite-element analysis and 2D flow","Results you can slice and inspect"])}
{block("camera","Renderer",["Sun and sky from a date, time and place","Spot light, floor and several cameras","Still pictures and MP4 videos, using Mitsuba 3"])}
{block("code","Open source",["GPL-3.0 licensed","Built on build123d (OpenCascade), PyQt6, pyvista / VTK, gmsh and Mitsuba 3","All the code is on GitHub"])}
</div></div></section>
<section style="padding-top:0" id="honest"><div class="wrap"><div class="split" style="align-items:start"><div><div class="eyebrow">Honest limits</div><h2>What is checked, and what is not</h2><p class="lead">We would rather tell you than have you find out.</p></div>
<div class="prose"><ul class="checks" style="margin-top:0"><li>The gear geometry is checked against textbook values and against the real solids: meshing gears do not overlap, and a deliberately wrong spacing does. That is a geometry check, not a strength or life calculation.</li><li>The simulations are tools for learning and first estimates. Check anything that matters against a trusted method.</li><li>OpenPara is young software under active development. Expect rough edges, and please report them.</li></ul></div></div></div></section>
<section style="padding-top:0"><div class="wrap"><div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(300px,1fr))"><div class="shotph">Screenshot: sketch with constraints<br>(coming soon)</div><div class="shotph">Screenshot: assembly<br>(coming soon)</div></div></div></section>'''
page("features.html", "Features - OpenPara", "Parametric parts, assemblies, a gear generator, simulation and a renderer in one free program.", feat, pagehead("Features", "What is in OpenPara today."))

# ------------------------------------------------------------------ guides
def video(text):
    return f'<div class="video"><div>{svg("play")}<br>{text}</div></div>'

guides = f'''<section style="padding-top:52px"><div class="wrap"><div class="layout"><aside class="toc" aria-label="On this page"><b>Guides</b><a href="#first">Your first part</a><a href="#train">A gear train</a><a href="#planetary">A planetary set</a></aside>
<div class="prose">
<h2 id="first">Your first part: a gear</h2><p>About ten minutes, and no CAD experience needed.</p>
<ol class="steps"><li>Start OpenPara and press <b>Part Generator</b> on the ribbon.</li><li>Choose <b>Spur gear</b>. Leave Module at 2 and Number of teeth at 20.</li><li>Look at the 3D preview. The numbers on the right (pitch diameter, outside diameter and so on) update as you type.</li><li>Change the face width and the bore diameter to what you need.</li><li>Press <b>OK</b>. The gear is added as one feature. Double-click it in the tree any time to change the numbers.</li><li>Save with <b>File &gt; Save</b>.</li></ol>
{video("Video: your first part (coming)")}
<h2 id="train">A gear train from centre distances</h2>
<ol class="steps"><li>In the Part Generator, open the <b>Gear systems</b> tab and choose <b>Gear train</b>.</li><li>Define gear 1: module, teeth, pressure angle, width and bore. Use a helix angle above 0 for helical gears; the hands alternate for you.</li><li>For gear 2, choose <b>Centre distance</b> and type the distance you have room for. OpenPara picks the nearest whole tooth count and uses profile shift to make up the small remainder.</li><li>For a third gear, choose another distance, a ratio, or the total of both distances. You can bend the chain at the middle gear.</li><li>Read the results: centre distances, ratios, and each gear's position and turn angle.</li><li>Press <b>Open the parts</b>. Each gear opens as its own part, unsaved. Put them together in an assembly using the positions and turn angles shown.</li></ol>
<div class="note"><div>If a distance cannot be reached with whole teeth and a small shift, OpenPara says so and tells you the nearest distance it can reach.</div></div>
<h2 id="planetary">A planetary set</h2>
<ol class="steps"><li>In <b>Gear systems</b>, choose <b>Planetary set</b>.</li><li>Choose which two gears set the size, for example sun and planet teeth. The ring always has sun + 2 &times; planet teeth.</li><li>Choose the number of planets. They must be equally spaced, so the sun plus ring teeth must divide evenly. If your choice does not work, OpenPara lists the counts that do.</li><li>Read the ratios for holding the ring, the sun or the carrier still.</li><li>Press <b>Open the parts</b>: three parts open (sun, planet, ring). Make the assembly yourself, adding as many planets as you chose, using the angles and radius shown. There is no carrier part.</li></ol>
{video("Video: a planetary set (coming)")}
</div></div></div></section>'''
page("guides.html", "Guides - OpenPara", "Step-by-step guides: your first part, gear trains and planetary sets.", guides, pagehead("Guides", "Start where you are. Video walk-throughs will be added to each guide."))

# ------------------------------------------------------------------ about
about = f'''<section style="padding-top:52px"><div class="wrap prose">
<p class="lead" style="margin-top:0;color:var(--ink)">OpenPara aims to be a parametric CAD program that anyone can use: someone making a part for a home project, a student, or an engineer who wants a modeller they can read and extend.</p>
<h2 id="licence">Licence</h2><p>OpenPara is free software under the <a href="https://www.gnu.org/licenses/gpl-3.0.html">GNU General Public License, version 3</a>. You may use it, study it, change it and share it, and if you share a changed version it must stay free in the same way. The full text is in the <a href="{REPO}/blob/main/LICENSE">LICENSE</a> file.</p>
<h2>Get involved</h2><ul><li><b>Try it and tell us.</b> Report problems and ideas on the <a href="{REPO}/issues">issues page</a>.</li><li><b>Read or change the code.</b> It is all on <a href="{REPO}">GitHub</a>.</li><li><b>Share your parts and guides.</b> More generators (keyways, bore shapes and other families) are planned.</li></ul>
<h2>Built with</h2><p><a href="https://github.com/gumyr/build123d">build123d</a> and OpenCascade for geometry, PyQt6 for the interface, pyvista / VTK for 3D views, gmsh for meshing, and Mitsuba 3 for rendering. Thank you to everyone who made those.</p>
</div></section>'''
page("about.html", "About - OpenPara", "OpenPara is free software under the GPL-3.0. Learn how to get involved.", about, pagehead("About OpenPara", "Free software, built in the open."))
print("site written")
