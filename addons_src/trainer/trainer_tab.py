"""The Trainer as a program tab: merge annotator zips into a ".training" project, choose training / validation sets and distortions,
train a model in the background (the window stays usable) and save it as a new version the annotator lists.

All the logic is in trainer_core.py; this file is the window.
"""
import importlib.util
import os
import shutil
import sys
import threading
import time

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                             QProgressBar,
                             QListWidget,
                             QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QSplitter, QTableWidget,
                             QTableWidgetItem, QVBoxLayout, QWidget)

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import trainer_core as tc  # noqa: E402
import ui_kit  # noqa: E402


HINTS = {
    "brightness": "Randomly makes pictures lighter or darker, so the model copes with different lighting.",
    "contrast": "Randomly flattens or sharpens the difference between light and dark areas.",
    "saturation": "Randomly washes colours out or boosts them, like a different camera sensor.",
    "blur": "Randomly softens pictures, like a camera that is slightly out of focus. Radius is in pixels; chance is how often it is applied (0 to 1).",
    "noise": "Adds random grain, like a camera in low light. Higher numbers are grainier.",
    "jpeg": "Re-saves the picture at lower JPEG quality so it picks up compression blocks. Lower numbers look worse (100 = no loss).",
    "count": "How many distorted versions are made of each training picture. 3 copies means about 4 times as many training pictures, and every epoch takes about 4 times as long.",
    "type": "All of these are YOLO models. Classes + boxes: the model finds objects and says what they are. "
            "Classes + boxes + distance: it also estimates how far away each object is, in metres. It learns that from the LiDAR distances picked on "
            "boxes in the Annotator (boxes without one still teach class and position), and it is the kind the Gimble uses to show distance. "
            "Pretrained starts from weights that already know general shapes: it trains quickly and works with fewer pictures. "
            "Not pretrained starts from random numbers: it needs many more pictures and epochs.",
    "size": "Bigger models can be more accurate but are slower to train and run, and need more GPU memory. n = nano (smallest), s = small, m = medium, l = large.",
    "epochs": "One epoch is one pass over all the training pictures. More epochs train longer; it usually helps until the validation score stops improving.",
    "patience": "Training ends early when the validation score has not improved for this many epochs.",
    "batch": "How many pictures the GPU handles at once. Higher is faster but needs more GPU memory. If training runs out of memory, lower it.",
    "imgsz": "Every picture is resized to this many pixels wide before training. Bigger sizes find small objects better but need more GPU memory and time. 640 is the usual choice.",
    "continue": "Train further from a model you already made (here or in the annotator's models, or a .pt file). It keeps its size and its kind "
                "(with or without distance) and must know the same classes you have ticked.",
    "name": "Optional name for the finished model. It is shown in the annotator's AI model box with the size and date. Left empty, it is named after you.",
    "python": "The Python that runs the training. It needs torch (the CUDA build, for your GPU) and ultralytics.",
}


def hint(key_or_text):
    lab = QLabel(HINTS.get(key_or_text, key_or_text))
    lab.setWordWrap(True)
    lab.setStyleSheet("color:#6a7790; font-size:11px;")
    return lab


def tip(widget, key):
    widget.setToolTip(HINTS[key])
    return widget


