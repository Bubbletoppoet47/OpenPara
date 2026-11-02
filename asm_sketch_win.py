"""asm_sketch_win.py - the Assembly Sketch window (a sketch of its own file, .gpk, whose variables drive parts) and the part-side "Link to Assembly
Sketch" dialog.  The sketch window is the part window with its sketcher (tools, relations, dimensions, symbols, configurations) plus a Variables tab."""
import os

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                             QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

import asm_sketch as ak
import pm_app


class AsmSketchWindow(pm_app.MainWindow):
    KIND = "asmsketch"

    def __init__(self, path=None, shell=None):
        self.shell = shell
        self.parts = []                      # absolute paths of the parts it drives
        self.push_timer = None
        self.var_table = None
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

    def open_file(self, p):
        try:
            doc, parts = ak.load(p)
        except Exception as ex:              # noqa: BLE001
            QMessageBox.warning(self, "Open", str(ex))
            return
        self.doc, self.path = doc, p
        self.parts = [ak.absolute(x, os.path.dirname(os.path.abspath(p))) for x in parts]
        self.sel = self.sel_face = self.sel_plane = None
        self.undo, self.redo = [], []
        self.saved_json = doc.to_json()
        self.setWindowTitle(f"Assembly Sketch - {os.path.basename(p)}")

    def save(self, as_new=False):
        if as_new or not self.path:
            p, _ = QFileDialog.getSaveFileName(self, "Save assembly sketch", self.path or "sketch.gpk", "Assembly sketch (*.gpk)")
            if not p:
                return False
            self.path = p if p.endswith(ak.EXT) else p + ak.EXT
        base = os.path.dirname(os.path.abspath(self.path))
        ak.save(self.path, self.doc, [ak.rel(x, base) for x in self.parts])
        self.saved_json = self.doc.to_json()
        self.setWindowTitle(f"Assembly Sketch - {os.path.basename(self.path)}")
        self.say(f"Saved {self.path}")
        self.refresh_vars()
        return True

    # ------------------------------------------------------------------ the Variables tab
    def build_vars_panel(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addWidget(QLabel("Variables: the symbols and named dimensions of this sketch, one number per configuration.\n"
                             "Parts take them one way (Configurations tab of a part > Link to Assembly Sketch...)."))
        self.var_table = QTableWidget(0, 2)
        self.var_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        lay.addWidget(self.var_table, 1)
        lay.addWidget(QLabel("Parts this sketch drives:"))
        self.part_list = QListWidget()
        self.part_list.setMaximumHeight(110)
        lay.addWidget(self.part_list)
        row = QHBoxLayout()
        b = QPushButton("Update parts now")
        b.setToolTip("Write the numbers into the parts that are not open too (open parts follow live; others read them when they are opened)")
        b.clicked.connect(lambda: self.push_now(write_closed=True))
        row.addWidget(b)
        b = QPushButton("Forget part")
        b.setToolTip("Stop updating the selected part from here (its links stay in the part until you unlink the columns)")
        b.clicked.connect(self.forget_part)
        row.addWidget(b)
        lay.addLayout(row)
        self.vars_status = QLabel("")
        self.vars_status.setWordWrap(True)
        lay.addWidget(self.vars_status)
        self.left.addTab(w, "Variables")
        self.left.setCurrentIndex(self.left.count() - 1)

    def refresh_vars(self):
        if self.var_table is None:
            return
        try:
            configs, vars_, values = ak.variables(self.doc)
        except Exception as ex:              # noqa: BLE001
            self.vars_status.setText(f"Could not read the variables: {ex}")
            return
        t = self.var_table
        t.setRowCount(len(vars_))
        t.setColumnCount(2 + len(configs))
        t.setHorizontalHeaderLabels(["Variable", "Kind"] + configs)
        for r, v in enumerate(vars_):
            t.setItem(r, 0, QTableWidgetItem(v["name"]))
            t.setItem(r, 1, QTableWidgetItem(v["kind"]))
            for j, c in enumerate(configs):
                x = values.get(c, {}).get(v["name"])
                t.setItem(r, 2 + j, QTableWidgetItem("" if x is None else f"{x:.6g}"))
        t.resizeColumnsToContents()
        self.part_list.clear()
        for p in self.parts:
            self.part_list.addItem(p + ("" if os.path.isfile(p) else "   (not found)"))
        self.vars_status.setText("" if vars_ else "No variables yet: make a symbol (Sketch > Parameters) or give a dimension a name; "
                                                  "an output symbol takes the number the geometry measures.")

    def update_all(self, fit=False, keep_props=False):
        super().update_all(fit, keep_props)
        if self.var_table is not None:
            self.refresh_vars()
            if self.push_timer is not None and self.parts:
                self.push_timer.start(350)

    # ------------------------------------------------------------------ driving the parts
    def add_part(self, path):
        path = os.path.normpath(os.path.abspath(path))
        if path not in self.parts:
            self.parts.append(path)
        self.refresh_vars()

    def forget_part(self):
        i = self.part_list.currentRow()
        if 0 <= i < len(self.parts):
            self.parts.pop(i)
            self.refresh_vars()

    def part_doc(self, path):
        sh = self.shell or self.window()
        return sh.part_doc(path) if hasattr(sh, "part_doc") else None

    def push_now(self, write_closed=False):
        if not self.path or not self.parts:
            if write_closed:
                self.vars_status.setText("Save the sketch first: parts find it by its file." if not self.path else "No parts linked yet.")
            return
        res = ak.push(self.path, self.doc, self.parts, self.part_doc, write_closed=write_closed)
        sh = self.shell or self.window()
        for p, state in res:
            if state == "open" and hasattr(sh, "find_tab"):
                i = sh.find_tab(p)
                w = sh.tabs.widget(i) if i is not None else None
                if w is not None and hasattr(w, "update_all"):
                    w.update_all(keep_props=True)
        if write_closed:
            n = {s: sum(1 for _p, x in res if x == s) for s in ("open", "written", "skipped", "missing")}
            bad = [f"{os.path.basename(p)}: {s}" for p, s in res if s.startswith("error")]
            self.vars_status.setText(f"{n['open']} open part(s) updated, {n['written']} file(s) written, {n['missing']} not found." + ("  " + "; ".join(bad) if bad else ""))


# ----------------------------------------------------------------------------------------------------------------- part side
def link_dialog(win):
    """Configurations tab of a part > Link to Assembly Sketch...: choose a sketch, then which variable drives which item of the part."""
    if not win.path:
        QMessageBox.information(win, "Link to assembly sketch", "Save the part first: the sketch finds the part by its file.")
        return
    dlg = _LinkDialog(win)
    if dlg.exec():
        dlg.apply()


class _LinkDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Link to Assembly Sketch")
        self.resize(680, 520)
        self.src = None
        self.sketch_doc = None
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Assembly sketch:"))
        self.combo = QComboBox()
        self.combo.setMinimumWidth(300)
        top.addWidget(self.combo, 1)
        b = QPushButton("Browse...")
        b.clicked.connect(self.browse)
        top.addWidget(b)
        lay.addLayout(top)
        self.open_tabs = self.find_open()
        for p, _d in self.open_tabs:
            self.combo.addItem(p + "   (open)", p)
        links = {ln["src"] for ln in win.doc.links}
        for s in sorted(links):
            ab = win.doc.link_src_path(next(ln for ln in win.doc.links if ln["src"] == s))
            if all(ab != p for p, _d in self.open_tabs):
                self.combo.addItem(ab, ab)
        self.combo.currentIndexChanged.connect(self.load_vars)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("filter the items of this part...")
        self.filter.textChanged.connect(self.apply_filter)
        lay.addWidget(self.filter)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Item of this part (a column of its Configurations table)", "Takes its number from the variable"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 340)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        lay.addWidget(self.table, 1)
        self.note = QLabel("")
        self.note.setWordWrap(True)
        lay.addWidget(self.note)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.cands = win.cfg_candidates()
        self.combos = {}
        self.load_vars()

    def find_open(self):
        sh = self.win.window()
        out = []
        tabs = getattr(sh, "tabs", None)
        if tabs is not None:
            for i in range(tabs.count()):
                w = tabs.widget(i)
                if getattr(w, "KIND", "") == "asmsketch" and getattr(w, "path", None):
                    out.append((os.path.normpath(os.path.abspath(w.path)), w))
        return out

    def browse(self):
        p, _ = QFileDialog.getOpenFileName(self, "Assembly sketch", "", "Assembly sketch (*.gpk)")
        if p:
            p = os.path.normpath(os.path.abspath(p))
            i = self.combo.findData(p)
            if i < 0:
                self.combo.addItem(p, p)
                i = self.combo.count() - 1
            self.combo.setCurrentIndex(i)

    def load_vars(self):
        self.src = self.combo.currentData()
        self.table.setRowCount(0)
        self.combos = {}
        if not self.src:
            self.note.setText("Open an assembly sketch (File > New Assembly Sketch, then save it) or browse to a .gpk file.")
            return
        live = next((w.doc for p, w in self.open_tabs if p == self.src), None)
        try:
            doc = live or ak.load(self.src)[0]
            self.vars = [v["name"] for v in ak.variables(doc)[1]]
        except Exception as ex:              # noqa: BLE001
            self.note.setText(f"Could not read that sketch: {ex}")
            return
        doc_links = {ln["target"]: ln for ln in self.win.doc.links if self.win.doc.link_src_path(ln) == self.src}
        self.table.setRowCount(len(self.cands))
        for r, (key, label, _val) in enumerate(self.cands):
            self.table.setItem(r, 0, QTableWidgetItem(label))
            cb = QComboBox()
            cb.addItem("(not linked)")
            cb.addItems(self.vars)
            if key in doc_links and doc_links[key]["var"] in self.vars:
                cb.setCurrentText(doc_links[key]["var"])
            self.table.setCellWidget(r, 1, cb)
            self.combos[key] = cb
        self.note.setText("Linked items get one number per sketch configuration (a part configuration of the same name is made when missing). "
                          "Everything you leave unlinked stays yours.")
        self.apply_filter()

    def apply_filter(self):
        t = self.filter.text().strip().lower()
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            cb = self.table.cellWidget(r, 1)
            linked = cb is not None and cb.currentIndex() > 0
            self.table.setRowHidden(r, bool(t) and t not in it.text().lower() and not linked)

    def apply(self):
        win = self.win
        if not self.src or not self.combos:
            return
        win.snapshot()
        base = os.path.dirname(os.path.abspath(win.path))
        src_rel = ak.rel(self.src, base)
        mine = {ln["target"] for ln in win.doc.links if win.doc.link_src_path(ln) == self.src}
        n = 0
        for key, cb in self.combos.items():
            if cb.currentIndex() > 0:
                win.doc.link_add(src_rel, cb.currentText(), key)
                n += 1
            elif key in mine:
                win.doc.link_remove(key)
        win.doc.base_dir = base
        # register this part with the sketch (open tab, or the file) so the sketch can find it
        live = next((w for p, w in self.open_tabs if p == self.src), None)
        if live is not None:
            live.add_part(win.path)
        else:
            try:
                sdoc, parts = ak.load(self.src)
                absp = [ak.absolute(x, os.path.dirname(self.src)) for x in parts]
                me = os.path.normpath(os.path.abspath(win.path))
                if me not in [os.path.normpath(x) for x in absp]:
                    ak.save(self.src, sdoc, [ak.rel(x, os.path.dirname(self.src)) for x in absp + [me]])
            except Exception as ex:          # noqa: BLE001
                win.say(f"Linked, but could not register the part in the sketch file: {ex}")
        changed, msgs = ak.refresh_part(win.doc, win.live_sketch_doc)
        win.doc.cfg_apply(win.doc.cfg["active"])
        win.update_all(keep_props=True)
        win.say(f"{n} column(s) linked to {os.path.basename(self.src)}. Save the part to keep the links." + ("  " + "; ".join(msgs) if msgs else ""))
