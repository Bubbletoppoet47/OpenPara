"""The "Gear systems" tab of the Part Generator: a train of up to three gears, or a planetary set.  The numbers come from gearsys.py;
pressing "Open the parts" makes one ordinary Part Generator part per distinct gear, each in its own part document (no assembly)."""
import math

import gears
import gearsys
import partgen
from PyQt6.QtWidgets import (QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea,
                             QStackedWidget, QTextBrowser, QVBoxLayout, QWidget)

try:
    import numpy as np
    import pyvista as pv
    from pyvistaqt import QtInteractor
except Exception:
    pv = QtInteractor = None


def g(v, n=4):
    return f"{v:.{n}f}".rstrip("0").rstrip(".") if "." in f"{v:.{n}f}" else f"{v:.{n}f}"


def t10(v):
    return f"{v:.10g}"


def raw_for(kind, p):
    """The Part Generator's text parameters for a solved gear (p: dict from gearsys)."""
    d = partgen.defaults(kind)
    src = {"mode": "module", "size": p["module"], "teeth": p["teeth"], "pressure": p.get("pressure", 20), "width": p["width"], "bore": p.get("bore", 0),
           "helix": p.get("helix", 0), "hand": p.get("hand", "right"), "shift": p.get("shift", 0), "add": p.get("add", 1), "ded": p.get("ded", 1.25),
           "backlash": p.get("backlash", 0), "rim": p.get("rim", 5), "phase": p.get("phase", 0)}
    out = {}
    for k in d:
        v = src.get(k, d[k])
        out[k] = v if isinstance(v, str) else t10(float(v)) if k not in ("teeth",) else str(int(v))
    return out


class Field:
    """A labelled QLineEdit / QComboBox that can be read back as text or number."""

    def __init__(self, form, label, default, tip="", choices=None, on_change=None):
        if choices:
            self.w = QComboBox()
            for val, text in choices:
                self.w.addItem(text, val)
            self.w.setCurrentIndex(max(0, self.w.findData(default)))
            self.w.currentIndexChanged.connect(lambda _i: on_change())
        else:
            self.w = QLineEdit(str(default))
            self.w.textEdited.connect(lambda _t: on_change())
        self.w.setToolTip(tip)
        self.label = QLabel(label)
        form.addRow(self.label, self.w)

    def text(self):
        return self.w.currentData() if isinstance(self.w, QComboBox) else self.w.text().strip()

    def num(self, name=None):
        try:
            return float(self.text())
        except ValueError:
            raise ValueError(f"'{self.text()}' is not a number ({name or self.label.text()})")

    def set_enabled(self, on):
        self.w.setEnabled(on)
        self.label.setEnabled(on)


