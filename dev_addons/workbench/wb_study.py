"""wb_study.py - the Parametric Study block of the workbench.

A study runs an analysis again and again with other values of its inputs (the Parametric Studies add-on: study/ in the analysis's project folder).  In the workbench a study
block is wired to ONE analysis: the wire comes from the analysis's Setup cell into the study's Parameters cell.  Double-click opens the study window of that analysis (the analysis's
own tab is opened behind it when it is not open: the study works on it).

The cells:   Parameters (import)  the inputs and outputs of the wired analysis; Refresh reads them again.  It says "refresh" when the Setup of the analysis changed.
             Study (compute)      Update runs every design point of the table (the window asks first when there are many) and waits for the end.
             Results (view)       opens the study window.
Where the study is kept: in the project folder of the analysis, as everywhere else in the program (study/study.json, the table of design points and the outputs of every case).  The
analysis block takes it into the project file with the rest of its folder - WITHOUT the full result of each case (study/cases/), which Update works out again.  So removing the
study block does not delete the study (wire a new block to the analysis to see it again), and a study made in the analysis's own tab is saved too.
"""
import hashlib
import json
import os
import time

import wb_nodes as nodes

WAIT_LIMIT = 4 * 3600.0                                       # seconds an Update waits for a study to finish


def analysis_of(tab, node):
    """(analysis node, its adapter), or the text that says what is missing."""
    k = tab.project.incoming(node.id, "setup")
    if k is None:
        return "Wire the Setup cell of an analysis into Parameters first: a study runs one analysis again and again."
    src = tab.project.node(k.a)
    a = nodes.adapter_for(src.kind)
    if a is None or not hasattr(a, "open_editor"):
        return f"'{src.title}' cannot be opened here."
    return src, a


def definition_digest(folder):
    """A fingerprint of what the person set up in a study (the inputs that vary, the design points, the outputs, the early-exit conditions, the list of studies), NOT of what a run
    recorded (the cases, run_meta) or of what the window remembers (the last fill): a run must not make its own study say 'update'."""
    h = hashlib.sha1()
    sd = os.path.join(folder, "study")
    for root, dirs, fs in os.walk(sd):
        dirs.sort()
        for fn in sorted(fs):
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, sd).replace(os.sep, "/")
            if "cases/" in rel or rel.endswith(".tmp"):
                continue
            try:
                with open(full, "rb") as f:
                    raw = f.read()
                if fn == "study.json":
                    j = json.loads(raw.decode("utf-8"))
                    for k in ("cases", "run_meta", "fill"):
                        j.pop(k, None)
                    raw = json.dumps(j, sort_keys=True).encode("utf-8")
            except (OSError, ValueError):
                raw = b""
            h.update(rel.encode() + b"\0" + raw + b"\1")
    return h.hexdigest()


