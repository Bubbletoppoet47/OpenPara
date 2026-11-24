"""wb_parts.py - the Part and Assembly blocks of the workbench.

A PART block holds one part (the JSON of a .gpd file).  Double-click: the part is written to the project's workspace as an ordinary .gpd and opened in the usual part window; what
is edited there is read back into the block (when the project is saved, when the Workbench tab is shown again, before Update Project).  The block is READY when the part has a solid.

An ASSEMBLY block holds one assembly (the JSON of a .gpa file) with its own COPY of every part in it (core/asm_embed.py), so its data is self-contained.  Double-click opens the usual
assembly window in embed mode: Insert Component offers the Part blocks of the project (and "Browse for a file...") and puts a copy in the assembly; Edit Component edits that copy only.
There is no link from a Part block to an assembly: changing the part afterwards does not change the assembly (that comes later).  Both kinds can be saved out as a .gpd / .gpa file of their
own (self-contained), and such a file can be imported as a block (wb_import).
"""
import json
import os

import wb_nodes as nodes
import wb_project as wp


def unique_path(folder, stem, ext):
    """folder/stem.ext, or folder/stem (2).ext ... when that exists (a file is never overwritten)."""
    p = os.path.join(folder, stem + ext)
    i = 2
    while os.path.exists(p):
        p = os.path.join(folder, f"{stem} ({i}){ext}")
        i += 1
    return p


def write_text(path, text):
    try:
        import fileio
        fileio.write_text(path, text)
    except ImportError:                                      # noqa: BLE001
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)


class DocAdapter(nodes.Adapter):
    """What a part and an assembly have in common: one file in the workspace, one window."""
    ext = ""
    key = ""                                                 # the field of node.data that holds the JSON object ("doc" / "asm")
    first_cell = "geometry"

    # ---- the file of the node in the workspace
    def path_of(self, tab, node):
        return os.path.join(nodes.workspace_of(tab, node), nodes.safe_stem(node.title) + self.ext)

    def empty(self):
        raise NotImplementedError

    def created(self, tab, node):
        """A new block starts as an empty part / assembly (so that opening it for the first time is not a change); one made with content is judged now."""
        if node.data.get(self.key) is None:
            node.data[self.key] = json.loads(self.empty())
            return
        # a block made with content (an import, the example): it says at once whether it is ready
        tab.project.set_ready(node.id, self.first_cell, bool(self.ready_of(tab, node, None, node.data[self.key])))

    def state(self, tab, node):
        return tab.node_state.setdefault(node.id, {})

    def materialize(self, tab, node):
        """Writes the block's content to its file in the workspace; -> the path.  (Only when its editor is not open: an open editor owns the file.)"""
        st = self.state(tab, node)
        p = self.path_of(tab, node)
        old = st.get("file")
        if old and old != p and os.path.exists(old):             # the block was renamed: its file follows
            try:
                os.replace(old, p)
            except OSError:
                pass
        st["file"] = p
        obj = node.data.get(self.key)
        write_text(p, json.dumps(obj, indent=1) if obj is not None else self.empty())
        return p

    def window_for(self, tab, node, path):
        raise NotImplementedError

    def open_cell(self, tab, node, key):
        w = tab.editor_of(node.id)
        if w is not None:
            h = tab.host
            if h is not None and hasattr(h, "tabs"):
                h.tabs.setCurrentWidget(w)
            return w
        tab.sync_editors()                                       # edits made in an editor that was closed since are taken first: the file is only a cache
        p = self.materialize(tab, node)
        w = self.window_for(tab, node, p)
        if w is None:
            return None
        st = self.state(tab, node)
        text = self.live_text(w)                                 # what the editor makes of the file is the baseline: opening a block is not a change
        st["base"] = json.loads(text)
        write_text(p, text)
        tab.show_editor(node, w)
        tab.say(f"{node.label} {node.title}: edit it in its tab. The project takes the changes when you save it or come back here.")
        return w

    # ---- reading back
    def live_text(self, w):
        raise NotImplementedError

    def ready_of(self, tab, node, w, obj):
        raise NotImplementedError

    def sync(self, tab, node):
        st = tab.node_state.get(node.id)
        if not st or "base" not in st:
            return None                                          # never opened: there is nothing to read back
        w = tab.editor_of(node.id)
        try:
            if w is not None:
                text = self.live_text(w)
            elif st.get("file") and os.path.isfile(st["file"]):
                with open(st["file"], encoding="utf-8") as f:
                    text = f.read()
            else:
                return None
            obj = json.loads(text)
        except Exception as ex:                                  # noqa: BLE001
            tab.say(f"'{node.title}' could not be read back: {ex}")
            return None
        if w is not None:                                        # the project has it now: the editor is not 'unsaved' any more
            try:
                if w.is_dirty():
                    w.save()
            except Exception:                                    # noqa: BLE001
                pass
        if obj == st["base"]:
            return None
        st["base"] = obj
        node.data[self.key] = obj
        tab.project.set_ready(node.id, self.first_cell, bool(self.ready_of(tab, node, w, obj)))
        return self.first_cell

    def closed(self, tab, node):
        w = tab.editor_of(node.id)
        h = tab.host
        if w is not None and h is not None and hasattr(h, "tabs"):
            try:
                if w.is_dirty():
                    w.save()                                     # (the block is going: no question about its unsaved changes)
            except Exception:                                    # noqa: BLE001
                pass
            i = h.tabs.indexOf(w)
            if i >= 0:
                h.close_tab(i)
        tab.node_state.pop(node.id, None)

    def export(self, tab, node, folder):
        if node.data.get(self.key) is None:
            raise ValueError(f"'{node.title}' is empty: there is nothing to save yet.")
        p = unique_path(folder, nodes.safe_stem(node.title), self.ext)
        write_text(p, json.dumps(node.data[self.key], indent=1))
        return p


