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

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                             QProgressBar,
                             QListWidget,
                             QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QSplitter, QStackedWidget, QTableWidget,
                             QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import chart_data as cd  # noqa: E402
import trainer_charts as tch  # noqa: E402
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
    "type": "Distance only: no boxes are found. The model is told a box (where it is and how big) and answers how far away it is. A formula and four regressors "
            "(k / height, log-linear, nearest neighbours, gradient boosting, Gaussian process), or a small neural network on a ladder of recipes from 1986 to today. "
            "They train in seconds to minutes on the processor, need no torch, and are kept in this project (the Annotator cannot use them: it needs a detector).\n\n"
            "Classes + boxes: a YOLO model that finds objects and says what they are. "
            "Classes + boxes + distance: two models trained one after the other. First that same YOLO model; then a separate, small distance "
            "model that is told a box and its class and answers how far away it is, in metres. It learns that from the LiDAR distances picked on "
            "boxes in the Annotator. Each is scored by itself, then both together, and they are saved as one model (the kind the Gimble uses to "
            "show distance). Every model starts from random weights: nothing pretrained is used, so it needs many pictures and epochs.",
    "size": "Bigger models can be more accurate but are slower to train and run, and need more GPU memory. n = nano (smallest), s = small, m = medium, l = large.\n"
            "For a distance-only model this chooses what is trained: which of the formula and regressors, or which rung of the ladder of network recipes.",
    "seeds": "How many times each network is trained from different random weights. 1 is a quick look; 5 shows how much of a result is luck, and is what a claim should rest on.",
    "lrs": "The learning rate is the size of each step. Default: the one the rung starts with. The grid: eight rates (five for Adam) from very small to very large, which shows "
           "which rates work and which make the training blow up. The one with the best median error is kept.",
    "epochs": "One epoch is one pass over all the training pictures. More epochs train longer; it usually helps until the validation score stops improving.",
    "patience": "Training ends early when the validation score has not improved for this many epochs.",
    "batch": "How many pictures the GPU handles at once. Higher is faster but needs more GPU memory. If training runs out of memory, lower it.",
    "imgsz": "Every picture is resized to this many pixels wide before training. Bigger sizes find small objects better but need more GPU memory and time. 640 is the usual choice.",
    "continue": "Train further from a model you already made (here or in the annotator's models, or a .pt file). It keeps its size and must "
                "know the same classes you have ticked. A Classes + boxes model can also get a distance model on top: choose the "
                "Classes + boxes + distance type.",
    "dist_only": "Ticked: the detector of the model you continue from is used exactly as it is, and only the distance model is trained "
                 "(a new one, or the model's own trained further). This is quick, and the detector's scores do not change. "
                 "Unticked: the detector is trained further first, then the distance model.",
    "name": "Optional name for the finished model. It is shown in the annotator's AI model box with the size and date. Left empty, it is named after you.",
    "layers": "The layers of the network: the six numbers of a box go in, each hidden layer has the neurons you type (the blue numbers), and one number, the distance, comes out. "
              "Parameters are the weights and biases (and, with batch norm, the scale and shift of every hidden layer).",
    "net_loss": "How a wrong answer is scored while training. Mean squared error punishes big misses hardest; smooth L1 (beta 0.1) treats big misses gently.",
    "net_opt": "How the weights change after each batch. Plain: a step against the gradient. With momentum: part of the last step is kept. Adam: a step size for every weight. "
               "AdamW: Adam with the weight decay done on its own.",
    "net_lr": "The size of each step. The Train tab can try a whole grid of rates instead of this one.",
    "net_mom": "How much of the last step is kept (0 to 0.99). Only with the momentum optimiser.",
    "net_wd": "Pulls the weights a little towards zero at every step, so the network does not fit noise. 0 is off.",
    "net_act": "What each hidden unit does with its sum: sigmoid and tanh squash it, ReLU cuts everything below zero, SiLU is a smooth ReLU.",
    "net_init": "How the weights start: a small uniform range (the 1986 way), Glorot (keeps the signal's spread level for sigmoid and tanh) or He (for ReLU).",
    "net_target": "What the network is asked to answer: the distance divided by 20 metres, or the standardised natural logarithm of the distance (a miss then counts as a ratio).",
    "net_patience": "Training ends early when the validation error has not improved for this many epochs, and the weights of the best epoch are kept. Never = it runs all its epochs.",
    "net_batch": "How many boxes are used for each step of the weights.",
    "net_bn": "Batch normalisation: the numbers of each hidden layer are re-centred and re-scaled over the batch before the activation.",
    "cl_folds": "The k nearest neighbours and gradient boosting choose their settings by cross-validation, in folds that keep a recording whole.",
    "cl_width": "The log-linear regression normally uses the height of the box; ticked, it uses the width too.",
    "cl_blr": "Gradient boosting tries each of these learning rates (separated by commas) and keeps the one that cross-validates best.",
    "cl_bdepth": "Gradient boosting tries each of these tree depths (separated by commas) and keeps the one that cross-validates best.",
    "cl_biter": "The most boosting rounds (trees) gradient boosting may use.",
    "cl_gprows": "The Gaussian process gets slow with many boxes: it is fitted on at most this many (a random choice of the training boxes).",
    "cl_gprest": "How many times the Gaussian process restarts its search for its settings.",
    "python": "The Python that runs the training. It needs torch (the CUDA build, for your GPU) and ultralytics. "
              "When OpenPara's own Python is the one chosen and it has neither, OpenPara can download them for you.",
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


