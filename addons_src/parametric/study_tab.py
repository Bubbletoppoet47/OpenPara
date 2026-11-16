"""
study_tab.py - the window of a parametric study: a tab bound to one simulation project (a SimWindow of the Simulation add-on).

Everything simulation-specific comes from the study adapter of the simulation (simulation/study_iface.py), so the same window serves 1D FEA,
2D FEA, 2D CFD and any simulation that offers an adapter.  Besides the adapter's inputs, the dimensions of the part copied into the project can
be varied (a study of the geometry) when the simulation works on a sketch of the part.

How a run goes: each case is PREPARED on the main thread, one at a time, in small slices between window events (it builds the scratch tab of
the case and reads the widgets), while the cases are COMPUTED one after another on a worker thread; each finished case is recorded on the main
thread (outputs, early-exit conditions).  Nothing is done for all cases at once, so the window never freezes, however many cases there are.
The live simulation tab is never changed by a run; a case is put on its screen only when you click its row.
"""
import itertools
import os
import queue as _queue
import threading
import traceback

import math

from PyQt6.QtCore import QPointF, QRectF, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QHeaderView,
                             QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea,
                             QSpinBox, QSplitter, QTabWidget, QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

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
    """Solves the prepared cases one after another.  The cases are prepared on the main thread (one slice at a time, see StudyTab.prep_tick) and
    arrive through `queue`; the worker never waits for the window, so a long study cannot freeze it."""
    progress = pyqtSignal(str)
    case_done = pyqtSignal(int, object)
    all_done = pyqtSignal(bool)

    def __init__(self, n, labels=None):
        super().__init__()
        self.n = n
        self.queue = _queue.Queue()
        self.stop = False
        self.halt = False                    # an early-exit condition was met: the rows below are skipped

    def run(self):
        stopped = False
        for i in range(self.n):
            spec = None
            while spec is None:
                if self.stop:
                    break
                try:
                    spec = self.queue.get(timeout=0.1)
                except _queue.Empty:
                    pass
            if self.stop:
                stopped = True
                break
            if self.halt:
                break
            head = f"Case {spec['label']} ({i + 1} of {self.n}): "
            case = run_one(spec, lambda t, head=head: self.progress.emit(head + str(t)), lambda: self.stop)
            if case is None:
                stopped = True
                break
            self.case_done.emit(i, case)
        self.all_done.emit(stopped)


class ConvergencePlot(QWidget):
    """One output against the number of elements (log scale): the values, the estimated limit (dashed) and the level that is good enough (ring)."""

    def __init__(self):
        super().__init__()
        self.setMinimumSize(280, 190)
        self.xs, self.ys, self.limit, self.pick, self.title = [], [], None, None, ""

    def set_data(self, xs, ys, limit=None, pick=None, title=""):
        self.xs, self.ys, self.limit, self.pick, self.title = list(xs), list(ys), limit, pick, title
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        try:
            self.draw(p)
        except Exception:                      # noqa: BLE001 - an error escaping a paint event would close the whole program
            pass
        finally:
            p.end()

    def draw(self, p):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor("#ffffff"))
        f = QFont("Segoe UI")
        f.setPixelSize(11)
        p.setFont(f)
        r = QRectF(64, 22, w - 80, h - 54)
        if r.width() < 40 or r.height() < 40:
            return
        if len(self.xs) < 2:
            p.setPen(QColor("#7a8696"))
            p.drawText(QRectF(0, 0, w, h), Qt.AlignmentFlag.AlignCenter, "Run the study to see the convergence.")
            return
        lx = [math.log10(x) for x in self.xs]
        x0, x1 = min(lx), max(lx)
        if x1 - x0 < 1e-9:
            x0, x1 = x0 - 0.5, x1 + 0.5
        vals = list(self.ys) + ([self.limit] if self.limit is not None else [])
        lo, hi = min(vals), max(vals)
        if hi - lo < 1e-12 * max(1.0, abs(hi)):
            lo, hi = lo - 1.0, hi + 1.0
        pad = 0.08 * (hi - lo)
        lo, hi = lo - pad, hi + pad

        def X(v):
            return r.left() + (math.log10(v) - x0) / (x1 - x0) * r.width()

        def Y(v):
            return r.bottom() - (v - lo) / (hi - lo) * r.height()
        p.setPen(QPen(QColor("#9aa6b8"), 1))
        p.drawRect(r)
        p.setPen(QColor("#4a5668"))
        for i in range(5):
            v = lo + (hi - lo) * i / 4
            p.drawText(QRectF(0, Y(v) - 7, r.left() - 5, 14), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, format(v, ".4g"))
            p.setPen(QPen(QColor("#e6eaf0"), 1))
            p.drawLine(QPointF(r.left(), Y(v)), QPointF(r.right(), Y(v)))
            p.setPen(QColor("#4a5668"))
        for x in self.xs:
            p.drawText(QRectF(X(x) - 32, r.bottom() + 3, 64, 14), Qt.AlignmentFlag.AlignCenter, format(x, ".4g"))
        p.drawText(QRectF(r.left(), h - 16, r.width(), 14), Qt.AlignmentFlag.AlignCenter, "number of elements (log scale)")
        p.drawText(QRectF(r.left(), 2, r.width(), 16), Qt.AlignmentFlag.AlignLeft, self.title)
        if self.limit is not None:
            p.setPen(QPen(QColor("#e76f51"), 1, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(r.left(), Y(self.limit)), QPointF(r.right(), Y(self.limit)))
            p.drawText(QRectF(r.right() - 190, Y(self.limit) - 16, 186, 14), Qt.AlignmentFlag.AlignRight, "estimated limit " + format(self.limit, ".5g"))
        p.setPen(QPen(QColor("#1f77b4"), 2))
        pts = [QPointF(X(x), Y(y)) for x, y in zip(self.xs, self.ys)]
        for a, b in zip(pts, pts[1:]):
            p.drawLine(a, b)
        p.setBrush(QColor("#1f77b4"))
        for q in pts:
            p.drawEllipse(q, 3.5, 3.5)
        if self.pick is not None and 0 <= self.pick < len(pts):
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor("#2a9d4a"), 2))
            p.drawEllipse(pts[self.pick], 9, 9)


