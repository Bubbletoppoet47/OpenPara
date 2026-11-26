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

A DISTANCE-ONLY model (.opdm: it answers how far a box is, it finds no boxes) is in the list too.  It is tried with the boxes of a detector: the "Boxes from" box over the setup card says
which one (wb_testing_boxes.py).  The detector runs once over the session however many distance models are tried on it.  Every run made in the window is kept (in memory) and the
"Compare models" pane shows them side by side: a table and the share that pass by distance (wb_testing_compare.py).  A model that holds a pickle is opened only after the person says yes.
"""
import os
import threading

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QSplitter, QVBoxLayout, QWidget

import ui_kit
import wb_models
import wb_models_tab
import wb_project as wp
import wb_testing_boxes as tb
import wb_testing_compare as tcmp

NO_DETECTOR = ("A distance-only model finds no boxes: it answers how far each box is. Pick the model that finds the boxes in 'Boxes from' (a model of the list that is not distance only: "
               "wire a Trainer or a Trained models block that has one into this block, or drop a .pt file on it).")


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
        return {"label": label, "path": path or "", "kind": {"scratch": "scratch", "distance": "distance"}.get(r["key"], "assist")}


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
        self._dist_labels, self._det_labels = [], []         # the labels of the list: distance-only models, and the models that find boxes
        self._bf = ""                                        # the "Boxes from" choice (a plain string: the worker thread of a run reads it)
        self._detectors, self._composed = {}, {}             # detector label -> DetectorBoxes;  (model id, detector label) -> predictor.  Emptied when the list changes
        self._trusted = set()                                # ids of the pickled models the person said yes to, while this window is open
        self.kept, self.slots = {}, {}                       # the runs made here: (model label, detector label) -> {...};  run -> its colour in the chart
        self._run_info = None                                # (model label, detector label) of the run that was started last
        self._queue = []                                     # model labels still to run ("Run the other distance models")
        self._shown_once = False
        self._build(ana)
        self.reload_models()
        self.restore()
        self._poll_state = None
        self._timer = QTimer(self)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

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
        self._timer.stop()
        self.analyse.shutdown()

    # ------------------------------------------------------------------ what the Analyse tab asks of its window
    def _save_cfg(self):
        pass

    def _update_status(self):
        """An analysis ended (or the LiDAR was read again): the project takes note."""
        self.runs += 1
        self.keep_run()
        self.refresh_compare()
        self.adapter.changed_in_window(self.tab)
        if self._queue:
            kept = self.kept.get(self._run_info) if self._run_info else None
            if kept is not None and kept["an"].finished:
                QTimer.singleShot(0, self._next_queued)
            else:
                self._queue = []

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
        self.analyse.predictor_for = self._predictor_for     # (a distance-only model is put on the boxes of a detector; the other models are run as the Analyse tab does)
        self.analyse.bind_ribbon(R.add_page("Test", self.analyse.ribbon_items()))
        B = rib.button
        self.models_buttons = R.add_page("Models", [
            B("import_model", "ann_import_zip", "Import\nmodel...", "Takes model files (.pt, .opdm) into this block. A model up to 500 MB is kept inside the project file, a bigger one is linked.", self.import_model),
            B("import_folder", "ann_import_zip", "Import\nfolder...", "Takes every model file (.pt, .opdm) of a folder into this block.", self.import_folder),
            "|",
            B("compare", "ann_an_report", "Compare\nmodels", "Show the runs made in this window side by side: a table, and the share that pass by distance.", checkable=True),
        ])
        self.models_buttons["compare"].toggled.connect(self.show_compare)
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
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(6)
        ll.addWidget(self._boxes_card(ana))
        ll.addWidget(self.analyse.panel, 1)
        self.compare = tcmp.CompareView(self.run_others, self.export_comparison)
        self.compare.hide()
        body.addWidget(left)
        body.addWidget(self.analyse.view)
        body.addWidget(self.compare)
        body.setStretchFactor(1, 1)
        body.setSizes([330, 900, 0])
        self.body = body
        self.analyse.panel.model_combo.currentTextChanged.connect(self._model_changed)
        orig = self.analyse.refresh_models

        def refresh_models():                                # (the example adds its made-up model to the list: the detector list follows)
            orig()
            self.reload_boxes_from()
        self.analyse.refresh_models = refresh_models
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
        self._detectors.clear()                                                         # (what was loaded of the old list goes)
        self._composed.clear()
        count = {}
        for r in every:
            count[r["name"]] = count.get(r["name"], 0) + 1
        by = {}
        self._dist_labels, self._det_labels = [], []
        for r in every:
            label = r["name"] if count[r["name"]] == 1 else f"{r['name']} ({r['from']})"
            if r["key"] == "distance":
                label += " (distance only)"
                self._dist_labels.append(label)
            else:
                self._det_labels.append(label)
            by[label] = r
        self._ai_entries.set(by)
        self.ai_choice.clear()
        self.ai_choice.addItems(list(by))
        if self.analyse is not None and not self.analyse.running:
            self.analyse.refresh_models()
        self.reload_boxes_from()
        n, d = len(by), len(self._dist_labels)
        self.bar_lbl.setText(f"{n} model{'s' if n != 1 else ''}" + (f"  ({d} distance only)" if d else ""))

    # ------------------------------------------------------------------ "Boxes from": the detector a distance-only model is put on
    def _boxes_card(self, ana):
        box = QFrame()
        box.setObjectName("boxesfrom")
        box.setStyleSheet("QFrame#boxesfrom{background:#ffffff; border:1px solid #ababab;}")
        v = QVBoxLayout(box)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(4)
        h = QLabel("BOXES FROM")
        h.setStyleSheet(ana.HEADING)
        v.addWidget(h)
        self.bf_combo = QComboBox()
        self.bf_combo.setToolTip("The model that finds the boxes. Used when the model chosen below is a distance-only one: it answers how far each of those boxes is.")
        self.bf_combo.currentTextChanged.connect(self._bf_changed)
        v.addWidget(self.bf_combo)
        self.bf_note = QLabel("")
        self.bf_note.setWordWrap(True)
        self.bf_note.setStyleSheet(f"color:{ui_kit.MUTED}; font-size:11px;")
        v.addWidget(self.bf_note)
        return box

    def reload_boxes_from(self):
        """The list of detectors (every model that is not distance only, and the example's made-up one while the example is open); the choice stays when it is still there."""
        import annotator_analyse as ana
        labels = list(self._det_labels)
        if self.analyse is not None and self.analyse.demo_dir is not None:
            labels.append(ana.DEMO_LABEL)
        keep = self._bf if self._bf in labels else (labels[0] if labels else "")
        self.bf_combo.blockSignals(True)
        self.bf_combo.clear()
        self.bf_combo.addItems(labels)
        if keep:
            self.bf_combo.setCurrentText(keep)
        self.bf_combo.blockSignals(False)
        self._bf = keep
        self._model_changed(self.analyse.panel.model_combo.currentText() if self.analyse is not None else "")

    def _bf_changed(self, text):
        self._bf = text

    def _model_changed(self, text):
        dist = text in self._dist_labels
        self.bf_combo.setEnabled(dist and not (self.analyse is not None and self.analyse.running))
        if dist:
            self.bf_note.setText("This model gives distances only. The boxes come from the model chosen here." if self._bf else NO_DETECTOR)
        else:
            self.bf_note.setText("This model finds its own boxes." if text else "No model yet.")

    def make_detector(self, label):
        """predict(picture path) of a detector of the list (loaded on the worker thread of a run; a model that cannot be run says why)."""
        import annotator_analyse as ana
        import annotator_analysis as aa
        if label == ana.DEMO_LABEL:
            return aa.demo_predictor
        return self.analyse._default_predictor(label)[0]

    def _detector(self, label):
        d = self._detectors.get(label)
        if d is None:
            d = self._detectors[label] = tb.DetectorBoxes(self.make_detector(label))
        return d

    def trust_question(self, label, row):
        """May a model file that holds a pickle be opened?  (A pickle can run code when it is read.)  Asked in the window's thread."""
        r = QMessageBox.question(self, "A model that holds a pickle",
                                 f"'{label}' ({row['from']}) holds a pickle of a scikit-learn model. A pickle can run code when it is read.\n\nOpen it only if you trust where it came from. Open it?",
                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        return r == QMessageBox.StandardButton.Yes

    def _ask_gui(self, fn):
        """Runs fn in the window's thread and waits for its answer (called from the worker thread of a run)."""
        done, box = threading.Event(), {}

        def go():
            try:
                box["v"] = fn()
            except Exception as e:                           # noqa: BLE001
                box["e"] = e
            finally:
                done.set()
        self.post(go)
        while not done.wait(0.1):
            if self.analyse._stop.is_set():
                raise RuntimeError("Stopped.")
        if "e" in box:
            raise box["e"]
        return box.get("v")

    def _predictor_for(self, label):
        """(predict, has_distance) of a run, on its worker thread.  A model that finds boxes: as the Analyse tab does.  A distance-only one: the boxes of the detector chosen in 'Boxes from',
        the distance of each from the model."""
        row = self._ai_entries.rows.get(label)
        if row is None or row["key"] != "distance":
            self._run_info = (label, "")
            return self.analyse._default_predictor(label)
        bf = self._bf
        if not bf:
            raise RuntimeError(NO_DETECTOR)
        ck = (row["id"], bf)
        pred = self._composed.get(ck)
        if pred is None:
            path = wb_models.row_path(self.tab, row)
            if not path or not os.path.exists(path):
                raise RuntimeError(f"'{label}' is not there (any more). Pick another model.")
            trust = False
            if tb.needs_trust(path):
                trust = row["id"] in self._trusted or bool(self._ask_gui(lambda: self.trust_question(label, row)))
                if not trust:
                    raise RuntimeError(f"'{label}' was not opened: it holds a pickle, and it was not trusted.")
                self._trusted.add(row["id"])
            model = tb.load_model(path, trust)
            pred = self._composed[ck] = tb.DistanceOnBoxes(self._detector(bf), model)
        self._run_info = (label, bf)
        return pred, True

    # ------------------------------------------------------------------ the runs made here, side by side
    def keep_run(self):
        """The run that just ended is kept (in memory) under the model and the detector it was made with; the same again replaces it."""
        a = self.analyse
        an = a.analysis
        if an is None or an.analysed == 0 or a.session is None:
            return
        info = self._run_info if self._run_info and self._run_info[0] == an.model else (an.model, "")
        if info not in self.slots:
            self.slots[info] = len(self.slots) if len(self.slots) < len(tcmp.PALETTE) else None
        self.kept[info] = {"an": an, "region": an.region, "folder": tb.folder_key(a.session), "name": tb.run_name(info[0], info[1])}
        if len(self.kept) >= 2 and not self._shown_once:
            self._shown_once = True
            self.models_buttons["compare"].setChecked(True)

    def compare_items(self):
        a = self.analyse
        here = tb.folder_key(a.session)
        out = []
        for key, k in self.kept.items():
            if k["folder"] != here:
                continue
            it = {"name": k["name"], "slot": self.slots.get(key), "summary": None, "note": ""}
            if not tb.same_reading(k["region"], a.region):
                it["note"] = "read with the other part of the box: run again"
            else:
                it["summary"] = tb.summarise(k["an"], a.settings)
                if not k["an"].finished:
                    it["note"] = f"stopped after {k['an'].analysed} of {len(k['an'].session)} frames"
            out.append(it)
        return out

    def refresh_compare(self):
        if not self.models_buttons["compare"].isChecked():
            return
        import annotator_analysis as aa
        a = self.analyse
        self.compare.set_items(self.compare_items(), round(a.settings.tol * 100, 4), aa.METHOD_NAMES[a.settings.method])
        self.compare.run_btn.setEnabled(not a.running)

    def _poll(self):
        """The settings on the left moved, a run ended or the session changed: the pane follows."""
        a = self.analyse
        state = (round(a.settings.conf, 4), round(a.settings.tol, 4), a.settings.method, a.region, tb.folder_key(a.session), len(self.kept), a.running,
                 tuple(id(k["an"]) for k in self.kept.values()), a.analysis.analysed if a.analysis is not None else 0)
        if state != self._poll_state:
            self._poll_state = state
            self._model_changed(a.panel.model_combo.currentText())
            self.refresh_compare()

    def show_compare(self, on):
        self.compare.setVisible(bool(on))
        self.body.setSizes([330, 560, 400] if on else [330, 900, 0])
        if on:
            self.refresh_compare()

    def run_others(self):
        """Every distance-only model of the list that has no run on this session yet, one after the other, on the boxes of the detector chosen in 'Boxes from'."""
        a = self.analyse
        if a.running:
            return
        if a.session is None:
            self.say("Open a recorded session first (Test > Open session).")
            return
        if not self._bf:
            self.say(NO_DETECTOR)
            return
        here = tb.folder_key(a.session)
        todo = [lab for lab in self._dist_labels
                if not ((lab, self._bf) in self.kept and self.kept[(lab, self._bf)]["folder"] == here and tb.same_reading(self.kept[(lab, self._bf)]["region"], a.region))]
        if not todo:
            self.say("Every distance-only model of the list has been run on this session already.")
            return
        self._queue = todo
        self.say(f"Running {len(todo)} distance-only model{'s' if len(todo) != 1 else ''} on the boxes of {self._bf}.")
        self._next_queued()

    def _next_queued(self):
        a = self.analyse
        if not self._queue or a.running:
            return
        label = self._queue.pop(0)
        a.panel.model_combo.setCurrentText(label)
        a.set_model(label)
        a.run()

    def export_comparison(self):
        a = self.analyse
        items = [(it["name"], it["summary"]) for it in self.compare_items() if it["summary"] is not None]
        if not items:
            self.say("Nothing to export yet: run a model over the session.")
            return None
        path, _ = QFileDialog.getSaveFileName(self, "Export the comparison", "model_comparison.csv", "CSV (*.csv)")
        if not path:
            return None
        tb.write_comparison(path, items, a.settings)
        self.say(f"Wrote {os.path.basename(path)}.")
        return path

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
        d = {"conf": round(a.settings.conf, 4), "tol": round(a.settings.tol, 4), "method": a.settings.method, "region": a.region, "dots": a.dots, "model": a.panel.model_combo.currentText()}
        if self._dist_labels and self._bf:                                               # (only a block that has a distance-only model has a use for it)
            d["boxes_from"] = self._bf
        return d

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
        if s.get("boxes_from") and self.bf_combo.findText(s["boxes_from"]) >= 0:
            self.bf_combo.setCurrentText(s["boxes_from"])
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
