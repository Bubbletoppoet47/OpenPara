"""lab_tab.py - the Constraint Lab tab (Playground, Full dev mode).

It is OpenPara's own assembly window (core/assembly.py, unchanged: the same view, picking, dragging, mate panel and file format) with two things added
on a "Constraint Lab" ribbon tab:

  Engine   which mate engine solves this assembly.  "Current" is core/asm_model.py, the one OpenPara uses.  "Experimental" is lab_engine.py, which
           started as a copy and lives only in this add-on (its header lists what it does differently), so a new solver can be built and tried on real
           parts here without touching anything else.  The window's assembly is
           moved onto the other engine's class when you switch (the poses stay as they are), and every new, opened or undone assembly follows the choice.
  Mate Matrix   scores an engine on every kind of pick against every kind of pick, for every mate type (lab_matrix.py), and shows where the engines differ.

Parts are inserted the usual way (Insert Components).  Ctrl+C / Ctrl+V duplicates a component."""
import os

from PyQt6.QtGui import QFontDatabase, QGuiApplication
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar, QPushButton,
                             QVBoxLayout)

import asm_model
import assembly
import lab_engine
import lab_highlight
import lab_matrix

ENGINES = {"Current": asm_model, "Experimental": lab_engine}      # name -> the module that has Assembly, face_ref, MateError ...


def apply_engine(a, name):
    """Move the assembly `a` onto the engine `name` (its poses, components and mates stay as they are); the engine's lab_adopt(), when it has one, sets up
    anything the class needs that the other engine's __init__ did not make."""
    cls = ENGINES[name].Assembly
    if type(a) is not cls:
        a.__class__ = cls
        getattr(a, "_cache", {}).clear()
        adopt = getattr(a, "lab_adopt", None)
        if adopt is not None:
            adopt()
    return a


class LabWindow(lab_highlight.FaceTint, assembly.AssemblyWindow):
    engine_name = "Current"

    def __init__(self, path=None, shell=None):
        super().__init__(path=path, shell=shell)
        self.matrix_win = None
        self.engine_label = QLabel()
        self.statusBar().addPermanentWidget(self.engine_label)
        self.ribbon.addTab(self.ribbon_page([
            ("tool_eng_cur", "●", "Current\nEngine", "Solve with the mate engine OpenPara uses (core/asm_model.py)", lambda: self.set_engine("Current")),
            ("tool_eng_exp", "◌", "Experimental\nEngine", "Solve with the lab's own copy of the engine (dev_addons/constraint_lab/lab_engine.py)",
             lambda: self.set_engine("Experimental")),
            "|",
            ("lab_tint", "◧", "Face\nRecolour", "On: a picked or hovered face is shown by recolouring its own triangles (nothing floats).  Off: the old lifted copy "
             "of the face.  Needs the baked outline drawing (Settings); the classic drawing always uses the old copy.", lambda: self.tint_toggle()),
            "|",
            ("lab_matrix", "▦", "Mate\nMatrix", "Score an engine on every pick type against every pick type for every mate, from several starting poses",
             lambda: self.matrix_open()),
        ]), "Constraint Lab")
        b = self.act["lab_tint"]
        b.setCheckable(True)
        b.setChecked(self.face_tint)
        b.setStyleSheet(b.styleSheet() + " QToolButton:checked{background:#cfe3fb; border:1px solid #6aa0e0;}")
        self.show_engine()
        self.say("Constraint Lab: insert parts and mate them as usual.  The engine and the Mate Matrix are on the Constraint Lab tab of the ribbon.")

    # ------------------------------------------------------------------ the engine
    def wire(self, a):
        super().wire(a)
        apply_engine(a, self.engine_name)

    def title(self):
        return os.path.basename(self.path) if self.path else "Constraint Lab"

    def set_engine(self, name):
        self.engine_name = name
        apply_engine(self.asm, name)
        self.show_engine()
        self.say(f"Engine: {name}.  New mates, drags and solves use it from now on; the poses stay where they are until you move a part or edit a mate.")

    def tint_toggle(self):
        on = self.act["lab_tint"].isChecked()
        self.set_face_tint(on)
        baked = assembly.settings.get("outline_mode") == "baked"
        self.say("Face highlight: " + ("recolours the face's own triangles." if on and baked else
                                       "recolour is on, but this view uses the classic outline drawing (Settings > Outline drawing = baked), so the old lifted copy is drawn." if on
                                       else "the old lifted copy of the face."))

    def show_engine(self):
        self.engine_label.setText(f"  Engine: {self.engine_name}  ")
        for key, name in (("tool_eng_cur", "Current"), ("tool_eng_exp", "Experimental")):
            b = self.act.get(key)
            if b is not None:
                b.setChecked(name == self.engine_name)

    def matrix_open(self):
        if self.matrix_win is None:
            self.matrix_win = MatrixDialog(self)
        self.matrix_win.show()
        self.matrix_win.raise_()


