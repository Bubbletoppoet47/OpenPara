"""wb_tools.py - the tools that work on ONE document: Sheets (.opsheet), Controls (.opctl), Circuits (.opcirc) and the Truss Generator (.truss), as blocks of the workbench.

A block keeps the document as it would be saved on its own: node.data["file"] holds the bytes of the file (as text when they are text); the Truss Generator's document is a
FOLDER (project.json and the sketch), so node.data["files"] holds the files in it.  Double-click: the document is written to the project's workspace and opened in the tool's usual
tab (a new, empty one is made and saved there first); what is done in the tab is read back (when the project is saved, when the Workbench is shown again, before Update Project).
Saved on its own, the block is the ordinary file (or folder), which opens in the program like any other.  The cell is ready once the document has something in it (it was changed
in the tab).

Two blocks have no wires in or out yet: the PDF Editor and the Annotator.  The PDF Editor's document is a FOLDER of the PDFs and page projects that are open in its tab (a file opened
from anywhere else is copied into it, so the project never depends on a file somewhere else).  The Annotator's dataset is too big to be packed into a project file: the block keeps a
LINK to the project folder (a folder with manifest.json) that the annotator window works in; the window of a new block starts a project in a temporary folder, and the block takes the
folder once the project is saved.  dataset_folder() gives that folder: it is what a Trainer block will be wired to later.
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


def fingerprint(path):
    """A fast fingerprint of a file or folder: names, sizes and times only (the contents of PDFs are not read each time the project looks at the block)."""
    h = hashlib.sha1()
    if os.path.isdir(path):
        for root, dirs, files in os.walk(path):
            dirs.sort()
            for fn in sorted(files):
                full = os.path.join(root, fn)
                try:
                    st = os.stat(full)
                except OSError:
                    continue
                h.update(f"{os.path.relpath(full, path).replace(os.sep, '/')}\0{st.st_size}\0{st.st_mtime_ns}\1".encode("utf-8"))
    else:
        st = os.stat(path)
        h.update(f"{st.st_size}\0{st.st_mtime_ns}".encode("utf-8"))
    return h.hexdigest()


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
        w = self.make_editor(h, node, f)
        if w is None:
            return None
        tab.adopt_editor(node, w)
        st["file"] = f
        st["base"] = self.fingerprint(f) if self.exists(f) else ""
        tab.say(f"{node.label} {node.title}: work in its tab. The project takes the changes when you save it or come back here.")
        return w

    def make_editor(self, h, node, f):
        """The tool's tab on the block's document `f` (written into the workspace from the block, or a new one that is saved there first)."""
        if node.data.get(self.slot):
            self.remove(f)                                       # (nothing left over from before is mixed into the document)
            self.write(node, f)
            return h.new_addon_tab(self.tab_kind, f)
        w = h.new_addon_tab(self.tab_kind, None)                 # a new document: the tool makes an empty one, which is saved in the workspace so that there is a file
        if w is not None:
            w.path = f
            w.save()
        return w

    def fingerprint(self, path):
        return digest(path)

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
        d = self.fingerprint(f)
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
        if out.get("lost"):
            bits.append(f"{out['lost']} dimension{'s' if out['lost'] != 1 else ''} / mark{'s' if out['lost'] != 1 else ''} lost their geometry (open the drawing: they are red in its Outline)")
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
        if out.get("lost"):
            tab.note(f"{node.label} {node.title}: {self.say_of({'lost': out['lost']})}")
        if out["failed"]:
            return "; ".join(f"{n}: {why}" for n, why in out["failed"])
        return None

    def refresh_file(self, tab, node, items):
        """The models of a drawing that is not open are brought up to date and the drawing is saved back into the block."""
        none = {"added": [], "refreshed": [], "removed": [], "failed": [], "lost": 0}
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


class PdfEditorAdapter(FileToolAdapter):
    """PDF Editor (no wires): the document is a folder.  The tab opens on every PDF and page project in it; a PDF or project opened from anywhere else is copied into it (see
    PdfEditorTab.attach_block_folder), a new page project is made in it.  What changes (a saved highlight, a new file) is fingerprinted by names, sizes and times, so a big PDF is
    not read each time."""

    def __init__(self):
        super().__init__("pdf", "pdfeditor", "", "PDF editor", True)

    def fingerprint(self, path):
        return fingerprint(path)

    def make_editor(self, h, node, f):
        self.remove(f)
        if node.data.get(self.slot):
            self.write(node, f)
        os.makedirs(f, exist_ok=True)
        w = h.new_addon_tab(self.tab_kind, None)
        if w is not None and hasattr(w, "attach_block_folder"):
            w.attach_block_folder(f)
        return w


class AnnotatorAdapter(nodes.Adapter):
    """Annotator (no wires): the block keeps a LINK to the annotator project folder (a folder with its dataset inside; node.data["link"] = {"abs", "rel"}), never a copy: a dataset
    is photos and video frames, far too big for a project file.  A new block opens the annotator on a new project in a temporary folder, as the annotator does on its own; the
    first time the project is saved to its own folder (the annotator asks where) the block takes that folder.  The block follows the window: Save As, or a Dataset location chosen in
    the window, moves the link.  A change in the dataset (its manifest) is a change of the cell.  dataset_folder() is where a later Trainer block will get the dataset."""
    kind = "annotator"
    first_cell = "document"
    tab_kind = "annotator"
    addon = "General Classification Annotator"

    def available(self, tab):
        try:
            import addons
            ok = self.tab_kind in addons.tab_kinds()
        except Exception:                                        # noqa: BLE001
            ok = False
        if not ok:
            return False, f"This tool needs the add-on '{self.addon}', which is not installed or is switched off (Add-ons)."
        try:
            import annotator_tab
            need = annotator_tab.missing(required_only=True)
        except Exception:                                        # noqa: BLE001
            need = []
        if need:
            return False, "The annotator needs these packages first: " + ", ".join(p for _i, p, _w, _r in need) + " (pip install them, then open the block again)."
        return True, ""

    @staticmethod
    def is_project(folder):
        return bool(folder) and os.path.isfile(os.path.join(folder, "manifest.json"))

    def dataset_folder(self, tab, node):
        """The project folder the block links to, as it is now; None when the block has none yet or the folder is not where it was."""
        link = node.data.get("link")
        folder = wp.resolve_link(link, tab.path) if isinstance(link, dict) else None
        return folder if self.is_project(folder) else None

    @staticmethod
    def mark(folder):
        """What shows that the dataset changed: the folder and its manifest (rewritten by every import, box and class)."""
        try:
            st = os.stat(os.path.join(folder, "manifest.json"))
        except OSError:
            return ""
        return f"{os.path.normcase(os.path.abspath(folder))}|{st.st_size}|{st.st_mtime_ns}"

    @staticmethod
    def dmark(folder):
        """What shows that a distance was picked or changed: the number, sizes and newest time of the distance files (a pick rewrites its file, never the manifest)."""
        n = size = newest = 0
        try:
            with os.scandir(os.path.join(folder, "distances")) as it:
                for e in it:
                    if e.name.endswith(".json"):
                        st = e.stat()
                        n, size, newest = n + 1, size + st.st_size, max(newest, st.st_mtime_ns)
        except OSError:
            return ""
        return f"{n}|{size}|{newest}"

    @staticmethod
    def counts(folder):
        """{"images": annotated pictures that a Trainer can use, "boxes": their boxes, "distances": boxes with a LiDAR distance} read from the folder as it is (no annotator
        window is needed; nothing is written)."""
        import json
        out = {"images": 0, "boxes": 0, "distances": 0}
        try:
            with open(os.path.join(folder, "manifest.json"), encoding="utf-8") as f:
                imgs = (json.load(f) or {}).get("images", {})
        except (OSError, ValueError):
            return out
        for img_id, info in imgs.items():
            if not isinstance(info, dict) or not info.get("annotated") or info.get("ai_pending"):
                continue
            out["images"] += 1
            try:
                with open(os.path.join(folder, "labels", "annotated", f"{img_id}.txt"), encoding="utf-8") as f:
                    out["boxes"] += sum(1 for ln in f if ln.strip())
            except OSError:
                pass
            try:
                with open(os.path.join(folder, "distances", f"{img_id}.json"), encoding="utf-8") as f:
                    out["distances"] += sum(1 for pk in (json.load(f) or {}).get("boxes", []) if isinstance(pk, dict) and pk.get("distance_m") is not None)
            except (OSError, ValueError, AttributeError):
                pass
        return out

    def look(self, tab, node, folder):
        """Reads the cells Dataset and Distances from the folder: ready when it has annotated pictures / boxes with a distance.  -> the keys of the cells whose content changed since the
        last look (the first look of a block only sets what there is: nothing changed yet)."""
        st = tab.node_state.setdefault(node.id, {})
        m, dm = self.mark(folder), self.dmark(folder)
        first = "seen_mark" not in st
        keys = []
        if m != st.get("seen_mark") or dm != st.get("seen_dmark") or "counts" not in st:
            st["counts"] = self.counts(folder)
        c = st["counts"]
        prj = tab.project
        prj.set_ready(node.id, self.first_cell, True)
        prj.set_ready(node.id, "dataset", c["images"] > 0)
        prj.set_ready(node.id, "distances", c["distances"] > 0)
        if not first:
            if m != st["seen_mark"]:
                keys += [self.first_cell, "dataset", "distances"]
            elif dm != st["seen_dmark"]:
                keys += ["distances"]
        st["seen_mark"], st["seen_dmark"] = m, dm
        return keys

    def locate(self, tab, node):
        """The folder of a block whose project is not where it was: the person is asked where it is now.  -> the folder or None."""
        link = node.data.get("link") or {}
        from PyQt6.QtWidgets import QFileDialog
        start = os.path.dirname(link.get("abs", "")) if link.get("abs") else ""
        p = QFileDialog.getExistingDirectory(tab, f"The annotator project of '{node.title}' is not at {link.get('abs', 'its place')} any more: choose its folder", start)
        if not p:
            tab.say(f"'{node.title}': its annotator project folder was not found, so it was not opened.")
            return None
        if not self.is_project(p):
            tab.say(f"'{os.path.basename(p)}' is not an annotator project (it has no manifest.json), so '{node.title}' was not opened.")
            return None
        node.data["link"] = wp.rel_link(p, tab.path)
        tab.project.touch(node.id, self.first_cell)
        return p

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
        folder = None
        if node.data.get("link"):
            folder = self.dataset_folder(tab, node) or self.locate(tab, node)
            if folder is None:
                return None
        w = h.new_addon_tab(self.tab_kind, folder)               # no folder: a new project in a temporary one
        if w is None:
            return None
        tab.adopt_editor(node, w)
        tab.node_state.setdefault(node.id, {})["base"] = self.mark(folder) if folder else ""
        if folder:
            self.look(tab, node, folder)
        tab.say(f"{node.label} {node.title}: work in its tab. " + ("The project folder is kept as a link, never copied." if folder else
                "Save the project into a folder of its own (File > Save) and the block keeps that folder."))
        return w

    def sync(self, tab, node):
        w = tab.editor_of(node.id)
        folder = getattr(w, "path", None) if w is not None else None
        if not self.is_project(folder):
            folder = self.dataset_folder(tab, node)               # (no window, or a project that is still in its temporary folder: the folder the block links to)
            if folder is None:
                return None
        st = tab.node_state.setdefault(node.id, {})
        keys = []
        m = self.mark(folder)
        if "base" in st and m != st["base"]:
            keys.append(self.first_cell)
            tab.project.set_ready(node.id, self.first_cell, True)
        st["base"] = m
        if w is not None and self.is_project(getattr(w, "path", None)):
            link = wp.rel_link(folder, tab.path)
            if node.data.get("link") != link:
                node.data["link"] = link
        for k in self.look(tab, node, folder):
            if k not in keys:
                keys.append(k)
        return keys or None

    def source_mark(self, tab, node):
        """What a Trainer took from this block: the dataset and its distances as they are now ("" when the block has no project folder yet)."""
        folder = self.dataset_folder(tab, node)
        return f"{self.mark(folder)}#{self.dmark(folder)}" if folder else ""

    def rebaseline(self, tab, node):
        """The program itself wrote into the project folder (reading a dataset out of it also rewrites its manifest): that is not a change for the cells."""
        folder = self.dataset_folder(tab, node)
        if folder:
            st = tab.node_state.setdefault(node.id, {})
            st["base"], st["seen_mark"], st["seen_dmark"] = self.mark(folder), self.mark(folder), self.dmark(folder)

    def closed(self, tab, node):
        w = tab.editor_of(node.id)
        h = tab.host
        if w is not None and h is not None and hasattr(h, "tabs"):
            i = h.tabs.indexOf(w)
            if i >= 0:
                h.close_tab(i)                                    # (the program asks about a project that was never saved, as it does on its own)
        tab.node_state.pop(node.id, None)

    def export(self, tab, node, folder):
        tab.sync_editors()
        src = self.dataset_folder(tab, node)
        if src is None:
            raise ValueError(f"'{node.title}' has no saved annotator project yet: open it and save the project into a folder (File > Save), then save the block on its own.")
        p = wb_parts.unique_path(folder, nodes.safe_stem(node.title), ".annotator")
        os.makedirs(folder, exist_ok=True)
        shutil.copytree(src, p)
        return p


for _k, _t, _e, _a, _f in TOOLS:
    nodes.register(SheetsAdapter(_k, _t, _e, _a, _f) if _k == "sheets" else DrawingAdapter(_k, _t, _e, _a, _f) if _k == "drawing" else FileToolAdapter(_k, _t, _e, _a, _f))
nodes.register(PdfEditorAdapter())
nodes.register(AnnotatorAdapter())
