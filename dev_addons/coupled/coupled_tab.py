"""coupled_tab.py - the Coupled Physics window: one heat analysis and one stress analysis of the SAME geometry (both 2D or both 3D), solved together.  The heat problem is solved
first, its temperature field is handed to the stress problem (every node of the stress mesh takes the temperature at its place in the heat mesh; the two analyses keep their own
meshes), and the stress problem is solved with that temperature as a load of its own.  The window shows the members, the link between them, one Solve button, the combined
result with the checks of the hand-over, a self-check and a diagnostics report.

The window does not hold the analyses: the Workbench block gives it their windows (members_source) and it drives them through coupled_members.  A window opened without a
Workbench block says so.  The project folder (.gpx) holds the options only (state.sim)."""
import json
import os
import time
import traceback

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QApplication, QDoubleSpinBox, QHBoxLayout, QLabel, QMessageBox, QPushButton, QSplitter, QTextBrowser, QVBoxLayout, QWidget)

import coupled_check
import coupled_engine as ce
import coupled_ext
import coupled_members as cm
import sim_project
import sim_report as R
import sim_ui

KIND = coupled_ext.KIND
LABEL = coupled_ext.LABEL
DEFAULT_OPTIONS = {"tmean_tol_pct": 2.0}
EXTRA_OPTIONS = ("known",)                # {"name", "expected", "unit", "tol_pct", "axis"}: a known answer of the problem (the example project sets it): the growth of the far end of a 3D body, in mm
EVENT_LIMIT = 300


