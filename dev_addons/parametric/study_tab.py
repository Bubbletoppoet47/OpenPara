"""
study_tab.py - the window of a parametric study: a tab bound to one simulation project (a SimWindow of the Simulation add-on).

Everything simulation-specific comes from the study adapter of the simulation (simulation/study_iface.py), so the same window serves 1D FEA,
2D FEA, 2D CFD and any simulation that offers an adapter.  Besides the adapter's inputs, the dimensions of the part copied into the project can
be varied (a study of the geometry) when the simulation works on a sketch of the part.

How a run goes: every case is PREPARED on the main thread (it builds the scratch tab of the case and reads the widgets), then the cases are
COMPUTED one after another on a worker thread, and each finished case is recorded on the main thread (outputs, early-exit conditions).
The live simulation tab is never changed by a run; a case is put on its screen only when you click its row.
"""
import itertools
import os
import threading
import traceback

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame,
                             QHBoxLayout, QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton, QScrollArea, QSplitter,
                             QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

import study_core as core


def _is_cancel(ex):
    return type(ex).__name__ == "StudyCancelled"


def run_one(spec, progress, cancel):
    """Computes one prepared case (any thread).  None when it was cancelled."""
    if spec.get("error"):
        return {"status": "failed", "error": spec["error"]}
    try:
        case = spec["run"](progress, cancel)
    except Exception as ex:
        if _is_cancel(ex):
            return None
        return {"status": "failed", "error": traceback.format_exc()}
    if cancel():
        return None
    if spec.get("state") is not None:
        case["state"] = spec["state"]
    return case


class CaseWorker(QThread):
    progress = pyqtSignal(str)
    case_done = pyqtSignal(int, object)
    all_done = pyqtSignal(bool)

    def __init__(self, specs):
        super().__init__()
        self.specs = specs
        self.stop = False
        self.halt = False                    # an early-exit condition was met: the rows below are skipped
        self.ack = threading.Event()

    def run(self):
        stopped = False
        n = len(self.specs)
        for i, spec in enumerate(self.specs):
            if self.stop:
                stopped = True
                break
            if self.halt:
                break
            self.ack.clear()
            head = f"Case {spec['label']} ({i + 1} of {n}): "
            case = run_one(spec, lambda t, head=head: self.progress.emit(head + str(t)), lambda: self.stop)
            if case is None:
                stopped = True
                break
            self.case_done.emit(i, case)
            while not self.ack.wait(0.1):
                if self.stop:
                    break
        self.all_done.emit(stopped)


