"""wb_tools.py - the tools that work on ONE document: Sheets (.opsheet), Controls (.opctl), Circuits (.opcirc) and the Truss Generator (.truss), as blocks of the workbench.

A block keeps the document as it would be saved on its own: node.data["file"] holds the bytes of the file (as text when they are text); the Truss Generator's document is a
FOLDER (project.json and the sketch), so node.data["files"] holds the files in it.  Double-click: the document is written to the project's workspace and opened in the tool's usual
tab (a new, empty one is made and saved there first); what is done in the tab is read back (when the project is saved, when the Workbench is shown again, before Update Project).
Saved on its own, the block is the ordinary file (or folder), which opens in the program like any other.  The cell is ready once the document has something in it (it was changed
in the tab).
"""
import hashlib
import os
import shutil

import wb_nodes as nodes
import wb_parts
import wb_project as wp

# (block kind, tab kind of the add-on, extension, add-on, the document is a folder)
TOOLS = (("sheets", "sheets", ".opsheet", "Sheets", False), ("drawing", "drawing", ".opdraw", "Drawings", False), ("controls", "controls", ".opctl", "Systems and Controls", False), ("circuits", "circuits", ".opcirc", "Circuits", False),
         ("truss", "truss", ".truss", "Truss Generator", True))


def digest(path):
    """A fingerprint of a file, or of everything in a folder (names and bytes)."""
    h = hashlib.sha1()
    if os.path.isdir(path):
        for root, dirs, files in os.walk(path):
            dirs.sort()
            for fn in sorted(files):
                full = os.path.join(root, fn)
                h.update(os.path.relpath(full, path).replace(os.sep, "/").encode("utf-8") + b"\0")
                with open(full, "rb") as f:
                    h.update(f.read())
                h.update(b"\1")
    else:
        with open(path, "rb") as f:
            h.update(f.read())
    return h.hexdigest()


class FileToolAdapter(nodes.Adapter):
    first_cell = "document"

    def __init__(self, kind, tab_kind, ext, addon, folder=False):
        self.kind, self.tab_kind, self.ext, self.addon, self.folder = kind, tab_kind, ext, addon, folder
        self.slot = "files" if folder else "file"                # where the document is in node.data

    def available(self, tab):
        try:
            import addons
            ok = self.tab_kind in addons.tab_kinds()
        except Exception:                                        # noqa: BLE001
            ok = False
        return (True, "") if ok else (False, f"This tool needs the add-on '{self.addon}', which is not installed or is switched off (Add-ons).")

    def state(self, tab, node):
        return tab.node_state.setdefault(node.id, {})

    def file_of(self, tab, node):
        return os.path.join(nodes.workspace_of(tab, node), nodes.safe_stem(node.title) + self.ext)

    def exists(self, path):
        return os.path.isdir(path) if self.folder else os.path.isfile(path)

    def remove(self, path):
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            elif os.path.exists(path):
                os.remove(path)
        except OSError:
            pass

    def write(self, node, f):
        """The block's document into the workspace as `f`."""
        if self.folder:
            wp.unpack_folder(node.data[self.slot], f)
        else:
            wp.unpack_file(node.data[self.slot], os.path.dirname(f), os.path.basename(f))

    def pack(self, f):
        return wp.pack_folder(f) if self.folder else wp.pack_file(f)

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
        st = self.state(tab, node)
        f = self.file_of(tab, node)
        old = st.get("file")
        if old and old != f:
            self.remove(old)
        if node.data.get(self.slot):
            self.remove(f)                                       # (nothing left over from before is mixed into the document)
            self.write(node, f)
            w = h.new_addon_tab(self.tab_kind, f)
        else:                                                    # a new document: the tool makes an empty one, which is saved in the workspace so that there is a file
            w = h.new_addon_tab(self.tab_kind, None)
            if w is not None:
                w.path = f
                w.save()
        if w is None:
            return None
        tab.adopt_editor(node, w)
        st["file"] = f
        st["base"] = digest(f) if self.exists(f) else ""
        tab.say(f"{node.label} {node.title}: work in its tab. The project takes the changes when you save it or come back here.")
        return w

    def sync(self, tab, node):
        st = tab.node_state.get(node.id)
        if not st or "base" not in st:
            return None
        w = tab.editor_of(node.id)
        f = st.get("file")
        if w is not None:
            try:
                if w.is_dirty():
                    w.save()
            except Exception as ex:                              # noqa: BLE001
                tab.say(f"'{node.title}' could not be saved into the project: {ex}")
        if not f or not self.exists(f):
            return None
        d = digest(f)
        if d == st["base"]:
            return None
        st["base"] = d
        node.data[self.slot] = self.pack(f)
        tab.project.set_ready(node.id, self.first_cell, True)
        return [self.first_cell]

    def closed(self, tab, node):
        w = tab.editor_of(node.id)
        h = tab.host
        if w is not None and h is not None and hasattr(h, "tabs"):
            try:
                if w.is_dirty():
                    w.save()
            except Exception:                                    # noqa: BLE001
                pass
            i = h.tabs.indexOf(w)
            if i >= 0:
                h.close_tab(i)
        tab.node_state.pop(node.id, None)

    def export(self, tab, node, folder):
        tab.sync_editors()
        if not node.data.get(self.slot):
            raise ValueError(f"'{node.title}' has nothing in it yet: open it and make something first.")
        p = wb_parts.unique_path(folder, nodes.safe_stem(node.title), self.ext)
        os.makedirs(folder, exist_ok=True)
        self.write(node, p)
        return p


