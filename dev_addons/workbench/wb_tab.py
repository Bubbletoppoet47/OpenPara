"""wb_tab.py - the WORKBENCH tab: the toolbox on the left, the project schematic on the right, and the buttons that act on the whole project.

One tab is one project (a .opara file).  Everything a project holds is a block on the schematic; a double-click on a cell opens the block's editor in a tab of its own (the
ordinary editors: the part window, the assembly window, the analysis windows); Save writes everything into the one .opara file.  Update Project refreshes the cells that
take their data from another block and then computes the cells that are out of date, in the order the wires say.  Opening a project never computes anything.
"""
import atexit
import contextlib
import os
import shutil
import sys
import tempfile
import time

from PyQt6.QtCore import QMimeData, QPointF, QRectF, QSize, Qt, QTimer
from PyQt6.QtGui import QAction, QColor, QDrag, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (QApplication, QDialog, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QToolBar,
                             QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

import wb_canvas as cv
import wb_icons as ic
import wb_nodes as nodes
import wb_project as wp

FILTER = "OpenPara project (*.opara);;All files (*)"
STATUS_NAMES = {wp.OK: "up to date", wp.INCOMPLETE: "incomplete", wp.REFRESH: "refresh required", wp.UPDATE: "update required", wp.FAILED: "failed"}


# ---------------------------------------------------------------------------------------------------------------------------- the look (Sheets: grey bars, navy ink)
BAR_H = 40                                                  # the height of the header of the toolbox and of the bar above the schematic
BAR_CSS = "background: #f0f0f0; border: 0; border-bottom: 1px solid #d3d8e2;"
TOOLBOX_CSS = """
QTreeWidget { background: #ffffff; border: 0; border-right: 1px solid #c9d0dc; color: #10204d; font-size: 13px; outline: 0; }
QTreeWidget::item { height: 22px; }
QTreeWidget::item:hover { background: #eef2f9; }
QTreeWidget::item:selected { background: #dfe8f8; color: #10204d; }
"""
BAR_BUTTONS_CSS = """
QToolBar#wbBar { %s spacing: 6px; }
QToolBar#wbBar QToolButton { font-size: 13px; font-weight: 500; color: #10204d; background: transparent; border: 1px solid transparent; border-radius: 3px; padding: 4px 8px; }
QToolBar#wbBar QToolButton:hover { background: #e3e7ef; border-color: #c9d0dc; }
QToolBar#wbBar QToolButton:pressed { background: #d6dce8; }
QToolBar#wbBar::separator { width: 1px; background: #d3d8e2; margin: 10px 4px; }
""" % BAR_CSS
HEADER_CSS = "padding: 0 12px; color: #5a6577; font-size: 13px; font-weight: 600; " + BAR_CSS
STRIP_CSS = "padding: 0 16px; color: #10204d; font-size: 12px; font-weight: 600; background: #e9edf5; border: 0; border-bottom: 1px solid #d3d8e2;"
CHIP_CSS = "background: #10204d; color: #ffffff; font-size: 11px; font-weight: 600; border-radius: 9px; padding: 2px 10px;"


def swatch(color, px=18):
    """The little square of the colour of a group in front of its name in the toolbox (a raised edge: light above and to the left, dark below and to the right)."""
    r = 2
    pm = QPixmap(px * 2, px * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    box = QRectF((px - 10) / 2.0, (px - 10) / 2.0, 10, 10)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawRoundedRect(box, r, r)
    p.fillRect(QRectF(box.left() + 1, box.top() + 0.5, box.width() - 3, 1), QColor(255, 255, 255, 90))
    p.fillRect(QRectF(box.left() + 0.5, box.top() + 1, 1, box.height() - 3), QColor(255, 255, 255, 90))
    p.fillRect(QRectF(box.left() + 2, box.bottom() - 1.5, box.width() - 3, 1), QColor(0, 0, 0, 64))
    p.fillRect(QRectF(box.right() - 1.5, box.top() + 2, 1, box.height() - 3), QColor(0, 0, 0, 64))
    p.end()
    return QIcon(pm)


# ---------------------------------------------------------------------------------------------------------------------------- the toolbox
class Toolbox(QTreeWidget):
    """The kinds of block, in groups.  Drag one onto the schematic (onto a cell that can feed it, and it is wired at once), or double-click it."""

    def __init__(self, tab):
        super().__init__()
        self.tab = tab
        self.setHeaderHidden(True)
        self.setIconSize(QSize(18, 18))
        self.setStyleSheet(TOOLBOX_CSS)
        self.setDragEnabled(True)
        self.setRootIsDecorated(True)
        self.setIndentation(12)
        self.setUniformRowHeights(True)
        self.itemDoubleClicked.connect(self.on_double)
        self.fill()

    def fill(self):
        self.clear()
        for grp in wp.GROUPS:
            kinds = [sp for sp in wp.KINDS.values() if sp.group == grp]
            if not kinds:
                continue
            g = QTreeWidgetItem([grp])
            f = QFont(self.font())
            f.setBold(True)
            g.setFont(0, f)
            g.setIcon(0, swatch(ic.GROUP_COLOR.get(grp, ic.GREY)))
            g.setSizeHint(0, QSize(0, 24))
            g.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.addTopLevelItem(g)
            for sp in kinds:
                ok, why = nodes.availability(self.tab, sp.kind)
                it = QTreeWidgetItem([sp.label])
                it.setIcon(0, ic.kind_icon(sp.kind, 18))
                it.setData(0, Qt.ItemDataRole.UserRole, sp.kind)
                it.setToolTip(0, sp.tip + ("" if ok else f"\n\n{why}"))
                fl = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled
                it.setFlags(fl)
                if not ok:
                    it.setForeground(0, self.palette().placeholderText())
                g.addChild(it)
            g.setExpanded(True)

    def item_of(self, kind):
        for i in range(self.topLevelItemCount()):
            g = self.topLevelItem(i)
            for j in range(g.childCount()):
                if g.child(j).data(0, Qt.ItemDataRole.UserRole) == kind:
                    return g.child(j)
        return None

    def on_double(self, it, _col):
        kind = it.data(0, Qt.ItemDataRole.UserRole)
        if kind:
            self.tab.add_block(kind)

    def startDrag(self, actions):
        it = self.currentItem()
        kind = it.data(0, Qt.ItemDataRole.UserRole) if it is not None else None
        if not kind:
            return
        md = QMimeData()
        md.setText(cv.MIME + kind)
        d = QDrag(self)
        d.setMimeData(md)
        d.setPixmap(it.icon(0).pixmap(28, 28))
        d.exec(Qt.DropAction.CopyAction)


# ---------------------------------------------------------------------------------------------------------------------------- the tab
class WorkbenchTab(QWidget):
    no_session = False                                      # (a workbench itself is listed in the session by its file)

    def __init__(self, host=None):
        super().__init__()
        self.host = host
        self.project = wp.Project("Project")
        self.path = None
        self.workspace = tempfile.mkdtemp(prefix="opara_wb_")
        atexit.register(self.drop_workspace)
        self.editors = {}                                   # node id -> the editor tab (a widget) that was opened for it
        self.hosted = {}                                    # node id -> (the analysis window, the node of the Coupled Physics block that shows its panes): an analysis wired into Coupled Physics has no tab
        self.node_state = {}                                # node id -> what the kind's adapter keeps about it (its workspace file, what it last read back)
        self.notes = []                                      # what the steps of the running Refresh / Update had to say (shown with the result)
        self.busy_now = False
        self.scene = cv.SchematicScene(self.project)
        self.view = cv.SchematicView(self.scene)
        self.toolbox = Toolbox(self)
        self.line = QLabel("")
        self.line.setWordWrap(True)
        self.line.setObjectName("wbLine")
        self.line.setStyleSheet("#wbLine { padding: 5px 12px; color: #5a6577; font-size: 12px; background: #f0f0f0; border-top: 1px solid #d3d8e2; }")
        self.build_ui()
        self.update_header()
        self.scene.activated.connect(self.on_activated)
        self.scene.menuAsked.connect(self.on_menu)
        self.scene.message.connect(self.say)
        self.scene.edited.connect(self.on_edited)
        self.view.dropped.connect(self.on_dropped)
        self.view.filesDropped.connect(lambda paths, pos: QTimer.singleShot(0, lambda: self.on_files_dropped(paths, pos)))      # (after the drop is over: a message may be shown)
        self.view.deleteAsked.connect(self.delete_selected)
        self.view.renameAsked.connect(self.rename_selected)
        self.scene.selectionChanged.connect(self.on_selection)
        self.say("Drag a system from the Toolbox onto the schematic, or double-click it. Double-click a cell to open its editor.")

    # ---- the window
    def build_ui(self):
        bar = QToolBar()
        bar.setObjectName("wbBar")
        bar.setIconSize(QSize(18, 18))
        bar.setMovable(False)
        bar.setFixedHeight(BAR_H)
        bar.setStyleSheet(BAR_BUTTONS_CSS)
        self.acts = {}
        lead = QWidget()
        lead.setFixedWidth(6)                                # (the bar's own padding would squeeze its buttons, so the space before the chip is a widget)
        bar.addWidget(lead)
        chip = QLabel("Workbench")
        chip.setObjectName("wbChip")
        chip.setStyleSheet("#wbChip { %s }" % CHIP_CSS)
        chip.setFixedHeight(20)
        bar.addWidget(chip)
        self.file_label = QLabel("")
        self.file_label.setObjectName("wbFile")
        self.file_label.setStyleSheet("#wbFile { color: #5a6577; font-size: 13px; margin: 0 10px 0 4px; }")
        self.file_label.setFixedHeight(24)
        bar.addWidget(self.file_label)

        def act(key, text, fn, tip, shortcut=None):
            a = QAction(text, self)
            a.setToolTip(tip)
            a.setStatusTip(tip)
            if shortcut:
                a.setShortcut(shortcut)
            a.triggered.connect(lambda _c=False, f=fn: f())
            bar.addAction(a)
            self.acts[key] = a
            return a
        act("new", "New", self.new_project, "A new, empty project in a new tab")
        act("open", "Open...", self.open_dialog, "Open a project file (.opara)")
        act("save", "Save", lambda: self.save(), "Save the project: everything in it goes into the one .opara file")
        act("save_as", "Save As...", lambda: self.save(True), "Save the project under another name")
        bar.addSeparator()
        act("refresh", "Refresh Project", lambda: self.refresh_project(), "Refresh the cells that take data from another block (the geometry of an analysis)")
        act("update", "Update Project", lambda: self.update_project(), "Refresh and compute everything that is out of date, in the order of the wires")
        bar.addSeparator()
        act("import", "Import...", self.import_dialog, "Add parts, assemblies, tool files or another project (.opara) from files as blocks")
        act("import_folder", "Import Folder...", self.import_folder_dialog, "Add an analysis project folder (.gpv, .gpf ...) or a Truss Generator folder as a block")
        act("fit", "Fit", self.view.fit_all, "Show the whole schematic")
        act("report", "Project Report", self.show_report, "What is in the project, the status of every cell, what Update would do and what is wrong")
        act("example", "Load Example Project", self.load_example, "Fills the schematic with an example project (it asks before it replaces anything)")
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(0)
        t = QLabel("Toolbox")
        t.setObjectName("wbToolboxHead")
        t.setFixedHeight(BAR_H)
        t.setStyleSheet("#wbToolboxHead { %s }" % HEADER_CSS)
        lv.addWidget(t)
        lv.addWidget(self.toolbox)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)
        rv.addWidget(bar)
        h = QLabel("Project Schematic")
        h.setObjectName("wbStrip")
        h.setFixedHeight(28)
        h.setStyleSheet("#wbStrip { %s }" % STRIP_CSS)
        rv.addWidget(h)
        rv.addWidget(self.view, 1)
        rv.addWidget(self.line)
        sp = QSplitter(Qt.Orientation.Horizontal)
        sp.addWidget(left)
        sp.addWidget(right)
        sp.setStretchFactor(1, 1)
        sp.setSizes([232, 1000])
        sp.setChildrenCollapsible(False)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(sp)

    def update_header(self):
        """The name of the project file in the bar (a star when there is something to save)."""
        name = os.path.basename(self.path) if self.path else (self.project.name if self.project.name != "Project" else "Untitled project")
        self.file_label.setText(name + (" *" if self.project.is_dirty() else ""))

    def say(self, text):
        self.line.setText(str(text))
        h = self.host
        if h is not None and hasattr(h, "statusBar"):
            try:
                h.statusBar().showMessage(str(text), 8000)
            except Exception:                                # noqa: BLE001
                pass

    def busy(self, text):
        h = self.host
        if h is not None and hasattr(h, "busy"):
            return h.busy(text)
        return contextlib.nullcontext()

    # ---- the tab contract of the program window
    def title(self):
        return os.path.basename(self.path) if self.path else (self.project.name if self.project.name != "Project" else "Workbench")

    def is_dirty(self):
        return self.project.is_dirty()

    def refresh_parts(self):
        """The program calls this when the tab is shown again: what was edited in the blocks' editors is read back."""
        self.sync_editors()
        self.update_header()

    def can_close(self):
        return not self.busy_now

    def shutdown(self):
        self.drop_workspace()

    def drop_workspace(self):
        try:
            shutil.rmtree(self.workspace, ignore_errors=True)
        except Exception:                                    # noqa: BLE001
            pass

    # ---- the project
    def set_project(self, p):
        self.node_state.clear()
        self.project = p
        self.scene.project = p
        self.path = p.path
        self.scene.rebuild()
        self.update_header()
        v = p.view
        self.view.resetTransform()
        if abs(v.get("zoom", 1.0) - 1.0) > 1e-6:
            self.view.scale(v["zoom"], v["zoom"])
        self.view.centerOn(v.get("x", 300.0), v.get("y", 150.0))
        self.on_selection()

    def load(self, path):
        p = wp.Project.read(path)
        self.close_editors()
        self.set_project(p)
        moved = list(getattr(self.scene, "moved_apart", []) or [])
        note = ""
        if moved:
            letters = ", ".join(p.nodes[i].label for i in moved if i in p.nodes)
            note = f" {len(moved)} system{'s' if len(moved) != 1 else ''} ({letters}) sat on or too close to another and {'were' if len(moved) != 1 else 'was'} moved apart; save to keep that."
        self.say(f"Opened {path}: {len(p.nodes)} systems. Nothing was computed: cells that need it say so.{note}")
        return p

    def new_project(self):
        if self.host is not None and hasattr(self.host, "new_addon_tab"):
            return self.host.new_addon_tab("workbench", None)
        self.close_editors()
        self.set_project(wp.Project("Project"))
        return self

    def open_dialog(self):
        f, _ = QFileDialog.getOpenFileName(self, "Open project", os.path.dirname(self.path) if self.path else "", FILTER)
        if f:
            self.open_path(f)

    def open_path(self, f):
        if self.host is not None and hasattr(self.host, "open_path"):
            return self.host.open_path(f)
        self.load(f)
        return self

    def save(self, as_new=False):
        path = self.project.path
        if as_new or not path:
            start = path or os.path.join(os.path.dirname(self.path) if self.path else "", (nodes.safe_stem(self.project.name) or "project") + wp.EXT)
            f, _ = QFileDialog.getSaveFileName(self, "Save project", start, FILTER)
            if not f:
                return False
            path = f if f.lower().endswith(wp.EXT) else f + wp.EXT
            if self.project.name == "Project":
                self.project.name = os.path.splitext(os.path.basename(path))[0]
        self.sync_editors()
        self.remember_view()
        try:
            self.project.write(path)
        except (OSError, wp.ProjectError) as ex:
            QMessageBox.warning(self, "Save project", f"The project could not be saved: {ex}")
            return False
        self.path = self.project.path
        self.update_header()
        self.say(f"Saved {self.path}")
        return True

    def remember_view(self):
        c = self.view.mapToScene(self.view.viewport().rect().center())
        self.project.view = {"x": round(c.x(), 1), "y": round(c.y(), 1), "zoom": round(self.view.transform().m11(), 4)}

    # ---- blocks
    def add_block(self, kind, x=None, y=None, title=None, data=None, link_from=None):
        sp = wp.spec_of(kind)
        if sp is None:
            return None
        n = self.scene.add_node(kind, x, y, title, data)
        a = nodes.adapter_for(kind)
        if a is not None:
            try:
                a.created(self, n)
            except Exception as ex:                          # noqa: BLE001
                self.say(f"'{n.title}' was added, but its editor could not be prepared: {ex}")
        if link_from is not None:
            self.scene.make_link(link_from[0], link_from[1], n.id, self.scene.compatible_cell(n.id, link_from[2], "in") or "")
        self.scene.refresh()
        ok, why = nodes.availability(self, kind)
        if not ok:
            self.say(f"Added {n.label} {n.title}. {why}")
        return n

    def on_files_dropped(self, paths, pos):
        """Files and folders dropped on the canvas become blocks at the drop point, side by side: a part, an assembly, an analysis project (its setup and results only: it
        has no geometry until it is wired), a tool file or another project.  -> the nodes made."""
        return self.import_many(paths, pos.x(), pos.y())

    def on_dropped(self, kind, pos):
        """A kind was dropped from the toolbox: onto a cell that can feed it, the new block is put to the right and wired; else where it was dropped."""
        sp = wp.spec_of(kind)
        if sp is None:
            return
        for it in self.scene.items(pos):
            if isinstance(it, cv.SystemItem):
                w = it.where(it.mapFromScene(pos))
                c = it.node().spec.cell(w) if it.node().spec and w else None
                if c is not None and c.provides and any(set(c.provides) & set(x.accepts) for x in sp.cells):
                    x, y = it.pos().x() + cv.BLOCK_W + 4 * cv.GRID, it.pos().y()
                    self.add_block(kind, x, y, link_from=(it.nid, w, c.provides))
                    return
                break
        self.add_block(kind, pos.x(), pos.y())

    def on_edited(self):
        self.relink()
        self.scene.refresh()
        self.update_header()

    def relink(self):
        """A wire was made or removed: a block whose own readiness depends on where it is wired (a stress analysis wired into Coupled Physics needs no load) is looked at again."""
        for n in list(self.project.nodes.values()):
            a = nodes.adapter_for(n.kind)
            if a is None or n.spec is None or not hasattr(a, "relink"):
                continue
            try:
                a.relink(self, n)
            except Exception as ex:                          # noqa: BLE001
                self.say(f"'{n.title}' could not be looked at again: {ex}")

    def on_selection(self):
        try:
            ids = self.scene.selected_ids()
        except RuntimeError:                                 # the scene is being deleted with the window
            return
        if len(ids) == 1:
            n = self.project.nodes[ids[0]]
            sts = self.project.statuses(n.id)
            if n.spec is not None:
                self.say(f"{n.label}  {n.title}: " + ", ".join(f"{n.cell_name(c.key)} {c.label} {STATUS_NAMES[sts[c.key]]}" for c in n.spec.cells))
        elif len(ids) > 1:
            self.say(f"{len(ids)} systems selected: drag one to move them all.")

    def selected_nodes(self):
        return [self.project.nodes[i] for i in self.scene.selected_ids() if i in self.project.nodes]

    def delete_selected(self):
        """Deletes the selected wires, and the selected blocks after asking (what is inside a block is part of the project and goes with it)."""
        for k in self.scene.selected_links():
            self.scene.remove_link(k)
        ns = self.selected_nodes()
        if not ns:
            return 0
        names = ", ".join(f"{n.label} {n.title}" for n in ns[:6]) + (f" and {len(ns) - 6} more" if len(ns) > 6 else "")
        r = QMessageBox.question(self, "Delete", f"Delete {names} from the project?\n\nWhat is inside {'it' if len(ns) == 1 else 'them'} (the part, the setup ...) is deleted with "
                                 "the block. Its wires go too.", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if r != QMessageBox.StandardButton.Yes:
            return 0
        for n in ns:
            a = nodes.adapter_for(n.kind)
            if a is not None:
                try:
                    a.closed(self, n)
                except Exception:                            # noqa: BLE001
                    pass
            self.editors.pop(n.id, None)
            self.hosted.pop(n.id, None)
        self.scene.remove_nodes([n.id for n in ns])
        self.say(f"Deleted {names}.")
        return len(ns)

    def rename_selected(self):
        ns = self.selected_nodes()
        if len(ns) == 1:
            self.rename(ns[0].id)

    def rename(self, nid):
        n = self.project.node(nid)
        t, ok = QInputDialog.getText(self, "Rename", "Name of the system:", text=n.title)
        if ok:
            self.project.rename_node(nid, t)
            self.scene.refresh()
            self.scene.edited.emit()
        return ok

    # ---- editors
    def on_activated(self, nid, what):
        if what == "caption":
            self.rename(nid)
            return
        self.open_cell(nid, what)

    def open_cell(self, nid, key):
        n = self.project.node(nid)
        if n.spec is None:
            self.say(f"'{n.title}' is of a kind this program does not know ({n.kind}); it is kept in the file but cannot be opened here.")
            return None
        if key not in [c.key for c in n.spec.cells]:
            key = n.spec.cells[0].key if key in ("name", "head") else key
        a = nodes.adapter_for(n.kind)
        if a is None:
            self.say(f"'{n.title}': this kind is not wired into the workbench yet.")
            return None
        ok, why = a.available(self)
        if not ok:
            self.say(why)
            return None
        note = self.refresh_geometry_on_open(n) if getattr(a, "simulation", False) else None
        try:
            w = a.open_cell(self, n, key)
        except Exception as ex:                              # noqa: BLE001
            import traceback
            self.say(f"'{n.title}' could not be opened: {ex}")
            try:
                import gpd_app
                gpd_app.log_error(f"The workbench could not open '{n.title}':\n{traceback.format_exc()}")
            except Exception:                                # noqa: BLE001
                pass
            return None
        self.scene.refresh()
        if note:
            self.say(note)                                   # (the editor said its own hint while it opened: what happened to the geometry matters more)
        return w

    def refresh_geometry_on_open(self, n):
        """Opening a simulation block brings its GEOMETRY up to date with the part or assembly wired into it, when that changed since the block took it.  Only that cell:
        the solve is never run here (the solution then says 'update' until the person runs it).  A refresh that fails leaves the block as it was.
        -> the sentence to say once the block is open (what was done, or why it failed), or None when there was nothing to do."""
        prj = self.project
        c = n.spec.cell("geometry") if n.spec is not None else None
        k = prj.incoming(n.id, "geometry") if c is not None and c.role == "import" else None
        if k is None:
            return None
        self.sync_editors()                                  # a part changed in its own tab goes into the project first
        if prj.status(n.id, "geometry") != wp.REFRESH:
            return None
        src = prj.node(k.a)
        err = self.run_step(n.id, "geometry", "refresh")
        self.scene.refresh()
        if err:
            return f"{n.label} {n.title}: its geometry could not be refreshed from '{src.title}' ({err}); it opens as it was."
        return f"{n.label} {n.title}: its geometry was refreshed from '{src.title}'. Nothing was solved: run the solution when you want it."

    def register_editor(self, node, widget):
        """The tab of an editor opened for a node: it does not go in the recent list or the session (it lives in the workspace), it closes with the workbench, and its
        tab is named after the block."""
        self.editors[node.id] = widget
        widget.no_session = True
        widget.depends_on = lambda: self
        widget.title = lambda n=node: f"{n.label} {n.title}"
        return widget

    def show_editor(self, node, widget):
        """Puts the editor of a node in a tab of the program window (as a tab of this project: no recent list, no session)."""
        self.register_editor(node, widget)
        h = self.host
        if h is not None and hasattr(h, "add_tab"):
            h.add_tab(widget)
        return widget

    def adopt_editor(self, node, widget):
        """An editor that the program window already put in a tab (an analysis opened from its project folder) becomes the node's editor."""
        self.register_editor(node, widget)
        h = self.host
        if h is not None and hasattr(h, "refresh_titles"):
            h.refresh_titles()
        return widget

    def register_hosted(self, node, widget, owner):
        """An analysis window whose panes are shown in the window of the Coupled Physics block `owner` (no tab of its own): it is the node's editor for as long as that window is open."""
        self.hosted[node.id] = (widget, owner.id)
        return widget

    def hosted_by(self, nid):
        """The node id of the Coupled Physics block that shows the analysis `nid`, or None (not hosted, or its window is closed)."""
        hw = self.hosted.get(nid)
        if hw is None:
            return None
        return hw[1] if self.editor_of(nid) is not None else None

    def editor_of(self, nid):
        """The editor tab of a node when it is still open, else None.  An analysis shown inside the window of a Coupled Physics block is its editor too (the window, not a tab)."""
        hw = self.hosted.get(nid)
        if hw is not None:
            w, owner = hw
            try:
                if self.editor_of(owner) is None:
                    self.hosted.pop(nid, None)
                    return None
                w.isVisible()                                # a deleted Qt object raises here
            except RuntimeError:
                self.hosted.pop(nid, None)
                return None
            return w
        w = self.editors.get(nid)
        if w is None:
            return None
        h = self.host
        try:
            if h is not None and hasattr(h, "is_open") and not h.is_open(w):
                self.editors.pop(nid, None)
                return None
            w.isVisible()                                    # a deleted Qt object raises here
        except RuntimeError:
            self.editors.pop(nid, None)
            return None
        return w

    def close_editors(self):
        h = self.host
        for nid in list(self.editors):
            w = self.editor_of(nid)
            if w is not None and h is not None and hasattr(h, "tabs"):
                i = h.tabs.indexOf(w)
                if i >= 0:
                    h.close_tab(i)
        self.editors.clear()

    def sync_editors(self, skip=()):
        """What was edited in the blocks' editors goes back into the project (a changed block makes the cells that use it say refresh / update)."""
        changed = []
        for n in list(self.project.nodes.values()):
            a = nodes.adapter_for(n.kind)
            if a is None or n.spec is None or n.id in skip:
                continue
            try:
                keys = a.sync(self, n)
            except Exception as ex:                          # noqa: BLE001
                self.say(f"'{n.title}' could not be read back from its editor: {ex}")
                continue
            keys = [keys] if isinstance(keys, str) else list(keys or [])
            for key in keys:
                self.project.touch(n.id, key)
            if keys:
                changed.append(n.id)
        if changed:
            self.scene.refresh()
        return changed

    # ---- refresh and update
    def run_step(self, nid, key, action):
        """One refresh or update.  -> None when it worked, else the text of what went wrong (the cell then shows failed)."""
        n = self.project.node(nid)
        a = nodes.adapter_for(n.kind)
        if a is None:
            err = "this kind is not wired into the workbench yet"
        else:
            try:
                err = a.refresh(self, n, key) if action == "refresh" else a.update(self, n, key)
            except Exception as ex:                          # noqa: BLE001
                import traceback
                err = f"{type(ex).__name__}: {ex}"
                try:
                    import gpd_app
                    gpd_app.log_error(f"Workbench {action} of {n.cell_name(key)} failed:\n{traceback.format_exc()}")
                except Exception:                            # noqa: BLE001
                    pass
        if err:
            self.project.mark_failed(nid, key, err)
        elif action == "refresh":
            self.project.mark_refreshed(nid, key)
        else:
            self.project.mark_updated(nid, key)
        return err or None

    def note(self, text):
        """Something a step wants the person to know: said now, and again with the final message of the Refresh / Update."""
        self.notes.append(str(text))
        self.say(text)

    def run_plan(self, steps, what):
        done, failed, skip = 0, [], set()
        self.notes = []
        self.busy_now = True
        try:
            for s in steps:
                if s["node"] in skip:
                    continue
                self.say(f"{what}: {s['action']} {s['name']} ...")
                QApplication.processEvents()
                err = self.run_step(s["node"], s["cell"], s["action"])
                self.scene.refresh()
                if err:
                    failed.append((s["name"], err))
                    skip.add(s["node"])
                else:
                    done += 1
        finally:
            self.busy_now = False
        self.scene.refresh()
        more = ("  " + " ".join(self.notes)) if self.notes else ""
        if failed:
            self.say(f"{what}: {done} done, {len(failed)} failed: " + "; ".join(f"{n}: {e}" for n, e in failed[:3]) + more)
        elif done:
            self.say(f"{what}: {done} step{'s' if done != 1 else ''} done. Everything that could be is up to date." + more)
        else:
            self.say(f"{what}: nothing to do." + ("" if not self.project.blocked() else " Some cells are incomplete: " + self.project.blocked()[0][1]) + more)
        return done, failed

    def refresh_project(self, only=None):
        self.sync_editors()
        steps = [s for s in self.project.plan_update(only) if s["action"] == "refresh"]
        return self.run_plan(steps, "Refresh Project")

    def update_project(self, only=None):
        self.sync_editors()
        return self.run_plan(self.project.plan_update(only), "Update Project")

    def update_node(self, nid):
        return self.update_project(only={nid})

    # ---- menus
    def build_menu(self, info):
        m = QMenu(self)
        prj = self.project
        nid, key = info.get("node"), info.get("cell")
        if info["on"] in ("cell", "node") and nid in prj.nodes:
            n = prj.nodes[nid]
            sp = n.spec
            if sp is not None and info["on"] == "cell":
                c = sp.cell(key)
                m.addAction(f"Open {n.cell_name(key)} {c.label}", lambda: self.open_cell(nid, key))
                st = prj.status(nid, key)
                if c.role == "import" and st == wp.REFRESH:
                    m.addAction(f"Refresh {n.cell_name(key)}", lambda: self.update_project(only={nid}))
                if c.role == "compute":
                    m.addAction(f"Update {n.cell_name(key)}", lambda: self.update_project(only={nid}))
                if st == wp.INCOMPLETE:
                    m.addAction("Why is it incomplete?", lambda: self.say(prj.why_incomplete(nid, key)))
                if st == wp.FAILED:
                    m.addAction("Show what failed", lambda: self.say(prj.cell(nid, key)["failed"]))
                for k in [x for x in prj.links if x.b == nid and x.b_cell == key] + [x for x in prj.links if x.a == nid and x.a_cell == key]:
                    other = prj.nodes[k.a if k.b == nid else k.b]
                    m.addAction(f"Remove the wire to {other.title}", lambda k=k: self.scene.remove_link(k))
                m.addSeparator()
            if sp is not None:
                m.addAction("Update this system", lambda: self.update_project(only={nid}))
            m.addAction("Rename...", lambda: self.rename(nid))
            a = nodes.adapter_for(n.kind)
            if a is not None and sp is not None and sp.standalone:
                m.addAction("Save this system on its own...", lambda: self.export_node(nid))
            m.addAction("Delete...", self.delete_selected)
        elif info["on"] == "link":
            m.addAction("Remove this wire", self.delete_selected)
        else:
            sub = m.addMenu("Add a system")
            for grp in wp.GROUPS:
                gm = None
                for sp in wp.KINDS.values():
                    if sp.group != grp:
                        continue
                    if gm is None:
                        gm = sub.addMenu(grp)
                    pos = info.get("scene") or QPointF(0, 0)
                    gm.addAction(ic.kind_icon(sp.kind), sp.label, lambda k=sp.kind, p=pos: self.add_block(k, p.x(), p.y()))
            m.addAction("Fit to window", self.view.fit_all)
        return m

    def on_menu(self, info):
        m = self.build_menu(info)
        if not m.isEmpty():
            m.exec(info["global"] if info.get("global") is not None else self.cursor().pos())

    # ---- saving a block on its own, importing
    def export_node(self, nid, folder=None):
        n = self.project.node(nid)
        a = nodes.adapter_for(n.kind)
        if a is None:
            self.say("That kind cannot be saved on its own yet.")
            return None
        if folder is None:
            folder = QFileDialog.getExistingDirectory(self, "Save this system on its own: choose the folder", os.path.dirname(self.path) if self.path else "")
            if not folder:
                return None
        self.sync_editors()
        try:
            p = a.export(self, n, folder)
        except Exception as ex:                              # noqa: BLE001
            QMessageBox.warning(self, "Save on its own", f"Could not save it: {ex}")
            return None
        if p:
            self.say(f"Saved '{n.title}' as {p}")
        return p

    def import_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Import into the project", os.path.dirname(self.path) if self.path else "",
                                                "Parts, assemblies, tools and projects (*.gpd *.gpa *.opsheet *.opctl *.opcirc *.opara);;All files (*)")
        return self.import_many(files)

    def import_folder_dialog(self):
        d = QFileDialog.getExistingDirectory(self, "Import an analysis project or Truss folder", os.path.dirname(self.path) if self.path else "")
        return self.import_many([d] if d else [])

    def import_many(self, paths, x=None, y=None):
        """Imports every path (side by side from x, y when they are given); what could not be imported is listed with its reason in one message.  -> the nodes made."""
        out, bad = [], []
        for i, f in enumerate(paths):
            n = self.import_file(f, None if x is None else x + i * (cv.BLOCK_W + 2 * cv.GRID), y)
            if n is not None:
                out.append(n)
            else:
                bad.append(f"{os.path.basename(str(f).rstrip('/' + chr(92)))}: {self.line.text()}")
        if bad:
            QMessageBox.warning(self, "Import", "Not imported:\n\n" + "\n\n".join(bad))
        return out

    def import_file(self, path, x=None, y=None):
        """A part, an assembly or a project of the old kind becomes a block (wb_import).  -> the node or None (the reason is said)."""
        try:
            import wb_import
        except ImportError:
            self.say("Importing is not available in this version of the workbench.")
            return None
        return wb_import.import_path(self, path, x, y)

    # ---- the example and the report
    def load_example(self):
        if self.project.nodes and self.is_dirty():
            r = QMessageBox.question(self, "Load Example Project", "This replaces the project in this tab. Unsaved changes are lost.\n\nContinue?")
            if r != QMessageBox.StandardButton.Yes:
                return None
        try:
            import wb_example
        except ImportError:
            self.say("There is no example project in this version of the workbench yet.")
            return None
        self.close_editors()
        wb_example.load(self)
        self.scene.rebuild()
        self.scene.refresh()
        self.view.fit_all()
        return self.project

    def report_text(self):
        lines = ["OpenPara Workbench - project report", "=" * 36, time.strftime("%Y-%m-%d %H:%M:%S"),
                 f"Program {wp.program_version()}, Python {sys.version.split()[0]}", ""]
        lines += self.project.report_lines()
        lines += ["", "Editors open: " + (", ".join(f"{self.project.nodes[i].label}" for i in self.editors if i in self.project.nodes and self.editor_of(i) is not None) or "none")]
        miss = nodes.check_kinds()
        if miss:
            lines.append("Kinds with no editor wired in yet: " + ", ".join(miss))
        return "\n".join(lines)

    def show_report(self):
        text = self.report_text()
        d = QDialog(self)
        d.setWindowTitle("Project Report")
        d.resize(820, 560)
        v = QVBoxLayout(d)
        ed = QPlainTextEdit(text)
        ed.setReadOnly(True)
        f = QFont("Consolas")
        f.setStyleHint(QFont.StyleHint.Monospace)
        ed.setFont(f)
        v.addWidget(ed)
        h = QHBoxLayout()
        b1, b2, b3 = QPushButton("Copy"), QPushButton("Save as text..."), QPushButton("Close")
        b1.clicked.connect(lambda: QApplication.clipboard().setText(text))
        b2.clicked.connect(lambda: self.save_report(text))
        b3.clicked.connect(d.accept)
        h.addStretch(1)
        for b in (b1, b2, b3):
            h.addWidget(b)
        v.addLayout(h)
        d.exec()
        return text

    def save_report(self, text):
        f, _ = QFileDialog.getSaveFileName(self, "Save the report", "workbench_report.txt", "Text (*.txt)")
        if f:
            with open(f, "w", encoding="utf-8") as fh:
                fh.write(text)


def load_adapters():
    """What each kind of block does comes from its own module (a module that cannot be loaded leaves its kinds 'not wired in', the rest works)."""
    for name in ("wb_parts", "wb_analysis", "wb_tools", "wb_trainer", "wb_study", "wb_coupled"):
        try:
            __import__(name)
        except Exception:                                    # noqa: BLE001
            import traceback
            try:
                import gpd_app
                gpd_app.log_error(f"The workbench could not load {name}:\n{traceback.format_exc()}")
            except Exception:                                # noqa: BLE001
                pass


load_adapters()


def make_workbench(host=None, path=None):
    w = WorkbenchTab(host)
    if path:
        w.load(path)
    return w
