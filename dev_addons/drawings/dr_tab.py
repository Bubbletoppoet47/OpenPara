"""
dr_tab.py - the Drawings tab: a ribbon (View Layout, Annotation, Sketch), the Outline + Details column on the left (the Model View and Projected View panels open in its place), the
sheet in the middle (a white sheet on a grey canvas) and a status line.  It looks and behaves like the Part window.

Files: .opdraw (JSON: the sheet, the copies of the models, the views, and what is drawn on them: dimensions, marks, balloons; and on the sheet: notes and lines).  Export > PDF writes the sheet at its true paper size.
In a Workbench block ("Drawing") the models are not added by hand: the parts and assemblies wired into the block are the models (sync_models).
"""
import json
import os

from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (QFileDialog, QFrame, QInputDialog, QHBoxLayout, QLabel, QMenu, QScrollArea, QSplitter, QStackedWidget, QTabWidget, QToolButton, QVBoxLayout, QWidget)

import dr_annot as A
import dr_canvas as C
import dr_geom as G
import dr_icons as I
import dr_items as IT
import dr_model as M
import dr_panels as PN
import dr_pdf
import dr_proj as P
import dr_sheet as S
import ui_kit

FILTER = "Drawing (*.opdraw);;All files (*)"
RIBBON_QSS = "QToolButton{font-size:11px; padding:2px;} QToolButton:disabled{color:#a0a0a0;} QToolButton:checked{background:#cfe3fb; border:1px solid #6aa0e0;}"
UNDO_LIMIT = 60
TOOL_KEYS = ("dim", "center_mark", "centerline", "note", "balloon", "note_pattern", "line", "rect", "circle", "arc")
NEEDS_VIEW = ("dim", "center_mark", "centerline", "balloon")           # the tools that pick things on the views (the others work on the bare sheet)