class StudySource:
    """What a Sheets block may import: ONLY the Parametric Studies wired into its Study Results cell (a study is never imported from anywhere else in a block).  Each is a copy
    of the study as its block keeps it, in the workspace of the Sheets block (the study window may be open on its own folder, which is never touched)."""

    def __init__(self, tab, node):
        self.tab, self.node = tab, node
        self.cache = {}

    def reset(self):
        """The next copies are taken from the studies as their blocks keep them now (what was done in a study window is read back first)."""
        self.cache = {}
        self.tab.sync_editors()

    def blocks(self):
        prj = self.tab.project
        out = []
        for k in prj.incoming_all(self.node.id, "studies"):
            n = prj.nodes.get(k.a)
            if n is not None and n.kind == "study" and n not in out:
                out.append(n)
        return out

    def folder_of(self, study):
        return os.path.join(nodes.workspace_of(self.tab, self.node), "studies", f"{nodes.safe_stem(study.title)}-{study.id}.study")

    def take(self, study):
        """The study as its block keeps it, written into its folder.  -> the folder, or None when the block has nothing saved of it yet."""
        f = self.folder_of(study)
        shutil.rmtree(f, ignore_errors=True)
        files = study.data.get("files")
        if not files:
            return None
        wp.unpack_folder(files, f)
        return f

    def projects(self):
        """[(name, folder)] of the wired studies that have something saved: a fresh copy each time."""
        self.reset()
        out = []
        for st in self.blocks():
            f = self.take(st)
            if f:
                self.cache[st.id] = f
                out.append((st.title, f))
        return out

    def path_of(self, nid):
        """The folder of the wired study `nid` in this session, or None when that study is not wired into the block (any more)."""
        st = next((b for b in self.blocks() if b.id == nid), None)
        if st is None:
            return None
        if nid not in self.cache:
            f = self.take(st)
            if f is None:
                return None
            self.cache[nid] = f
        return self.cache[nid]

    def node_of(self, project):
        """The id of the study block a folder is the copy of, or None."""
        return next((b.id for b in self.blocks() if os.path.normpath(self.folder_of(b)) == os.path.normpath(str(project))), None)

    def name_of(self, project, sub, default):
        nid = self.node_of(project)
        st = self.tab.project.nodes.get(nid) if nid else None
        base = os.path.basename(str(project).rstrip("/\\"))
        return default.replace(base, st.title, 1) if st is not None and base and default.startswith(base) else default

    def nothing_to_import(self):
        bl = self.blocks()
        if not bl:
            return "No Parametric Study is wired into this block. In the Workbench, wire the Results cell of a study into the Study Results cell of this Sheets block."
        return "The wired study has nothing saved yet: open it (double-click its Results cell) and run it, or use Update Project; then import."


