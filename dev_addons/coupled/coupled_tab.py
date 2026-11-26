"""coupled_tab.py - the Coupled Physics window: ONE window for the fluid, heat and stress analyses of the same geometry (2D or 3D) and their combined solve.  At the top of its left column
a strip of five buttons - Fluid, Thermal, Structural, Coupled, Viz - chooses what the window shows: an analysis (its own Outline and Details on the left, its own model view on the right: the
side panel and the view of that analysis's window, hosted here: coupled_host), the coupling (the options, Solve with the passes of the loop, and the report), or the picture of the last solve
(Viz: coupled_viz).  The analyses are set up in their own tabs of the strip, where they always were set up; the Coupled tab solves them together.

The solve is what it was: the heat problem first, its temperature field handed to the stress problem (every node of the stress mesh takes the temperature at its place in the heat mesh; the
two analyses keep their own meshes), and the stress problem solved with that temperature as a load of its own.  With a Fluid Flow analysis (2D or 3D) wired in as well: the fluid and the heat
analysis exchange heat at the walls they share (a loop until the two agree), and the pressure of the flow is the load of the stress analysis; the structure can move the flow.

The window does not own the analyses: the Workbench block gives it their windows (members_source) and it drives them through coupled_members.  A window opened without a Workbench block says
so.  The project folder (.gpx) holds the options only (state.sim); every analysis keeps its own project folder."""
import html
import json
import os
import time
import traceback

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QApplication, QCheckBox, QDoubleSpinBox, QHBoxLayout, QLabel, QMessageBox, QPushButton, QSpinBox, QSplitter, QStackedWidget, QTextBrowser, QVBoxLayout,
                             QWidget)

import coupled_check
import coupled_engine as ce
import coupled_ext
import coupled_handover
import coupled_host
import coupled_members as cm
import coupled_steps
import coupled_viz
import sim_project
import sim_report as R
import sim_ui
import ui_kit

KIND = coupled_ext.KIND
LABEL = coupled_ext.LABEL
DEFAULT_OPTIONS = {"tmean_tol_pct": 2.0, "conj_tol_pct": 1.0, "conj_max": 25, "shear": False, "moves_flow": False, "fsi_tol_pct": 1.0, "fsi_max": 12}


def mesh_count(m):
    """How many elements the mesh of a moved flow has (2D: triangles, 3D: tetrahedra)."""
    return int(m.get("triangles", m.get("cells", 0)))


def tol_text(kn):
    """How far a known answer may be off: 'x K' for a temperature, else 'x %'."""
    return f"{kn['tol_abs']:g} K" if kn.get("tol_abs") is not None else f"{kn['tol_pct']:g} %"


EXTRA_OPTIONS = ("known",)                # a known answer of the problem (the example projects set it): {"name", "expected", "unit", "tol_pct", "axis"}: the growth of the far end of a 3D body, in mm;
#                                           or {"kind": "wall_temperature", "name", "expected" (degC), "unit": "degC", "tol_abs" (K)}: the walls of a fluid and a very conductive solid
EVENT_LIMIT = 300


def optional(name):
    """A module of another add-on (solid_diag ...) or None when that add-on is not there."""
    try:
        import importlib
        return importlib.import_module(name)
    except ImportError:
        return None


class _Marks:
    """What the Outline of the Coupled page asks of its window: a tick in front of every row (nothing is 'incomplete' or 'to do' about a row of this page)."""

    def __init__(self, keys):
        self.keys = keys

    def outline_marks(self):
        return {k: "ok" for k in self.keys}