class Num(QLineEdit):
    """A number box: right-aligned, shows the number as short as it can ("0.001"), and says (changed) when a new one was typed."""
    changed = pyqtSignal()

    def __init__(self, value=0.0, lo=0.0, hi=1e9):
        super().__init__()
        self.lo, self.hi, self._v = lo, hi, float(value)
        self.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.setValue(value)
        self.editingFinished.connect(self._done)

    def value(self):
        return self._v

    def setValue(self, v):
        self._v = min(self.hi, max(self.lo, float(v)))
        self.setText(f"{self._v:g}")

    def _done(self):
        try:
            v = float(self.text().replace(",", "."))
        except ValueError:
            v = self._v
        old = self._v
        self.setValue(v)
        if self._v != old:
            self.changed.emit()


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
        self.setAcceptDrops(True)                              # model files (.pt) dropped on the window are imported
        self.job = None
        self.env = None
        self._bg = False
        self._pkg = None                                       # while torch / ultralytics are being downloaded: {'stop', 't0', 'text'}
        self._offered = False                                  # the download was offered once on its own (the button stays)
        self._prep = None                                      # while a run is being prepared: {'stop', 'stage', 'done', 'total', 't0', ...}
        self._closed = False
        self._distort_pictures = 0
        self._loading = False
        self.workbench_block = None                            # set by the Workbench block that opened this window (set_workbench_block)
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
        if self._pkg:
            r = QMessageBox.question(self, "Download running", "torch and ultralytics are still being downloaded. Closing this tab cancels the download.\n\nCancel it and close?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if r != QMessageBox.StandardButton.Yes:
                return False
            self._pkg["stop"] = True
        if self._bg:
            QMessageBox.information(self, "Please wait", "An import or export is still running. Close the tab when it has finished.")
            return False
        return True

    def shutdown(self):
        self.timer.stop()
        self._closed = True
        if self._prep:
            self._prep["stop"] = True                          # the preparation thread ends at its next picture
        if self._pkg:
            self._pkg["stop"] = True                           # so does the download
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
    KIND_BUTTONS = {                                       # model type -> ribbon text, icon, what it is
        "yolo": ("Detector", "trn_detector", "Classes + boxes: a YOLO model that finds objects in a picture and says what they are."),
        "yolo_distance": ("Detector +\ndistance", "trn_detector_dist", "Classes + boxes + distance: that detector, then a separate model that says how far each box is."),
        "classical_regress": ("Distance:\nclassic", "trn_dist_classic", "Distance only: the formula k / height and four regressors; they train in seconds on the processor."),
        "nn_ladder": ("Distance:\nnetwork", "trn_dist_network", "Distance only: a small neural network, on a ladder of recipes from 1986 to today."),
    }
    ABOUT = {
        "yolo": "Classes + boxes.\n\nA YOLO model that finds objects in a picture and says what they are. It starts from random weights: nothing pretrained is used, so it needs many "
                "pictures and epochs.\n\nChoose its size and the number of epochs on the left. To train further from a model you already made, tick Continue from existing model.",
        "yolo_distance": "Classes + boxes + distance.\n\nTwo models trained one after the other. First that same YOLO model; then a separate, small distance model that is told a box and "
                         "its class and answers how far away it is, in metres. It learns that from the LiDAR distances picked on boxes in the Annotator.\n\nEach is scored by itself, "
                         "then both together, and they are saved as one model (the kind the Gimble uses to show distance).",
        "classical_regress": "Distance only: classic.\n\nNo boxes are found. The model is told a box (where it is and how big) and answers how far away it is. The formula k / height, a "
                             "log-linear regression, k nearest neighbours, gradient boosting and a Gaussian process.\n\nThey train in seconds to minutes on the processor, need no torch, "
                             "and are kept in this project. Choose one on the left, or all five to compare them.",
    }

    def _build(self):
        import annotator_ribbon as rib                      # the Annotator's ribbon: tabs of big buttons, as in the Part window
        self._rib = rib
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.ribbon = rib.Ribbon()
        outer.addWidget(self.ribbon)
        self.pages = QStackedWidget()                        # one page for each ribbon tab: Data, Model, Train, Setup
        outer.addWidget(self.pages, 1)
        foot = QWidget()                                     # the status bar: the project and where its data comes from, what is going on, what the page is about
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(8, 2, 8, 2)
        self.foot_lbl = QLabel("")
        self.foot_lbl.setStyleSheet(f"color:{ui_kit.MUTED};")
        self.status = QLabel("")
        self.status.setStyleSheet(f"color:{ui_kit.WARN};")
        self.foot_info = QLabel("")
        self.foot_info.setStyleSheet(f"color:{ui_kit.MUTED};")
        fl.addWidget(self.foot_lbl)
        fl.addWidget(self.status, 1)
        fl.addWidget(self.foot_info)
        outer.addWidget(foot)
        self._rows = []                                      # the Model page's rows: (kinds it is for, label, field)
        self._kind_buttons = {}
        self._start_buttons, self._stop_buttons = [], []
        self._own_lrs = []
        self.net_hidden = [32, 32]
        self.type_box = QComboBox(self)                      # the kind of model is held by this box; the ribbon's kind buttons set it (it is never shown)
        self.type_box.hide()
        for k, spec in tc.model_types().items():
            self.type_box.addItem(spec["label"], k)
        self.type_box.currentIndexChanged.connect(lambda _i: self._sync_kind_buttons())
        self.type_box.currentIndexChanged.connect(lambda _i: self._type_changed())
        self.data_page = self._build_data_page()
        self.model_page = self._build_model_page()
        self.train_page = self._build_train_page()
        self.setup_page = self._build_setup_page()
        for p in (self.data_page, self.model_page, self.train_page, self.setup_page):
            self.pages.addWidget(p)
        self.panel_pages = [self.data_page, self.model_page]  # what waits while a run is being prepared
        self._build_ribbon()
        self.ribbon.currentChanged.connect(self._on_ribbon_tab)
        self._live_reset()

    def _pane(self, head=None):
        """A bordered panel with a small heading, as on the boards; returns it and its layout."""
        f = QFrame()
        f.setObjectName("pane")
        f.setStyleSheet(f"QFrame#pane{{border:1px solid {ui_kit.LINE};}}")
        v = QVBoxLayout(f)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(6)
        if head:
            v.addWidget(pane_head(head))
        return f, v

    @staticmethod
    def _scrolled(layout_owner_margins=(0, 0, 0, 0)):
        """A scroll area with a widget in it; returns (area, the widget's layout)."""
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        iv = QVBoxLayout(inner)
        iv.setContentsMargins(*layout_owner_margins)
        iv.setSpacing(6)
        sc.setWidget(inner)
        return sc, iv

    # ---- Data: the sets and the classes, and the distortions
    def _build_data_page(self):
        page = QWidget()
        h = QHBoxLayout(page)
        h.setContentsMargins(6, 6, 6, 4)
        h.setSpacing(6)
        left, gv = self._pane("Data")
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
        gv.addWidget(self.sets_table, 1)
        gv.addWidget(ui_kit.note("A set marked Validation is never trained on: it is only used for the scores, so they say how the model does on pictures it has not seen."))
        self.data_info = QLabel("")
        self.data_info.setWordWrap(True)
        gv.addWidget(self.data_info)
        gv.addWidget(pane_head("Classes to train on"))
        self.class_list = QListWidget()
        self.class_list.setMaximumHeight(130)
        self.class_list.itemChanged.connect(lambda _i: self._classes_changed())
        gv.addWidget(self.class_list)
        right, rv = self._pane("Distortions")
        sc, dv = self._scrolled()
        rv.addWidget(sc, 1)
        dv.addWidget(ui_kit.note("Extra, slightly changed copies of the training pictures (lighter, blurred, noisy ...), so the model copes with pictures that are not perfect."))
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
        dv.addStretch(1)
        h.addWidget(left, 1)
        h.addWidget(right, 1)
        return page

    # ---- Model: what is trained (the kind is chosen in the ribbon)
    def _build_model_page(self):
        page = QWidget()
        lay = QHBoxLayout(page)
        lay.setContentsMargins(6, 6, 6, 4)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        lay.addWidget(split)
        left, lv = self._pane()
        sc, iv = self._scrolled()
        lv.addWidget(sc, 1)
        # the layers of a network
        self.layers_box = QWidget()
        lb = QVBoxLayout(self.layers_box)
        lb.setContentsMargins(0, 0, 0, 0)
        lb.setSpacing(4)
        hrow = QHBoxLayout()
        hrow.addWidget(pane_head("Layers"))
        hrow.addStretch(1)
        self.layer_add, self.layer_del = QPushButton("+ layer"), QPushButton("- layer")
        for b, t in ((self.layer_add, "Adds a hidden layer (as wide as the last one)."), (self.layer_del, "Takes the last hidden layer away (one stays).")):
            b.setToolTip(t)
            hrow.addWidget(b)
        self.layer_add.clicked.connect(lambda _c=False: self._layer_add())
        self.layer_del.clicked.connect(lambda _c=False: self._layer_del())
        lb.addLayout(hrow)
        self.layers_table = QTableWidget(0, 4)
        self.layers_table.setHorizontalHeaderLabels(["Layer", "Neurons", "Activation", "Parameters"])
        hh = self.layers_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in (1, 2, 3):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self.layers_table.verticalHeader().setVisible(False)
        self.layers_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.layers_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        tip(self.layers_table, "layers")
        lb.addWidget(self.layers_table)
        iv.addWidget(self.layers_box)
        self.learn_head = pane_head("Settings")
        iv.addWidget(self.learn_head)
        mf = self.model_form = QFormLayout()
        mf.setVerticalSpacing(6)
        iv.addLayout(mf)

        def row(kinds, label, field, key=None):
            lab = None
            if label is None:
                mf.addRow(field)
            else:
                lab = label if isinstance(label, QLabel) else QLabel(label)
                mf.addRow(lab, field)
            if key:
                tip(field, key)
                if lab is not None:
                    lab.setToolTip(HINTS[key])
            self._rows.append((kinds, lab, field))
            return lab

        ALL, YOLO, NET, CLS = ("yolo", "net", "classic"), ("yolo",), ("net",), ("classic",)
        self.size_box = QComboBox()
        self.size_box.currentIndexChanged.connect(lambda _i: self._size_changed())
        self.size_label = row(ALL, "Size", self.size_box, "size")
        # -- the network
        self.net_loss = self._combo((("Mean squared error", "mse"), ("Smooth L1 (beta 0.1)", "smooth_l1")), "net_loss")
        row(NET, "Loss", self.net_loss)
        self.net_opt = self._combo((("Plain gradient descent", "plain"), ("With momentum", "momentum"), ("Adam", "adam"), ("AdamW", "adamw")), "net_opt")
        row(NET, "Optimiser", self.net_opt)
        self.net_lr = Num(0.001, 1e-7, 10.0)
        self.net_lr.changed.connect(self._net_changed)
        row(NET, "Learning rate", self.net_lr, "net_lr")
        self.net_mom = Num(0.9, 0.0, 0.999)
        self.net_mom.changed.connect(self._net_changed)
        row(NET, "Momentum", self.net_mom, "net_mom")
        self.net_wd = Num(0.0, 0.0, 1.0)
        self.net_wd.changed.connect(self._net_changed)
        row(NET, "Weight decay", self.net_wd, "net_wd")
        self.net_act = self._combo((("Sigmoid", "sigmoid"), ("tanh", "tanh"), ("ReLU", "relu"), ("SiLU", "silu")), "net_act")
        row(NET, "Activation", self.net_act)
        self.net_init = self._combo((("Uniform (-0.1, 0.1)", "uniform"), ("Glorot", "glorot"), ("He", "he")), "net_init")
        row(NET, "Initialisation", self.net_init)
        self.net_target = self._combo((("Distance / 20", "d20"), ("Standardised ln distance", "log_std")), "net_target")
        row(NET, "Target", self.net_target)
        # -- the classic regressors
        self.cl_folds = self._spinbox(2, 10, 5, "cl_folds")
        row(CLS, "Cross-validation folds", self.cl_folds)
        self.cl_width = QCheckBox("Log-linear: use the box width too")
        self.cl_width.toggled.connect(lambda _c: self._model_changed())
        row(CLS, None, self.cl_width, "cl_width")
        self.cl_blr = QLineEdit("0.03, 0.1")
        self.cl_blr.editingFinished.connect(self._model_changed)
        row(CLS, "Boosting learning rates", self.cl_blr, "cl_blr")
        self.cl_bdepth = QLineEdit("2, 3, 4")
        self.cl_bdepth.editingFinished.connect(self._model_changed)
        row(CLS, "Boosting depths", self.cl_bdepth, "cl_bdepth")
        self.cl_biter = self._spinbox(10, 5000, 500, "cl_biter")
        row(CLS, "Boosting rounds (at most)", self.cl_biter)
        self.cl_gprows = self._spinbox(100, 100000, 6000, "cl_gprows")
        row(CLS, "Gaussian process: most boxes", self.cl_gprows)
        self.cl_gprest = self._spinbox(0, 20, 2, "cl_gprest")
        row(CLS, "Gaussian process: restarts", self.cl_gprest)
        # -- what every trained kind has
        self.epochs = QSpinBox()
        self.epochs.setRange(1, 5000)
        self.epochs.valueChanged.connect(lambda _v: self._model_changed())
        self.epochs.setAlignment(Qt.AlignmentFlag.AlignRight)
        row(("yolo", "net"), "Epochs", self.epochs, "epochs")
        self.net_patience = self._spinbox(0, 1000, 50, "net_patience", net=True)
        self.net_patience.setSpecialValueText("never")
        row(NET, "Stop early after", self.net_patience)
        self.more = {}
        for key, label, lo, hi in (("patience", "Stop early after", 1, 1000), ("batch", "Batch size", 1, 512), ("imgsz", "Picture size (pixels)", 64, 2048)):
            sp = self._spinbox(lo, hi, lo, key)
            self.more[key] = sp
            row(YOLO, label, sp)
        self.net_batch = self._spinbox(1, 4096, 32, "net_batch", net=True)
        row(NET, "Batch size", self.net_batch)
        self.net_bn = QCheckBox()
        self.net_bn.toggled.connect(lambda _c: self._net_changed())
        row(NET, "Batch norm", self.net_bn, "net_bn")
        self.cont_on = QCheckBox("Continue from existing model")
        self.cont_on.toggled.connect(lambda _c: self._continue_changed())
        tip(self.cont_on, "continue")
        row(YOLO, None, self.cont_on)
        crow = QHBoxLayout()
        self.cont_box = QComboBox()
        self.cont_box.setMinimumWidth(200)
        self.cont_box.currentIndexChanged.connect(lambda _i: self._continue_changed())
        crow.addWidget(self.cont_box, 1)
        self.cont_browse = QPushButton("Browse...")
        self.cont_browse.clicked.connect(self.browse_model)
        crow.addWidget(self.cont_browse)
        self.cont_row = QWidget()
        self.cont_row.setLayout(crow)
        crow.setContentsMargins(0, 0, 0, 0)
        row(YOLO, None, self.cont_row)
        self.dist_only = QCheckBox("Keep the detector as it is: train only the distance model")
        self.dist_only.toggled.connect(lambda _c: self._model_changed())
        tip(self.dist_only, "dist_only")
        mf.addRow(self.dist_only)
        self._row_visible(self.dist_only, False)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("(optional)")
        self.name_edit.textChanged.connect(lambda _t: self._model_changed())
        row(ALL, "Model name", self.name_edit, "name")
        iv.addStretch(1)
        # the right side: the neurons of every layer (a network), or what the kind is; and the data
        right, rv = self._pane()
        self.kind_stack = QStackedWidget()
        net_page = QWidget()
        nv = QVBoxLayout(net_page)
        nv.setContentsMargins(0, 0, 0, 0)
        nv.addWidget(pane_head("Neurons per layer"))
        self.layer_bars = tch.LayerBars()
        nv.addWidget(self.layer_bars, 1)
        about = QWidget()
        av = QVBoxLayout(about)
        av.setContentsMargins(0, 0, 0, 0)
        av.addWidget(pane_head("About this kind"))
        self.about_label = QLabel("")
        self.about_label.setWordWrap(True)
        self.about_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        av.addWidget(self.about_label)
        av.addStretch(1)
        self.kind_stack.addWidget(net_page)
        self.kind_stack.addWidget(about)
        rv.addWidget(self.kind_stack, 1)
        rv.addWidget(pane_head("Data"))
        self.data_table = QTableWidget(1, 4)
        self.data_table.setHorizontalHeaderLabels(["Pictures", "Boxes", "Distance boxes", "Validation distance boxes"])
        self.data_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.data_table.verticalHeader().setVisible(False)
        self.data_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.data_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.data_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.data_table.setFixedHeight(self.data_table.horizontalHeader().sizeHint().height() + self.data_table.verticalHeader().defaultSectionSize() + 4)
        rv.addWidget(self.data_table)
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        left.setMinimumWidth(400)
        split.setSizes([440, 900])
        return page

    def _combo(self, items, key=None):
        box = QComboBox()
        for text, data in items:
            box.addItem(text, data)
        box.currentIndexChanged.connect(lambda _i: self._net_changed())
        if key:
            tip(box, key)
        return box

    def _spinbox(self, lo, hi, value, key=None, net=False):
        sp = QSpinBox()
        sp.setRange(lo, hi)
        sp.setValue(value)
        sp.setAlignment(Qt.AlignmentFlag.AlignRight)
        sp.valueChanged.connect((lambda _v: self._net_changed()) if net else (lambda _v: self._model_changed()))
        if key and key in HINTS:
            tip(sp, key)
        return sp

    # ---- Train: the runs, the numbers of the run that is training, the charts and the log
    def _build_train_page(self):
        page = QWidget()
        lay = QHBoxLayout(page)
        lay.setContentsMargins(6, 6, 6, 4)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        lay.addWidget(split)
        left, lv = self._pane("Runs")
        self.runs_table = QTableWidget(0, 2)
        self.runs_table.horizontalHeader().setVisible(False)
        self.runs_table.verticalHeader().setVisible(False)
        self.runs_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.runs_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.runs_table.setColumnWidth(1, 150)
        self.runs_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.runs_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.runs_table.setMinimumHeight(150)
        lv.addWidget(self.runs_table, 2)
        self.now_head = pane_head("Now")
        lv.addWidget(self.now_head)
        self.now_table = QTableWidget(4, 2)
        for r, text in enumerate(("Epoch", "Validation median error", "Training median error", "Target reached at epoch")):
            it = QTableWidgetItem(text)
            it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.now_table.setItem(r, 0, it)
            self.now_table.setItem(r, 1, self._right_item("-"))
        self.now_table.horizontalHeader().setVisible(False)
        self.now_table.verticalHeader().setVisible(False)
        self.now_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.now_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.now_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.now_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.now_table.setFixedHeight(4 * self.now_table.verticalHeader().defaultSectionSize() + 4)
        lv.addWidget(self.now_table)
        lv.addWidget(pane_head("Models made here"))
        self.models_note = ui_kit.note("The Trained models window lists every model; right-click one here to export or remove it.")
        lv.addWidget(self.models_note)
        self.models_list = QListWidget()
        self.models_list.setMaximumHeight(110)
        self.models_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.models_list.customContextMenuRequested.connect(self._models_menu)
        lv.addWidget(self.models_list)
        right, rv = self._pane()
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
        self.charts = tch.ChartsPane()                         # the figures of a finished distance-network run (learning curves, learning rates, layer by layer, ...)
        live = QWidget()
        liv = QVBoxLayout(live)
        liv.setContentsMargins(0, 0, 0, 0)
        liv.setSpacing(2)
        self.live_note = ui_kit.note("")
        liv.addWidget(self.live_note)
        self.live_plots = {}
        for key in ("error", "grad", "units"):
            pw = tch.PlotWidget()
            pw.setMinimumSize(300, 170)
            self.live_plots[key] = pw
            liv.addWidget(pw, 1)
        self.live_plots["units"].setVisible(False)
        self.run_tabs = QTabWidget()
        self.run_tabs.setDocumentMode(True)
        self.run_tabs.addTab(live, "Live charts")
        self.run_tabs.addTab(self.log, "Log")
        self.run_tabs.addTab(self.charts, "Finished runs")
        self.run_tabs.setTabToolTip(2, "Charts of a finished distance-network run: learning curves, the learning-rate sweep, layer by layer, the error and the epochs by rung, a momentum toy.")
        self.live_tab = live
        rv.addWidget(self.run_tabs, 1)
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        left.setMinimumWidth(340)
        split.setSizes([420, 900])
        self.chk_error = QCheckBox("Error and loss curves")
        self.chk_grad = QCheckBox("Gradient norm per layer")
        self.chk_units = QCheckBox("Saturated and dead units")
        self.chk_error.setChecked(True)
        self.chk_grad.setChecked(True)
        for chk, key in ((self.chk_error, "error"), (self.chk_grad, "grad"), (self.chk_units, "units")):
            chk.toggled.connect(lambda on, k=key: self._live_visibility(k, on))
        self._live = {"rows": [], "mtime": None, "runs": [], "epochs": 0, "n_hidden": 1, "target": 0.075}
        return page

    @staticmethod
    def _right_item(text):
        it = QTableWidgetItem(text)
        it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
        it.setTextAlignment(int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
        return it

    # ---- Setup: the Python that trains, and what it has
    def _build_setup_page(self):
        page = QWidget()
        lay = QHBoxLayout(page)
        lay.setContentsMargins(6, 6, 6, 4)
        pane, rv = self._pane("Training Python")
        prow = QHBoxLayout()
        self.py_box = QComboBox()
        self.py_box.setMinimumWidth(260)
        tip(self.py_box, "python")
        self.py_box.currentIndexChanged.connect(lambda _i: self._python_chosen())
        prow.addWidget(self.py_box, 1)
        rv.addLayout(prow)
        rv.addWidget(hint("python"))
        self.env_label = QLabel("Looking for a Python with torch, ultralytics and a GPU ...")
        self.env_label.setWordWrap(True)
        self.env_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        rv.addWidget(self.env_label)
        self.pkg_box = QWidget()                               # downloading torch / ultralytics for OpenPara's own Python: what it is doing
        pk = QHBoxLayout(self.pkg_box)
        pk.setContentsMargins(0, 0, 0, 0)
        self.pkg_bar = QProgressBar()
        self.pkg_bar.setRange(0, 0)                            # it does not know how far it is: it moves to show it is alive
        self.pkg_bar.setMaximumWidth(160)
        self.pkg_text = QLabel("")
        self.pkg_text.setWordWrap(True)
        self.pkg_cancel = QPushButton("Cancel")
        self.pkg_cancel.clicked.connect(lambda _c=False: self.cancel_download())
        pk.addWidget(self.pkg_bar)
        pk.addWidget(self.pkg_text, 1)
        pk.addWidget(self.pkg_cancel)
        self.pkg_box.setVisible(False)
        rv.addWidget(self.pkg_box)
        rv.addStretch(1)
        lay.addWidget(pane)
        return page

    # ---- the ribbon: a page of buttons for each tab
    def _build_ribbon(self):
        rib = self._rib
        B = rib.button
        R = self.ribbon
        made = R.add_page("Data", [
            B("import_zip", "ann_import_zip", "Import\ndataset zip...", "Adds the pictures and boxes of a dataset zip (made by the Annotator or another Trainer) to this project.", self.import_zip),
            B("take", "ann_sync", "Take from\nAnnotator", "Takes the pictures, boxes and distances of the Annotator wired into this block again (the Workbench's Refresh does the same).", self.take_from_annotator),
            B("save_as", "ann_export_zip", "Save project\nas...", "Gives the project a .training folder of its own (or copies it to a new one).", lambda: self.save(True)),
            "|",
            B("clear_dist", "ann_clear_dist", "Delete distorted\ncopies", "Deletes the distorted copies of the training pictures (they are made again when training starts).", self.clear_distortions),
        ])
        self.take_btn, self.save_as_btn = made["take"], made["save_as"]
        self.take_btn.setVisible(False)                      # only a block that has an Annotator wired into it
        self.bar_buttons = [made["import_zip"], made["take"], made["save_as"], made["clear_dist"]]
        # Model: the kind of model, what the network comes to, and Start / Stop
        items = []
        for i in range(self.type_box.count()):
            k = self.type_box.itemData(i)
            text, icon, tip_text = self.KIND_BUTTONS.get(k, (rib.two_lines(self.type_box.itemText(i)), "trn_detector", self.type_box.itemText(i)))
            items.append(B(f"kind_{k}", icon, text, tip_text, group="kind"))
        self.rd_params, self.rd_shape = rib.readout("-"), rib.readout("-", 130)
        block, self.model_caption = rib.field_block([("Parameters", self.rd_params), ("Shape", self.rd_shape)], "")
        items += ["|", rib.widget("readouts", block), "|"] + self._run_items(B)
        made = R.add_page("Model", items)
        for i in range(self.type_box.count()):
            k = self.type_box.itemData(i)
            b = made[f"kind_{k}"]
            self._kind_buttons[k] = b
            b.toggled.connect(lambda on, idx=i: self._kind_pressed(idx, on))
        self._model_start, self._model_stop = made["start"], made["stop"]
        self.bar_buttons += list(self._kind_buttons.values())
        # Train: Start / Stop, how many runs, and which charts
        self.seeds = QSpinBox()
        self.seeds.setRange(1, 10)
        self.seeds.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.seeds.valueChanged.connect(lambda _v: self._model_changed())
        tip(self.seeds, "seeds")
        self.lrs_box = QComboBox()
        self.lrs_box.addItem("The Model tab's rate", None)
        self.lrs_box.addItem("The grid (8 values, 5 for Adam)", "grid")
        self.lrs_box.addItem("Own values ...", "own")
        self.lrs_box.setMinimumWidth(200)
        self.lrs_box.currentIndexChanged.connect(lambda _i: self._model_changed())
        self.lrs_box.activated.connect(lambda _i: self._lrs_picked())
        tip(self.lrs_box, "lrs")
        block, self.runs_caption = rib.field_block([("Seeds", self.seeds), ("Learning rates", self.lrs_box)], "", label_px=100)
        made = R.add_page("Train", self._run_items(B) + ["|", rib.widget("runs", block), "|", rib.widget("charts", rib.check_column([self.chk_error, self.chk_grad, self.chk_units]))])
        self.btn_train, self.btn_stop = made["start"], made["stop"]
        self._start_buttons = [self._model_start, self.btn_train]
        self._stop_buttons = [self._model_stop, self.btn_stop]
        for b in self._stop_buttons:
            b.setEnabled(False)                              # (nothing runs yet)
        made = R.add_page("Setup", [
            B("scan", "ann_sync", "Scan\nagain", "Looks again for a Python with torch and ultralytics.", self.check_env),
            B("browse_python", "ann_model_load", "Browse\nPython...", "Pick the python.exe that has torch and ultralytics.", self.browse_python),
            B("download", "ann_model_dl", "Download\npackages...", "Downloads torch and ultralytics for OpenPara's own Python.", self.offer_download),
            B("remove_pkgs", "ann_delete_box", "Remove\npackages", "Removes the packages OpenPara downloaded.", self.remove_downloaded),
        ])
        self.pkg_install_btn, self.pkg_remove_btn = made["download"], made["remove_pkgs"]
        self.btn_pkg_install, self.btn_pkg_remove = self.pkg_install_btn, self.pkg_remove_btn      # (shown when the Python has what to download / remove)
        for b in (self.btn_pkg_install, self.btn_pkg_remove):
            b.setVisible(False)
        corner = QWidget()                                   # what this is and which project, beside the tabs
        cl = QHBoxLayout(corner)
        cl.setContentsMargins(0, 0, 8, 0)
        cl.setSpacing(8)
        cl.addWidget(ui_kit.kind_chip("Trainer", "#b83280"))
        self.bar_lbl = QLabel("")
        self.bar_lbl.setStyleSheet(f"color:{ui_kit.MUTED};")
        cl.addWidget(self.bar_lbl)
        R.setCornerWidget(corner, Qt.Corner.BottomRightCorner)

    def _run_items(self, B):
        return [B("start", "trn_start", "Start\ntraining", "Starts training with the settings of this window. Nothing else starts a training: updating the Workbench project never does.", self.start, bold=True),
                B("stop", "trn_stop", "Stop", "Stops the run (while it is being prepared: Cancel). A distance network with several runs first offers to stop after the run that is going.", self.stop)]

    def _set_run_buttons(self, start=None, stop=None, stop_text=None):
        for b in self._start_buttons:
            if start is not None:
                b.setEnabled(start)
        for b in self._stop_buttons:
            if stop is not None:
                b.setEnabled(stop)
            if stop_text is not None:
                b.setText(stop_text)

    @staticmethod
    def _spin(lo, hi, dec):
        s = QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setDecimals(dec)
        s.setSingleStep(0.1 if dec else 1)
        return s

    # ------------------------------------------------------------------ the kind of model, and the Model page
    def _kind(self):
        """'net' (a distance network), 'classic' (the formula and regressors) or 'yolo' (a detector, with or without distance, and the types add-ons bring)."""
        return {"nn_ladder": "net", "classical_regress": "classic"}.get(self.type_box.currentData() or "yolo", "yolo")

    def _sync_kind_buttons(self):
        cur = self.type_box.currentData()
        for k, b in self._kind_buttons.items():
            b.blockSignals(True)
            b.setChecked(k == cur)
            b.setEnabled(self.type_box.isEnabled() and not self.preparing())
            b.blockSignals(False)

    def _kind_pressed(self, idx, on):
        if on and self.type_box.currentIndex() != idx:
            self.type_box.setCurrentIndex(idx)

    def _size_changed(self):
        self._cl_enable()                                    # (each tuning row of the classic regressors follows the regressor chosen, also when it is set from the project)
        if self._loading:
            return
        if self._kind() == "net":
            self._net_recipe_reset()
        self._model_changed()

    def _show_kind_rows(self):
        kind = self._kind()
        for kinds, lab, field in self._rows:
            on = kind in kinds
            self._row_visible(field, on)
            if lab is not None:
                lab.setVisible(on)
        if kind != "yolo":
            self._row_visible(self.dist_only, False)
        self.size_label.setText({"net": "Recipe", "classic": "Regressor"}.get(kind, "Size"))
        self.layers_box.setVisible(kind == "net")
        self.learn_head.setText({"net": "LEARNING", "classic": "REGRESSOR", "yolo": "TRAINING"}[kind])
        self.kind_stack.setCurrentIndex(0 if kind == "net" else 1)
        if kind != "net":
            spec = self._spec()
            self.about_label.setText(self.ABOUT.get(self.type_box.currentData() or "", f"{spec.get('label', '')}\n\nA model type added by an add-on."))
        self._cl_enable()

    def _cl_enable(self):
        """Each tuning row of the classic regressors is for the regressors that use it."""
        which = self.size_box.currentData() or "all"
        use = {"cl_folds": ("all", "knn", "boosting"), "cl_width": ("all", "loglinear"), "cl_blr": ("all", "boosting"), "cl_bdepth": ("all", "boosting"), "cl_biter": ("all", "boosting"),
               "cl_gprows": ("all", "gp"), "cl_gprest": ("all", "gp")}
        for name, kinds in use.items():
            getattr(self, name).setEnabled(which in kinds)

    # ---- the network: layers, learning, and what they come to
    NET_N_IN = 6                                              # the six numbers a box gives (dist_data.FEATURE_NAMES)

    def _rung(self):
        """The rung (0 - 8 or a demo's name) the Recipe stands for, or None for the whole ladder."""
        d = self.size_box.currentData()
        if self._kind() != "net" or d is None or d == "ladder":
            return None
        return d if str(d).startswith("demo") else int(d)

    def _net_base(self):
        import np_net as nn
        r = self._rung()
        return nn.rung_config(6 if r is None else r, **({"depth": 8, "width": 32} if isinstance(r, str) else {}))

    def _net_fill(self, cfg):
        """The learning controls and the layers from a recipe's settings (no change is saved)."""
        was = self._loading
        self._loading = True
        try:
            opt = cfg["optimizer"]
            kind = opt if opt in ("adam", "adamw") else ("momentum" if (cfg.get("momentum") or 0) > 0 else "plain")
            for box, val in ((self.net_loss, cfg["loss"]), (self.net_opt, kind), (self.net_act, cfg["activation"]), (self.net_init, cfg["init"]), (self.net_target, cfg["target"])):
                box.setCurrentIndex(max(0, box.findData(val)))
            self.net_lr.setValue(cfg.get("lr") or 0.001)
            self.net_mom.setValue(cfg.get("momentum") or 0.9)
            self.net_wd.setValue(cfg.get("weight_decay") or 0.0)
            self.net_batch.setValue(int(cfg["batch"]))
            self.net_bn.setChecked(bool(cfg["batch_norm"]))
            self.net_patience.setValue(int(cfg["patience"]) if cfg.get("early_stopping") else 0)
            self.net_hidden = [int(x) for x in cfg["hidden"]]
        finally:
            self._loading = was
        self._net_enable()
        self._layers_fill()

    def _net_recipe_reset(self):
        """A new recipe: its own settings fill the controls (what was changed by hand is replaced)."""
        self._net_fill(self._net_base())

    def _net_enable(self):
        single = self._rung() is not None
        for w in (self.net_loss, self.net_opt, self.net_lr, self.net_wd, self.net_act, self.net_init, self.net_target, self.net_patience, self.net_batch, self.net_bn,
                  self.layer_add, self.layer_del, self.layers_table):
            w.setEnabled(single and not self.preparing())
        self.net_mom.setEnabled(single and self.net_opt.currentData() == "momentum" and not self.preparing())

    def _net_changed(self, *_a):
        if self._loading:
            return
        sender = self.sender()
        if sender is self.net_opt:                              # the optimiser brings its usual step size
            import np_net as nn
            opt = self.net_opt.currentData()
            self._loading = True
            self.net_lr.setValue(nn.default_lr({"optimizer": "sgd" if opt in ("plain", "momentum") else opt}))
            if opt == "momentum" and self.net_mom.value() <= 0:
                self.net_mom.setValue(0.9)
            self._loading = False
        elif sender is self.net_act and self.net_act.currentData() == "silu" and self.net_init.currentData() == "he":
            self._loading = True                               # (SiLU goes with Glorot, as in the recipes)
            self.net_init.setCurrentIndex(self.net_init.findData("glorot"))
            self._loading = False
        self._net_enable()
        self._layers_fill()
        self._model_changed()

    def _layer_add(self):
        self.net_hidden.append(self.net_hidden[-1] if self.net_hidden else 32)
        self._layers_fill()
        self._model_changed()

    def _layer_del(self):
        if len(self.net_hidden) > 1:
            self.net_hidden.pop()
            self._layers_fill()
            self._model_changed()

    def _layer_params(self):
        """[(name, neurons, activation, parameters)] of the network as it is set, and the total."""
        import np_net as nn
        n_in, hidden, bn = self.NET_N_IN, list(self.net_hidden), self.net_bn.isChecked()
        act = self.net_act.currentText()
        rows, prev = [("Input", n_in, "none", 0)], n_in
        for i, w in enumerate(hidden):
            rows.append((f"Hidden {i + 1}", w, act, prev * w + w + (2 * w if bn else 0)))
            prev = w
        rows.append(("Output", 1, "linear", prev + 1))
        total = nn.count_params(n_in, hidden, bn)
        return rows, total

    def _layers_fill(self):
        """The layers table (neurons of the hidden layers can be typed), the bar chart, and the read-outs of the ribbon."""
        rows, total = self._layer_params()
        t = self.layers_table
        was = self._loading
        self._loading = True
        try:
            t.setRowCount(len(rows) + 1)
            for r, (name, n, act, params) in enumerate(rows):
                hidden = 0 < r < len(rows) - 1
                t.setItem(r, 0, self._text_item(name))
                if hidden:
                    sp = QSpinBox()
                    sp.setRange(1, 4096)
                    sp.setValue(n)
                    sp.setAlignment(Qt.AlignmentFlag.AlignRight)
                    sp.setFrame(False)
                    sp.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
                    sp.setStyleSheet(f"color:{ui_kit.ACCENT_DARK};")
                    sp.setEnabled(self._rung() is not None and not self.preparing())
                    sp.valueChanged.connect(lambda v, i=r - 1: self._hidden_typed(i, v))
                    t.setCellWidget(r, 1, sp)
                else:
                    t.removeCellWidget(r, 1)
                    t.setItem(r, 1, self._right_item(str(n)))
                t.setItem(r, 2, self._text_item(act))
                t.setItem(r, 3, self._right_item(f"{params:,}"))
            last = len(rows)
            for c, text in enumerate(("Total", "", "", f"{total:,}")):
                it = self._text_item(text) if c < 3 else self._right_item(text)
                f = it.font()
                f.setBold(True)
                it.setFont(f)
                t.setItem(last, c, it)
            t.removeCellWidget(last, 1)
            t.setFixedHeight(min(t.rowCount(), 12) * 30 + t.horizontalHeader().height() + 6)
        finally:
            self._loading = was
        self._model_view_update()

    def _hidden_typed(self, i, v):
        if self._loading or i >= len(self.net_hidden):
            return
        self.net_hidden[i] = int(v)
        rows, total = self._layer_params()
        for r, (_n, _w, _a, params) in enumerate(rows):                  # (only the numbers change: the box being typed in stays)
            self.layers_table.item(r, 3).setText(f"{params:,}")
        self.layers_table.item(len(rows), 3).setText(f"{total:,}")
        self._model_view_update()
        self._model_changed()

    @staticmethod
    def _text_item(text):
        it = QTableWidgetItem(text)
        it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
        return it

    def _shape_text(self):
        h = self.net_hidden
        return f"{h[0]} x {len(h)}" if len(set(h)) == 1 else " - ".join(str(x) for x in h)

    def _model_view_update(self):
        """What the kind comes to: the parameters and the shape in the ribbon, the bars, the line in the status bar."""
        if getattr(self, "layer_bars", None) is None:
            return
        if self._kind() == "net":
            _rows, total = self._layer_params()
            h = self.net_hidden
            self.rd_params.setText(f"{total:,}")
            self.rd_shape.setText(self._shape_text())
            self.model_caption.setText(f"{len(h)} hidden layer{'s' if len(h) != 1 else ''}" + (f" of {h[0]}" if len(set(h)) == 1 else ""))
            self.layer_bars.set_layers([self.NET_N_IN] + list(h) + [1])
        else:
            self.rd_params.setText("-")
            self.rd_shape.setText("-")
            self.model_caption.setText(self._spec().get("label", ""))
        for w in (self.rd_params, self.rd_shape):
            w.setEnabled(self._kind() == "net")                          # (the numbers of a network)
        self._runs_caption()
        self._foot_info()

    def _runs_caption(self):
        """Seeds x learning rates (x rungs) = the number of runs."""
        if getattr(self, "runs_caption", None) is None:
            return
        n = self._run_count()
        if self._kind() != "net":
            self.runs_caption.setText("One run: the seeds and learning rates are for a network.")
        else:
            seeds, lrs, rungs = self.seeds.value(), self._lr_count(), self._rung_count()
            grid_all = rungs > 1 and self.lrs_box.currentData() == "grid"           # (the grid of each rung is its own: 8 for gradient descent, 5 for Adam)
            self.runs_caption.setText(f"{seeds} seed{'s' if seeds != 1 else ''} x " + ("the learning-rate grid of each rung" if grid_all else f"{lrs} learning rate{'s' if lrs != 1 else ''}")
                                      + (f" x {rungs} rungs" if rungs != 1 and not grid_all else "") + f" = {n} run{'s' if n != 1 else ''}")
        for w in (self.seeds, self.lrs_box):
            w.setEnabled(self._kind() == "net" and not self.preparing() and not self.running())
        for c in (self.chk_error, self.chk_grad, self.chk_units):
            c.setEnabled(self._kind() == "net")
        self.live_note.setText("The charts fill in while the network trains." if self._kind() == "net" else "Live charts are drawn for a distance network. Follow this run in the Log tab.")

    def _rung_count(self):
        d = self.size_box.currentData()
        return 9 if d == "ladder" else 1

    def _lr_count(self):
        sel = self.lrs_box.currentData()
        if sel == "grid":
            import np_net as nn
            return len(nn.lr_grid(self._net_cfg_now()))
        if sel == "own":
            return max(1, len(self._own_lrs))
        return 1

    def _run_count(self):
        if self._kind() != "net":
            return 1
        if self._rung_count() > 1 and self.lrs_box.currentData() == "grid":
            import np_net as nn
            return self.seeds.value() * sum(len(nn.lr_grid(nn.rung_config(r))) for r in range(self._rung_count()))
        return self.seeds.value() * self._lr_count() * self._rung_count()

    def _net_cfg_now(self):
        """The settings of the network as they are on screen (a rung's settings with the controls' values over them)."""
        import np_net as nn
        base = self._net_base()
        try:
            return nn.rung_config(base["rung"], **({"depth": 8, "width": 32} if isinstance(base["rung"], str) else {}), **self._net_overrides())
        except (ValueError, KeyError):
            return base

    def _net_values(self):
        opt = self.net_opt.currentData()
        return {"optimizer": "sgd" if opt in ("plain", "momentum") else opt, "momentum": self.net_mom.value() if opt == "momentum" else 0.0, "loss": self.net_loss.currentData(),
                "lr": self.net_lr.value(), "weight_decay": self.net_wd.value(), "activation": self.net_act.currentData(), "init": self.net_init.currentData(),
                "target": self.net_target.currentData(), "batch": self.net_batch.value(), "batch_norm": self.net_bn.isChecked(), "patience": self.net_patience.value(),
                "hidden": list(self.net_hidden)}

    def _net_overrides(self):
        """What differs from the chosen recipe, in the names the job takes (np_net.rung_config / train_nn_job.OVERRIDES); nothing for the whole ladder."""
        if self._rung() is None:
            return {}
        base, v, over = self._net_base(), self._net_values(), {}
        for k in ("activation", "init", "loss", "target", "weight_decay", "batch_norm", "batch", "optimizer", "momentum"):
            if v[k] != base[k]:
                over[k] = v[k]
        early = v["patience"] > 0
        if early != bool(base["early_stopping"]):
            over["early_stopping"] = early
        if early and v["patience"] != base["patience"]:
            over["patience"] = v["patience"]
        if tuple(v["hidden"]) != tuple(base["hidden"]):
            over["hidden"] = list(v["hidden"])
        return over

    def _params(self):
        """The settings only a distance model reads (the job gets them as params)."""
        kind = self._kind()
        if kind == "net":
            import np_net as nn
            over = self._net_overrides()
            sel = self.lrs_box.currentData()
            lrs = None
            if sel == "grid":
                lrs = "grid"
            elif sel == "own" and self._own_lrs:
                lrs = list(self._own_lrs)
            elif self._rung() is not None and abs(self.net_lr.value() - nn.default_lr(self._net_cfg_now())) > 1e-12:
                lrs = float(self.net_lr.value())
            return dict(over, seeds=self.seeds.value(), lrs=lrs)
        if kind == "classic":
            out = {"folds": self.cl_folds.value(), "loglinear_width": self.cl_width.isChecked(), "boosting_max_iter": self.cl_biter.value(),
                   "gp_max_rows": self.cl_gprows.value(), "gp_restarts": self.cl_gprest.value()}
            lrs, depths = self._floats(self.cl_blr.text()), self._floats(self.cl_bdepth.text(), integer=True)
            if lrs:
                out["boosting_learning_rates"] = lrs
            if depths:
                out["boosting_depths"] = depths
            return out
        return {}

    @staticmethod
    def _floats(text, integer=False):
        try:
            vals = [float(x) for x in text.replace(";", ",").split(",") if x.strip()]
        except ValueError:
            return None
        vals = [v for v in vals if v > 0]
        return [int(v) for v in vals] if integer else vals

    def _params_restore(self, prm):
        """The controls from the settings saved in the project (the saved differences, over the recipe's own)."""
        kind = self._kind()
        if kind == "net":
            import np_net as nn
            r = self._rung()
            base = self._net_base()
            over = {k: v for k, v in (prm or {}).items() if k in ("activation", "init", "loss", "target", "weight_decay", "batch_norm", "batch", "optimizer", "momentum",
                                                                      "early_stopping", "patience", "hidden")}
            try:
                cfg = nn.rung_config(base["rung"], **({"depth": 8, "width": 32} if isinstance(base["rung"], str) else {}), **over)
            except (ValueError, KeyError):
                cfg = base
            lrs = (prm or {}).get("lrs")
            if r is not None and isinstance(lrs, (int, float)) and not isinstance(lrs, bool):
                cfg = dict(cfg, lr=float(lrs))
            self._net_fill(cfg)
            self._own_lrs = [float(x) for x in lrs] if isinstance(lrs, list) else []
            self.lrs_box.setCurrentIndex(max(0, self.lrs_box.findData("grid" if lrs == "grid" else "own" if self._own_lrs else None)))
            self._own_lrs_text()
        elif kind == "classic":
            p = prm or {}
            self.cl_folds.setValue(int(p.get("folds", 5)))
            self.cl_width.setChecked(bool(p.get("loglinear_width", False)))
            self.cl_blr.setText(", ".join(f"{x:g}" for x in p.get("boosting_learning_rates", [0.03, 0.1])))
            self.cl_bdepth.setText(", ".join(str(int(x)) for x in p.get("boosting_depths", [2, 3, 4])))
            self.cl_biter.setValue(int(p.get("boosting_max_iter", 500)))
            self.cl_gprows.setValue(int(p.get("gp_max_rows", 6000)))
            self.cl_gprest.setValue(int(p.get("gp_restarts", 2)))

    def _own_lrs_text(self):
        i = self.lrs_box.findData("own")
        n = len(self._own_lrs)
        self.lrs_box.setItemText(i, f"{n} value{'s' if n != 1 else ''}, {min(self._own_lrs):g} to {max(self._own_lrs):g}" if n else "Own values ...")

    def _lrs_picked(self):
        if self.lrs_box.currentData() == "own":
            from PyQt6.QtWidgets import QInputDialog
            text, ok = QInputDialog.getText(self, "Learning rates", "The learning rates to try, separated by commas (for example 0.0003, 0.001, 0.003):",
                                            text=", ".join(f"{x:g}" for x in self._own_lrs) or "0.0003, 0.001, 0.003")
            vals = self._floats(text) if ok else None
            if vals:
                self._own_lrs = vals
            elif not self._own_lrs:
                self.lrs_box.setCurrentIndex(0)
            self._own_lrs_text()
        self._model_changed()

    def _foot_info(self):
        """What the page is about, at the right of the status bar."""
        idx = self.ribbon.currentIndex() if getattr(self, "ribbon", None) is not None else 0
        name = self.ribbon.tabText(idx) if idx >= 0 else "Data"
        if name == "Model":
            if self._kind() == "net":
                _rows, total = self._layer_params()
                h = self.net_hidden
                text = f"{len(h)} hidden layer{'s' if len(h) != 1 else ''}" + (f" of {h[0]}" if len(set(h)) == 1 else "") + f", {total:,} parameters"
            else:
                text = self._spec().get("label", "")
        elif name == "Train":
            text = self._live_text()
        elif name == "Data":
            text = self.data_info.text().split("\n")[0]
        else:
            text = ""
        self.foot_info.setText(text)

    def _data_table_fill(self, s, total):
        boxes = sum(s["boxes"]["train"]) + sum(s["boxes"]["val"]) if total else 0
        vals = (s["train"] + s["val"], boxes, s["dist"]["train"], s["dist"]["val"])
        for c, v in enumerate(vals):
            self.data_table.setItem(0, c, self._right_item(f"{v:,}"))

    def _models_menu(self, pos):
        from PyQt6.QtWidgets import QMenu
        if self.models_list.itemAt(pos) is None:
            return
        menu = QMenu(self)
        menu.addAction("Export ...", self.export_model)
        menu.addAction("Remove", self.remove_model)
        menu.exec(self.models_list.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------ the run that is training (live.json of the run folder)
    def _live_visibility(self, key, on):
        self.live_plots[key].setVisible(on)

    def _live_reset(self):
        self._live = {"rows": [], "mtime": None, "runs": [], "epochs": 0, "n_hidden": len(self.net_hidden), "target": 0.075, "k": 0, "n": 0}
        self.runs_table.setRowCount(0)
        self._runs_cache = []
        for r in range(4):
            self.now_table.item(r, 1).setText("-")
        self.now_head.setText("NOW")
        self._live_charts()

    def _runs_single(self, status):
        """A kind without a list of runs (a detector, the classic regressors): one row says what is going on."""
        t = self.runs_table
        t.setRowCount(1)
        t.setItem(0, 0, self._text_item(self.type_box.currentText()))
        t.removeCellWidget(0, 1)
        t.setItem(0, 1, self._right_item(status))
        self.now_head.setText("NOW")

    def _log_progress(self, text):
        """The epoch a detector (or anything that prints 'epoch N / M') has reached, from its log."""
        import re
        found = re.findall(r"epoch\s+(\d+)\s*(?:/\s*(\d+))?", text, flags=re.I)
        if found:
            n, total = found[-1]
            self.now_table.item(0, 1).setText(f"{n} of {total}" if total else n)
            if self.ribbon.tabText(self.ribbon.currentIndex()) == "Train":
                self.foot_info.setText(f"epoch {n}" + (f" of {total}" if total else ""))

    def _live_charts(self):
        lv = self._live
        self.live_plots["error"].set_spec(cd.live_error(lv["rows"], lv["epochs"], lv["target"]))
        self.live_plots["grad"].set_spec(cd.live_grad(lv["rows"], lv["epochs"], lv["n_hidden"]))
        self.live_plots["units"].set_spec(cd.live_units(lv["rows"], lv["epochs"], lv["n_hidden"]))
        self.live_note.setVisible(not lv["rows"] or self._kind() != "net")

    def _live_text(self):
        lv = getattr(self, "_live", None)
        if not lv or not lv.get("n"):
            return self.runs_caption.text() if getattr(self, "runs_caption", None) is not None and self._kind() == "net" else ""
        last = lv["rows"][-1]["epoch"] if lv["rows"] else 0
        return f"Run {lv['k']} of {lv['n']}   |   epoch {int(last)} of {lv['epochs']}"

    def _live_poll(self, run_dir):
        """Reads live.json when it changed: the list of runs, the numbers of the one that is going, and its curves."""
        path = os.path.join(run_dir, "live.json")
        try:
            mt = os.stat(path).st_mtime_ns
        except OSError:
            return
        if mt == self._live.get("mtime"):
            return
        try:
            import json
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return                                           # (being written: the next look gets it)
        self._live.update(mtime=mt, runs=data.get("runs") or [], epochs=int(data.get("epochs") or 0), rows=(data.get("current") or {}).get("rows") or [],
                          n_hidden=int(data.get("n_hidden") or len(self.net_hidden)), target=float(data.get("target_err") or 0.075))
        runs = self._live["runs"]
        self._live["n"] = len(runs)
        running = [i for i, r in enumerate(runs) if r.get("status") == "running"]
        self._live["k"] = (running[0] + 1) if running else sum(1 for r in runs if r.get("status") not in ("queued", None))
        self._runs_fill(runs)
        self._now_fill()
        self._live_charts()
        self._foot_info()

    def _runs_fill(self, runs):
        t = self.runs_table
        cache = self._runs_cache
        multi = len({r.get("rung") for r in runs}) > 1
        if len(cache) != len(runs):
            t.setRowCount(len(runs))
            cache[:] = [None] * len(runs)
        running_row = None
        for i, r in enumerate(runs):
            st = r.get("status", "queued")
            sig = (st, int(r.get("epoch") or 0), r.get("val_err"))
            if st == "running":
                running_row = i
            if cache[i] == sig:
                continue
            cache[i] = sig
            name = (f"{r.get('rung', '')}  " if multi else "") + f"{r['lr']:g}, seed {r['seed']}"
            t.setItem(i, 0, self._text_item(name))
            if st == "running":
                bar = t.cellWidget(i, 1)
                if not isinstance(bar, QProgressBar):
                    bar = QProgressBar()
                    bar.setTextVisible(True)
                    t.setCellWidget(i, 1, bar)
                bar.setRange(0, max(1, int(r.get("epochs") or 1)))
                bar.setValue(int(r.get("epoch") or 0))
                bar.setFormat("Running  %v / %m")
            else:
                t.removeCellWidget(i, 1)
                text = {"queued": "Queued", "diverged": "Diverged", "failed": "Failed"}.get(st)
                if text is None:
                    ve = r.get("val_err")
                    text = f"{ve * 100:.1f} %" if isinstance(ve, (int, float)) else "Done"
                t.setItem(i, 1, self._right_item(text))
        if running_row is not None and running_row != getattr(self, "_runs_scrolled", None):
            self._runs_scrolled = running_row
            t.scrollToItem(t.item(running_row, 0))

    def _now_fill(self):
        lv, rows = self._live, self._live["rows"]
        self.now_head.setText(f"NOW, RUN {lv['k']} OF {lv['n']}" if lv["n"] else "NOW")
        if not rows:
            return
        last = rows[-1]

        def pct(v):
            return f"{float(v) * 100:.1f} %" if isinstance(v, (int, float)) and v == v else "-"
        reached = next((int(r["epoch"]) for r in rows if isinstance(r.get("val_median_rel_err"), (int, float)) and r["val_median_rel_err"] <= lv["target"]), None)
        self.now_table.item(0, 1).setText(f"{int(last['epoch'])} of {lv['epochs']}")
        self.now_table.item(1, 1).setText(pct(last.get("val_median_rel_err")))
        self.now_table.item(2, 1).setText(pct(last.get("train_median_rel_err")))
        self.now_table.item(3, 0).setText(f"Reached {lv['target'] * 100:g} % at epoch")
        self.now_table.item(3, 1).setText(str(reached) if reached else "not yet")

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
            self._show_kind_rows()
            self.epochs.setValue(m["epochs"])
            for k, s in self.more.items():
                s.setValue(m[k])
            self._fill_continue(m.get("continue_from"))
            self.cont_on.setChecked(bool(m.get("continue_from")))
            self.dist_only.setChecked(bool(m.get("distance_only", True)))
            self.name_edit.setText(m.get("name") or "")
            prm = m.get("params") or {}
            self.seeds.setValue(int(prm.get("seeds") or 1))
            self._params_restore(prm)
            self._continue_enable()
        finally:
            self._loading = False
        self.refresh_data()
        self.refresh_models()
        self.setWindowTitle(self.title())

    def _fill_sizes(self, want=None):
        spec = tc.model_types().get(self.type_box.currentData() or "yolo", {})
        names = dict({"n": "Nano", "s": "Small", "m": "Medium", "l": "Large"}, **(spec.get("size_names") or {}))
        sizes = tuple(spec.get("sizes", ()))
        if self.type_box.currentData() == "nn_ladder":                 # the ladder in its order, each rung with its name
            import np_net as nn
            names.update({str(k): f"{r['name']} (rung {k})" for k, r in nn.RUNGS.items()})
            order = ("ladder",) + tuple(str(k) for k in range(9)) + ("demo_sigmoid", "demo_relu_he", "demo_bn")
            sizes = tuple(x for x in order if x in sizes)
        self.size_box.blockSignals(True)
        self.size_box.clear()
        for s in sizes:
            self.size_box.addItem(names.get(s, s), s)
        i = self.size_box.findData(want)
        if i < 0:
            i = self.size_box.findData(spec.get("default_size"))
        self.size_box.setCurrentIndex(max(0, i))
        self.size_box.blockSignals(False)

    def refresh_bar(self):
        """The ribbon's corner says which project this is, the status bar where its data comes from, and the folded steps their one-line summary."""
        try:
            wb = self.workbench_block
            if wb:
                self.bar_lbl.setText(f"<b>{wb['label']} {wb['title']}</b>")
                self.foot_lbl.setText("A block of a Workbench project   |   " + (f"Fed by {wb['annotator']}" if wb.get("annotator") else
                                                                                 "No Annotator is wired into it: import a dataset zip here, or wire an Annotator's Dataset in the Workbench"))
            else:
                self.bar_lbl.setText(f"<b>{self.title()}</b>" if self.path else "A new project (not saved yet)")
                self.foot_lbl.setText(f"Project: {self.path}" if self.path else "")
            self._foot_info()
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
        self._data_table_fill(s, total)
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
        if getattr(self, "charts", None) is not None:
            self.charts.set_runs_dir(self.tp.runs_dir)
        self.models_list.clear()
        for v in self.tp.list_models():
            sc = v.get("scores") or {}
            if v.get("kind") == "distance":
                what = tc.model_types().get("nn_ladder" if v.get("family") == "mlp" else "classical_regress", {}).get("size_names", {})
                name = (f"network, rung {(v.get('info') or {}).get('rung')}" if v.get("family") == "mlp" else what.get(v.get("family"), v.get("family")))
                it = QListWidgetItem(f"{name}   distance only   {time.strftime('%Y-%m-%d %H:%M', time.localtime(v['ts']))}" + self.ml.distance_text(sc, "   "))
                it.setData(Qt.ItemDataRole.UserRole, v["path"])
                it.setToolTip(v["file"] + ("\nThis file holds a pickle: it is opened only if you say you trust it." if v.get("pickled") else ""))
                self.models_list.addItem(it)
                continue
            kind = {"two": "classes + boxes + distance", "old": "classes + boxes + distance (earlier kind)"}.get(tc.checkpoint_kind(v["path"]), "classes + boxes")
            it = QListWidgetItem(f"{self.ml.mr.SIZE_NAMES.get(v['size'], '?')}   {kind}   {time.strftime('%Y-%m-%d %H:%M', time.localtime(v['ts']))}"
                                 + (f"   mAP50 {sc['map50']}" if "map50" in sc else "") + self.ml.distance_text(sc))
            it.setData(Qt.ItemDataRole.UserRole, v["path"])
            it.setToolTip(v["file"])
            self.models_list.addItem(it)

    # ------------------------------------------------------------------ the ribbon, a block of the Workbench, the models
    def _on_ribbon_tab(self, index):
        """Each tab of the ribbon shows its page: Data, Model, Train, Setup."""
        self.pages.setCurrentIndex(index)
        self._foot_info()

    def set_workbench_block(self, info):
        """Called by the Workbench block that opened this window.  Its models are kept in the Workbench project (they are not also put in the Annotator's Models folder), the
        project is the block's own (no Save project as), and `info` says what the status bar shows: {"label", "title", "annotator": the Annotator wired in or "",
        "take": a function that takes that Annotator's dataset again (-> None or what went wrong), "changed": a function that tells the Workbench a model was made or removed}."""
        self.workbench_block = info
        self.tp.publish_shared = False
        self.save_as_btn.setVisible(False)
        self.take_btn.setVisible(bool(info.get("annotator")) and callable(info.get("take")))
        self.models_note.setText("They are kept in the Workbench project, inside its file.")
        self.refresh_bar()

    def _models_changed_here(self):
        fn = (self.workbench_block or {}).get("changed")
        if callable(fn):
            try:
                fn()
            except Exception:  # noqa: BLE001
                pass

    def take_from_annotator(self):
        fn = (self.workbench_block or {}).get("take")
        if not callable(fn) or self.running() or self._bg or self.preparing():
            return
        err = fn()
        self.status.setText("")
        if err:
            QMessageBox.warning(self, "Take from Annotator", err)
        else:
            self.refresh_data()

    def _chosen_model(self):
        it = self.models_list.currentItem()
        if it is None and self.models_list.count() == 1:
            it = self.models_list.item(0)
        return it.data(Qt.ItemDataRole.UserRole) if it is not None else None

    def export_model(self):
        path = self._chosen_model()
        if not path:
            QMessageBox.information(self, "Export model", "Choose a model in the list of models first.")
            return
        dest, _ = QFileDialog.getSaveFileName(self, "Export the model as a file", os.path.basename(path), "Distance model (*.opdm)" if path.lower().endswith(tc.DISTANCE_EXT) else "Model (*.pt)")
        if not dest:
            return
        try:
            out = self.tp.export_model(path, dest)
        except OSError as e:
            QMessageBox.critical(self, "Export model", f"Could not write the model: {e}")
            return
        self.status.setText(f"Exported {os.path.basename(out)}." if out.lower().endswith(tc.DISTANCE_EXT)
                            else f"Exported {os.path.basename(out)}, with its information in {os.path.basename(self.ml.info_path(out))}.")

    def import_model(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Import model file(s)", "", "Models (*.pt *.opdm);;Model (*.pt);;Distance model (*.opdm)")
        if paths:
            self.import_model_files(paths)

    def import_model_files(self, paths):
        """Takes model files into the project (the Workbench block then keeps each inside its project file up to 500 MB, or linked).  A .pt file can run code when it is loaded:
        the person is asked once."""
        paths = [p for p in paths if p.lower().endswith((".pt", tc.DISTANCE_EXT)) and os.path.isfile(p)]
        if not paths:
            return 0
        if any(p.lower().endswith(".pt") for p in paths):                  # (a distance model is numbers, and is only copied here; the one with a pickle asks when it is opened)
            r = QMessageBox.question(self, "Import model", "A model file (.pt) can contain code that runs when it is loaded.\n\nImport only models you made or trust. Import " + (
                f"these {len(paths)} files?" if len(paths) > 1 else os.path.basename(paths[0]) + "?"), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if r != QMessageBox.StandardButton.Yes:
                return 0
        done, failed = [], []
        for p in paths:
            try:
                done.append(os.path.basename(self.tp.import_model(p)))
            except Exception as e:  # noqa: BLE001
                failed.append(f"{os.path.basename(p)}: {e}")
        self.refresh_models()
        self._models_changed_here()
        self.status.setText((f"Imported {', '.join(done)}. " if done else "") + ("; ".join(failed)))
        return len(done)

    def remove_model(self):
        path = self._chosen_model()
        if not path:
            QMessageBox.information(self, "Remove model", "Choose a model in the list of models first.")
            return
        r = QMessageBox.question(self, "Remove model", f"Remove {os.path.basename(path)} from this project?\n\nIt cannot be got back from here (export it first to keep a copy).",
                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if r != QMessageBox.StandardButton.Yes:
            return
        self.tp.remove_model(path)
        self.refresh_models()
        self._models_changed_here()

    def dragEnterEvent(self, e):
        if any(u.toLocalFile().lower().endswith((".pt", tc.DISTANCE_EXT)) for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.import_model_files([u.toLocalFile() for u in e.mimeData().urls()])

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
        if self._spec().get("numpy_only") and p["enabled"]:
            self.dist_note.setText("This model type learns from the original pictures' boxes: no distorted copies are made for it, whatever is set here. (They are made again for a YOLO type.)")
        elif not p["enabled"] or not p["pictures"]:
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
        self._fill_sizes(self.size_box.currentData())
        self._show_kind_rows()
        if self._kind() == "net":
            self._net_recipe_reset()
        self._continue_enable()
        self._model_changed()
        self._summary()

    def _model_changed(self):
        if self._loading:
            return
        m = {"type": self.type_box.currentData(), "size": self.size_box.currentData(), "epochs": self.epochs.value(),
             "name": self.name_edit.text().strip(), "continue_from": self.cont_box.currentData() if self.cont_on.isChecked() else None,
             "distance_only": self.dist_only.isChecked()}
        m.update({k: s.value() for k, s in self.more.items()})
        m["params"] = self._params()
        self.tp.meta["settings"].setdefault("model", {})["params"] = {}      # (the settings are merged: a difference taken back must not stay in the old ones)
        self.tp.set_settings({"model": m})
        self._update_env_view()
        self._model_view_update()

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
                        kind = {"two": ", with distance", "old": ", with distance, earlier kind"}.get(tc.checkpoint_kind(v["path"]), "")
                        self.cont_box.addItem(f"{v['file'][:-3]}   ({label}{kind})", v["path"])
        if want and want not in seen:
            self.cont_box.addItem(os.path.basename(want), want)
        i = self.cont_box.findData(want) if want else -1
        self.cont_box.setCurrentIndex(i if i >= 0 else (0 if self.cont_box.count() else -1))
        self._loading = was

    def _row_visible(self, wdg, on):
        if hasattr(self.model_form, "setRowVisible"):                # Qt 6.4 and later
            self.model_form.setRowVisible(wdg, on)
        else:
            wdg.setVisible(on)

    def _spec(self):
        return tc.model_types().get(self.type_box.currentData() or "yolo", {})

    def _type_rows(self):
        """What the chosen kind uses: a distance-only model is trained from random weights (nothing to continue from) on the processor, from the original pictures."""
        numeric = bool(self._spec().get("numpy_only"))
        self.cont_on.setEnabled(not numeric)
        for wdg in (self.cont_row, self.cont_box, self.cont_browse):
            wdg.setEnabled(not numeric and self.cont_on.isChecked())
        self._show_kind_rows()

    def _continue_enable(self):
        self._type_rows()
        numeric = bool(self._spec().get("numpy_only"))
        on = self.cont_on.isChecked() and not numeric
        path = self.cont_box.currentData() if on else None
        kind = tc.checkpoint_kind(path) if path and os.path.isfile(path) else "plain"
        builtin = (self.type_box.currentData() or "") in ("yolo", "yolo_distance")
        self.cont_row.setEnabled(on)
        self.size_box.setEnabled(not on)
        # a classes + boxes model can go on as it is or get a distance model on top; one with a distance model keeps it
        self.type_box.setEnabled(not on or (kind == "plain" and builtin))
        self._sync_kind_buttons()
        show = on and self.type_box.currentData() == "yolo_distance" and kind != "old"
        if show != (not self.dist_only.isHidden()):
            self._row_visible(self.dist_only, show)                    # a whole row: the form gives its height back and lays itself out again

    def _continue_changed(self):
        self._type_follows_model()
        self._continue_enable()
        self._model_changed()

    def _type_follows_model(self):
        """A model that has a distance model is continued with it: choosing one switches the type to Classes + boxes + distance.
        A classes + boxes model leaves the type as it is (it can go on as it is, or get a distance model on top)."""
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
                self._fill_sizes(self.size_box.currentData())
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
            self._continue_enable()
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
        if not self._offered and not self._closed and self.env and tc.can_download(self.env) and not self._spec().get("numpy_only"):
            self._offered = True                               # asked once on its own; the button below the text asks again
            QTimer.singleShot(300, self.offer_download)

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

    # ------------------------------------------------------------------ downloading torch and ultralytics
    def _pkg_buttons(self, offer):
        """The download button (when OpenPara's own Python lacks something) and the remove button (when something was downloaded)."""
        names = ""
        if self.env:
            need_t, need_u = tc.missing_packages(self.env)
            names = " and ".join(n for n, need in (("torch", need_t), ("ultralytics", need_u)) if need)
        self.btn_pkg_install.setText(f"Download {names}..." if names else "Download torch and ultralytics...")
        self.btn_pkg_install.setVisible(bool(offer))
        self.btn_pkg_remove.setVisible(tc.has_packages() and not self._pkg)
        self.btn_pkg_remove.setEnabled(not self.running())

    def _ask_download(self, text, choices):
        """Asks which download to make: choices = [(button text, kind)]; returns the kind, or None for Not now."""
        box = QMessageBox(self)
        box.setWindowTitle("Download what training needs")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(text)
        buttons = {box.addButton(label, QMessageBox.ButtonRole.AcceptRole): kind for label, kind in choices}
        box.addButton("Not now", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return buttons.get(box.clickedButton())

    def offer_download(self):
        """Asks (once, with the size) whether to download what OpenPara's own Python lacks, then does it in the background."""
        if self._pkg or self._closed or not self.env or not tc.can_download(self.env):
            return
        need_t, need_u = tc.missing_packages(self.env)
        names = " and ".join(n for n, need in (("torch", need_t), ("ultralytics", need_u)) if need)
        text = f"Training needs {names}, and the Python OpenPara runs on does not have {'it' if not (need_t and need_u) else 'them'} yet.\n\n"
        if need_t:
            gpu = tc.nvidia_gpu()
            if gpu:
                text += (f"This computer has an NVIDIA GPU ({gpu}). The GPU version trains much faster:\n    {tc.DOWNLOAD_TEXT['cuda']}.\n"
                         f"The CPU version works on any computer but is slow:\n    {tc.DOWNLOAD_TEXT['cpu']}.\n\n")
                choices = [("Download the GPU version", "cuda"), ("Download the CPU version", "cpu")]
            else:
                text += f"No NVIDIA GPU was found, so this is the CPU version: slow, but it works.\n    {tc.DOWNLOAD_TEXT['cpu']}.\n\n"
                choices = [("Download", "cpu")]
        else:
            text += "It is a small download (about 0.2 GB).\n\n"
            choices = [("Download", "cpu")]
        text += "It is done once, needs an internet connection, and you can keep working while it downloads."
        kind = self._ask_download(text, choices)
        if kind:
            self.start_download(kind)

    def start_download(self, kind):
        if self._pkg or not self.env:
            return
        python = self.env["python"]
        need_t, need_u = tc.missing_packages(self.env)
        state = self._pkg = {"stop": False, "t0": time.time(), "text": "Starting ...", "kind": kind}
        self.pkg_box.setVisible(True)
        self.pkg_cancel.setEnabled(True)
        self._update_env_view()
        self._pkg_show()

        def say(t):
            self.post(lambda: state.update(text=t))

        def run():
            err, cancelled = None, False
            try:
                tc.install_packages(kind, need_t, need_u, progress=say, stop=lambda: state["stop"])
            except tc.Cancelled:
                cancelled = True
            except tc.InstallError as e:
                err = str(e)
            except Exception as e:  # noqa: BLE001
                err = f"The download failed unexpectedly: {e}"
            info = None if (err or cancelled) else tc.check_env(python)
            self.post(lambda: self._download_done(python, info, err, cancelled))
        threading.Thread(target=run, daemon=True).start()

    def cancel_download(self):
        if self._pkg:
            self._pkg["stop"] = True
            self._pkg["text"] = "Cancelling ..."
            self.pkg_cancel.setEnabled(False)

    def _pkg_show(self):
        if self._pkg:
            n = int(time.time() - self._pkg["t0"])
            self.pkg_text.setText(f"{self._pkg['text']}   ({n // 60}:{n % 60:02d})")

    def _download_done(self, python, info, err, cancelled):
        if self._closed:
            return
        self._pkg = None
        self.pkg_box.setVisible(False)
        if err:
            QMessageBox.warning(self, "Download", err)
        elif cancelled:
            self.status.setText("The download was cancelled; nothing was installed.")
        elif info is not None:
            self._added_python(info)
            if info["ok"]:
                gpu = f"GPU: {info['gpu']}" if info.get("cuda") else "This is the CPU version, so training is slow (fine for a try)."
                QMessageBox.information(self, "Download", f"Done. torch {info['torch']} and ultralytics {info['ultralytics']} are installed.\n\n{gpu}")
            else:
                QMessageBox.warning(self, "Download", "The download finished, but the Trainer still cannot use it:\n\n" + tc.env_text(info))
        self._update_env_view()

    def remove_downloaded(self):
        """Deletes the packages the Trainer downloaded (the way back to how it was; they can be downloaded again)."""
        if self._pkg or self.running() or not tc.has_packages():
            return
        r = QMessageBox.question(self, "Remove the downloaded packages", "Delete the torch and ultralytics that OpenPara downloaded for its own Python? "
                                 "They can be downloaded again, but training needs them.",
                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if r != QMessageBox.StandardButton.Yes:
            return
        try:
            tc.remove_packages()
        except tc.InstallError as e:
            QMessageBox.warning(self, "Remove", str(e))
        self._offered = True                                   # taken away on purpose: not asked again unasked (the button stays)
        self.check_env()

    def _update_env_view(self):
        if self.env is None:
            if not self.py_box.count():
                self.env_label.setText("No Python was found. Use Browse... to pick the python.exe that has torch and ultralytics.")
            self._pkg_buttons(False)
            return
        spec = self._spec()
        problems, warnings = tc.env_problems(self.env, spec)
        text = tc.env_text(self.env, spec)
        if problems:
            self.env_label.setStyleSheet("color: #b00020;")
            text = "Training is not possible with this Python yet:\n" + text
        elif warnings:
            self.env_label.setStyleSheet("color: #b36b00;")
        else:
            self.env_label.setStyleSheet("")
        offer = tc.can_download(self.env) and not self._pkg and not spec.get("numpy_only")
        if offer:
            text += "\nOpenPara can download what is missing: press the button below."
        self.env_label.setText(text)
        self._pkg_buttons(offer)
        self._set_run_buttons(start=not self.running() and not self.preparing())

    def start(self):
        """Prepares the run in a background thread (the distorted copies and the run's copy of the data can take minutes), showing what
        it is doing; the window stays usable and Cancel ends it.  Then the training program starts."""
        if self.running() or self._bg or self.preparing():
            return
        if self.env is None or tc.env_problems(self.env, self._spec())[0]:
            QMessageBox.warning(self, "Training", tc.env_text(self.env, self._spec()) if self.env else "No usable Python yet. Wait for the scan to finish, or use Browse... to pick one.")
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
        self._live_reset()
        self.ribbon.show_page("Train")                         # (the runs, the numbers and the charts are on the Train page)
        self._prep_view(True)
        self._prep_show()
        threading.Thread(target=run, daemon=True).start()

    def _prep_view(self, on):
        """The window while a run is being prepared: the left panel and the bar's commands wait, Stop is Cancel, the bar shows."""
        for pg in self.panel_pages:
            pg.setEnabled(not on)
        for b in self.bar_buttons:
            b.setEnabled(not on)
        self.py_box.setEnabled(not on)
        self._set_run_buttons(start=not on and not self.running(), stop=on or self.running(), stop_text="Cancel" if on else "Stop")
        self.prep_bar.setVisible(on)
        self._run_state_changed()

    def _run_state_changed(self):
        """What can be changed follows what is going on: the kind buttons, the recipe's controls, the seeds and learning rates."""
        self._sync_kind_buttons()
        self._net_enable()
        self._runs_caption()

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
        self._job_net = self._kind() == "net"
        self._stop_after = self._job_net and self._run_count() > 1          # a sweep can be stopped after the run that is going
        self._stop_after_asked = False
        self._set_run_buttons(start=False, stop=True, stop_text="Stop after\nthis run" if self._stop_after else "Stop")
        self._run_state_changed()
        if not self._job_net:
            self._runs_single("Running")
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
            self._set_run_buttons(stop=False)
            self._prep_show()
        elif self.running():
            if getattr(self, "_stop_after", False) and not self._stop_after_asked:
                self._stop_after_asked = True                  # the run that is going ends, the rest are not started, and a model is made from the runs that finished
                self.job.stop_after_run()
                self._set_run_buttons(stop_text="Stop now")
                self.status.setText("Stopping after the run that is going: the runs that finished are kept. Press Stop now to end it at once (nothing is saved then).")
            else:
                self.job.stop()

    def _tick(self):
        if self._prep is not None:
            self._prep_show()
        if self._pkg is not None:
            self._pkg_show()
        if self.job is None:
            return
        text = self.job.read_log()
        if text:
            self.log.appendPlainText(text.rstrip("\n"))
            if not getattr(self, "_job_net", False):
                self._log_progress(text)
        if getattr(self, "_job_net", False):
            self._live_poll(self.job.run_dir)
        code = self.job.poll()
        if code is None:
            return
        job, self.job = self.job, None
        text = job.read_log()
        if text:
            self.log.appendPlainText(text.rstrip("\n"))
        if getattr(self, "_job_net", False):
            self._live_poll(job.run_dir)
        else:
            self._runs_single("Stopped" if job.stopped else "Done")
        self._set_run_buttons(start=True, stop=False, stop_text="Stop")
        self._run_state_changed()
        if self.status.text().startswith("Stopping after"):
            self.status.setText("")
        res = job.result()
        if res and res.get("ok") and res.get("kind") == "nn_ladder" and not job.stopped:
            self.charts.set_runs_dir(self.tp.runs_dir)
            if self.charts.load(job.run_dir):
                self.run_tabs.setCurrentWidget(self.charts)      # (a network run has charts to look at)
        if job.stopped:
            self.run_label.setText("Stopped. Nothing was saved from this run.")
        elif res and res.get("ok") and res.get("warning"):
            self.run_label.setText("Finished, but not with what was asked for - see the end of the log. " + res["warning"])
            self.refresh_models()
            self._models_changed_here()
            self._tell_annotators()
        elif res and res.get("ok") and res.get("stopped_early"):
            self.run_label.setText(f"Stopped after the run that was going ({res['stopped_early']} of {res.get('planned')} runs). The model is made from the runs that finished and saved"
                                   + (" in this project." if self.workbench_block else " and the annotator lists it."))
            self.refresh_models()
            self._models_changed_here()
            self._tell_annotators()
        elif res and res.get("ok"):
            self.run_label.setText("Finished. The new model is saved" + (" in this project." if self.workbench_block else " and the annotator lists it."))
            self.refresh_models()
            self._models_changed_here()
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