class DrawingTab(QWidget):
    ASK_SHEET = True                                  # a new drawing asks for its sheet when it first shows (a test turns this off)

    def __init__(self, path=None):
        super().__init__()
        self.host = None
        self.path = None
        self.kind = "drawing"
        self.title_text = "Drawing"
        self.models_from_wires = False                # a Drawing block of the Workbench: the wired parts and assemblies are the models
        self.d = M.Drawing()
        self.undo_stack, self.redo_stack = [], []
        self.state = self.d.snapshot()
        self.version, self.saved_version = 0, 0
        self.cmd = None                               # "model" | "projected" | None
        self.asked = bool(path)
        self.act = {}
        self.build_ui()
        if path:
            self.open_path(path)
        self.after_change()

    # ------------------------------------------------------------------------------------------------------------------------ the window
    def build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.canvas = C.SheetCanvas(self.d)
        # ---- the ribbon (the look of the Part window: a tab strip under big buttons)
        self.ribbon = QTabWidget()
        self.ribbon.setFixedHeight(104)
        self.ribbon.setDocumentMode(True)
        self.ribbon.setTabPosition(QTabWidget.TabPosition.South)
        self.ribbon.addTab(self.ribbon_page([
            ("model", "dr_model_view", "Model\nView", "Put a view of a part or an assembly on the sheet", lambda: self.open_command("model")),
            ("projected", "dr_proj_view", "Projected\nView", "A view projected from another one: pick the view, move to a side, click", lambda: self.open_command("projected")),
            "|",
            ("sheet", "dr_sheet", "Sheet\nSetup", "The size of the sheet (standard sizes), landscape or portrait, third or first angle", lambda: self.sheet_dialog()),
            ("fit", "dr_fit", "Fit to\nWindow", "Show the whole sheet", lambda: self.canvas.fit()),
            "|",
            ("turn_left", "dr_turn_left", "Turn\nLeft 90\u00b0", "Turn the selected view 90 degrees to the left on the sheet, like a sheet of paper.  Its dimensions, balloons and notes with leaders turn with it; press again to go on",
             lambda: self.turn_selected(1)),
            ("turn_right", "dr_turn_right", "Turn\nRight 90\u00b0", "Turn the selected view 90 degrees to the right on the sheet, like a sheet of paper.  Its dimensions, balloons and notes with leaders turn with it; press again to go on",
             lambda: self.turn_selected(-1)),
            "|",
            ("refresh", "dr_refresh", "Refresh\nViews", "Draw the lines of every view again from its model", lambda: self.refresh_views()),
            ("delete", "dr_delete", "Delete", "Delete the selected view or the selected dimension, note, balloon or drawn line", lambda: self.delete_selected()),
            "|",
            ("save", "dr_save", "Save", "Save the drawing (.opdraw)", lambda: self.save()),
            ("pdf", "dr_pdf", "Export\nPDF", "Write the sheet as a PDF at its true paper size", lambda: self.export_pdf_dialog()),
            "|",
            ("undo", "dr_undo", "Undo", "Undo the last change", lambda: self.do_undo()),
            ("redo", "dr_redo", "Redo", "Redo", lambda: self.do_redo()),
        ]), "View Layout")
        self.ribbon.addTab(self.ribbon_page([
            ("dim", "dr_dim", "Dimension", "Pick the type (Horizontal, Vertical, Length / distance, Diameter, Radius, Angle), click what it measures, then click where it goes",
             lambda t: self.start_tool("dim", t), [(label, key) for key, label in A.DIM_TYPES]),
            ("note", "dr_note", "Note", "Text on the sheet, with or without a leader (straight or bent, with an arrow)", lambda: self.start_tool("note")),
            ("balloon", "dr_balloon", "Balloon", "A circle with a number and a leader to an edge or a face of a view", lambda: self.start_tool("balloon")),
            "|",
            ("center_mark", "dr_center_mark", "Center\nMark", "A cross at the middle of a circle or an arc", lambda: self.start_tool("center_mark")),
            ("centerline", "dr_centerline", "Centerline", "A dash-dot line along the axis between two lines", lambda: self.start_tool("centerline")),
            "|",
            ("note_pattern", "dr_note_pattern", "Linear Note\nPattern", "Repeat a note along a direction: the spacing and how many, in one or two directions", lambda: self.start_tool("note_pattern")),
        ]), "Annotation")
        self.ribbon.addTab(self.ribbon_page([
            ("select", "dr_select", "Select", "Pick and move things (ends the tool that is open)", lambda: self.finish_tool()),
            ("line", "dr_draw_line", "Line", "Draw a line on the sheet", lambda: self.start_tool("line")),
            ("rect", "dr_draw_rect", "Rectangle", "Draw a rectangle on the sheet", lambda: self.start_tool("rect")),
            ("circle", "dr_draw_circle", "Circle", "Draw a circle on the sheet", lambda: self.start_tool("circle")),
            ("arc", "dr_draw_arc", "Arc", "Draw an arc on the sheet: the centre, the start, the end", lambda: self.start_tool("arc")),
        ]), "Sketch")
        self.ribbon.setCurrentIndex(0)
        for k in TOOL_KEYS + ("select",):
            self.act[k].setCheckable(True)
        self.act["select"].setChecked(True)
        # ---- the left column: Outline + Details, and the property panel of the command that is open
        self.left = QTabWidget()
        self.left.setTabPosition(QTabWidget.TabPosition.North)
        self.left.setIconSize(QSize(26, 26))
        self.outline = PN.OutlinePanel(self)
        self.left.addTab(self.outline, I.icon("dr_sheet", 26), "")
        self.left.setTabToolTip(0, "Outline: the sheet, the models and the views, with their details")
        self.props = QStackedWidget()
        self.model_panel = PN.ModelViewPanel(self)
        self.proj_panel = PN.ProjectedPanel(self)
        self.tool_panel = PN.ToolPanel(self)
        self.props.addWidget(QLabel("  Pick a command from the ribbon."))
        self.props.addWidget(self.model_panel)
        self.props.addWidget(self.proj_panel)
        self.props.addWidget(self.tool_panel)
        self.left.addTab(self.props, I.icon("dr_model_view", 26), "")
        self.left.setTabToolTip(1, "Properties of the command that is open")
        self.left.setMinimumWidth(340)
        self.left.setMaximumWidth(460)
        root.addWidget(self.left, 0)
        # ---- the sheet
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        rl.addWidget(self.ribbon)
        bar = QWidget()
        bar.setObjectName("hintbar")
        bar.setStyleSheet("#hintbar{background:#cfd9ea; border:none;}")          # the strip above the sheet: the same blue as the Part window's, it says what to do next
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(8, 3, 8, 3)
        self.hint_lbl = QLabel("")
        self.hint_lbl.setStyleSheet("color:#1d2a44;")
        self.hint_lbl.setMinimumWidth(100)                   # a long hint is cut short in a narrow window; it never pushes the window wider
        bl.addWidget(self.hint_lbl, 1)
        bar.setFixedHeight(26)
        rl.addWidget(bar)
        rl.addWidget(self.canvas, 1)
        foot = QWidget()
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(0)
        self.status = ui_kit.StatusLine("")
        fl.addWidget(self.status, 1)
        self.sheet_lbl = QLabel("")
        self.sheet_lbl.setStyleSheet("color:#6a7790; padding:2px 8px;")
        self.sheet_lbl.setMinimumWidth(240)                  # the text changes with the selected view: it never pushes the window wider
        self.coord_lbl = QLabel("")
        self.coord_lbl.setStyleSheet("color:#6a7790; padding:2px 8px;")
        self.coord_lbl.setMinimumWidth(150)
        fl.addWidget(self.sheet_lbl)
        fl.addWidget(self.coord_lbl)
        rl.addWidget(foot)
        root.addWidget(right, 1)
        self.canvas.selection_changed.connect(self.on_selection)
        self.canvas.changed.connect(self.on_canvas_changed)
        self.canvas.hint.connect(self.set_hint)
        self.canvas.coords.connect(lambda x, y: self.coord_lbl.setText(f"x {x:.1f}   y {y:.1f} mm"))
        self.canvas.placing.connect(lambda on: self.model_panel.clear_pick() if not on else None)
        self.canvas.annot_selected.connect(self.on_annot_selected)
        self.canvas.tool_changed.connect(self.on_tool_changed)
        self.canvas.edit_requested.connect(self.edit_item_text)
        self.canvas.direction_picked.connect(self.pattern_direction)
        for seq, fn in (("Ctrl+Z", self.do_undo), ("Ctrl+Y", self.do_redo), ("Ctrl+Shift+Z", self.do_redo)):
            QShortcut(QKeySequence(seq), self, activated=fn, context=Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.set_hint("Open Model View to put a view of a part or an assembly on the sheet.")

    def ribbon_page(self, items):
        page = QWidget()
        lay = QHBoxLayout(page)
        lay.setContentsMargins(6, 2, 6, 2)
        lay.setSpacing(2)
        for it in items:
            if it == "|":
                f = QFrame()
                f.setFrameShape(QFrame.Shape.VLine)
                f.setFrameShadow(QFrame.Shadow.Sunken)
                lay.addWidget(f)
                continue
            key, icon_key, text, tip, fn = it[:5]
            menu = it[5] if len(it) > 5 else None                    # a button that opens a menu of choices: fn(choice) for the one picked
            b = QToolButton()
            b.setText(text)
            b.setIcon(I.icon(icon_key, 36))
            b.setIconSize(QSize(36, 36))
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            b.setToolTip(tip or text.replace("\n", " "))
            b.setAutoRaise(True)
            b.setMinimumWidth(66)
            b.setMinimumHeight(70)
            b.setStyleSheet(RIBBON_QSS)
            if fn is None:
                b.setEnabled(False)
                b.setToolTip((tip or text.replace("\n", " ")) + " (not built yet)")
            elif menu:
                m = QMenu(b)
                for label, choice in menu:
                    act = m.addAction(I.icon(PN.DIM_ICON.get(choice, icon_key), 20), label)
                    act.triggered.connect(lambda _c=False, f=fn, v=choice: f(v))
                b.setMenu(m)
                b.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            else:
                b.clicked.connect(lambda _c=False, f=fn: f())
            if key:
                self.act[key] = b
            lay.addWidget(b)
        lay.addStretch(1)
        sc = QScrollArea()
        sc.setWidget(page)
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        sc.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        return sc

    def set_hint(self, text):
        self.hint_lbl.setText(text or ("Select a view to move it, or open a command from the ribbon." if self.d.views else
                                       "Open Model View to put a view of a part or an assembly on the sheet."))

    # ------------------------------------------------------------------------------------------------------------------------ the document, undo, dirty
    def commit(self, what=""):
        """The document changed (a person did something): it can be undone, the file is dirty, everything that shows it is brought up to date."""
        self.undo_stack.append(self.state)
        del self.undo_stack[:-UNDO_LIMIT]
        self.redo_stack.clear()
        self.state = self.d.snapshot()
        self.version += 1
        self.after_change()

    def after_change(self, reset=False):
        self.outline.rebuild()
        self.model_panel.refresh()
        self.canvas.refresh(reset=reset)
        if getattr(self, "tool_panel", None) is not None and self.canvas.tool == "note_pattern":
            self.tool_panel.sync()
        w, h = self.d.sheet_dims()
        s = S.size(self.d.sheet["size"])[1].split("  ")[0]
        self.sheet_text = f"{s}   {'landscape' if self.d.sheet['landscape'] else 'portrait'}   {'1st' if self.d.sheet['first_angle'] else '3rd'} angle"
        self.show_sheet_label()
        self.proj_panel.show_view()
        for k in ("undo", "redo"):
            if k in self.act:
                self.act[k].setEnabled(bool(self.undo_stack if k == "undo" else self.redo_stack))
        if "delete" in self.act:
            self.act["delete"].setEnabled(self.canvas.sel is not None or self.canvas.sel_annot is not None)
        self.update_turn_buttons()

    def update_turn_buttons(self):
        """The two Turn buttons work on the selected view (not while a view is still being placed)."""
        v = next((v for v in self.d.views if v["id"] == self.canvas.sel), None)
        on = v is not None and v["kind"] == "model" and self.canvas.mode == "select"
        for k in ("turn_left", "turn_right"):
            if k in self.act:
                self.act[k].setEnabled(on)

    def show_sheet_label(self):
        """The strip under the sheet: the sheet, and the style and the scale of the selected view (there is no scale of the sheet: every view has its own)."""
        v = next((v for v in self.d.views if v["id"] == self.canvas.sel), None)
        extra = f"   {v['name']}  {M.scale_text(v['scale'])}" if v is not None else ""
        self.sheet_lbl.setText(getattr(self, "sheet_text", "") + extra)

    def do_undo(self):
        self.canvas.tool_end()
        if self.canvas.mode != "select":
            self.canvas.end_place()
        if not self.undo_stack:
            return False
        self.redo_stack.append(self.state)
        self.state = self.undo_stack.pop()
        self.d.restore(self.state)
        self.version += 1
        self.after_change(reset=True)
        return True

    def do_redo(self):
        self.canvas.tool_end()
        if self.canvas.mode != "select" or not self.redo_stack:
            return False
        self.undo_stack.append(self.state)
        self.state = self.redo_stack.pop()
        self.d.restore(self.state)
        self.version += 1
        self.after_change(reset=True)
        return True

    def is_dirty(self):
        return self.version != self.saved_version

    def title(self):
        return os.path.basename(self.path) if self.path else self.title_text

    def can_close(self):
        return True

    def shutdown(self):
        self.canvas.tool_end(emit=False)
        self.canvas.end_place(emit=False)

    def guard(self, fn, *args, **kw):
        """Runs an edit of the document; a message that says what is wrong (a model that cannot be built, a scale that is not a number) goes to the status line.  -> (True, result)."""
        try:
            return True, fn(*args, **kw)
        except (M.DrawingError, G.GeometryError) as ex:
            self.status.say(str(ex), "bad")
            return False, None

    # ------------------------------------------------------------------------------------------------------------------------ the shell's questions
    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_S and ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.save()
            ev.accept()
            return
        super().keyPressEvent(ev)

    def showEvent(self, ev):
        super().showEvent(ev)
        if self.ASK_SHEET and not self.asked:
            self.asked = True
            QTimer.singleShot(0, lambda: self.sheet_dialog(first=True))

    # ------------------------------------------------------------------------------------------------------------------------ files
    def open_path(self, path):
        try:
            with open(path, encoding="utf-8") as f:
                d = M.Drawing.from_json(f.read())
        except (OSError, M.DrawingError) as ex:
            self.status.say(f"Couldn't open {os.path.basename(path)}: {ex}", "bad")
            return False
        self.d = d
        self.canvas.d = d
        self.canvas.r.d = d
        self.canvas.r.cache.clear()
        self.path = path
        self.asked = True
        self.undo_stack, self.redo_stack = [], []
        self.state = d.snapshot()
        self.version = self.saved_version = 0
        self.after_change(reset=True)
        self.canvas.fit()
        self.status.say(f"Opened {path}", "good")
        return True

    def save(self, as_new=False):
        self.canvas.tool_end()
        self.canvas.end_place()
        if not self.path or as_new:
            p, _ = QFileDialog.getSaveFileName(self, "Save drawing", self.path or "drawing" + M.EXT, FILTER)
            if not p:
                return False
            if not p.lower().endswith(M.EXT):
                p += M.EXT
            self.path = p
        return self.save_to(self.path)

    def save_to(self, path):
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.d.to_json())
        except OSError as ex:
            self.status.say(f"Couldn't save: {ex}", "bad")
            return False
        self.path = path
        self.saved_version = self.version
        self.status.say(f"Saved {path}", "good")
        return True

    def export_pdf_dialog(self):
        base = os.path.splitext(self.title())[0] + ".pdf"
        p, _ = QFileDialog.getSaveFileName(self, "Export PDF", base, "PDF (*.pdf)")
        if not p:
            return None
        if not p.lower().endswith(".pdf"):
            p += ".pdf"
        return self.export_pdf(p)

    def export_pdf(self, path):
        self.canvas.tool_end()
        self.canvas.end_place()
        try:
            dr_pdf.export_pdf(self.d, path)
        except OSError as ex:
            self.status.say(f"Couldn't export: {ex}", "bad")
            return None
        w, h = self.d.sheet_dims()
        self.status.say(f"Exported {path}  ({S.inch_text(w, h)} sheet, vector lines)", "good")
        return path

    # ------------------------------------------------------------------------------------------------------------------------ the sheet
    def sheet_dialog(self, first=False):
        dlg = PN.NewDrawingDialog(self.d.sheet, self, title="New drawing" if first else "Sheet setup", ok_text="Create" if first else "OK")
        if dlg.exec():
            r = dlg.result_sheet()
            if first:                                      # the start of the drawing: nothing to undo back to (but a sheet that is not the default is a change to keep)
                differs = r != self.d.sheet
                self.d.set_sheet(r["size"], r["landscape"], r["first_angle"])
                self.state = self.d.snapshot()
                if differs:
                    self.version += 1
                self.after_change()
                self.canvas.fit()
            else:
                self.set_sheet(r["size"], r["landscape"], r["first_angle"])

    def set_sheet(self, size, landscape, first_angle):
        old = dict(self.d.sheet)
        ok, _ = self.guard(self.d.set_sheet, size, landscape, first_angle)
        if not ok:
            return False
        if old == self.d.sheet:
            return True
        self.canvas.r.cache.clear()
        self.commit("sheet")
        self.canvas.fit()
        return True                                                    # (third or first angle changes the next projected view; the views on the sheet are views of their own)

    # ------------------------------------------------------------------------------------------------------------------------ models
    def source_text(self, m):
        if m.get("file"):
            return f"The file {os.path.basename(m['file'])}"
        if m.get("src"):
            return "A block of the Workbench project, wired into this one"
        return "A copy kept in this drawing"

    def add_model_file(self, path=None):
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, "Add a part or an assembly", "", "Part or assembly (*.gpd *.gpa);;All files (*)")
            if not path:
                return None
        name = os.path.splitext(os.path.basename(path))[0]
        try:
            if path.lower().endswith(".gpa"):
                import asm_embed
                text, _warns = asm_embed.self_contained_text(path)
                data, kind = json.loads(text), "assembly"
            else:
                with open(path, encoding="utf-8") as f:
                    data, kind = json.load(f), "part"
        except Exception as ex:                                  # noqa: BLE001 (a file that is not a part or an assembly)
            self.status.say(f"Couldn't read {os.path.basename(path)}: {ex}", "bad")
            return None
        mid = self.d.add_model(name, kind, data)
        self.d.model(mid)["file"] = path
        self.commit("model")
        self.status.say(f"Added {name}.", "good")
        return mid

    def sync_models(self, items):
        """A Drawing block of the Workbench: `items` = [{"src", "name", "kind", "data"}], what is wired into the block now (Drawing.sync_models).  A change is one undo step.
        -> {"added", "refreshed", "removed", "failed": [(name, message)]}."""
        out = self.d.sync_models(items)
        if out["added"] or out["refreshed"] or out["removed"]:
            self.canvas.r.cache.clear()
            self.commit("models")
        if out.get("lost"):
            self.status.say(self.lost_text(out["lost"]), "warn")
        return out

    @staticmethod
    def lost_text(n):
        return f"{n} dimension{'s' if n != 1 else ''} / mark{'s' if n != 1 else ''} lost their geometry: it is not in the model any more (shown in red in the Outline).  Delete them, or change the model back."

    def remove_model(self, mid):
        if mid is None:
            return
        ok, _ = self.guard(self.d.remove_model, mid)
        if ok:
            self.canvas.r.cache.clear()
            self.commit("remove model")

    def refresh_views(self):
        n = 0
        for v in [v for v in self.d.views if v["kind"] == "model"]:
            ok, _ = self.guard(self.d.reproject, v)
            n += 1 if ok else 0
        self.canvas.r.cache.clear()
        self.commit("refresh")
        lost = len(self.d.lost_annots())
        self.status.say((f"Drew {n} view{'s' if n != 1 else ''} again from the models." if n else "There is no view to refresh.") + (("  " + self.lost_text(lost)) if lost else ""),
                        "warn" if lost else "info")

    # ------------------------------------------------------------------------------------------------------------------------ commands (Model View, Projected View)
    def open_command(self, name):
        self.canvas.tool_end()
        self.canvas.end_place(emit=False)
        self.cmd = name
        if name == "model":
            if not self.d.models:
                self.status.say("There is no part or assembly in the drawing yet. " + ("Wire one into this block in the Workbench." if self.models_from_wires else
                                                                                       "Use Add from file to bring one in."), "warn")
            self.model_panel.refresh()
            self.props.setCurrentWidget(self.model_panel)
            self.left.setCurrentIndex(1)
            self.set_hint("Pick a part or assembly, then an orientation; the view follows the pointer: click on the sheet to put it down.")
        else:
            self.props.setCurrentWidget(self.proj_panel)
            self.left.setCurrentIndex(1)
            sel = self.canvas.sel
            view = next((v for v in self.d.views if v["id"] == sel), None)
            self.proj_panel.set_parent(view)
            if view is not None:
                self.start_projected(view["id"])
            else:
                self.set_hint("Click the view on the sheet that the new view is projected from.")
        for k in ("model", "projected"):
            self.act[k].setDown(False)

    def start_tool(self, name, dim_type=None):
        """An Annotation or Sketch tool: Dimension (dim_type: "h" "v" "a" "dia" "rad" "ang" - the person picks it in the menu of the button or in the panel), Center Mark, Centerline (the
        pointer picks things on the views), Note, Balloon, Line, Rectangle, Circle, Arc."""
        self.cmd = None
        self.model_panel.clear_pick()
        self.canvas.end_place(emit=False)
        self.tool_panel.set_tool(name)
        self.props.setCurrentWidget(self.tool_panel)
        self.left.setCurrentIndex(1)
        if not self.d.views and name in NEEDS_VIEW:
            self.status.say("There is no view on the sheet yet: " + ("a balloon points at a view." if name == "balloon" else "there is nothing to pick."), "warn")
        self.canvas.tool_begin(name, dim_type)
        self.tool_panel.sync()
        self.canvas.setFocus()
        for k in TOOL_KEYS:
            self.act[k].setChecked(k == name)
        self.act["select"].setChecked(False)

    def finish_tool(self):
        self.canvas.tool_end()

    def on_tool_changed(self, name):
        for k in TOOL_KEYS:
            self.act[k].setChecked(k == name)
        self.act["select"].setChecked(name is None)
        if name is None and self.props.currentWidget() is self.tool_panel:
            self.props.setCurrentIndex(0)
            self.left.setCurrentIndex(0)
        self.set_hint("" if name is None else self.canvas.TOOL_HINT.get(name, ""))

    def on_annot_selected(self, aid):
        self.outline.select_annot(aid)
        if "delete" in self.act:
            self.act["delete"].setEnabled(aid is not None or self.canvas.sel is not None)

    def delete_selected(self):
        if self.canvas.sel_annot:
            self.delete_annot(self.canvas.sel_annot)
        else:
            self.delete_view(self.canvas.sel)

    def delete_annot(self, aid):
        if not aid:
            return
        ok, _ = self.guard(self.d.remove_annot, aid)
        if ok:
            if self.canvas.sel_annot == aid:
                self.canvas.sel_annot = None
            self.commit("annot_delete")

    def finish_command(self, ok=True):
        self.canvas.end_place()
        self.cmd = None
        self.model_panel.clear_pick()
        self.props.setCurrentIndex(0)
        self.left.setCurrentIndex(0)
        self.set_hint("")

    def start_model_view(self, mid, orient, style, scale_text):
        self.canvas.end_place(emit=False)
        scale = None
        if scale_text:
            ok, scale = self.guard(M.parse_scale, scale_text)
            if not ok:
                return None
        x, y = self.canvas.cursor_mm or (self.d.sheet_dims()[0] / 2.0, self.d.sheet_dims()[1] / 2.0)
        ok, v = self.guard(self.d.add_view, mid, orient, (x, y), scale, style)
        if not ok:
            return None
        self.canvas.begin_model(v["id"])
        self.after_change()
        self.canvas.setFocus()
        return v["id"]

    def start_projected(self, parent_id):
        self.canvas.proj_style = self.proj_panel.style_choice()
        self.canvas.proj_scale = self.proj_panel.scale_choice()
        self.canvas.begin_projected(parent_id)
        self.proj_panel.set_parent(self.d.view(parent_id))
        self.canvas.setFocus()

    def on_selection(self, vid):
        self.outline.select_view(vid)
        self.model_panel.show_view()
        self.proj_panel.show_view()
        self.show_sheet_label()
        self.update_turn_buttons()
        if "delete" in self.act:
            self.act["delete"].setEnabled(vid is not None)
        if self.cmd == "projected" and vid and self.canvas.mode == "select":
            self.start_projected(vid)

    def on_canvas_changed(self, what):
        if what in ("place", "move", "delete", "dim", "mark", "annot_move", "annot_delete", "note", "balloon", "draw", "pattern"):
            self.commit(what)
        elif what == "place_end":
            self.after_change()

    # ------------------------------------------------------------------------------------------------------------------------ notes and balloons
    def ask_text(self, title, label, text, multiline=False):
        """Asks for a text in a small dialog; None when it was cancelled (a test replaces this)."""
        if multiline:
            v, ok = QInputDialog.getMultiLineText(self, title, label, text)
        else:
            v, ok = QInputDialog.getText(self, title, label, text=text)
        return v if ok else None

    def edit_item_text(self, aid):
        """A note or a balloon was double-clicked: ask for its text."""
        try:
            a = self.d.annot(aid)
        except M.DrawingError:
            return
        if a.get("type") == "note":
            v = self.ask_text("Note", "Text of the note", a["text"], True)
            if v is not None:
                self.set_note(aid, v, None, (a.get("leader") or {}).get("kind"))
        elif a.get("type") == "balloon":
            v = self.ask_text("Balloon", "Number in the balloon", a["text"], False)
            if v is not None:
                self.set_balloon_text(aid, v)

    def set_note(self, aid, text, size, leader):
        """The text, the size (points) or the leader (None, "straight", "bent") of a note changed (the Details, the dialog)."""
        try:
            n = self.d.annot(aid)
        except M.DrawingError:
            return
        cur = (n.get("leader") or {}).get("kind")
        new_text = None if text is None or text == n["text"] else text
        new_size = None if size is None or abs(IT.clean_size(size) - n.get("size", IT.NOTE_SIZE)) < 1e-9 else size
        lead = False if leader == cur else leader
        if new_text is None and new_size is None and lead is False:
            return
        ok, _ = self.guard(self.d.set_note, aid, new_text, new_size, lead)
        if ok:
            self.commit("note")
        else:
            self.after_change()                                      # the boxes show what the note says again

    def set_note_pattern(self, aid, remove=False, **fields):
        """The Linear Note Pattern of a note changed (a1, s1, c1 / a2, s2, c2, or remove=True; the panels)."""
        try:
            n = self.d.annot(aid)
        except M.DrawingError:
            return
        cur = n.get("pattern")
        if remove and not cur:
            return
        if not remove and cur and all(abs(float(cur[k]) - float(v)) < 1e-9 for k, v in fields.items()):
            return
        ok, _ = self.guard(self.d.set_pattern, aid, remove, **fields)
        if ok:
            self.commit("pattern")
        else:
            self.after_change()

    def pattern_direction(self, which, angle):
        """A line of a view was clicked to give the direction `which` of the pattern of the note the tool works on."""
        aid = self.canvas.pattern_note
        if aid is not None:
            self.set_note_pattern(aid, **{"a%d" % which: round(angle, 2)})

    def set_balloon_text(self, aid, text):
        try:
            b = self.d.annot(aid)
        except M.DrawingError:
            return
        if (text or "").strip() == b["text"]:
            return
        ok, _ = self.guard(self.d.set_balloon_text, aid, text)
        if ok:
            self.commit("balloon")
        else:
            self.after_change()

    # ------------------------------------------------------------------------------------------------------------------------ what the Details change
    def select_view(self, vid):
        self.canvas.set_selected(vid)

    def rename_view(self, vid, name):
        name = (name or "").strip()
        v = self.d.view(vid)
        if not name or name == v["name"]:
            return
        v["name"] = name
        self.commit("rename")

    def delete_view(self, vid):
        if not vid:
            return
        if self.canvas.mode != "select":
            self.canvas.end_place()
        ok, _ = self.guard(self.d.remove_view, vid)
        if ok:
            self.canvas.sel = None
            self.canvas.r.cache.pop(vid, None)
            self.commit("delete")

    # ---- the style buttons and the scale field of the Model View and Projected View panels: they change ONE view
    def panel_view(self, kind):
        """The view that the buttons and the scale field of the Model View panel (kind "model") or of the Projected View panel ("projected") change: the view that follows the pointer, or the
        selected one.  None: the next view (the panel keeps what it starts with)."""
        v = next((v for v in self.d.views if v["id"] == self.canvas.sel), None)
        if v is None:
            return None
        if kind == "projected":                                  # the view on the pointer, or the one just put down by this command (it is a view of its own, a model view, from then on)
            if v["kind"] == "projected":
                return v if v["parent"] == self.canvas.proj_parent else None      # (the view that the new ones are projected from is selected, not one of theirs)
            return v if self.canvas.mode == "projected" and v["id"] == self.canvas.last_placed else None
        return v if v["kind"] == kind else None

    def panel_style(self, kind, style):
        """A style button of a panel was clicked (style None for a projected view: its parent's)."""
        if kind == "projected":
            self.canvas.proj_style = self.proj_panel.style_choice()
            self.update_ghost()
        v = self.panel_view(kind)
        if v is None:
            return
        if style is None:
            style = self.d.view(v["parent"] or self.canvas.proj_parent)["style"]
        if v["id"] == self.canvas.float_id:                      # still on the pointer: it is not in the undo list yet, it is put down with this style
            self.guard(self.d.set_style, v["id"], style)
            self.canvas.update()
        else:
            self.set_view_style(v["id"], style)

    def panel_scale(self, kind, text):
        """The scale field of a panel was edited."""
        text = (text or "").strip()
        if text:
            try:
                M.parse_scale(text)
            except M.DrawingError as ex:
                self.status.say(str(ex), "bad")
                return
        if kind == "projected":
            self.canvas.proj_scale = self.proj_panel.scale_choice()
            self.update_ghost()
        v = self.panel_view(kind)
        if v is None or not text:
            return
        if v["id"] == self.canvas.float_id:
            if abs(v["scale"] - M.parse_scale(text)) > 1e-12:
                self.guard(self.d.set_scale, v["id"], text)
                self.canvas.r.cache.clear()
                self.canvas.update()
        else:
            self.set_view_scale(v["id"], text)

    def update_ghost(self):
        """The projected view that follows the pointer takes the style and the scale set in the panel (the parent's where it sets none)."""
        g, par = self.canvas.float_id, self.canvas.proj_parent
        if self.canvas.mode != "projected" or g is None or par is None:
            return
        pv = self.d.view(par)
        self.guard(self.d.set_style, g, self.canvas.proj_style or pv["style"])
        self.guard(self.d.set_scale, g, self.canvas.proj_scale or pv["scale"])
        self.canvas.r.cache.clear()
        self.canvas.update()

    def set_view_style(self, vid, style):
        if self.d.view(vid)["style"] == style:
            return
        ok, _ = self.guard(self.d.set_style, vid, style)
        if ok:
            self.commit("style")

    def turn_selected(self, quarters):
        if self.canvas.mode != "select":
            return
        v = next((v for v in self.d.views if v["id"] == self.canvas.sel), None)
        if v is None:
            self.status.say("Select a view first: click it on the sheet.", "warn")
            return
        self.turn_view(v["id"], quarters)

    def turn_view(self, vid, quarters):
        """Turns a view on the sheet a quarter to the left (+1) or to the right (-1); what is fixed to the view turns with it (DRW-1)."""
        ok, v = self.guard(self.d.turn_view, vid, quarters)
        if not ok:
            return
        self.canvas.r.cache.clear()
        self.commit("turn")
        lost = len(self.d.lost_annots())
        tt = M.TURN_TEXT[int(v.get("turn", 0)) % 4]
        if lost:
            self.status.say(self.lost_text(lost), "warn")
        else:
            self.status.say(f"{v['name']} is {tt}." if tt else f"{v['name']} is the way up it started.", "info")

    def set_view_orient(self, vid, name):
        v = self.d.view(vid)
        if name not in P.ORIENTATIONS:                                 # ("Custom" is what a view shows that looks along none of the nine: nothing to set)
            return
        if v["orient"] == name:
            if int(v.get("turn", 0)) % 4:                              # the same orientation again turns the view back upright (what is on the view turns back with it)
                self.turn_view(vid, -int(v["turn"]))
            return
        had = len(self.d.annots()) + len(self.d.balloons)
        ok, _ = self.guard(self.d.set_orient, vid, name)
        if ok:
            self.canvas.r.cache.clear()
            self.commit("orientation")
            gone = had - len(self.d.annots()) - len(self.d.balloons)
            if gone:
                self.status.say(f"The view looks another way now: its {gone} dimension{'s' if gone != 1 else ''} / mark{'s' if gone != 1 else ''} / balloon{'s' if gone != 1 else ''} had nothing to hold on to and {'were' if gone != 1 else 'was'} removed (Undo brings {'them' if gone != 1 else 'it'} back).", "warn")

    def set_view_scale(self, vid, text):
        try:
            s = M.parse_scale(text)
        except M.DrawingError as ex:
            self.status.say(str(ex), "bad")
            self.after_change()
            return
        if abs(self.d.view(vid)["scale"] - s) < 1e-12:
            return
        ok, _ = self.guard(self.d.set_scale, vid, s)
        if ok:
            self.canvas.r.cache.clear()
            self.commit("scale")


def make_tab(path=None):
    return DrawingTab(path)