class MatrixDialog(QDialog):
    """Runs lab_matrix on one engine or both and shows the report."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Mate Matrix")
        self.resize(1040, 720)
        self.results, self.running, self.stop = {}, False, False
        lay = QVBoxLayout(self)
        info = QLabel("Tries every kind of pick against every kind of pick for every mate type, from several starting poses, on small built-in parts "
                      "(a plate with a hole, a block, a pin, two balls).  The first pick moves, the second sits on the fixed part.  Then it builds a few "
                      "assemblies with several mates (a pin in a hole, a block in a corner, a chain, a redundant mate, a conflict).")
        info.setWordWrap(True)
        lay.addWidget(info)
        top = QHBoxLayout()
        top.addWidget(QLabel("Engine"))
        self.which = QComboBox()
        self.which.addItems(list(ENGINES) + ["Compare both"])
        self.which.setCurrentIndex(len(ENGINES))
        top.addWidget(self.which)
        self.quick = QCheckBox("Quick (2 start poses, easy ones)")
        top.addWidget(self.quick)
        self.run_b = QPushButton("Run")
        self.run_b.clicked.connect(self.run)
        self.stop_b = QPushButton("Stop")
        self.stop_b.setEnabled(False)
        self.stop_b.clicked.connect(self.request_stop)
        top.addWidget(self.run_b)
        top.addWidget(self.stop_b)
        top.addStretch(1)
        lay.addLayout(top)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setFormat("")
        lay.addWidget(self.bar)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.text.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.text.setPlainText("Press Run.  One engine takes about 40 seconds (Quick: about 10); Compare both about twice that.")
        lay.addWidget(self.text, 1)
        bot = QHBoxLayout()
        cp = QPushButton("Copy report")
        cp.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.text.toPlainText()))
        sv = QPushButton("Save report...")
        sv.clicked.connect(self.save)
        cl = QPushButton("Close")
        cl.clicked.connect(self.close)
        bot.addWidget(cp)
        bot.addWidget(sv)
        bot.addStretch(1)
        bot.addWidget(cl)
        lay.addLayout(bot)

    def request_stop(self):
        self.stop = True

    def closeEvent(self, e):
        self.stop = True                                   # a run in progress ends at its next step
        super().closeEvent(e)

    def save(self):
        p, _ = QFileDialog.getSaveFileName(self, "Save the report", "mate_matrix.txt", "Text (*.txt)")
        if p:
            with open(p, "w", encoding="utf-8") as f:
                f.write(self.text.toPlainText())

    def run(self):
        if self.running:
            return
        names = list(ENGINES) if self.which.currentIndex() == len(ENGINES) else [self.which.currentText()]
        n_starts = 2 if self.quick.isChecked() else None
        self.running, self.stop = True, False
        self.run_b.setEnabled(False)
        self.stop_b.setEnabled(True)
        results = {}
        try:
            phases = 2 * len(names)                            # per engine: the pick pairs, then the scenarios with several mates
            for i, n in enumerate(names):
                def prog(done, total, ph=2 * i, n=n, what="pick pairs"):
                    self.bar.setValue(int(1000 * (ph + done / total) / phases))
                    self.bar.setFormat(f"{n}: {done} of {total} {what}")
                    QApplication.processEvents()
                    return self.stop
                results[n] = lab_matrix.run(ENGINES[n], n_starts=n_starts, progress=prog)
                if self.stop:
                    break
                results[n]["scen"] = lab_matrix.run_scenarios(ENGINES[n], n_starts=n_starts,
                                                              progress=lambda d, t, ph=2 * i + 1, n=n: prog(d, t, ph, n, "scenario runs"))
                if self.stop:
                    break
            self.results = results
            self.text.setPlainText(lab_matrix.report(results))
            self.bar.setValue(1000 if not self.stop else self.bar.value())
        except Exception:
            import traceback
            self.text.setPlainText("The matrix could not run:\n\n" + traceback.format_exc())
        finally:
            self.running = False
            self.run_b.setEnabled(True)
            self.stop_b.setEnabled(False)


def make_tab(host=None, path=None):
    p = path if path and path.lower().endswith(".gpa") else None
    return LabWindow(path=p, shell=host)
