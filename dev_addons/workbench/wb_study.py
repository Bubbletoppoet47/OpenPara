"""wb_study.py - the Parametric Study block of the workbench.

A study runs analyses again and again with other values of their inputs (the Parametric Studies add-on).  In the workbench a study block takes ANY NUMBER of wires into its
Parameters cell:  the Setup of an analysis (its inputs, and the outputs that are recorded) and the Part cell of a Part (its dimensions; a change of a dimension flows through every
analysis that works on that Part).  It needs at least one analysis.  wb_multi.py has the details.

The cells:   Parameters (import)  the inputs and outputs of everything wired in; Refresh reads them again.  It says "refresh" when a wired block changed.
             Study (compute)      Update runs every design point of the table (the window asks first when there are many) and waits for the end.
             Results (view)       opens the study window.
Where the study is kept: in the block (the folder study/: the table of design points, the outputs of every case, the studies of the picker), WITHOUT the full result of each case
(study/cases/), which Update works out again.  The analyses are opened behind the study window (it runs them).
"""
import hashlib
import json
import os
import shutil
import time

import wb_nodes as nodes
import wb_project as wp

WAIT_LIMIT = 4 * 3600.0                                       # seconds an Update waits for a study to finish
NEEDS = "Wire the Setup cell of an analysis into Parameters first: a study runs the analyses wired into it again and again."


def pack(folder):
    """{relative path: stored file} of the study folder without the full result of each case."""
    return wp.pack_folder(folder, skip=lambda rel: rel.endswith(".tmp") or rel.endswith(".new") or (rel.startswith("study/") and "/cases/" in rel))


def walk_study(folder):
    sd = os.path.join(folder, "study")
    for root, dirs, fs in os.walk(sd):
        dirs.sort()
        for fn in sorted(fs):
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, sd).replace(os.sep, "/")
            if "cases/" in rel or rel.endswith(".tmp"):
                continue
            yield full, fn, rel


def files_digest(folder):
    """A fingerprint of everything the block keeps of the study (the definition AND what a run recorded; not the full result of each case)."""
    h = hashlib.sha1()
    for full, _fn, rel in walk_study(folder):
        try:
            with open(full, "rb") as f:
                raw = f.read()
        except OSError:
            raw = b""
        h.update(rel.encode() + b"\0" + raw + b"\1")
    return h.hexdigest()


def definition_digest(folder):
    """A fingerprint of what the person set up in a study (the inputs that vary, the design points, the outputs, the early-exit conditions, the list of studies), NOT of what a run
    recorded (the cases, run_meta) or of what the window remembers (the last fill): a run must not make its own study say 'update'."""
    h = hashlib.sha1()
    for full, fn, rel in walk_study(folder):
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

    # ---- the folder in the workspace
    def state(self, tab, node):
        return tab.node_state.setdefault(node.id, {})

    def folder_of(self, tab, node):
        return os.path.join(nodes.workspace_of(tab, node), nodes.safe_stem(node.title) + ".study")

    def materialize(self, tab, node):
        """Writes the block's study folder to the workspace (an empty one when it has none yet); -> the folder."""
        st = self.state(tab, node)
        f = self.folder_of(tab, node)
        shutil.rmtree(f, ignore_errors=True)
        files = node.data.get("files")
        if files:
            wp.unpack_folder(files, f)
        else:
            os.makedirs(f, exist_ok=True)
        st["folder"] = f
        return f

    def remember(self, tab, node):
        """Notes the study as it is now: what is set up from here on that differs makes the Study cell say update."""
        st = self.state(tab, node)
        folder = st.get("folder")
        if folder and os.path.isdir(folder):
            st["def"] = definition_digest(folder)

    # ---- opening
    def wired(self, tab, node):
        return tab.project.has_wire_of(tab.project.incoming_all(node.id, "setup"), ("analysis",))

    def open_study(self, tab, node, front=True):
        """The study window of the block (made when it is not open; it opens the analyses wired in behind it).  -> the widget, or None (the reason is said)."""
        w = tab.editor_of(node.id)
        h = tab.host
        if w is not None:
            if front and h is not None and hasattr(h, "tabs"):
                h.tabs.setCurrentWidget(w)
            return w
        if not self.wired(tab, node):
            tab.say(NEEDS)
            return None
        import study_tab
        import wb_multi
        front_w = h.tabs.currentWidget() if h is not None and hasattr(h, "tabs") else None
        tab.sync_editors()
        f = self.materialize(tab, node)
        host = wb_multi.StudyHost(tab, node, f)
        try:
            w = study_tab.StudyTab(host, threaded=True)
        except Exception as ex:                                   # noqa: BLE001
            tab.say(f"The study could not be opened: {type(ex).__name__}: {ex}")
            return None
        if not os.path.isfile(os.path.join(f, "study", "study.json")):
            w.save()
        w.host_ = host
        tab.show_editor(node, w)
        self.state(tab, node)["base"] = files_digest(f)
        self.remember(tab, node)
        if not front and front_w is not None and h is not None and hasattr(h, "tabs"):
            h.tabs.setCurrentWidget(front_w)
        elif front and h is not None and hasattr(h, "tabs"):
            h.tabs.setCurrentWidget(w)
        return w

    def open_cell(self, tab, node, key):
        return self.open_study(tab, node)

    # ---- reading back
    def sync(self, tab, node):
        """What was done in the study window is saved into the study folder, and the block takes it."""
        w = tab.editor_of(node.id)
        if w is None:
            return None
        try:
            if w.is_dirty():
                w.save()
        except Exception as ex:                                   # noqa: BLE001
            tab.say(f"'{node.title}' could not be saved into the project: {ex}")
            return None
        st = self.state(tab, node)
        folder = st.get("folder")
        if not folder or not os.path.isdir(folder):
            return None
        d = files_digest(folder)
        if d != st.get("base"):
            node.data["files"] = pack(folder)
            st["base"] = d
            tab.project.changed()                                 # (the file needs saving; whether a cell changed is told below)
        dd = definition_digest(folder)
        old = st.get("def")
        st["def"] = dd
        if old is not None and dd != old:
            return "setup"                                        # the study was set up differently: what it recorded is out of date
        return None

    def refresh(self, tab, node, key):
        """Parameters: the window reads the inputs and outputs of everything wired in again."""
        if key != "setup":
            return None
        if not tab.project.incoming_all(node.id, "setup"):
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
                return "The study did not start (it asked first, and was not confirmed, or an analysis is not ready)."
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
        try:
            self.sync(tab, node)
        except Exception:                                         # noqa: BLE001
            pass
        if h is not None and hasattr(h, "tabs"):
            i = h.tabs.indexOf(w)
            if i >= 0:
                h.close_tab(i)
        tab.editors.pop(node.id, None)

    def closed(self, tab, node):
        self.close_editor(tab, node)
        tab.node_state.pop(node.id, None)


nodes.register(StudyAdapter())
