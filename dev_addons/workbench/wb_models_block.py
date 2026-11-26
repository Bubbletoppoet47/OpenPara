"""wb_models_block.py - the Trained models block of the workbench.

    B Trainer  --Models--->  C Trained models  --Models--->  D Model testing

ONE list of every model: the ones trained in the Trainers wired into its From trainers cell (they stay in their Trainer: nothing is copied, the list follows the wires), the ones imported
into the block (kept INSIDE the project file up to 500 MB each, a bigger one is linked and the person is told) and the ones in the shared Models folder of the Annotator (what was
downloaded from GitHub; they are listed, never copied into a project).  The window (wb_models_tab) filters that list: all models, embedded models, GitHub models.

The block never trains and never reads a model file with torch: a model file can run code when it is loaded.  Its cells:
    From trainers import   takes any number of Trainers (none is fine); Refresh only says the list was looked at again
    Library       data     the list: ready when it has a model
    Models        view     the list as seen by a Model testing block that is wired to it
A change in the list (a model imported, renamed, removed; one added to or deleted from the shared folder; one made or removed in a wired Trainer) grows the stamp of Library, so a Model
testing block downstream says refresh.
"""
import os
import shutil

import wb_models
import wb_nodes as nodes
import wb_parts


class TrainedModelsAdapter(nodes.Adapter):
    kind = "trained_models"
    first_cell = "library"

    # ------------------------------------------------------------------ is it possible
    def available(self, tab):
        ml, tc = wb_models.libs()
        if tc is None or ml is None or not os.path.isdir(tc.ANNOTATOR_APP):
            return False, "Trained models uses the model files of the Annotator and Trainer add-ons: install both first (Add-ons)."
        try:
            import annotator_ribbon  # noqa: F401
        except Exception:                                    # noqa: BLE001
            return False, "Trained models uses the Annotator add-on's ribbon: install the Annotator add-on first (Add-ons)."
        return True, ""

    def state(self, tab, node):
        st = tab.node_state.setdefault(node.id, {})
        if st.get("project") != id(tab.project):             # (the state of a block of an earlier project with the same id is not this block's)
            st.clear()
            st["project"] = id(tab.project)
        return st

    # ------------------------------------------------------------------ the list and the cells
    def look(self, tab, node):
        """Reads the list of models again; Library is ready when there is a model.  -> the keys of the cells whose content changed (["library"] when the list is not what it was)."""
        st = self.state(tab, node)
        rows = wb_models.models_of(tab, node.id)
        fp = wb_models.fingerprint(rows)
        keys = ["library"] if st.get("fp") is not None and fp != st["fp"] else []
        st["fp"] = fp
        tab.project.set_ready(node.id, "library", bool(rows))
        return keys

    def created(self, tab, node):
        self.look(tab, node)

    def sync(self, tab, node):
        return self.look(tab, node) or None

    def relink(self, tab, node):
        self.look(tab, node)

    def refresh(self, tab, node, key):
        """Nothing is copied from a Trainer: the list follows the wires.  Refresh only takes the list as it is now."""
        if key == "trainers":
            self.look(tab, node)
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
        import wb_models_tab
        w = wb_models_tab.ModelsWindow(tab, node, self)
        tab.show_editor(node, w)
        tab.say(f"{node.label} {node.title}: the list of models is in its tab. Drop model files (.pt) on it to import them.")
        return w

    def changed_in_window(self, tab):
        """A model was imported, renamed or removed in the window: the project reads it back now (the cells say so at once)."""
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

    def export(self, tab, node, folder):
        """The models of the block (its own and those of the wired Trainers, not the shared ones) as files in a folder: every .pt with its .json beside it."""
        rows = [r for r in wb_models.models_of(tab, node.id) if r["origin"] != "shared"]
        p = wb_parts.unique_path(folder, nodes.safe_stem(node.title), "")
        os.makedirs(p, exist_ok=True)
        for r in rows:
            dest = os.path.join(p, r["file"])
            if os.path.exists(dest):                         # (two models with one file name, e.g. from two Trainers)
                dest = wb_parts.unique_path(p, os.path.splitext(r["file"])[0], ".pt")
            wb_models.export_entry(tab, r["node"], r["entry"], dest)
        return p


nodes.register(TrainedModelsAdapter())