class StudyAdapter(nodes.Adapter):
    kind = "study"
    needs = "parametric"
    first_cell = "setup"

    def available(self, tab):
        try:
            import ext
            if not ext.hooks("sim_study"):
                return False, "This block needs the add-on 'Parametric Studies', which is not installed or is switched off (Add-ons)."
        except Exception:                                         # noqa: BLE001
            return False, "This block needs the add-on 'Parametric Studies', which is not installed or is switched off (Add-ons)."
        return True, ""

    def remember(self, tab, node):
        """Notes the study as it is now: what is set up from here on that differs makes the Study cell say update."""
        got = analysis_of(tab, node)
        if isinstance(got, str):
            return
        src = got[0]
        folder = tab.node_state.get(src.id, {}).get("folder")
        if folder:
            tab.node_state.setdefault(node.id, {})["def"] = definition_digest(folder)

    # ---- opening
    def open_study(self, tab, node, front=True):
        """The study window of the wired analysis (made when it is not open).  -> the widget, or None (the reason is said)."""
        w = tab.editor_of(node.id)
        h = tab.host
        if w is not None:
            if front and h is not None and hasattr(h, "tabs"):
                h.tabs.setCurrentWidget(w)
            return w
        got = analysis_of(tab, node)
        if isinstance(got, str):
            tab.say(got)
            return None
        src, a = got
        front_w = h.tabs.currentWidget() if h is not None and hasattr(h, "tabs") else None
        sim = tab.editor_of(src.id)
        if sim is None:
            sim = a.open_editor(tab, src, front=False)
        if sim is None:
            return None
        if not callable(getattr(sim, "open_study", None)):
            tab.say(f"'{src.title}' has no parametric study.")
            return None
        w = sim.open_study()                                      # saves the analysis when it changed, and makes or shows its study tab
        if w is None:
            return None
        tab.adopt_editor(node, w)
        self.remember(tab, node)
        if not front and front_w is not None and h is not None:
            h.tabs.setCurrentWidget(front_w)
        return w

    def open_cell(self, tab, node, key):
        return self.open_study(tab, node)

    # ---- reading back
    def sync(self, tab, node):
        """What was done in the study window is saved into the analysis's folder, and the analysis block takes it."""
        w = tab.editor_of(node.id)
        if w is None:
            return None
        try:
            if w.is_dirty():
                w.save()
        except Exception as ex:                                   # noqa: BLE001
            tab.say(f"'{node.title}' could not be saved into the project: {ex}")
            return None
        got = analysis_of(tab, node)
        if isinstance(got, str):
            return None
        src, a = got
        if hasattr(a, "take_study"):
            a.take_study(tab, src)
        folder = tab.node_state.get(src.id, {}).get("folder")
        st = tab.node_state.setdefault(node.id, {})
        if folder:
            d = definition_digest(folder)
            old = st.get("def")
            st["def"] = d
            if old is not None and d != old:
                return "setup"                                     # the study was set up differently: what it recorded is out of date
        return None

    def refresh(self, tab, node, key):
        """Parameters: the window reads the inputs and outputs of the analysis again."""
        if key != "setup":
            return None
        if tab.project.incoming(node.id, "setup") is None:
            return "There is no wire into this cell: nothing to refresh from."
        w = tab.editor_of(node.id)
        if w is not None:
            try:
                w.refresh_params()
            except Exception as ex:                               # noqa: BLE001
                return f"{type(ex).__name__}: {ex}"
        return None

    def update(self, tab, node, key):
        """Study: every design point of the table is run, here, and Update waits for the end."""
        if key != "solution":
            return None
        from PyQt6.QtWidgets import QApplication
        w = self.open_study(tab, node, front=False)
        if w is None:
            return "The study could not be opened (see the message above)."
        try:
            w.refresh_params()
            why = w.adapter.ready()
            if why:
                return why
            if not w.data.rows:
                return "The table of design points is empty: add rows in the study first."
            if w.run_all() is False and not w.running():
                return "The study did not start (it asked first, and was not confirmed, or the analysis is not ready)."
            t0 = time.monotonic()
            while w.running():
                QApplication.processEvents()
                time.sleep(0.01)
                if time.monotonic() - t0 > WAIT_LIMIT:
                    return "the study did not finish in time"
            QApplication.processEvents()
            if w.is_dirty():
                w.save()
        except Exception as ex:                                   # noqa: BLE001
            return f"{type(ex).__name__}: {ex}"
        self.remember(tab, node)                                  # (a run is not a change of the set-up)
        self.sync(tab, node)
        return None

    # ---- closing
    def close_editor(self, tab, node):
        w = tab.editor_of(node.id)
        h = tab.host
        if w is None:
            return
        try:
            if w.is_dirty():
                w.save()
        except Exception:                                         # noqa: BLE001
            pass
        if h is not None and hasattr(h, "tabs"):
            i = h.tabs.indexOf(w)
            if i >= 0:
                h.close_tab(i)
        tab.editors.pop(node.id, None)

    def closed(self, tab, node):
        self.close_editor(tab, node)


nodes.register(StudyAdapter())
