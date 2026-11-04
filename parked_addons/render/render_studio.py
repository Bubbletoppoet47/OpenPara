"""
render_studio.py - Render Studio: photorealistic pictures of a part or an assembly (Mitsuba 3 path tracer).

Open a part (.gpd) or an assembly (.gpa), give each material a colour / roughness / metallic, set the sun (date, time, place), a spot light and
a floor, place several cameras, and render all of them to PNG files.  Run it with run_render_studio.bat (or:  python render_studio.py [file]).
The renderer runs as a separate program (render_core.py), so a problem there can never close this window; Stop kills it.
Settings are saved in a render project (.gpr): the model it was made from, the looks, the lights, the cameras and the output settings.
"""
import copy
import importlib.util
import json
import math
import os
import sys
import tempfile

import numpy as np
from PyQt6.QtCore import QDate, QProcess, QSize, Qt, QTime, QTimer, QUrl
from PyQt6.QtGui import QAction, QColor, QDesktopServices, QKeySequence, QPixmap
from PyQt6.QtWidgets import (QApplication, QCheckBox, QColorDialog, QComboBox, QDateEdit, QDialog, QDockWidget, QDoubleSpinBox, QFileDialog,
                             QFormLayout, QFrame, QHBoxLayout, QInputDialog, QLabel, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
                             QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSlider, QSpinBox, QTextEdit, QTimeEdit, QToolButton,
                             QVBoxLayout, QWidget)

import render_core as rc
import render_scene as rs
import unitctl

try:
    import pyvista as pv
    from pyvistaqt import QtInteractor
except Exception:
    pv, QtInteractor = None, None

HERE = os.path.dirname(os.path.abspath(__file__))
SIZES = [("1280 x 720", 1280, 720), ("1920 x 1080", 1920, 1080), ("800 x 600", 800, 600), ("1080 x 1080 (square)", 1080, 1080),
         ("3840 x 2160 (4K)", 3840, 2160), ("Custom", 0, 0)]
QUALITY = [("Draft (fast, grainy)", 32), ("Normal", 128), ("High", 512), ("Very high", 2048), ("Ultra 4096 (slow)", 4096), ("Ultra+ 8192 (slower)", 8192), ("Maximum 16384 (very slow)", 16384)]


def mitsuba_ok():
    return importlib.util.find_spec("mitsuba") is not None


class Section(QWidget):
    """A titled block that folds away (like a Blender panel)."""

    def __init__(self, title, open_=True):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 2)
        lay.setSpacing(0)
        self.head = QToolButton()
        self.head.setText(title)
        self.head.setCheckable(True)
        self.head.setChecked(open_)
        self.head.setArrowType(Qt.ArrowType.DownArrow if open_ else Qt.ArrowType.RightArrow)
        self.head.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.head.setStyleSheet("QToolButton{font-weight:bold; text-align:left; padding:4px; border:none; background:#e3e8f0;}")
        self.head.setSizePolicy(self.head.sizePolicy().horizontalPolicy(), self.head.sizePolicy().verticalPolicy())
        self.head.clicked.connect(self.toggle)
        lay.addWidget(self.head)
        self.body = QWidget()
        self.form = QFormLayout(self.body)
        self.form.setContentsMargins(8, 6, 4, 6)
        self.body.setVisible(open_)
        lay.addWidget(self.body)
        self.head.setMinimumWidth(10)
        self.head.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)

    def toggle(self, on):
        self.body.setVisible(on)
        self.head.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)


def dspin(lo, hi, val, step=1.0, dec=2, w=84):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(dec)
    s.setSingleStep(step)
    s.setValue(val)
    s.setFixedWidth(w)
    s.setKeyboardTracking(False)
    return s


class LenSpin(QDoubleSpinBox):
    """A length box: its value is always in millimetres, but it is shown and typed in the program's unit (File > Units)."""

    def textFromValue(self, v):
        return unitctl.num(unitctl.to_disp(v), 7)

    def valueFromText(self, t):
        try:
            return unitctl.from_disp(float(t.replace(",", ".").split()[0]))
        except (ValueError, IndexError):
            return self.value()

    def refresh_unit(self):
        self.lineEdit().setText(self.textFromValue(self.value()))


def dlen(lo, hi, val, step=10.0, w=78):
    s = LenSpin()
    s.setRange(lo, hi)
    s.setDecimals(6)
    s.setSingleStep(step)
    s.setValue(val)
    s.setFixedWidth(w)
    s.setKeyboardTracking(False)
    return s


def slider(val, lo=0, hi=100):
    s = QSlider(Qt.Orientation.Horizontal)
    s.setRange(lo, hi)
    s.setValue(int(val))
    return s


def color_button(rgb):
    b = QPushButton()
    b.setFixedSize(46, 22)
    set_button_color(b, rgb)
    return b


def set_button_color(b, rgb):
    c = QColor(*[int(round(max(0, min(1, x)) * 255)) for x in rgb])
    b.setStyleSheet(f"background:{c.name()}; border:1px solid #555;")


def pick_color(parent, rgb):
    c = QColorDialog.getColor(QColor(*[int(round(x * 255)) for x in rgb]), parent, "Colour")
    return [c.redF(), c.greenF(), c.blueF()] if c.isValid() else None


def row(*widgets):
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    for x in widgets:
        h.addWidget(x)
    h.addStretch(1)
    return w