def optional(name):
    """A module of another add-on (solid_diag ...) or None when that add-on is not there."""
    try:
        import importlib
        return importlib.import_module(name)
    except ImportError:
        return None


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
        self.saved_sig = None
        self.build()
        self.saved_sig = self.signature()
        self.refresh()

    # ------------------------------------------------------------------------------------------------------------------------------ the window
    def build(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Orientation.Horizontal)
        lay.addWidget(split)
        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(4, 4, 4, 4)
        cl.setSpacing(4)

        s1 = sim_ui.Section("coupled", 1, "Physics", True)
        self.members_lbl = sim_ui.wrapped("")
        self.members_lbl.setTextFormat(Qt.TextFormat.RichText)
        s1.body.addWidget(self.members_lbl)
        row = QHBoxLayout()
        self.b_heat = QPushButton("Open the heat analysis")
        self.b_stress = QPushButton("Open the stress analysis")
        self.b_heat.clicked.connect(lambda: self.show_member("thermal"))
        self.b_stress.clicked.connect(lambda: self.show_member("structural"))
        row.addWidget(self.b_heat)
        row.addWidget(self.b_stress)
        s1.body.addLayout(row)
        cl.addWidget(s1)

        s2 = sim_ui.Section("coupled", 2, "Coupling", True)
        self.link_lbl = sim_ui.wrapped("")
        self.link_lbl.setTextFormat(Qt.TextFormat.RichText)
        s2.body.addWidget(self.link_lbl)
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
        cl.addWidget(s2)

        s3 = sim_ui.Section("coupled", 3, "Results", True)
        self.b_solve = sim_ui.solve_button("Solve")
        self.b_cancel = sim_ui.solve_side_button("Cancel")
        self.b_solve.clicked.connect(lambda *_: self.solve())
        self.b_cancel.clicked.connect(lambda *_: self.cancel())
        s3.body.addWidget(sim_ui.solve_row(self.b_solve, self.b_cancel))
        self.status_lbl = sim_ui.wrapped("")
        s3.body.addWidget(self.status_lbl)
        brow = QHBoxLayout()
        self.b_check = QPushButton("Self-check")
        self.b_check.setToolTip("Solves problems with known answers on stand-in analyses and prints PASS or FAIL beside the numbers; it also checks that the checks can fail.")
        self.b_diag = QPushButton("Diagnostics report")
        self.b_diag.setToolTip("What this window and its two analyses did, with times, checks and every error: also saved as diagnostics.txt in the project folder. Send it when something goes wrong.")
        self.b_check.clicked.connect(lambda *_: self.run_self_check())
        self.b_diag.clicked.connect(lambda *_: self.show_diagnostics())
        brow.addWidget(self.b_check)
        brow.addWidget(self.b_diag)
        s3.body.addLayout(brow)
        cl.addWidget(s3)
        cl.addStretch(1)
        self.sections = [s1, s2, s3]
        panel = sim_ui.make_panel(content, [])
        self.view = QTextBrowser()
        self.view.setOpenLinks(False)
        split.addWidget(panel)
        split.addWidget(self.view)
        split.setStretchFactor(1, 1)
        sim_ui.fit_side_panel(split, panel, content)
        sim_ui.solve_shortcut(self, self.b_solve)

    # ------------------------------------------------------------------------------------------------------------------------------ the project
    def title(self):
        return os.path.basename(self.path.rstrip("/\\")) if self.path else LABEL

    def signature(self):
        return json.dumps(self.options, sort_keys=True)

    def is_dirty(self):
        return self.signature() != self.saved_sig

    def project_ok(self):
        return bool(self.path) and sim_project.kind_of_folder(self.path) == KIND

    def create_project(self, path):
        sim_project.create(path, KIND)
        self.path = path
        self.save()
        return True

    def save(self, as_new=False):
        if not self.project_ok():
            self.say("A Coupled Physics window is saved with its Workbench project: there is no project folder to save into here.")
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
                w.e_tol.setValue(float(w.options["tmean_tol_pct"]))
            except (OSError, ValueError, TypeError):
                pass
        w.saved_sig = w.signature()
        w.refresh()
        return w

    def options_changed(self, *_):
        self.options["tmean_tol_pct"] = float(self.e_tol.value())

    # ------------------------------------------------------------------------------------------------------------------------------ what it says
    def say(self, text):
        self.status_lbl.setText(text)
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
        """The members, the link and the buttons (what can be said before a solve)."""
        try:
            src = self.members()
        except Exception as ex:                                                      # noqa: BLE001
            src = {"windows": {}, "labels": {}, "show": {}, "problem": None, "note": f"The analyses could not be read: {ex}"}
        self.src = src
        labels = src.get("labels", {})
        lines = []
        for role, name in (("thermal", "Heat"), ("structural", "Stress")):
            lines.append(f"<b>{name}</b>: " + (labels.get(role) or "<span style='color:%s'>not wired in yet</span>" % R.GREY))
        if src.get("problem"):
            lines.append(R.note(src["problem"], R.AMBER))
        elif src.get("note"):
            lines.append(R.note(src["note"]))
        self.members_lbl.setText("<br>".join(lines))
        have = bool(labels.get("thermal")) and bool(labels.get("structural"))
        self.b_heat.setEnabled(bool(src.get("show", {}).get("thermal")))
        self.b_stress.setEnabled(bool(src.get("show", {}).get("structural")))
        rows = [("Temperature", "Heat → Stress", "every node of the stress mesh", "the temperature field of the heat analysis (linked: its values are not typed)")]
        t = "".join(f"<tr><td><b>{a}</b></td><td>{b}</td><td>{c}</td></tr>" for a, b, c, _d in rows)
        self.link_lbl.setText("<table cellspacing='0' cellpadding='3'>" + t + "</table>" + R.note(
            "One way: the stress does not change the temperature, so the heat problem is solved once and its field is given to the stress problem. The thermal expansion "
            "coefficient and the reference temperature are the ones of the material in the stress analysis (Material and analysis)."))
        self.enable_buttons(have)
        self.show_report()

    def enable_buttons(self, have=None):
        if have is None:
            labels = getattr(self, "src", {}).get("labels", {})
            have = bool(labels.get("thermal")) and bool(labels.get("structural"))
        self.b_solve.setEnabled(have and not self.running)
        self.b_cancel.setEnabled(self.running)
        self.b_check.setEnabled(not self.running)

    def show_member(self, role):
        f = getattr(self, "src", {}).get("show", {}).get(role)
        if f is not None:
            f()

    # ------------------------------------------------------------------------------------------------------------------------------ solving
    def cancel(self):
        if self.running:
            self.cancel_flag = True
            self.say("Cancelling...")

    def progress(self, text, frac):
        self.status_lbl.setText(f"{text}...")
        QApplication.processEvents()

    def fail(self, text, error=None):
        self.last_error = error or text
        self.log("error", self.last_error)
        self.result = None
        self.say(text)
        self.show_report()
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
        self.enable_buttons()
        t0 = time.monotonic()
        try:
            res = ce.solve_coupled(mem, {"tmean_tol": float(self.options["tmean_tol_pct"]) / 100.0}, progress=self.progress, cancel=lambda: self.cancel_flag)
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
        try:
            res["structural"].update(mem["structural"].summary())
        except Exception as ex:                                                      # noqa: BLE001
            self.log("error", f"The result of the stress analysis could not be summarised: {ex}")
        failed = [c["name"] for c in res["checks"] if not c["ok"]]
        self.say(("Solved" if res["ok"] else "Solved, but a check failed") + f" in {res['seconds']:.2g} s" + (f": {', '.join(failed)}." if failed else "."))
        self.log("note", f"solved ({res['dim']}D) in {res['seconds']:.3g} s; checks failed: {failed or 'none'}")
        self.enable_buttons()
        self.show_report()
        return True

    def known_answer(self, mem):
        """The known answer of the problem (options["known"]) against what the stress analysis gave: {"name", "expected", "got", "unit", "tol_pct", "ok"} or None."""
        kn = self.options.get("known")
        if not kn:
            return None
        row = {"name": kn.get("name", "Known answer"), "expected": float(kn["expected"]), "unit": kn.get("unit", "mm"), "tol_pct": float(kn.get("tol_pct", 2.0)), "got": None, "ok": False}
        st = mem["structural"]
        try:
            if not hasattr(st, "far_end"):
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
                "the material with its thermal expansion coefficient; no mechanical load is needed), then press Solve.")
            if self.last_error:
                msg += R.note(self.last_error.strip().splitlines()[-1], R.RED)
            if self.check_result is not None:                                    # the self-check needs no solve: show its rows even before the first one
                msg += self.self_check_html(self.check_result)
            return msg
        h = []
        h.append(R.heading("Coupled solve", f"{res['dim']}D, one way: heat → stress") + (R.chip("PASS", "ok") if res["ok"] and all(c["ok"] for c in res["checks"]) else R.chip("CHECK FAILED" if res["ok"] else "REFUSED", "bad")))
        th, st = res["thermal"], res["structural"]
        h.append(R.subhead("Heat analysis"))
        h.append(R.kv([("Lowest temperature", R.temp_text(th["T_min"]), None), ("Highest temperature", R.temp_text(th["T_max"]), None), ("Average temperature", R.temp_text(th["T_mean"]), None),
                       ("Time", f"{th['seconds']:.3g}", "s")]))
        h.append(R.subhead("Stress analysis"))
        rows = []
        if "umax" in st:
            rows += [("Largest displacement", R.num(st["umax"]), st["L"]), ("Largest von Mises stress", R.num(st["vm_max"]), st["S"])]
        rows.append(("Time", f"{st['seconds']:.3g}", "s"))
        h.append(R.kv(rows))
        h.append(R.subhead("What was handed over"))
        trs = []
        for t in res["transfers"]:
            trs.append([t["name"], f"{t['points']:,} nodes", "direct copy" if t["direct"] else "interpolated", f"{R.temp_text(t['src_range'][0])} .. {R.temp_text(t['src_range'][1])}",
                        f"{R.temp_text(t['dst_range'][0])} .. {R.temp_text(t['dst_range'][1])}", str(t["outside"])])
        h.append(R.grid(["Transfer", "Points", "How", "Heat mesh range", "Stress mesh range", "Outside"], trs))
        h.append(R.subhead("Checks"))
        crow = [[("<b style='color:%s'>PASS</b>" if c["ok"] else "<b style='color:%s'>FAIL</b>") % (R.GREEN if c["ok"] else R.RED), c["name"] + (" (stops the result)" if c["hard"] and not c["ok"] else ""), c["detail"]] for c in res["checks"]]
        kn = res.get("known")
        if kn is not None:
            crow.append([("<b style='color:%s'>PASS</b>" if kn["ok"] else "<b style='color:%s'>FAIL</b>") % (R.GREEN if kn["ok"] else R.RED), "Known answer: " + kn["name"],
                         (f"{kn['got']:.5g} {kn['unit']} found, {kn['expected']:.5g} {kn['unit']} expected (within {kn['tol_pct']:g} %)" if kn["got"] is not None else kn.get("note", "not computed"))])
        h.append(R.grid(["", "Check", "What it found"], crow))
        for p in res["passes"]:
            h.append(R.note(p["note"]))
        h.append(R.note("The temperature and the stress pictures are in the windows of the two analyses (their Results pages): they hold this solve."))
        if self.check_result is not None:
            h.append(self.self_check_html(self.check_result))
        return "".join(h)

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
        L += sec("Members", [f"{r}: {src.get('labels', {}).get(r) or 'not wired in'}" for r in ("thermal", "structural")] +
                 ([f"problem: {src['problem']}"] if src.get("problem") else []) + ([f"note: {src['note']}"] if src.get("note") else []))
        L += sec("Options", [f"{k}: {v}" for k, v in sorted(self.options.items())])
        res = self.result
        if res is None:
            L += sec("Last solve", ["No solve has run in this window." if not self.last_error else "The last solve did not run: " + self.last_error.strip().splitlines()[-1]])
        else:
            lines = [f"dimension: {res['dim']}D, one way (heat to stress), {res['seconds']:.4g} s in the loop ({res.get('wall_seconds', 0):.4g} s with the windows)",
                     f"heat: {res['thermal']['T_min']:.6g} .. {res['thermal']['T_max']:.6g} K (average {res['thermal']['T_mean']:.6g} K), {res['thermal']['seconds']:.4g} s",
                     f"stress: {res['structural']['seconds']:.4g} s" + ("" if "umax" not in res["structural"] else f", largest displacement {res['structural']['umax']:.6g} {res['structural']['L']}, largest von Mises {res['structural']['vm_max']:.6g} {res['structural']['S']}")]
            for t in res["transfers"]:
                lines.append(f"transfer {t['name']}: {t['points']} points, {t['outside']} outside (gap {t['max_gap']:.3g}), {'direct' if t['direct'] else 'interpolated'}, "
                             f"{t['src_range'][0]:.6g}..{t['src_range'][1]:.6g} K to {t['dst_range'][0]:.6g}..{t['dst_range'][1]:.6g} K")
            L += sec("Last solve", lines)
            kn = res.get("known")
            L += sec("Checks", [f"{'PASS' if c['ok'] else 'FAIL'}{' (hard)' if c['hard'] else ''} {c['name']}: {c['detail']}" for c in res["checks"]] +
                     ([f"{'PASS' if kn['ok'] else 'FAIL'} Known answer, {kn['name']}: expected {kn['expected']:.6g} {kn['unit']}, found {'-' if kn['got'] is None else format(kn['got'], '.6g')} (within {kn['tol_pct']:g} %)"] if kn else []))
        if self.check_result is not None:
            L += sec("Self-check", [f"{'PASS' if x['ok'] else 'FAIL'} {x['name']}: expected {x['expected']}; found {x['got']}" for x in self.check_result["rows"]])
        # what the two analyses said last (their own reports hold more)
        wins = src.get("windows") if isinstance(src.get("windows"), dict) else {}
        for role, kinds in (("heat", ("thermal", "thermal3d")), ("stress", ("fea", "solid"))):
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


def make_coupled(host, path=None):
    coupled_ext.ensure_registered()
    if path:
        return CoupledWindow.open_project(host, path)
    return CoupledWindow(shell=host)


coupled_ext.ensure_registered()
