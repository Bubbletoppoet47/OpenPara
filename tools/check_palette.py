#!/usr/bin/env python3
"""check_palette.py - are the colours of an icon, a stylesheet or a screen the colours of OpenPara's theme?

The palette is written down in two places:
    icon_kit.py                                  LOOK (the navy ink, the blue-grey body, the greys) and HUES (eight accent colours); the muted tones the kit
                                                 draws from each hue are worked out here the way the kit does.  Read as text: no Qt, nothing is imported.
    planning/design/theme/palette.json           the colours the approved Workbench and ribbon designs add, each with what it is for.
`planning/design/theme/README.md` shows them as a swatch sheet.

    python tools/check_palette.py FILE...        check these files.  A file that is not in the baseline must be all palette; one that is may not get worse.
    python tools/check_palette.py --changed      the files that differ from origin/dev (--since REF for another one), and new ones
    python tools/check_palette.py --all          every program file against the baseline
    python tools/check_palette.py --list         the palette
    python tools/check_palette.py --swatches OUT.png   draw the swatch sheet
    python tools/check_palette.py --tighten      write the baseline again with the counts of now; it only goes down, nothing is added
    python tools/check_palette.py --init         write the baseline for the first time

The program has many colours from before the palette was written down.  They are the BASELINE (tools/palette_baseline.json): per file, how many times each
off-palette colour is used.  A colour may be used less than before, never more, and a new colour must be in the palette.  When a colour is replaced by a palette
colour, run --tighten and commit the smaller baseline.  To add a colour to the palette: put it in palette.json with what it is for and say why in the commit.

What it reads: #rrggbb, and #rgb after a colon, a quote or a bracket, inside the strings of a .py file (never its comments) or anywhere in a .qss or .svg file;
rgb( ) and rgba( ) in strings; QColor(r, g, b).  It does not read #aarrggbb or colour names.  Exit status 1 when a check fails.
"""
import argparse
import ast
import io
import json
import os
import re
import subprocess
import sys
import tokenize

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
KIT = os.path.join(ROOT, "icon_kit.py")
PALETTE_JSON = os.path.join(ROOT, "planning", "design", "theme", "palette.json")
BASELINE = os.path.join(HERE, "palette_baseline.json")

SCAN_EXT = (".py", ".qss", ".svg")
SCAN_TOP = ("shared/", "dev_addons/", "addons_src/", "updater_tool/")        # and the .py files in the root
EXEMPT = ("icon_kit.py", "tools/check_palette.py")                             # icon_kit.py is where the palette is defined

HEX6 = re.compile(r"(?<![0-9A-Za-z_&])#([0-9a-fA-F]{6})(?![0-9A-Za-z_])")
HEX3 = re.compile(r"(?:[\"'(]|:\s*)#([0-9a-fA-F]{3})(?![0-9A-Za-z_])")
RGBF = re.compile(r"rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})")
QCOL = re.compile(r"QColor\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})")


# ------------------------------------------------------------------------------------------------------------------------------ colours
def norm(h):
    h = h.lower().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return "#" + h


def rgb(h):
    h = norm(h).lstrip("#")
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)]


def _hex(r, g, b):
    return "#%02x%02x%02x" % (r, g, b)


def mix(a, b, t):
    """The kit's own mix (icon_kit._mix): a toward b by t."""
    A, B = rgb(a), rgb(b)
    return "#" + "".join(f"{max(0, min(255, round(x * (1 - t) + y * t))):02x}" for x, y in zip(A, B))


def distance(a, b):
    return sum((x - y) ** 2 for x, y in zip(rgb(a), rgb(b))) ** 0.5


# ------------------------------------------------------------------------------------------------------------------------------ the palette
def _literal(tree, name):
    for n in tree.body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) and n.targets[0].id == name:
            return ast.literal_eval(n.value)
    raise ValueError(f"{name} was not found in icon_kit.py")


def kit_colours(path=KIT):
    """{hex: name} of what icon_kit.py draws with: LOOK, HUES and the four tones of each hue (as icon_kit._tone works them out)."""
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    look, hues = _literal(tree, "LOOK"), _literal(tree, "HUES")
    out = {}
    for k in ("ink", "body", "paper", "hi", "lo", "grey"):
        if k in look:
            out.setdefault(norm(look[k]), f"kit {k}")
    for hk, h in hues.items():
        out.setdefault(norm(h), f"hue {hk}")
        for tn, c in kit_tones(look, hk, h).items():
            out.setdefault(norm(c), f"hue {hk}, {tn} as drawn")
    return out


