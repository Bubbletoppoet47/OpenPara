"""wb_nodes.py - what each KIND of node does in the workbench: how its editor is opened, how what was edited is read back into the project, how a cell is refreshed
or updated, how the node is saved on its own.  The window (wb_tab) only calls these; a kind with no adapter still shows in the schematic (and is saved in the file) but
cannot be opened.

An adapter works on the node's WORKSPACE: a folder under a temporary folder of the open project, where the node is written as the ordinary file or project folder its editor
already knows (a .gpd for a part, a .gpv folder for a 3D analysis ...).  The editor opens that file like any other tab.  Before the project is saved the workspace is read back
into node.data (from the live editor when it is open, else from the files).  So the existing editors need no change, and a project file never depends on a file lying in some
other folder.
"""
import os

import wb_project as wp

ADAPTERS = {}


def register(adapter):
    ADAPTERS[adapter.kind] = adapter
    return adapter


def adapter_for(kind):
    return ADAPTERS.get(kind)


class Adapter:
    kind = ""
    needs = ""                       # the add-on the kind needs ("" = nothing beyond the program)
    first_cell = ""                  # the cell that holds the content a double-click opens (the cell that changes when the editor changes something)
    simulation = False               # an analysis block: opening it first refreshes its geometry cell when the wired part / assembly changed (it never solves)

    # ---- is it possible at all here
    def available(self, tab):
        """(True, "") or (False, why not): the add-on that the kind needs is not installed, a package is missing ..."""
        return True, ""

    # ---- the node and its editor
    def created(self, tab, node):
        """A node of this kind was just added in the schematic."""

    def open_cell(self, tab, node, key):
        tab.say(f"'{node.title}': opening {key} is not wired up for this kind yet.")
        return None

    def sync(self, tab, node):
        """Reads the node back from its editor / workspace into node.data.  -> the key of the cell whose content changed, or None."""
        return None

    def refresh(self, tab, node, key):
        """An import cell takes the new data of its source.  -> None when done, else the text of what went wrong."""
        return None

    def update(self, tab, node, key):
        """A compute cell is computed.  -> None when done, else the text of what went wrong."""
        return None

    def relink(self, tab, node):
        """A wire was made or removed somewhere: look at the node again where its own readiness depends on its wires."""

    def closed(self, tab, node):
        """The node was removed from the project: close its editor, forget its workspace."""

    def export(self, tab, node, folder):
        """Writes the node out as its own file or project folder (the form of node.spec.standalone) into `folder`.  -> the path, or None."""
        return None


def workspace_of(tab, node):
    """The folder of a node in the open project's workspace (made when asked for)."""
    d = os.path.join(tab.workspace, node.id)
    os.makedirs(d, exist_ok=True)
    return d


def safe_stem(title):
    """A name that is a good file name on every system."""
    s = "".join(ch if ch.isalnum() or ch in " -_()." else "_" for ch in str(title)).strip(" .")
    return s or "node"


class Unavailable(Adapter):
    """The kind of a block whose add-on is not wired in (used for the toolbox note)."""
    def __init__(self, kind, why):
        self.kind, self.why = kind, why

    def available(self, tab):
        return False, self.why


# the generic wording used by the toolbox
def availability(tab, kind):
    a = adapter_for(kind)
    if a is None:
        return False, "Not wired into the workbench yet: you can place the block and it is saved, but it cannot be opened."
    return a.available(tab)


def check_kinds():
    """[kind] of every registered kind that has no adapter (for the report)."""
    return [k for k in wp.KINDS if k not in ADAPTERS]
