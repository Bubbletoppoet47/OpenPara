// Fills in the latest release (version, installer link) from GitHub; the pages still work without it.
(function () {
  fetch("https://api.github.com/repos/Bubbletoppoet47/OpenPara/releases/latest").then(function (r) { return r.ok ? r.json() : null; }).then(function (rel) {
    if (!rel) return;
    var exe = (rel.assets || []).filter(function (a) { return /Setup.*\.exe$/i.test(a.name); })[0];
    var v = (rel.tag_name || "").replace(/^v/, "");
    var b = document.getElementById("ver-btn"); if (b && v) b.textContent = "(" + v + ")";
    var f = document.getElementById("foot-ver"); if (f && v) f.textContent = v;
    var d = document.getElementById("dl-exe"); if (d && exe) { d.href = exe.browser_download_url; d.textContent = "Download OpenPara " + v + " for Windows"; }
    var i = document.getElementById("dl-info");
    if (i && v) i.textContent = "Latest version " + v + (exe ? " (" + Math.round(exe.size / 1048576) + " MB)" : "") + ", released " + new Date(rel.published_at).toLocaleDateString() + ".";
  }).catch(function () {});
})();
