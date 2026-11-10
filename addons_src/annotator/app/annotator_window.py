"""
annotator_window.py - the General Classification Annotator as a Qt window (a QMainWindow, so it can be a tab).

Desktop bounding-box annotation tool for building a detection dataset: draw boxes on photos from the Gimble rig (camera + LiDAR), import
a recorded session folder (every sample brings its LiDAR depth, viewable as an overlay) or a video, pre-label with AI models, and PUBLISH
what you annotated as a zip you can hand to someone (and merge theirs into yours). Classes are your own and bound to hotkeys (Edit > Classes, Edit > Hotkeys).

All the actual logic (box math, file formats, the project's on-disk state, Gimble import, export / splitting) lives in annotator_core.py
and share_zip.py and is toolkit-free; this file is the visual layer: it shows things and turns clicks into calls on a Project object.
It does the same things the older Tkinter window (annotator_gui.py in the General-Classification-Annotator repository) did.
"""

import contextlib
import json
import os
import shutil
import tempfile
import threading

import numpy as np
from PIL import Image
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QColor, QShortcut
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFrame, QMessageBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, QPushButton,
                             QScrollArea, QSplitter, QVBoxLayout, QWidget)

try:                                                         # inside OpenPara: the shared look (bar, button weights); on its own the annotator does without
    import ui_kit
except ImportError:
    ui_kit = None

import annotator_core as ac
import annotator_canvas as cv
import annotator_dialogs as dlg
import dataset_zip as dz
import hotkeys as hk
import model_download as md
import model_library as ml
import model_registry as mr
import qtk
import share_zip as sz
import web_mode as wm

HERE = os.path.dirname(os.path.abspath(__file__))
COPY_LIDAR_ON_IMPORT = True              # also copy each sample's raw LiDAR points into the project
color_for_class = cv.color_for_class
DEPTH_NEAR_M, DEPTH_FAR_M, PICK_RADIUS_PX, ZOOM_MAX, ZOOM_STEP = cv.DEPTH_NEAR_M, cv.DEPTH_FAR_M, cv.PICK_RADIUS_PX, cv.ZOOM_MAX, cv.ZOOM_STEP

# AI models: downloaded from GitHub (File > Download models from GitHub) into one folder in OpenPara's own data folder, <models_dir()>/Assist
# and /Scratch; or trained by you (found under RUNS_DIR, the training program's output folder).  Nothing is built in.
def models_dir():
    try:
        import paths
        base = paths.user_dir()
    except Exception:  # noqa: BLE001
        base = os.path.join(os.path.expanduser("~"), ".openpara")
    return os.path.join(base, "Annotator", "Models")


def untitled_dir():
    """A fresh working folder for a project that has not been saved yet."""
    import tempfile
    base = os.path.join(os.path.dirname(models_dir()), "untitled")
    os.makedirs(base, exist_ok=True)
    return tempfile.mkdtemp(prefix="project_", dir=base)


RUNS_DIR = os.path.join(os.path.expanduser("~"), "yolo_runs")
AI_CHOICES = ["No AI model"]


