"""wb_trainer.py - the Trainer block of the workbench.

    A Annotator  --Dataset--->  B Trainer  --Models--->  (a Trained models block, a Model testing block)
                 --Distances->

The Trainer's two import cells take what the wired Annotator has (ONE Annotator for each Trainer).  Refresh copies it into the Trainer's own training project, in the block's
workspace: the same zip the annotator shares (every annotated picture, its boxes and its distances) is made from the annotator's folder and merged in with the code the Trainer
window uses, so a picture that is already there is not copied again and the newest edit wins.  Pictures are never stored in the project file: they are taken again from the
Annotator's folder (a link) when the project is opened and the cell says refresh.

Update Project never trains.  The Training cell is a "data" cell: it is ready once a model was trained, and training starts only when the person presses Start training in the Trainer
window.

What the project file keeps of a Trainer (node.data):
    settings   the settings of the training project (model type, size, epochs, distortions, the Python to train with ...)
    models     every model trained: {"file", "key", "bytes", "stored": "inside" | "linked", "info", "blob" | "link"}.
               A model up to MODEL_LIMIT (500 MB) is kept INSIDE the file, so one project file is one training; a bigger one is LINKED (it is written next to the project, and the
               person is told).  Importing a model from a file works the same way (see store_model_file).
Never kept: the pictures, the distorted copies, the frozen copies of runs.
"""
import json
import os
import shutil
import tempfile

import wb_models
import wb_nodes as nodes
import wb_parts
import wb_project as wp

KEYS = wb_models.KEYS                            # the model folders of a training project (the annotator's Models layout)
mb = wb_models.mb


def trainer_core():
    """The Trainer add-on's own module, or None when the add-on is not there."""
    try:
        import trainer_core as tc
        return tc
    except Exception:                                        # noqa: BLE001
        return None