class SheetsAdapter(FileToolAdapter):
    """Sheets: the Study Results cell takes the studies wired into it; in the Sheets window only these can be imported, and Refresh of the cell reads the imported tables again."""

    def open_cell(self, tab, node, key):
        w = super().open_cell(tab, node, key)
        if w is not None and hasattr(w, "attach_study_source"):
            w.attach_study_source(StudySource(tab, node))
        return w

    def refresh(self, tab, node, key):
        if key != "studies":
            return None
        w = tab.editor_of(node.id)
        if w is not None and hasattr(w, "study_refresh_all"):
            if getattr(w, "study_source", None) is None:
                w.attach_study_source(StudySource(tab, node))
            done, notes = w.study_refresh_all()
        else:
            done, notes = self.refresh_file(tab, node, StudySource(tab, node))
        if notes:
            tab.note(f"{node.label} {node.title}: " + " ".join(notes))
        return None

    def refresh_file(self, tab, node, src):
        """The imported tables of a document that is not open are read again from the wired studies, and the document is saved back into the block."""
        if not node.data.get(self.slot):
            return 0, []
        try:
            import sh_book
            import sh_study
        except ImportError:
            return 0, ["The Sheets add-on is not available here: the imported tables were not read again."]
        f = os.path.join(nodes.workspace_of(tab, node), "refresh" + self.ext)
        self.write(node, f)
        try:
            wb = sh_book.Workbook.load(f)
            done, notes = sh_study.refresh_all(wb, lambda ln: src.path_of(ln["wb"]), lambda ln: bool(ln.get("wb")))
            if done:
                wb.save(f)
                node.data[self.slot] = self.pack(f)
                tab.project.touch(node.id, self.first_cell)
        finally:
            self.remove(f)
        return done, notes


class DrawingAdapter(FileToolAdapter):
    """Drawing: the Parts and Assemblies wired into the Models cell are the models of the drawing (a copy of each is kept in it); the Drawing window of the block does not add models
    by itself, and Refresh of the cell takes what changed in the wired blocks (the views are drawn again, in the open window and in a drawing that is closed)."""

    def model_items(self, tab, node):
        """[{"src": block id, "name", "kind", "data"}] of the wired Part and Assembly blocks that have content (the open editors are read back first)."""
        tab.sync_editors()
        prj = tab.project
        out = []
        for k in prj.incoming_all(node.id, "models"):
            n = prj.nodes.get(k.a)
            if n is None or n.kind not in ("part", "assembly") or any(it["src"] == n.id for it in out):
                continue
            data = n.data.get("doc" if n.kind == "part" else "asm")
            if data is not None:
                out.append({"src": n.id, "name": n.title, "kind": n.kind, "data": data})
        return out

    def open_cell(self, tab, node, key):
        w = super().open_cell(tab, node, key)
        if w is not None and hasattr(w, "sync_models"):
            w.models_from_wires = True
            out = w.sync_models(self.model_items(tab, node))
            note = self.say_of(out)
            if note:
                tab.note(f"{node.label} {node.title}: {note}")
            w.model_panel.refresh()
        return w

    @staticmethod
    def say_of(out):
        bits = [f"{k} {', '.join(out[k])}" for k in ("added", "refreshed", "removed") if out.get(k)]
        bits += [f"{n}: {why}" for n, why in out.get("failed", [])]
        return "; ".join(bits)

    def refresh(self, tab, node, key):
        if key != "models":
            return None
        items = self.model_items(tab, node)
        w = tab.editor_of(node.id)
        if w is not None and hasattr(w, "sync_models"):
            out = w.sync_models(items)
        else:
            out = self.refresh_file(tab, node, items)
        if out["failed"]:
            return "; ".join(f"{n}: {why}" for n, why in out["failed"])
        return None

    def refresh_file(self, tab, node, items):
        """The models of a drawing that is not open are brought up to date and the drawing is saved back into the block."""
        none = {"added": [], "refreshed": [], "removed": [], "failed": []}
        if not node.data.get(self.slot):
            return none                                          # never opened: the models are taken when it is
        import dr_model
        f = os.path.join(nodes.workspace_of(tab, node), "refresh" + self.ext)
        self.write(node, f)
        try:
            with open(f, encoding="utf-8") as fh:
                d = dr_model.Drawing.from_json(fh.read())
            out = d.sync_models(items)
            if out["added"] or out["refreshed"] or out["removed"]:
                with open(f, "w", encoding="utf-8") as fh:
                    fh.write(d.to_json())
                node.data[self.slot] = self.pack(f)
                tab.project.touch(node.id, self.first_cell)
        finally:
            self.remove(f)
        return out


for _k, _t, _e, _a, _f in TOOLS:
    nodes.register(SheetsAdapter(_k, _t, _e, _a, _f) if _k == "sheets" else DrawingAdapter(_k, _t, _e, _a, _f) if _k == "drawing" else FileToolAdapter(_k, _t, _e, _a, _f))