class RenderStudio(QMainWindow):
    def __init__(self, path=None, shell=None, src_widget=None, gpr=None):
        super().__init__()
        self.shell = shell                                  # the modeller's main window when this is one of its tabs
        self.embedded = shell is not None or src_widget is not None or gpr is not None
        self.kind = "render"
        self.src_tab = src_widget
        self.setWindowTitle("Render Studio")
        self.resize(1480, 900)
        self.proj = None
        self.bodies, self.meshes = [], []
        self.proj_path = None
        self.dirty = False
        self.busy = False
        self.proc = None
        self.tmp = tempfile.mkdtemp(prefix="gpd_studio_")
        self.cur_cam = -1
        self.results = []
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(120)
        self.timer.timeout.connect(self.draw_scene)

        self.make_view()
        self.make_menus()
        self.make_bottom()
        self.make_props()
        self.statusBar().showMessage("Open a part or an assembly (File > Open model...)." if not self.embedded else "")
        if gpr:
            self.open_embedded_gpr(gpr)
        elif src_widget is not None:
            self.load_from_widget(src_widget)
            self.finish_open()
        elif path:
            QTimer.singleShot(0, lambda: self.open_any(path))

    # ---- what the modeller's tab bar needs (title, dirty flag, save, path, plotter)
    @property
    def path(self):
        return self.proj_path

    @property
    def plotter(self):
        return self.pl

    def title(self):
        if self.proj_path:
            return os.path.basename(self.proj_path)
        if self.proj and self.proj.get("source"):
            return os.path.splitext(os.path.basename(self.proj["source"]))[0] + " (render)"
        return "Render"

    def is_dirty(self):
        return bool(self.dirty)

    def save(self, as_new=False):
        return self.save_project(as_new)

    def update_all(self):
        self.draw_scene()

    def set_title(self):
        t = self.title()
        self.setWindowTitle(("* " if self.dirty else "") + ("Render Studio - " + t if not self.embedded else t))
        if self.shell is not None:
            try:
                self.shell.refresh_titles()
            except Exception:
                pass

    def alive(self, w):
        if w is None:
            return False
        try:
            w.title()
            return self.shell is None or self.shell.tabs.indexOf(w) >= 0
        except RuntimeError:
            return False

    def source_widget(self):
        """The part / assembly tab this render belongs to (opened again when it was closed); None when it cannot be found."""
        if self.alive(self.src_tab):
            return self.src_tab
        p = (self.proj or {}).get("source")
        if self.shell is None or not p or not os.path.exists(p):
            return None
        here = self.shell.tabs.indexOf(self)
        w = self.shell.open_path(p)
        if here >= 0:
            self.shell.tabs.setCurrentIndex(here)
        self.src_tab = w
        return w

    def load_from_widget(self, w):
        bodies = rs.bodies_from_widget(w)
        self.set_bodies(bodies, w.path)

    def open_embedded_gpr(self, path):
        proj = rs.load_project(path)
        src = proj.get("source", "")
        if src and not os.path.isabs(src):
            src = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(path)), src))
        if not src or not os.path.exists(src):
            raise ValueError(f"the model of this render project was not found: {src}")
        live = None
        if self.shell is not None:
            i = self.shell.find_tab(src)
            live = self.shell.tabs.widget(i) if i is not None else None
        if live is not None:
            self.load_from_widget(live)
            self.src_tab = live
        else:
            self.load_model(src)
        self.merge_project(proj)
        self.proj_path = path
        self.finish_open()

    def merge_project(self, proj):
        base = self.proj
        for k, v in proj.items():
            if k == "appearance":
                base["appearance"].update({n: a for n, a in v.items() if n in base["appearance"]})
            elif k != "source":
                base[k] = {**base[k], **v} if isinstance(v, dict) and isinstance(base.get(k), dict) else v

    def refresh_model(self):
        """Reads the part / assembly again (it may have changed); looks, lights and cameras stay."""
        w = self.source_widget()
        if w is None:
            QMessageBox.information(self, "Render", "The part / assembly of this render is not open and could not be opened.")
            return
        self.pull_from_controls()
        old = copy.deepcopy(self.proj)
        try:
            self.load_from_widget(w)
        except Exception as ex:
            self.proj = old
            QMessageBox.warning(self, "Render", f"Could not read the model: {ex}")
            return
        self.merge_project(old)
        self.finish_open(keep_cam=True)
        self.dirty = True
        self.set_title()
        self.statusBar().showMessage("The model was read again.")

    @classmethod
    def open_file(cls, shell, path):
        return cls(shell=shell, gpr=path)

    def shutdown(self):
        """Called when the tab is closed: stops a running render."""
        try:
            if self.proc is not None:
                self.proc.kill()
        except Exception:
            pass
        try:
            if self.pl is not None:
                self.pl.close()
        except Exception:
            pass

    # ================================================================ window parts
    def make_view(self):
        holder = QWidget()
        lay = QVBoxLayout(holder)
        lay.setContentsMargins(0, 0, 0, 0)
        self.pl = None
        if QtInteractor is None:
            lay.addWidget(QLabel("The 3D view needs pyvista and pyvistaqt (run_render_studio.bat installs them)."))
        else:
            try:
                self.pl = QtInteractor(holder)
                lay.addWidget(self.pl.interactor if hasattr(self.pl, "interactor") else self.pl)
                self.pl.set_background("#f4f6fa")
            except Exception as ex:
                self.pl = None
                lay.addWidget(QLabel(f"The 3D view could not start: {ex}"))
        self.setCentralWidget(holder)

    def make_menus(self):
        def act(menu, text, fn, key=None):
            a = QAction(text, self)
            if key:
                a.setShortcut(QKeySequence(key))
            a.triggered.connect(lambda _=False: fn())
            menu.addAction(a)
            return a
        fm = self.menuBar().addMenu("File")
        emb = self.embedded
        if not emb:
            act(fm, "Open model (part or assembly)...", self.open_model_dialog, "Ctrl+O")
            act(fm, "Open render project...", self.open_project_dialog)
            fm.addSeparator()
        else:
            act(fm, "Read the part / assembly again", self.refresh_model)
            fm.addSeparator()
        act(fm, "Export general settings...", self.export_settings)
        act(fm, "Import general settings...", self.import_settings)
        act(fm, "Export cameras...", self.export_cameras)
        act(fm, "Import cameras...", self.import_cameras)
        fm.addSeparator()
        act(fm, "Save render project", self.save_project, None if emb else "Ctrl+S")
        act(fm, "Save render project as...", lambda: self.save_project(True), None if emb else "Ctrl+Shift+S")
        if not emb:
            fm.addSeparator()
            act(fm, "Quit", self.close)
        rm = self.menuBar().addMenu("Render")
        self.a_prev = act(rm, "Preview of the selected camera (fast)", lambda: self.start_render("preview"), "F5")
        self.a_sel = act(rm, "Render the selected camera", lambda: self.start_render("selected"), "F11")
        self.a_all = act(rm, "Render all cameras", lambda: self.start_render("all"), "F12")
        rm.addSeparator()
        self.a_vprev = act(rm, "Preview video (fast)", lambda: self.start_render("video_preview"))
        self.a_video = act(rm, "Render video (MP4)", lambda: self.start_render("video"), "Ctrl+F12")
        rm.addSeparator()
        self.a_stop = act(rm, "Stop", self.stop_render, "Esc")
        self.a_stop.setEnabled(False)
        hm = self.menuBar().addMenu("Help")
        act(hm, "Guide", self.show_guide, "F1")

    def make_props(self):
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        # ---- scene
        self.s_scene = Section("Scene")
        self.src_lbl = QLabel("(nothing open)")
        self.src_lbl.setWordWrap(True)
        b = QPushButton("Open model...")
        b.clicked.connect(self.open_model_dialog)
        self.s_scene.form.addRow(self.src_lbl)
        self.s_scene.form.addRow(b)
        self.up_combo = QComboBox()
        self.up_combo.addItems(["+Z", "-Z", "+Y", "-Y", "+X", "-X"])
        self.up_combo.setToolTip("Which direction of the model is UP.  The floor is flat, perpendicular to it.  Change it to stand the model on "
                                 "another side (a part drawn on the Front plane may need +Y).")
        self.up_combo.currentTextChanged.connect(self.up_changed)
        self.s_scene.form.addRow("Up direction of the model", self.up_combo)
        lay.addWidget(self.s_scene)
        # ---- appearance
        self.s_app = Section("Appearance (colour, roughness, metallic)")
        self.app_host = QWidget()
        self.app_lay = QVBoxLayout(self.app_host)
        self.app_lay.setContentsMargins(0, 0, 0, 0)
        self.s_app.form.addRow(self.app_host)
        lay.addWidget(self.s_app)
        # ---- sun
        self.s_sun = Section("Sun and sky")
        f = self.s_sun.form
        self.sun_on = QCheckBox("Sun and sky light")
        self.sun_shadows = QCheckBox("Sun shadows (off = soft sky light only)")
        self.sun_date = QDateEdit()
        self.sun_date.setCalendarPopup(True)
        self.sun_date.setDisplayFormat("yyyy-MM-dd")
        self.sun_time = QTimeEdit()
        self.sun_time.setDisplayFormat("HH:mm")
        self.sun_tz = dspin(-12, 14, -7, 1, 1)
        self.sun_tz.setToolTip("Hours from UTC of the clock time you give (Arizona = -7, no daylight saving).")
        self.sun_lat = dspin(-90, 90, 33.45, 0.5, 3)
        self.sun_lon = dspin(-180, 180, -112.07, 0.5, 3)
        self.sun_north = dspin(-360, 360, 0, 5, 1)
        self.sun_north.setToolTip("Where north is, as an angle clockwise from the model's +Y direction seen from above.  0 = the model's +Y is north, "
                                  "+X is east.")
        self.sun_int = slider(100, 5, 400)
        self.sun_turb = dspin(2, 10, 3, 0.5, 1)
        self.sun_turb.setToolTip("Haze of the air: 2 clear, 6+ hazy.")
        self.sun_amb = slider(0, 0, 100)
        self.sun_amb.setToolTip("An extra even white light from everywhere (useful with the sun off).")
        self.sun_read = QLabel()
        f.addRow(self.sun_on)
        f.addRow(self.sun_shadows)
        f.addRow("Date", self.sun_date)
        f.addRow("Time", self.sun_time)
        f.addRow("UTC offset (h)", self.sun_tz)
        f.addRow("Latitude", self.sun_lat)
        f.addRow("Longitude", self.sun_lon)
        f.addRow("North direction (deg)", self.sun_north)
        f.addRow("Brightness", self.sun_int)
        f.addRow("Haze", self.sun_turb)
        f.addRow("Even light", self.sun_amb)
        f.addRow(self.sun_read)
        lay.addWidget(self.s_sun)
        # ---- spot
        self.s_spot = Section("Spot light", False)
        f = self.s_spot.form
        self.sp_on = QCheckBox("Spot light")
        self.sp_pos = [dlen(-1e6, 1e6, 0) for _ in range(3)]
        self.sp_tgt = [dlen(-1e6, 1e6, 0) for _ in range(3)]
        self.sp_pow = slider(50, 1, 300)
        self.sp_cone = dspin(5, 85, 35, 5, 0)
        self.sp_col = color_button([1, 1, 1])
        f.addRow(self.sp_on)
        self.len_labels = []
        for text, ws in (("Position x y z (mm)", self.sp_pos), ("Aims at x y z (mm)", self.sp_tgt)):
            lb = QLabel(unitctl.label(text))
            self.len_labels.append((lb, text))
            f.addRow(lb, row(*ws))
        f.addRow("Power", self.sp_pow)
        f.addRow("Cone angle (deg)", self.sp_cone)
        f.addRow("Colour", self.sp_col)
        lay.addWidget(self.s_spot)
        # ---- floor
        self.s_floor = Section("Floor")
        f = self.s_floor.form
        self.fl_on = QCheckBox("Floor")
        self.fl_z = dlen(-1e6, 1e6, 0, 1.0, 84)
        self.fl_z.setToolTip("Height of the floor along the model's up direction (in the program's length unit, File > Units).")
        b1 = QPushButton("At the bottom of the model")
        b1.clicked.connect(self.floor_bottom)
        self.fl_col = color_button([0.6, 0.6, 0.6])
        self.fl_rough = slider(80)
        f.addRow(self.fl_on)
        lb = QLabel(unitctl.label("Height (mm)"))
        self.len_labels.append((lb, "Height (mm)"))
        f.addRow(lb, row(self.fl_z, b1))
        f.addRow("Colour", self.fl_col)
        f.addRow("Roughness", self.fl_rough)
        lay.addWidget(self.s_floor)
        # ---- cameras
        self.s_cam = Section("Cameras")
        f = self.s_cam.form
        self.cam_list = QListWidget()
        self.cam_list.setMaximumHeight(120)
        self.cam_list.currentRowChanged.connect(self.cam_selected)
        self.cam_list.itemChanged.connect(self.cam_renamed)
        f.addRow(self.cam_list)
        b_add = QPushButton("Add from current view")
        b_add.setToolTip("A new camera where you are looking now in the 3D view.")
        b_add.clicked.connect(self.cam_add_view)
        self.preset = QComboBox()
        self.preset.addItems(list(rs.PRESET_VIEWS))
        b_pre = QPushButton("Add view")
        b_pre.clicked.connect(self.cam_add_preset)
        f.addRow(row(b_add))
        f.addRow(row(self.preset, b_pre))
        b_up = QPushButton("Move up")
        b_up.clicked.connect(lambda: self.cam_move(-1))
        b_dn = QPushButton("Move down")
        b_dn.clicked.connect(lambda: self.cam_move(1))
        f.addRow(row(QLabel("Tick = part of the video path; the list order is the path order:"), b_up, b_dn))
        b_exp = QPushButton("Export cameras...")
        b_exp.clicked.connect(self.export_cameras)
        b_imp = QPushButton("Import cameras...")
        b_imp.clicked.connect(self.import_cameras)
        f.addRow(row(b_exp, b_imp))
        b_look = QPushButton("Look through")
        b_look.clicked.connect(self.cam_look)
        b_upd = QPushButton("Set from current view")
        b_upd.setToolTip("Moves the selected camera to where you are looking now.")
        b_upd.clicked.connect(self.cam_update)
        b_del = QPushButton("Delete")
        b_del.clicked.connect(self.cam_delete)
        f.addRow(row(b_look, b_upd, b_del))
        self.cam_o = [dlen(-1e6, 1e6, 0) for _ in range(3)]
        self.cam_t = [dlen(-1e6, 1e6, 0) for _ in range(3)]
        self.cam_fov = dspin(5, 120, 35, 1, 1)
        self.cam_fov.setToolTip("Vertical field of view in degrees (small = telephoto, large = wide).")
        for text, ws in (("Position x y z (mm)", self.cam_o), ("Looks at x y z (mm)", self.cam_t)):
            lb = QLabel(unitctl.label(text))
            self.len_labels.append((lb, text))
            f.addRow(lb, row(*ws))
        f.addRow("Field of view (deg)", self.cam_fov)
        lay.addWidget(self.s_cam)
        # ---- animation
        self.s_anim = Section("Animation (video)", False)
        f = self.s_anim.form
        self.an_curve = QComboBox()
        self.an_curve.addItems(["Curved (smooth through the cameras)", "Straight (point to point)"])
        self.an_ease = QComboBox()
        self.an_ease.addItems(["Constant speed", "Ease in / out (gentle start and stop)"])
        self.an_sec = dspin(1, 600, 10, 1, 1)
        self.an_fps = QSpinBox()
        self.an_fps.setRange(5, 120)
        self.an_fps.setValue(30)
        self.an_info = QLabel()
        self.an_info.setWordWrap(True)
        self.an_show = QCheckBox("Show the path in the 3D view")
        self.an_show.setChecked(True)
        self.an_show.toggled.connect(lambda _=False: self.timer.start())
        b_av = QPushButton("Preview video (fast)")
        b_av.clicked.connect(lambda: self.start_render("video_preview"))
        b_ar = QPushButton("Render video (MP4)")
        b_ar.clicked.connect(lambda: self.start_render("video"))
        b_ar.setStyleSheet("font-weight:bold;")
        self.run_btns_extra = [b_av, b_ar]
        f.addRow(QLabel("Tick two or more cameras above (start, middle, end ...) and put them in order."))
        f.addRow("Path", self.an_curve)
        f.addRow("Speed", self.an_ease)
        f.addRow("Length (seconds)", self.an_sec)
        f.addRow("Frames per second", self.an_fps)
        f.addRow(self.an_info)
        f.addRow(self.an_show)
        f.addRow(row(b_av, b_ar))
        lay.addWidget(self.s_anim)
        # ---- output
        self.s_out = Section("Output")
        f = self.s_out.form
        self.o_size = QComboBox()
        for t, _w, _h in SIZES:
            self.o_size.addItem(t)
        self.o_w = QSpinBox()
        self.o_w.setRange(64, 8000)
        self.o_h = QSpinBox()
        self.o_h.setRange(64, 8000)
        self.o_qual = QComboBox()
        for t, _n in QUALITY:
            self.o_qual.addItem(t)
        self.o_qual.setToolTip("Samples per pixel: more = smoother picture, slower (time grows in proportion).")
        self.o_spp = QSpinBox()
        self.o_spp.setRange(1, 200000)
        self.o_exp = dspin(-4, 4, 0.5, 0.25, 2)
        self.o_exp.setToolTip("Exposure in stops (EV): + brighter, - darker.")
        self.o_bg = QComboBox()
        self.o_bg.addItems(["Sky", "Solid colour", "Transparent (PNG with alpha)"])
        self.o_bgc = color_button([1, 1, 1])
        self.o_fire = QCheckBox("Remove single bright pixels (fireflies)")
        self.o_den = QCheckBox("Denoise (NVIDIA graphics card)")
        self.o_den.setToolTip("Cleans the grain with the NVIDIA OptiX denoiser (needs an NVIDIA card with a recent driver).\nIf it cannot run, the render goes on without it and the log says so.")
        self.o_folder = QLabel("(asked at the first render)")
        self.o_folder.setWordWrap(True)
        b_fold = QPushButton("Folder...")
        b_fold.clicked.connect(self.choose_folder)
        b_open = QPushButton("Open folder")
        b_open.clicked.connect(self.open_folder)
        self.o_prefix = QComboBox()
        self.o_prefix.setEditable(True)
        self.o_prefix.setToolTip("Put in front of every file name (the camera name follows).")
        f.addRow("Picture size", self.o_size)
        f.addRow("Width x height (px)", row(self.o_w, QLabel("x"), self.o_h))
        f.addRow("Quality", self.o_qual)
        f.addRow("Samples per pixel", self.o_spp)
        f.addRow("Exposure (EV)", self.o_exp)
        f.addRow("Background", row(self.o_bg, self.o_bgc))
        f.addRow(self.o_fire)
        f.addRow(self.o_den)
        f.addRow("File name start", self.o_prefix)
        f.addRow("Folder", self.o_folder)
        f.addRow(row(b_fold, b_open))
        lay.addWidget(self.s_out)
        lay.addStretch(1)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(host)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        dock = QDockWidget("Properties", self)
        dock.setWidget(sc)
        dock.setMinimumWidth(400)
        dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        self.connect_props()
        self.setEnabled_props(False)

    def make_bottom(self):
        host = QWidget()
        lay = QHBoxLayout(host)
        left = QVBoxLayout()
        row_ = QHBoxLayout()
        b1 = QPushButton("Preview (fast)")
        b1.clicked.connect(lambda: self.start_render("preview"))
        b2 = QPushButton("Render selected camera")
        b2.clicked.connect(lambda: self.start_render("selected"))
        b3 = QPushButton("Render ALL cameras")
        b3.clicked.connect(lambda: self.start_render("all"))
        b3.setStyleSheet("font-weight:bold;")
        self.b_stop = QPushButton("Stop")
        self.b_stop.clicked.connect(self.stop_render)
        self.b_stop.setEnabled(False)
        self.run_btns = [b1, b2, b3]
        for b in (b1, b2, b3, self.b_stop):
            row_.addWidget(b)
        left.addLayout(row_)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        left.addWidget(self.bar)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        left.addWidget(self.log)
        self.files = QListWidget()
        self.files.setMaximumHeight(90)
        self.files.currentRowChanged.connect(self.show_result)
        self.files.itemDoubleClicked.connect(lambda it: QDesktopServices.openUrl(QUrl.fromLocalFile(it.data(Qt.ItemDataRole.UserRole))))
        left.addWidget(self.files)
        lay.addLayout(left, 2)
        self.img = QLabel("The picture appears here.")
        self.img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img.setMinimumSize(QSize(380, 220))
        self.img.setStyleSheet("background:#d8dce3; border:1px solid #aab;")
        lay.addWidget(self.img, 3)
        dock = QDockWidget("Render", self)
        dock.setWidget(host)
        dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)
        self.bottom_dock = dock
        QTimer.singleShot(0, lambda: self.resizeDocks([dock], [250], Qt.Orientation.Vertical))

    # ================================================================ binding of the controls
    def connect_props(self):
        ch = self.changed
        for w in (self.sun_on, self.sun_shadows, self.sp_on, self.fl_on, self.o_fire, self.o_den):
            w.toggled.connect(lambda _=False: ch())
        for w in ([self.sun_tz, self.sun_lat, self.sun_lon, self.sun_north, self.sun_turb, self.sp_cone, self.fl_z, self.cam_fov, self.o_exp]
                  + self.sp_pos + self.sp_tgt + self.cam_o + self.cam_t):
            w.valueChanged.connect(lambda _=0: ch())
        for w in (self.sun_int, self.sun_amb, self.sp_pow, self.fl_rough):
            w.valueChanged.connect(lambda _=0: ch())
        self.sun_date.dateChanged.connect(lambda _=None: ch())
        self.sun_time.timeChanged.connect(lambda _=None: ch())
        self.o_size.currentIndexChanged.connect(self.size_changed)
        self.o_qual.currentIndexChanged.connect(self.quality_changed)
        for w in (self.an_curve, self.an_ease):
            w.currentIndexChanged.connect(lambda _=0: ch())
        self.an_sec.valueChanged.connect(lambda _=0: ch())
        self.an_fps.valueChanged.connect(lambda _=0: ch())
        self.o_w.valueChanged.connect(lambda _=0: ch())
        self.o_h.valueChanged.connect(lambda _=0: ch())
        self.o_spp.valueChanged.connect(lambda _=0: ch())
        self.o_bg.currentIndexChanged.connect(lambda _=0: ch())
        self.o_prefix.editTextChanged.connect(lambda _="": ch())
        for btn, key in ((self.sp_col, "spot"), (self.fl_col, "floor"), (self.o_bgc, "bg")):
            btn.clicked.connect(lambda _=False, k=key: self.pick(k))

    def setEnabled_props(self, on):
        for s in (self.s_app, self.s_sun, self.s_spot, self.s_floor, self.s_cam, self.s_anim, self.s_out, self.up_combo):
            s.setEnabled(on)
        for b in self.run_btns + self.run_btns_extra:
            b.setEnabled(on and not self.busy)

    def pick(self, key):
        p = self.proj
        cur = {"spot": p["spot"]["color"], "floor": p["floor"]["color"], "bg": p["render"]["bg_color"]}[key]
        c = pick_color(self, cur)
        if c is None:
            return
        if key == "spot":
            p["spot"]["color"] = c
            set_button_color(self.sp_col, c)
        elif key == "floor":
            p["floor"]["color"] = c
            set_button_color(self.fl_col, c)
        else:
            p["render"]["bg_color"] = c
            set_button_color(self.o_bgc, c)
        self.mark()

    def size_changed(self, i):
        _t, w, h = SIZES[i]
        for sp in (self.o_w, self.o_h):
            sp.blockSignals(True)
        if w:
            self.o_w.setValue(w)
            self.o_h.setValue(h)
        for sp in (self.o_w, self.o_h):
            sp.blockSignals(False)
        self.o_w.setEnabled(not w)
        self.o_h.setEnabled(not w)
        self.changed()

    def quality_changed(self, i):
        self.o_spp.blockSignals(True)
        self.o_spp.setValue(QUALITY[i][1])
        self.o_spp.blockSignals(False)
        self.changed()

    # ---- project <-> controls
    def push_to_controls(self):
        """The project's values into the controls (no change signals)."""
        p = self.proj
        self.loading = True
        try:
            self.up_combo.setCurrentText(p.get("up", "+Z"))
            s = p["sun"]
            self.sun_on.setChecked(s["on"])
            self.sun_shadows.setChecked(s["shadows"])
            y, m, d = (int(x) for x in s["date"].split("-"))
            self.sun_date.setDate(QDate(y, m, d))
            hh, mm = (int(x) for x in s["time"].split(":")[:2])
            self.sun_time.setTime(QTime(hh, mm))
            self.sun_tz.setValue(s["tz"])
            self.sun_lat.setValue(s["lat"])
            self.sun_lon.setValue(s["lon"])
            self.sun_north.setValue(s["north"])
            self.sun_int.setValue(int(round(s["intensity"] * 100)))
            self.sun_turb.setValue(s["turbidity"])
            self.sun_amb.setValue(int(round(p.get("ambient", 0) * 100)))
            sp = p["spot"]
            self.sp_on.setChecked(sp["on"])
            for w, v in zip(self.sp_pos, sp["pos"]):
                w.setValue(v)
            for w, v in zip(self.sp_tgt, sp["target"]):
                w.setValue(v)
            self.sp_pow.setValue(int(sp["power"]))
            self.sp_cone.setValue(sp["cone"])
            set_button_color(self.sp_col, sp["color"])
            fl = p["floor"]
            self.fl_on.setChecked(fl["on"])
            self.fl_z.setValue(fl["z"])
            set_button_color(self.fl_col, fl["color"])
            self.fl_rough.setValue(int(round(fl["roughness"] * 100)))
            r = p["render"]
            k = next((i for i, (_t, w, h) in enumerate(SIZES) if w == r["width"] and h == r["height"]), len(SIZES) - 1)
            self.o_size.setCurrentIndex(k)
            self.o_w.setValue(r["width"])
            self.o_h.setValue(r["height"])
            self.o_w.setEnabled(SIZES[k][1] == 0)
            self.o_h.setEnabled(SIZES[k][1] == 0)
            self.o_spp.setValue(r["spp"])
            q = next((i for i, (_t, n) in enumerate(QUALITY) if n == r["spp"]), 1)
            self.o_qual.blockSignals(True)
            self.o_qual.setCurrentIndex(q)
            self.o_qual.blockSignals(False)
            self.o_exp.setValue(r["exposure"])
            self.o_bg.setCurrentIndex({"sky": 0, "color": 1, "transparent": 2}.get(r["background"], 0))
            set_button_color(self.o_bgc, r["bg_color"])
            self.o_fire.setChecked(r.get("fireflies", True))
            self.o_den.setChecked(r.get("denoise", False))
            a = p["anim"]
            self.an_curve.setCurrentIndex(0 if a["curved"] else 1)
            self.an_ease.setCurrentIndex(1 if a["ease"] else 0)
            self.an_sec.setValue(a["seconds"])
            self.an_fps.setValue(a["fps"])
            self.o_prefix.setEditText(p["output"].get("name", "render"))
            self.o_folder.setText(p["output"].get("folder") or "(asked at the first render)")
            self.fill_appearance()
            self.fill_cameras()
        finally:
            self.loading = False
        self.update_anim_info()

    def pull_from_controls(self):
        p = self.proj
        s = p["sun"]
        s["on"], s["shadows"] = self.sun_on.isChecked(), self.sun_shadows.isChecked()
        s["date"] = self.sun_date.date().toString("yyyy-MM-dd")
        s["time"] = self.sun_time.time().toString("HH:mm")
        s["tz"], s["lat"], s["lon"] = self.sun_tz.value(), self.sun_lat.value(), self.sun_lon.value()
        s["north"], s["intensity"], s["turbidity"] = self.sun_north.value(), self.sun_int.value() / 100.0, self.sun_turb.value()
        p["ambient"] = self.sun_amb.value() / 100.0
        sp = p["spot"]
        sp["on"] = self.sp_on.isChecked()
        sp["pos"] = [w.value() for w in self.sp_pos]
        sp["target"] = [w.value() for w in self.sp_tgt]
        sp["power"], sp["cone"] = float(self.sp_pow.value()), self.sp_cone.value()
        fl = p["floor"]
        fl["on"], fl["z"], fl["roughness"] = self.fl_on.isChecked(), self.fl_z.value(), self.fl_rough.value() / 100.0
        r = p["render"]
        r["width"], r["height"], r["spp"], r["exposure"] = self.o_w.value(), self.o_h.value(), self.o_spp.value(), self.o_exp.value()
        r["background"] = ["sky", "color", "transparent"][self.o_bg.currentIndex()]
        r["fireflies"] = self.o_fire.isChecked()
        r["denoise"] = self.o_den.isChecked()
        a = p["anim"]
        a["curved"], a["ease"] = self.an_curve.currentIndex() == 0, self.an_ease.currentIndex() == 1
        a["seconds"], a["fps"] = self.an_sec.value(), self.an_fps.value()
        p["output"]["name"] = self.o_prefix.currentText()
        if 0 <= self.cur_cam < len(p["cameras"]):
            c = p["cameras"][self.cur_cam]
            c["origin"], c["target"], c["fov"] = [w.value() for w in self.cam_o], [w.value() for w in self.cam_t], self.cam_fov.value()

    def changed(self):
        if self.proj is None or getattr(self, "loading", False):
            return
        self.pull_from_controls()
        self.mark()

    def update_anim_info(self):
        if self.proj is None:
            return
        cams = [c["name"] for c in self.proj["cameras"] if c.get("anim")]
        a = self.proj["anim"]
        n = max(2, int(round(a["seconds"] * a["fps"])))
        if len(cams) < 2:
            self.an_info.setText("<span style='color:#b00020'>Tick at least two cameras.</span>")
        else:
            self.an_info.setText(f"{n} frames from {len(cams)} cameras: " + " -> ".join(cams))
        self.timer.start()

    def mark(self):
        self.dirty = True
        self.update_anim_info()
        self.update_sun_readout()
        self.timer.start()
        self.set_title()

    def update_sun_readout(self):
        if self.proj is None:
            return
        s = self.proj["sun"]
        try:
            el, az = rc.sun_position(s["lat"], s["lon"], s["date"], s["time"], s["tz"])
            comp = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][int(((az + 22.5) % 360) // 45)]
            self.sun_read.setText(f"Sun: {el:.1f} deg above the horizon, from the {comp} ({az:.0f} deg)" + ("   - BELOW THE HORIZON (night)" if el <= 0 else ""))
        except Exception:
            self.sun_read.setText("")

    # ================================================================ settings and cameras as text files
    def json_dialog_save(self, title, name, data):
        start = os.path.join(self.start_dir() or "", name)
        path, _ = QFileDialog.getSaveFileName(self, title, start, "Text file (*.json *.txt)")
        if not path:
            return
        if not os.path.splitext(path)[1]:
            path += ".json"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1)
        self.statusBar().showMessage(f"Saved {path}")

    def json_dialog_open(self, title):
        path, _ = QFileDialog.getOpenFileName(self, title, self.start_dir(), "Text file (*.json *.txt)")
        if not path:
            return None
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception as ex:
            QMessageBox.warning(self, "Open", f"Could not read that file: {ex}")
            return None

    def export_settings(self):
        if self.proj is None:
            return
        self.pull_from_controls()
        self.json_dialog_save("Export general settings", "render_settings.json", rs.export_settings(self.proj))

    def import_settings(self):
        if self.proj is None:
            return
        d = self.json_dialog_open("Import general settings")
        if d is None:
            return
        try:
            rs.import_settings(self.proj, d)
        except Exception as ex:
            QMessageBox.warning(self, "Import", str(ex))
            return
        self.push_to_controls()
        self.cam_selected(self.cur_cam)
        self.mark()
        self.draw_scene()
        self.statusBar().showMessage("Settings imported: sun, spot light, floor, picture, quality and animation.")

    def export_cameras(self):
        if self.proj is None:
            return
        self.pull_from_controls()
        self.json_dialog_save("Export cameras", "render_cameras.json", rs.export_cameras(self.proj))

    def import_cameras(self):
        if self.proj is None:
            return
        d = self.json_dialog_open("Import cameras")
        if d is None:
            return
        try:
            cams = rs.import_cameras(d)
        except Exception as ex:
            QMessageBox.warning(self, "Import", str(ex))
            return
        box = QMessageBox(self)
        box.setWindowTitle("Import cameras")
        box.setText(f"{len(cams)} camera(s) in the file.")
        b_rep = box.addButton("Replace my cameras", QMessageBox.ButtonRole.AcceptRole)
        b_add = box.addButton("Add to my cameras", QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        if box.clickedButton() is b_rep:
            self.proj["cameras"] = cams
        elif box.clickedButton() is b_add:
            for c in cams:
                c["name"] = self.unique_name(c["name"])
                self.proj["cameras"].append(c)
        else:
            return
        self.cur_cam = 0
        self.fill_cameras()
        self.mark()

    # ================================================================ opening / saving
    def open_model_dialog(self):
        p, _ = QFileDialog.getOpenFileName(self, "Open model", self.start_dir(), "Part or assembly (*.gpd *.gpa)")
        if p:
            self.open_any(p)

    def open_project_dialog(self):
        p, _ = QFileDialog.getOpenFileName(self, "Open render project", self.start_dir(), "Render project (*.gpr)")
        if p:
            self.open_any(p)

    def start_dir(self):
        return os.path.dirname(self.proj.get("source", "")) if self.proj and self.proj.get("source") else ""

    def open_any(self, path):
        if not self.ask_save():
            return
        try:
            if path.lower().endswith(".gpr"):
                proj = rs.load_project(path)
                src = proj.get("source", "")
                if src and not os.path.isabs(src):
                    src = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(path)), src))
                if not src or not os.path.exists(src):
                    QMessageBox.warning(self, "Open", f"The model of this render project was not found:\n{src}")
                    return
                self.load_model(src)
                self.merge_project(proj)
                self.proj_path = path
            else:
                self.load_model(path)
                self.proj_path = None
        except Exception as ex:
            import traceback
            QMessageBox.warning(self, "Open", f"Could not open it: {ex}\n\n{traceback.format_exc()}")
            return
        self.finish_open()

    def finish_open(self, keep_cam=False):
        n = len(self.proj["cameras"])
        self.cur_cam = min(max(self.cur_cam, 0), n - 1) if keep_cam and n else (0 if n else -1)
        self.push_to_controls()
        self.cam_list.setCurrentRow(self.cur_cam)
        self.setEnabled_props(True)
        self.dirty = False
        self.update_sun_readout()
        self.draw_scene(reset=not keep_cam)
        self.set_title()
        self.statusBar().showMessage(f"{len(self.bodies)} body(ies) loaded from {self.proj['source']}")

    def load_model(self, path):
        self.statusBar().showMessage("Loading the model...")
        QApplication.processEvents()
        self.set_bodies(rs.load_bodies(path), path)

    def set_bodies(self, bodies, path):
        if not bodies:
            raise ValueError("the file has no solid to draw (is every part hidden or empty?)")
        self.bodies = bodies
        self.meshes = [rs.mesh_of(b[1]) for b in bodies]
        self.proj = rs.new_project(bodies, self.meshes, path)
        self.src_lbl.setText(f"<b>{os.path.basename(path)}</b><br>{len(bodies)} body(ies)")

    def save_project(self, as_new=False):
        if self.proj is None:
            return False
        self.pull_from_controls()
        path = self.proj_path
        if (as_new or not path) and self.embedded and not as_new:
            base = os.path.splitext(self.proj["source"])[0] + "_render"
            path, k = base + ".gpr", 2
            while os.path.exists(path):
                path = f"{base}_{k}.gpr"
                k += 1
        elif as_new or not path:
            start = os.path.splitext(self.proj["source"])[0] + ".gpr"
            path, _ = QFileDialog.getSaveFileName(self, "Save render project", start, "Render project (*.gpr)")
            if not path:
                return False
            if not path.lower().endswith(".gpr"):
                path += ".gpr"
        out = copy.deepcopy(self.proj)
        try:
            out["source"] = os.path.relpath(self.proj["source"], os.path.dirname(os.path.abspath(path)))
        except ValueError:
            pass
        rs.save_project(out, path)
        self.proj_path = path
        self.dirty = False
        self.set_title()
        self.statusBar().showMessage(f"Saved {path}")
        if self.embedded:
            try:
                import sim_links
                src = self.source_widget()
                if src is not None and sim_links.add(src, path, "renders"):
                    src.refresh_tree()
            except Exception as ex:
                self.statusBar().showMessage(f"Saved {path} (could not link it to the model: {ex})")
        return True

    def ask_save(self):
        if not self.dirty or self.proj is None or self.embedded:
            return True
        r = QMessageBox.question(self, "Render project", "Save the changes to the render project first?",
                                 QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        if r == QMessageBox.StandardButton.Cancel:
            return False
        if r == QMessageBox.StandardButton.Save:
            return self.save_project()
        return True

    def closeEvent(self, ev):
        if not self.ask_save():
            ev.ignore()
            return
        self.stop_render()
        try:
            if self.pl is not None:
                self.pl.close()
        except Exception:
            pass
        super().closeEvent(ev)

    # ================================================================ appearance
    def fill_appearance(self):
        while self.app_lay.count():
            it = self.app_lay.takeAt(0)
            if it.widget() is not None:
                it.widget().deleteLater()
        self.app_ctrl = {}
        for name, _s, mat in self.bodies:
            ap = self.proj["appearance"][name]
            box = QFrame()
            box.setFrameShape(QFrame.Shape.StyledPanel)
            g = QFormLayout(box)
            g.setContentsMargins(6, 4, 6, 4)
            title = QLabel(f"<b>{name}</b>  <span style='color:#667'>({mat or 'no material'})</span>")
            g.addRow(title)
            cb = color_button(ap["color"])
            rough = slider(round(ap["roughness"] * 100))
            met = slider(round(ap["metallic"] * 100))
            rv, mv = QLabel(f"{ap['roughness']:.2f}"), QLabel(f"{ap['metallic']:.2f}")
            cb.clicked.connect(lambda _=False, n=name, b=cb: self.pick_body_color(n, b))
            rough.valueChanged.connect(lambda v, n=name, lab=rv: self.set_body(n, "roughness", v / 100.0, lab))
            met.valueChanged.connect(lambda v, n=name, lab=mv: self.set_body(n, "metallic", v / 100.0, lab))
            reset = QPushButton("Material default")
            reset.setToolTip("Back to the look that goes with the material.")
            reset.clicked.connect(lambda _=False, n=name, m=mat: self.reset_body(n, m))
            g.addRow("Colour", row(cb, reset))
            g.addRow("Roughness", row(rough, rv))
            g.addRow("Metallic", row(met, mv))
            self.app_lay.addWidget(box)
            self.app_ctrl[name] = (cb, rough, met, rv, mv)

    def pick_body_color(self, name, btn):
        c = pick_color(self, self.proj["appearance"][name]["color"])
        if c is not None:
            self.proj["appearance"][name]["color"] = c
            set_button_color(btn, c)
            self.mark()

    def set_body(self, name, key, v, lab):
        if getattr(self, "loading", False):
            return
        self.proj["appearance"][name][key] = v
        lab.setText(f"{v:.2f}")
        self.mark()

    def reset_body(self, name, mat):
        ap = rs.default_appearance(mat)
        self.proj["appearance"][name] = ap
        cb, rough, met, rv, mv = self.app_ctrl[name]
        set_button_color(cb, ap["color"])
        rough.setValue(round(ap["roughness"] * 100))
        met.setValue(round(ap["metallic"] * 100))
        self.mark()

    # ================================================================ floor / up axis
    def model_bounds(self):
        return rs.bounds_of(self.meshes)

    def units_changed(self, *_a):
        """File > Units changed: length boxes and their labels show the new unit (the values stay in mm)."""
        for lb, text in getattr(self, "len_labels", []):
            lb.setText(unitctl.label(text))
        for w in self.sp_pos + self.sp_tgt + self.cam_o + self.cam_t + [self.fl_z]:
            w.refresh_unit()

    def floor_bottom(self):
        if self.proj is None:
            return
        lo, hi = self.model_bounds()
        up = self.proj.get("up", "+Z")
        ax = rs.UP_AXES[up]
        z = float(lo[ax]) if up[0] == "+" else float(-hi[ax])
        self.fl_z.setValue(z)

    def up_changed(self, text):
        if self.proj is None or getattr(self, "loading", False) or text == self.proj.get("up"):
            return
        self.proj["up"] = text
        self.floor_bottom()
        lo, hi = self.model_bounds()
        r = QMessageBox.question(self, "Up direction", "Re-aim the cameras for the new up direction (replace them by the standard Iso and Front cameras)?")
        if r == QMessageBox.StandardButton.Yes:
            self.proj["cameras"] = [rs.view_camera(lo, hi, rs.PRESET_VIEWS["Iso"], name="Iso", up=text),
                                    rs.view_camera(lo, hi, rs.PRESET_VIEWS["Front"], name="Front", up=text)]
            self.cur_cam = 0
            self.fill_cameras()
        self.mark()
        self.draw_scene(reset=True)

    # ================================================================ cameras
    def fill_cameras(self):
        self.cam_list.blockSignals(True)
        self.cam_list.clear()
        for c in self.proj["cameras"]:
            it = QListWidgetItem(c["name"])
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if c.get("anim") else Qt.CheckState.Unchecked)
            self.cam_list.addItem(it)
        self.cam_list.blockSignals(False)
        if 0 <= self.cur_cam < self.cam_list.count():
            self.cam_list.setCurrentRow(self.cur_cam)
        self.cam_selected(self.cur_cam)

    def cam_selected(self, i):
        self.cur_cam = i
        loading = getattr(self, "loading", False)
        self.loading = True
        try:
            if 0 <= i < len(self.proj["cameras"]):
                c = self.proj["cameras"][i]
                for w, v in zip(self.cam_o, c["origin"]):
                    w.setValue(v)
                for w, v in zip(self.cam_t, c["target"]):
                    w.setValue(v)
                self.cam_fov.setValue(c["fov"])
        finally:
            self.loading = loading
        self.timer.start()

    def cam_renamed(self, item):
        i = self.cam_list.row(item)
        if 0 <= i < len(self.proj["cameras"]):
            self.proj["cameras"][i]["anim"] = item.checkState() == Qt.CheckState.Checked
            self.update_anim_info()
            name = item.text().strip() or f"Camera {i + 1}"
            names = [c["name"] for k, c in enumerate(self.proj["cameras"]) if k != i]
            while name in names:
                name += "_2"
            self.proj["cameras"][i]["name"] = name
            if item.text() != name:
                self.cam_list.blockSignals(True)
                item.setText(name)
                self.cam_list.blockSignals(False)
            self.mark()

    def cam_move(self, d):
        i, L = self.cur_cam, self.proj["cameras"] if self.proj else []
        j = i + d
        if not (0 <= i < len(L) and 0 <= j < len(L)):
            return
        L[i], L[j] = L[j], L[i]
        self.cur_cam = j
        self.fill_cameras()
        self.mark()

    def unique_name(self, base):
        names = {c["name"] for c in self.proj["cameras"]}
        if base not in names:
            return base
        k = 2
        while f"{base} {k}" in names:
            k += 1
        return f"{base} {k}"

    def view_now(self):
        """(position, target, up, vertical fov) of the 3D view."""
        pos, foc, up = self.pl.camera_position
        return [float(x) for x in pos], [float(x) for x in foc], [float(x) for x in up], float(self.pl.camera.view_angle)

    def cam_add_view(self):
        if self.proj is None or self.pl is None:
            return
        o, t, u, fov = self.view_now()
        self.proj["cameras"].append({"name": self.unique_name(f"Camera {len(self.proj['cameras']) + 1}"), "origin": o, "target": t, "up": u, "fov": fov})
        self.cur_cam = len(self.proj["cameras"]) - 1
        self.fill_cameras()
        self.mark()

    def cam_add_preset(self):
        if self.proj is None:
            return
        lo, hi = self.model_bounds()
        nm = self.preset.currentText()
        self.proj["cameras"].append(rs.view_camera(lo, hi, rs.PRESET_VIEWS[nm], name=self.unique_name(nm), up=self.proj.get("up", "+Z")))
        self.cur_cam = len(self.proj["cameras"]) - 1
        self.fill_cameras()
        self.mark()

    def cam_update(self):
        if self.proj is None or self.pl is None or not (0 <= self.cur_cam < len(self.proj["cameras"])):
            return
        o, t, u, fov = self.view_now()
        c = self.proj["cameras"][self.cur_cam]
        c.update(origin=o, target=t, up=u, fov=fov)
        self.cam_selected(self.cur_cam)
        self.mark()

    def cam_delete(self):
        if self.proj is None or not (0 <= self.cur_cam < len(self.proj["cameras"])):
            return
        if len(self.proj["cameras"]) <= 1:
            QMessageBox.information(self, "Cameras", "Keep at least one camera.")
            return
        del self.proj["cameras"][self.cur_cam]
        self.cur_cam = max(0, self.cur_cam - 1)
        self.fill_cameras()
        self.mark()

    def cam_look(self):
        if self.proj is None or self.pl is None or not (0 <= self.cur_cam < len(self.proj["cameras"])):
            return
        c = self.proj["cameras"][self.cur_cam]
        cam = self.pl.camera
        cam.position, cam.focal_point, cam.up = c["origin"], c["target"], c.get("up", [0, 0, 1])
        cam.view_angle = c["fov"]
        self.pl.reset_camera_clipping_range()
        self.pl.render()

    # ================================================================ the 3D view
    def draw_scene(self, reset=False):
        pl = self.pl
        if pl is None or self.proj is None:
            return
        p = self.proj
        keep = None if reset else (pl.camera_position, pl.camera.view_angle)
        try:
            pl.clear()
            lo, hi = self.model_bounds()
            cen, diag = 0.5 * (lo + hi), float(np.linalg.norm(hi - lo))
            for (name, _s, _m), (v, n, f) in zip(self.bodies, self.meshes):
                if not len(f):
                    continue
                poly = pv.PolyData(v, np.hstack([np.full((len(f), 1), 3), f]).ravel())
                poly.point_data["Normals"] = n
                ap = p["appearance"][name]
                pl.add_mesh(poly, color=ap["color"], smooth_shading=False, pbr=False, specular=0.2 + 0.6 * ap["metallic"], specular_power=10 + 40 * (1 - ap["roughness"]),
                            reset_camera=False, pickable=False)
            R = rs.rotation_to_z(p.get("up", "+Z"))
            up = rs.up_vector(p.get("up", "+Z"))
            if p["floor"]["on"]:
                ax = rs.UP_AXES[p.get("up", "+Z")]
                sign = 1.0 if p.get("up", "+Z")[0] == "+" else -1.0
                c = cen.copy()
                c[ax] = sign * p["floor"]["z"]
                pl.add_mesh(pv.Plane(center=c, direction=tuple(up), i_size=3.0 * diag, j_size=3.0 * diag), color=p["floor"]["color"], opacity=0.55,
                            reset_camera=False, pickable=False, lighting=False)
            if p["sun"]["on"]:
                el, az = rc.sun_position(p["sun"]["lat"], p["sun"]["lon"], p["sun"]["date"], p["sun"]["time"], p["sun"]["tz"])
                v = R.T @ rc.sun_vector(max(el, 1.0), az, p["sun"]["north"])
                pl.add_mesh(pv.Arrow(start=cen + v * 1.3 * diag, direction=-v, scale=0.5 * diag), color="#f2b800", reset_camera=False, pickable=False, lighting=False)
            if p["spot"]["on"]:
                pos, tgt = np.array(p["spot"]["pos"], float), np.array(p["spot"]["target"], float)
                pl.add_mesh(pv.Line(pos, tgt), color="#e08a00", line_width=2, reset_camera=False, pickable=False)
                pl.add_mesh(pv.Sphere(radius=0.03 * diag, center=pos), color="#e08a00", reset_camera=False, pickable=False, lighting=False)
            aspect = p["render"]["width"] / max(1, p["render"]["height"])
            for i, c in enumerate(p["cameras"]):
                o, t = np.array(c["origin"], float), np.array(c["target"], float)
                fw = t - o
                L = np.linalg.norm(fw)
                if L < 1e-9:
                    continue
                fw /= L
                u0 = np.array(c.get("up", [0, 0, 1]), float)
                rt = np.cross(fw, u0)
                if np.linalg.norm(rt) < 1e-9:
                    continue
                rt /= np.linalg.norm(rt)
                upv = np.cross(rt, fw)
                s = 0.10 * diag
                h = s * math.tan(math.radians(c["fov"]) / 2)
                cor = [o + fw * s + sx * rt * h * aspect + sy * upv * h for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
                col = "#e8590c" if i == self.cur_cam else "#3b6fb6"
                pts = [o, cor[0], cor[1], cor[2], cor[3]]
                lines = [2, 0, 1, 2, 0, 2, 2, 0, 3, 2, 0, 4, 2, 1, 2, 2, 2, 3, 2, 3, 4, 2, 4, 1]
                pd = pv.PolyData(np.array(pts))
                pd.lines = np.array(lines)
                pl.add_mesh(pd, color=col, line_width=3 if i == self.cur_cam else 2, reset_camera=False, pickable=False, lighting=False)
                pl.add_point_labels([o], [c["name"]], font_size=11, text_color=col, shape=None, show_points=False, always_visible=True, reset_camera=False)
            ac = [c for c in p["cameras"] if c.get("anim")]
            if len(ac) >= 2 and self.an_show.isChecked():
                pts = rs.path_polyline(ac, p["anim"]["curved"])
                pd = pv.PolyData(pts)
                pd.lines = np.hstack([[len(pts)], np.arange(len(pts))])
                pl.add_mesh(pd, color="#2f9e44", line_width=4, reset_camera=False, pickable=False, lighting=False)
            if keep is None:
                pl.camera_position = "iso"
                pl.reset_camera()
            else:
                pl.camera_position, pl.camera.view_angle = keep
            pl.render()
        except Exception as ex:
            self.statusBar().showMessage(f"(3D view: {ex})")

    # ================================================================ rendering
    def choose_folder(self):
        if self.proj is None:
            return
        start = self.proj["output"].get("folder") or os.path.dirname(self.proj["source"])
        d = QFileDialog.getExistingDirectory(self, "Folder for the pictures", start)
        if d:
            self.proj["output"]["folder"] = d
            self.o_folder.setText(d)
            self.mark()

    def open_folder(self):
        f = self.proj["output"].get("folder") if self.proj else ""
        if f and os.path.isdir(f):
            QDesktopServices.openUrl(QUrl.fromLocalFile(f))

    def out_folder(self):
        f = self.proj["output"].get("folder")
        if f:
            os.makedirs(f, exist_ok=True)
            return f
        self.choose_folder()
        return self.proj["output"].get("folder") or None

    def start_render(self, mode):
        """mode: preview | selected | all | video_preview | video"""
        if self.proj is None or self.busy:
            return
        if not mitsuba_ok():
            QMessageBox.warning(self, "Render", "The renderer (Mitsuba) is not installed for this Python.\nRun run_render_studio.bat once, or:\n"
                                f"    {sys.executable} -m pip install mitsuba")
            return
        self.pull_from_controls()
        p = self.proj
        video = mode.startswith("video")
        names, over, prefix = None, None, p["output"].get("name", "")
        p_use = p
        if video:
            if importlib.util.find_spec("imageio_ffmpeg") is None:
                QMessageBox.warning(self, "Render", "Videos need imageio-ffmpeg.\nRun run_render_studio.bat once, or:\n"
                                    f"    {sys.executable} -m pip install imageio-ffmpeg")
                return
            ac = [c for c in p["cameras"] if c.get("anim")]
            if len(ac) < 2:
                QMessageBox.information(self, "Video", "Tick at least two cameras (start, middle, end ...) in the Cameras list first.")
                return
            a = p["anim"]
            fps = int(a["fps"])
            secs = float(a["seconds"])
            over = {}
            if mode == "video_preview":
                fps = 10
                w = 480
                h = max(64, int(round(w * p["render"]["height"] / max(1, p["render"]["width"]))))
                over = {"width": w, "height": h, "spp": 16, "denoise": False}
                folder = os.path.join(self.tmp, "videopreview")
            else:
                folder = self.out_folder()
                if not folder:
                    return
            if p["render"]["background"] == "transparent":
                over["background"] = "color"                       # a video has no transparency
            n = max(2, int(round(secs * fps)))
            frames = rs.path_cameras(ac, n, a["curved"], a["ease"])
            p_use = dict(p)
            p_use["cameras"] = frames
        elif mode == "all":
            folder = self.out_folder()
            if not folder:
                return
        else:
            if not (0 <= self.cur_cam < len(p["cameras"])):
                return
            names = [p["cameras"][self.cur_cam]["name"]]
            if mode == "preview":
                w = 480
                h = max(64, int(round(w * p["render"]["height"] / max(1, p["render"]["width"]))))
                over, folder, prefix = {"width": w, "height": h, "spp": 24, "denoise": False}, os.path.join(self.tmp, "preview"), "preview_"
            else:
                folder = self.out_folder()
                if not folder:
                    return
        sc_dir = os.path.join(self.tmp, "scene")
        sc = rs.scene_for_render(p_use, self.bodies, self.meshes, sc_dir, over)
        sc["prefix"] = (prefix + "_") if prefix and not prefix.endswith("_") else prefix
        if video:
            vname = (p["output"].get("name") or "render") + ("_preview" if mode == "video_preview" else "_video") + ".mp4"
            sc["video"] = {"frames": sc["cameras"], "fps": fps, "file": vname}
            sc["cameras"] = []
        self.stop_file = os.path.join(self.tmp, "stop.flag")
        if os.path.exists(self.stop_file):
            os.remove(self.stop_file)
        sc["stop_file"] = self.stop_file
        sc_path = os.path.join(sc_dir, "scene.json")
        with open(sc_path, "w", encoding="utf-8") as fh:
            json.dump(sc, fh)
        self.run_mode, self.run_folder = mode, folder
        self.n_total = len(names) if names else (1 if video else len(p["cameras"]))
        self.n_done = 0
        self.stop_asked = False
        self.results_new = []
        self.video_file = os.path.join(folder, sc["video"]["file"]) if video else None
        self.log.clear()
        self.bar.setValue(0)
        self.set_busy(True)
        proc = QProcess(self)
        proc.setProgram(__import__("paths").python_exe())
        proc.setWorkingDirectory(HERE)
        args = ["-u", os.path.join(HERE, "render_core.py"), sc_path, folder] + ([json.dumps(names)] if names else [])
        proc.setArguments(args)
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        proc.readyReadStandardOutput.connect(self.read_proc)
        proc.finished.connect(self.proc_finished)
        proc.errorOccurred.connect(self.proc_error)
        self.proc = proc
        self.statusBar().showMessage("Rendering...")
        proc.start()

    def read_proc(self):
        if self.proc is None:
            return
        txt = bytes(self.proc.readAllStandardOutput()).decode("utf-8", "replace")
        for line in txt.splitlines():
            if not line.strip():
                continue
            if line.startswith("PROGRESS "):
                try:
                    _w, f, eta = line.split()
                    self.bar.setValue(int(100 * float(f)))
                    e = int(float(eta))
                    self.statusBar().showMessage(f"Rendering... {100 * float(f):.0f} %   about {e // 3600}:{e % 3600 // 60:02d}:{e % 60:02d} left")
                except ValueError:
                    pass
                continue
            self.log.appendPlainText(line)
            if " saved " in line and line.startswith("["):
                path = line.split(" saved ", 1)[1].split("  (stopped")[0].strip()
                self.n_done += 1
                self.results_new.append(path)
                self.add_result(path)
            elif line.startswith("saved ") and line.strip().lower().endswith(".mp4"):
                path = line[len("saved "):].strip()
                self.n_done += 1
                self.bar.setValue(100)
                self.results_new.append(path)
                self.add_result(path)

    def proc_error(self, err):
        if self.proc is not None and err == QProcess.ProcessError.FailedToStart:
            self.log.appendPlainText("The renderer could not start: " + self.proc.errorString())

    def proc_finished(self, code, _status):
        self.read_proc()
        ok = code == 0 and self.n_done >= 1
        mode = self.run_mode
        self.set_busy(False)
        self.proc = None
        if ok and mode == "video_preview" and self.video_file and os.path.exists(self.video_file):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.video_file))
        what = "video" if mode.startswith("video") else "picture(s)"
        self.statusBar().showMessage(f"Done: {self.n_done} {what} saved in {self.run_folder}" if ok else
                                     ("Stopped." if self.stop_asked else "The render did not finish (see the log below)."))
        if not ok and not self.stop_asked:
            self.log.appendPlainText("(the renderer stopped; if the text above does not explain it, please send it to me)")

    def stop_render(self):
        if self.proc is None:
            return
        if self.stop_asked:                                   # second press: stop at once
            self.proc.kill()
            self.log.appendPlainText("Stopped at once.")
            return
        self.stop_asked = True
        try:
            open(self.stop_file, "w").close()
        except OSError:
            self.proc.kill()
            return
        self.log.appendPlainText("Stopping after the current pass (pictures keep what they have; a video keeps its frames and continues next time). "
                                 "Press Stop again to stop at once.")
        proc = self.proc
        QTimer.singleShot(90000, lambda: proc.kill() if self.proc is proc else None)

    def set_busy(self, on):
        self.busy = on
        for b in self.run_btns + self.run_btns_extra:
            b.setEnabled(not on)
        self.b_stop.setEnabled(on)
        self.a_stop.setEnabled(on)
        for a in (self.a_prev, self.a_sel, self.a_all, self.a_vprev, self.a_video):
            a.setEnabled(not on)

    def add_result(self, path):
        it = QListWidgetItem(os.path.basename(path))
        it.setData(Qt.ItemDataRole.UserRole, path)
        self.files.addItem(it)
        self.files.setCurrentRow(self.files.count() - 1)

    def show_result(self, i):
        if i < 0:
            return
        path = self.files.item(i).data(Qt.ItemDataRole.UserRole)
        pm = QPixmap(path)
        if pm.isNull():
            return
        self.img.setPixmap(pm.scaled(self.img.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    # ================================================================ guide
    def show_guide(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Render Studio - guide")
        dlg.resize(760, 720)
        lay = QVBoxLayout(dlg)
        box = QTextEdit()
        box.setReadOnly(True)
        try:
            gp = next((q for q in (os.path.join(HERE, "docs", "README_render.txt"), os.path.join(HERE, "README_render.txt")) if os.path.exists(q)),
                      os.path.join(HERE, "README_render.txt"))
            with open(gp, "r", encoding="utf-8") as fh:
                box.setPlainText(fh.read())
        except OSError:
            box.setPlainText("README_render.txt was not found next to the program.")
        lay.addWidget(box)
        dlg.exec()


def main():
    app = QApplication(sys.argv)
    try:
        import pm_app
        pm_app.apply_theme(app)
    except Exception:
        pass
    try:
        import gpd_app
        gpd_app.install_excepthook()
    except Exception:
        pass
    w = RenderStudio(sys.argv[1] if len(sys.argv) > 1 else None)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