class TrainerAdapter(nodes.Adapter):
    kind = "trainer"
    first_cell = "training"
    tab_kind = "trainer"
    addon = "Trainer"

    # ------------------------------------------------------------------ is it possible
    def available(self, tab):
        try:
            import addons
            ok = self.tab_kind in addons.tab_kinds()
        except Exception:                                    # noqa: BLE001
            ok = False
        if not ok:
            return False, f"This tool needs the add-on '{self.addon}', which is not installed or is switched off (Add-ons)."
        tc = trainer_core()
        if tc is None or not os.path.isdir(tc.ANNOTATOR_APP):
            return False, "The Trainer uses the Annotator add-on's code for its dataset merge and model files: install the Annotator add-on first (Add-ons)."
        import importlib.util
        need = [p for p, m in (("pillow", "PIL"), ("numpy", "numpy")) if importlib.util.find_spec(m) is None]
        if need:
            return False, "The Trainer needs these packages first: " + ", ".join(need) + " (pip install them, then open the block again)."
        return True, ""

    # ------------------------------------------------------------------ the training project in the workspace
    def folder(self, tab, node):
        return os.path.join(nodes.workspace_of(tab, node), "Trainer.training")

    def state(self, tab, node):
        return tab.node_state.setdefault(node.id, {})

    def wired_annotator(self, tab, node):
        """The Annotator block wired into the Dataset cell (or into Distances), or None."""
        prj = tab.project
        for key in ("dataset", "distances"):
            for k in prj.incoming_all(node.id, key):
                n = prj.nodes.get(k.a)
                if n is not None and n.kind == "annotator":
                    return n
        return None

    def build(self, tab, node):
        """Writes the training project of the block into the workspace when it is not there yet: its settings and the models kept in the block (no pictures).  -> its folder."""
        tc = trainer_core()
        folder = self.folder(tab, node)
        st = self.state(tab, node)
        if st.get("built") and os.path.isfile(os.path.join(folder, tc.MARKER)):
            return folder
        shutil.rmtree(folder, ignore_errors=True)            # (what a project that was open before in this workbench left under the same name is not this block's)
        tp = tc.TrainingProject(folder)
        saved = dict(node.data.get("settings") or {})
        if saved.get("python") and not os.path.exists(saved["python"]):
            saved.pop("python")                              # the Python of another computer
        if saved:
            tp.set_settings(saved)
        for m in node.data.get("models") or []:
            self.put_model(tab, node, tp.models_dir, m)
        st["built"], st["fp"], st["settings"] = True, self.fingerprint(tp.models_dir), self.settings_text(tp.meta)
        return folder

    @staticmethod
    def settings_text(meta):
        return json.dumps(meta.get("settings") or {}, sort_keys=True)

    @staticmethod
    def fingerprint(models_dir):
        """Names and sizes of the model files of a training project."""
        out = []
        for key in KEYS:
            d = os.path.join(models_dir, {"assist": "Assist", "scratch": "Scratch"}[key])
            if os.path.isdir(d):
                for fn in sorted(os.listdir(d)):
                    if fn.lower().endswith(".pt"):
                        try:
                            out.append(f"{key}/{fn}/{os.path.getsize(os.path.join(d, fn))}")
                        except OSError:
                            pass
        return "|".join(out)

    # ------------------------------------------------------------------ models: kept inside, or linked
    def store_model_file(self, tab, node, pt, key, info=None):
        """Takes a model file into the block: INSIDE the project up to wb_models.MODEL_LIMIT, else LINKED (see wb_models.store_file).  -> the entry, or None when the block has it."""
        return wb_models.store_file(tab, node, pt, key, info)

    def put_model(self, tab, node, models_dir, m):
        """A model of the block as files in the training project: the .pt and its .json.  A linked model whose file is gone is left out (and said)."""
        tc = trainer_core()
        sub = os.path.join(models_dir, {"assist": "Assist", "scratch": "Scratch"}.get(m.get("key"), "Assist"))
        os.makedirs(sub, exist_ok=True)
        pt = os.path.join(sub, wp.safe_name(m["file"]))
        if m.get("stored") == "linked":
            src = wp.resolve_link(m.get("link") or {}, tab.path)
            if src is None:
                tab.note(f"{node.label} {node.title}: the linked model {m['file']} is not where it was ({(m.get('link') or {}).get('abs', '?')}), so it is not in the Trainer.")
                return None
            if not os.path.exists(pt):
                shutil.copyfile(src, pt)
        else:
            if not isinstance(m.get("blob"), dict):
                return None
            wp.unpack_file(m["blob"], sub, os.path.basename(pt))
        if isinstance(m.get("info"), dict) and m["info"]:
            with open(tc.libs()[3].info_path(pt), "w", encoding="utf-8") as f:
                json.dump(m["info"], f, indent=2)
        self.state(tab, node).setdefault("placed", set()).add((m["file"], m.get("key")))
        return pt

    def read_back(self, tab, node, folder):
        """Brings the models of the workspace training project into the block (new ones are stored, ones that are gone are dropped).  -> True when something changed."""
        tc = trainer_core()
        ml = tc.libs()[3]
        models_dir = os.path.join(folder, "models")
        seen, changed = set(), False
        for key in KEYS:
            for v in ml.list_versions(models_dir, key):
                seen.add((v["file"], key))
                got = self.store_model_file(tab, node, v["path"], key)
                changed = changed or got is not None
        placed = self.state(tab, node).setdefault("placed", set())          # the models that were in the training project at some time: one of them that is gone was removed there
        placed |= seen
        keep = [m for m in node.data.get("models", []) if (m["file"], m.get("key")) in seen or (m["file"], m.get("key")) not in placed]
        if len(keep) != len(node.data.get("models", [])):
            node.data["models"], changed = keep, True
        return changed

    # ------------------------------------------------------------------ the node and its window
    def open_cell(self, tab, node, key):
        w = tab.editor_of(node.id)
        h = tab.host
        if w is not None:
            if h is not None and hasattr(h, "tabs"):
                h.tabs.setCurrentWidget(w)
            return w
        if h is None or not hasattr(h, "new_addon_tab"):
            tab.say(f"'{node.title}' opens in the program window; there is none here.")
            return None
        tab.sync_editors()
        folder = self.build(tab, node)
        note = ""
        an = self.wired_annotator(tab, node)
        if an is not None:
            err = self.take(tab, node, only_if_stale=True)
            if err:
                note = f" The Annotator's dataset could not be taken: {err}"
        w = h.new_addon_tab(self.tab_kind, folder)
        if w is None:
            return None
        tab.adopt_editor(node, w)
        info = {"label": node.label, "title": node.title, "annotator": f"{an.label} {an.title}" if an is not None else "",
                "take": lambda: self.take_now(tab, node), "changed": lambda: self.changed_in_window(tab)}
        if hasattr(w, "set_workbench_block"):
            w.set_workbench_block(info)
        else:
            w.workbench_block = info
        self.look(tab, node, folder)
        tab.say(f"{node.label} {node.title}: work in its tab. " + (f"Its dataset comes from {an.label} {an.title}." if an is not None else
                "Wire an Annotator's Dataset into it to train on that, or import a dataset zip in its window.") + note)
        return w

    def look(self, tab, node, folder):
        """Reads the settings and the models of the training project; the cells Setup and Training are ready when there is something in them.  -> the keys of the cells that changed."""
        tc = trainer_core()
        st = self.state(tab, node)
        w = tab.editor_of(node.id)
        meta = getattr(getattr(w, "tp", None), "meta", None)
        if meta is None:
            try:
                with open(os.path.join(folder, tc.MARKER), encoding="utf-8") as f:
                    meta = json.load(f)
            except (OSError, ValueError):
                return []
        keys = []
        text = self.settings_text(meta)
        if text != st.get("settings"):
            st["settings"] = text
            node.data["settings"] = json.loads(text)
            keys.append("setup")
        env = getattr(w, "env", None)
        py = (meta.get("settings") or {}).get("python")
        tab.project.set_ready(node.id, "setup", bool(py) and not (env and env.get("problems")))
        fp = self.fingerprint(os.path.join(folder, "models"))
        if fp != st.get("fp"):
            st["fp"] = fp
            self.read_back(tab, node, folder)
            keys.append("training")
        tab.project.set_ready(node.id, "training", bool(node.data.get("models")))
        return keys

    def sync(self, tab, node):
        tc = trainer_core()
        folder = self.folder(tab, node)
        if tc is None or not tab.node_state.get(node.id, {}).get("built") or not os.path.isfile(os.path.join(folder, tc.MARKER)):
            return None                                       # (never opened: what the block keeps is what it was)
        return self.look(tab, node, folder) or None

    # ------------------------------------------------------------------ Refresh: the dataset of the wired Annotator
    def refresh(self, tab, node, key):
        if key in ("dataset", "distances"):
            return self.take(tab, node)
        return None

    def take(self, tab, node, only_if_stale=False):
        """Copies the dataset (pictures, boxes, distances) of the wired Annotator into the training project.  -> None when done, else the text of what went wrong."""
        tc = trainer_core()
        an = self.wired_annotator(tab, node)
        if an is None:
            return None
        tab.sync_editors()
        ad = nodes.adapter_for("annotator")
        src = ad.dataset_folder(tab, an)
        if src is None:
            return f"The Annotator '{an.title}' has no saved project folder yet: open it and save the project into a folder (File > Save)."
        st = self.state(tab, node)
        folder = self.build(tab, node)
        mark = ad.source_mark(tab, an)
        w = tab.editor_of(node.id)
        tp = w.tp if w is not None and hasattr(w, "tp") else tc.TrainingProject(folder)
        have = bool(tp.data.manifest["images"])
        if st.get("taken") == mark and have:
            return None
        if only_if_stale and st.get("taken") == mark:
            return None
        ac, dz, _sz, _ml = tc.libs()
        me = tc.default_me()
        tmp = tempfile.mkdtemp(prefix="wb_dataset_")
        try:
            zp = os.path.join(tmp, "dataset.zip")

            def tick(label):
                last = [0]

                def cb(n, total):
                    if n - last[0] >= 25 or n == total:
                        last[0] = n
                        tab.say(f"{node.label} {node.title}: {label} {n} / {total} pictures ...")
                        from PyQt6.QtWidgets import QApplication
                        QApplication.processEvents()
                return cb
            project = ac.Project(src)
            res = dz.export_zip(project, zp, me, tick("reading"))
            ad.rebaseline(tab, an)                            # (reading the dataset rewrote its manifest: that is not a change of the dataset)
            if not res["count"]:
                return f"The Annotator '{an.title}' has no annotated pictures yet."
            plan = tp.plan_import(zp, me, tick("comparing"))
            tp.apply_import(plan, None, me, tick("taking"))
            if w is not None and hasattr(w, "refresh_all"):
                w.refresh_all()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        st["taken"] = ad.source_mark(tab, an)
        return None

    def take_now(self, tab, node):
        """Take from Annotator in the window: the dataset is taken again whatever the cells say.  -> None or what went wrong."""
        st = self.state(tab, node)
        st.pop("taken", None)
        err = self.take(tab, node)
        if not err:
            for key in ("dataset", "distances"):
                if tab.project.incoming_all(node.id, key):
                    tab.project.mark_refreshed(node.id, key)
            tab.scene.refresh()
        return err

    def changed_in_window(self, tab):
        """A model was made, imported or removed in the window: the project reads it back now (the cells say so at once)."""
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
        """The training project on its own: a .training folder with the settings and the models (and the pictures when they have been taken); runs and caches are left out."""
        tab.sync_editors()
        src = self.build(tab, node)
        p = wb_parts.unique_path(folder, nodes.safe_stem(node.title), ".training")
        os.makedirs(folder, exist_ok=True)
        shutil.copytree(src, p, ignore=shutil.ignore_patterns("runs", "weights_cache"))
        return p


nodes.register(TrainerAdapter())
