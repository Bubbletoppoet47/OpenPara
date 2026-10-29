"""
sim_tab.py - the 1D FEA, 2D FEA and 2D CFD containers (a "simulation" document tab, saved as a .gps file).

A simulation belongs to a part or an assembly (its source).  What it works on is a COPY (a snapshot) of a 2D sketch:
  * a part:      one of its sketches, or a slice - a plane that cuts the part (a base plane, a reference plane, with an offset)
  * an assembly: only a slice (a plane cuts all its parts; touching parts are bonded)
The Refresh button takes the snapshot again from the source (the sketch or the slice as it is now); that clears the mesh and result.
The material of the part (Material in its tree) fills the material boxes by itself; in an assembly slice every region uses the material
of the part it was cut from.  The solvers and tabs are the ones of the earlier program (physics_tab, cfd_tab, beam_tab).
"""
import json
import os
import types

import numpy as np

from PyQt6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

import beam_tab
import cfd_tab
import mat_lib
import physics_materials as pmat
import physics_store as pstore
import physics_tab
import sim_slice
import sketcher_core as sc
import slice3d
import slice_sketch as ss
import unitctl
import units

KINDS = {"beam": ("1D FEA", beam_tab.BeamTab), "fea": ("2D FEA", physics_tab.PhysicsTab), "cfd": ("2D CFD", cfd_tab.CFDTab)}
SLICE_NEW, SLICE_LAST = "__slice_new__", "__slice_last__"


class _HostModel:
    """The solver tabs read `win.m.unit_system`: it is the program's unit system (File > Units)."""

    @property
    def unit_system(self):
        return unitctl.system()


class SimHost:
    """What the solver tabs call their 'window': they ask it for the sketches to import and show its status."""

    def __init__(self, sim):
        self.sim = sim
        self.doc = None
        self.m = _HostModel()
        self._restoring = False

    def status(self, text):
        self.sim.status_lbl.setText(text)

    def sketch_list(self):
        return self.sim.source_items()

    def sketch_json(self, sid):
        return self.sim.source_json(sid)


def fill_material(tab, kind, mat):
    """Puts a part material into the material boxes of a 1D / 2D FEA tab (in the tab's units).  False when it has no elastic values."""
    e = mat_lib.elastic(mat_lib.with_elastic(mat))
    if e is None:
        return False
    E, nu, sy, su = e
    u = tab.cur_unit
    tab.mat_combo.blockSignals(True)
    tab.mat_combo.setCurrentIndex(0)                                  # "(custom values)": the values come from the part
    tab.mat_combo.blockSignals(False)
    tab.e_E.setText(f"{pmat.from_mpa(E, u):.10g}")
    tab.e_sy.setText(f"{pmat.from_mpa(sy, u):.10g}")
    tab.e_su.setText(f"{pmat.from_mpa(su, u):.10g}")
    if kind == "fea":
        tab.e_nu.setText(f"{nu:.6g}")
    return True