class PartAdapter(DocAdapter):
    kind = "part"
    ext = ".gpd"
    key = "doc"

    def empty(self):
        import pm_model as pm
        return pm.Document().to_json()

    def window_for(self, tab, node, path):
        import pm_app
        return pm_app.MainWindow(path)

    def live_text(self, w):
        return w.doc.to_json()

    def ready_of(self, tab, node, w, obj):
        """A part is ready when it has a solid: the live Document says; a part that is not open is built once from its text."""
        if w is not None and getattr(w, "doc", None) is not None:
            return w.doc.solid is not None
        return solid_of_text(json.dumps(obj)) is not None


def solid_of_text(text):
    import pm_model as pm
    try:
        d = pm.Document.from_json(text)
        d.rebuild()
        return d.solid
    except Exception:                                            # noqa: BLE001
        return None


class AssemblyAdapter(DocAdapter):
    kind = "assembly"
    ext = ".gpa"
    key = "asm"

    def empty(self):
        import asm_model as am
        return am.Assembly().to_json()

    def window_for(self, tab, node, path):
        import assembly
        h = tab.host
        w = assembly.AssemblyWindow(None, shell=h)
        w.embed = True                                           # inserted parts are copied in; an old file with paths is read as copies
        w.open_file(path)
        w.insert_hook = lambda win, t=tab, n=node: choose_and_insert(t, n, win)
        return w

    def live_text(self, w):
        w.sync_embedded()
        return w.asm.to_json()

    def ready_of(self, tab, node, w, obj):
        """An assembly is ready when at least one of its components has a solid."""
        if w is not None and hasattr(w, "asm"):
            for c in w.asm.components:
                if c.get("derived"):
                    continue
                d = w.part_doc(c)
                if d is not None and d.solid is not None:
                    return True
            return False
        return bool(obj.get("components"))


# ---------------------------------------------------------------------------------------------------------------------------- Insert Component from the project
def project_sources(tab, exclude=None):
    """[{"name", "kind": "part" | "assembly", "text", "node": id}] of the Part and Assembly blocks of the project that have content, newest state (editors are read back first)."""
    tab.sync_editors(skip={exclude} if exclude else ())            # (not the assembly that is being worked on: it is the one asking)
    out = []
    for n in tab.project.nodes.values():
        if n.id == exclude or n.kind not in ("part", "assembly"):
            continue
        key = "doc" if n.kind == "part" else "asm"
        if n.data.get(key) is None:
            continue
        out.append({"name": nodes.safe_stem(n.title), "kind": n.kind, "text": json.dumps(n.data[key]), "node": n.id})
    return out


def choose_sources(tab, items, parent=None):
    """Asks which of the project's parts to insert.  -> ("project", [items chosen]) | ("browse", None) | (None, None) for Cancel.  (Replaced in the tests.)"""
    from PyQt6.QtWidgets import QAbstractItemView, QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout
    d = QDialog(parent)
    d.setWindowTitle("Insert Component")
    v = QVBoxLayout(d)
    v.addWidget(QLabel("Parts and assemblies of this project. Each one is COPIED into the assembly:\nchanging the copy does not change the block, and the other way round."))
    lst = QListWidget()
    lst.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    for it in items:
        li = QListWidgetItem(f"{tab.project.nodes[it['node']].label}  {it['name']}   ({'part' if it['kind'] == 'part' else 'assembly'})")
        li.setData(0x100, it)
        lst.addItem(li)
    v.addWidget(lst)
    res = {"how": None}
    h = QHBoxLayout()
    b_ins, b_browse, b_cancel = QPushButton("Insert"), QPushButton("Browse for a file..."), QPushButton("Cancel")
    b_ins.clicked.connect(lambda: (res.update(how="project"), d.accept()))
    b_browse.clicked.connect(lambda: (res.update(how="browse"), d.accept()))
    b_cancel.clicked.connect(d.reject)
    h.addStretch(1)
    for b in (b_ins, b_browse, b_cancel):
        h.addWidget(b)
    v.addLayout(h)
    d.resize(460, 340)
    d.exec()
    if res["how"] == "project":
        return "project", [lst.item(i).data(0x100) for i in range(lst.count()) if lst.item(i).isSelected()]
    return (res["how"], None)


def choose_and_insert(tab, node, win):
    """The Insert Component hook of an assembly window in the workbench.  -> True when it did the inserting (or the user cancelled), False to let the file dialog open."""
    items = project_sources(tab, exclude=node.id)
    if not items:
        return False
    how, chosen = choose_sources(tab, items, win)
    if how == "browse":
        return False
    if how == "project" and chosen:
        win.insert_files([{"name": it["name"], "kind": it["kind"], "text": it["text"]} for it in chosen])
    return True


nodes.register(PartAdapter())
nodes.register(AssemblyAdapter())