def kit_tones(look, hue_key, hue):
    """The four colours icon_kit._tone works out from a hue: the accent shape, the accent line, the dot and the tube."""
    k = look["mute_blue"] if hue_key == "feat" else look["mute"]
    base = mix(hue, look["grey"], k)
    return {"accent": mix(base, "#000000", .08), "line": mix(mix(hue, look["grey"], k * .75), "#000000", .15),
            "dot": mix(mix(hue, look["grey"], k * .75), "#000000", .05), "tube": mix(base, "#ffffff", .5)}


def extra_colours(path=PALETTE_JSON):
    """{hex: name} of the colours palette.json adds (tiers: name, hex, use, source)."""
    out = {}
    if not os.path.isfile(path):
        return out
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    for tier, spec in (data.get("tiers") or {}).items():
        for c in spec.get("colours", []):
            out.setdefault(norm(c["hex"]), f"{tier}: {c['name']}")
    return out


def palette(kit=KIT, extra=PALETTE_JSON):
    p = dict(kit_colours(kit))
    for h, n in extra_colours(extra).items():
        p.setdefault(h, n)
    return p


def nearest(h, pal):
    best = min(pal, key=lambda c: distance(h, c))
    return best, pal[best], distance(h, best)


# ------------------------------------------------------------------------------------------------------------------------------ reading a file
def _scan_text(text, line0, found, hex3=True):
    """Adds (line, '#rrggbb') for every colour in `text`, which starts on line `line0`."""
    for i, ln in enumerate(text.split("\n")):
        n = line0 + i
        for m in HEX6.finditer(ln):
            found.append((n, norm(m.group(1))))
        if hex3:
            for m in HEX3.finditer(ln):
                found.append((n, norm(m.group(1))))
        for m in RGBF.finditer(ln):
            r, g, b = (int(x) for x in m.groups())
            if max(r, g, b) <= 255:
                found.append((n, _hex(r, g, b)))


def colours_in(path, text=None):
    """[(line, '#rrggbb')] of the colours a file uses."""
    if text is None:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    found = []
    if not path.lower().endswith(".py"):
        _scan_text(text, 1, found)
        return found
    fstr_mid = getattr(tokenize, "FSTRING_MIDDLE", None)
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.STRING or (fstr_mid is not None and tok.type == fstr_mid):
                _scan_text(tok.string, tok.start[0], found)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        found = []
        _scan_text(text, 1, found)                                  # a file that does not tokenise: look at every line
    for i, ln in enumerate(text.split("\n")):                         # QColor(r, g, b), in the code
        code = ln.split("#", 1)[0] if re.match(r"\s*#", ln) else ln
        for m in QCOL.finditer(code):
            r, g, b = (int(x) for x in m.groups())
            if max(r, g, b) <= 255:
                found.append((i + 1, _hex(r, g, b)))
    return found


def off_palette(path, pal, text=None):
    """[(line, hex)] of the colours of a file that are not in the palette."""
    return [(n, h) for n, h in colours_in(path, text) if h not in pal]


def counts(items):
    out = {}
    for _n, h in items:
        out[h] = out.get(h, 0) + 1
    return out


# ------------------------------------------------------------------------------------------------------------------------------ which files
def rel(path):
    return os.path.relpath(os.path.abspath(path), ROOT).replace(os.sep, "/")


def scanned(r):
    """True for a program file this check looks at: not a test, not parked, not an asset, not the palette itself."""
    if not r.endswith(SCAN_EXT) or r in EXEMPT or "/assets/" in r or r.startswith("assets/") or "__pycache__" in r:
        return False
    base = os.path.basename(r)
    if base.startswith("test_"):
        return False
    if "/" not in r:
        return r.endswith(".py")
    return r.startswith(SCAN_TOP)


def _git(*args):
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return r.stdout.split("\n") if r.returncode == 0 else None


def tracked():
    out = _git("ls-files")
    if out is None:
        out = [rel(os.path.join(d, f)) for d, _s, fs in os.walk(ROOT) for f in fs]
    return [r for r in out if r and scanned(r) and os.path.isfile(os.path.join(ROOT, r))]


