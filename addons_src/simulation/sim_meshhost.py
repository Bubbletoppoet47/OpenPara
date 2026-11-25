"""
sim_meshhost.py - what the Mesh page of the 2D FEA and the 2D Thermal window does (the mixin of both tabs).  The page itself is built by sim_meshui, from the same widgets
as the 3D windows; the options it edits and the quality report are in sim_mesh2d.

A window that uses it has: e_h (the element size), b_mesh, lbl_h, geom, canvas (with .sel), regions (the list), mesh, status(text), refresh_sections() and a
`sections` list; and keeps its options in `mesh_opts` (see sim_mesh2d).  The tab's widgets are the single truth while the window is open (read_mesh_options);
`mesh_opts` is what is saved with the project and what the widgets are filled from (put_mesh_options).
"""
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QLabel, QTableWidgetItem

import sim_mesh2d as sm2
import sim_meshui


class Mesh2DHost:
    SIZE_BOX = "e_h"                 # the box of the element size (the CFD window: "e_hb", the size at the body)
    LOCAL_REGIONS = True             # a local size can go on a region (the CFD window has bodies, no regions)

    # ------------------------------------------------------------------ the page
    def build_mesh_page(self, lay):
        """Element size, the advanced options, the Mesh button, the line about the mesh and the quality box - in the order the 3D windows have them."""
        from PyQt6.QtWidgets import QFormLayout
        self.mesh_opts = sm2.default_mesh()
        mf = QFormLayout()
        mf.addRow(self.lbl_h, self.e_h)
        lay.addLayout(mf)
        sim_meshui.build_advanced(self, lay, 2, sm2.ORDERS, sm2.GROWTH_RANGE, sm2.CURV_RANGE)

    def build_mesh_foot(self, lay):
        """Under the Mesh button: what the mesh is, and how good it is."""
        lay.addWidget(self.b_mesh)
        self.mesh_lbl = QLabel("")
        self.mesh_lbl.setWordWrap(True)
        lay.addWidget(self.mesh_lbl)
        sim_meshui.build_quality(self, lay)

    # ------------------------------------------------------------------ the options
    def element_h(self):
        """The element size typed (0 when it is not a number yet)."""
        try:
            return float(getattr(self, self.SIZE_BOX).text().strip().replace(",", "."))
        except ValueError:
            return 0.0

    def element_order(self):
        """2 (quadratic) or 1 (linear): the order box counts only with the advanced options on."""
        return 1 if (self.cb_adv.isChecked() and self.order_combo is not None and self.order_combo.currentData() == 1) else 2

    def read_mesh_options(self):
        """The boxes into `mesh_opts`; returns them.  Raises ValueError (a sentence) for a bad number or a combination that cannot be meshed."""
        mo = sm2.complete(self.mesh_opts)                         # the local sizes stay as they are
        mo["advanced"] = self.cb_adv.isChecked()
        mo["order"] = (self.order_combo.currentData() or 2) if self.order_combo is not None else 2
        mo["curv"] = self.sp_curv.value() if self.cb_curv.isChecked() else 0
        self.mesh_opts = mo
        if not mo["advanced"]:
            return mo
        try:
            t = self.e_hmin.text().strip().replace(",", ".")
            mo["hmin"] = float(t) if t else 0.0
        except ValueError:
            raise ValueError("The minimum size must be a number (or blank for automatic).")
        try:
            mo["growth"] = float(self.e_growth.text().strip().replace(",", "."))
        except ValueError:
            raise ValueError("The growth rate must be a number.")
        why = sm2.validate(mo, self.element_h())
        if why:
            raise ValueError(why)
        return mo

    def mesher_options(self):
        """What the mesher is given (None = the plain automatic mesh).  Raises ValueError like read_mesh_options."""
        return sm2.options(self.read_mesh_options())

    def mesh_state(self):
        """The options for the saved project (the last valid ones when a box holds a bad number)."""
        try:
            self.read_mesh_options()
        except ValueError:
            pass
        return sm2.complete(self.mesh_opts)

    def restore_mesh_options(self, st):
        """From a saved state.  A file from before the advanced options kept the element order in a box of its own (the inputs): Linear there means the advanced
        options on, with linear elements."""
        mo = st.get("mesh_opts")
        if mo is None:
            mo = sm2.default_mesh()
            if "linear" in str((st.get("inputs") or {}).get("order_combo", "")).lower():
                mo["advanced"], mo["order"] = True, 1
        self.mesh_opts = sm2.complete(mo)
        self.put_mesh_options()

    def put_mesh_options(self):
        """The boxes from `mesh_opts` (after opening a project or changing the units)."""
        mo = sm2.complete(self.mesh_opts)
        self.mesh_opts = mo
        wds = [w for w in (self.cb_adv, self.cb_curv, self.sp_curv, self.order_combo) if w is not None]
        for wd in wds:
            wd.blockSignals(True)
        self.cb_adv.setChecked(bool(mo["advanced"]))
        if self.order_combo is not None:
            self.order_combo.setCurrentIndex(max(0, self.order_combo.findData(mo["order"])))
        self.cb_curv.setChecked(mo["curv"] > 0)
        self.sp_curv.setValue(mo["curv"] or 10)
        self.sp_curv.setEnabled(mo["curv"] > 0)
        for wd in wds:
            wd.blockSignals(False)
        self.e_hmin.setText(format(mo["hmin"], ".8g") if mo["hmin"] else "")
        self.e_growth.setText(format(mo["growth"], ".8g"))
        self.adv_box.setVisible(bool(mo["advanced"]))
        self.fill_local_table()
        self.refresh_mesh_info()

    def inputs_changed(self):
        """A box of the advanced options was edited."""
        try:
            self.read_mesh_options()
        except ValueError as ex:
            self.status(str(ex))
        self.refresh_mesh_info()
        self.refresh_sections()

    def adv_toggled(self, on):
        self.adv_box.setVisible(bool(on))
        self.inputs_changed()

    def curv_toggled(self, on):
        self.sp_curv.setEnabled(bool(on))
        self.inputs_changed()

    # ------------------------------------------------------------------ local sizes
    def region_names_for_sizes(self):
        names = {}
        for f in (self.geom["faces"] if self.geom is not None else []):
            nm = (getattr(self, "region_names", None) or {}).get(f["id"])
            names[("rg", f["id"])] = f"Region {f['id'] + 1}" + (f" [{nm}]" if nm else "")
        return names

    def fill_local_table(self):
        t = self.face_table
        t.blockSignals(True)
        t.setRowCount(0)
        ro = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        names = self.region_names_for_sizes()
        for r, x in enumerate(sm2.complete(self.mesh_opts)["local"]):
            t.insertRow(r)
            a = QTableWidgetItem(sm2.target_text(x["targets"], names))
            a.setFlags(ro)
            b = QTableWidgetItem(format(x["h"], ".8g"))
            b.setFlags(ro | Qt.ItemFlag.ItemIsEditable)
            t.setItem(r, 0, a)
            t.setItem(r, 1, b)
        t.blockSignals(False)
        L = self.unit_label()
        self.hmin_label.setText(f"Minimum size ({L})")

    def unit_label(self):
        import units
        return units.get(self.unit_name())["L"]

    def selected_local_targets(self):
        """What a local size goes on: the edges and points selected in the view, and the regions selected in the Regions list."""
        t = [(k, int(i)) for k, i in self.canvas.sel if k in ("pt", "ln", "ar", "sp", "ci")]
        if self.geom is not None and self.LOCAL_REGIONS:
            faces = self.geom["faces"]
            for it in self.regions.selectedItems():
                r = self.regions.row(it)
                if 0 <= r < len(faces):
                    t.append(("rg", int(faces[r]["id"])))
        return t

    def try_local_sizes(self, sizes):
        """Takes a new list of local sizes when the options stay valid with it; else says why not."""
        mo = sm2.complete(self.mesh_opts)
        mo["local"] = sizes
        why = sm2.validate(dict(mo, advanced=True), self.element_h())
        if why:
            self.status(why)
            return False
        self.mesh_opts = mo
        self.fill_local_table()
        self.refresh_sections()
        return True

    def set_face_size(self):
        if self.geom is None:
            self.status("Import a sketch first.")
            return False
        targets = self.selected_local_targets()
        if not targets:
            self.status("Select the edge(s), point(s) or region(s) first (click them in the view, or in the Regions list), then set the size."
                        if self.LOCAL_REGIONS else "Select the edge(s) or point(s) of a body first (click them in the view), then set the size.")
            return False
        try:
            hf = float(self.e_face_h.text().strip().replace(",", "."))
        except ValueError:
            self.status("Type the element size for the selection (a number).")
            return False
        sizes = [dict(x) for x in sm2.complete(self.mesh_opts)["local"]]
        key = sorted(targets)
        old = next((x for x in sizes if sorted(x["targets"]) == key), None)
        if old is not None:
            old["h"] = hf
        else:
            sizes.append({"targets": targets, "h": hf})
        if self.try_local_sizes(sizes):
            self.status(f"Element size {hf:.4g} {self.unit_label()} on {sm2.target_text(targets, self.region_names_for_sizes())}.")
            return True
        return False

    def remove_face_size(self):
        r = self.face_table.currentRow()
        sizes = [dict(x) for x in sm2.complete(self.mesh_opts)["local"]]
        if not 0 <= r < len(sizes):
            self.status("Select a row of the list first.")
            return False
        del sizes[r]
        return self.try_local_sizes(sizes)

    def face_item_changed(self, it):
        if it.column() != 1:
            return
        sizes = [dict(x) for x in sm2.complete(self.mesh_opts)["local"]]
        r = it.row()
        try:
            hf = float(it.text().strip().replace(",", "."))
        except ValueError:
            self.status("The size must be a number.")
            QTimer.singleShot(0, self.fill_local_table)
            return
        if 0 <= r < len(sizes):
            sizes[r]["h"] = hf
            if not self.try_local_sizes(sizes):
                QTimer.singleShot(0, self.fill_local_table)

    # ------------------------------------------------------------------ what the mesh is
    def mesh_kind_text(self):
        """What the elements are, for the line under the Mesh button."""
        return "quadratic" if self.element_order() == 2 else "linear"

    def refresh_mesh_info(self):
        """The line under the Mesh button and the quality box, from the mesh the window holds (nothing when there is none)."""
        if not hasattr(self, "mesh_lbl"):
            return
        mesh = self.mesh
        if mesh is None:
            self.mesh_lbl.setText("")
            self.quality_lbl.setText("")
            self.quality_box.setVisible(False)
            self._quality_cache = None
            return
        s = mesh["stats"]
        order = self.element_order()
        kind = self.mesh_kind_text()
        self.mesh_lbl.setText(f"{s['n_tris']:,} triangles, {s['n_nodes']:,} nodes ({kind})")
        if not self.cb_adv.isChecked():
            self.quality_lbl.setText("")
            self.quality_box.setVisible(False)
            return
        c = getattr(self, "_quality_cache", None)
        if c is None or c[0] is not mesh or c[1] != order:
            qr = sm2.quality(mesh, order)
            c = self._quality_cache = (mesh, order, qr)
        qr = c[2]
        L = self.unit_label()
        self.quality_lbl.setText(sim_meshui.quality_html2d(qr, sm2.verdict(qr), lambda v: v, L, kind))
        self.quality_box.setVisible(True)

    def mesh_diag_lines(self):
        """The mesh options for the Diagnostics report."""
        mo = self.mesh_state()
        if not mo["advanced"]:
            return ["mesh options: plain (advanced options off: quadratic elements, no minimum size, no refinement at curves)"]
        names = self.region_names_for_sizes()
        out = [f"mesh options: advanced - order {mo['order']}, minimum size {mo['hmin']:g}" + (" (automatic)" if not mo["hmin"] else "") +
               f", growth rate {mo['growth']:g}, refinement at curved edges " + (f"{mo['curv']} per circle" if mo["curv"] else "off")]
        for x in mo["local"]:
            out.append(f"  local size {x['h']:g}: {sm2.target_text(x['targets'], names)}")
        return out