class GearSystemsPage(QWidget):
    def __init__(self, dialog):
        super().__init__()
        self.dialog = dialog
        self.result = None
        self.plotter = None
        ch = self.changed
        root = QHBoxLayout(self)
        # ---------------------------------------------------------------- left: inputs
        left = QVBoxLayout()
        top = QFormLayout()
        self.system = QComboBox()
        self.system.addItem("Gear train (2 or 3 gears)", "train")
        self.system.addItem("Planetary set (sun, planets, ring)", "planetary")
        self.system.currentIndexChanged.connect(lambda _i: (self.stack.setCurrentIndex(self.system.currentIndex()), self.changed()))
        top.addRow("System", self.system)
        left.addLayout(top)
        self.stack = QStackedWidget()
        # ---- train
        tr = QWidget()
        tl = QVBoxLayout(tr)
        tl.setContentsMargins(0, 0, 0, 0)
        b1 = QGroupBox("Gear 1 (fully defined)")
        f1 = QFormLayout(b1)
        self.t = {}
        t = self.t
        t["module"] = Field(f1, "Module (mm)", "2", "Normal module; the same for every gear.", on_change=ch)
        t["teeth"] = Field(f1, "Number of teeth", "20", "", on_change=ch)
        t["pressure"] = Field(f1, "Pressure angle (deg)", "20", "", on_change=ch)
        t["helix"] = Field(f1, "Helix angle (deg)", "0", "0 makes spur gears. The same angle is used on every gear; the hands alternate.", on_change=ch)
        t["hand"] = Field(f1, "Hand of gear 1", "right", "", [("right", "Right hand"), ("left", "Left hand")], ch)
        t["width"] = Field(f1, "Face width (mm)", "10", "", on_change=ch)
        t["bore"] = Field(f1, "Bore diameter (mm)", "8", "", on_change=ch)
        t["shift"] = Field(f1, "Profile shift x1", "0", "Optional; gear 2 / 3 absorb the rest when a centre distance is set.", on_change=ch)
        t["backlash"] = Field(f1, "Backlash (mm)", "0", "Used on every gear.", on_change=ch)
        tl.addWidget(b1)
        gl = QGroupBox("Layout")
        fl = QFormLayout(gl)
        t["count"] = Field(fl, "Number of gears", "2", "", [("2", "2 gears"), ("3", "3 gears")], ch)
        t["bend"] = Field(fl, "Angle at gear 2 (deg)", "180", "180 = a straight line; smaller bends the chain at the middle gear (3 gears).", on_change=ch)
        tl.addWidget(gl)
        b2 = QGroupBox("Gear 2")
        f2 = QFormLayout(b2)
        t["how2"] = Field(f2, "Sized by", "centre", "", [("centre", "Centre distance 1-2 (mm)"), ("ratio", "Ratio teeth 2 / teeth 1"), ("teeth", "Number of teeth")], ch)
        t["val2"] = Field(f2, "Value", "60", "", on_change=ch)
        t["width2"] = Field(f2, "Face width (mm)", "10", "", on_change=ch)
        t["bore2"] = Field(f2, "Bore diameter (mm)", "8", "", on_change=ch)
        self.b2 = b2
        tl.addWidget(b2)
        b3 = QGroupBox("Gear 3")
        f3 = QFormLayout(b3)
        t["how3"] = Field(f3, "Sized by", "centre", "", [("centre", "Centre distance 2-3 (mm)"), ("ratio", "Ratio teeth 3 / teeth 2"), ("teeth", "Number of teeth"),
                                                       ("span", "Total of both centre distances (mm)")], ch)
        t["val3"] = Field(f3, "Value", "60", "", on_change=ch)
        t["width3"] = Field(f3, "Face width (mm)", "10", "", on_change=ch)
        t["bore3"] = Field(f3, "Bore diameter (mm)", "8", "", on_change=ch)
        self.b3 = b3
        tl.addWidget(b3)
        tl.addStretch(1)
        self.stack.addWidget(tr)
        # ---- planetary
        pw = QWidget()
        pl = QVBoxLayout(pw)
        pl.setContentsMargins(0, 0, 0, 0)
        bp = QGroupBox("Planetary set")
        fp = QFormLayout(bp)
        self.p = {}
        p = self.p
        p["module"] = Field(fp, "Module (mm)", "2", "", on_change=ch)
        p["pressure"] = Field(fp, "Pressure angle (deg)", "20", "", on_change=ch)
        p["helix"] = Field(fp, "Helix angle (deg)", "0", "0 makes spur gears. Sun and planet get opposite hands, planet and ring the same.", on_change=ch)
        p["hand"] = Field(fp, "Hand of the sun", "right", "", [("right", "Right hand"), ("left", "Left hand")], ch)
        p["backlash"] = Field(fp, "Backlash (mm)", "0", "", on_change=ch)
        p["given"] = Field(fp, "Sizes set by", "sun+planet", "The ring always has sun + 2 x planet teeth.",
                           [("sun+planet", "Sun and planet teeth"), ("sun+ring", "Sun and ring teeth"), ("ring+planet", "Ring and planet teeth")], ch)
        p["zs"] = Field(fp, "Sun teeth", "18", "", on_change=ch)
        p["zp"] = Field(fp, "Planet teeth", "12", "", on_change=ch)
        p["zr"] = Field(fp, "Ring teeth", "42", "", on_change=ch)
        p["n"] = Field(fp, "Number of planets", "3", "Equally spaced; needs (sun + ring teeth) divisible by this number.", on_change=ch)
        pl.addWidget(bp)
        bw = QGroupBox("Widths, bores, rim")
        fw = QFormLayout(bw)
        p["ws"] = Field(fw, "Sun face width (mm)", "10", "", on_change=ch)
        p["wp"] = Field(fw, "Planet face width (mm)", "10", "", on_change=ch)
        p["wr"] = Field(fw, "Ring face width (mm)", "10", "", on_change=ch)
        p["bs"] = Field(fw, "Sun bore (mm)", "8", "", on_change=ch)
        p["bp"] = Field(fw, "Planet bore (mm)", "4", "", on_change=ch)
        p["rim"] = Field(fw, "Ring rim thickness (mm)", "5", "", on_change=ch)
        pl.addWidget(bw)
        pl.addStretch(1)
        self.stack.addWidget(pw)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(self.stack)
        sc.setFixedWidth(360)
        left.addWidget(sc, 1)
        root.addLayout(left)
        # ---------------------------------------------------------------- right: read-out, preview, buttons
        right = QVBoxLayout()
        self.view = QTextBrowser()
        self.view.setMinimumHeight(250)
        right.addWidget(self.view, 3)
        self.plot_host = QVBoxLayout()
        right.addLayout(self.plot_host, 2)
        row = QHBoxLayout()
        self.btn_prev = QPushButton("Preview layout")
        self.btn_prev.setToolTip("Builds the parts and shows them placed together (a look only: no assembly is made).")
        self.btn_prev.clicked.connect(self.preview)
        self.btn_open = QPushButton("Open the parts")
        self.btn_open.setToolTip("Opens each distinct gear as its own part document (a Part Generator part). Nothing is saved or assembled.")
        self.btn_open.clicked.connect(self.open_parts)
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.dialog.reject)
        for b in (self.btn_prev, self.btn_open, self.btn_close):
            row.addWidget(b)
        right.addLayout(row)
        root.addLayout(right, 1)
        self.changed()

    # ------------------------------------------------------------------ inputs -> solution
    def changed(self, *_a):
        if not hasattr(self, "view"):                     # still being built
            return
        t, p = self.t, self.p
        three = t["count"].text() == "3"
        self.b3.setVisible(three)
        t["bend"].set_enabled(three)
        given = p["given"].text()
        p["zs"].set_enabled(given in ("sun+planet", "sun+ring"))
        p["zp"].set_enabled(given in ("sun+planet", "ring+planet"))
        p["zr"].set_enabled(given in ("sun+ring", "ring+planet"))
        self.solve_now()

    def gear1(self):
        t = self.t
        return {"module": t["module"].num("module"), "teeth": int(round(t["teeth"].num("teeth"))), "pressure": t["pressure"].num("pressure angle"),
                "helix": t["helix"].num("helix angle"), "hand": t["hand"].text(), "width": t["width"].num("face width"), "bore": t["bore"].num("bore"),
                "shift": t["shift"].num("profile shift"), "backlash": t["backlash"].num("backlash"), "add": 1.0, "ded": 1.25}

    def solve_now(self):
        self.result = None
        try:
            if self.system.currentData() == "train":
                t = self.t
                links = [{"how": t["how2"].text(), "value": t["val2"].num("value 2"), "width": t["width2"].num("width 2"), "bore": t["bore2"].num("bore 2")}]
                if t["count"].text() == "3":
                    links.append({"how": t["how3"].text(), "value": t["val3"].num("value 3"), "width": t["width3"].num("width 3"), "bore": t["bore3"].num("bore 3")})
                r = gearsys.solve_train(self.gear1(), links, t["bend"].num("angle") if len(links) > 1 else 180.0)
                r["system"] = "train"
                self.result = r
                self.view.setHtml(self.html_train(r))
            else:
                p = self.p
                base = {"module": p["module"].num("module"), "pressure": p["pressure"].num("pressure angle"), "helix": p["helix"].num("helix angle"),
                        "hand": p["hand"].text(), "backlash": p["backlash"].num("backlash")}
                r = gearsys.solve_planetary(base, p["given"].text(), zs=int(round(p["zs"].num("sun teeth"))), zp=int(round(p["zp"].num("planet teeth"))),
                                            zr=int(round(p["zr"].num("ring teeth"))), n=int(round(p["n"].num("planets"))),
                                            widths={"sun": p["ws"].num("sun width"), "planet": p["wp"].num("planet width"), "ring": p["wr"].num("ring width")},
                                            bores={"sun": p["bs"].num("sun bore"), "planet": p["bp"].num("planet bore")}, rim=p["rim"].num("rim"))
                r["system"] = "planetary"
                for key, val in (("zs", r["zs"]), ("zp", r["zp"]), ("zr", r["zr"])):     # show the number that was worked out
                    if not p[key].w.isEnabled():
                        p[key].w.setText(str(val))
                self.result = r
                self.view.setHtml(self.html_planetary(r))
        except Exception as ex:
            self.view.setHtml(f"<p style='color:#c00000'>{ex}</p>")
        for b in (self.btn_prev, self.btn_open):
            b.setEnabled(self.result is not None)

    # ------------------------------------------------------------------ read-outs
    @staticmethod
    def table(head, rows):
        h = "".join(f"<th align='left' style='padding-right:12px'>{c}</th>" for c in head)
        body = "".join("<tr>" + "".join(f"<td style='padding-right:12px'>{c}</td>" for c in r) + "</tr>" for r in rows)
        return f"<table cellspacing='2'><tr>{h}</tr>{body}</table>"

    def html_train(self, r):
        gs, ds = r["gears"], r["dims"]
        rows = []
        for i, (q, D) in enumerate(zip(gs, ds)):
            rows.append([f"Gear {i + 1}", D["z"], g(D["d"]), g(D["da"]), g(D["df"]), f"{float(q.get('shift', 0)):+.4f}", q["hand"] if D["beta"] else "-",
                         g(q["width"]), g(q["bore"])])
        out = ["<h3>Gears</h3>", self.table(["", "Teeth", "Pitch dia", "Tip dia", "Root dia", "Shift x", "Hand", "Width", "Bore"], rows)]
        out.append("<h3>Centre distances and ratios</h3><ul>")
        for i, C in enumerate(r["C"]):
            out.append(f"<li>Gear {i + 1} to gear {i + 2}: centre distance <b>{C:.4f} mm</b>, ratio {r['ratio'][i]:.4f} : 1, "
                       f"contact ratio {r['contact'][i]:.2f}</li>")
        if len(r["C"]) > 1:
            out.append(f"<li>Total of both centre distances: {sum(r['C']):.4f} mm</li>")
        out.append(f"<li>Overall ratio gear 1 to last gear: {r['total_ratio']:.4f} : 1 "
                   f"(the last gear turns {'the same way' if len(gs) == 3 else 'the opposite way'} as gear 1)</li></ul>")
        out.append("<h3>To assemble</h3><p>Stand the parts on the same plane (bottom faces together). Turn each part about its own axis by the angle "
                   "(counter-clockwise looking down its axis), then put its axis at the position.</p>")
        rows = [[f"Gear {i + 1}", f"({r['pos'][i][0]:.4f}, {r['pos'][i][1]:.4f})", f"{r['turn'][i]:.4f}"] for i in range(len(gs))]
        out.append(self.table(["", "Axis position X, Y (mm)", "Turn (deg)"], rows))
        if r["notes"]:
            out.append("<h3>Notes</h3><ul>" + "".join(f"<li>{n}</li>" for n in r["notes"]) + "</ul>")
        return "".join(out)

    def html_planetary(self, r):
        D = r["dims"]
        rows = [["Sun", r["zs"], g(D["sun"]["d"]), g(D["sun"]["da"]), g(r["sun"]["width"]), r["sun"]["hand"] if D["sun"]["beta"] else "-"],
                ["Planet", r["zp"], g(D["planet"]["d"]), g(D["planet"]["da"]), g(r["planet"]["width"]), r["planet"]["hand"] if D["planet"]["beta"] else "-"],
                ["Ring", r["zr"], g(D["ring"]["d"]), f"{g(2 * (D['ring']['rp'] - D['ring']['mn'] * r['ring']['add']))} (inside)", g(r["ring"]["width"]),
                 r["ring"]["hand"] if D["ring"]["beta"] else "-"]]
        out = ["<h3>Gears</h3>", self.table(["", "Teeth", "Pitch dia", "Tip dia", "Width", "Hand"], rows)]
        out.append(f"<p>Ring teeth = sun + 2 x planet = {r['zs']} + 2 x {r['zp']} = <b>{r['zr']}</b>.<br>"
                   f"Centre distance, sun to planet = planet to ring: <b>{r['C']:.4f} mm</b>.<br>"
                   f"Planet counts that fit (equal spacing and no contact): {', '.join(map(str, r['valid_n'])) or 'none'}. "
                   f"Chosen: {r['n']} {'(ok)' if r['n_ok'] else '(does not work)'}.</p>")
        out.append("<h3>Ratios</h3><ul>" + "".join(f"<li>{k}: {v:.4f} : 1</li>" for k, v in r["ratios"].items()) + "</ul>")
        out.append("<h3>To assemble</h3><p>Sun and ring: axis at the origin, bottom faces on the same plane, not turned (the ring's teeth are already "
                   f"offset by {r['ring_phase']:.4f} deg so that the planets fit). Planets: bottom face on the same plane, turn each about its own axis "
                   "(counter-clockwise looking down its axis) and put its axis on the circle of radius "
                   f"{r['C']:.4f} mm at the angle shown.</p>")
        rows = [[f"Planet {i + 1}", f"{360.0 * i / r['n']:.3f}", f"({r['C'] * math.cos(math.radians(360.0 * i / r['n'])):.4f}, "
                 f"{r['C'] * math.sin(math.radians(360.0 * i / r['n'])):.4f})", f"{r['planet_turn'][i]:.4f}"] for i in range(r["n"])]
        out.append(self.table(["", "Position angle (deg)", "Axis X, Y (mm)", "Turn (deg)"], rows))
        if r["notes"]:
            out.append("<h3>Notes</h3><ul>" + "".join(f"<li>{n}</li>" for n in r["notes"]) + "</ul>")
        return "".join(out)

    # ------------------------------------------------------------------ the parts
    def parts(self):
        """[(tab name, Part Generator type, text parameters)] - one per distinct gear."""
        r = self.result
        out = []
        if r["system"] == "train":
            for i, q in enumerate(r["gears"]):
                kind = "Helical gear" if q.get("helix", 0) else "Spur gear"
                out.append((f"Gear {i + 1} ({q['teeth']}T)", kind, raw_for(kind, q)))
        else:
            for name, key in (("Sun", "sun"), ("Planet", "planet"), ("Ring", "ring")):
                q = r[key]
                kind = "Ring gear" if key == "ring" else "Helical gear" if q.get("helix", 0) else "Spur gear"
                out.append((f"{name} ({q['teeth']}T)", kind, raw_for(kind, q)))
        return out

    def shell(self):
        w = self.dialog.parent().window() if self.dialog.parent() is not None else None
        return w if w is not None and hasattr(w, "new_part") else None

    def open_parts(self):
        if self.result is None:
            return
        if self.result["system"] == "planetary" and not self.result["n_ok"]:
            if QMessageBox.question(self, "Planetary set", "The chosen number of planets does not work (see the notes). Open the parts anyway?") \
                    != QMessageBox.StandardButton.Yes:
                return
        shell = self.shell()
        if shell is None:
            QMessageBox.information(self, "Gear systems", "The parts open as tabs in the main OpenPara window; this window was not started from it.")
            return
        import pm_model as pm
        self.opened = []
        for name, kind, raw in self.parts():
            w = shell.new_part()
            w.snapshot()
            f = w.doc.add(pm.new_feature("partgen", gen=kind, params=raw, place={"plane": "Top", "ox": "0", "oy": "0", "oz": "0"}))
            w.created_new = f["id"]
            w.sel = f["id"]
            w.tab_name = name
            w.update_all(fit=True)
            self.opened.append(w)
        try:
            shell.refresh_titles()
        except Exception:
            pass
        self.dialog.systems_done = True
        self.dialog.reject()

    # ------------------------------------------------------------------ preview
    def preview(self):
        if self.result is None:
            return
        import gears as G
        r = self.result
        placed = []
        try:
            if r["system"] == "train":
                for i, q in enumerate(r["gears"]):
                    kind = "Helical gear" if q.get("helix", 0) else "Spur gear"
                    placed.append((G.make(kind, q), r["pos"][i][0], r["pos"][i][1], r["turn"][i]))
            else:
                placed.append((G.make("Helical gear" if r["sun"].get("helix", 0) else "Spur gear", r["sun"]), 0, 0, 0))
                placed.append((G.make("Ring gear", r["ring"]), 0, 0, 0))
                pl = G.make("Helical gear" if r["planet"].get("helix", 0) else "Spur gear", r["planet"])
                for i in range(r["n"]):
                    a = math.radians(360.0 * i / r["n"])
                    placed.append((pl, r["C"] * math.cos(a), r["C"] * math.sin(a), r["planet_turn"][i]))
        except Exception as ex:
            self.view.setHtml(f"<p style='color:#c00000'>{ex}</p>")
            return
        if QtInteractor is None:
            return
        if self.plotter is None:
            try:
                self.plotter = QtInteractor(self)
                self.plotter.set_background("#f7f9fc", top="#cfd9ea")
                self.plotter.setMinimumSize(380, 240)
                self.plot_host.addWidget(self.plotter)
            except Exception:
                self.plotter = None
                return
        from build123d import Location
        pl = self.plotter
        pl.clear()
        doc = self.dialog.doc
        colours = [(0.62, 0.70, 0.82), (0.82, 0.70, 0.55), (0.65, 0.80, 0.62), (0.78, 0.62, 0.78)]
        for k, (sol, x, y, turn) in enumerate(placed):
            sol = sol.moved(Location((x, y, 0), (0, 0, 1), turn))
            verts, cells, off = [], [], 0
            for _i, vv, tt in doc.mesh(sol):
                verts.append(vv)
                cells.append(np.hstack([np.full((len(tt), 1), 3), tt + off]).ravel())
                off += len(vv)
            if verts:
                pl.add_mesh(pv.PolyData(np.vstack(verts), np.concatenate(cells)), color=colours[min(k, 3) if r["system"] == "train" else (0 if k == 0 else 1 if k == 1 else 2)],
                            smooth_shading=False, ambient=0.28, diffuse=0.78, specular=0.3, reset_camera=False)
            pts, lines, o = [], [], 0
            for poly in doc.edge_lines(sol):
                n = len(poly)
                if n >= 2:
                    pts.append(poly)
                    lines.append(np.hstack([[n], np.arange(o, o + n)]))
                    o += n
            if pts:
                pd = pv.PolyData(np.vstack(pts))
                pd.lines = np.concatenate(lines).astype(np.int64)
                pl.add_mesh(pd, color=(0.08, 0.10, 0.14), line_width=1.0, pickable=False, reset_camera=False)
        pl.add_axes()
        pl.view_xy()
        pl.reset_camera()
