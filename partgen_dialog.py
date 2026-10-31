"""The Part Generator window: pick a part type, fill in its parameters, watch it in 3D, press OK to add it as ONE feature.
Opened again on that feature, it edits the same parameters (they are stored in the feature)."""
import partgen
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                             QListWidget, QListWidgetItem, QScrollArea, QTabWidget, QVBoxLayout, QWidget)

try:
    import numpy as np
    import pyvista as pv
    from pyvistaqt import QtInteractor
except Exception:                                              # no 3D view available: the dialog still works without the preview
    pv = QtInteractor = None

CHOICE_TEXT = {"right": "Right hand", "left": "Left hand", "Top": "Z (Top plane)", "Front": "-Y (Front plane)", "Right": "X (Right plane)",
               **dict(partgen.SIZE_MODES)}


class PartGenDialog(QDialog):
    def __init__(self, doc, feature=None, parent=None):
        super().__init__(parent)
        self.doc, self.feature = doc, feature
        self.setWindowTitle("Part Generator" + (f" - {feature['name']}" if feature else ""))
        self.resize(1080, 640)
        self.raw = {}                                      # part type -> {param: text}, kept while switching types
        self.place = dict((feature or {}).get("place") or {"plane": "Top", "ox": "0", "oy": "0", "oz": "0"})
        self.kind = None
        self.solid = None
        self.edits = {}
        self.cam_set = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(350)
        self.timer.timeout.connect(self.refresh)

        self.systems_done = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs)
        page1 = QWidget()
        root = QHBoxLayout(page1)
        self.tabs.addTab(page1, "Single part")
        # --- left: the catalogue
        left = QVBoxLayout()
        left.addWidget(QLabel("Part type"))
        self.types = QListWidget()
        self.types.setFixedWidth(170)
        group = None
        for name, spec in partgen.PART_TYPES.items():
            if spec["group"] != group:
                group = spec["group"]
                h = QListWidgetItem(group.upper())
                h.setFlags(Qt.ItemFlag.NoItemFlags)
                self.types.addItem(h)
            it = QListWidgetItem("   " + name)
            it.setData(Qt.ItemDataRole.UserRole, name)
            self.types.addItem(it)
        left.addWidget(self.types, 1)
        root.addLayout(left)
        # --- middle: parameters, read-outs
        mid = QVBoxLayout()
        self.form_host = QWidget()
        self.form_lay = QVBoxLayout(self.form_host)
        self.form_lay.setContentsMargins(0, 0, 0, 0)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(self.form_host)
        sc.setFixedWidth(330)
        mid.addWidget(sc, 1)
        root.addLayout(mid)
        # --- right: read-outs and preview
        right = QVBoxLayout()
        self.out_box = QGroupBox("Calculated")
        self.out_form = QFormLayout(self.out_box)
        right.addWidget(self.out_box)
        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        right.addWidget(self.msg)
        self.plotter = None
        if QtInteractor is not None:
            try:
                self.plotter = QtInteractor(self)
                self.plotter.set_background("#f7f9fc", top="#cfd9ea")
                self.plotter.setMinimumSize(380, 300)
                right.addWidget(self.plotter, 1)
            except Exception:
                self.plotter = None
        if self.plotter is None:
            right.addWidget(QLabel("(3D preview not available here)"), 1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        right.addWidget(self.buttons)
        root.addLayout(right, 1)

        if feature is None:                               # gear systems make new parts, so they are not offered when editing one
            import gearsys_page
            self.systems = gearsys_page.GearSystemsPage(self)
            self.tabs.addTab(self.systems, "Gear systems")
        else:
            self.tabs.tabBar().hide()
        first = (feature or {}).get("gen") or "Spur gear"
        if feature:
            self.raw[first] = dict(feature.get("params") or {})
            self.types.setEnabled(False)               # a generated part keeps its type; to make another type, add a new part
        self.types.currentItemChanged.connect(lambda cur, _p: cur is not None and cur.data(Qt.ItemDataRole.UserRole) and self.set_kind(cur.data(Qt.ItemDataRole.UserRole)))
        for i in range(self.types.count()):
            if self.types.item(i).data(Qt.ItemDataRole.UserRole) == first:
                self.types.setCurrentRow(i)

    # ------------------------------------------------------------------ the parameter form
    def set_kind(self, kind):
        self.kind = kind
        self.raw.setdefault(kind, partgen.defaults(kind))
        while self.form_lay.count():
            w = self.form_lay.takeAt(0).widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self.edits = {}
        main, adv = partgen.param_defs(kind)
        box = QGroupBox(kind)
        self.fill(QFormLayout(box), main)
        self.form_lay.addWidget(box)
        ab = QGroupBox("Advanced")
        ab.setCheckable(True)
        ab.setChecked(any(str(self.raw[kind].get(k, d)) != str(d) for k, _l, d, _t, _tip in adv))
        inner = QWidget()
        il = QFormLayout(inner)
        il.setContentsMargins(0, 0, 0, 0)
        self.fill(il, adv)
        lay = QVBoxLayout(ab)
        lay.addWidget(inner)
        inner.setVisible(ab.isChecked())
        ab.toggled.connect(inner.setVisible)
        self.form_lay.addWidget(ab)
        pb = QGroupBox("Placement")
        pf = QFormLayout(pb)
        cb = QComboBox()
        for v in ("Top", "Front", "Right"):
            cb.addItem(CHOICE_TEXT[v], v)
        cb.setCurrentIndex(max(0, ["Top", "Front", "Right"].index(self.place.get("plane", "Top"))))
        cb.currentIndexChanged.connect(lambda _i: (self.place.__setitem__("plane", cb.currentData()), self.timer.start()))
        pf.addRow("Axis along", cb)
        for k, label, d in partgen.PLACEMENT[1:]:
            e = QLineEdit(str(self.place.get(k, d)))
            e.textEdited.connect(lambda t, k=k: (self.place.__setitem__(k, t), self.timer.start()))
            pf.addRow(label, e)
        self.form_lay.addWidget(pb)
        self.form_lay.addStretch(1)
        self.cam_set = False
        self.refresh()

    def fill(self, form, defs):
        kind = self.kind
        for k, label, d, t, tip in defs:
            if t.startswith("choice"):
                w = QComboBox()
                for v in t.split(":")[1].split("|"):
                    w.addItem(CHOICE_TEXT.get(v, v), v)
                cur = str(self.raw[kind].get(k, d))
                w.setCurrentIndex(max(0, w.findData(cur)))
                w.currentIndexChanged.connect(lambda _i, k=k, w=w: (self.raw[self.kind].__setitem__(k, w.currentData()), self.timer.start()))
            else:
                w = QLineEdit(str(self.raw[kind].get(k, d)))
                w.textEdited.connect(lambda t_, k=k: (self.raw[self.kind].__setitem__(k, t_), self.timer.start()))
            w.setToolTip(tip + ("\nA number or a formula using the Globals." if not t.startswith("choice") else ""))
            form.addRow(label, w)
            self.edits[k] = w

    # ------------------------------------------------------------------ live part
    def values(self):
        return partgen.numbers(self.kind, self.raw[self.kind], self.doc.num)

    def refresh(self):
        """Rebuild the part from the current inputs; show read-outs, warnings and the 3D preview."""
        while self.out_form.rowCount():
            self.out_form.removeRow(0)
        self.solid = None
        self.msg.setStyleSheet("color:#c00000;")
        try:
            v = self.values()
            for lab, txt in partgen.readouts(self.kind, v):
                self.out_form.addRow(lab, QLabel(txt))
            warns = partgen.warnings(self.kind, v)
            sol = partgen.build(self.kind, v)
            pl = self.place
            self.solid = partgen.placed(sol, pl.get("plane", "Top"), self.doc.num(pl.get("ox", "0")), self.doc.num(pl.get("oy", "0")), self.doc.num(pl.get("oz", "0")))
            self.msg.setStyleSheet("color:#a05a00;")
            self.msg.setText("\n".join(warns))
        except Exception as ex:                        # a bad input: say what is wrong, keep the dialog usable
            self.msg.setText(str(ex) or type(ex).__name__)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(self.solid is not None)
        self.draw()

    def draw(self):
        pl = self.plotter
        if pl is None:
            return
        try:
            cam = pl.camera_position if self.cam_set else None
            pl.clear()
            if self.solid is not None:
                verts, cells, off = [], [], 0
                for _i, vv, tt in self.doc.mesh(self.solid):
                    verts.append(vv)
                    cells.append(np.hstack([np.full((len(tt), 1), 3), tt + off]).ravel())
                    off += len(vv)
                if verts:
                    pl.add_mesh(pv.PolyData(np.vstack(verts), np.concatenate(cells)), color=(0.62, 0.70, 0.82), smooth_shading=False,
                                ambient=0.28, diffuse=0.78, specular=0.30, specular_power=22, reset_camera=False)
                self.draw_edges(pl)
            pl.add_axes()
            if cam is not None:
                pl.camera_position = cam
            else:
                pl.view_isometric()
                pl.reset_camera()
                self.cam_set = True
        except Exception:
            pass

    def draw_edges(self, pl):
        """Real edges of the solid as dark lines over the shaded mesh."""
        pts, lines, off = [], [], 0
        for poly in self.doc.edge_lines(self.solid):
            n = len(poly)
            if n < 2:
                continue
            pts.append(poly)
            lines.append(np.hstack([[n], np.arange(off, off + n)]))
            off += n
        if pts:
            pd = pv.PolyData(np.vstack(pts))
            pd.lines = np.concatenate(lines).astype(np.int64)
            pl.add_mesh(pd, color=(0.08, 0.10, 0.14), line_width=1.5, pickable=False, reset_camera=False,
                        render_lines_as_tubes=False)

    # ------------------------------------------------------------------ result
    def result_data(self):
        """(part type, parameters as typed, placement) for the feature."""
        return self.kind, dict(self.raw[self.kind]), dict(self.place)

    def done(self, code):
        self.timer.stop()
        if self.plotter is not None:
            try:
                self.plotter.close()
            except Exception:
                pass
        super().done(code)