class ConvergencePanel(QWidget):
    """The Convergence tab of a refinement study: a plot of one output, the table of levels, the verdicts and the 'use this size' button."""

    def __init__(self, use_cb):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        row = QHBoxLayout()
        row.addWidget(QLabel("Output:"))
        self.pickbox = QComboBox()
        self.pickbox.activated.connect(lambda _i: self.show_output())
        row.addWidget(self.pickbox, 1)
        lay.addLayout(row)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.plot = ConvergencePlot()
        self.table = QTableWidget(0, 0)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        split.addWidget(self.plot)
        split.addWidget(self.table)
        split.setSizes([360, 420])
        lay.addWidget(split, 1)
        self.verdicts = QPlainTextEdit()
        self.verdicts.setReadOnly(True)
        self.verdicts.setMaximumHeight(110)
        lay.addWidget(self.verdicts)
        row = QHBoxLayout()
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("font-weight:bold;")
        row.addWidget(self.summary, 1)
        self.use = QPushButton("Use this element size in the simulation")
        self.use.setToolTip("Puts the recommended element size into the simulation on screen. Then make a new study for the real analysis.")
        self.use.clicked.connect(lambda _c=False: use_cb())
        row.addWidget(self.use)
        lay.addLayout(row)
        self.res = None
        self.labels = {}
        self.set_result(None, {})

    def set_result(self, res, labels, sizes_text=""):
        self.res, self.labels = res, labels
        self.pickbox.clear()
        self.table.clear()
        self.table.setRowCount(0)
        self.table.setColumnCount(0)
        self.use.setEnabled(False)
        if not res or not res["levels"]:
            self.plot.set_data([], [])
            self.verdicts.setPlainText("")
            self.summary.setText("No results yet. Run the study: every level is one solve with a finer mesh.")
            return
        for k, info in res["outputs"].items():
            self.pickbox.addItem(labels.get(k, k), k)
        lines = []
        for k, info in res["outputs"].items():
            lines.append(f"{labels.get(k, k)}: {info['verdict']} ({info['text']})")
        for k in res["notes"]:
            lines.append(f"Note on {labels.get(k, k)}: if this is a stress at a point load, a sharp corner or a fixed edge, it never converges (the exact "
                         "value there is infinite). Read the stress away from that spot, or use a probe average.")
        if res.get("pending"):
            lines.append("Still changing: add finer levels (a smaller factor or more levels) before choosing a size.")
        self.verdicts.setPlainText("\n".join(lines))
        rec = res["recommend"]
        if rec is not None:
            lv = res["levels"][rec]
            self.summary.setText(f"Good enough: level {lv['label']} ({sizes_text or 'size ' + format(lv['h'], '.4g')}, {lv['n']:.0f} elements): every output "
                                 f"changes by less than {res['tol']:g}% from here on.")
            self.use.setEnabled(True)
        elif res.get("pending"):
            self.summary.setText("Not converged yet: the finest levels still change the results by more than %g%%." % res["tol"])
        else:
            self.summary.setText("No size recommended: " + ("some outputs do not settle." if res["notes"] else "too few levels."))
        self.show_output()

    def show_output(self):
        res = self.res
        if not res or self.pickbox.count() == 0:
            return
        k = self.pickbox.currentData() or self.pickbox.itemData(0)
        info = res["outputs"].get(k)
        if info is None:
            return
        lv = res["levels"]
        self.plot.set_data([lv[i]["n"] for i in info["idx"]], info["values"], info["limit"],
                           info["idx"].index(res["recommend"]) if res["recommend"] in info["idx"] else None, self.labels.get(k, k))
        heads = ["Level", "Element size", "Elements", self.labels.get(k, k), "Change from previous (%)"]
        self.table.setColumnCount(len(heads))
        self.table.setHorizontalHeaderLabels(heads)
        self.table.setRowCount(len(info["idx"]))
        for r_, (i, v, pc) in enumerate(zip(info["idx"], info["values"], info["pct"])):
            cells = [str(lv[i]["label"]), format(lv[i]["h"], ".4g") if lv[i].get("h") else "", format(lv[i]["n"], ".0f"), format(v, ".6g"),
                     "" if pc is None else format(pc, "+.3g")]
            for c_, txt in enumerate(cells):
                it = QTableWidgetItem(txt)
                if res["recommend"] == i:
                    it.setBackground(QColor("#d6f0dc"))
                self.table.setItem(r_, c_, it)
        self.table.resizeColumnsToContents()


