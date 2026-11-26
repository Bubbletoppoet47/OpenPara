"""wb_testing_tab.py - the window of a Model testing block: the Annotator's Analyse tab (annotator_analyse.py), moved out of the Annotator window into a window of its own.

    ribbon   Test:    Open session  Run analysis  Stop  | Dots in boxes  All dots | Save frame image  Export CSV  Export report | Try the example  Self-check      (the Analyse tab's)
             Models:  Import model...  Import folder...
    left     the setup card (session, model, confidence, tolerance) over the Results / Boxes / Frames lists
    right    the frame with the model's boxes coloured by what the LiDAR says, a card for the selected box, the scrubber
    foot     the project, the models, and what the analysis says

The numbers and the widgets are the Annotator's (annotator_analysis.py, annotator_analyse.py).  The Analyse tab asks its window for a few things (the list of models, a folder to start in,
a way to run something in the window's thread); this window answers them from the block: the models are those of the wires and the ones imported into the block, not the Annotator's list.
Model files or a recorded session folder dropped on the window are taken: a model is imported (inside the project, or linked when it is over 500 MB), a session becomes the test data.
This window does not change what the Annotator's own Analyse tab does.
"""
import os

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import QComboBox, QFileDialog, QHBoxLayout, QLabel, QSplitter, QVBoxLayout, QWidget

import ui_kit
import wb_models
import wb_models_tab
import wb_project as wp


class Poster(QObject):
    """Runs a function in the window's thread (for what a worker thread of the analysis wants shown)."""
    call = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.call.connect(lambda fn: fn())

    def __call__(self, fn):
        self.call.emit(fn)


class LazyEntries:
    """The Analyse tab looks a model up by its label: {"path", "kind"}.  The file of a model kept inside the project is written out only when it is asked for (on the worker thread of a run)."""

    def __init__(self, win):
        self.win, self.rows = win, {}

    def set(self, rows):
        self.rows = rows

    def get(self, label, default=None):
        r = self.rows.get(label)
        if r is None:
            return default
        path = wb_models.row_path(self.win.tab, r)
        return {"label": label, "path": path or "", "kind": "scratch" if r["key"] == "scratch" else "assist"}