def changed(since="origin/dev"):
    a = _git("diff", "--name-only", since) or []
    b = _git("ls-files", "--others", "--exclude-standard") or []
    return sorted({r for r in a + b if r and scanned(r) and os.path.isfile(os.path.join(ROOT, r))})


# ------------------------------------------------------------------------------------------------------------------------------ the baseline
def load_baseline(path=BASELINE):
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("files", {})


def save_baseline(files, path=BASELINE):
    data = {"about": "Colours that are not in the palette, per file, from before the palette was written down. A count can go down, never up. "
                     "Written by tools/check_palette.py (--init, --tighten).",
            "files": {k: dict(sorted(v.items())) for k, v in sorted(files.items()) if v}}
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=1)
        f.write("\n")


def current_counts(files, pal):
    out = {}
    for r in files:
        c = counts(off_palette(os.path.join(ROOT, r), pal))
        if c:
            out[r] = c
    return out


def tightened(base, now):
    """The baseline with the counts of now: a count only goes down, and nothing is added."""
    out = {}
    for r, cs in base.items():
        for h, n in cs.items():
            m = min(n, now.get(r, {}).get(h, 0))
            if m:
                out.setdefault(r, {})[h] = m
    return out


# ------------------------------------------------------------------------------------------------------------------------------ checking
def check(files, pal, base, say=print, root=ROOT):
    """Checks files (paths relative to the root).  -> (number of problems, number of baseline counts that could go down)."""
    problems, slack = 0, 0
    for r in files:
        items = off_palette(os.path.join(root, r), pal)
        if not items:
            if r in base:
                slack += sum(base[r].values())
            continue
        allowed = dict(base.get(r, {}))
        used = {}
        shown = []
        for n, h in items:
            used[h] = used.get(h, 0) + 1
            if used[h] > allowed.get(h, 0):
                shown.append((n, h))
        for h, a in allowed.items():
            slack += max(0, a - used.get(h, 0))
        if not shown:
            continue
        say(f"{r}" + ("" if r in base else "   (not in the baseline: every colour must be in the palette)"))
        done = set()
        for n, h in shown:
            problems += 1
            if (n, h) in done:
                continue
            done.add((n, h))
            near, name, d = nearest(h, pal)
            say(f"  line {n:<5} {h}   not in the palette.  Nearest: {near} ({name})" + ("  - the same colour to the eye" if d < 6 else ""))
    return problems, slack