class SimWindow(QWidget):
    plotter = None
    nav = None

    def __init__(self, kind, shell=None, src_tab=None, path=None):
        super().__init__()
        self.kind = kind
        self.label, cls = KINDS[kind]
        self.shell = shell
        self.src_tab = src_tab
        self.path = path
        self.src = {"type": "asm" if (src_tab is not None and hasattr(src_tab, "asm")) else "part", "path": getattr(src_tab, "path", None),
                    "name": src_tab.title() if src_tab is not None else ""}
        self.meta = {"sid": None, "slice": None}
        self.pending = None
        self.host = SimHost(self)
        self.saved_sig = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        bar = QHBoxLayout()
        self.src_lbl = QLabel()
        bar.addWidget(self.src_lbl, 1)
        self.b_refresh = QPushButton("Refresh from source")
        self.b_refresh.setToolTip("Takes the sketch or the slice again from the part / assembly as it is now. This clears the mesh and "
                                  "result, because the geometry may have changed.")
        self.b_refresh.clicked.connect(self.refresh)
        bar.addWidget(self.b_refresh)
        lay.addLayout(bar)
        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet("color:#707070;")
        self.tab = cls(self.host)
        self.tab.picker.on_import = self.on_imported
        lay.addWidget(self.tab, 1)
        lay.addWidget(self.status_lbl)
        self.show_source()
        self.saved_sig = self.signature()

    # ------------------------------------------------------------------ title / dirty / files
    def title(self):
        base = os.path.splitext(os.path.basename(self.path))[0] if self.path else f"{self.label} - {self.src.get('name') or 'source'}"
        return base

    def show_source(self):
        kind = "assembly" if self.src["type"] == "asm" else "part"
        rule = ("slice only (a plane through the parts; touching parts are bonded)" if kind == "assembly" else
                ("sketch of the part" if self.kind == "beam" else "sketch of the part, or a slice"))
        self.src_lbl.setText(f"<b>{self.label}</b> of the {kind} <b>{self.src.get('name') or '?'}</b> - works on: {rule}")

    def signature(self):
        t = self.tab
        if getattr(t, "model", None) is None:
            return None
        try:
            ins = pstore.get_inputs(t, t.INPUTS)
        except Exception:
            ins = {}
        return (repr(getattr(t, "supports", None)), repr(getattr(t, "loads", None)), id(getattr(t, "mesh", None)),
                id(getattr(t, "result", None)), repr(sorted(ins.items())), repr(getattr(t, "members", None)),
                repr([bool(f["included"]) for f in t.geom["faces"]]) if getattr(t, "geom", None) else "")

    def is_dirty(self):
        return self.signature() != self.saved_sig

    def save(self, as_new=False):
        path = self.path
        if as_new or not path:
            start = path or (os.path.join(os.path.dirname(self.src["path"] or ""), self.title() + ".gps") if self.src.get("path") else self.title() + ".gps")
            path, _ = QFileDialog.getSaveFileName(self, "Save simulation", start, "Simulation (*.gps)")
            if not path:
                return False
            if not path.lower().endswith(".gps"):
                path += ".gps"
        meta = {"kind": self.kind, "source": {"type": self.src["type"], "name": self.src.get("name"),
                                              "path": self.rel(path, self.src.get("path"))},
                "meta": self.meta}
        try:
            pstore.save(path, {"main": self.tab}, extras={"sim.json": json.dumps(meta).encode("utf-8")})
        except Exception as ex:
            import traceback
            QMessageBox.warning(self, "Save", f"Could not save: {ex}\n\n{traceback.format_exc()}")
            return False
        self.path = path
        self.saved_sig = self.signature()
        note = ""
        src = self.live_source()
        if src is not None:
            import sim_links
            if sim_links.add(src, path):
                src.refresh_tree()
                note = f"  - listed under Simulations of the {'assembly' if self.src['type'] == 'asm' else 'part'}; save it to keep the link"
        self.status_lbl.setText(f"Saved {path}{note}")
        return True

    @staticmethod
    def rel(path, target):
        if not target:
            return None
        try:
            return os.path.relpath(target, os.path.dirname(os.path.abspath(path)))
        except ValueError:
            return target

    @classmethod
    def open_file(cls, shell, path):
        b = pstore.open_bundle(path)
        if b is None:
            raise ValueError("not found")
        meta = json.loads(b.read("sim.json").decode("utf-8"))
        data = pstore.load(path) or {}
        kind = meta["kind"]
        sp = meta["source"].get("path")
        src_path = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(path)), sp)) if sp and not os.path.isabs(sp) else sp
        w = cls(kind, shell=shell, src_tab=None, path=path)
        w.src = {"type": meta["source"].get("type", "part"), "path": src_path, "name": meta["source"].get("name", "")}
        w.meta = meta.get("meta") or {"sid": None, "slice": None}
        w.show_source()
        st = data.get("main")
        if st is not None:
            note = ""
            try:                                           # a file saved in other units opens converted to the program's units
                st = pstore.to_current_units(kind, st, unitctl.system(), unitctl.speed())
            except (ValueError, KeyError) as ex:
                note = f"kept in its own units ({ex})"
            w.units_note = note
            w.host._restoring = True
            try:
                w.tab.import_state(st)
            finally:
                w.host._restoring = False
        w.saved_sig = w.signature()
        return w

    def update_all(self, fit=False):
        pass

    def units_changed(self, old_s, new_s, old_v, new_v):
        """File > Units was changed: the solver tab's sketch copy, numbers, loads and results are converted (a mesh or result that
        cannot be converted is cleared - solve again).  The speed unit is converted separately."""
        t = self.tab
        msgs = []
        if getattr(t, "model", None) is None:
            try:                                           # nothing imported yet: only the boxes hold numbers
                if units.canon(old_s) != units.canon(new_s):
                    if hasattr(t, "convert_input_units"):
                        t.convert_input_units(new_s)
                    elif hasattr(t, "apply_units"):
                        t.apply_units(new_s)
                if old_v != new_v and hasattr(t, "e_speed"):
                    txt = t.e_speed.text().strip()
                    if txt:
                        t.e_speed.setText(f"{float(txt) * units.speed_factor(old_v, new_v):.6g}")
            except Exception:
                pass
            return
        if units.canon(old_s) != units.canon(new_s):
            try:
                m = t.change_units(old_s, new_s, True)
                if m:
                    msgs.append(m)
            except ValueError as ex:
                msgs.append(f"kept in {old_s}: {ex}")
        if old_v != new_v and self.kind in ("cfd", "beam"):
            t.import_state(pstore.speed_state(t.export_state(), old_v, new_v))
        self.status_lbl.setText(f"Units: {new_s}, speed in {new_v}." + ((" " + " ".join(msgs)) if msgs else ""))

    # ------------------------------------------------------------------ the source
    def live_source(self):
        """The open tab of the source part / assembly, or None (never opens anything)."""
        w = self.src_tab
        if w is None and self.shell is not None and self.src.get("path"):
            i = self.shell.find_tab(self.src["path"])
            w = self.shell.tabs.widget(i) if i is not None else None
        if w is None:
            return None
        try:
            w.title()
            if self.shell is None or self.shell.tabs.indexOf(w) >= 0:
                return w
        except RuntimeError:
            pass
        return None

    def source_widget(self):
        """The part / assembly tab this simulation belongs to (opened again when it was closed)."""
        w = self.src_tab
        if w is not None:
            try:
                w.title()
                if self.shell is None or self.shell.tabs.indexOf(w) >= 0:
                    return w
            except RuntimeError:
                pass
        p = self.src.get("path")
        if self.shell is None or not p or not os.path.exists(p):
            return None
        here = self.shell.tabs.indexOf(self)
        w = self.shell.open_path(p)
        if here >= 0:
            self.shell.tabs.setCurrentIndex(self.shell.tabs.indexOf(self))
        self.src_tab = w
        return w

    def part_doc(self):
        w = self.source_widget()
        return getattr(w, "doc", None) if w is not None and self.src["type"] == "part" else None

    def bodies(self):
        """[(name, solid, material)] of the source (a part: itself; an assembly: its parts, placed)."""
        w = self.source_widget()
        if w is None:
            return []
        if self.src["type"] == "part":
            d = w.doc
            return [(self.src.get("name") or "part", d.solid, d.material)] if d is not None and d.solid is not None else []
        import asm_sub
        return asm_sub.bodies_of(w, w.asm)

    def planes(self):
        w = self.source_widget()
        if w is None:
            return []
        if self.src["type"] == "part":
            return slice3d.part_plane_specs(w.doc) if w.doc is not None else []
        return slice3d.asm_plane_specs(w.asm)

    def visible_planes(self):
        """The planes the source viewport shows (hidden planes are left out of the slice window)."""
        return sim_slice.visible_planes(self.source_widget(), self.src["type"])

    def source_items(self):
        items = []
        d = self.part_doc() if self.src["type"] == "part" else None
        if d is not None:
            items += [(f["id"], f["name"]) for f in d.features if f["kind"] == "sketch"]
        if self.kind != "beam":
            items.append((SLICE_NEW, "Slice with a plane..."))
            sl = self.meta.get("slice")
            if sl:
                items.append((SLICE_LAST, "Slice again: " + self.slice_text(sl)))
        return items

    @staticmethod
    def slice_text(sl):
        return f"{sl['plane']} {unitctl.to_disp(sl.get('offset', 0)):+.6g} {unitctl.length_unit()}" + (" (flipped)" if sl.get("flip") else "")

    def source_json(self, sid):
        """(name, sketch JSON text) for an item of the picker, or None."""
        if sid in (SLICE_NEW, SLICE_LAST):
            return self.slice_json(sid == SLICE_LAST)
        d = self.part_doc()
        f = d.feature(sid) if d is not None else None
        if f is None or f["kind"] != "sketch":
            self.status_lbl.setText("That sketch is no longer in the part.")
            return None
        text = f["model"] if isinstance(f["model"], str) else json.dumps(f["model"])
        self.pending = None
        return f["name"], text

    def slice_json(self, again):
        planes = self.planes()
        bodies = self.bodies()
        if not planes or not bodies:
            QMessageBox.information(self, "Slice", "There is no solid to slice yet (is the source open and does it have a solid?).")
            return None
        spec = self.meta.get("slice") if again else None
        if spec is None:
            vis = self.visible_planes()
            dlg = sim_slice.SliceDialog(self, vis, bodies, self.meta.get("slice"), multi=self.src["type"] == "asm")
            if not dlg.exec() or dlg.out is None:
                return None
            spec = dlg.out
        if spec.get("face"):
            pl = {k: np.array(v, float) for k, v in spec["face"].items()}
        else:
            pl = dict(planes).get(spec["plane"])
        if pl is None:
            QMessageBox.information(self, "Slice", f"The plane '{spec['plane']}' no longer exists.")
            return None
        use = [(i, b) for i, b in enumerate(bodies) if b[0] not in spec.get("excluded", [])]
        sp = slice3d.shifted(pl, spec.get("offset", 0.0), spec.get("flip", False))
        loops = slice3d.slice_bodies([(i, b[1]) for i, b in use], sp)
        if not loops:
            QMessageBox.information(self, "Slice", "The plane does not cut any part. Move it (offset) or choose another plane.")
            return None
        m = sc.Model()
        scale = 1.0e-3 / units.get(m.unit_system)["L_m"]
        bld = ss._Builder(m, loops, scale)
        bld.make_geometry()
        self.pending = {"loops": loops, "bodies": [(b[0], b[2]) for i, b in enumerate(bodies)], "scale": scale, "notes": list(bld.notes)}
        self.meta["slice"] = dict(spec)
        return "Slice " + self.slice_text(spec), m.to_json()

    # ------------------------------------------------------------------ after an import
    def on_imported(self, sid, text, name):
        t = self.tab
        t.import_picked(sid, text, name)
        sid = SLICE_LAST if sid == SLICE_NEW else sid           # Refresh repeats the slice without asking again
        self.meta["sid"] = sid
        notes = []
        mats = None
        if sid == SLICE_LAST and self.pending is not None:
            mats = self.apply_regions()
            notes += self.pending.get("notes", [])
        if self.kind in ("fea", "beam"):
            first = None
            if mats:
                first = next((m for m in mats.values() if mat_lib.elastic(m)), None)
            elif self.src["type"] == "part" and self.part_doc() is not None:
                first = self.part_doc().material
            if first is not None:
                if fill_material(t, self.kind, first):
                    notes.append(f"Material from the part: {mat_lib.summary(mat_lib.with_elastic(first))}.")
                else:
                    notes.append("The part's material has no elastic properties: type E and Poisson's ratio (or choose another material in the part).")
        self.tab.picker.refresh()
        self.tab.picker.select(sid)
        if notes:
            self.status_lbl.setText("  ".join(notes))

    def apply_regions(self):
        """Names the regions of a slice by the part they come from, switches off the ones that belong to no part (holes), and (2D FEA) gives each
        its material.  -> {region id: material dict} or None."""
        t, p = self.tab, self.pending
        if getattr(t, "geom", None) is None:
            return None
        rp = slice3d.region_parts(t.geom, p["loops"])
        names = {f: p["bodies"][i][0] for f, i in rp.items() if i is not None}
        mats = {f: mat_lib.with_elastic(p["bodies"][i][1]) for f, i in rp.items() if i is not None}
        if self.kind == "cfd":
            return mats
        if self.kind == "fea":
            for f in t.geom["faces"]:
                if rp.get(f["id"]) is None:
                    f["included"] = False              # inside a hole of a part: no material there
            t.region_names = names
            t.region_mats = {f: {"E_MPa": e[0], "nu": e[1], "Sy_MPa": e[2], "Su_MPa": e[3]} for f, m in mats.items()
                             for e in [mat_lib.elastic(m)] if e is not None}
            missing = [names[f] for f, m in mats.items() if mat_lib.elastic(m) is None]
            t.fill_regions()
            t.refresh_lists()
            t.canvas.invalidate()
            if missing:
                self.status_lbl.setText("No elastic properties for: " + ", ".join(sorted(set(missing))) + ". These regions use the material boxes of the tab.")
        return mats

    def refresh(self):
        sid = self.meta.get("sid")
        if sid is None:
            self.status_lbl.setText("Nothing imported yet: choose a sketch or a slice and press Import.")
            return
        if self.tab.result is not None or self.tab.mesh is not None:
            if QMessageBox.question(self, "Refresh", "Taking the geometry again clears the supports, loads, mesh and result of this tab. Continue?") \
                    != QMessageBox.StandardButton.Yes:
                return
        self.tab.picker.refresh()
        self.tab.picker.select(sid)
        self.tab.picker.go()