class StudyTab(QWidget):
    def __init__(self, sw, threaded=True):
        super().__init__()
        self.sw = sw                          # the SimWindow this study belongs to
        self.threaded = threaded
        self.path_ = sw.path                  # (not .path: the shell finds the simulation's tab by that name)
        self.data = core.StudyData.load(sw.path) if core.exists(sw.path) else core.StudyData()
        self.desc = {}
        self.checked_items = {}
        self.adapter = None
        self.worker = None
        self.specs = []
        self.ctx = {}
        self.geo_cache = {}
        self.own_state = None
        self.dirty = not core.exists(sw.path)
        self.building = False

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(6, 6, 6, 6)
        self.head = QLabel()
        self.head.setWordWrap(True)
        ll.addWidget(self.head)
        ll.addWidget(self.note("Tick the inputs that should change from case to case. Each ticked input becomes a column of the design-point "
                               "table; every row of the table is one case."))
        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["Input", "Now"])
        self.tree.setMinimumHeight(240)
        self.tree.header().resizeSection(0, 250)
        self.tree.itemChanged.connect(self.param_toggled)
        ll.addWidget(self.tree, 2)
        b = QPushButton("Refresh the list from the simulation")
        b.clicked.connect(lambda: self.refresh_params())
        ll.addWidget(b)

        ll.addWidget(QLabel("<b>Outputs to record</b>"))
        self.out_tree = QTreeWidget()
        self.out_tree.setColumnCount(1)
        self.out_tree.setHeaderHidden(True)
        self.out_tree.setMinimumHeight(160)
        self.out_tree.itemChanged.connect(self.output_toggled)
        ll.addWidget(self.out_tree, 1)

        ll.addWidget(QLabel("<b>Stop early when...</b>"))
        ll.addWidget(self.note("Checked after every case, in table order. The case that meets a condition is kept (and marked); every row below "
                               "it is skipped. Put the heavier cases last."))
        self.exit_table = QTableWidget(0, 4)
        self.exit_table.setHorizontalHeaderLabels(["On", "Output", "", "Value"])
        self.exit_table.verticalHeader().hide()
        self.exit_table.setMinimumHeight(100)
        self.exit_table.setMaximumHeight(160)
        self.exit_table.horizontalHeader().setStretchLastSection(True)
        ll.addWidget(self.exit_table)
        row = QHBoxLayout()
        self.b_addx = QPushButton("Add condition")
        self.b_addx.clicked.connect(self.add_exit)
        row.addWidget(self.b_addx)
        b = QPushButton("Remove selected")
        b.clicked.connect(self.del_exit)
        row.addWidget(b)
        ll.addLayout(row)

        ll.addWidget(QLabel("<b>Run</b>"))
        row = QHBoxLayout()
        self.b_all = QPushButton("Run all rows")
        self.b_all.clicked.connect(self.run_all)
        self.b_sel = QPushButton("Run selected row")
        self.b_sel.clicked.connect(self.run_selected)
        row.addWidget(self.b_all)
        row.addWidget(self.b_sel)
        ll.addLayout(row)
        self.b_cur = QPushButton("Run current setup (one case, nothing changed)")
        self.b_cur.clicked.connect(self.run_current)
        ll.addWidget(self.b_cur)
        self.b_stop = QPushButton("Stop")
        self.b_stop.setEnabled(False)
        self.b_stop.clicked.connect(self.stop_run)
        ll.addWidget(self.b_stop)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        ll.addWidget(self.bar)
        self.prog = self.note("")
        ll.addWidget(self.prog)
        ll.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(left)
        scroll.setMinimumWidth(380)
        scroll.setMaximumWidth(480)

        right = QSplitter(Qt.Orientation.Vertical)
        top = QWidget()
        tl = QVBoxLayout(top)
        tl.setContentsMargins(6, 6, 6, 0)
        tl.addWidget(QLabel("<b>Design points</b> (one row = one case; double-click a cell to edit)"))
        self.design = QTableWidget(0, 0)
        self.design.itemChanged.connect(self.design_edited)
        self.design.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        tl.addWidget(self.design, 1)
        row = QHBoxLayout()
        for text, fn in (("Add row", self.add_row), ("Duplicate row", self.dup_row), ("Delete row", self.del_row),
                         ("Fill grid...", self.fill_grid)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        tl.addLayout(row)
        bottom = QWidget()
        bl_ = QVBoxLayout(bottom)
        bl_.setContentsMargins(6, 6, 6, 6)
        bl_.addWidget(QLabel("<b>Results</b> (click a row to put that case on the screen of the simulation)"))
        self.res_table = QTableWidget(0, 0)
        self.res_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.res_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.res_table.cellClicked.connect(lambda r, c: self.show_case(r))
        bl_.addWidget(self.res_table, 1)
        self.case_lbl = self.note("")
        bl_.addWidget(self.case_lbl)
        row = QHBoxLayout()
        self.b_back = QPushButton("Back to my own inputs")
        self.b_back.setToolTip("Puts the simulation back the way it was before a case was shown.")
        self.b_back.clicked.connect(self.back_to_own)
        row.addWidget(self.b_back)
        b = QPushButton("Export table (CSV)...")
        b.clicked.connect(self.export_csv)
        row.addWidget(b)
        self.b_clear = QPushButton("Clear results")
        self.b_clear.clicked.connect(self.clear_results)
        row.addWidget(self.b_clear)
        row.addStretch(1)
        bl_.addLayout(row)
        right.addWidget(top)
        right.addWidget(bottom)
        right.setStretchFactor(0, 1)
        right.setStretchFactor(1, 1)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        split.addWidget(scroll)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(split, 1)

        self.refresh_params()
        self.fill_exit_table()
        self.rebuild_design()
        self.rebuild_results()
        if self.data.cases:
            self.case_lbl.setText("Results of the last run, loaded from the project. Click a row to show it.")

    # ------------------------------------------------------------------ small helpers
    @staticmethod
    def note(text):
        lb = QLabel(text)
        lb.setWordWrap(True)
        lb.setStyleSheet("color:#606060;")
        return lb

    def title(self):
        return "Study - " + os.path.basename(str(self.path_).rstrip("/\\"))

    def is_dirty(self):
        return self.dirty

    def mark(self):
        self.dirty = True

    def tab(self):
        return self.sw.tab

    def running(self):
        return self.worker is not None

    # ------------------------------------------------------------------ the inputs
    def geo_params(self):
        """The dimensions of the part copied into the project (only for a simulation of a sketch of a part)."""
        src = getattr(self.sw, "source", None)
        sid = self.sw.meta.get("sid") if isinstance(getattr(self.sw, "meta", None), dict) else None
        solid = getattr(self.sw, "study_geometry", False)                        # a 3D part simulation: the whole part is its geometry
        if src is None or getattr(src, "type", "") != "part" or (not solid and (not sid or str(sid).startswith("__"))):
            return []
        out = []
        try:
            cands = src.doc.cfg_candidates()
        except Exception:
            return []
        for key, label, now in cands:
            is_bool = key.startswith("s:")
            out.append({"id": core.GEO + key, "group": "Part dimensions (changes the geometry)", "label": "Part: " + label,
                        "kind": "bool" if is_bool else "text", "choices": None,
                        "now": ("yes" if now else "no") if is_bool else str(now), "geo": key})
        return out

    def refresh_params(self):
        self.building = True
        try:
            self.adapter = self.tab().study_adapter()
            plist = list(self.adapter.params()) + self.geo_params()
            self.desc = {d["id"]: d for d in plist}
            self.outs = list(self.adapter.outputs())
            ready = self.adapter.ready()
            pname = os.path.basename(str(self.path_).rstrip("/\\"))
            self.head.setText(f"<b>{self.adapter.label}</b> study of the project <b>{pname}</b>"
                              + (f"<br><span style='color:#a05000'>{ready}</span>" if ready else ""))
            self.tree.blockSignals(True)
            self.tree.clear()
            groups = {}
            self.items = {}
            for d in plist:
                g = groups.get(d["group"])
                if g is None:
                    g = QTreeWidgetItem(self.tree, [d["group"]])
                    g.setFlags(g.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                    f = g.font(0)
                    f.setBold(True)
                    g.setFont(0, f)
                    groups[d["group"]] = g
                it = QTreeWidgetItem(g, [d["label"], str(d["now"])])
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                it.setCheckState(0, Qt.CheckState.Checked if d["id"] in self.data.checked else Qt.CheckState.Unchecked)
                it.setData(0, Qt.ItemDataRole.UserRole, d["id"])
                self.items[d["id"]] = it
            for g in groups.values():
                g.setExpanded(any(g.child(i).checkState(0) == Qt.CheckState.Checked for i in range(g.childCount())) or g.text(0).endswith("inputs"))
            self.tree.blockSignals(False)
            self.fill_outputs()
        finally:
            self.building = False
        self.rebuild_design()
        self.fill_exit_table()

    def param_toggled(self, item, col):
        if self.building or col != 0:
            return
        pid = item.data(0, Qt.ItemDataRole.UserRole)
        if pid is None:
            return
        on = item.checkState(0) == Qt.CheckState.Checked
        if on and pid not in self.data.checked:
            self.data.checked.append(pid)
            for r in self.data.rows:
                r.setdefault(pid, self.now(pid))
        elif not on and pid in self.data.checked:
            self.data.checked.remove(pid)
        self.mark()
        self.rebuild_design()

    def now(self, pid):
        d = self.desc.get(pid)
        return str(d["now"]) if d else ""

    def cols(self):
        return [p for p in self.data.checked if p in self.desc]

    # ------------------------------------------------------------------ outputs and early exit
    def fill_outputs(self):
        defaults = [o["id"] for o in self.outs if not o["numeric"]][:1] + [o["id"] for o in self.outs if o["numeric"]][:4]
        if not self.data.out_checked:
            self.data.out_checked = defaults
        self.out_tree.blockSignals(True)
        self.out_tree.clear()
        groups = {}
        for o in self.outs:
            g = groups.get(o["group"])
            if g is None:
                g = QTreeWidgetItem(self.out_tree, [o["group"]])
                g.setFlags(g.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                g.setExpanded(True)
                groups[o["group"]] = g
            it = QTreeWidgetItem(g, [o["label"]])
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(0, Qt.CheckState.Checked if o["id"] in self.data.out_checked else Qt.CheckState.Unchecked)
            it.setData(0, Qt.ItemDataRole.UserRole, o["id"])
        self.out_tree.blockSignals(False)

    def output_toggled(self, item, col):
        oid = item.data(0, Qt.ItemDataRole.UserRole)
        if oid is None:
            return
        if item.checkState(0) == Qt.CheckState.Checked:
            if oid not in self.data.out_checked:
                self.data.out_checked.append(oid)
        elif oid in self.data.out_checked:
            self.data.out_checked.remove(oid)
        self.mark()

    def numeric_outputs(self):
        return [(o["id"], o["label"]) for o in self.outs if o["numeric"]]

    def add_exit(self):
        outs = self.numeric_outputs()
        if not outs:
            QMessageBox.information(self, "Stop early", "This simulation has no numeric outputs to test.")
            return
        key = next((k for k, _ in outs if "fos" in k), outs[0][0])
        self.data.exit_conds.append({"on": True, "key": key, "op": "<" if "fos" in key else ">", "value": "1" if "fos" in key else "0"})
        self.mark()
        self.fill_exit_table()

    def del_exit(self):
        r = self.exit_table.currentRow()
        if 0 <= r < len(self.data.exit_conds):
            del self.data.exit_conds[r]
            self.mark()
            self.fill_exit_table()

    def fill_exit_table(self):
        t = self.exit_table
        t.blockSignals(True)
        outs = self.numeric_outputs()
        conds = self.data.exit_conds
        t.setRowCount(len(conds))

        def setk(r, k, v):
            conds[r][k] = v
            self.mark()
        for r, c in enumerate(conds):
            cb = QCheckBox()
            cb.setChecked(bool(c.get("on", True)))
            cb.toggled.connect(lambda on, r=r: setk(r, "on", bool(on)))
            t.setCellWidget(r, 0, cb)
            ck = QComboBox()
            for k, lab in outs:
                ck.addItem(lab, k)
            if not any(k == c["key"] for k, _ in outs):
                ck.addItem(c["key"], c["key"])
            ck.setCurrentIndex(max(0, ck.findData(c["key"])))
            ck.currentIndexChanged.connect(lambda _i, r=r, ck=ck: setk(r, "key", ck.currentData()))
            t.setCellWidget(r, 1, ck)
            co = QComboBox()
            co.addItems(core.OPS)
            co.setCurrentText(c.get("op", ">"))
            co.currentTextChanged.connect(lambda tx, r=r: setk(r, "op", tx))
            t.setCellWidget(r, 2, co)
            t.setItem(r, 3, QTableWidgetItem(str(c.get("value", ""))))
        t.resizeColumnsToContents()
        t.setColumnWidth(1, 200)
        t.blockSignals(False)
        try:
            t.itemChanged.disconnect()
        except TypeError:
            pass
        t.itemChanged.connect(lambda it: it.column() == 3 and it.row() < len(conds) and setk(it.row(), "value", it.text().strip()))

    # ------------------------------------------------------------------ the design-point table
    def rebuild_design(self):
        self.design.blockSignals(True)
        cols = self.cols()
        self.design.setColumnCount(len(cols))
        self.design.setHorizontalHeaderLabels([self.desc[p]["label"] for p in cols])
        self.design.setRowCount(len(self.data.rows))
        self.design.setVerticalHeaderLabels([str(i + 1) for i in range(len(self.data.rows))])
        for r, row in enumerate(self.data.rows):
            for c, p in enumerate(cols):
                self.design.setItem(r, c, QTableWidgetItem(str(row.get(p, ""))))
        self.design.resizeColumnsToContents()
        self.design.blockSignals(False)

    def design_edited(self, item):
        cols = self.cols()
        if item.row() < len(self.data.rows) and item.column() < len(cols):
            self.data.rows[item.row()][cols[item.column()]] = item.text().strip()
            self.mark()

    def fresh_row(self):
        return {p: self.now(p) for p in self.cols()}

    def add_row(self):
        self.data.rows.append(dict(self.data.rows[-1]) if self.data.rows else self.fresh_row())
        self.mark()
        self.rebuild_design()

    def dup_row(self):
        r = self.design.currentRow()
        if 0 <= r < len(self.data.rows):
            self.data.rows.insert(r + 1, dict(self.data.rows[r]))
            self.mark()
            self.rebuild_design()

    def del_row(self):
        r = self.design.currentRow()
        if 0 <= r < len(self.data.rows) and len(self.data.rows) > 1:
            del self.data.rows[r]
            self.mark()
            self.rebuild_design()

    def fill_grid(self, lists_text=None):
        """The table becomes every combination of the values typed for each ticked input.  `lists_text` ({id: 'a, b, c'}) skips the dialog."""
        cols = self.cols()
        if not cols:
            QMessageBox.information(self, "Fill grid", "Tick at least one input on the left first.")
            return False
        if lists_text is None:
            dlg = QDialog(self)
            dlg.setWindowTitle("Fill grid")
            dlg.setMinimumWidth(520)
            lay = QVBoxLayout(dlg)
            lay.addWidget(self.note("Type the values to try for each input, separated by commas (for example 10, 15, 20, 25). The table is "
                                    "replaced by every combination of them."))
            form = QFormLayout()
            edits = {}
            for p in cols:
                e = QLineEdit(str(self.data.rows[0].get(p, "")) if self.data.rows else "")
                form.addRow(self.desc[p]["label"], e)
                edits[p] = e
            lay.addLayout(form)
            bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
            bb.accepted.connect(dlg.accept)
            bb.rejected.connect(dlg.reject)
            lay.addWidget(bb)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return False
            lists_text = {p: e.text() for p, e in edits.items()}
        lists = []
        for p in cols:
            vals = core.split_list(lists_text.get(p, ""))
            if not vals:
                QMessageBox.warning(self, "Fill grid", f"'{self.desc[p]['label']}' has no values.")
                return False
            lists.append(vals)
        try:
            rows = core.grid_rows(cols, lists)
        except ValueError as ex:
            QMessageBox.warning(self, "Fill grid", str(ex))
            return False
        if len(rows) > 30 and QMessageBox.question(self, "Fill grid", f"That makes {len(rows)} cases. Continue?") != QMessageBox.StandardButton.Yes:
            return False
        self.data.rows = rows
        self.mark()
        self.rebuild_design()
        return True

    # ------------------------------------------------------------------ running
    def run_all(self):
        return self.start([(str(i + 1), dict(r)) for i, r in enumerate(self.data.rows)], True)

    def run_selected(self):
        r = self.design.currentRow()
        if not (0 <= r < len(self.data.rows)):
            QMessageBox.information(self, "Run", "Click a row of the design-point table first.")
            return False
        return self.start([(str(r + 1), dict(self.data.rows[r]))], True)

    def run_current(self):
        return self.start([("current", {})], False)

    def geo_state(self, geo):
        """The saved state of the simulation tab with the sketch of the part after changing its dimensions (cached per set of values)."""
        key = tuple(sorted(geo.items()))
        if key in self.geo_cache:
            return self.geo_cache[key]
        import sim_project
        import sim_source
        sid = self.sw.meta.get("sid")
        src = sim_source.open_source(sim_project.source_file(self.sw.path))
        vals = {}
        for pid, v in geo.items():
            d = self.desc.get(pid)
            k = d["geo"] if d else pid[len(core.GEO):]
            if k.startswith("s:"):
                from study_iface import parse_bool
                v = parse_bool(v)
            vals[k] = v
        if hasattr(self.adapter, "geometry_state"):                       # the simulation turns the changed part into its own state
            st = self.adapter.geometry_state(src, vals)
            self.geo_cache[key] = st
            return st
        src.set_values(vals)
        m = src.doc.models.get(sid)
        if m is None:
            raise ValueError("The sketch of the simulation is not in the part any more.")
        st = self.adapter.base_state()
        if "model_json" not in st:
            raise ValueError("This simulation cannot take a changed sketch.")
        st["model_json"] = m.to_json()
        self.geo_cache[key] = st
        return st

    def prepare_all(self, jobs, use_params):
        """Builds a spec for each job on the main thread: {label, values, run, error, state}."""
        pids = self.cols() if use_params else []
        specs = []
        for label, vals in jobs:
            vals = {p: vals[p] for p in pids if p in vals}
            geo = {p: v for p, v in vals.items() if p.startswith(core.GEO)}
            plain = {p: v for p, v in vals.items() if p not in geo}
            spec = {"label": label, "values": dict(vals), "run": None, "error": None, "state": None}
            try:
                st = self.geo_state(geo) if geo else None
                sp = self.adapter.prepare(plain, self.ctx, st)
                spec["run"], spec["error"], spec["state"] = sp.get("run"), sp.get("error"), st
            except Exception as ex:
                spec["error"] = str(ex) if isinstance(ex, ValueError) else traceback.format_exc()
            specs.append(spec)
        return specs, pids

    def start(self, jobs, use_params):
        if self.running():
            return False
        self.refresh_params()
        why = self.adapter.ready()
        if why:
            QMessageBox.information(self, "Run", why)
            return False
        if len(jobs) > 12 and QMessageBox.question(self, "Run", f"{len(jobs)} cases will run one after another and may take a long time. Continue?"
                                                   ) != QMessageBox.StandardButton.Yes:
            return False
        self.ctx = {}
        self.geo_cache = {}
        if self.own_state is not None:
            self.back_to_own()
        specs, pids = self.prepare_all(jobs, use_params)
        outs = {o["id"]: o["label"] for o in self.outs}
        unit = getattr(self.tab(), "unit_name", None)
        self.data.clear_cases()
        self.data.run_meta = {"params": [(p, self.desc[p]["label"]) for p in pids],
                              "outputs": [(k, outs[k]) for k in self.data.out_checked if k in outs],
                              "unit": unit() if callable(unit) else None}
        self.specs = specs
        self.mark()
        self.rebuild_results()
        self.bar.setValue(0)
        self.set_busy(True)
        if self.threaded:
            self.worker = CaseWorker(specs)
            self.worker.progress.connect(lambda t: self.prog.setText(t))
            self.worker.case_done.connect(self.on_case_done)
            self.worker.all_done.connect(self.on_all_done)
            self.worker.start()
        else:                                           # no thread (tests): the same steps, in order
            self.worker = CaseWorker(specs)
            stopped = False
            for i, spec in enumerate(specs):
                if self.worker.halt:
                    break
                case = run_one(spec, lambda t: None, lambda: self.worker.stop)
                if case is None:
                    stopped = True
                    break
                self.on_case_done(i, case)
            self.on_all_done(stopped)
        return True

    def set_busy(self, on):
        for w in (self.b_all, self.b_sel, self.b_cur):
            w.setEnabled(not on)
        self.b_stop.setEnabled(on)
        self.tab().setEnabled(not on)                  # nothing else may use the mesher or the solvers during a batch

    def stop_run(self):
        if self.worker is not None:
            self.worker.stop = True
            self.b_stop.setEnabled(False)
            self.prog.setText("Stopping after the current step...")

    def on_case_done(self, i, case):
        spec = self.specs[i]
        keys = [k for k, _ in self.data.run_meta["outputs"]]
        want = sorted(set(keys) | set(core.exit_keys(self.data.exit_conds)))
        try:
            outs = self.adapter.case_outputs(case, want)
        except Exception:
            outs = {}
        summary = {"label": spec["label"], "values": dict(spec["values"]), "status": case.get("status", "failed"),
                   "outputs": {k: outs.get(k) for k in keys}, "error": case.get("error"), "early_exit": None, "early_skipped": False,
                   "notes": [], "file": None}
        try:
            hit = core.check_exit(self.data.exit_conds, outs)
        except Exception:
            hit = None
        if hit and self.worker is not None:
            summary["early_exit"] = hit
            self.worker.halt = True
        self.data.add_case(summary, case if case.get("status") != "failed" or case.get("result") is not None else None)
        self.bar.setValue(int(1000 * (i + 1) / max(1, len(self.specs))))
        self.rebuild_results()
        if self.worker is not None:
            self.worker.ack.set()

    def on_all_done(self, stopped):
        w = self.worker
        self.worker = None
        if w is not None and self.threaded:
            w.wait()
        self.set_busy(False)
        n = len(self.data.cases)
        if w is not None and w.halt and not stopped:
            first = next((c for c in self.data.cases if c.get("early_exit")), None)
            for spec in self.specs[n:]:
                self.data.add_case({"label": spec["label"], "values": dict(spec["values"]), "status": "skipped", "outputs": {}, "error": None,
                                    "early_exit": None, "early_skipped": True, "file": None,
                                    "notes": [f"Skipped: early exit after case {first['label'] if first else '?'} ({first['early_exit'] if first else ''})."]}, None)
            self.prog.setText(f"Stopped early: {first['early_exit'] if first else 'an early-exit condition'}.")
        elif stopped:
            self.prog.setText("Stopped. The cases done so far are kept.")
        else:
            self.prog.setText(f"Done: {n} case(s).")
        self.bar.setValue(1000 if not stopped else self.bar.value())
        self.rebuild_results()
        self.mark()
        try:
            self.save()
        except Exception:
            pass
        self.sw.refresh_study_button() if hasattr(self.sw, "refresh_study_button") else None

    # ------------------------------------------------------------------ results
    def rebuild_results(self):
        heads, rows = self.data.table()
        t = self.res_table
        t.setColumnCount(len(heads))
        t.setHorizontalHeaderLabels(heads)
        t.setRowCount(len(rows))
        for r, (c, cells) in enumerate(zip(self.data.cases, rows)):
            sev = self.data.severity(c)
            for col, txt in enumerate(cells):
                it = QTableWidgetItem(txt)
                if sev == "bad":
                    it.setBackground(QColor("#fde0e0"))
                elif sev == "warn":
                    it.setBackground(QColor("#fff3d6"))
                t.setItem(r, col, it)
        t.resizeColumnsToContents()

    def show_case(self, r):
        if not (0 <= r < len(self.data.cases)) or self.running():
            return False
        c = self.data.cases[r]
        case = self.data.case(r)
        if case is None or case.get("result") is None:
            why = c.get("error") or "; ".join(c.get("notes") or []) or "This case has no result to show."
            self.case_lbl.setText("Case " + str(c["label"]) + ": " + str(why).strip().splitlines()[-1])
            return False
        if self.own_state is None:
            self.own_state = self.tab().export_state()
        try:
            self.adapter = self.tab().study_adapter()
            self.sw.host._restoring = True
            try:
                self.adapter.show(case)
            finally:
                self.sw.host._restoring = False
        except Exception as ex:
            self.case_lbl.setText(f"Could not show the case: {ex}")
            return False
        sh = getattr(self.sw, "shell", None)
        if sh is not None:
            sh.tabs.setCurrentWidget(self.sw)
        vals = ", ".join(f"{lab} = {c['values'].get(p, '')}" for p, lab in self.data.run_meta["params"]) or "the current setup"
        self.case_lbl.setText(f"Case {c['label']} ({vals}) is now shown in the simulation tab. 'Back to my own inputs' restores your setup.")
        return True

    def back_to_own(self):
        if self.own_state is None or self.running():
            return
        self.sw.host._restoring = True
        try:
            self.tab().import_state(self.own_state)
        finally:
            self.sw.host._restoring = False
        self.own_state = None
        self.case_lbl.setText("The simulation tab is back to what it was before a case was shown.")

    def clear_results(self):
        if self.running():
            return
        if self.data.cases and QMessageBox.question(self, "Clear results", "Delete the results of this study (the table of inputs stays)?"
                                                    ) != QMessageBox.StandardButton.Yes:
            return
        self.data.clear_cases()
        self.mark()
        self.rebuild_results()

    def export_csv(self, path=None):
        if not self.data.cases:
            QMessageBox.information(self, "Export", "No results yet.")
            return False
        if path is None:
            path, _ = QFileDialog.getSaveFileName(self, "Export results", "parameter_results.csv", "CSV (*.csv)")
        if not path:
            return False
        self.data.write_csv(path)
        return True

    # ------------------------------------------------------------------ save
    def save(self, as_new=False):
        if not self.sw.path:
            return False
        self.data.save(self.sw.path)
        self.dirty = False
        return True

    def closeEvent(self, ev):
        if self.worker is not None:
            self.worker.stop = True
            self.worker.ack.set()
            self.worker.wait(3000)
        super().closeEvent(ev)