class CoupledWindow(QWidget):
    kind = KIND
    label = LABEL

    def __init__(self, shell=None, path=None):
        super().__init__()
        coupled_ext.ensure_registered()
        self.host = shell
        self.path = path
        self.options = dict(DEFAULT_OPTIONS)
        self.members_source = None            # a function -> {"windows": {kind: window} or a function giving it, "labels": {role: text}, "show": {role: function that brings it in front}, "problem": text or None, "note": text}
        self.result = None
        self.used = None                      # the members of the last solve
        self.check_result = None
        self.last_error = ""
        self.events = []
        self.running = False
        self.cancel_flag = False
        self.live = []
        self.saved_sig = None
        self.hosted = {}                      # role -> coupled_host.Hosted: the analyses whose panes are shown in this window
        self.role = "coupled"                 # what the window shows now: a role of the strip
        self.src = {}
        self.solved_for = None                # current_key() when the last solve was made
        self.build()
        self.saved_sig = self.signature()
        self.refresh()

    # ------------------------------------------------------------------------------------------------------------------------------ the window
    ORDER = ("Coupling", "Options", "Solve", "Results", "Self-check", "Diagnostics report")

    def build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(ui_kit.kind_chip(LABEL, "#6d33c0"))
        self.info_lbl = QLabel("")
        self.info_lbl.setWordWrap(True)
        self.info_lbl.setTextFormat(Qt.TextFormat.RichText)
        self.info_lbl.setStyleSheet(f"color:{ui_kit.MUTED};")
        top.addWidget(self.info_lbl, 1)
        root.addLayout(top)
        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.setChildrenCollapsible(False)
        col = QWidget()
        cl = QVBoxLayout(col)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        self.strip = coupled_host.RoleStrip()
        cl.addWidget(self.strip)
        self.left = QStackedWidget()
        cl.addWidget(self.left, 1)
        col.setMinimumWidth(340)
        self.right = QStackedWidget()
        self.split.addWidget(col)
        self.split.addWidget(self.right)
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 1)
        self.split.setSizes([sim_ui.SIDE_W, 1000])
        root.addWidget(self.split, 1)
        self.line = QLabel("")
        self.line.setStyleSheet(f"color:{ui_kit.MUTED};")
        root.addWidget(self.line)
        self.build_member_pages()
        self.build_coupled_page()
        self.viz = coupled_viz.VizPage(self)
        self.left.addWidget(self.viz.panel)
        self.right.addWidget(self.viz.canvas)
        self.strip.picked.connect(self.show_role)
        self.ticker = coupled_host.Ticker(self, self.update_marks)

    def build_member_pages(self):
        """The page of an analysis that is wired in but not hosted (a window opened without the Workbench, or an analysis that opens in a tab of its own): what it is, and a button that opens it."""
        self.placeholders = {}
        for role, text in (("fluid", "fluid"), ("thermal", "heat"), ("structural", "stress")):
            box = QWidget()
            lay = QVBoxLayout(box)
            lay.setContentsMargins(10, 10, 10, 10)
            lbl = sim_ui.wrapped("")
            lbl.setTextFormat(Qt.TextFormat.RichText)
            lay.addWidget(lbl)
            b = QPushButton(f"Open the {text} analysis")
            b.clicked.connect(lambda *_, r=role: self.show_member(r))
            lay.addWidget(b)
            lay.addStretch(1)
            blank = QLabel("")
            self.left.addWidget(box)
            self.right.addWidget(blank)
            self.placeholders[role] = (box, blank, lbl)
            setattr(self, {"fluid": "b_fluid", "thermal": "b_heat", "structural": "b_stress"}[role], b)

    def build_coupled_page(self):
        s1 = sim_ui.Section("coupled", 1, "Coupling", True)
        self.members_lbl = sim_ui.wrapped("")
        self.members_lbl.setTextFormat(Qt.TextFormat.RichText)
        s1.body.addWidget(self.members_lbl)
        self.link_lbl = sim_ui.wrapped("")
        self.link_lbl.setTextFormat(Qt.TextFormat.RichText)
        s1.body.addWidget(self.link_lbl)

        s2 = sim_ui.Section("coupled", 2, "Options", True)
        orow = QHBoxLayout()
        orow.addWidget(QLabel("Largest change of the average temperature (%)"))
        self.e_tol = QDoubleSpinBox()
        self.e_tol.setRange(0.01, 50.0)
        self.e_tol.setDecimals(2)
        self.e_tol.setValue(self.options["tmean_tol_pct"])
        self.e_tol.setToolTip("The average temperature of the stress mesh may differ from the average of the heat mesh by this share of the temperature range before the check 'Average temperature kept' fails.")
        self.e_tol.valueChanged.connect(self.options_changed)
        orow.addWidget(self.e_tol)
        s2.body.addLayout(orow)
        self.fluid_opts = QWidget()                                   # only with a fluid analysis wired in
        fo = QVBoxLayout(self.fluid_opts)
        fo.setContentsMargins(0, 0, 0, 0)
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("Heat exchange: heat flux agreement (%)"))
        self.e_conj_tol = QDoubleSpinBox()
        self.e_conj_tol.setRange(0.001, 50.0)
        self.e_conj_tol.setDecimals(3)
        self.e_conj_tol.setValue(self.options["conj_tol_pct"])
        self.e_conj_tol.setToolTip("The fluid and the solid are solved again and again until the heat flux on the wall that the solid takes and the one the fluid gives differ by less than this share of the largest flux.")
        self.e_conj_tol.valueChanged.connect(self.options_changed)
        r1.addWidget(self.e_conj_tol)
        fo.addLayout(r1)
        r2 = QHBoxLayout()
        r2.addWidget(QLabel("Heat exchange: at most this many iterations"))
        self.e_conj_max = QSpinBox()
        self.e_conj_max.setRange(1, 200)
        self.e_conj_max.setValue(int(self.options["conj_max"]))
        self.e_conj_max.valueChanged.connect(self.options_changed)
        r2.addWidget(self.e_conj_max)
        fo.addLayout(r2)
        self.cb_shear = QCheckBox("Pressure on the stress analysis includes the wall shear of the flow")
        self.cb_shear.setChecked(bool(self.options["shear"]))
        self.cb_shear.toggled.connect(self.options_changed)
        fo.addWidget(self.cb_shear)
        self.cb_moves = QCheckBox("The structure moves the flow: the flow is solved again round the body as the stress analysis moves it")
        self.cb_moves.setChecked(bool(self.options["moves_flow"]))
        self.cb_moves.setToolTip("Needs a stress analysis wired in. The body in the fluid window is moved by the displacement of the stress analysis, meshed again and the flow is solved round it; the "
                                 "stress analysis is loaded with that pressure, and so on until the displacement stops changing. The stress analysis stays linear (small displacements).")
        self.cb_moves.toggled.connect(self.options_changed)
        fo.addWidget(self.cb_moves)
        r3 = QHBoxLayout()
        r3.addWidget(QLabel("Moving the flow: displacement agreement (%)"))
        self.e_fsi_tol = QDoubleSpinBox()
        self.e_fsi_tol.setRange(0.001, 50.0)
        self.e_fsi_tol.setDecimals(3)
        self.e_fsi_tol.setValue(self.options["fsi_tol_pct"])
        self.e_fsi_tol.setToolTip("The passes stop when the displacement of the stress analysis differs from the one the flow was solved with by less than this share of the largest displacement.")
        self.e_fsi_tol.valueChanged.connect(self.options_changed)
        r3.addWidget(self.e_fsi_tol)
        fo.addLayout(r3)
        r4 = QHBoxLayout()
        r4.addWidget(QLabel("Moving the flow: at most this many passes"))
        self.e_fsi_max = QSpinBox()
        self.e_fsi_max.setRange(1, 100)
        self.e_fsi_max.setValue(int(self.options["fsi_max"]))
        self.e_fsi_max.valueChanged.connect(self.options_changed)
        r4.addWidget(self.e_fsi_max)
        fo.addLayout(r4)
        self.moves_rows = (self.e_fsi_tol, self.e_fsi_max)
        s2.body.addWidget(self.fluid_opts)

        s3 = sim_ui.Section("coupled", 3, "Solve", True)
        self.b_solve = sim_ui.solve_button("Solve")
        self.b_cancel = sim_ui.solve_side_button("Cancel")
        self.b_solve.clicked.connect(lambda *_: self.solve())
        self.b_cancel.clicked.connect(lambda *_: self.cancel())
        s3.body.addWidget(sim_ui.solve_row(self.b_solve, self.b_cancel))
        self.status_lbl = sim_ui.wrapped("")
        s3.body.addWidget(self.status_lbl)
        self.steps_lbl = sim_ui.wrapped("")
        self.steps_lbl.setTextFormat(Qt.TextFormat.RichText)
        s3.body.addWidget(self.steps_lbl)

        s4 = sim_ui.Section("coupled", 4, "Results", True)
        s4.body.addWidget(sim_ui.wrapped("The report of the last solve is on the right: what was handed over, the checks and the known answer. The pictures are in the Viz tab."))
        self.b_top = QPushButton("Show the report from the top")
        self.b_top.clicked.connect(lambda *_: self.view.verticalScrollBar().setValue(0))
        s4.body.addWidget(self.b_top)

        s5 = sim_ui.Section("coupled", 5, "Self-check", True)
        s5.body.addWidget(sim_ui.wrapped("Solves problems with known answers on stand-in analyses and prints PASS or FAIL beside the numbers; it also checks that the checks can fail."))
        self.b_check = QPushButton("Self-check")
        self.b_check.setToolTip("Solves problems with known answers on stand-in analyses and prints PASS or FAIL beside the numbers; it also checks that the checks can fail.")
        self.b_check.clicked.connect(lambda *_: self.run_self_check())
        s5.body.addWidget(self.b_check)

        s6 = sim_ui.Section("coupled", 6, "Diagnostics report", True)
        s6.body.addWidget(sim_ui.wrapped("What this window and its analyses did, with times, checks and every error: also saved as diagnostics.txt in the project folder. Send it when something goes wrong."))
        self.b_diag = QPushButton("Diagnostics report")
        self.b_diag.setToolTip("What this window and its two analyses did, with times, checks and every error: also saved as diagnostics.txt in the project folder. Send it when something goes wrong.")
        self.b_diag.clicked.connect(lambda *_: self.show_diagnostics())
        s6.body.addWidget(self.b_diag)

        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(4, 4, 4, 4)
        cl.setSpacing(4)
        self.sections = [s1, s2, s3, s4, s5, s6]
        for s_ in self.sections:
            cl.addWidget(s_)
        cl.addStretch(1)
        panel = sim_ui.make_panel(content, [])
        self.outline = sim_ui.outlinize(panel, None, "coupled", order=self.ORDER)
        self.outline.attach(_Marks(self.ORDER))
        self.outline.select("Solve")
        self.outline.touched = True
        self.panel = panel
        self.view = QTextBrowser()
        self.view.setOpenLinks(False)
        self.left.addWidget(panel)
        self.right.addWidget(self.view)
        sim_ui.solve_shortcut(panel, self.b_solve)
        sim_ui.solve_shortcut(self.view, self.b_solve)

    # ------------------------------------------------------------------------------------------------------------------------------ the project
    def title(self):
        return os.path.basename(self.path.rstrip("/\\")) if self.path else LABEL

    def signature(self):
        return json.dumps(self.options, sort_keys=True)

    def is_dirty(self):
        """The options changed, or an analysis shown here has changes that are not saved (the window is the tab of them all)."""
        if self.signature() != self.saved_sig:
            return True
        for h in self.hosted.values():
            try:
                if h.win.is_dirty():
                    return True
            except Exception:                                                        # noqa: BLE001
                pass
        return False

    def save_members(self):
        """Saves the analyses shown here that have changes (each into its own project folder).  -> the roles that could not be saved."""
        bad = []
        for role, h in self.hosted.items():
            try:
                if h.win.is_dirty() and h.win.save() is False:
                    bad.append(role)
            except Exception as ex:                                                  # noqa: BLE001
                self.log("error", f"The {role} analysis could not be saved: {ex}")
                bad.append(role)
        return bad

    def project_ok(self):
        return bool(self.path) and sim_project.kind_of_folder(self.path) == KIND

    def create_project(self, path):
        sim_project.create(path, KIND)
        self.path = path
        self.save()
        return True

    def save(self, as_new=False):
        bad = self.save_members()
        if not self.project_ok():
            self.say("A Coupled Physics window is saved with its Workbench project: there is no project folder to save into here.")
            return False
        if bad:
            self.say("Not saved: " + ", ".join(coupled_host.NAMES[r] for r in bad) + " could not be saved (see the diagnostics report).")
            return False
        try:
            st = sim_project.state_path(self.path)
            tmp = st + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"kind": KIND, "options": self.options}, f)
            os.replace(tmp, st)
        except OSError as ex:
            QMessageBox.warning(self, "Save", f"Could not save: {ex}")
            return False
        self.saved_sig = self.signature()
        return True

    @classmethod
    def open_project(cls, shell, folder):
        folder = os.path.abspath(folder.rstrip("/\\") or folder)
        if sim_project.kind_of_folder(folder) != KIND:
            raise ValueError(f"not a {LABEL} project folder")
        w = cls(shell=shell, path=folder)
        sp = sim_project.state_path(folder)
        if os.path.isfile(sp):
            try:
                with open(sp, encoding="utf-8") as f:
                    got = json.load(f).get("options") or {}
                w.options.update({k: v for k, v in got.items() if k in DEFAULT_OPTIONS or k in EXTRA_OPTIONS})
                want = dict(w.options)                                          # (each box reports to options_changed as it is set: take the values before the first one is)
                w.e_tol.setValue(float(want["tmean_tol_pct"]))
                w.e_conj_tol.setValue(float(want["conj_tol_pct"]))
                w.e_conj_max.setValue(int(want["conj_max"]))
                w.cb_shear.setChecked(bool(want["shear"]))
                w.cb_moves.setChecked(bool(want["moves_flow"]))
                w.e_fsi_tol.setValue(float(want["fsi_tol_pct"]))
                w.e_fsi_max.setValue(int(want["fsi_max"]))
                w.options_changed()
            except (OSError, ValueError, TypeError):
                pass
        w.saved_sig = w.signature()
        w.refresh()
        return w

    def options_changed(self, *_):
        self.options["tmean_tol_pct"] = float(self.e_tol.value())
        self.options["conj_tol_pct"] = float(self.e_conj_tol.value())
        self.options["conj_max"] = int(self.e_conj_max.value())
        self.options["shear"] = bool(self.cb_shear.isChecked())
        self.options["moves_flow"] = bool(self.cb_moves.isChecked())
        self.options["fsi_tol_pct"] = float(self.e_fsi_tol.value())
        self.options["fsi_max"] = int(self.e_fsi_max.value())
        for w in self.moves_rows:
            w.setEnabled(self.options["moves_flow"])
        self.refresh_handover()

    # ------------------------------------------------------------------------------------------------------------------------------ what it says
    def say(self, text):
        self.status_lbl.setText(text)
        if self.role == "coupled" and text:
            self.line.setText(f"Coupled: {text}")
        self.log("say", text)

    def log(self, level, text):
        if not text:
            return
        self.events.append((time.time(), level, str(text)))
        if len(self.events) > EVENT_LIMIT:
            del self.events[:len(self.events) - EVENT_LIMIT]

    def members(self):
        """What the Workbench block gives: {"windows", "labels", "show", "problem", "note"}; without a block there is nothing."""
        if self.members_source is None:
            return {"windows": {}, "labels": {}, "show": {}, "problem": None, "note": "This window works inside a Workbench project: add a Coupled Physics block there and wire a heat analysis and a stress analysis into it."}
        return self.members_source()

    def refresh(self):
        """The members, the link, the strip and the buttons (what can be said before a solve)."""
        try:
            src = self.members()
        except Exception as ex:                                                      # noqa: BLE001
            src = {"windows": {}, "labels": {}, "show": {}, "problem": None, "note": f"The analyses could not be read: {ex}"}
        self.src = src
        labels = src.get("labels", {})
        lines = []
        for role, name in (("fluid", "Fluid"), ("thermal", "Heat"), ("structural", "Stress")):
            if role == "fluid" and not labels.get("fluid"):
                continue                                                                  # (the fluid is optional: it is listed when it is wired in)
            lines.append(f"<b>{name}</b>: " + (labels.get(role) or "<span style='color:%s'>not wired in yet</span>" % R.GREY))
        if src.get("problem"):
            lines.append(R.note(src["problem"], R.AMBER))
        elif src.get("note"):
            lines.append(R.note(src["note"]))
        self.members_lbl.setText("<br>".join(lines))
        have = self.wired(labels)
        wired = [r for r in coupled_host.MEMBER_ROLES if labels.get(r)]
        self.strip.set_roles(wired + ["coupled", "viz"])
        for role in coupled_host.MEMBER_ROLES:
            box, _blank, lbl = self.placeholders[role]
            lbl.setText(f"<b>{coupled_host.NAMES[role]}</b>: " + (labels.get(role) or "not wired in") + "<br>This analysis is set up in a window of its own; it is not shown inside this one.")
        if self.role not in self.strip.roles():
            self.show_role("coupled")
        else:
            self.show_role(self.role)
        self.info_lbl.setText(self.info_text(src, labels))
        self.fluid_opts.setVisible(bool(labels.get("fluid")))
        self.cb_moves.setEnabled(bool(labels.get("structural")))                          # (the structure can only move the flow when there is one)
        for w in self.moves_rows:
            w.setEnabled(bool(labels.get("structural")) and bool(self.options["moves_flow"]))
        self.b_fluid.setEnabled(bool(src.get("show", {}).get("fluid")))
        self.b_heat.setEnabled(bool(src.get("show", {}).get("thermal")))
        self.b_stress.setEnabled(bool(src.get("show", {}).get("structural")))
        fl, th, st = (bool(labels.get(r)) for r in ("fluid", "thermal", "structural"))
        things = "faces" if int(src.get("dim") or 2) == 3 else "edges"                    # what the walls of a flow are called
        rows = []
        if fl and th:
            rows.append(("Heat exchange", "Fluid ⇄ Heat", "the walls the two share", "the wall temperature of the solid and the heat flux of the fluid, iterated until they agree"))
        if fl and st:
            rows.append(("Pressure", "Fluid → Stress", "the walls of the fluid that the stress analysis does not hold", f"the pressure of the settled flow on those {things}"))
            if self.options.get("moves_flow"):
                rows.append(("Movement", "Stress → Fluid", "every point of the outline of the body in the fluid", "the displacement of the stress analysis: the body is moved, "
                             + ("the air mesh follows it" if things == "faces" else "meshed again") + ", the flow solved again"))
        if th and st:
            rows.append(("Temperature", "Heat → Stress", "every node of the stress mesh", "the temperature field of the heat analysis (linked: its values are not typed)"))
        t = "".join(f"<tr><td><b>{a}</b></td><td>{b}</td><td>{c}</td></tr>" for a, b, c, _d in rows)
        if fl:
            note = (("The structure moves the flow: the flow, the stress and the displacement are repeated until the displacement stops changing; the stress analysis stays linear (small displacements). "
                     if st and self.options.get("moves_flow") else "The body is not moved by the structure: the flow is solved round it as drawn. ") +
                    "The flow does not depend on the temperature (no buoyancy), so it is solved once per pass. The heat exchange is repeated until the fluid and the solid agree on the wall; "
                    f"the {things} that touch the solid are chosen in the fluid window ('Wall of the thermal analysis'), and what is set on those {things} in the thermal analysis is replaced "
                    f"by the exchange. The pressure goes to every {things[:-1]} of the stress analysis that the fluid touches and that no support holds.")
        else:
            note = ("One way: the stress does not change the temperature, so the heat problem is solved once and its field is given to the stress problem. The thermal expansion "
                    "coefficient and the reference temperature are the ones of the material in the stress analysis (Material and analysis).")
        self.link_lbl.setText("<table cellspacing='0' cellpadding='3'>" + t + "</table>" + R.note(note))
        self.enable_buttons(have)
        self.show_report()
        self.refresh_handover()
        self.update_marks()

    @staticmethod
    def info_text(src, labels):
        """The line beside the badge: of what, and what the three analyses are."""
        fl, th, st = (bool(labels.get(r)) for r in ("fluid", "thermal", "structural"))
        names = [n for n, on in (("fluid", fl), ("heat", th), ("stress", st)) if on]
        what = (", ".join(names[:-1]) + " and " + names[-1] if len(names) > 1 else (names[0] if names else "")) + (" analyses" if len(names) > 1 else " analysis" if names else "")
        one = "one part" if int(src.get("dim") or 2) == 3 else "one sketch"
        part = src.get("part")
        head = f"of the part <b>{part}</b> (the copy in the project)" if part else ""
        tail = f"{what} of {one}" if what else ""
        return " · ".join(x for x in (head, tail) if x)

    @staticmethod
    def wired(labels):
        """Enough is wired in to solve: a heat and a stress analysis, or a fluid with one of them."""
        fl, th, st = (bool(labels.get(r)) for r in ("fluid", "thermal", "structural"))
        return (th and st) or (fl and (th or st))

    def enable_buttons(self, have=None):
        if have is None:
            have = self.wired(getattr(self, "src", {}).get("labels", {}))
        self.b_solve.setEnabled(have and not self.running)
        self.b_cancel.setEnabled(self.running)
        self.b_check.setEnabled(not self.running)

    # ------------------------------------------------------------------------------------------------------------------------------ the strip and the analyses shown here
    def page_of(self, role):
        """(left widget, right widget) of a role: the panes of the hosted analysis, its placeholder, the Coupled page or the Viz page."""
        h = self.hosted.get(role)
        if h is not None:
            return h.panel, h.view
        if role in self.placeholders:
            return self.placeholders[role][0], self.placeholders[role][1]
        if role == "viz":
            return self.viz.panel, self.viz.canvas
        return self.panel, self.view

    def show_role(self, role):
        """Shows a tab of the strip.  -> False when there is no such tab now (the analysis is not wired in)."""
        if role not in self.strip.roles():
            return False
        left, right = self.page_of(role)
        self.left.setCurrentWidget(left)
        self.right.setCurrentWidget(right)
        self.strip.select(role)
        self.role = role
        if role == "viz":
            self.viz.refresh()
        else:
            self.viz.stop()                                                               # (the animation does not go on behind another tab)
        self.line.setText(self.line_for(role))
        return True

    def line_for(self, role):
        """The one line at the bottom for a tab."""
        labels = (getattr(self, "src", None) or {}).get("labels", {})
        n = sum(1 for r in coupled_host.MEMBER_ROLES if labels.get(r))
        if role in coupled_host.MEMBER_ROLES:
            together = {3: "the three", 2: "the two"}.get(n, "them")
            return f"{coupled_host.NAMES[role]}: set up here. Solving {together} together is in the Coupled tab." if role in self.hosted else \
                   f"{coupled_host.NAMES[role]}: this analysis is set up in a window of its own."
        if role == "viz":
            return "Viz: shows the last coupled solve. Nothing here changes the result."
        return "Coupled: solves the analyses together. Set each of them up in its own tab first." if self.strip.roles() != ["coupled", "viz"] else \
               "Coupled: wire the analyses into the Physics cell of this block in the Workbench."

    def host_member(self, role, win):
        """Shows the side panel and the view of an analysis window here (the window itself stays alive, hidden).  A role already shown is replaced."""
        if role not in coupled_host.MEMBER_ROLES:
            raise ValueError(f"{role} is not an analysis")
        if role in self.hosted:
            self.unhost_member(role)
        h = coupled_host.Hosted(role, win)
        win.setParent(self)
        win.hide()
        self.left.addWidget(h.panel)
        self.right.addWidget(h.view)
        h.relays = coupled_host.route_status(win, lambda text, r=role: self.member_said(r, text))
        coupled_host.rebind_solve(h)
        coupled_host.fix_fitter(h)
        self.hosted[role] = h
        if self.role == role:
            self.show_role(role)
        self.refresh_handover()
        self.update_marks()
        return h

    def unhost_member(self, role):
        """Takes an analysis out of the window.  -> its window (the caller shuts it down), or None."""
        h = self.hosted.pop(role, None)
        if h is None:
            return None
        tab = getattr(h.win, "tab", None)
        if tab is not None:
            coupled_handover.apply(tab, [])                                               # (on its own again it hands nothing over)
        self.refresh_handover()
        if self.role == role:
            self.show_role("coupled")
        for wdg, stack in ((h.panel, self.left), (h.view, self.right)):
            try:
                stack.removeWidget(wdg)
                wdg.hide()
                wdg.setParent(None)
                wdg.deleteLater()
            except RuntimeError:
                pass
        self.update_marks()
        return h.win

    def refresh_handover(self):
        """Gives every hosted 2D analysis the rows of what the others hand over to it (coupled_handover); the Outline of one that changed is brought up to date."""
        src = getattr(self, "src", None) or {}
        labels = src.get("labels", {})
        names = src.get("titles") or labels                                                   # (the names of the analyses: 'Air flow', not '2D Fluid Flow N Air flow')
        tabs = {r: getattr(h.win, "tab", None) for r, h in self.hosted.items()}
        for role, h in self.hosted.items():
            tab = tabs.get(role)
            if tab is None:
                continue
            try:
                rows = coupled_handover.rows_for(role, tabs, names, self.options) if labels.get(role) else []
                changed = coupled_handover.apply(tab, rows)
            except Exception as ex:                                                       # noqa: BLE001 - a window being rebuilt has nothing to say yet
                self.log("warn", f"handed-over rows of {role}: {ex}")
                continue
            if changed and h.outline is not None:
                try:
                    h.outline.sync()
                except RuntimeError:
                    pass

    def hosted_windows(self):
        return {r: h.win for r, h in self.hosted.items()}

    def member_said(self, role, text):
        """What a hosted analysis writes in its status line is the line of the window while its tab is shown."""
        if role == self.role and text:
            self.line.setText(f"{coupled_host.NAMES[role]}: {text}")
            self.line.setToolTip(text)

    def show_member(self, role):
        if role in self.hosted:
            self.show_role(role)
            return
        f = getattr(self, "src", {}).get("show", {}).get(role)
        if f is not None:
            f()

    # ------------------------------------------------------------------------------------------------------------------------------ the marks
    def current_key(self):
        """What the solve depends on, as the Workbench counts it (the stamps of the Geometry and Setup cells of the analyses and of this block); None without a Workbench."""
        fn = (getattr(self, "src", None) or {}).get("deps_key")
        if callable(fn):
            try:
                return fn()
            except Exception:                                                        # noqa: BLE001
                return None
        return None

    def is_current(self):
        """True when the last solve is the answer to what is set up now.  The Workbench's own record of what changed is used (it is brought up to date when the project reads the analyses back:
        saving, or coming back to the Workbench), so a change just typed in an analysis shows here a little later; a window without a Workbench takes its last solve for current."""
        if self.result is None or not self.result.get("ok", False):
            return False
        key = self.current_key()
        return key is None or key == self.solved_for

    def show_steps(self):
        """The passes of the last solve under the Solve button."""
        rows = coupled_steps.step_rows(self.result, self.options)
        if not rows:
            self.steps_lbl.setText("")
            return
        body = "".join(f"<tr><td style='color:#3d8c6c'><b>✓</b></td><td>{t}</td><td align='right' style='color:{R.GREY}'>{d}</td></tr>" for _k, t, d in rows)
        self.steps_lbl.setText(f"<p>{coupled_steps.header_text(self.result)}</p><table width='100%' cellspacing='0' cellpadding='3'>{body}</table>")

    def update_marks(self):
        """The marks of the strip: Setup ready (tick) / not ready (question mark) for an analysis; solved and current (tick), not solved or changed since (bolt), not enough wired (question mark) for Coupled;
        a current result (tick) or none (bolt) for Viz."""
        src = getattr(self, "src", None) or {}
        labels = src.get("labels", {})
        self.refresh_handover()                                                          # (the walls of a fluid are known once it is meshed: the rows follow)
        given = {}
        fn = src.get("marks")
        if callable(fn):
            try:
                given = fn() or {}
            except Exception:                                                        # noqa: BLE001
                given = {}
        for role in coupled_host.MEMBER_ROLES:
            if not labels.get(role):
                continue
            h = self.hosted.get(role)
            kind = given.get(role) or (h.setup_mark() if h is not None else "ok")
            self.strip.set_mark(role, kind, {"ok": "Setup is ready.", "incomplete": "Setup is not ready: see its Outline for what is missing.", "update": "Setup has changed."}.get(kind, ""))
        if src.get("problem") or not self.wired(labels):
            self.strip.set_mark("coupled", "incomplete", str(src.get("problem") or "Not enough analyses are wired in."))
        elif self.is_current():
            self.strip.set_mark("coupled", "ok", "The last solve is the answer to what is set up now.")
        else:
            self.strip.set_mark("coupled", "update", "Not solved yet, or something changed since the last solve: press Solve.")
        self.strip.set_mark("viz", "ok" if (self.result is not None and self.is_current()) else "update",
                            "The picture shows the last solve." if (self.result is not None and self.is_current()) else "No current result to show: solve in the Coupled tab.")

    def showEvent(self, ev):
        super().showEvent(ev)
        self.ticker.start()
        self.update_marks()

    def hideEvent(self, ev):
        super().hideEvent(ev)
        self.ticker.stop()

    # ------------------------------------------------------------------------------------------------------------------------------ solving
    def cancel(self):
        if self.running:
            self.cancel_flag = True
            self.say("Cancelling...")

    def progress(self, text, frac):
        self.status_lbl.setText(f"{text}...")
        self.live.append(text)
        self.show_live()
        QApplication.processEvents()

    def show_live(self):
        """The steps of the solve that is running, one row each as the engine reports it: a tick for a step that is done, three dots for the one being worked on."""
        rows = coupled_steps.live_rows(self.live)
        body = "".join((f"<tr><td style='color:#3d8c6c'><b>✓</b></td><td style='color:{R.GREY}'>{html.escape(t)}</td></tr>" if done else
                        f"<tr><td><b>…</b></td><td><b>{html.escape(t)}</b></td></tr>") for done, t in rows)
        self.steps_lbl.setText(f"<p style='color:{R.GREY}'>Working:</p><table width='100%' cellspacing='0' cellpadding='2'>{body}</table>" if rows else "")

    def fail(self, text, error=None):
        self.last_error = error or text
        self.log("error", self.last_error)
        self.result = None
        self.solved_for = None
        self.steps_lbl.setText("")
        self.say(text)
        self.show_report()
        self.update_marks()
        return False

    def solve(self):
        """Solves the heat analysis, hands its field over, solves the stress analysis.  -> True when it was done (the checks may still say no: see the result), else False with the
        reason said in the window (last_error)."""
        if self.running:
            return False
        self.last_error = ""
        try:
            src = self.members()
        except Exception as ex:                                                      # noqa: BLE001
            return self.fail(f"The analyses could not be read: {ex}")
        if src.get("problem"):
            return self.fail(str(src["problem"]))
        try:
            wins = src["windows"]
            mem = cm.pair(wins() if callable(wins) else wins)
        except ce.CoupledError as ex:
            return self.fail(str(ex))
        self.running, self.cancel_flag = True, False
        self.live = []
        self.enable_buttons()
        t0 = time.monotonic()
        try:
            res = ce.solve_coupled(mem, {"tmean_tol": float(self.options["tmean_tol_pct"]) / 100.0, "conj_tol": float(self.options["conj_tol_pct"]) / 100.0,
                                         "conj_max": int(self.options["conj_max"]), "shear": bool(self.options["shear"]), "moves_flow": bool(self.options["moves_flow"]),
                                         "fsi_tol": float(self.options["fsi_tol_pct"]) / 100.0, "fsi_max": int(self.options["fsi_max"])}, progress=self.progress, cancel=lambda: self.cancel_flag)
        except ce.Cancelled:
            self.running = False
            return self.fail("Cancelled.")
        except ce.CoupledError as ex:
            self.running = False
            return self.fail(str(ex))
        except Exception:                                                            # noqa: BLE001
            self.running = False
            tb = traceback.format_exc()
            return self.fail(tb.strip().splitlines()[-1], tb)
        finally:
            self.running = False
        res["wall_seconds"] = time.monotonic() - t0
        self.result, self.used = res, mem
        res["known"] = self.known_answer(mem)
        if "structural" in mem:
            try:
                res["structural"].update(mem["structural"].summary())
            except Exception as ex:                                                  # noqa: BLE001
                self.log("error", f"The result of the stress analysis could not be summarised: {ex}")
        failed = [c["name"] for c in res["checks"] if not c["ok"]]
        self.say(("Solved" if res["ok"] else "Solved, but a check failed") + f" in {res['seconds']:.2g} s" + (f": {', '.join(failed)}." if failed else "."))
        self.log("note", f"solved ({res['dim']}D) in {res['seconds']:.3g} s; checks failed: {failed or 'none'}")
        self.solved_for = self.current_key()
        self.show_steps()
        self.enable_buttons()
        self.show_report()
        self.viz.refresh()
        self.update_marks()
        return True

    def known_answer(self, mem):
        """The known answer of the problem (options["known"]) against what the stress analysis gave: {"name", "expected", "got", "unit", "tol_pct", "ok"} or None."""
        kn = self.options.get("known")
        if not kn:
            return None
        row = {"name": kn.get("name", "Known answer"), "expected": float(kn["expected"]), "unit": kn.get("unit", "mm"), "tol_pct": float(kn.get("tol_pct", 2.0)), "got": None, "ok": False}
        if kn.get("tol_abs") is not None:
            row["tol_abs"] = float(kn["tol_abs"])
        st = mem.get("structural")
        if kn.get("kind") == "wall_temperature":                                     # a body that conducts so well that it is at one temperature: so are the walls the fluid shares with it
            try:
                h = (self.result or {}).get("fluid", {}).get("history", [])[-1]
                lo, hi = float(h["Tw_min"]) - 273.15, float(h["Tw_max"]) - 273.15       # (degC)
                row["got"] = max((lo, hi), key=lambda v: abs(v - row["expected"]))     # the wall point that is farthest from the answer
                row["ok"] = abs(row["got"] - row["expected"]) <= float(row.get("tol_abs", 1.0))
                row["note"] = f"the walls run from {lo:.3f} to {hi:.3f} degC"
            except Exception as ex:                                                  # noqa: BLE001
                row["note"] = f"this known answer needs the flow and the heat exchange ({type(ex).__name__}: {ex})"
            return row
        try:
            if st is None or not hasattr(st, "far_end"):
                row["note"] = "this known answer is for a 3D body"
                return row
            row["got"] = st.far_end(int(kn.get("axis", 0)))
            row["ok"] = abs(row["got"] - row["expected"]) <= row["tol_pct"] / 100.0 * abs(row["expected"])
        except Exception as ex:                                                      # noqa: BLE001
            row["note"] = f"{type(ex).__name__}: {ex}"
        return row

    # ------------------------------------------------------------------------------------------------------------------------------ the combined result
    def show_report(self):
        self.view.setHtml(self.report_html())

    def report_html(self):
        res = self.result
        if res is None:
            msg = R.heading("Coupled Physics") + R.note(
                "Wire a heat analysis and a stress analysis of the same geometry (both 2D or both 3D) into this block, set each of them up in its own window (the heat conditions; the supports, "
                "the material with its thermal expansion coefficient; no mechanical load is needed), then press Solve. A fluid flow analysis (2D or 3D) can be wired in next to a heat analysis "
                "of its dimension (they exchange heat on the walls they share) and / or a stress analysis (it takes the pressure).")
            if self.last_error:
                msg += R.note(self.last_error.strip().splitlines()[-1], R.RED)
            if self.check_result is not None:                                    # the self-check needs no solve: show its rows even before the first one
                msg += self.self_check_html(self.check_result)
            return msg
        h = []
        has = {r: r in res for r in ("fluid", "thermal", "structural")}
        ways = (["fluid ⇄ heat"] if has["fluid"] and has["thermal"] else []) + (["fluid → stress"] if has["fluid"] and has["structural"] else []) + \
               (["heat → stress"] if has["thermal"] and has["structural"] else [])
        how = "one way: " + ", ".join(ways) if not (has["fluid"] and has["thermal"]) else ", ".join(ways)
        if "fsi" in res:
            how = ", ".join(ways) + ", stress → fluid (the structure moves the flow)"
        h.append(R.heading("Coupled solve", f"{res['dim']}D, {how}") + (R.chip("PASS", "ok") if res["ok"] and all(c["ok"] for c in res["checks"]) else R.chip("CHECK FAILED" if res["ok"] else "REFUSED", "bad")))
        if has["fluid"]:
            h += self.fluid_html(res)
        if has["thermal"]:
            th = res["thermal"]
            h.append(R.subhead("Heat analysis"))
            h.append(R.kv([("Lowest temperature", R.temp_text(th["T_min"]), None), ("Highest temperature", R.temp_text(th["T_max"]), None), ("Average temperature", R.temp_text(th["T_mean"]), None),
                           ("Time", f"{th['seconds']:.3g}", "s")]))
        if has["structural"]:
            st = res["structural"]
            h.append(R.subhead("Stress analysis"))
            rows = []
            if "umax" in st:
                rows += [("Largest displacement", R.num(st["umax"]), st["L"]), ("Largest von Mises stress", R.num(st["vm_max"]), st["S"])]
            rows.append(("Time", f"{st['seconds']:.3g}", "s"))
            h.append(R.kv(rows))
        h.append(R.subhead("What was handed over"))
        trs = []
        for t in res["transfers"]:
            if "src_text" in t:                                                      # a transfer of the fluid: described in words
                trs.append([t["name"], f"{t['points']:,} {t.get('unit', 'wall points')}", "iterated until both sides agree" if t["what"] == "heat exchange" else ("by position on the wall" if t.get("unit") == "nodes" else "by position along the edge"),
                            t["src_text"], t["dst_text"], str(t["outside"])])
                continue
            trs.append([t["name"], f"{t['points']:,} nodes", "direct copy" if t["direct"] else "interpolated", f"{R.temp_text(t['src_range'][0])} .. {R.temp_text(t['src_range'][1])}",
                        f"{R.temp_text(t['dst_range'][0])} .. {R.temp_text(t['dst_range'][1])}", str(t["outside"])])
        h.append(R.grid(["Transfer", "Points", "How", "From", "To", "Outside"], trs))
        h.append(R.subhead("Checks"))
        crow = [[("<b style='color:%s'>PASS</b>" if c["ok"] else "<b style='color:%s'>FAIL</b>") % (R.GREEN if c["ok"] else R.RED), c["name"] + (" (stops the result)" if c["hard"] and not c["ok"] else ""), c["detail"]] for c in res["checks"]]
        kn = res.get("known")
        if kn is not None:
            crow.append([("<b style='color:%s'>PASS</b>" if kn["ok"] else "<b style='color:%s'>FAIL</b>") % (R.GREEN if kn["ok"] else R.RED), "Known answer: " + kn["name"],
                         (f"{kn['got']:.5g} {kn['unit']} found, {kn['expected']:.5g} {kn['unit']} expected (within {tol_text(kn)})" + (f"; {kn['note']}" if kn.get("note") else "") if kn["got"] is not None else kn.get("note", "not computed"))])
        h.append(R.grid(["", "Check", "What it found"], crow))
        for p in res["passes"]:
            h.append(R.note(p["note"]))
        h.append(R.note("The pictures are in the Viz tab." if res["dim"] == 2 else "The pictures are in the windows of the analyses (their Results pages): they hold this solve. Viz of 3D results comes with the 3D fluid flow work."))
        if self.check_result is not None:
            h.append(self.self_check_html(self.check_result))
        return "".join(h)

    def fluid_html(self, res):
        """The part of the result that belongs to the fluid: the flow, the heat exchange with the solid and what the loop did."""
        f = res["fluid"]
        h = [R.subhead("Fluid analysis")]
        flow = f"{f.get('status', '?')}" + (f", {f['steps']} steps" if f.get("steps") else "")
        rows = [("Flow", flow, None)]
        if "iterations" in f:
            rows += [("Inlet temperature", R.temp_text(f["T_in"]), None), ("Wall temperature", f"{R.temp_text(f['Tw_min'])} .. {R.temp_text(f['Tw_max'])}", None),
                     ("Heat exchange", f"{f['iterations']} iterations, heat flux agreement {100 * f['mismatch']:.2g} %", None),
                     ("Heat leaving the solid", R.num(f["Q_solid"], 5), "W"), ("Heat entering the fluid", R.num(f["Q_fluid"], 5), "W"),
                     ("Fluid energy balance", f"{100 * f['balance'].get('relative', 0.0):.2g} %", None)]
        rows.append(("Time", f"{f['seconds']:.3g}", "s"))
        h.append(R.kv(rows))
        for n in f.get("notes", []):
            h.append(R.note(n, R.AMBER))
        fs = res.get("fsi")
        if fs:
            h.append(R.subhead("The structure moves the flow"))
            h.append(R.kv([("Passes", f"{fs['iterations']} ({'converged' if fs['converged'] else 'NOT converged'}, limit {100 * fs['tol']:g} %)", None),
                           ("Largest displacement", R.num(fs["umax"]), res.get("structural", {}).get("L", "")), ("Size of the body", R.num(fs["size"]), res.get("structural", {}).get("L", ""))]))
            h.append(R.grid(["Pass", "Largest displacement", "Change from the pass before", "Relaxation", "Elements"],
                            [[str(x["it"]), R.num(x["umax"]), f"{100 * x['change']:.3g} %" if x["it"] > 1 else "-", f"{x['omega']:g}", f"{mesh_count(x['mesh']):,}" if x.get("mesh") else "-"]
                             for x in fs["history"][:30]]))
            h.append(R.note("The body in the fluid window is the body as the stress analysis moved it in the last pass. The stress analysis is linear: it works with small displacements and the load of "
                            "the moved flow is put on the walls as drawn."))
        hist = f.get("history") or []
        if len(hist) > 1:
            h.append(R.grid(["Iteration", "Heat flux mismatch", "Largest change of the wall temperature (K)"], [[str(x["it"]), f"{100 * x['mismatch']:.3g} %", f"{x['dT']:.3g}"] for x in hist[:12]]))
        return h

    # ------------------------------------------------------------------------------------------------------------------------------ the self-check
    def run_self_check(self):
        if self.running:
            return False
        self.running = True
        self.enable_buttons()
        try:
            self.check_result = coupled_check.run(self.progress)
        except Exception:                                                            # noqa: BLE001
            tb = traceback.format_exc()
            self.running = False
            return self.fail("The self-check could not run: " + tb.strip().splitlines()[-1], tb)
        finally:
            self.running = False
        r = self.check_result
        self.say(("Self-check: every problem passed" if r["ok"] else "Self-check: a problem FAILED") + f" ({len(r['rows'])} problems, {r['seconds']:.2g} s).")
        self.log("note", self.say_text(r))
        self.enable_buttons()
        self.show_report()
        return r["ok"]

    @staticmethod
    def say_text(r):
        return "self-check " + ("PASS" if r["ok"] else "FAIL") + ": " + "; ".join(f"{'PASS' if x['ok'] else 'FAIL'} {x['name']}" for x in r["rows"] if not x["ok"])

    def self_check_html(self, r):
        rows = [[("<b style='color:%s'>PASS</b>" if x["ok"] else "<b style='color:%s'>FAIL</b>") % (R.GREEN if x["ok"] else R.RED), x["name"], x["expected"], x["got"]] for x in r["rows"]]
        return R.heading("Self-check", "stand-in analyses with known answers") + (R.chip("PASS", "ok") if r["ok"] else R.chip("FAIL", "bad")) + R.grid(["", "Problem", "Expected", "Found"], rows)

    # ------------------------------------------------------------------------------------------------------------------------------ diagnostics
    def diagnostics_text(self):
        diag = optional("solid_diag")
        L = diag.program_lines("Coupled Physics diagnostics report") if diag is not None else ["Coupled Physics diagnostics report", time.strftime("%Y-%m-%d %H:%M:%S")]
        sec = (lambda t, ls: diag.section(t, ls)) if diag is not None else (lambda t, ls: ["", f"== {t} =="] + list(ls))
        src = getattr(self, "src", None) or {}
        L += sec("Members", [f"{r}: {src.get('labels', {}).get(r) or 'not wired in'}" for r in ("fluid", "thermal", "structural")] +
                 ([f"problem: {src['problem']}"] if src.get("problem") else []) + ([f"note: {src['note']}"] if src.get("note") else []))
        L += sec("Options", [f"{k}: {v}" for k, v in sorted(self.options.items())])
        res = self.result
        if res is None:
            L += sec("Last solve", ["No solve has run in this window." if not self.last_error else "The last solve did not run: " + self.last_error.strip().splitlines()[-1]])
        else:
            lines = [f"dimension: {res['dim']}D, {res['seconds']:.4g} s in the loop ({res.get('wall_seconds', 0):.4g} s with the windows)"]
            if "thermal" in res:
                lines.append(f"heat: {res['thermal']['T_min']:.6g} .. {res['thermal']['T_max']:.6g} K (average {res['thermal']['T_mean']:.6g} K), {res['thermal']['seconds']:.4g} s")
            if "structural" in res:
                lines.append(f"stress: {res['structural']['seconds']:.4g} s" + ("" if "umax" not in res["structural"] else
                             f", largest displacement {res['structural']['umax']:.6g} {res['structural']['L']}, largest von Mises {res['structural']['vm_max']:.6g} {res['structural']['S']}"))
            fl = res.get("fluid")
            if fl:
                lines.append(f"fluid: flow {fl.get('status')}, {fl.get('steps')} steps, {fl.get('triangles', fl.get('cells', '?'))} {'cells' if 'cells' in fl else 'triangles'}, {fl['seconds']:.4g} s")
                if "iterations" in fl:
                    lines.append(f"heat exchange: {fl['iterations']} iterations, flux mismatch {fl['mismatch']:.3e}, inlet {fl['T_in']:.6g} K, wall {fl['Tw_min']:.6g} .. {fl['Tw_max']:.6g} K, "
                                 f"Q solid {fl['Q_solid']:.6g} W, Q fluid {fl['Q_fluid']:.6g} W, fluid balance {fl['balance'].get('relative', 0.0):.3e}, Prandtl {fl.get('Pr', float('nan')):.4g}")
                    lines += [f"  iteration {x['it']}: mismatch {x['mismatch']:.3e}, wall change {x['dT']:.3e} K, relaxation {x['omega']:g}" for x in fl.get("history", [])[:30]]
                lines += [f"fluid note: {n}" for n in fl.get("notes", [])]
            fs = res.get("fsi")
            if fs:
                lines.append(f"structure moves the flow: {fs['iterations']} passes, {'converged' if fs['converged'] else 'NOT converged'} (limit {100 * fs['tol']:g} %), largest displacement {fs['umax']:.6g}, "
                             f"size of the body {fs['size']:.6g}, outline gap {fs['gap']:.3g} element sizes")
                lines += [f"  pass {x['it']}: largest displacement {x['umax']:.6g}, change {100 * x['change']:.4g} %, relaxation {x['omega']:g}" +
                          (f", {mesh_count(x['mesh'])} elements" + (f", smallest angle {x['mesh']['angle_min']:.1f} deg" if "angle_min" in x["mesh"] else f", smallest volume ratio {x['mesh'].get('shrink', 1.0):.3f}") if x.get("mesh") else "") for x in fs["history"][:30]]
            for t in res["transfers"]:
                if "src_text" in t:
                    lines.append(f"transfer {t['name']}: {t['what']}, {t['points']} {t.get('unit', 'wall points')}, gap {t['max_gap']:.3g}: {t['src_text']} -> {t['dst_text']}")
                    continue
                lines.append(f"transfer {t['name']}: {t['points']} points, {t['outside']} outside (gap {t['max_gap']:.3g}), {'direct' if t['direct'] else 'interpolated'}, "
                             f"{t['src_range'][0]:.6g}..{t['src_range'][1]:.6g} K to {t['dst_range'][0]:.6g}..{t['dst_range'][1]:.6g} K")
            L += sec("Last solve", lines)
            kn = res.get("known")
            L += sec("Checks", [f"{'PASS' if c['ok'] else 'FAIL'}{' (hard)' if c['hard'] else ''} {c['name']}: {c['detail']}" for c in res["checks"]] +
                     ([f"{'PASS' if kn['ok'] else 'FAIL'} Known answer, {kn['name']}: expected {kn['expected']:.6g} {kn['unit']}, found {'-' if kn['got'] is None else format(kn['got'], '.6g')} (within {tol_text(kn)})"] if kn else []))
        win_lines = [f"strip: {', '.join(self.strip.roles())}; shown: {self.role}", "marks: " + ", ".join(f"{r} {m}" for r, m in self.strip.marks().items())]
        for role, h in sorted(self.hosted.items()):
            win_lines.append(f"{role}: ‘{src.get('labels', {}).get(role) or '?'}’ is shown in this window (its own window is kept hidden inside; Outline {'there' if h.outline is not None else 'missing'})")
        loose = [r for r in ("fluid", "thermal", "structural") if src.get("labels", {}).get(r) and r not in self.hosted]
        win_lines.append("not shown in this window (3D analyses keep their own tabs): " + (", ".join(loose) if loose else "none"))
        win_lines.append(f"handed-over rows: {len(getattr(self, 'handover', None) or [])}")
        L += sec("The window", win_lines)
        try:
            vz = self.viz.self_check()
            vl = [self.viz.message() or "A picture of the last solve is built."] + [f"{'PASS' if x['ok'] else 'FAIL'} {x['name']}: expected {x['expected']}; found {x['got']}" for x in vz]
        except Exception as ex:                                                                  # noqa: BLE001
            vl = [f"The Viz checks could not run: {ex}"]
        L += sec("Viz", vl)
        if self.check_result is not None:
            L += sec("Self-check", [f"{'PASS' if x['ok'] else 'FAIL'} {x['name']}: expected {x['expected']}; found {x['got']}" for x in self.check_result["rows"]])
        # what the two analyses said last (their own reports hold more)
        wins = src.get("windows") if isinstance(src.get("windows"), dict) else {}
        for role, kinds in (("fluid", ("cfd", "fluid3d")), ("heat", ("thermal", "thermal3d")), ("stress", ("fea", "solid"))):
            w = next((wins[k] for k in kinds if k in wins), None)
            ev = getattr(w, "events", None)
            if ev and diag is not None:
                L += sec(f"The {role} analysis said", diag.events_lines(ev, 40))
        L += sec("This window said", diag.events_lines(self.events) if diag is not None else [f"{level}: {text}" for _t, level, text in self.events] or ["Nothing was said."])
        return "\n".join(L)

    def show_diagnostics(self):
        text = self.diagnostics_text()
        diag = optional("solid_diag")
        folder = self.path if self.project_ok() else None
        if diag is not None and hasattr(diag, "show_report"):
            diag.show_report(self, text, folder, "Coupled Physics diagnostics report")
        else:
            QMessageBox.information(self, "Diagnostics report", text[:4000])
        return text

    # ------------------------------------------------------------------------------------------------------------------------------ hooks of the program window
    def units_changed(self):
        self.show_report()

    def heat_changed(self):
        self.show_report()

    def shutdown(self):
        self.cancel_flag = True
        try:
            self.ticker.stop()
            self.viz.stop()
        except (AttributeError, RuntimeError):
            pass
        for h in list(self.hosted.values()):                                         # (the analyses shown here go with the window: their workers and timers stop)
            try:
                if hasattr(h.win, "shutdown"):
                    h.win.shutdown()
            except Exception:                                                        # noqa: BLE001
                pass


def make_coupled(host, path=None):
    coupled_ext.ensure_registered()
    if path:
        return CoupledWindow.open_project(host, path)
    return CoupledWindow(shell=host)


coupled_ext.ensure_registered()