class TestingWindow(QWidget):
    kind = "modeltesting"
    path = None

    def __init__(self, tab, node, adapter):
        super().__init__()
        import annotator_analyse as ana
        self.tab, self.node, self.adapter = tab, node, adapter
        self.host = tab.host
        self.cfg = {}
        self.runs = 0                                        # how many analyses ended in this window (the block's Analysis cell follows it)
        self.post = Poster()
        self.ai_choice = QComboBox()                         # what the Analyse tab reads its list of models from (not shown)
        self._ai_entries = LazyEntries(self)
        self._fp = None
        self._note = ""
        self.setAcceptDrops(True)
        self.analyse = None
        self._build(ana)
        self.reload_models()
        self.restore()

    # ------------------------------------------------------------------ the tab protocol
    def title(self):
        return f"{self.node.label} {self.node.title}"

    def is_dirty(self):
        return False

    def save(self, as_new=False):
        return True

    def can_close(self):
        if self.analyse.running:
            from PyQt6.QtWidgets import QMessageBox
            r = QMessageBox.question(self, "An analysis is running", "A model is still being run over the session. Closing this tab stops it; what is done so far is not kept.\n\nStop and close?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if r != QMessageBox.StandardButton.Yes:
                return False
            self.analyse.stop()
        return True

    def shutdown(self):
        self.analyse.shutdown()

    # ------------------------------------------------------------------ what the Analyse tab asks of its window
    def _save_cfg(self):
        pass

    def _update_status(self):
        """An analysis ended (or the LiDAR was read again): the project takes note."""
        self.runs += 1
        self.adapter.changed_in_window(self.tab)

    def _announce(self, text):
        self.say(text)

    def show_analyse_status(self, text):
        self._analyse_text = text
        if hasattr(self, "foot_lbl"):                        # (the Analyse tab says it once while it is being made, before the status bar is)
            self.foot_lbl.setText(text)

    # ------------------------------------------------------------------ the window
    def _build(self, ana):
        import annotator_ribbon as rib
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.ribbon = R = rib.Ribbon()
        outer.addWidget(R)
        self.analyse = ana.AnalyseTab(self)
        self.analyse.bind_ribbon(R.add_page("Test", self.analyse.ribbon_items()))
        B = rib.button
        self.models_buttons = R.add_page("Models", [
            B("import_model", "ann_import_zip", "Import\nmodel...", "Takes model files (.pt, .opdm) into this block. A model up to 500 MB is kept inside the project file, a bigger one is linked.", self.import_model),
            B("import_folder", "ann_import_zip", "Import\nfolder...", "Takes every model file (.pt, .opdm) of a folder into this block.", self.import_folder),
        ])
        corner = QWidget()
        cl = QHBoxLayout(corner)
        cl.setContentsMargins(0, 0, 8, 0)
        cl.addWidget(ui_kit.kind_chip("Model testing", "#2f6fb3"))
        self.bar_lbl = QLabel("")
        self.bar_lbl.setStyleSheet(f"color:{ui_kit.MUTED};")
        cl.addWidget(self.bar_lbl)
        R.setCornerWidget(corner, Qt.Corner.BottomRightCorner)
        body = QSplitter()
        body.setContentsMargins(4, 4, 4, 4)
        body.setChildrenCollapsible(False)
        body.addWidget(self.analyse.panel)
        body.addWidget(self.analyse.view)
        body.setStretchFactor(1, 1)
        body.setSizes([330, 900])
        outer.addWidget(body, 1)
        foot = QWidget()
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(8, 2, 8, 2)
        self.foot_lbl = QLabel("")
        self.foot_lbl.setStyleSheet(f"color:{ui_kit.MUTED};")
        fl.addWidget(self.foot_lbl, 1)
        self.status = QLabel("")
        self.status.setStyleSheet(f"color:{ui_kit.WARN};")
        fl.addWidget(self.status)
        outer.addWidget(foot)
        self.foot_lbl.setText(getattr(self, "_analyse_text", ""))

    def say(self, text):
        self.status.setText(text)

    # ------------------------------------------------------------------ the models
    def reload_models(self):
        """The models of the wires and of the block, as the Analyse tab's list (a model keeps its label while it is there)."""
        every = wb_models.models_of(self.tab, self.node.id)
        fp = wb_models.fingerprint(every)
        if fp == self._fp:
            return
        self._fp = fp
        rows = [r for r in every if r["key"] != "distance"]                     # (a distance-only model finds no boxes: it waits for the "Boxes from" slot of the next step)
        waiting = len(every) - len(rows)
        by, count = {}, {}
        for r in rows:
            count[r["name"]] = count.get(r["name"], 0) + 1
        for r in rows:
            label = r["name"] if count[r["name"]] == 1 else f"{r['name']} ({r['from']})"
            by[label] = r
        self._ai_entries.set(by)
        self.ai_choice.clear()
        self.ai_choice.addItems(list(by))
        if self.analyse is not None and not self.analyse.running:
            self.analyse.refresh_models()
        self.bar_lbl.setText(f"{len(rows)} model{'s' if len(rows) != 1 else ''}" + (f"  (+ {waiting} distance-only: not testable yet)" if waiting else ""))

    def import_model(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Import model file(s)", "", "Models (*.pt *.opdm);;Model (*.pt);;Distance model (*.opdm)")
        if paths:
            self.take_paths(paths)

    def import_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Import every model file (.pt, .opdm) of a folder")
        if d:
            self.take_paths([d])

    # ------------------------------------------------------------------ the session and the settings
    def session_link(self):
        """The recorded session as a link for the project file.  Nothing open keeps the link the block has; the made-up example is a temporary folder and is not kept."""
        s = self.analyse.session
        if s is None:
            return self.node.data.get("session")             # (nothing open: the session of the block could not be opened, e.g. its folder is on a disk that is not there; the link stays)
        if self.analyse.demo_dir is not None and os.path.abspath(s.folder).startswith(os.path.abspath(self.analyse.demo_dir)):
            return self.node.data.get("session")             # (trying the example does not take the person's own test data away)
        return wp.rel_link(s.folder, self.tab.path)

    def settings_now(self):
        a = self.analyse
        return {"conf": round(a.settings.conf, 4), "tol": round(a.settings.tol, 4), "method": a.settings.method, "region": a.region, "dots": a.dots, "model": a.panel.model_combo.currentText()}

    def restore(self):
        """The window opens as the block was left: the settings, and the session when its folder is still there (nothing is run)."""
        a, p = self.analyse, self.analyse.panel
        s = self.node.data.get("settings") or {}
        if "conf" in s:
            p.conf_slider.setValue(int(round(float(s["conf"]) * 100)))
        if "tol" in s:
            p.tol_spin.setValue(int(round(float(s["tol"]) * 100)))
        if s.get("region") == "core":
            p.core_check.setChecked(True)
        if s.get("method") in ("closest", "median", "average"):
            a.settings.method = s["method"]
        if s.get("dots") == "all" and "dots_all" in a.rb:
            a.rb["dots_all"].setChecked(True)
        if s.get("model") and p.model_combo.findText(s["model"]) >= 0:
            p.model_combo.setCurrentText(s["model"])
        link = self.node.data.get("session")
        if link:
            folder = wp.resolve_link(link, self.tab.path)
            if folder and os.path.isdir(folder):
                a.open_session(folder)
            else:
                self.say(f"The session folder {link.get('abs', '')} is not there: open it again (Test > Open session).")
        a.refresh(True)

    # ------------------------------------------------------------------ dropping files
    def take_paths(self, paths):
        """Model files and folders of them are imported into the block; a recorded session folder is opened as the test data.  -> a sentence about what was done."""
        import annotator_analysis as aa
        models, sessions = [], []
        for p in paths:
            if os.path.isdir(p) and aa.find_sessions(p):
                sessions.append(p)
            else:
                models.append(p)
        said = []
        if sessions and not self.analyse.running:
            if self.analyse.open_session(sessions[0]):
                said.append(f"Test data: {os.path.basename(sessions[0])}.")
        if models:
            done, text = wb_models_tab.import_models(self, self.tab, self.node, models, self.host)
            if done:
                self.reload_models()
                self.adapter.changed_in_window(self.tab)
            if text:
                said.append(text)
        self.say(" ".join(said))
        return " ".join(said)

    def dragEnterEvent(self, e):
        if any(u.toLocalFile().lower().endswith(wb_models.EXTS) or os.path.isdir(u.toLocalFile()) for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.take_paths([u.toLocalFile() for u in e.mimeData().urls()])
