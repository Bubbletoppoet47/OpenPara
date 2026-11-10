// The gear drawing on the home page (redrawn when a number changes) and the result videos.
// The sums are the same as gear_outline() in tools/build_site.py, which draws the picture a browser without scripts shows.
(function () {
  var fig = document.getElementById("gear");
  if (fig) {
    var CX = 260, CY = 262, R = 168, ALPHA = 20 * Math.PI / 180;
    var el = function (id) { return document.getElementById(id); };
    var num = function (v) { return String(Math.round(v * 100) / 100); };
    var inv = function (phi) { return Math.tan(phi) - phi; };

    var outline = function (z, m, s) {
      var r = m * z / 2, rb = r * Math.cos(ALPHA), ra = r + m, rf = r - 1.25 * m;
      var half = Math.PI / (2 * z) + inv(ALPHA), r0 = Math.max(rb, rf + 0.3 * m), flank = [], k, i;
      for (k = 0; k < 7; k++) {
        var rho = r0 + (ra - r0) * k / 6;
        flank.push([rho, half - inv(Math.acos(Math.min(1, rb / rho)))]);
      }
      var a0 = flank[0][1], at = flank[6][1], fil = Math.min(0.35 * m / rf, 0.8 * (Math.PI / z - a0));
      var pt = function (rho, a) { return (CX + s * rho * Math.cos(a)).toFixed(2) + " " + (CY + s * rho * Math.sin(a)).toFixed(2); };
      var arc = function (rad) { return "A" + (s * rad).toFixed(2) + " " + (s * rad).toFixed(2) + " 0 0 1 "; };
      var d = "";
      for (i = 0; i < z; i++) {
        var c = 2 * Math.PI * i / z - Math.PI / 2;
        d += (i === 0 ? "M" : arc(rf)) + pt(rf, c - a0 - fil) + "Q" + pt(rf, c - a0) + " " + pt(r0, c - a0);
        for (k = 1; k < 7; k++) d += "L" + pt(flank[k][0], c - flank[k][1]);
        d += arc(ra) + pt(ra, c + at);
        for (k = 5; k >= 0; k--) d += "L" + pt(flank[k][0], c + flank[k][1]);
        d += "Q" + pt(rf, c + a0) + " " + pt(rf, c + a0 + fil);
      }
      return d + arc(rf) + pt(rf, -Math.PI / 2 - a0 - fil) + "Z";
    };

    var draw = function () {
      var z = parseInt(el("k-z").value, 10), m = parseFloat(el("k-m").value);
      var d = m * z, da = m * (z + 2), df = m * (z - 2.5), db = d * Math.cos(ALPHA), s = R / (da / 2);
      el("g-out").setAttribute("d", outline(z, m, s));
      el("g-bore").setAttribute("r", (s * 0.16 * d).toFixed(2));
      el("g-pitch").setAttribute("r", (s * d / 2).toFixed(2));
      el("g-da").textContent = "⌀ " + num(da);
      el("g-d").textContent = "pitch ⌀ " + num(d);
      var a = 38 * Math.PI / 180;
      el("g-lead").setAttribute("d", "M" + (CX + s * d / 2 * Math.cos(a)).toFixed(1) + " " + (CY + s * d / 2 * Math.sin(a)).toFixed(1) + "L" + (CX + R - 38) + " " + (CY + R - 2) + "h78");
      var bars = [50, 20, 10, 5, 2, 1], bar = 1, i;
      for (i = 0; i < bars.length; i++) if (bars[i] * s <= 120) { bar = bars[i]; break; }
      var by = CY + R + 24;
      el("g-bar").setAttribute("d", "M40 " + (by - 7) + "v7h" + (bar * s).toFixed(1) + "v-7");
      el("g-bar-t").textContent = bar + " mm";
      el("o-z").textContent = z; el("o-m").textContent = num(m) + " mm";
      el("t-d").textContent = num(d) + " mm"; el("t-da").textContent = num(da) + " mm";
      el("t-df").textContent = num(df) + " mm"; el("t-db").textContent = num(db) + " mm";
    };
    fig.querySelector(".knobs").hidden = false;
    el("k-z").addEventListener("input", draw);
    el("k-m").addEventListener("input", draw);
    draw();
  }

  // Videos: they play only while they are on screen; someone who asked for less motion gets the player's buttons instead.
  var vids = Array.prototype.slice.call(document.querySelectorAll("video"));
  if (!vids.length) return;
  var calm = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (calm) {
    vids.forEach(function (v) { v.removeAttribute("autoplay"); v.pause(); v.controls = true; });
  } else if ("IntersectionObserver" in window) {
    var io = new IntersectionObserver(function (items) {
      items.forEach(function (it) {
        if (it.isIntersecting) { var p = it.target.play(); if (p && p.catch) p.catch(function () {}); } else it.target.pause();
      });
    }, { threshold: 0.2 });
    vids.forEach(function (v) { io.observe(v); });
  }
})();
