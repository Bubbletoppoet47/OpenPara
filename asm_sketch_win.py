"""asm_sketch_win.py - the Assembly Sketch window: a sketch of its own file (.gpk) whose exported variables drive the assembly and the parts linked to it.
The window is the part window with its sketcher (tools, relations, dimensions, symbols, configurations) plus a Variables tab: the Export box of each
variable, and the Linked files panel (one assembly - required - and any number of parts, open or not, saved by their location relative to the sketch)."""
import os

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (QAbstractItemView, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QListWidget, QMessageBox, QPushButton,
                             QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

import asm_sketch as ak
import pm_app
import unitctl


class AsmSketchWindow(pm_app.MainWindow):
    asm_sketch = True                  # the sketcher offers Make driven / Make driving on a dimension here only
    KIND = "asmsketch"

    def __init__(self, path=None, shell=None):
        self.shell = shell
        self.assembly = None                 # absolute path of the assembly it belongs to
        self.parts = []                      # absolute paths of the parts it drives
        self.push_timer = None
        self.var_table = None
        self.vbusy = False
        super().__init__(None)
        self.setWindowTitle("Assembly Sketch")
        self.build_vars_panel()
        self.push_timer = QTimer(self)
        self.push_timer.setSingleShot(True)
        self.push_timer.timeout.connect(self.push_now)
        if path and os.path.isfile(path):
            self.open_file(path)
        else:
            self.doc = ak.new_document()
            self.saved_json = self.doc.to_json()
        self.update_all(fit=True)
        QTimer.singleShot(0, self.start_editing)

    def demo(self):                          # a new window is an empty assembly sketch, not the part window's demo part
        pass

    def start_editing(self):
        f = ak.sketch_feature(self.doc)
        if f is not None:
            try:
                self.enter_sketch(f["id"])
            except Exception as ex:          # noqa: BLE001  (the window stays usable: double-click the sketch in the tree)
                self.say(f"Could not start the sketch by itself ({ex}): double-click it in the tree.")

    def title(self):
        return os.path.basename(self.path) if self.path else getattr(self, "tab_name", None) or "Assembly Sketch 1"

    # ------------------------------------------------------------------ files
    def open_dialog(self):
        p, _ = QFileDialog.getOpenFileName(self, "Open assembly sketch", "", "Assembly sketch (*.gpk)")
        if p:
            self.open_file(p)
            self.update_all(fit=True)

    def base(self):
        return os.path.dirname(os.path.abspath(self.path)) if self.path else None

    def open_file(self, p):
        try:
            doc, asm, parts = ak.load(p)
        except Exception as ex:              # noqa: BLE001
            QMessageBox.warning(self, "Open", str(ex))
            return
        base = os.path.dirname(os.path.abspath(p))
        self.doc, self.path = doc, p
        self.assembly = ak.absolute(asm, base) if asm else None
        self.parts = [ak.absolute(x, base) for x in parts]
        self.sel = self.sel_face = self.sel_plane = None
        self.undo, self.redo = [], []
        self.saved_json = doc.to_json()
        self.setWindowTitle(f"Assembly Sketch - {os.path.basename(p)}")

    def save(self, as_new=False):
        old = self.base()
        if as_new or not self.path:
            p, _ = QFileDialog.getSaveFileName(self, "Save assembly sketch", self.path or "sketch.gpk", "Assembly sketch (*.gpk)")
            if not p:
                return False
            self.path = p if p.endswith(ak.EXT) else p + ak.EXT
        base = self.base()
        ak.save(self.path, self.doc, ak.rel(self.assembly, base) if self.assembly else None, [ak.rel(x, base) for x in self.parts])
        self.saved_json = self.doc.to_json()
        self.setWindowTitle(f"Assembly Sketch - {os.path.basename(self.path)}")
        self.say(f"Saved {self.path}" + ("  (the linked files keep the old location of this sketch until you press Update linked files)" if old and old != base and (self.parts or self.assembly) else ""))
        self.refresh_vars()
        return True

    # ------------------------------------------------------------------ the Variables tab
    def build_vars_panel(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addWidget(QLabel("Variables: the symbols and named dimensions of this sketch, one number per configuration.\n"
                             "Tick Export for the ones the linked files should receive (as AS-<configuration>-<name>)."))
        self.var_table = QTableWidget(0, 4)
        self.var_table.itemChanged.connect(self.export_changed)
        lay.addWidget(self.var_table, 1)
        box = QGroupBox("Linked files")
        bl = QVBoxLayout(box)
        r = QHBoxLayout()
        r.addWidget(QLabel("Assembly (required):"))
        self.asm_label = QLabel("(none)")
        self.asm_label.setWordWrap(True)
        r.addWidget(self.asm_label, 1)
        b = QPushButton("Set...")
        b.clicked.connect(self.pick_assembly)
        r.addWidget(b)
        b = QPushButton("Open")
        b.clicked.connect(lambda: self.open_in_shell(self.assembly))
        r.addWidget(b)
        bl.addLayout(r)
        bl.addWidget(QLabel("Parts (at least one, no limit; each part follows one sketch):"))
        self.part_list = QListWidget()
        self.part_list.setMaximumHeight(120)
        self.part_list.itemDoubleClicked.connect(lambda it: self.open_in_shell(self.parts[self.part_list.row(it)]))
        bl.addWidget(self.part_list)
        r = QHBoxLayout()
        b = QPushButton("Add parts...")
        b.clicked.connect(self.pick_parts)
        r.addWidget(b)
        b = QPushButton("Add open parts")
        b.setToolTip("Link every part that is open in a tab")
        b.clicked.connect(self.add_open_parts)
        r.addWidget(b)
        b = QPushButton("Remove")
        b.setToolTip("Stop driving the selected part (its configurations stay; the numbers go)")
        b.clicked.connect(self.remove_part)
        r.addWidget(b)
        bl.addLayout(r)
        b = QPushButton("Update linked files now")
        b.setToolTip("Open files follow live; this also writes the numbers into the files that are not open (they pull them when opened anyway)")
        b.clicked.connect(lambda: self.push_now(write_closed=True))
        bl.addWidget(b)
        lay.addWidget(box)
        self.vars_status = QLabel("")
        self.vars_status.setWordWrap(True)
        lay.addWidget(self.vars_status)
        self.left.addTab(w, "Variables")
        self.left.setCurrentIndex(self.left.count() - 1)

    @staticmethod
    def _shown(kind, x):
        if kind == "length":
            return f"{unitctl.to_disp(x):.6g}"
        return f"{x:.6g}"

    def refresh_vars(self):
        if self.var_table is None:
            return
        try:
            configs, vars_, values = ak.variables(self.doc)
        except Exception as ex:              # noqa: BLE001
            self.vars_status.setText(f"Could not read the variables: {ex}")
            return
        t = self.var_table
        self.vbusy = True
        t.setRowCount(len(vars_))
        t.setColumnCount(4 + len(configs))
        t.setHorizontalHeaderLabels(["Export", "Variable", "Kind", "Role"] + configs)
        for r, v in enumerate(vars_):
            cb = QTableWidgetItem("")
            cb.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            cb.setCheckState(Qt.CheckState.Checked if v["export"] else Qt.CheckState.Unchecked)
            cb.setData(Qt.ItemDataRole.UserRole, v["name"])
            t.setItem(r, 0, cb)
            kind = f"length ({unitctl.length_unit()})" if v["kind"] == "length" else ("angle (deg)" if v["kind"] == "angle" else "number")
            for c, txt in ((1, v["name"]), (2, kind), (3, v["role"])):
                it = QTableWidgetItem(txt)
                it.setFlags(Qt.ItemFlag.ItemIsEnabled)
                t.setItem(r, c, it)
            for j, c in enumerate(configs):
                x = values.get(c, {}).get(v["name"])
                it = QTableWidgetItem("" if x is None else self._shown(v["kind"], x))
                it.setFlags(Qt.ItemFlag.ItemIsEnabled)
                if v["role"] == "driven":
                    it.setBackground(QBrush(QColor("#eef2f7")))
                t.setItem(r, 4 + j, it)
        t.resizeColumnsToContents()
        self.vbusy = False
        self.asm_label.setText(self.assembly or "(none: set the assembly this sketch belongs to)")
        self.part_list.clear()
        for p in self.parts:
            self.part_list.addItem(p + ("" if os.path.isfile(p) else "   (not found)"))
        msg = []
        if not vars_:
            msg.append("No variables yet: make a symbol (Sketch > Parameters) or give a dimension a name; a driven symbol takes the number the geometry measures.")
        elif not any(v["export"] for v in vars_):
            msg.append("Nothing is exported yet: tick Export on the variables the assembly and parts should receive.")
        if not self.assembly:
            msg.append("This sketch needs an assembly: press Set... next to Assembly.")
        elif not self.parts:
            msg.append("Add at least one part.")
        self.vars_status.setText("  ".join(msg))

    def export_changed(self, item):
        if self.vbusy or item.column() != 0:
            return
        name = item.data(Qt.ItemDataRole.UserRole)
        on = item.checkState() == Qt.CheckState.Checked
        if (name in self.doc.export) == on:
            return
        self.snapshot()
        ak.set_export(self.doc, name, on)
        self.update_all(keep_props=True)

    def update_all(self, fit=False, keep_props=False, light=False):
        super().update_all(fit, keep_props, light)
        if self.var_table is not None:
            self.refresh_vars()
            if self.push_timer is not None and (self.parts or self.assembly):
                self.push_timer.start(350)

    # ------------------------------------------------------------------ the shell (the program window with the tabs)
    def host(self):
        return self.shell or self.window()

    def open_obj(self, path):
        """The live Document / Assembly of a file that is open in a tab, else None."""
        sh = self.host()
        tabs = getattr(sh, "tabs", None)
        if tabs is None or not hasattr(sh, "find_tab"):
            return None
        i = sh.find_tab(path)
        w = tabs.widget(i) if i is not None else None
        if w is None or getattr(w, "KIND", "") == "asmsketch":
            return None
        return getattr(w, "asm", None) or (getattr(w, "doc", None) if hasattr(w, "update_all") else None)

    def refresh_window(self, path):
        sh = self.host()
        i = sh.find_tab(path) if hasattr(sh, "find_tab") else None
        w = sh.tabs.widget(i) if i is not None else None
        if w is None or not hasattr(w, "update_all"):
            return
        try:
            w.update_all(keep_props=True)
        except TypeError:
            w.update_all()

    def open_in_shell(self, path):
        if path and hasattr(self.host(), "open_path"):
            self.host().open_path(path)

    # ------------------------------------------------------------------ linking
    def need_saved(self):
        if self.path:
            return True
        QMessageBox.information(self, "Linked files", "Save the sketch first: the linked files find it by its location.")
        return False

    def sketch_of(self, path):
        """Absolute path of the sketch a file follows now (None when it follows none)."""
        o = self.open_obj(path)
        if o is None and os.path.isfile(path):
            try:
                o = ak.load_target(path)
            except Exception:                # noqa: BLE001
                return None
        if o is None or not getattr(o, "gsv", None):
            return None
        if o.base_dir is None:
            o.base_dir = os.path.dirname(os.path.abspath(path))
        return o.gsv_src_path()

    def assembly_parts(self):
        """Absolute paths of the parts the linked assembly is made of ([] when unknown)."""
        if not self.assembly:
            return []
        try:
            a = self.open_obj(self.assembly) or ak.load_target(self.assembly)
        except Exception:                    # noqa: BLE001
            return []
        base = os.path.dirname(self.assembly)
        return [os.path.normcase(os.path.normpath(ak.absolute(c["path"], base))) for c in a.components if c.get("path")]

    def link_one(self, path):
        """Write the link into the file (live when open) and give it the numbers.  Returns True when linked."""
        mine = os.path.normcase(os.path.normpath(self.path))
        other = self.sketch_of(path)
        if other and os.path.normcase(os.path.normpath(other)) != mine and os.path.isfile(other):
            QMessageBox.warning(self, "Linked files", f"{os.path.basename(path)} already follows another assembly sketch ({os.path.basename(other)}).\n"
                                                      "A file follows one sketch: remove it from that sketch first.")
            return False
        st, msgs = ak.link(path, self.path, self.doc, self.open_obj(path))
        if st.startswith("error") or st == "missing":
            QMessageBox.warning(self, "Linked files", f"{os.path.basename(path)}: {st}")
            return False
        if st == "open":
            self.refresh_window(path)
        self.vars_status.setText(f"Linked {os.path.basename(path)} ({'open: updated live' if st == 'open' else 'written into the file'})." + ("  " + "; ".join(msgs) if msgs else ""))
        return True

    def pick_assembly(self):
        if not self.need_saved():
            return
        p, _ = QFileDialog.getOpenFileName(self, "Assembly this sketch belongs to", self.base(), "Assembly (*.gpa)")
        if not p:
            return
        p = os.path.normpath(os.path.abspath(p))
        if self.assembly and self.assembly != p:
            ak.unlink(self.assembly, self.open_obj(self.assembly))
            self.refresh_window(self.assembly)
        if self.link_one(p):
            self.assembly = p
            self.refresh_vars()
            self.warn_outsiders()

    def add_part(self, path):
        path = os.path.normpath(os.path.abspath(path))
        if path in self.parts:
            return True
        if not path.lower().endswith(".gpd"):
            QMessageBox.warning(self, "Linked files", "Only part files (.gpd) go in the parts list: the assembly has its own line.")
            return False
        if not self.need_saved():
            return False
        if not self.assembly:
            QMessageBox.information(self, "Linked files", "Set the assembly first: every assembly sketch belongs to one assembly.")
            return False
        if not self.link_one(path):
            return False
        self.parts.append(path)
        self.refresh_vars()
        if self.assembly_parts() and os.path.normcase(path) not in self.assembly_parts():
            self.vars_status.setText(self.vars_status.text() + f"  Note: {os.path.basename(path)} is not a component of {os.path.basename(self.assembly)} (it is linked anyway).")
        return True

    def warn_outsiders(self):
        inside = self.assembly_parts()
        if not inside:
            return
        out = [os.path.basename(p) for p in self.parts if os.path.normcase(p) not in inside]
        if out:
            self.vars_status.setText(self.vars_status.text() + "  Not components of the assembly: " + ", ".join(out))

    def pick_parts(self):
        if not self.need_saved():
            return
        files, _ = QFileDialog.getOpenFileNames(self, "Parts this sketch drives", self.base(), "Part (*.gpd)")
        for p in files:
            self.add_part(p)

    def add_open_parts(self):
        sh = self.host()
        tabs = getattr(sh, "tabs", None)
        n = 0
        for i in range(tabs.count() if tabs is not None else 0):
            w = tabs.widget(i)
            p = getattr(w, "path", None)
            if p and p.lower().endswith(".gpd") and getattr(w, "KIND", "") != "asmsketch":
                n += bool(self.add_part(p))
        if not n:
            self.say("No saved part is open in a tab.")

    def remove_part(self):
        i = self.part_list.currentRow()
        if not (0 <= i < len(self.parts)):
            return
        p = self.parts.pop(i)
        ak.unlink(p, self.open_obj(p))
        self.refresh_window(p)
        self.refresh_vars()

    def push_now(self, write_closed=False):
        files = ([self.assembly] if self.assembly else []) + self.parts
        if not self.path or not files:
            if write_closed:
                self.vars_status.setText("Save the sketch first: the linked files find it by its location." if not self.path else "No linked files yet.")
            return
        res = ak.push(self.path, self.doc, files, self.open_obj, write_closed=write_closed)
        for p, state, _m in res:
            if state == "open":
                self.refresh_window(p)
        if write_closed:
            n = {s: sum(1 for _p, x, _m in res if x == s) for s in ("open", "written", "skipped", "missing")}
            bad = [f"{os.path.basename(p)}: {s}" for p, s, _m in res if s.startswith("error")]
            self.vars_status.setText(f"{n['open']} open file(s) updated, {n['written']} file(s) written, {n['missing']} not found." + ("  " + "; ".join(bad) if bad else ""))
