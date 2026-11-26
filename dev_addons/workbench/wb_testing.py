"""wb_testing.py - the Model testing block of the workbench: the Annotator's Analyse tab (open a recorded session of the Gimble rig, run a model over it, see how its distance holds up
against the LiDAR frame by frame) as a block of its own.

    B Trainer / C Trained models  --Models-->  D Model testing

Cells:
    Models     import   the models of the blocks wired into it (any number; none is fine); the models dropped or imported on the block itself are its own (node.data["models"], inside the
                        project file up to 500 MB each, linked above that).  Nothing is copied from a wired block.  Refresh only says the list was looked at again.
    Test data  data     a LINK to a recorded session folder (frames and depth are far too big for a project file)
    Setup      data     the confidence, the tolerance, the way the LiDAR is read, the model shown
    Analysis   data     ready while an analysis has been run in the window.  NOT a compute cell: Update Project never runs a model, the person presses Run analysis.
    Results    view

Results are not saved in the project (the cells say so after the file is opened: Analysis is not ready until it is run again); the CSV and the report are what is kept.

What the project file keeps of the block (node.data):  models (entries, see wb_models), session {"abs", "rel"}, settings {"conf", "tol", "method", "region", "dots", "model"}.
"""
import os
import shutil

import wb_models
import wb_nodes as nodes
import wb_project as wp


class ModelTestingAdapter(nodes.Adapter):
    kind = "model_test"
    first_cell = "data"

    # ------------------------------------------------------------------ is it possible
    def available(self, tab):
        ml, tc = wb_models.libs()
        if tc is None or ml is None or not os.path.isdir(tc.ANNOTATOR_APP):
            return False, "Model testing uses the analysis code and the model files of the Annotator and Trainer add-ons: install both first (Add-ons)."
        try:
            import annotator_analyse  # noqa: F401
        except Exception as e:                               # noqa: BLE001
            return False, f"Model testing uses the Annotator add-on's analysis, which could not be loaded ({e}). It needs numpy and pillow."
        return True, ""

    def state(self, tab, node):
        st = tab.node_state.setdefault(node.id, {})
        if st.get("project") != id(tab.project):             # (the state of a block of an earlier project with the same id is not this block's)
            st.clear()
            st["project"] = id(tab.project)
        return st

    # ------------------------------------------------------------------ what the cells say
    def look(self, tab, node):
        """Reads the window (when it is open) into the block: the settings, the session, the runs.  -> the keys of the cells that changed."""
        st = self.state(tab, node)
        w = tab.editor_of(node.id)
        keys = []
        prj = tab.project
        if w is not None and hasattr(w, "analyse"):
            settings = w.settings_now()
            if settings != node.data.get("settings"):
                node.data["settings"] = settings
                keys.append("setup")
            link = w.session_link()
            if link != node.data.get("session"):
                node.data["session"] = link
                keys.append("data")
            if w.runs != st.get("runs", 0):
                st["runs"] = w.runs
                keys.append("analysis")
            an = w.analyse.analysis
            prj.set_ready(node.id, "analysis", bool(an is not None and an.analysed > 0))
        else:
            prj.set_ready(node.id, "analysis", False)         # (results are not saved: after a file is opened the analysis is to be run again)
        link = node.data.get("session")
        prj.set_ready(node.id, "data", bool(link and wp.resolve_link(link, tab.path)))
        prj.set_ready(node.id, "setup", True)                  # (the settings have a default for everything)
        return keys

    def created(self, tab, node):
        self.look(tab, node)

    def sync(self, tab, node):
        return self.look(tab, node) or None

    def relink(self, tab, node):
        self.look(tab, node)

    def refresh(self, tab, node, key):
        """Nothing is copied from a wired block: the list follows the wires.  An open window reads it again."""
        if key == "models":
            w = tab.editor_of(node.id)
            if w is not None and hasattr(w, "reload_models"):
                w.reload_models()
        return None

    # ------------------------------------------------------------------ the window
    def open_cell(self, tab, node, key):
        w = tab.editor_of(node.id)
        h = tab.host
        if w is not None:
            if h is not None and hasattr(h, "tabs"):
                h.tabs.setCurrentWidget(w)
            return w
        if h is None or not hasattr(h, "add_tab"):
            tab.say(f"'{node.title}' opens in the program window; there is none here.")
            return None
        import wb_testing_tab
        w = wb_testing_tab.TestingWindow(tab, node, self)
        tab.show_editor(node, w)
        n = len(wb_models.models_of(tab, node.id))
        tab.say(f"{node.label} {node.title}: work in its tab. " + (f"It has {n} model{'s' if n != 1 else ''}. " if n else "It has no model yet: wire a Trainer or a Trained models block into it, or drop model files on it. ")
                + ("Its test session is open." if w.analyse.session is not None else "Open a recorded session (Test > Open session) to run them on."))
        return w

    def changed_in_window(self, tab):
        """Something was run, or a model imported, in the window: the project reads it back now (the cells say so at once)."""
        tab.sync_editors()
        tab.scene.refresh()

    # ------------------------------------------------------------------ the rest of the protocol
    def closed(self, tab, node):
        w = tab.editor_of(node.id)
        h = tab.host
        if w is not None and h is not None and hasattr(h, "tabs"):
            i = h.tabs.indexOf(w)
            if i >= 0:
                h.close_tab(i)
        tab.node_state.pop(node.id, None)
        shutil.rmtree(os.path.join(tab.workspace, node.id), ignore_errors=True)


nodes.register(ModelTestingAdapter())