def same_path(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def pane_head(text):
    """The small heading of a pane ("RUN"), the same as in the rest of the program."""
    lb = QLabel(text.upper())
    lb.setStyleSheet("color:#4a5872; font-size:11px; font-weight:600; letter-spacing:1px;")
    return lb


class Poster:
    """Runs a function in the window's thread (for work done in a background thread)."""

    def __init__(self):
        from PyQt6.QtCore import QObject, pyqtSignal

        class _P(QObject):
            call = pyqtSignal(object)

        self._p = _P()
        self._p.call.connect(lambda fn: fn())

    def __call__(self, fn):
        self._p.call.emit(fn)


def make_tab(path=None):
    if importlib.util.find_spec("PIL") is None or importlib.util.find_spec("numpy") is None:
        return MissingPackages("The Trainer needs these packages first:\n\n    pip install pillow numpy opencv-python")
    if not os.path.isdir(tc.ANNOTATOR_APP):
        return MissingPackages("The Trainer uses the Annotator add-on's code for its dataset merge and model files.\n\n"
                               "Install the Annotator add-on first (File > Add-ons).")
    if path:
        os.makedirs(path, exist_ok=True)
        return TrainerTab(path)
    return TrainerTab(tc.untitled_dir(), temp=True)


class MissingPackages(QWidget):
    def __init__(self, text):
        super().__init__()
        self.path = None
        self.host = None
        lay = QVBoxLayout(self)
        lab = QLabel(text)
        lab.setWordWrap(True)
        lay.addWidget(lab)
        lay.addStretch(1)

    def title(self):
        return "Trainer"


class TrainerTab(QWidget):
    def __init__(self, root, temp=False):
        super().__init__()
        self.kind = "trainer"
        self.host = None
        self.temp_root = root if temp else None
        self.path = None if temp else root
        self.post = Poster()
        self.job = None
        self.env = None
        self._bg = False
        self._prep = None                                      # while a run is being prepared: {'stop', 'stage', 'done', 'total', 't0', ...}
        self._closed = False
        self._distort_pictures = 0
        self._loading = False
        self.ac, self.dz, self.sz, self.ml = tc.libs()
        self.cfg = self.sz.load_config()
        self.me = self.sz.identity(self.cfg)
        self.tp = tc.TrainingProject(root)
        self._loading = True                                   # building the widgets must not write their empty values into the settings
        self._build()
        self._loading = False
        self._infos = {}
        self.refresh_all()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(500)
        QTimer.singleShot(400, self.check_env)

    # ------------------------------------------------------------------ the tab protocol
    def title(self):
        if self.path:
            b = os.path.basename(self.path.rstrip("/\\"))
            return b[:-len(".training")] if b.lower().endswith(".training") else b
        return "Trainer"

    def is_dirty(self):
        return self.temp_root is not None and bool(self.tp.data.manifest["images"])

    def running(self):
        return self.job is not None and self.job.poll() is None

    def preparing(self):
        """True between pressing Start training and the training program starting (distorted copies, the run's copy of the data)."""
        return self._prep is not None

    def can_close(self):
        if self.running():
            r = QMessageBox.question(self, "Training is running", "A model is still training. Closing this tab stops it and nothing is saved from the run.\n\nStop training and close?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if r != QMessageBox.StandardButton.Yes:
                return False
            self.job.stop()
        if self.preparing():
            QMessageBox.information(self, "Please wait", "The training data is still being prepared. Press Cancel to stop that, then close the tab.")
            return False
        if self._bg:
            QMessageBox.information(self, "Please wait", "An import or export is still running. Close the tab when it has finished.")
            return False
        return True

    def shutdown(self):
        self.timer.stop()
        self._closed = True
        if self._prep:
            self._prep["stop"] = True                          # the preparation thread ends at its next picture
        if self.running():
            self.job.stop()
        if self.temp_root:
            shutil.rmtree(self.temp_root, ignore_errors=True)

    def save(self, as_new=False):
        """Gives an unsaved project its folder (everything is copied there); Save As copies a saved one."""
        if self.temp_root is None and not as_new:
            return True
        if self.running() or self._bg or self.preparing():
            QMessageBox.information(self, "Save", "Wait for the training / import to finish, then save.")
            return False
        start = (self.path or "Trainer") if as_new else "Trainer.training"
        path, _ = QFileDialog.getSaveFileName(self, "Save the training project (a folder)", start, "Training project (*.training)")
        if not path:
            return False
        if not path.lower().endswith(".training"):
            path += ".training"
        if self.path and same_path(path, self.path):
            return True
        try:
            self.tp.data.save_manifest()
            self.tp.save()
            shutil.copytree(self.tp.root, path, dirs_exist_ok=True)
        except OSError as e:
            QMessageBox.critical(self, "Save", f"Could not save the project: {e}")
            return False
        old, self.temp_root = self.temp_root, None
        self.path = path
        self.tp = tc.TrainingProject(path)
        if old:
            shutil.rmtree(old, ignore_errors=True)
        self.refresh_all()
        return True

    def _busy(self, text):
        fn = getattr(self.host, "busy", None)
        import contextlib
        return fn(text) if callable(fn) else contextlib.nullcontext()

    # ------------------------------------------------------------------ the window
    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 4)
        top = QHBoxLayout()                                  # the bar: what this is and which project on the left, its commands on the right
        top.setSpacing(8)
        top.addWidget(ui_kit.kind_chip("Trainer", "#b83280"))
        self.bar_lbl = QLabel("")
        self.bar_lbl.setStyleSheet(f"color:{ui_kit.MUTED};")
        top.addWidget(self.bar_lbl)
        self.status = QLabel("")
        self.status.setStyleSheet(f"color:{ui_kit.WARN};")
        top.addWidget(self.status, 1)
        self.bar_buttons = []
        for text, fn, tipx in (("Import dataset zip...", self.import_zip, "Adds the pictures and boxes of a dataset zip (made by the Annotator or another Trainer) to this project."),
                               ("Save project as...", lambda: self.save(True), "Gives the project a .training folder of its own (or copies it to a new one).")):
            b = QPushButton(text)
            b.setToolTip(tipx)
            b.clicked.connect(lambda _c=False, f=fn: f())
            top.addWidget(b)
            self.bar_buttons.append(b)
        outer.addLayout(top)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        outer.addWidget(split, 1)
        self.sections = []

        def section(n, title, help_text=None, summary=None):
            """A numbered, foldable step of the left panel (the look of the analysis panels); returns its layout."""
            sec = ui_kit.Section("trainer", n, title, True, help_text, summary)
            self.sections.append(sec)
            lv.addWidget(sec)
            return sec.body

        # ---- left: data, distortions, model
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(4, 2, 6, 6)
        lv.setSpacing(2)
        gv = section(1, "Data", "The sets of pictures this model learns from. A set marked Validation is never trained on: it is only used for the "
                                "scores, so they say how the model does on pictures it has not seen.",
                     lambda: self.data_info.text().split("\n")[0])
        self.sets_table = QTableWidget(0, 4)
        self.sets_table.setHorizontalHeaderLabels(["Set", "Pictures", "Annotated", "Use as"])
        hh = self.sets_table.horizontalHeader()                    # the set's name takes what is left; "Use as" is never cut off
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in (1, 2):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.sets_table.setColumnWidth(3, 120)
        self.sets_table.verticalHeader().setVisible(False)
        self.sets_table.setMinimumHeight(120)
        gv.addWidget(self.sets_table)
        self.data_info = QLabel("")
        self.data_info.setWordWrap(True)
        gv.addWidget(self.data_info)
        gv.addWidget(QLabel("Classes to train on"))
        self.class_list = QListWidget()
        self.class_list.setMaximumHeight(110)
        self.class_list.itemChanged.connect(lambda _i: self._classes_changed())
        gv.addWidget(self.class_list)

        dv = section(2, "Distortions", "Extra, slightly changed copies of the training pictures (lighter, blurred, noisy ...), so the model copes "
                                       "with pictures that are not perfect. Validation pictures are never distorted.",
                     lambda: "On" if self.dist_on.isChecked() else "Off")
        self.dist_on = QCheckBox("Train on distorted copies of the training pictures")
        self.dist_on.toggled.connect(lambda _c: self._dist_changed())
        dv.addWidget(self.dist_on)
        self.dist_box = QWidget()
        form = QFormLayout(self.dist_box)
        self.dist_checks, self.dist_spins = {}, {}
        for key, label, rk, lo, hi, dec, _neutral in tc.DISTORTION_TYPES:
            row = QHBoxLayout()
            cb = QCheckBox(label)
            cb.toggled.connect(lambda _c: self._dist_changed())
            lo_s, hi_s = self._spin(lo, hi, dec), self._spin(lo, hi, dec)
            lo_s.valueChanged.connect(lambda _v: self._dist_changed())
            hi_s.valueChanged.connect(lambda _v: self._dist_changed())
            row.addWidget(cb, 1)
            row.addWidget(QLabel("from"))
            row.addWidget(lo_s)
            row.addWidget(QLabel("to"))
            row.addWidget(hi_s)
            if key == "blur":
                ch = self._spin(0.0, 1.0, 2)
                ch.valueChanged.connect(lambda _v: self._dist_changed())
                row.addWidget(QLabel("chance"))
                row.addWidget(ch)
                self.dist_spins["blur_chance"] = ch
            for wdg in (cb, lo_s, hi_s):
                wdg.setToolTip(HINTS[key])
            form.addRow(row)
            form.addRow(hint(key))
            self.dist_checks[key] = cb
            self.dist_spins[key] = (lo_s, hi_s)
        self.dist_count = QSpinBox()
        self.dist_count.setRange(1, 30)
        self.dist_count.valueChanged.connect(lambda _v: self._dist_changed())
        tip(self.dist_count, "count")
        form.addRow("Copies per training picture:", self.dist_count)
        form.addRow(hint("count"))
        dv.addWidget(self.dist_box)
        dv.addWidget(ui_kit.note("Copies are made when training starts (and again if you change these settings). Validation pictures are never distorted."))
        self.dist_note = QLabel("")                            # how much work the next start has: the copies still to make
        self.dist_note.setWordWrap(True)
        dv.addWidget(self.dist_note)
        btn = QPushButton("Delete the distorted copies")
        btn.clicked.connect(self.clear_distortions)
        dv.addWidget(btn)

        mv = section(3, "Model", None, lambda: f"{self.type_box.currentText()}, {self.epochs.value()} epochs")
        mf = QFormLayout()
        mv.addLayout(mf)
        self.type_box = QComboBox()
        self.type_box.currentIndexChanged.connect(lambda _i: self._type_changed())
        tip(self.type_box, "type")
        mf.addRow("Model type:", self.type_box)
        mf.addRow(hint("type"))
        self.size_box = QComboBox()
        self.size_box.currentIndexChanged.connect(lambda _i: self._model_changed())
        tip(self.size_box, "size")
        mf.addRow("Size:", self.size_box)
        mf.addRow(hint("size"))
        self.cont_on = QCheckBox("Continue from existing model")
        self.cont_on.toggled.connect(lambda _c: self._continue_changed())
        tip(self.cont_on, "continue")
        mf.addRow(self.cont_on)
        crow = QHBoxLayout()
        self.cont_box = QComboBox()
        self.cont_box.setMinimumWidth(240)
        self.cont_box.currentIndexChanged.connect(lambda _i: self._continue_changed())
        crow.addWidget(self.cont_box, 1)
        self.cont_browse = QPushButton("Browse...")
        self.cont_browse.clicked.connect(self.browse_model)
        crow.addWidget(self.cont_browse)
        self.cont_row = QWidget()
        self.cont_row.setLayout(crow)
        crow.setContentsMargins(0, 0, 0, 0)
        mf.addRow(self.cont_row)
        mf.addRow(hint("continue"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("(optional)")
        self.name_edit.textChanged.connect(lambda _t: self._model_changed())
        tip(self.name_edit, "name")
        mf.addRow("Model name:", self.name_edit)
        mf.addRow(hint("name"))
        self.epochs = QSpinBox()
        self.epochs.setRange(1, 5000)
        self.epochs.valueChanged.connect(lambda _v: self._model_changed())
        tip(self.epochs, "epochs")
        mf.addRow("Epochs:", self.epochs)
        mf.addRow(hint("epochs"))
        self.more = {}
        for key, label, lo, hi in (("patience", "Stop early after (epochs)", 1, 1000), ("batch", "Batch size", 1, 512),
                                   ("imgsz", "Picture size (pixels)", 64, 2048)):
            sp = QSpinBox()
            sp.setRange(lo, hi)
            sp.valueChanged.connect(lambda _v: self._model_changed())
            tip(sp, key)
            mf.addRow(label + ":", sp)
            mf.addRow(hint(key))
            self.more[key] = sp
        lv.addStretch(1)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        sc.setWidget(left)
        split.addWidget(sc)
        self.panel_scroll, self.panel = sc, left

        # ---- right: environment, run, log, models
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(8, 4, 2, 2)
        rv.addWidget(pane_head("Training Python"))
        prow = QHBoxLayout()
        self.py_box = QComboBox()
        self.py_box.setMinimumWidth(260)
        tip(self.py_box, "python")
        self.py_box.currentIndexChanged.connect(lambda _i: self._python_chosen())
        prow.addWidget(self.py_box, 1)
        for text, fn in (("Browse...", self.browse_python), ("Scan again", self.check_env)):
            b = QPushButton(text)
            b.clicked.connect(lambda _c=False, f=fn: f())
            prow.addWidget(b)
        rv.addLayout(prow)
        rv.addWidget(hint("python"))
        self.env_label = QLabel("Looking for a Python with torch, ultralytics and a GPU ...")
        self.env_label.setWordWrap(True)
        self.env_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        rv.addWidget(self.env_label)
        row = QHBoxLayout()
        rv.addSpacing(6)
        rv.addWidget(pane_head("Run"))
        self.btn_train = ui_kit.primary(QPushButton("Start training"))       # the action that moves the work on
        self.btn_train.setMinimumHeight(34)
        self.btn_train.setMinimumWidth(170)
        self.btn_train.clicked.connect(self.start)
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setMinimumHeight(34)
        self.btn_stop.clicked.connect(self.stop)
        self.btn_stop.setEnabled(False)
        for b in (self.btn_train, self.btn_stop):
            row.addWidget(b)
        row.addStretch(1)
        rv.addLayout(row)
        self.prep_bar = QProgressBar()                         # shown while a run is being prepared (before the training program starts)
        self.prep_bar.setTextVisible(True)
        self.prep_bar.setVisible(False)
        rv.addWidget(self.prep_bar)
        self.run_label = QLabel("")
        self.run_label.setWordWrap(True)
        rv.addWidget(self.run_label)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        self.log.setStyleSheet("font-family: Consolas, monospace;")
        rv.addWidget(self.log, 1)
        rv.addWidget(pane_head("Models trained in this project"))
        rv.addWidget(ui_kit.note("They are also offered in the Annotator's AI model box."))
        self.models_list = QListWidget()
        self.models_list.setMaximumHeight(110)
        rv.addWidget(self.models_list)
        split.addWidget(right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        ui_kit.fit_panel(split, sc, left, lo=480, hi=700)

        types = tc.model_types()
        for k, spec in types.items():
            self.type_box.addItem(spec["label"], k)

    @staticmethod
    def _spin(lo, hi, dec):
        s = QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setDecimals(dec)
        s.setSingleStep(0.1 if dec else 1)
        return s

    # ------------------------------------------------------------------ showing the project
    def refresh_all(self):
        self._loading = True
        try:
            st = self.tp.settings
            d, m = st["distortions"], st["model"]
            self.dist_on.setChecked(d["enabled"])
            for key, *_r in tc.DISTORTION_TYPES:
                self.dist_checks[key].setChecked(d["types"].get(key, True))
            ac_ranges = dict(self.ac.DEFAULT_DISTORTION_RANGES)
            for key, _l, rk, _lo, _hi, _dec, _n in tc.DISTORTION_TYPES:
                lo, hi = d["ranges"].get(key, ac_ranges[rk])
                self.dist_spins[key][0].setValue(lo)
                self.dist_spins[key][1].setValue(hi)
            self.dist_spins["blur_chance"].setValue(d.get("blur_chance", 0.5))
            self.dist_count.setValue(d["count"])
            self.dist_box.setEnabled(d["enabled"])
            i = self.type_box.findData(m["type"])
            self.type_box.setCurrentIndex(max(0, i))
            self._fill_sizes(m["size"])
            self.epochs.setValue(m["epochs"])
            for k, s in self.more.items():
                s.setValue(m[k])
            self._fill_continue(m.get("continue_from"))
            self.cont_on.setChecked(bool(m.get("continue_from")))
            self.name_edit.setText(m.get("name") or "")
            self._continue_enable()
        finally:
            self._loading = False
        self.refresh_data()
        self.refresh_models()
        self.setWindowTitle(self.title())

    def _fill_sizes(self, want=None):
        spec = tc.model_types().get(self.type_box.currentData() or "yolo", {})
        names = {"n": "Nano", "s": "Small", "m": "Medium", "l": "Large"}
        self.size_box.blockSignals(True)
        self.size_box.clear()
        for s in spec.get("sizes", ()):
            self.size_box.addItem(names.get(s, s), s)
        i = self.size_box.findData(want or spec.get("default_size"))
        self.size_box.setCurrentIndex(max(0, i))
        self.size_box.blockSignals(False)

    def refresh_bar(self):
        """The bar says which project this is, and the folded steps their one-line summary."""
        try:
            self.bar_lbl.setText(f"<b>{self.title()}</b>" if self.path else "A new project (not saved yet)")
            for sec in self.sections:
                sec.refresh_summary()
        except (AttributeError, RuntimeError):
            pass

    def refresh_data(self):
        was = self._loading
        self._loading = True
        try:
            data = self.tp.data
            self.sets_table.setRowCount(0)
            rows = self.tp.sets()
            self.sets_table.setRowCount(len(rows))
            for r, row in enumerate(rows):
                for c, v in enumerate((row["session_id"], row["samples"], row["annotated"])):
                    it = QTableWidgetItem(str(v))
                    it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.sets_table.setItem(r, c, it)
                box = QComboBox()
                box.addItem("Training", "train")
                box.addItem("Validation", "val")
                box.setCurrentIndex(1 if row["role"] == "val" else 0)
                box.currentIndexChanged.connect(lambda _i, sid=row["session_id"], b=box: self._role_changed(sid, b.currentData()))
                self.sets_table.setCellWidget(r, 3, box)
            sel = self._chosen_classes()
            saved = self.tp.settings["model"].get("classes")
            self.class_list.clear()
            for c in data.classes:
                it = QListWidgetItem(c)
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                on = (c in sel) if sel is not None else (saved is None or c in saved)
                it.setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
                self.class_list.addItem(it)
        finally:
            self._loading = was
        self._summary()

    def _chosen_classes(self):
        if self.class_list.count() == 0:
            return None
        return [self.class_list.item(i).text() for i in range(self.class_list.count()) if self.class_list.item(i).checkState() == Qt.CheckState.Checked]

    def _summary(self):
        chosen = self._chosen_classes()
        s = self.tp.summary(chosen)
        total = len(self.tp.annotated_ids())
        self._distort_pictures = s["distort_pictures"]
        self._dist_note()
        if not total:
            self.data_info.setText("No pictures yet. Import a dataset zip made by the Annotator (or another Trainer): Import dataset zip... above.")
            self.refresh_bar()
            return
        tr = ", ".join(f"{n}: {c}" for n, c in zip(s["classes"], s["boxes"]["train"]))
        va = ", ".join(f"{n}: {c}" for n, c in zip(s["classes"], s["boxes"]["val"]))
        warn = ""
        if s["val"] == 0:
            warn = "\nNo validation pictures: mark at least one set as Validation."
        elif s["train"] == 0:
            warn = "\nNo training pictures: keep at least one set as Training."
        dist = ""
        wants = bool(tc.model_types().get(self.type_box.currentData() or "yolo", {}).get("distance"))
        if wants or s["dist"]["train"] or s["dist"]["val"]:
            dist = f"\nBoxes with a distance - training: {s['dist']['train']}, validation: {s['dist']['val']}"
        if wants and not warn:
            if s["dist"]["train"] == 0:
                warn = ("\nNone of the training boxes has a distance, so a distance model cannot be trained from this data. "
                        "Pick distances in the Annotator (on pictures recorded with LiDAR), or choose a \"Classes + boxes\" model type.")
            elif s["dist"]["val"] == 0:
                warn = "\nNo validation box has a distance: the model still learns distance, but its distance error cannot be scored."
        self.data_info.setText(f"{s['train']} training and {s['val']} validation pictures.\nBoxes in training - {tr}\nBoxes in validation - {va}{dist}{warn}")
        self.refresh_bar()

    def refresh_models(self):
        self.models_list.clear()
        for v in self.tp.list_models():
            sc = v.get("scores") or {}
            kind = "classes + boxes + distance" if tc.is_distance_checkpoint(v["path"]) else "classes + boxes"
            self.models_list.addItem(f"{self.ml.mr.SIZE_NAMES.get(v['size'], '?')}   {kind}   {time.strftime('%Y-%m-%d %H:%M', time.localtime(v['ts']))}"
                                     + (f"   mAP50 {sc['map50']}" if "map50" in sc else "") + self.ml.distance_text(sc))

    # ------------------------------------------------------------------ settings changes
    def _role_changed(self, sid, role):
        if self._loading:
            return
        removed = self.tp.set_role(sid, role)
        self.refresh_data()
        if role == "val" and removed:
            self.status.setText(f"{removed} distorted copies of that set were removed.")

    def _classes_changed(self):
        if self._loading:
            return
        self.tp.set_settings({"model": {"classes": self._chosen_classes()}})
        self._summary()

    def _dist_changed(self):
        if self._loading:
            return
        ranges = {k: [self.dist_spins[k][0].value(), self.dist_spins[k][1].value()] for k, *_r in tc.DISTORTION_TYPES}
        self.dist_box.setEnabled(self.dist_on.isChecked())
        self.tp.set_settings({"distortions": {"enabled": self.dist_on.isChecked(), "count": self.dist_count.value(), "ranges": ranges,
                                              "blur_chance": self.dist_spins["blur_chance"].value(),
                                              "types": {k: c.isChecked() for k, c in self.dist_checks.items()}}})
        self._dist_note()

    def _dist_note(self):
        """Says what the next start has to make, so a long wait is known before Start training is pressed."""
        p = self.tp.distortion_plan(self._distort_pictures)
        if not p["enabled"] or not p["pictures"]:
            self.dist_note.setText("")
        elif p["to_make"] == 0:
            self.dist_note.setText(f"All {p['pictures'] * p['count']:,} copies are made ({p['pictures']:,} training pictures x {p['count']}). "
                                   "The next training starts without making any.")
        else:
            some = f" {p['ready']:,} pictures already have theirs." if p["ready"] else ""
            self.dist_note.setText(f"The next training first makes {p['to_make']:,} copies ({p['pictures'] - p['ready']:,} training pictures x {p['count']}).{some} "
                                   "That can take minutes; it shows its progress and can be cancelled, and it is only done once.")

    def _type_changed(self):
        if self._loading:
            return
        self._fill_sizes()
        self._model_changed()
        self._summary()

    def _model_changed(self):
        if self._loading:
            return
        m = {"type": self.type_box.currentData(), "size": self.size_box.currentData(), "epochs": self.epochs.value(),
             "name": self.name_edit.text().strip(), "continue_from": self.cont_box.currentData() if self.cont_on.isChecked() else None}
        m.update({k: s.value() for k, s in self.more.items()})
        self.tp.set_settings({"model": m})
        self._update_env_view()

    def _fill_continue(self, want=None):
        was = self._loading
        self._loading = True
        self.cont_box.clear()
        seen = set()
        for label, d in (("this project", self.tp.models_dir), ("annotator", tc.annotator_models_dir())):
            for key in self.ml.FOLDERS:
                for v in self.ml.list_versions(d, key):
                    if v["path"] not in seen:
                        seen.add(v["path"])
                        kind = ", with distance" if tc.is_distance_checkpoint(v["path"]) else ""
                        self.cont_box.addItem(f"{v['file'][:-3]}   ({label}{kind})", v["path"])
        if want and want not in seen:
            self.cont_box.addItem(os.path.basename(want), want)
        i = self.cont_box.findData(want) if want else -1
        self.cont_box.setCurrentIndex(i if i >= 0 else (0 if self.cont_box.count() else -1))
        self._loading = was

    def _continue_enable(self):
        on = self.cont_on.isChecked()
        self.cont_row.setEnabled(on)
        self.size_box.setEnabled(not on)
        self.type_box.setEnabled(not on)

    def _continue_changed(self):
        self._continue_enable()
        self._type_follows_model()
        self._model_changed()

    def _type_follows_model(self):
        """A model is continued as the kind it is: choosing a distance model switches the type to a distance type, and the other way round."""
        path = self.cont_box.currentData() if self.cont_on.isChecked() else None
        cur = self.type_box.currentData()
        spec = tc.model_types().get(cur or "", {})
        if self._loading or not path or not os.path.isfile(path) or spec.get("script") not in (tc.HELPER_SCRIPT, tc.DISTANCE_SCRIPT):
            return
        want = tc.type_for_checkpoint(path, cur)
        if want != cur:
            self._loading = True
            try:
                self.type_box.setCurrentIndex(max(0, self.type_box.findData(want)))
                self._fill_sizes()
            finally:
                self._loading = False
            self._summary()

    def browse_model(self):
        path, _ = QFileDialog.getOpenFileName(self, "Model to continue from", "", "Model (*.pt)")
        if path:
            path = os.path.normpath(path)
            self._fill_continue(path)
            self.cont_on.setChecked(True)
            self._type_follows_model()
            self._model_changed()

    def clear_distortions(self):
        if self.preparing() or self.running():
            QMessageBox.information(self, "Distorted copies", "Wait for the training to finish (or stop it) first.")
            return
        if QMessageBox.question(self, "Distorted copies", "Delete all distorted copies? They are made again when the next training starts.") \
                == QMessageBox.StandardButton.Yes:
            self.tp.clear_distortions()
            self.tp.meta.pop("distortion_sig", None)
            self.tp.save()
            self.status.setText("Distorted copies deleted.")
            self._dist_note()

    def _ensure_me(self):
        if not self.me:
            self.me = tc.default_me()
        return self.me

    # ------------------------------------------------------------------ import (in the background)
    def _bg_run(self, work, done, text):
        """work() runs in a thread; done(result) / failure message run in the window's thread."""
        self._bg = True
        self.status.setText(text)

        def run():
            try:
                res = work()
            except Exception as e:  # noqa: BLE001
                err = e
                self.post(lambda: self._bg_failed(err))
                return
            self.post(lambda: done(res))
        threading.Thread(target=run, daemon=True).start()

    def _bg_failed(self, err):
        self._bg = False
        self.status.setText("")
        QMessageBox.critical(self, "Trainer", f"That did not work:\n\n{err}")

    def _progress(self, label):
        return lambda d, t: self.post(lambda: self.status.setText(f"{label}: {d}/{t}"))

    def import_zip(self):
        if self._bg:
            return
        paths, _ = QFileDialog.getOpenFileNames(self, "Import dataset zip(s) (made by the annotator or a Trainer)", "", "Dataset zip (*.zip)")
        me = self._ensure_me() if paths else None
        if not me:
            return
        queue = list(paths)
        report = []

        def next_zip():
            if not queue:
                self._bg = False
                self._imports_done(report)
                return
            z = queue.pop(0)
            self._bg_run(lambda: self.tp.plan_import(z, me, self._progress("Reading " + os.path.basename(z))),
                         lambda plan: self._planned(plan, me, report, next_zip), f"Reading {os.path.basename(z)} ...")
        next_zip()

    def _planned(self, plan, me, report, nxt):
        self._bg = False
        choices = None                                           # None = whoever edited last wins
        n = len(plan["conflicts"])
        if n:
            box = QMessageBox(self)
            box.setWindowTitle("Same pictures, annotated differently")
            box.setText(f"{n} picture(s) in {os.path.basename(plan['_zip'])} are annotated differently from your copy.\n\nWhich version should be kept?")
            mine = box.addButton("Keep mine", QMessageBox.ButtonRole.AcceptRole)
            theirs = box.addButton("Take the zip's", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("Newest edit wins", QMessageBox.ButtonRole.AcceptRole)
            cancel = box.addButton("Skip this zip", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            clicked = box.clickedButton()
            if clicked is cancel or clicked is None:
                self.tp.discard_plan(plan)
                self.status.setText("")
                nxt()
                return
            if clicked is mine:
                choices = {c["uid"]: "mine" for c in plan["conflicts"]}
            elif clicked is theirs:
                choices = {c["uid"]: "theirs" for c in plan["conflicts"]}

        def done(res):
            self._bg = False
            report.append((os.path.basename(plan["_zip"]), res))
            nxt()
        self._bg_run(lambda: self.tp.apply_import(plan, choices, me, self._progress("Importing")), done, "Importing ...")

    def _imports_done(self, report):
        self.status.setText("")
        self.refresh_data()
        if report:
            lines = []
            for name, r in report:
                bits = [f"{r['new']} new" if r["new"] else "", f"{r['updated']} updated" if r["updated"] else "",
                        f"{r['duplicates']} already there" if r["duplicates"] else "",
                        f"classes added: {', '.join(r['added_classes'])}" if r["added_classes"] else ""]
                lines.append(f"{name}: " + (", ".join(b for b in bits if b) or "nothing new"))
            QMessageBox.information(self, "Import finished", "\n".join(lines) + "\n\nMark which sets are Validation before you train.")

    # ------------------------------------------------------------------ training
    def check_env(self):
        """Looks for Pythons with torch / ultralytics (in the background) and offers them in the Training Python box."""
        self.env_label.setText("Looking for a Python with torch, ultralytics and a GPU ... (this takes a few seconds)")
        saved = self.tp.settings.get("python")

        def run():
            paths = tc.find_pythons()
            if saved and saved not in paths:
                paths.insert(0, saved)
            infos = tc.probe_all(paths) if paths else []
            self.post(lambda: self._pythons_found(infos, saved))
        threading.Thread(target=run, daemon=True).start()

    def _pythons_found(self, infos, saved):
        self._infos = {i["python"]: i for i in infos}
        was = self._loading
        self._loading = True
        self.py_box.clear()
        for i in infos:
            what = (f"torch {i['torch']}" + (f", GPU {i['gpu']}" if i["cuda"] else ", no GPU")) if i["torch"] else "no torch"
            self.py_box.addItem(f"{i['python']}   ({what}{'' if i['ultralytics'] else ', no ultralytics'})", i["python"])
        want = saved if saved in self._infos else (infos[0]["python"] if infos else None)
        if want:
            self.py_box.setCurrentIndex(self.py_box.findData(want))
        self._loading = was
        self._python_chosen(save=bool(saved) and want == saved)

    def _python_chosen(self, save=True):
        if self._loading:
            return
        p = self.py_box.currentData()
        self.env = getattr(self, "_infos", {}).get(p)
        if p and save:
            self.tp.set_settings({"python": p})
        self._update_env_view()

    def browse_python(self):
        path, _ = QFileDialog.getOpenFileName(self, "Python to train with (python.exe)", "", "Python (python.exe python python3);;All files (*)")
        if not path:
            return
        path = os.path.normpath(path)
        self.env_label.setText("Checking that Python ...")

        def run():
            info = tc.check_env(path)
            self.post(lambda: self._added_python(info))
        threading.Thread(target=run, daemon=True).start()

    def _added_python(self, info):
        infos = dict(getattr(self, "_infos", {}))
        infos[info["python"]] = info
        self.tp.set_settings({"python": info["python"]})
        self._pythons_found(list(infos.values()), info["python"])

    def _update_env_view(self):
        if self.env is None:
            if not self.py_box.count():
                self.env_label.setText("No Python was found. Use Browse... to pick the python.exe that has torch and ultralytics.")
            return
        text = tc.env_text(self.env)
        if self.env["problems"]:
            self.env_label.setStyleSheet("color: #b00020;")
            text = "Training is not possible with this Python yet:\n" + text
        elif self.env["warnings"]:
            self.env_label.setStyleSheet("color: #b36b00;")
        else:
            self.env_label.setStyleSheet("")
        self.env_label.setText(text)
        self.btn_train.setEnabled(not self.running() and not self.preparing())

    def start(self):
        """Prepares the run in a background thread (the distorted copies and the run's copy of the data can take minutes), showing what
        it is doing; the window stays usable and Cancel ends it.  Then the training program starts."""
        if self.running() or self._bg or self.preparing():
            return
        if self.env is None or self.env["problems"]:
            QMessageBox.warning(self, "Training", tc.env_text(self.env) if self.env else "No usable Python yet. Wait for the scan to finish, or use Browse... to pick one.")
            return
        me = self._ensure_me()
        if not me:
            return
        self._model_changed()
        prep = self._prep = {"stop": False, "stage": "", "done": 0, "total": 0, "t0": time.time(), "stage_t0": time.time(), "first": None,
                             "finished": [], "count": int(self.tp.settings["distortions"]["count"])}
        python = self.env["python"]

        def progress(stage, done, total):                      # called from the thread: only notes the numbers, _tick shows them
            if stage != prep["stage"]:
                if prep["total"]:                              # the stage that just ended, for a line in the log
                    prep["finished"].append((prep["stage"], prep["total"], time.time() - prep["stage_t0"]))
                prep.update(stage=stage, stage_t0=time.time(), first=None, done=0, total=0)
            if prep["first"] is None and total:
                prep["first"] = done                           # where this stage began (copies made by an earlier start are not timed)
            prep["done"], prep["total"] = done, total

        def run():
            try:
                job = self.tp.start_run(me["name"], progress_cb=progress, python=python, stop=lambda: prep["stop"])
            except BaseException as e:  # noqa: BLE001
                err = e
                self.post(lambda: self._prep_failed(prep, err))
                return
            self.post(lambda: self._prep_done(prep, job))

        self.log.clear()
        self.log.appendPlainText("Preparing the training data ...")
        self._prep_view(True)
        self._prep_show()
        threading.Thread(target=run, daemon=True).start()

    def _prep_view(self, on):
        """The window while a run is being prepared: the left panel and the bar's commands wait, Stop is Cancel, the bar shows."""
        self.panel.setEnabled(not on)
        for b in self.bar_buttons:
            b.setEnabled(not on)
        self.py_box.setEnabled(not on)
        self.btn_train.setEnabled(not on and not self.running())
        self.btn_stop.setText("Cancel" if on else "Stop")
        self.btn_stop.setEnabled(on or self.running())
        self.prep_bar.setVisible(on)

    @staticmethod
    def _dur(secs):
        secs = int(round(secs))
        return f"{secs} s" if secs < 60 else f"{secs // 60} min {secs % 60:02d} s" if secs < 3600 else f"{secs // 3600} h {secs % 3600 // 60:02d} min"

    def _prep_text(self, p):
        """(text, done, total) for the stage the preparation is in; total 0 = no count to show."""
        stage, done, total = p["stage"], p["done"], p["total"]
        if stage == "model":
            return "Reading the model to continue from ...", 0, 0
        if stage == "distortions":
            if not total:
                return "Looking which training pictures still need distorted copies ...", 0, 0
            text = f"Making distorted copies: {done:,} of {total:,} training pictures ({p['count']} copies each)"
            made, secs = done - (p["first"] or 0), time.time() - p["stage_t0"]
            if made >= 5 and secs >= 3 and done < total:
                text += f" - about {self._dur((total - done) * secs / made)} left"
            return text, done, total
        if stage == "copy":
            return (f"Putting the run's copy of the data together: {done:,} of {total:,} pictures" if total
                    else "Putting the run's copy of the data together ..."), done, total
        if stage == "start":
            return "Starting the training program ...", 0, 0
        return "Preparing the training data ...", 0, 0

    def _prep_show(self):
        p = self._prep
        if p is None:
            return
        text, done, total = self._prep_text(p)
        if p["stop"]:
            text = "Cancelling ..."
        self._prep_log(p)
        self.prep_bar.setRange(0, total if total else 0)       # 0, 0 = a moving bar: busy, nothing to count
        if total:
            self.prep_bar.setValue(done)
            self.prep_bar.setFormat(f"{done * 100 // total}%")
        self.run_label.setText(text)

    def _prep_log(self, p):
        """A line in the log for every stage that has ended since the last look."""
        while p["finished"]:
            stage, total, secs = p["finished"].pop(0)
            if stage == "distortions":
                self.log.appendPlainText(f"Distorted copies ready for {total:,} training pictures ({self._dur(secs)}).")
            elif stage == "copy":
                self.log.appendPlainText(f"The run's copy of the data is ready: {total:,} pictures ({self._dur(secs)}).")

    def _prep_end(self, prep):
        if self._prep is not prep:
            return False
        self._prep = None
        if self._closed:
            return False
        self._prep_view(False)
        self._dist_note()
        return True

    def _prep_done(self, prep, job):
        if not self._prep_end(prep):
            job.stop()                                         # the tab was closed meanwhile
            return
        self._prep_log(prep)
        self.job = job
        self.btn_train.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.run_label.setText(f"Training ... ({os.path.basename(job.run_dir)})")
        self.log.appendPlainText(f"Prepared in {self._dur(time.time() - prep['t0'])}. The training program is starting "
                                 "(loading PyTorch takes a moment before its first lines appear).\n")

    def _prep_failed(self, prep, err):
        if not self._prep_end(prep):
            return
        if isinstance(err, tc.Cancelled):
            self.run_label.setText("Cancelled before training started. Distorted copies that were made are kept, so the next start goes on from there.")
            self.log.appendPlainText("Cancelled.")
            return
        self.run_label.setText("Training did not start.")
        self.log.appendPlainText(f"Training did not start: {err}")
        if isinstance(err, ValueError):
            QMessageBox.warning(self, "Training", str(err))
        else:
            QMessageBox.critical(self, "Training", f"Could not start training:\n\n{err}")

    def stop(self):
        if self.preparing():
            self._prep["stop"] = True
            self.btn_stop.setEnabled(False)
            self._prep_show()
        elif self.running():
            self.job.stop()

    def _tick(self):
        if self._prep is not None:
            self._prep_show()
        if self.job is None:
            return
        text = self.job.read_log()
        if text:
            self.log.appendPlainText(text.rstrip("\n"))
        code = self.job.poll()
        if code is None:
            return
        job, self.job = self.job, None
        text = job.read_log()
        if text:
            self.log.appendPlainText(text.rstrip("\n"))
        self.btn_stop.setEnabled(False)
        self.btn_train.setEnabled(True)
        res = job.result()
        if job.stopped:
            self.run_label.setText("Stopped. Nothing was saved from this run.")
        elif res and res.get("ok"):
            self.run_label.setText("Finished. The new model is saved and the annotator lists it.")
            self.refresh_models()
            self._tell_annotators()
        else:
            self.run_label.setText("Training did not finish - see the log. Nothing was saved from this run.")

    def _tell_annotators(self):
        tabs = getattr(self.host, "tabs", None)
        if tabs is None:
            return
        for i in range(tabs.count()):
            w = tabs.widget(i)
            fn = getattr(w, "_models_changed", None)
            if callable(fn):
                try:
                    fn()
                except Exception:  # noqa: BLE001
                    pass