# ------------------------------------------------------------------------------------------------------------------------------ swatch sheet
def sheet(out_png, pal_kit=None, scale=2):
    from PIL import Image, ImageDraw, ImageFont
    pal_kit = pal_kit or kit_colours()
    with open(KIT, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    look, hues = _literal(tree, "LOOK"), _literal(tree, "HUES")
    with open(PALETTE_JSON, encoding="utf-8") as f:
        extra = json.load(f)

    def font(size, bold=False):
        for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans%s.ttf" % ("-Bold" if bold else ""), "DejaVuSans.ttf"):
            try:
                return ImageFont.truetype(p, size * scale)
            except OSError:
                pass
        return ImageFont.load_default()
    ink, grey, body = look["ink"], look["grey"], look["body"]
    S = scale
    W, M, CW, CH = 1040, 28, 148, 92
    rows = []          # (title, note, [(name, hex)])
    rows.append(("The kit: the greys and the ink", "icon_kit.py, LOOK.  Every icon is drawn with these.",
                 [("ink", look["ink"]), ("body", look["body"]), ("paper", look["paper"]), ("edge, bottom right", look["lo"]), ("grey", look["grey"])]))
    rows.append(("The kit: the accent hues", "icon_kit.py, HUES.  An icon uses one of them, mixed toward the grey (20 %, blue 10 %).",
                 [(k, v) for k, v in hues.items()]))
    drawn = [(k + " as drawn", kit_tones(look, k, v)["accent"]) for k, v in hues.items()]
    rows.append(("The kit: the same hues as drawn", "The accent shape of an icon: the hue mixed toward the grey and a little darker. Its line, dot and tube are a shade darker or lighter of it, "
                 "and are in the palette too.", drawn))
    for tier, spec in extra["tiers"].items():
        rows.append((spec.get("title", tier), spec.get("role", ""), [(c["name"], c["hex"]) for c in spec["colours"]]))
    per = (W - 2 * M + 12) // (CW + 12)
    probe = ImageDraw.Draw(Image.new("RGB", (4, 4)))

    def wrap(text, f, width):
        out, cur = [], ""
        for w in text.split():
            t = (cur + " " + w).strip()
            if cur and probe.textlength(t, font=f) > width * S:
                out.append(cur)
                cur = w
            else:
                cur = t
        return out + [cur] if cur else out
    H = M
    laid = []
    for title, note, cols in rows:
        n = (len(cols) + per - 1) // per
        nl = wrap(note, font(12), W - 2 * M)
        laid.append((H, title, nl, cols))
        H += 36 + 17 * len(nl) + 14 + n * (CH + 44) + 10
    H += M
    img = Image.new("RGB", (W * S, H * S), "#ffffff")
    d = ImageDraw.Draw(img)
    for y0, title, nl, cols in laid:
        d.text((M * S, y0 * S), title, fill=ink, font=font(17, True))
        for j, ln in enumerate(nl):
            d.text((M * S, (y0 + 26 + 17 * j) * S), ln, fill=grey, font=font(12))
        top = y0 + 36 + 17 * len(nl) + 14 - 8
        for i, (name, h) in enumerate(cols):
            cx, cy = M + (i % per) * (CW + 12), top + (i // per) * (CH + 44)
            d.rectangle([cx * S, cy * S, (cx + CW) * S, (cy + CH) * S], fill=h, outline=ink, width=S)
            d.text((cx * S, (cy + CH + 6) * S), name, fill=ink, font=font(12, True))
            d.text((cx * S, (cy + CH + 22) * S), norm(h), fill=grey, font=font(12))
    img.save(out_png)
    return out_png


# ------------------------------------------------------------------------------------------------------------------------------ command line
def main(argv=None):
    ap = argparse.ArgumentParser(description="Are the colours of a file the colours of OpenPara's theme?")
    ap.add_argument("files", nargs="*", help="files to check")
    ap.add_argument("--all", action="store_true", help="every program file against the baseline")
    ap.add_argument("--changed", action="store_true", help="the files that differ from --since, and new ones")
    ap.add_argument("--since", default="origin/dev")
    ap.add_argument("--list", action="store_true", help="print the palette")
    ap.add_argument("--swatches", metavar="OUT.png", help="draw the swatch sheet")
    ap.add_argument("--tighten", action="store_true", help="write the baseline again; counts only go down")
    ap.add_argument("--init", action="store_true", help="write the baseline for the first time")
    ap.add_argument("--force", action="store_true", help="with --init: replace a baseline that is there")
    a = ap.parse_args(argv)
    pal = palette()
    if a.list:
        for h, n in sorted(pal.items(), key=lambda kv: kv[1]):
            print(f"{h}  {n}")
        return 0
    if a.swatches:
        print(sheet(a.swatches))
        return 0
    if a.init:
        if os.path.isfile(BASELINE) and not a.force:
            print("The baseline is there already; --tighten lowers it, --init --force writes it again from scratch.")
            return 1
        now = current_counts(tracked(), pal)
        save_baseline(now)
        print(f"baseline written: {sum(sum(v.values()) for v in now.values())} uses of {len({h for v in now.values() for h in v})} colours in {len(now)} files")
        return 0
    if a.tighten:
        base = load_baseline()
        new = tightened(base, current_counts(sorted(base), pal))
        save_baseline(new)
        print(f"baseline: {sum(sum(v.values()) for v in base.values())} -> {sum(sum(v.values()) for v in new.values())} uses")
        return 0
    base = load_baseline()
    if a.all:
        files = tracked()
    elif a.changed:
        files = changed(a.since)
    else:
        files = [rel(f) for f in a.files]
        if not files:
            ap.print_usage()
            return 2
        for f in files:
            if not os.path.isfile(os.path.join(ROOT, f)):
                print(f"{f}: not found")
                return 2
    if not a.all and not a.changed:
        files = [f for f in files if f not in EXEMPT]
    problems, slack = check(files, pal, base)
    print(f"{len(files)} files checked, {problems} colour{'s' if problems != 1 else ''} not in the palette" + (f"; {slack} uses in the baseline could go (python tools/check_palette.py --tighten)" if slack else ""))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
