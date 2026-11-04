"""preview_site.py <docs-dir> <out-dir> - makes the PREVIEW copy of the website from docs/ (used by .github/workflows/site-preview.yml).

Differences from the live site: no CNAME (the preview must not claim openpara.net), an orange "preview" bar on every page, "(preview)" in the page
titles, and the download button / version line follow the newest Playground build (the newest dev- pre-release) instead of the newest release.
"""
import os
import re
import shutil
import sys

BAR = ('<div style="position:sticky;top:0;z-index:99999;background:#f08a24;color:#1a1204;font:600 14px/1.4 system-ui,sans-serif;'
       'text-align:center;padding:7px 12px">Preview of the next version of the website - not the live site. '
       '<a href="https://openpara.net" style="color:#1a1204;text-decoration:underline">Go to openpara.net</a></div>')

SITE_JS = '''// PREVIEW: the version and the download button follow the newest Playground build (dev- pre-release).
(function () {
  fetch("https://api.github.com/repos/Bubbletoppoet47/OpenPara/releases?per_page=30").then(function (r) { return r.ok ? r.json() : null; }).then(function (list) {
    var rel = (list || []).filter(function (x) { return /^dev-/.test(x.tag_name || "") && !x.draft; })[0];
    if (!rel) return;
    var exe = (rel.assets || []).filter(function (a) { return /Setup.*\\.exe$/i.test(a.name); })[0];
    var v = (rel.tag_name || "").replace(/^dev-/, "");
    var b = document.getElementById("ver-btn"); if (b && v) b.textContent = "(" + v + ")";
    var f = document.getElementById("foot-ver"); if (f && v) f.textContent = v + " (playground)";
    var d = document.getElementById("dl-exe"); if (d && exe) { d.href = exe.browser_download_url; d.textContent = "Download OpenPara Playground " + v + " for Windows"; }
    var i = document.getElementById("dl-info");
    if (i && v) i.textContent = "Newest Playground build " + v + (exe ? " (" + Math.round(exe.size / 1048576) + " MB)" : "") + ", built " + new Date(rel.published_at).toLocaleDateString() + ".";
  }).catch(function () {});
})();
'''


def main(src, out):
    if os.path.exists(out):
        shutil.rmtree(out)
    shutil.copytree(src, out, ignore=shutil.ignore_patterns("CNAME", "__pycache__"))
    n = 0
    for base, _dirs, files in os.walk(out):
        for f in files:
            if not f.endswith(".html"):
                continue
            p = os.path.join(base, f)
            t = open(p, encoding="utf-8").read()
            t, k = re.subn(r"(<body[^>]*>)", lambda m: m.group(1) + BAR, t, count=1)
            t = re.sub(r"(<title>)([^<]*)(</title>)", lambda m: m.group(1) + m.group(2) + " (preview)" + m.group(3), t, count=1)
            open(p, "w", encoding="utf-8").write(t)
            n += k
    open(os.path.join(out, "site.js"), "w", encoding="utf-8").write(SITE_JS)
    open(os.path.join(out, ".nojekyll"), "w").close()
    print(f"preview site: {n} pages with the preview bar -> {out}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
