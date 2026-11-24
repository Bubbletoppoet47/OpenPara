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
TOOLS = (("sheets", "sheets", ".opsheet", "Sheets", False), ("controls", "controls", ".opctl", "Systems and Controls", False), ("circuits", "circuits", ".opcirc", "Circuits", False),
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


for _k, _t, _e, _a, _f in TOOLS:
    nodes.register(FileToolAdapter(_k, _t, _e, _a, _f))