class RefineDialog(QDialog):
    """New mesh refinement study: the start size, the factor per level and the number of levels."""

    def __init__(self, parent, start, unit):
        super().__init__(parent)
        self.setWindowTitle("New mesh refinement study")
        lay = QVBoxLayout(self)
        intro = QLabel("The same analysis is solved on finer and finer meshes. The study then shows how the results settle, so you can pick an "
                       "element size that is fine enough.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        form = QFormLayout()
        self.name = QLineEdit("Mesh refinement")
        self.start = QLineEdit(start)
        self.start.setPlaceholderText("coarsest element size")
        self.factor = QLineEdit("0.7")
        self.levels = QSpinBox()
        self.levels.setRange(2, core.REFINE_MAX_LEVELS)
        self.levels.setValue(5)
        form.addRow("Name", self.name)
        form.addRow("Coarsest element size" + (f" ({unit})" if unit else ""), self.start)
        form.addRow("Size factor per level", self.factor)
        form.addRow("Number of levels", self.levels)
        lay.addLayout(form)
        hint = QLabel("A factor of 0.7 makes every level 30% finer (about 2x the elements in 2D, 3x in 3D). The size is multiplied by the factor at every level.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#606060;")
        lay.addWidget(hint)
        self.msg = QLabel("")
        self.msg.setStyleSheet("color:#b3261e;")
        self.msg.setWordWrap(True)
        lay.addWidget(self.msg)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def values(self):
        return self.name.text().strip() or "Mesh refinement", self.start.text().strip(), self.factor.text().strip(), self.levels.value()


class StudyTab(QWidget):
    def __init__(self, sw, threaded=True):
        super().__init__()
        self.sw = sw                          # the SimWindow this study belongs to
        self.kind = "study"                   # (the program window picks the tab's icon by it)
        self.threaded = threaded
        self.path_ = sw.path                  # (not .path: the shell finds the simulation's tab by that name)
        self.studies, self.cur = core.read_index(sw.path) if core.exists(sw.path) else ([{"name": core.FIRST, "sub": ""}], 0)
        self.data = self.load_data(self.studies[self.cur]["sub"])
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

        import sim_ui                                        # the numbered, foldable sections of the simulation panels (a study always belongs to one)
        import ui_kit

        # ---- the bar on top: what this is, and the way back to its simulation
        topbar = QHBoxLayout()
        topbar.setContentsMargins(6, 6, 6, 4)
        topbar.setSpacing(8)
        topbar.addWidget(ui_kit.kind_chip("Study", "#7c4dcc"))
        self.head = QLabel()
        self.head.setWordWrap(True)
        topbar.addWidget(self.head, 1)
        self.b_refresh = QPushButton("Refresh inputs")
        self.b_refresh.setToolTip("Reads the list of inputs and outputs from the simulation again (after supports, loads or profiles were changed).")
        self.b_refresh.clicked.connect(lambda: self.refresh_params())
        topbar.addWidget(self.b_refresh)
        self.b_sim = QPushButton("Go to the simulation")
        self.b_sim.setToolTip("Shows the simulation tab this study belongs to.")
        self.b_sim.clicked.connect(self.goto_sim)
        topbar.addWidget(self.b_sim)

        # ---- the studies of this project: one at a time (an extra row under the bar)
        bar2 = QHBoxLayout()
        bar2.setContentsMargins(6, 0, 6, 4)
        bar2.setSpacing(6)
        bar2.addWidget(QLabel("Study:"))
        self.pick = QComboBox()
        self.pick.setMinimumWidth(180)
        self.pick.setToolTip("A project can hold several studies, for example a mesh refinement study and then the real analysis.")
        self.pick.activated.connect(lambda i: self.switch_study(i))
        bar2.addWidget(self.pick)
        self.b_new = QPushButton("New study")
        menu = QMenu(self.b_new)
        menu.addAction("Empty study...").triggered.connect(lambda _c=False: self.ask_new_study())
        self.act_refine = menu.addAction("Mesh refinement study...")
        self.act_refine.triggered.connect(lambda _c=False: self.ask_refinement())
        menu.addAction("Copy of this study...").triggered.connect(lambda _c=False: self.ask_copy_study())
        self.b_new.setMenu(menu)
        bar2.addWidget(self.b_new)
        self.b_ren = QPushButton("Rename")
        self.b_ren.clicked.connect(lambda _c=False: self.ask_rename_study())
        bar2.addWidget(self.b_ren)
        self.b_del = QPushButton("Delete")
        self.b_del.clicked.connect(lambda _c=False: self.ask_delete_study())
        bar2.addWidget(self.b_del)
        bar2.addStretch(1)

        # ---- the left panel: three numbered steps (they fold), and the Run bar that is always in view
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(6, 2, 6, 6)
        ll.setSpacing(2)
        self.sections = []

        def sec(n, title, open_, help_text=None, summary=None):
            sc_ = sim_ui.Section("study", n, title, open_, help_text, summary)
            self.sections.append(sc_)
            ll.addWidget(sc_)
            return sc_.body

        lay = sec(1, "Inputs to vary", True,
                  help_text="Tick the inputs that should change from case to case. Each ticked input becomes a column of the design-point table; "
                            "every row of the table is one case.",
                  summary=lambda: f"{len(self.cols())} input(s) ticked" if self.desc else "")
        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["Input", "Now"])
        self.tree.setMinimumHeight(200)
        self.tree.header().resizeSection(0, 250)
        self.tree.itemChanged.connect(self.param_toggled)
        lay.addWidget(self.tree, 2)

        lay = sec(2, "Outputs to record", True, help_text="The results that are written into the results table for every case.",
                  summary=lambda: f"{len(self.data.out_checked)} output(s)")
        self.out_tree = QTreeWidget()
        self.out_tree.setColumnCount(1)
        self.out_tree.setHeaderHidden(True)
        self.out_tree.setMinimumHeight(150)
        self.out_tree.itemChanged.connect(self.output_toggled)
        lay.addWidget(self.out_tree, 1)

        lay = sec(3, "Stop early when", True,
                  help_text="Checked after every case, in table order. The case that meets a condition is kept (and marked); every row below it "
                            "is skipped. Put the heavier cases last.",
                  summary=lambda: f"{sum(1 for c in self.data.exit_conds if c.get('on', True))} condition(s) on" if self.data.exit_conds else "No conditions")
        self.exit_table = QTableWidget(0, 4)
        self.exit_table.setHorizontalHeaderLabels(["On", "Output", "", "Value"])
        self.exit_table.verticalHeader().hide()
        self.exit_table.setMinimumHeight(90)
        self.exit_table.setMaximumHeight(160)
        hh = self.exit_table.horizontalHeader()
        hh.setStretchLastSection(True)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)        # the output's name takes the room; no sideways scroll bar
        self.exit_table.setColumnWidth(0, 34)
        self.exit_table.setColumnWidth(2, 54)
        self.exit_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        lay.addWidget(self.exit_table)
        row = QHBoxLayout()
        self.b_addx = QPushButton("Add condition")
        self.b_addx.clicked.connect(self.add_exit)
        row.addWidget(self.b_addx)
        b = QPushButton("Remove selected")
        b.clicked.connect(self.del_exit)
        row.addWidget(b)
        lay.addLayout(row)
        ll.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setWidget(left)

        runbar = QFrame()                                    # pinned under the scrolling steps: Run is always one click away
        runbar.setObjectName("runbar")
        runbar.setStyleSheet("QFrame#runbar { border-top:1px solid #cfd6e0; background:#f6f8fa; }")
        rl = QVBoxLayout(runbar)
        rl.setContentsMargins(8, 8, 8, 6)
        rl.setSpacing(6)
        row = QHBoxLayout()
        self.b_all = ui_kit.primary(QPushButton("Run all rows"))
        self.b_all.setMinimumHeight(34)
        self.b_all.setToolTip("Runs every row of the design-point table, one case after another.")
        self.b_all.clicked.connect(self.run_all)
        self.b_stop = QPushButton("Stop")
        self.b_stop.setMinimumHeight(34)
        self.b_stop.setEnabled(False)
        self.b_stop.setToolTip("Stops after the case that is being solved; the finished cases are kept.")
        self.b_stop.clicked.connect(self.stop_run)
        row.addWidget(self.b_all, 3)
        row.addWidget(self.b_stop, 1)
        rl.addLayout(row)
        row = QHBoxLayout()
        self.b_sel = QPushButton("Run selected row")
        self.b_sel.setToolTip("Runs only the row that is selected in the design-point table.")
        self.b_sel.clicked.connect(self.run_selected)
        self.b_cur = QPushButton("Run current setup")
        self.b_cur.setToolTip("One case with the simulation exactly as it is now: nothing is changed. A quick check that the simulation solves.")
        self.b_cur.clicked.connect(self.run_current)
        row.addWidget(self.b_sel)
        row.addWidget(self.b_cur)
        rl.addLayout(row)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        rl.addWidget(self.bar)
        self.prog = self.note("Ready.")
        rl.addWidget(self.prog)

        panel = QWidget()
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.setSpacing(0)
        pv.addWidget(scroll, 1)
        pv.addWidget(runbar)
        panel.setMinimumWidth(360)
        self.panel = panel

        right = QSplitter(Qt.Orientation.Vertical)
        top = QWidget()
        tl = QVBoxLayout(top)
        tl.setContentsMargins(6, 6, 6, 0)
        tl.addWidget(self.table_head("Design points", "one row is one case; double-click a cell to edit it"))
        self.design = QTableWidget(0, 0)
        self.design.itemChanged.connect(self.design_edited)
        self.design.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        tl.addWidget(self.design, 1)
        self.design_hint = self.note("No columns yet. Tick an input in step 1 on the left: every ticked input becomes a column here, and every "
                                     "row is one case to run. Fill grid and Fill range make many rows at once.")
        tl.addWidget(self.design_hint)
        row = QHBoxLayout()
        for text, fn in (("Add row", self.add_row), ("Duplicate row", self.dup_row), ("Delete row", self.del_row),
                         ("Fill grid...", self.fill_grid), ("Fill range...", self.fill_range)):
            b = QPushButton(text)
            b.clicked.connect(lambda _c=False, f=fn: f())
            row.addWidget(b)
        row.addStretch(1)
        tl.addLayout(row)
        bottom = QWidget()
        bl_ = QVBoxLayout(bottom)
        bl_.setContentsMargins(6, 6, 6, 6)
        bl_.addWidget(self.table_head("Results", "click a row to show that case in the simulation tab"))
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
        b.clicked.connect(lambda _c=False: self.export_csv())            # (a direct connection hands the button's "checked" False in as the file name)
        row.addWidget(b)
        self.b_clear = QPushButton("Clear results")
        self.b_clear.clicked.connect(self.clear_results)
        row.addWidget(self.b_clear)
        row.addStretch(1)
        bl_.addLayout(row)
        self.conv = ConvergencePanel(self.use_size)
        self.tabs_bottom = QTabWidget()
        self.tabs_bottom.addTab(bottom, "Results")
        self.tabs_bottom.addTab(self.conv, "Convergence")
        right.addWidget(top)
        right.addWidget(self.tabs_bottom)
        right.setStretchFactor(0, 1)
        right.setStretchFactor(1, 1)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        split.addWidget(panel)
        split.addWidget(right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        ui_kit.fit_panel(split, panel, left, lo=380, hi=520)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addLayout(topbar)
        outer.addLayout(bar2)
        outer.addWidget(split, 1)
        self.fill_picker()

        self.refresh_params()
        self.fill_exit_table()
        self.rebuild_design()
        self.rebuild_results()
        self.refresh_convergence()
        if self.data.cases:
            self.case_lbl.setText("Results of the last run, loaded from the project. Click a row to show it.")

    # ------------------------------------------------------------------ small helpers
    @staticmethod
    def table_head(title, hint):
        lb = QLabel(f"<span style='color:#4a5872; font-size:11px; font-weight:600; letter-spacing:1px;'>{title.upper()}</span>"
                    f"&nbsp;&nbsp;<span style='color:#6a7790;'>{hint}</span>")
        return lb

    def goto_sim(self):
        sh = getattr(self.sw, "shell", None)
        if sh is not None and sh.is_open(self.sw):
            sh.tabs.setCurrentWidget(self.sw)

    def refresh_sections(self):
        for sc_ in getattr(self, "sections", []):
            sc_.refresh_summary()

    @staticmethod
    def note(text):
        lb = QLabel(text)
        lb.setWordWrap(True)
        lb.setStyleSheet("color:#606060;")
        return lb

    def title(self):
        return "Study - " + os.path.splitext(os.path.basename(str(self.path_).rstrip("/\\")))[0]

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
            pname = os.path.splitext(os.path.basename(str(self.path_).rstrip("/\\")))[0]
            self.head.setText(f"<b>{self.adapter.label}</b> study of the project <b>{pname}</b>"
                              + (f"<br><span style='color:#a05000'>{ready}</span>" if ready else ""))
            self.refresh_sections()
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
        if hasattr(self, "pick"):
            self.fill_picker()

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
        self.design_hint.setVisible(not cols)             # nothing ticked yet: say how the table gets its columns
        self.refresh_sections()

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

    def remember_fill(self, kind, value):
        """Keeps what a Fill window held when it was closed, in the study file, so the next one opens with the same values."""
        self.data.fill[kind] = value
        self.mark()
        try:
            self.save()
        except Exception:
            pass

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
            mem = (self.data.fill.get("grid") or {})
            for p in cols:
                e = QLineEdit(str(mem[p]) if p in mem else (str(self.data.rows[0].get(p, "")) if self.data.rows else ""))
                form.addRow(self.desc[p]["label"], e)
                edits[p] = e
            lay.addLayout(form)
            bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
            bb.accepted.connect(dlg.accept)
            bb.rejected.connect(dlg.reject)
            lay.addWidget(bb)
            ok_ = dlg.exec() == QDialog.DialogCode.Accepted
            self.remember_fill("grid", {**mem, **{p: e.text() for p, e in edits.items()}})        # kept whether the window was accepted or cancelled
            if not ok_:
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
        if len(rows) > 30 and QMessageBox.question(self, "Fill grid", f"That makes {len(rows):,} cases"
                                                   + (" - a very long study, one case after another." if len(rows) > core.CONFIRM_ABOVE else ".")
                                                   + " Continue?") != QMessageBox.StandardButton.Yes:
            return False
        self.data.rows = rows
        self.mark()
        self.rebuild_design()
        return True

    def fill_range(self, specs=None, together=None, log=None, rows=None, confirm=True):
        """Fills the table from a start value, an end value and a count per input (like linspace; log spacing too).  `together`: one row per step
        with all inputs moving at once (shared row count); otherwise every combination.  Replaces all rows after a confirmation.
        `specs` ({id: (start, end, count)}, with together/log/rows) skips the dialog."""
        cols = self.cols()
        if not cols:
            QMessageBox.information(self, "Fill range", "Tick at least one input on the left first.")
            return False
        if specs is None:
            dlg = QDialog(self)
            dlg.setWindowTitle("Fill range")
            dlg.setMinimumWidth(560)
            lay = QVBoxLayout(dlg)
            lay.addWidget(self.note("Give each input a start value and an end value; the values in between are made for you. "
                                    "The table is replaced (you are asked first)."))
            form = QFormLayout()
            mem = self.data.fill.get("range") or {}
            cb_mode = QComboBox()
            cb_mode.addItem("One row per step: all inputs move together (same number of rows)", True)
            cb_mode.addItem("Every combination of the inputs", False)
            cb_mode.setCurrentIndex(0 if mem.get("together", True) else 1)
            form.addRow("Rows", cb_mode)
            cb_sp = QComboBox()
            cb_sp.addItem("Equal steps (linear)", False)
            cb_sp.addItem("Equal ratios (log)", True)
            cb_sp.setCurrentIndex(1 if mem.get("log") else 0)
            form.addRow("Spacing", cb_sp)
            sp_rows = QSpinBox()
            sp_rows.setRange(1, core.MAX_CASES)
            sp_rows.setValue(int(mem.get("rows", 10)))
            form.addRow("Number of rows", sp_rows)
            lay.addLayout(form)
            grid = QFormLayout()
            edits = {}
            for p in cols:
                cur = str(self.data.rows[0].get(p, "")) if self.data.rows else ""
                m0 = (mem.get("specs") or {}).get(p) or [cur, cur, 5]
                a, b, n = QLineEdit(str(m0[0])), QLineEdit(str(m0[1])), QSpinBox()
                n.setRange(1, core.MAX_CASES)
                n.setValue(int(m0[2]))
                n.setToolTip("Values for this input (used when every combination is made)")
                r = QHBoxLayout()
                for lab, w_ in (("from", a), ("to", b), ("values", n)):
                    r.addWidget(QLabel(lab))
                    r.addWidget(w_, 1)
                grid.addRow(self.desc[p]["label"], r)
                edits[p] = (a, b, n)
            lay.addLayout(grid)
            bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
            bb.accepted.connect(dlg.accept)
            bb.rejected.connect(dlg.reject)
            lay.addWidget(bb)
            ok_ = dlg.exec() == QDialog.DialogCode.Accepted
            old_specs = dict(mem.get("specs") or {})
            old_specs.update({p: [e[0].text(), e[1].text(), e[2].value()] for p, e in edits.items()})
            self.remember_fill("range", {"together": bool(cb_mode.currentData()), "log": bool(cb_sp.currentData()), "rows": sp_rows.value(),
                                         "specs": old_specs})                                  # kept whether the window was accepted or cancelled
            if not ok_:
                return False
            together, log, rows = cb_mode.currentData(), cb_sp.currentData(), sp_rows.value()
            specs = {p: (e[0].text(), e[1].text(), e[2].value()) for p, e in edits.items()}
        try:
            new = core.range_rows(cols, specs, bool(together), bool(log), rows)
        except (ValueError, KeyError) as ex:
            QMessageBox.warning(self, "Fill range", f"Check the values: {ex}")
            return False
        if confirm and QMessageBox.question(self, "Fill range", f"This replaces all {len(self.data.rows)} row(s) of the table with {len(new):,} new "
                                            "row(s)" + (" - a very long study, one case after another" if len(new) > core.CONFIRM_ABOVE else "")
                                            + ". Continue?") != QMessageBox.StandardButton.Yes:
            return False
        self.data.rows = new
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

    def prepare_one(self, label, vals, pids):
        """The spec of one case, built on the main thread: {label, values, run, error, state}."""
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
        return spec

    def prepare_all(self, jobs, use_params):
        """All the specs at once (used where nothing is shown, as in tests); a real run prepares them one by one."""
        pids = self.cols() if use_params else []
        return [self.prepare_one(label, vals, pids) for label, vals in jobs], pids

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
        pids = self.cols() if use_params else []
        outs = {o["id"]: o["label"] for o in self.outs}
        unit = getattr(self.tab(), "unit_name", None)
        self.data.clear_cases()
        self.data.run_meta = {"params": [(p, self.desc[p]["label"]) for p in pids],
                              "outputs": [(k, outs[k]) for k in self.data.out_checked if k in outs],
                              "unit": unit() if callable(unit) else None}
        self.specs = []
        self.jobs, self.pids, self.next_job, self.halted = list(jobs), pids, 0, False
        self.mark()
        self.rebuild_results()
        self.bar.setValue(0)
        self.prog.setText(f"Starting: {len(jobs)} case(s)...")
        self.set_busy(True)
        self.worker = CaseWorker(len(jobs))
        if self.threaded:
            self.worker.progress.connect(lambda t: self.prog.setText(t))
            self.worker.case_done.connect(self.on_case_done)
            self.worker.all_done.connect(self.on_all_done)
            self.worker.start()
            self.prep_timer = QTimer(self)                   # prepares the next cases a little at a time, between window events
            self.prep_timer.timeout.connect(self.prep_tick)
            self.prep_timer.start(5)
        else:                                               # no thread (tests): the same steps, in order
            stopped = False
            for i, (label, vals) in enumerate(self.jobs):
                if self.worker.halt:
                    break
                spec = self.prepare_one(label, vals, pids)
                self.specs.append(spec)
                case = run_one(spec, lambda t: None, lambda: self.worker.stop)
                if case is None:
                    stopped = True
                    break
                self.on_case_done(i, case)
            self.on_all_done(stopped)
        return True

    PREFETCH = 3                                            # cases prepared ahead of the one being solved

    def prep_tick(self):
        """Prepares one more case (about one slice of work) when the worker is running low; stops when all are prepared or the run is over."""
        w = self.worker
        if w is None or w.stop or w.halt or self.halted or self.next_job >= len(self.jobs):
            self.prep_timer.stop()
            return
        if w.queue.qsize() >= self.PREFETCH:
            return
        label, vals = self.jobs[self.next_job]
        self.next_job += 1
        spec = self.prepare_one(label, vals, self.pids)
        self.specs.append(spec)
        w.queue.put(spec)

    def set_busy(self, on):
        for w in (self.b_all, self.b_sel, self.b_cur, self.pick, self.b_new, self.b_ren, self.b_del):
            w.setEnabled(not on)
        self.b_stop.setEnabled(on)
        self.tab().setEnabled(not on)                  # nothing else may use the mesher or the solvers during a batch

    def stop_run(self):
        if self.worker is not None:
            self.worker.stop = True
            self.b_stop.setEnabled(False)
            self.prog.setText("Stopping after the current step...")

    def on_case_done(self, i, case):
        if self.halted:                                        # an early exit was met: a case that was already under way is dropped
            return
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
            self.halted = True
        self.data.add_case(summary, case if case.get("status") != "failed" or case.get("result") is not None else None)
        self.bar.setValue(int(1000 * (i + 1) / max(1, len(self.jobs))))
        self.append_result(len(self.data.cases) - 1)
        if len(self.data.cases) % core.FLUSH_EVERY == 0 and self.sw.path:     # a long run does not keep every full result in memory
            try:
                self.data.flush(self.sw.path)
            except Exception:
                pass

    def on_all_done(self, stopped):
        w = self.worker
        self.worker = None
        if getattr(self, "prep_timer", None) is not None:
            self.prep_timer.stop()
        if w is not None and self.threaded:
            w.wait()
        self.set_busy(False)
        n = len(self.data.cases)
        if w is not None and w.halt and not stopped:
            first = next((c for c in self.data.cases if c.get("early_exit")), None)
            for label, jv in self.jobs[n:]:
                self.data.add_case({"label": label, "values": {p: jv[p] for p in self.pids if p in jv}, "status": "skipped", "outputs": {}, "error": None,
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
    def result_cells(self, r, c, cells):
        sev = self.data.severity(c)
        for col, txt in enumerate(cells):
            it = QTableWidgetItem(txt)
            if sev == "bad":
                it.setBackground(QColor("#fde0e0"))
            elif sev == "warn":
                it.setBackground(QColor("#fff3d6"))
            self.res_table.setItem(r, col, it)

    def rebuild_results(self):
        """The whole results table (at the start and the end of a run, not after every case)."""
        heads, rows = self.data.table()
        t = self.res_table
        t.setUpdatesEnabled(False)
        try:
            t.setColumnCount(len(heads))
            t.setHorizontalHeaderLabels(heads)
            t.setRowCount(len(rows))
            for r, (c, cells) in enumerate(zip(self.data.cases, rows)):
                self.result_cells(r, c, cells)
            t.resizeColumnsToContents()
        finally:
            t.setUpdatesEnabled(True)
        if hasattr(self, "conv"):
            self.refresh_convergence()

    def append_result(self, i):
        """Adds the row of case i to the table (during a run: the work per case stays the same however many cases there are)."""
        t = self.res_table
        if t.rowCount() != i or t.columnCount() != len(self.data.heads()):
            return self.rebuild_results()
        t.setRowCount(i + 1)
        self.result_cells(i, self.data.cases[i], self.data.row_cells(self.data.cases[i]))
        if i < 20 or i % 50 == 0:
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
        if not isinstance(path, str):
            path = None
        if not self.data.cases:
            QMessageBox.information(self, "Export", "No results yet.")
            return False
        if path is None:
            path, _ = QFileDialog.getSaveFileName(self, "Export results", "parameter_results.csv", "CSV (*.csv)")
        if not path:
            return False
        self.data.write_csv(path)
        return True

    # ------------------------------------------------------------------ several studies in one project
    def load_data(self, sub):
        if os.path.isfile(core.study_file(self.sw.path, sub)):
            return core.StudyData.load(self.sw.path, sub)
        d = core.StudyData()
        d.sub = sub
        return d

    def fill_picker(self):
        self.pick.blockSignals(True)
        self.pick.clear()
        for x in self.studies:
            self.pick.addItem(x["name"])
        self.pick.setCurrentIndex(self.cur)
        self.pick.blockSignals(False)
        self.b_del.setEnabled(bool(self.studies[self.cur]["sub"]) and not self.running())
        self.b_del.setToolTip("" if self.studies[self.cur]["sub"] else "The first study cannot be deleted (it can be renamed and its results cleared).")
        spec = self.adapter.mesh_refinement() if self.adapter is not None else None
        self.act_refine.setEnabled(spec is not None)
        self.act_refine.setToolTip("" if spec is not None else "Not available for this kind of simulation (it has no mesh).")

    def adopt(self, data):
        """Makes `data` the study on screen: every table is rebuilt from it."""
        self.data = data
        self.own_state = None
        self.refresh_params()
        self.rebuild_results()
        self.case_lbl.setText("Results of this study, loaded from the project. Click a row to show it." if self.data.cases else "")
        self.fill_picker()

    def switch_study(self, i):
        if self.running() or not 0 <= i < len(self.studies) or i == self.cur:
            self.fill_picker()
            return False
        if self.own_state is not None:
            self.back_to_own()
        self.save()
        self.cur = i
        self.adopt(self.load_data(self.studies[i]["sub"]))
        core.write_index(self.sw.path, self.studies, self.cur)
        return True

    def add_study(self, name, data):
        """Saves the study on screen, makes `data` a new study called `name` and shows it."""
        if self.running():
            return False
        if self.own_state is not None:
            self.back_to_own()
        self.save()
        data.sub = core.new_sub(name, self.studies)
        self.studies.append({"name": name, "sub": data.sub})
        self.cur = len(self.studies) - 1
        self.adopt(data)
        self.mark()
        self.save()
        return True

    def unique_name(self, base):
        names = {x["name"] for x in self.studies}
        name, i = base, 2
        while name in names:
            name, i = f"{base} {i}", i + 1
        return name

    def ask_new_study(self):
        name, ok = QInputDialog.getText(self, "New study", "Name:", text=self.unique_name(f"Study {len(self.studies) + 1}"))
        if ok and name.strip():
            self.new_empty(name.strip())

    def new_empty(self, name):
        d = core.StudyData()
        d.checked, d.rows = [], [{}]
        return self.add_study(self.unique_name(name), d)

    def ask_copy_study(self):
        name, ok = QInputDialog.getText(self, "Copy of this study", "Name:", text=self.unique_name(self.studies[self.cur]["name"] + " copy"))
        if ok and name.strip():
            self.copy_study(name.strip())

    def copy_study(self, name):
        """The inputs, rows, outputs and conditions of this study, without its results."""
        src = self.data
        d = core.StudyData()
        d.checked, d.rows = list(src.checked), [dict(r) for r in src.rows]
        d.out_checked, d.exit_conds = list(src.out_checked), [dict(c) for c in src.exit_conds]
        d.refine = dict(src.refine) if src.refine else None
        return self.add_study(self.unique_name(name), d)

    def ask_rename_study(self):
        name, ok = QInputDialog.getText(self, "Rename study", "Name:", text=self.studies[self.cur]["name"])
        if ok and name.strip():
            self.rename_study(name.strip())

    def rename_study(self, name):
        if any(x["name"] == name and i != self.cur for i, x in enumerate(self.studies)):
            QMessageBox.information(self, "Rename study", "Another study already has that name.")
            return False
        self.studies[self.cur]["name"] = name
        self.mark()
        self.fill_picker()
        return True

    def ask_delete_study(self):
        x = self.studies[self.cur]
        if not x["sub"] or self.running():
            return
        if QMessageBox.question(self, "Delete study", f"Delete the study '{x['name']}' with all its results? This cannot be undone."
                                ) != QMessageBox.StandardButton.Yes:
            return
        self.delete_study()

    def delete_study(self):
        x = self.studies[self.cur]
        if not x["sub"] or self.running():
            return False
        core.delete_files(self.sw.path, x["sub"])
        del self.studies[self.cur]
        self.cur = 0
        self.adopt(self.load_data(self.studies[0]["sub"]))
        self.mark()
        self.save()
        return True

    # ------------------------------------------------------------------ mesh refinement
    def refinement_spec(self):
        return self.adapter.mesh_refinement() if self.adapter is not None else None

    def ask_refinement(self):
        spec = self.refinement_spec()
        if spec is None:
            QMessageBox.information(self, "Mesh refinement", "A mesh refinement study is not available for this simulation.")
            return
        why = self.adapter.ready()
        if why:
            QMessageBox.information(self, "Mesh refinement", why)
            return
        now = self.now(spec["sizes"][0])
        try:
            start = now if float(now) > 0 else ""
        except ValueError:
            start = ""
        dlg = RefineDialog(self, start, spec.get("unit", ""))
        while True:
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            name, st, fac, lev = dlg.values()
            try:
                self.new_refinement(name, st, fac, lev)
                return
            except ValueError as ex:
                dlg.msg.setText(str(ex))

    def new_refinement(self, name, start, ratio, levels):
        """Makes a mesh refinement study: the rows, the inputs, the outputs and the convergence settings.  ValueError says what is wrong."""
        spec = self.refinement_spec()
        if spec is None:
            raise ValueError("A mesh refinement study is not available for this simulation.")
        self.refresh_params()
        sizes = spec["sizes"]
        nows = {p: self.now(p) for p in sizes}
        rows = core.refinement_rows(sizes, nows, start, ratio, levels, spec.get("extra"))
        st, ra, lv = core.refine_check(start, ratio, levels)
        d = core.StudyData()
        d.checked = [p for p in sizes + list(spec.get("extra", {})) if p in self.desc]
        d.rows = [{p: r[p] for p in d.checked} for r in rows]
        have = {o["id"] for o in self.outs}
        d.out_checked = [o for o in spec["outputs"] if o in have]
        d.refine = {"sizes": list(sizes), "count": spec["count"], "dim": spec["dim"], "ratio": ra, "levels": lv, "tol": 2.0}
        return self.add_study(self.unique_name(name or "Mesh refinement"), d)

    def refinement_levels(self):
        """[{"label", "h", "n", "outputs"}] of the finished cases of a refinement study."""
        rf = self.data.refine
        out = []
        if not rf:
            return out
        for c in self.data.cases:
            if c.get("status") not in ("ok", "converged") or c.get("early_skipped"):
                continue
            try:
                h = float(c["values"].get(rf["sizes"][0]))
            except (TypeError, ValueError):
                continue
            n = c.get("outputs", {}).get(rf["count"])
            if not isinstance(n, (int, float)) or n <= 0:
                n = (1.0 / h) ** rf["dim"] if h > 0 else None
            out.append({"label": c["label"], "h": h, "n": n, "outputs": {k: v for k, v in c.get("outputs", {}).items() if k != rf["count"] or True}})
        return out

    def refresh_convergence(self):
        rf = self.data.refine
        idx = self.tabs_bottom.indexOf(self.conv)
        self.tabs_bottom.setTabVisible(idx, bool(rf))
        if not rf:
            self.conv.set_result(None, {})
            self.conv.res = None
            return
        res = core.convergence(self.refinement_levels(), dim=rf.get("dim", 2), tol=float(rf.get("tol", 2.0)))
        labels = dict(self.data.run_meta.get("outputs", []))
        res["outputs"] = {k: v for k, v in res["outputs"].items() if k != rf["count"]}
        res["notes"] = [k for k in res["notes"] if k != rf["count"]]
        res["pending"] = [k for k in res.get("pending", []) if k != rf["count"]]
        self.conv.set_result(res, labels)

    def use_size(self):
        """The recommended element size goes into the simulation on screen."""
        res = self.conv.res
        rf = self.data.refine
        if not res or not rf or res["recommend"] is None:
            return False
        lv = res["levels"][res["recommend"]]
        case = next((c for c in self.data.cases if str(c["label"]) == str(lv["label"])), None)
        if case is None:
            return False
        try:
            for pid in rf["sizes"]:
                if pid in case["values"]:
                    self.adapter.set_live(pid, case["values"][pid])
        except ValueError as ex:
            QMessageBox.information(self, "Use this element size", str(ex))
            return False
        shown = ", ".join(f"{self.desc[p]['label']} = {case['values'][p]}" for p in rf["sizes"] if p in case["values"] and p in self.desc)
        self.prog.setText(f"The simulation now uses {shown}. Make a new study (New study > Empty) for the real analysis.")
        self.refresh_params()
        return True

    # ------------------------------------------------------------------ save
    def save(self, as_new=False):
        if not self.sw.path:
            return False
        self.data.save(self.sw.path)
        core.write_index(self.sw.path, self.studies, self.cur)
        self.dirty = False
        return True

    def depends_on(self):
        """The simulation tab this study belongs to: the program window closes the study first when that tab is closed."""
        return self.sw

    def can_close(self):
        """Asked by the program window before the tab is closed: a run in progress is stopped only when the user agrees."""
        if not self.running():
            return True
        if QMessageBox.question(self, "Close", "A study is running. Stop it and close? The cases finished so far are kept."
                                ) != QMessageBox.StandardButton.Yes:
            return False
        self.halt_now()
        return True

    def halt_now(self):
        """Stops a run at once (the case being solved is dropped), records what was finished and frees the simulation tab again."""
        w = self.worker
        if w is None:
            return
        w.stop = True
        if self.threaded:
            for sig in (w.progress, w.case_done, w.all_done):
                try:
                    sig.disconnect()
                except TypeError:
                    pass
            w.wait(5000)
        self.on_all_done(True)

    def shutdown(self):
        """The tab is being closed (the program window calls this; a closed tab gets no closeEvent)."""
        try:
            self.halt_now()
        except Exception:
            self.worker = None
        try:
            import study_ext
            study_ext.forget(self)
        except Exception:
            pass

    def closeEvent(self, ev):
        self.shutdown()
        super().closeEvent(ev)