def same_path(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


class AnnotatorWindow(QMainWindow):
    def __init__(self, project_root, note=None, first_run_prompt=True, temp=False):
        super().__init__()
        self.temp_root = project_root if temp else None      # a project that has not been saved yet works in a temporary folder
        self.setWindowTitle("General Classification Annotator")
        self.post = qtk.Poster()
        self.cfg = sz.load_config()                  # per computer: your name + id
        self.kind = "annotator"
        self.host = None
        self.project = None
        self._bg_job = False             # an import / export / refresh is running in the background
        self._web = None
        self._dialogs = {}
        self._classes_refresh = self._hotkeys_refresh = self._sessions_refresh = None
        self.shortcuts = []
        self._build_ui()
        self.open_project(project_root)
        if note:
            qtk.info(self, "Project folder", note)
        qtk.later(300, self._identify_old_models_in_background)
        if first_run_prompt:
            qtk.later(700, self.first_run_models_prompt)

    def title(self):
        if self.path:
            b = os.path.basename(self.path.rstrip("/\\"))
            return b[:-len(".annotator")] if b.lower().endswith(".annotator") else b
        return "Annotator"

    # ------------------------------------------------------------------ the project: a folder with its dataset inside
    def is_dirty(self):
        """True while the project has not been saved and already holds something (so closing it asks)."""
        return self.temp_root is not None and (bool(self.project.manifest['images']) or bool(self.project.classes))

    def ensure_saved(self, why):
        """The dataset lives inside the project folder, so a new project is saved (given its folder) before anything is put into it."""
        if self.temp_root is None:
            return True
        qtk.info(self, "Save the project first", f"{why}\n\nAn annotator project is kept in its own folder, with its dataset inside. Choose where to save it.")
        return bool(self.save())

    def save(self, as_new=False):
        """Gives an unsaved project its folder (everything is copied there and the project reopens on it); Save As copies a saved one."""
        if self.temp_root is None and not as_new:
            return True
        if self._bg_blocked():
            return False
        start = (self.path or "Annotator") if as_new else "Annotator.annotator"
        path, _ = QFileDialog.getSaveFileName(self, "Save the annotator project (a folder)", start, "Annotator project (*.annotator)")
        if not path:
            return False
        if not path.lower().endswith(".annotator"):
            path += ".annotator"
        if self.path and same_path(path, self.path):
            return True
        try:
            self.project.save_manifest()
            shutil.copytree(self.project.root, path, dirs_exist_ok=True)
        except OSError as e:
            qtk.error(self, "Save", f"Could not save the project: {e}")
            return False
        old, self.temp_root = self.temp_root, None
        self.open_project(path)
        if old:
            shutil.rmtree(old, ignore_errors=True)
        return True

    @contextlib.contextmanager
    def busy_card(self, text):
        """The window's 'Opening ...' card (the program window's), for tool windows that take a moment to build."""
        fn = getattr(self.host, "busy", None)
        if callable(fn):
            with fn(text):
                yield
        else:
            yield

    # ------------------------------------------------------------------ a project is opened (also File > Dataset location)
    def open_project(self, root):
        self.project = ac.Project(root)
        self.path = None if (self.temp_root and same_path(root, self.temp_root)) else root
        self.current_image_id = None
        self.current_pil_image = None
        self.boxes = []              # (class_id, xc, yc, w, h) for the current image
        self.box_dist = []           # parallel to boxes: None or {distance_m, u, v}
        self.active_session = None   # None = all sets; else the session id whose frames are listed
        self._session_keys = [None]
        self.selected_box_index = None
        self.scale, self.offset = 1.0, (0, 0)
        self.zoom, self.view_center = 1.0, None
        self.current_class_id = 0
        self.model_assist = None
        self._ai_kind = None
        self.model_conf = 0.25
        self._predict_busy = False
        self._predict_queued_img_id = None
        self._depth_cache = (None, None)
        self.hotkeys = hk.Hotkeys(self.project.load_hotkeys())
        self.me = sz.identity(self.cfg)              # None until you have told the app your name (asked on first share)
        self.access_people = set()                   # other people's data you have opened with Access this run
        if self.me:
            self.project.editor_id = self.me['id']
        self._scan_models()
        self.pick_check.setChecked(False)
        self.ai_choice.blockSignals(True)
        self.ai_choice.setCurrentIndex(0)
        self.ai_choice.blockSignals(False)
        self.ai_status.setText("No model loaded")
        self._refresh_ai_choices()
        self._build_ai_assist_checkboxes()
        self._bind_hotkeys()
        self._update_pick_check_text()
        self._update_fit_button_text()
        self._refresh_class_list()
        self._refresh_image_list()
        self.canvas.redraw()
        self._update_status()
        if self.project.startup_reconciled:
            qtk.info(self, "Cleaned up deleted files",
                     f"{len(self.project.startup_reconciled)} image(s) were deleted outside the app. Their labels were cleaned up.")

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(6, 6, 6, 4)
        # toolbar row
        tb = QHBoxLayout()
        self.pick_check = QCheckBox()
        self.pick_check.toggled.connect(self._on_pick_toggle)
        tb.addWidget(self.pick_check)
        self.fit_button = QPushButton()
        self.fit_button.clicked.connect(self.fit_view)
        tb.addWidget(self.fit_button)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        tb.addWidget(sep)
        tb.addWidget(QLabel("AI model:"))
        self.ai_choice = QComboBox()
        self.ai_choice.setMinimumWidth(190)
        self.ai_choice.addItems(AI_CHOICES)
        self.ai_choice.activated.connect(lambda _i: self.load_ai_model())
        tb.addWidget(self.ai_choice)
        b = self.confirm_btn = QPushButton("Confirm image")
        b.setToolTip("Marks this image as annotated the way it is now (its boxes are kept) and goes to the next one.")
        b.clicked.connect(self.confirm_current_as_is)
        if ui_kit is not None:
            ui_kit.primary(b)                                # the action that moves the work on
        tb.addWidget(b)
        self.ai_status = QLabel("No model loaded")
        tb.addWidget(self.ai_status)
        tb.addStretch(1)
        outer.addLayout(tb)

        split = QSplitter()
        outer.addWidget(split, 1)
        # left: classes, AI assist, selected box (scrollable, so nothing ever scrolls out of reach)
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.Shape.NoFrame)
        left = QWidget()
        left_scroll.setWidget(left)
        ll = QVBoxLayout(left)
        ll.addWidget(self._heading("Classes"))
        self.class_list = QListWidget()
        self.class_list.setMinimumHeight(120)
        self.class_list.currentRowChanged.connect(self._on_class_select)
        ll.addWidget(self.class_list, 1)
        ll.addWidget(self._note("Press a class key [ ] to pick it. A selected box is relabeled too.\nEdit > Classes / Hotkeys to change."))
        ll.addWidget(self._rule())
        ll.addWidget(self._heading("AI assist"))
        ll.addWidget(self._note("Check classes for live predictions on this photo. Confirmed images are never touched."))
        self.ai_box = QVBoxLayout()
        ll.addLayout(self.ai_box)
        b = QPushButton("Clear boxes and retry AI")
        b.clicked.connect(self.clear_and_retry_ai)
        ll.addWidget(b)
        ll.addWidget(self._note("Wipes this image's boxes and predicts again."))
        ll.addWidget(self._rule())
        ll.addWidget(self._heading("Selected box"))
        for text, fn in (("Delete selected box", self.delete_selected_box), ("Clear distance of box", self.clear_selected_distance)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            ll.addWidget(b)
        ll.addWidget(self._note("LiDAR switch (toolbar): hover a box, click to attach its distance, right-click to clear."))
        ll.addWidget(self._note("Drag: new box. Click: select. Double- or right-click: delete."))
        ll.addStretch(1)
        left_scroll.setMinimumWidth(220)
        split.addWidget(left_scroll)
        # centre: the picture
        self.canvas = cv.ImageCanvas(self)
        split.addWidget(self.canvas)
        # right: image navigator
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.addWidget(self._heading("Images"))
        rl.addWidget(self._note("Images still to annotate. [?] = AI draft, not yet confirmed."))
        rl.addWidget(self._heading("Working set", 10))
        self.session_combo = QComboBox()
        self.session_combo.activated.connect(self._on_session_pick)
        rl.addWidget(self.session_combo)
        rl.addWidget(self._note("[A] = every frame of the set is annotated."))
        self.show_annotated = QCheckBox("Show annotated too (review/fix)")
        self.show_annotated.toggled.connect(lambda _c: self._refresh_image_list())
        rl.addWidget(self.show_annotated)
        row = QHBoxLayout()
        for text, fn in (("< Prev", self.prev_image), ("Next >", self.next_image)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        rl.addLayout(row)
        for text, fn in (("Rotate 90° ⟳", self.rotate_current_frame), ("Delete frame...", self.delete_current_frame)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            rl.addWidget(b)
        self.image_list = QListWidget()
        self.image_list.currentRowChanged.connect(self._on_image_select)
        rl.addWidget(self.image_list, 1)
        right.setMinimumWidth(240)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        split.setSizes([230, 800, 260])
        # status bar
        self.status_label = QLabel("No project loaded")
        self.progress_label = QLabel("")
        self.statusBar().addWidget(self.status_label, 1)
        self.statusBar().addPermanentWidget(self.progress_label)
        self._build_menubar()
        self._build_bar()

    def _build_bar(self):
        """Inside OpenPara: the second menu bar is replaced by one bar, as in the other tabs - what this is and which project, then the File /
        Edit / Manage commands as drop-down buttons.  On its own (no OpenPara around it) the annotator keeps its menu bar."""
        self.bar_lbl = None
        if ui_kit is None:
            return
        from PyQt6.QtWidgets import QToolButton
        bar = QWidget()
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(6, 5, 6, 3)
        lay.setSpacing(8)
        lay.addWidget(ui_kit.kind_chip("Annotator", "#b83280"))
        self.bar_lbl = QLabel("")
        self.bar_lbl.setStyleSheet(f"color:{ui_kit.MUTED};")
        lay.addWidget(self.bar_lbl, 1)
        self.bar_buttons = {}
        for key, text, menu, tip in (("file", "File ▾", self.file_menu, "Import videos and datasets, export a dataset, download models, annotate from a tablet"),
                                     ("edit", "Edit ▾", self.edit_menu, "Classes, hotkeys, your name, AI confidence"),
                                     ("manage", "Manage ▾", self.manage_menu, "Sessions, and files deleted outside the annotator")):
            tb = QToolButton()
            tb.setText(text)
            tb.setToolTip(tip)
            tb.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            tb.setMenu(menu)
            ui_kit.menu_button(tb)
            lay.addWidget(tb)
            self.bar_buttons[key] = tb
        ui_kit.top_bar(self, bar)                             # (the menu bar is hidden, not replaced: its menus are what the buttons show)

    def _refresh_bar(self):
        lb = getattr(self, "bar_lbl", None)
        if lb is None:
            return
        try:
            n = len(self.project.list_images())
            name = self.title() if self.path else "A new project (not saved yet)"
            lb.setText(f"<b>{name}</b> - {n} image{'s' if n != 1 else ''}")
        except Exception:
            lb.setText("")

    @staticmethod
    def _heading(text, size=11):
        """A pane heading, the same small capitals as in the rest of the program."""
        lab = QLabel(text.upper())
        lab.setStyleSheet("color:#4a5872; font-size:11px; font-weight:600; letter-spacing:1px; padding-top:2px;")
        return lab

    @staticmethod
    def _note(text):
        lab = QLabel(text)
        lab.setWordWrap(True)
        lab.setStyleSheet("color:#6a7790; font-size:11px;")
        return lab

    @staticmethod
    def _rule():
        f = QFrame()
        f.setFrameShape(QFrame.Shape.HLine)
        return f

    def _build_menubar(self):
        bar = self.menuBar()
        file_m = bar.addMenu("&File")
        self.file_menu = file_m

        def add(menu, text, fn):
            a = QAction(text, self)
            a.triggered.connect(lambda _c=False: fn())
            menu.addAction(a)
            return a
        add(file_m, "Import Video...", self.import_video)
        try:
            import ext
            for text, fn in ext.MENU_ITEMS.get("annotator.file", []):      # add-ons (e.g. Gimble sessions) put their items here
                add(file_m, text, lambda fn=fn: fn(self))
        except ImportError:
            pass
        file_m.addSeparator()
        add(file_m, "Export dataset as zip...", self.export_zip)
        add(file_m, "Import dataset zip...", self.import_zip)
        file_m.addSeparator()
        add(file_m, "Download models from GitHub...", self.download_models)
        add(file_m, "Open in browser (tablet)...", self.open_in_browser)
        edit_m = bar.addMenu("&Edit")
        self.edit_menu = edit_m
        add(edit_m, "Classes...", self.manage_classes)
        add(edit_m, "Hotkeys...", self.edit_hotkeys)
        edit_m.addSeparator()
        add(edit_m, "My name...", self.change_my_name)
        add(edit_m, "AI confidence...", self.set_ai_confidence)
        manage_m = bar.addMenu("&Manage")
        self.manage_menu = manage_m
        add(manage_m, "Sessions...", self.manage_sessions)
        add(manage_m, "Sync Deleted Files", self.sync_deleted_files)

    # ------------------------------------------------------------------ small things
    def set_progress(self, text):
        self.progress_label.setText(text)

    def _announce(self, headline):
        """A short message in the status corner that fades after a few seconds."""
        self.set_progress(headline)
        qtk.later(4000, lambda: None if self._bg_job else self.set_progress(""))

    def _save_cfg(self):
        try:
            sz.save_config(self.cfg)
        except OSError:
            pass

    def _bg_blocked(self):
        """Renaming / deleting moves files the background jobs are using - refuse until they finish."""
        busy = self._bg_job or self._predict_busy
        if busy:
            qtk.info(self, "Busy", "Still working (import, export or AI). Try again in a moment.")
        return bool(busy)

    def _clear_current(self):
        self.current_image_id = None
        self.current_pil_image = None
        self._set_boxes([])
        self.selected_box_index = None
        self._depth_cache = (None, None)

    def closeEvent(self, e):
        w = self._web
        if w is not None:
            try:
                w.stop()
            except Exception:  # noqa: BLE001
                pass
        for d in list(self._dialogs.values()):
            try:
                d.close()
            except Exception:  # noqa: BLE001
                pass
        if self.temp_root:                              # an unsaved project that is closed is gone
            shutil.rmtree(self.temp_root, ignore_errors=True)
        super().closeEvent(e)

    # ------------------------------------------------------------------ AI models: from GitHub, or trained by you
    def _default_models_dir(self):
        return models_dir()

    def _scan_models(self):
        """The models downloaded from GitHub (the newest of each size and kind) go into the toolbar's AI model box."""
        self._inserted = {}
        for key in ml.FOLDERS:
            for v in ml.newest_per_size(ml.list_versions(models_dir(), key)):
                self._inserted[ml.short_label(v)] = self._entry_for(v, v['path'])

    def _models_changed(self):
        self._scan_models()
        self._refresh_ai_choices()

    def first_run_models_prompt(self):
        """Asked once, the first time the program starts on this computer."""
        if self.cfg.get('models_prompt_done'):
            return
        self.cfg['models_prompt_done'] = True
        self._save_cfg()
        self.download_models(first_run=True)

    def download_models(self, first_run=False, fetch=None, install=None):
        return dlg.DownloadModels.open(self, first_run, fetch or md.list_remote, install or md.install)

    def open_in_browser(self):
        """Starts the little web server (once) and shows the address, QR code and this time's access code."""
        w = self._web
        if w is None or not w.running:
            def predict(img_id):
                ma = self.model_assist
                if ma is None:
                    raise RuntimeError("Load an AI model on the computer first (the AI model box at the top).")
                with self._web_ai_lock:
                    return self._map_model_classes(ma.predict_boxes(self.project.image_path(img_id), conf_threshold=self.model_conf))
            self._web_ai_lock = threading.Lock()
            w = wm.WebShare(self.project, predict=predict, on_change=lambda: self.post(self._refresh_image_list))
            try:
                w.start()
            except OSError as e:
                qtk.error(self, "Open in browser", f"Couldn't start: {e}")
                return None
            self._web = w
        return dlg.WebWindow.open(self, w)

    @staticmethod
    def _entry_for(v, local_path):
        return {'kind': 'scratch' if v['key'] == 'scratch' else 'helper', 'size': v['size'], 'label': ml.short_label(v),
                'dir': os.path.dirname(local_path), 'path': local_path}

    # ------------------------------------------------------------------ hotkeys
    def _hotkey_label(self, idx):
        return self.hotkeys.label(f"class:{idx}")

    def _hotkey_actions(self):
        return {"delete_box": self.delete_selected_box, "toggle_pick": self._toggle_pick, "toggle_depth": self._toggle_pick,
                "prev_image": self.prev_image, "next_image": self.next_image, "fit_view": self.fit_view}

    def _bind_hotkeys(self):
        """(Re)creates every shortcut from self.hotkeys; run again whenever a key or the class list changes."""
        for s in self.shortcuts:
            s.setEnabled(False)
            s.setParent(None)
        self.shortcuts = []
        fixed = self._hotkey_actions()
        for action, _title in self.hotkeys.actions([""] * len(self.project.classes)):
            b = self.hotkeys.get(action)
            if not b:
                continue
            sc = QShortcut(qtk.to_qt_sequence(b), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            if action.startswith("class:"):
                sc.activated.connect(lambda i=int(action[6:]): self._set_active_class(i))
            else:
                sc.activated.connect(fixed[action])
            self.shortcuts.append(sc)

    def _update_pick_check_text(self):
        keys = [self.hotkeys.label(a) for a in ("toggle_pick", "toggle_depth")]
        keys = "/".join(k for k in keys if k)
        self.pick_check.setText("LiDAR dots + pick distance" + (f" ({keys})" if keys else ""))

    def _update_fit_button_text(self):
        key = self.hotkeys.label("fit_view")
        self.fit_button.setText("Fit to screen" + (f" ({key})" if key else ""))

    def _hotkeys_changed(self):
        """Save, rebind and refresh everything that shows a key."""
        try:
            self.project.save_hotkeys(self.hotkeys.to_dict())
        except OSError as e:
            qtk.error(self, "Hotkeys", f"Could not save the hotkeys:\n{e}")
        self._bind_hotkeys()
        self._update_pick_check_text()
        self._update_fit_button_text()
        self._build_ai_assist_checkboxes(keep_checked=self._checked_names())
        self._refresh_class_list()
        if self._classes_refresh:
            self._classes_refresh()

    def _apply_hotkey(self, action, binding):
        """Gives `action` the key `binding` (None clears it). Returns a one-line note for the Hotkeys window."""
        lost = self.hotkeys.set(action, binding, len(self.project.classes))
        self._hotkeys_changed()
        titles = dict(self.hotkeys.actions(self.project.classes))
        text = f"{titles.get(action, action)}: " + (hk.label(binding) if binding else "no key")
        if lost:
            text += "   (taken away from: " + ", ".join(titles.get(a, a) for a in lost) + ")"
        return text

    def edit_hotkeys(self):
        return dlg.HotkeysDialog.open(self)

    # ------------------------------------------------------------------ classes
    def _checked_names(self):
        return {self.project.classes[i] for i, c in self.ai_class_boxes.items() if c.isChecked() and i < len(self.project.classes)}

    def _build_ai_assist_checkboxes(self, keep_checked=()):
        """One checkbox per class; rebuilt whenever the class list changes. Classes in keep_checked stay checked; all others start
        unchecked: nothing gets AI-touched until you opt a class in."""
        while self.ai_box.count():
            it = self.ai_box.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.ai_class_boxes = {}
        for i, name in enumerate(self.project.classes):
            key = self._hotkey_label(i)
            cb = QCheckBox((f"[{key}] " if key else "") + name)
            cb.setChecked(name in keep_checked)
            cb.toggled.connect(lambda _c: self._on_ai_assist_toggle())
            self.ai_box.addWidget(cb)
            self.ai_class_boxes[i] = cb

    def _refresh_class_list(self):
        self.class_list.blockSignals(True)
        self.class_list.clear()
        for i, name in enumerate(self.project.classes):
            key = self._hotkey_label(i)
            it = QListWidgetItem((f"[{key}] " if key else "    ") + name)
            it.setForeground(QColor(color_for_class(i)))
            self.class_list.addItem(it)
        if self.project.classes:
            idx = min(self.current_class_id, len(self.project.classes) - 1)
            self.class_list.setCurrentRow(idx)
            self.current_class_id = idx
        self.class_list.blockSignals(False)

    def _set_active_class(self, idx):
        """Sets the class new boxes are drawn with; a selected box is relabeled in place too (one key does both)."""
        if not (0 <= idx < len(self.project.classes)):
            return
        self.current_class_id = idx
        self.class_list.blockSignals(True)
        self.class_list.setCurrentRow(idx)
        self.class_list.blockSignals(False)
        if self.selected_box_index is not None and self.selected_box_index < len(self.boxes):
            _, xc, yc, w, h = self.boxes[self.selected_box_index]
            self.boxes[self.selected_box_index] = (idx, xc, yc, w, h)
            self._save_current_boxes()
        self.canvas.redraw()
        self._update_status()

    def _on_class_select(self, row):
        if row >= 0:
            self._set_active_class(row)

    def _after_class_change(self, headline, boxes_changed=False, was_checked=()):
        """Everything that shows classes follows the project's list: sidebar, AI checkboxes (kept by NAME), the open image, exports."""
        n = len(self.project.classes)
        self.current_class_id = max(0, min(self.current_class_id, n - 1))
        self._bind_hotkeys()
        if self._hotkeys_refresh:
            self._hotkeys_refresh()
        self._refresh_class_list()
        self._build_ai_assist_checkboxes(keep_checked=set(was_checked))
        if boxes_changed:
            self._depth_cache = (None, None)
            if self.current_image_id is not None and self.current_image_id in self.project.manifest['images']:
                self.load_image(self.current_image_id)
            else:
                self.current_image_id = None
                self.current_pil_image = None
                self._set_boxes([])
                self._refresh_image_list()
            self.selected_box_index = None
        self.canvas.redraw()
        self._update_status()
        if self._classes_refresh:
            self._classes_refresh()
        self._announce(headline)

    def manage_classes(self):
        return dlg.ClassesDialog.open(self)

    # ------------------------------------------------------------------ image list / navigation
    def _is_foreign_owner(self, pid):
        return bool(pid) and bool(self.me) and pid != self.me['id']

    def _is_hidden_info(self, info):
        """True for an image of somebody else whose data you have not opened with Access."""
        pid = info.get('owner_id')
        return self._is_foreign_owner(pid) and pid not in self.access_people

    def _hidden_sessions(self):
        if not self.me:
            return set()
        return {info['session_id'] for info in self.project.manifest['images'].values()
                if info.get('session_id') and self._is_hidden_info(info)}

    def _visible_image_ids(self):
        """The sidebar is a work queue: once an image is annotated it drops off, so what is left is what still needs doing. Exceptions:
        'Show annotated too' brings back the full list, and the open image stays until you navigate away from it."""
        ids = self.project.list_images()
        imgs = self.project.manifest['images']
        if self.me:
            ids = [i for i in ids if not self._is_hidden_info(imgs[i])]    # other people's data stays shut until Access
        if self.active_session is not None:
            ids = [i for i in ids if imgs[i].get('session_id') == self.active_session]
        if self.show_annotated.isChecked():
            return ids
        return [i for i in ids if i == self.current_image_id or not self.project.is_annotated(i)]

    def _refresh_session_combo(self):
        """'All sets' plus one entry per imported set, marked [A] once every frame in it is annotated, with (annotated/total)."""
        prog = self.project.session_progress()
        hidden = self._hidden_sessions()
        prog = {sid: v for sid, v in prog.items() if sid not in hidden}
        if self.active_session is not None and self.active_session not in prog:
            self.active_session = None
        keys, labels = [None], []
        tot = sum(t for t, _ in prog.values())
        ann = sum(a for _, a in prog.values())
        labels.append(f"All sets  ({ann}/{tot})")
        for sid in sorted(prog):
            t, a = prog[sid]
            keys.append(sid)
            labels.append(("[A] " if t and a == t else "") + f"{sid}  ({a}/{t})")
        self._session_keys = keys
        self.session_combo.blockSignals(True)
        self.session_combo.clear()
        self.session_combo.addItems(labels)
        self.session_combo.setCurrentIndex(keys.index(self.active_session))
        self.session_combo.blockSignals(False)

    def _on_session_pick(self, i):
        if 0 <= i < len(self._session_keys):
            self.set_active_session(self._session_keys[i])

    def set_active_session(self, sid):
        """Show only this set's frames (None = every set). A fully annotated set opens in review mode."""
        self.active_session = sid
        self._clear_current()
        if not self._visible_image_ids() and self.project.list_images():
            self.show_annotated.blockSignals(True)
            self.show_annotated.setChecked(True)       # nothing left to do here - show everything to review
            self.show_annotated.blockSignals(False)
        self._refresh_image_list()
        self.canvas.redraw()
        self._update_status()

    def _refresh_image_list(self):
        self._refresh_session_combo()
        ids = self._visible_image_ids()
        self.image_list.blockSignals(True)
        self.image_list.clear()
        for img_id in ids:
            mark = "✓" if self.project.is_annotated(img_id) else ("?" if self.project.is_ai_pending(img_id) else " ")
            self.image_list.addItem(f"[{mark}] {img_id}")
        if self.current_image_id in ids:
            self.image_list.setCurrentRow(ids.index(self.current_image_id))
        self.image_list.blockSignals(False)
        if self.current_image_id is None and ids:
            self.load_image(ids[0])

    def _on_image_select(self, row):
        if row < 0:
            return
        ids = self._visible_image_ids()
        if row < len(ids) and ids[row] != self.current_image_id:
            self.load_image(ids[row])

    def prev_image(self):
        ids = self._visible_image_ids()
        if ids and self.current_image_id in ids:
            i = ids.index(self.current_image_id)
            if i > 0:
                self.load_image(ids[i - 1])

    def next_image(self):
        ids = self._visible_image_ids()
        if ids and self.current_image_id in ids:
            i = ids.index(self.current_image_id)
            if i < len(ids) - 1:
                self.load_image(ids[i + 1])

    def rotate_current_frame(self):
        """Rotate the open image 90 degrees clockwise (Project.rotate_image rewrites the file and remaps the boxes); reloads from disk."""
        img_id = self.current_image_id
        if img_id is None:
            return
        self.project.rotate_image(img_id, clockwise=True)
        self._depth_cache = (None, None)      # depth was rotated along with the image
        self.zoom, self.view_center = 1.0, None
        self.current_pil_image = Image.open(self.project.image_path(img_id)).convert("RGB")
        self._set_boxes(self.project.get_boxes(img_id), self.project.get_distances(img_id))
        self.selected_box_index = None
        self.canvas.redraw()
        self._update_status()

    def delete_current_frame(self):
        """Permanently deletes the open image, its label file and distorted variants; confirms first (no undo). Then lands on
        whatever took its place in the current view."""
        img_id = self.current_image_id
        if img_id is None:
            return
        detail = f"'{img_id}'"
        if self.boxes:
            status = "confirmed" if self.project.is_annotated(img_id) else "an unconfirmed AI draft"
            detail += f" ({len(self.boxes)} box(es), {status})"
        if not qtk.yesno(self, "Delete this frame?", f"Delete {detail} and its files? This can't be undone."):
            return
        ids = self._visible_image_ids()
        pos = ids.index(img_id) if img_id in ids else None
        self.project.delete_image(img_id)
        self._clear_current()
        remaining = self._visible_image_ids()
        if remaining:
            self.load_image(remaining[pos] if pos is not None and pos < len(remaining) else remaining[-1])
        else:
            self._refresh_image_list()
            self.canvas.redraw()
            self._update_status()

    def load_image(self, img_id):
        self.current_image_id = img_id
        self.zoom, self.view_center = 1.0, None
        self.current_pil_image = Image.open(self.project.image_path(img_id)).convert("RGB")
        self._set_boxes(self.project.get_boxes(img_id), self.project.get_distances(img_id))
        self.selected_box_index = None
        self._refresh_image_list()
        self.canvas.redraw()
        self._update_status()
        self._trigger_live_predict(img_id)

    # ------------------------------------------------------------------ view (zoom / pan)
    def set_view(self, zoom, center):
        """Applies a zoom + view centre (image px) and stores the clamped result."""
        self.zoom = max(1.0, min(ZOOM_MAX, zoom))
        self.view_center = center if self.zoom > 1 else None
        if self.current_pil_image is not None and self.zoom > 1:
            scale, (off_x, off_y), _ = self.canvas.fit_geometry()          # re-read: this applies the clamping
            cw, ch = max(self.canvas.width(), 1), max(self.canvas.height(), 1)
            self.view_center = ((cw / 2 - off_x) / scale, (ch / 2 - off_y) / scale)
        self.canvas.redraw()

    def fit_view(self):
        """Back to the whole image in the window."""
        self.zoom, self.view_center = 1.0, None
        if self.current_pil_image is not None:
            self.canvas.redraw()

    def zoom_at(self, cx, cy, steps):
        """Zoom in (steps > 0) or out around canvas point (cx, cy): the spot under the pointer stays put."""
        if self.current_pil_image is None:
            return
        new_zoom = max(1.0, min(ZOOM_MAX, self.zoom * (ZOOM_STEP ** steps)))
        if new_zoom == self.zoom:
            return
        ix, iy = self.canvas.to_image_px(cx, cy)
        self.zoom = new_zoom
        if new_zoom <= 1:
            self.fit_view()
            return
        cw, ch = max(self.canvas.width(), 1), max(self.canvas.height(), 1)
        iw, ih = self.current_pil_image.size
        scale = min(cw / iw, ch / ih) * new_zoom
        self.set_view(new_zoom, (ix - (cx - cw / 2) / scale, iy - (cy - ch / 2) / scale))

    def on_pan_drag(self, dx, dy):
        if self.current_pil_image is None or self.zoom <= 1:
            return
        scale = self.canvas.fit_geometry()[0]
        vcx, vcy = self.view_center
        self.set_view(self.zoom, (vcx - dx / scale, vcy - dy / scale))

    # ------------------------------------------------------------------ depth
    def current_depth_points(self):
        """(u, v, z_m) arrays for the open image's LiDAR returns, or None; cached per image (rotation clears the cache)."""
        img_id = self.current_image_id
        if img_id is None:
            return None
        if self._depth_cache[0] != img_id:
            self._depth_cache = (img_id, self.project.depth_points(img_id))
        return self._depth_cache[1]

    # ------------------------------------------------------------------ boxes: mouse gestures (called by the canvas)
    def box_at(self, cx, cy):
        """Index of the smallest box (by area) containing this canvas point, or None, so a small box inside a big one wins."""
        ix, iy = self.canvas.to_image_px(cx, cy)
        img_w, img_h = self.current_pil_image.size
        best_idx, best_area = None, None
        for i, (cls, xc, yc, w, h) in enumerate(self.boxes):
            x1, y1, x2, y2 = ac.yolo_box_to_pixel(xc, yc, w, h, img_w, img_h)
            if x1 <= ix <= x2 and y1 <= iy <= y2:
                area = (x2 - x1) * (y2 - y1)
                if best_area is None or area < best_area:
                    best_area, best_idx = area, i
        return best_idx

    def on_canvas_release(self, x0, y0, x, y):
        """A real drag draws a new box (even over existing ones); too small a movement is a click: pick a distance in LiDAR mode, else
        select what is underneath (or clear the selection)."""
        if self.current_pil_image is None:
            return
        if abs(x - x0) < 4 or abs(y - y0) < 4:
            if self.pick_check.isChecked():
                self._assign_pick(x, y)
                return
            self.selected_box_index = self.box_at(x, y)
            self.canvas.redraw()
            return
        if not self.project.classes:
            qtk.info(self, "Add a class first", "Add at least one class before drawing boxes.")
            return
        ix0, iy0 = self.canvas.to_image_px(x0, y0)
        ix1, iy1 = self.canvas.to_image_px(x, y)
        img_w, img_h = self.current_pil_image.size
        xc, yc, w, h = ac.pixel_box_to_yolo(ix0, iy0, ix1, iy1, img_w, img_h)
        self.boxes.append((self.current_class_id, xc, yc, w, h))
        self.box_dist.append(None)
        self.selected_box_index = None
        self._save_current_boxes()
        self.canvas.redraw()

    def on_canvas_double_click(self, x, y):
        if self.current_pil_image is None or self.pick_check.isChecked():
            return      # in pick mode clicks assign distances; deleting needs the button or right-click
        self._delete_box_index(self.box_at(x, y))

    def on_canvas_right_click(self, x, y):
        """Right-click a box to delete it (in pick mode: clear that box's distance instead, never the box)."""
        if self.current_pil_image is None:
            return
        if self.pick_check.isChecked():
            self._clear_distance_index(self.box_at(x, y))
        else:
            self._delete_box_index(self.box_at(x, y))

    def _delete_box_index(self, index):
        """The one place that removes a box and fixes the selection (removing index i shifts later boxes down by one)."""
        if index is None or not (0 <= index < len(self.boxes)):
            return
        del self.boxes[index]
        del self.box_dist[index]
        if self.selected_box_index == index:
            self.selected_box_index = None
        elif self.selected_box_index is not None and self.selected_box_index > index:
            self.selected_box_index -= 1
        self._save_current_boxes()
        self.canvas.redraw()

    def delete_selected_box(self):
        self._delete_box_index(self.selected_box_index)

    def _save_current_boxes(self):
        if self.current_image_id is None:
            return
        self._fit_dist()
        self.project.set_boxes(self.current_image_id, self.boxes, distances=self.box_dist)
        self._refresh_image_list()          # the checkmark is now right; the open image stays pinned in the list
        self._update_status()

    def _set_boxes(self, boxes, dists=None):
        """The one place the box list and its parallel distance list are replaced together, so they never drift apart."""
        self.boxes = list(boxes)
        self.box_dist = list(dists) if dists is not None else []
        self._fit_dist()

    def _fit_dist(self):
        n = len(self.boxes)
        self.box_dist = (self.box_dist + [None] * n)[:n]

    # ------------------------------------------------------------------ per-box LiDAR distance picking
    def _toggle_pick(self):
        self.pick_check.setChecked(not self.pick_check.isChecked())

    def _on_pick_toggle(self, on):
        self.canvas.setCursor(Qt.CursorShape.CrossCursor)
        self.canvas.hover = None
        self.canvas.redraw()

    def _pick_candidate(self, cx, cy):
        """(box_index, u, v, z_m): the nearest LiDAR return INSIDE the box under the cursor within PICK_RADIUS_PX, or None."""
        if self.current_pil_image is None:
            return None
        idx = self.box_at(cx, cy)
        pts = self.current_depth_points()
        if idx is None or pts is None or len(pts[0]) == 0:
            return None
        u, v, z = pts
        img_w, img_h = self.current_pil_image.size
        _, xc, yc, w, h = self.boxes[idx]
        x1, y1, x2, y2 = ac.yolo_box_to_pixel(xc, yc, w, h, img_w, img_h)
        inside = (u >= x1) & (u <= x2) & (v >= y1) & (v <= y2)
        if not inside.any():
            return None
        ix, iy = self.canvas.to_image_px(cx, cy)
        ui, vi, zi = u[inside], v[inside], z[inside]
        d2 = (ui - ix) ** 2 + (vi - iy) ** 2
        k = int(np.argmin(d2))
        if (d2[k] ** 0.5) * self.canvas.scale > PICK_RADIUS_PX:
            return None
        return idx, int(ui[k]), int(vi[k]), float(zi[k])

    def on_canvas_motion(self, x, y):
        c = self.canvas
        had = c.hover is not None
        c.hover = None
        if self.pick_check.isChecked() and self.current_pil_image is not None:
            cand = self._pick_candidate(x, y)
            if cand is None:
                idx = self.box_at(x, y)
                if self.current_depth_points() is None:
                    msg = "no LiDAR depth for this image"
                elif idx is None:
                    msg = "hover inside a box"
                else:
                    msg = "no LiDAR point near here"
                c.hover = ("label", (x + 14, y + 14, msg, "#bbbbbb"))
            else:
                _idx, u, v, z = cand
                px, py = c.to_canvas(u, v)
                c.hover = ("dot", (px, py, f"{z:.2f} m  (click to attach)"))
        if had or c.hover is not None:
            c.update()

    def _assign_pick(self, cx, cy):
        cand = self._pick_candidate(cx, cy)
        if cand is None:
            self.set_progress("Hover inside a box, near a LiDAR point, then click." if self.box_at(cx, cy) is None
                              else "No LiDAR point close enough inside that box.")
            qtk.later(2500, lambda: None if self._bg_job else self.set_progress(""))
            return
        idx, u, v, z = cand
        self._fit_dist()
        self.box_dist[idx] = {"distance_m": round(z, 3), "u": u, "v": v}
        self.selected_box_index = idx
        self._save_current_boxes()
        self.canvas.redraw()

    def _clear_distance_index(self, index):
        if index is None or not (0 <= index < len(self.boxes)):
            return
        self._fit_dist()
        if self.box_dist[index] is None:
            return
        self.box_dist[index] = None
        self._save_current_boxes()
        self.canvas.redraw()

    def clear_selected_distance(self):
        self._clear_distance_index(self.selected_box_index)

    # ------------------------------------------------------------------ sessions
    def manage_sessions(self):
        return dlg.SessionsDialog.open(self)

    def thin_set(self, sid, parent=None):
        return dlg.ThinDialog.open(self, sid, parent)

    # ------------------------------------------------------------------ sharing
    def _ensure_me(self, parent=None):
        """Your name, asked once and remembered (stays on this computer). None if you cancel."""
        if self.me:
            return self.me
        msg = ("What's your name?\n\nAsked once. It is stamped on the data you export, so everyone can tell whose annotations are "
               "whose.\n(no spaces or dots - use _ or -)")
        while True:
            name = qtk.ask_string(parent or self, "Your name", msg)
            if name is None:
                return None
            err = sz.person_name_error(name)
            if err is None:
                break
            qtk.error(parent or self, "Can't use that name", err)
        self.me = sz.set_identity(self.cfg, name)
        self._save_cfg()
        self.project.editor_id = self.me['id']
        self.project.manifest.setdefault('people', {})[self.me['id']] = self.me['name']
        self.project.save_manifest()
        return self.me

    def change_my_name(self):
        if not self.me:
            self._ensure_me()
            return
        while True:
            name = qtk.ask_string(self, "Your name", "Your name (your data keeps its owner id, so changing this only changes how it "
                                  "is shown):", self.me['name'])
            if name is None:
                return
            err = sz.person_name_error(name)
            if err is None:
                break
            qtk.error(self, "Can't use that name", err)
        self.me = sz.set_identity(self.cfg, name)
        self._save_cfg()
        self.project.manifest.setdefault('people', {})[self.me['id']] = self.me['name']
        self.project.save_manifest()

    def _share_fail(self, title, err):
        self._bg_job = False
        self.set_progress("")
        qtk.error(self, title, str(err))

    # ---- the dataset as a zip: export it, or merge somebody's zip into this project
    def export_zip(self):
        """All annotated images (with boxes, distances and depth) in ONE zip you can send to someone. Generated distortions are left out."""
        if self._bg_blocked():
            return
        if not sz.shareable_ids(self.project):
            qtk.info(self, "Nothing to export", "There are no annotated images yet. Annotate (or confirm) some images first.")
            return
        me = self._ensure_me()
        if not me:
            return
        stem = os.path.basename(self.path.rstrip("/\\")) if self.path else "dataset"
        stem = stem[:-len(".annotator")] if stem.lower().endswith(".annotator") else stem
        path, _ = QFileDialog.getSaveFileName(self, "Export dataset as zip", (stem or "dataset") + ".zip", "Dataset zip (*.zip)")
        if not path:
            return
        if not path.lower().endswith(".zip"):
            path += ".zip"
        self._bg_job = True
        self.set_progress("Exporting...")

        def worker():
            try:
                res = dz.export_zip(self.project, path, me, progress_cb=lambda d, t: self.post(lambda: self.set_progress(f"Exporting: {d}/{t}")))
            except Exception as e:  # noqa: BLE001
                err = e
                self.post(lambda: self._share_fail("Export failed", err))
                return
            self.post(lambda: self._export_done(res))
        threading.Thread(target=worker, daemon=True).start()

    def _export_done(self, res):
        self._bg_job = False
        self.set_progress("")
        qtk.info(self, "Exported", f"Exported {res['count']} annotated image(s) ({res['with_depth']} with LiDAR depth) to\n{res['path']}\n\n"
                 "Generated distorted copies are not included; they are made again where the zip is imported.")

    def import_zip(self):
        """Merges a dataset zip into this project: nothing is added twice, and images annotated differently on both sides are your choice."""
        if self._bg_blocked():
            return
        if not self.ensure_saved("Importing a dataset zip puts its images in the project."):
            return
        path, _ = QFileDialog.getOpenFileName(self, "Dataset zip to merge in", "", "Dataset zip (*.zip)")
        if not path:
            return
        me = self._ensure_me()
        if not me:
            return
        work = tempfile.mkdtemp(prefix="zip_", dir=os.path.dirname(untitled_dir()))
        self._bg_job = True
        self.set_progress("Reading the zip...")

        def worker():
            try:
                plan = dz.plan_zip(self.project, path, work, me)
                if plan['bad_classes']:
                    raise ValueError("The zip has class names this project can't use: " + ", ".join(plan['bad_classes']))
            except Exception as e:  # noqa: BLE001
                err = e
                self.post(lambda: (shutil.rmtree(work, ignore_errors=True), self._share_fail("Import failed", err)))
                return
            self.post(lambda: self._zip_planned(plan, me, work))
        threading.Thread(target=worker, daemon=True).start()

    def _zip_planned(self, plan, me, work):
        choices = None                                          # None = whoever edited last wins
        n = len(plan['conflicts'])
        if n:
            box = QMessageBox(self)
            box.setWindowTitle("Same images, annotated differently")
            box.setText(f"{n} image(s) are annotated differently in your project and in the zip.\n\nWhich version should be kept?")
            mine = box.addButton("Keep mine", QMessageBox.ButtonRole.AcceptRole)
            theirs = box.addButton("Take the zip's", QMessageBox.ButtonRole.AcceptRole)
            newest = box.addButton("Newest edit wins", QMessageBox.ButtonRole.AcceptRole)
            cancel = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            clicked = box.clickedButton()
            if clicked is cancel or clicked is None:
                shutil.rmtree(work, ignore_errors=True)
                self._bg_job = False
                self.set_progress("")
                return
            if clicked is mine:
                choices = {c['uid']: 'mine' for c in plan['conflicts']}
            elif clicked is theirs:
                choices = {c['uid']: 'theirs' for c in plan['conflicts']}
        self.set_progress("Importing...")

        def worker():
            try:
                report = dz.apply_zip(self.project, plan, choices, me, progress_cb=lambda d, t: self.post(lambda: self.set_progress(f"Importing: {d}/{t}")))
            except Exception as e:  # noqa: BLE001
                err = e
                self.post(lambda: (shutil.rmtree(work, ignore_errors=True), self._share_fail("Import failed", err)))
                return
            shutil.rmtree(work, ignore_errors=True)
            self.post(lambda: self._import_finished(plan, report))
        threading.Thread(target=worker, daemon=True).start()

    def _import_finished(self, plan, report):
        self._bg_job = False
        self.set_progress("")
        for pid in {e['owner_id'] for e in plan['new']} | {e['owner_id'] for e, _ in plan['update']}:
            if self._is_foreign_owner(pid):
                self.access_people.add(pid)           # you asked for their data: it is open
        self._depth_cache = (None, None)
        if report['added_classes']:
            self._after_class_change("")
        self._refresh_session_combo()
        self._refresh_image_list()
        if self.current_image_id in report['changed_ids']:
            self.load_image(self.current_image_id)
        if self._sessions_refresh:
            self._sessions_refresh()
        self._update_status()
        parts = []
        if report['new']:
            parts.append(f"{report['new']} new image(s)")
        if report['updated']:
            parts.append(f"{report['updated']} image(s) updated")
        if report['kept_mine'] or report['kept_local']:
            parts.append(f"{report['kept_mine'] + report['kept_local']} of your version(s) kept")
        if report['took_theirs']:
            parts.append(f"{report['took_theirs']} replaced by the zip's version")
        if report['duplicates']:
            parts.append(f"{report['duplicates']} duplicate picture(s) skipped")
        if report['added_classes']:
            parts.append("new class(es): " + ", ".join(report['added_classes']))
        qtk.info(self, "Import complete", ("Imported: " + "; ".join(parts) if parts else "Nothing new to import")
                 + f". ({report['same']} already identical.) Pick it in the Working set box.")

    # ------------------------------------------------------------------ dataset location
    # ------------------------------------------------------------------ import
    def import_video(self):
        """One or more video files; each becomes its own set (every Nth frame saved). Videos have no LiDAR depth."""
        if not self.ensure_saved("Importing a video puts its frames in the project."):
            return
        paths = qtk.ask_files(self, "Select video file(s)", "Video files (" + " ".join("*" + e for e in ac.Project.VIDEO_EXTS) + ");;All files (*.*)")
        if not paths:
            return
        try:
            n, fps, w, h = ac.Project.video_info(paths[0])
        except Exception as e:  # noqa: BLE001
            qtk.error(self, "Can't read video", str(e))
            return
        secs = (n / fps) if fps > 0 and n > 0 else 0
        stride = qtk.ask_int(self, "Frame interval", f"{os.path.basename(paths[0])}: {w}x{h}, {fps:.1f} fps, {n} frames"
                             + (f" ({secs:.0f} s)" if secs else "") + ".\n\nKeep one frame every N frames. Neighbouring frames are "
                             f"near-duplicates, so\n{max(1, round(fps / 3)) if fps > 0 else 10} (about 3 frames per second) is a good "
                             "start; 1 keeps every frame:", max(1, round(fps / 3)) if fps > 0 else 10, 1)
        if not stride:
            return
        names = {}
        for p in paths:
            default = self.project.find_video_session(p) or ac.Project.default_video_session_name(p)
            if len(paths) == 1:
                nm = qtk.ask_string(self, "Set name", "Name for this set of frames:", default)
                if not nm:
                    return
                default = nm.strip()
            names[p] = default
        if self._bg_job:
            qtk.info(self, "Busy", "Wait for the current import to finish first.")
            return
        self._bg_job = True
        self.set_progress("Importing video frames: 0")

        def worker():
            added = skipped = 0
            made, errors = [], []
            for p in paths:
                try:
                    r = self.project.import_video(p, stride=stride, session_name=names[p],
                                                  progress_cb=lambda d, t: self.post(lambda: self.set_progress(f"Importing video frames: {d}/{t}")))
                    added += len(r['new_ids'])
                    skipped += r['skipped_existing']
                    made.append(r['session_id'])
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{os.path.basename(p)}: {e}")

            def done():
                self.set_progress("")
                self._bg_job = False
                self._refresh_image_list()
                if self._sessions_refresh:
                    self._sessions_refresh()
                self._update_status()
                lines = [f"Added {added} frame(s) in {len(made)} set(s)" + (f": {', '.join(made)}" if made else "") + "."]
                if skipped:
                    lines.append(f"{skipped} frame(s) were already in the project and were left alone.")
                if made:
                    lines.append("Pick the set from the Working set box on the right.")
                if errors:
                    lines.append("\nProblems:\n" + "\n".join(errors))
                (qtk.warn if errors and not made else qtk.info)(self, "Video import", "\n".join(lines))
            self.post(done)
        threading.Thread(target=worker, daemon=True).start()

    def sync_deleted_files(self):
        """Also runs every time a project is opened; this is for catching up without reopening."""
        removed = self.project.reconcile_deleted_images()
        if removed:
            if self.current_image_id in removed:
                self._clear_current()
            self._refresh_image_list()
            self._update_status()
            qtk.info(self, "Sync complete", f"Cleaned up tracking for {len(removed)} deleted image(s).")
        else:
            qtk.info(self, "Sync complete", "Nothing to clean up - every tracked image still exists on disk.")

    # ------------------------------------------------------------------ model-assisted labeling
    # Load a model once, check the classes you want AI help with; then every time you land on an unannotated image (or toggle a
    # checkbox) ONLY the current photo is (re-)predicted, filtered to what is checked. Predictions go through
    # Project.set_ai_predicted_boxes(), which never marks an image annotated: you fix it or press Confirm image.
    def _refresh_ai_choices(self, entries=None):
        """Fills the AI model box with the trained model slots that exist right now."""
        try:
            entries = entries if entries is not None else mr.discover(RUNS_DIR)
        except Exception:  # noqa: BLE001
            entries = []
        self._ai_entries = {e['label']: e for e in entries}
        for label, e in self._inserted.items():
            self._ai_entries.setdefault(label, e)
        labels = AI_CHOICES + [e['label'] for e in entries] + [l for l in sorted(self._inserted) if l not in {e['label'] for e in entries}]
        cur = self.ai_choice.currentText()
        self.ai_choice.blockSignals(True)
        self.ai_choice.clear()
        self.ai_choice.addItems(labels)
        if cur in labels:
            self.ai_choice.setCurrentText(cur)
        self.ai_choice.blockSignals(False)

    def _identify_old_models_in_background(self):
        """An older single-folder run has to be opened once to learn its size; do that off the GUI thread."""
        def worker():
            try:
                entries = mr.discover(RUNS_DIR, detect_legacy=True)
            except Exception:  # noqa: BLE001
                return
            self.post(lambda: self._refresh_ai_choices(entries))
        threading.Thread(target=worker, daemon=True).start()

    def _set_choice(self, text):
        self.ai_choice.blockSignals(True)
        self.ai_choice.setCurrentText(text)
        self.ai_choice.blockSignals(False)

    def load_ai_model(self, kind=None):
        """Loads the model picked in the toolbar box (a downloaded one, or one you trained). Switching re-predicts the current photo."""
        if kind:
            if self.ai_choice.findText(kind) < 0:
                self._refresh_ai_choices()
            self._set_choice(kind)
        choice = self.ai_choice.currentText()
        self.model_assist = None
        self._ai_kind = None
        if choice == AI_CHOICES[0]:
            self.ai_status.setText("No model loaded")
            return
        self._scan_models()
        self._refresh_ai_choices()
        entry = self._ai_entries.get(choice)
        if entry is None:
            self._set_choice(AI_CHOICES[0])
            self.ai_status.setText("No model loaded")
            qtk.error(self, "Model not found", f"'{choice}' is not there (any more). Download models with File > Download models from GitHub.")
            return
        path = entry['path']
        if not os.path.exists(path):
            self._set_choice(AI_CHOICES[0])
            self.ai_status.setText("No model loaded")
            qtk.error(self, "Model file missing", f"The model file is gone:\n{path}")
            return
        try:
            import gimble_assist
        except ImportError as e:
            self._set_choice(AI_CHOICES[0])
            self.ai_status.setText("No model loaded")
            qtk.error(self, "Missing package", f"{e}\n\nModel-assisted labeling needs ultralytics and torch:\n\n    pip install ultralytics")
            return
        self.ai_status.setText("Loading model...")
        kind_now = choice

        def worker():
            try:
                if entry['kind'] == 'scratch':
                    assist = gimble_assist.GimbleAssist(path)
                else:
                    assist = gimble_assist.HelperAssist(path)
                error = None
            except Exception as e:  # noqa: BLE001
                assist, error = None, str(e)

            def done():
                if self.ai_choice.currentText() != kind_now:
                    return                      # the user already picked something else
                if error:
                    self._set_choice(AI_CHOICES[0])
                    self.ai_status.setText("No model loaded")
                    qtk.error(self, "Couldn't load checkpoint", error)
                    return
                self.model_assist = assist
                self._ai_kind = kind_now
                self._refresh_ai_status()
                if self.current_image_id is not None:
                    self._trigger_live_predict(self.current_image_id)
            self.post(done)
        threading.Thread(target=worker, daemon=True).start()

    def _refresh_ai_status(self):
        if self.model_assist is None:
            self.ai_status.setText("No model loaded")
            return
        kind = self._ai_kind
        desc = f"{(kind or 'model').lower()}: " + self.model_assist.describe()
        self.ai_status.setText(f"{desc} (conf {self.model_conf:.2f})")

    def set_ai_confidence(self):
        conf = qtk.ask_float(self, "Confidence threshold", "Only keep predictions at or above this confidence (0-1).\n"
                             "Lower catches more but with more false positives:", self.model_conf, 0.0, 1.0, 2)
        if conf is None:
            return
        self.model_conf = conf
        self._refresh_ai_status()
        if self.model_assist is not None and self.current_image_id is not None:
            self._trigger_live_predict(self.current_image_id)

    def _map_model_classes(self, boxes):
        """The model numbers its classes its own way; match by NAME and drop classes the project doesn't have."""
        names = getattr(self.model_assist, 'class_names', None)
        if not names:
            return boxes
        out = []
        for (c, xc, yc, w, h) in boxes:
            if 0 <= c < len(names) and names[c] in self.project.classes:
                out.append((self.project.classes.index(names[c]), xc, yc, w, h))
        return out

    def _selected_ai_classes(self):
        return {i for i, c in self.ai_class_boxes.items() if c.isChecked()}

    def _on_ai_assist_toggle(self):
        if self.current_image_id is not None:
            self._trigger_live_predict(self.current_image_id)

    def _trigger_live_predict(self, img_id):
        """(Re-)predicts exactly one image. One prediction at a time; a request that arrives meanwhile replaces any queued one."""
        if self.model_assist is None or self.project.is_annotated(img_id):
            return          # no model / confirmed (human ground truth is never touched again)
        if self._predict_busy:
            self._predict_queued_img_id = img_id
            return
        self._run_predict_now(img_id)

    def _run_predict_now(self, img_id):
        selected = self._selected_ai_classes()
        if not selected:
            # nothing checked: an earlier AI draft goes back to empty so the screen matches what is checked (your own boxes never)
            if self.project.is_ai_pending(img_id):
                self.project.set_ai_predicted_boxes(img_id, [])
                if img_id == self.current_image_id:
                    self._set_boxes([])
                    self.selected_box_index = None
                    self.canvas.redraw()
                    self._update_status()
                self._refresh_image_list()
            self._advance_predict_queue()
            return
        self._predict_busy = True
        self.set_progress(f"AI predicting: {img_id}")

        def worker():
            try:
                reloaded = bool(getattr(self.model_assist, 'reload_if_changed', lambda: False)())
                boxes = self.model_assist.predict_boxes(self.project.image_path(img_id), conf_threshold=self.model_conf)
                boxes = [b for b in self._map_model_classes(boxes) if b[0] in selected]
                error = None
            except Exception as e:  # noqa: BLE001
                boxes, error, reloaded = None, str(e), False

            def done():
                self._predict_busy = False
                self.set_progress("")
                if reloaded:
                    self._refresh_ai_status()
                if error:
                    qtk.error(self, "Prediction failed", error)
                else:
                    self.project.set_ai_predicted_boxes(img_id, boxes)
                    if img_id == self.current_image_id:
                        self._set_boxes(boxes)
                        self.selected_box_index = None
                        self.canvas.redraw()
                        self._update_status()
                    self._refresh_image_list()
                self._advance_predict_queue()
            self.post(done)
        threading.Thread(target=worker, daemon=True).start()

    def _advance_predict_queue(self):
        nxt, self._predict_queued_img_id = self._predict_queued_img_id, None
        if nxt is not None:
            self._trigger_live_predict(nxt)

    def clear_and_retry_ai(self):
        """Wipes the open image's boxes and sends it back through the live AI path (a newer model may catch more). Confirms only
        when it would discard a CONFIRMED annotation."""
        img_id = self.current_image_id
        if img_id is None:
            return
        if self.project.is_annotated(img_id):
            if not qtk.yesno(self, "Clear confirmed annotation?", f"'{img_id}' is confirmed annotated with {len(self.boxes)} box(es). "
                             "Clear it and send it back for a fresh AI pass? This can't be undone."):
                return
            self.project.unannotate_image(img_id)
        elif self.boxes or self.project.is_ai_pending(img_id):
            self.project.set_ai_predicted_boxes(img_id, [])
        self._set_boxes([])
        self.selected_box_index = None
        self.canvas.redraw()
        self._refresh_image_list()
        self._update_status()
        self._trigger_live_predict(img_id)

    def confirm_current_as_is(self):
        """Accepts the current boxes exactly as they stand (the AI draft looks right): indistinguishable from drawing them yourself."""
        if self.current_image_id is None:
            return
        self._save_current_boxes()
        self.canvas.redraw()

    # ------------------------------------------------------------------ status
    def _update_status(self):
        self._refresh_bar()
        self.canvas.update_empty()
        if self.current_image_id is None:
            n = len(self.project.list_images())
            hint = "" if n else "  |  empty - File > Import Gimble Session... or Import Video..."
            if n and self.active_session is not None:
                hint = f"  |  set {self.active_session}: nothing to show"
            self.status_label.setText(f"Project: {self.project.root}  |  {n} image(s){hint}")
            return
        if self.project.is_annotated(self.current_image_id):
            status = "annotated"
        elif self.project.is_ai_pending(self.current_image_id):
            status = "AI pre-labeled - needs review"
        else:
            status = "not yet annotated"
        info = self.project.manifest['images'].get(self.current_image_id, {})
        depth_txt = f"{info.get('depth_pixels', 0)} LiDAR pts" if self.project.has_depth(self.current_image_id) else "no depth"
        self.status_label.setText(
            f"{self.current_image_id}  |  {len(self.boxes)} box(es) ({sum(1 for d in self.box_dist if d)} with distance)  |  {status}  |  "
            f"{depth_txt}  |  {len(self.project.list_images())} image(s) in project"
            + (f"  |  set: {self.active_session}" if self.active_session else ""))
