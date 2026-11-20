"""
sh_tab.py - the Sheets tab: a ribbon (Home, Data, Charts, Images, Engineering), the name box and formula bar, the grid, the sheet tabs and a status line.

Files: .opsheet (JSON, the whole workbook with its charts and study links).  Excel files (.xlsx) open into a new workbook and export from the Data tab.
"""
import json
import os
import threading

from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtWidgets import (QApplication, QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox, QProgressDialog,
                             QPushButton, QScrollArea, QSizePolicy, QSplitter, QTabBar, QTabWidget, QToolButton, QVBoxLayout, QWidget)

import sh_book as B
import sh_chart
import sh_deps
import sh_dialogs as D
import sh_edit
import sh_engine as E
import sh_fmt
import sh_grid
import sh_picture
import sh_prefs
import sh_presets
import sh_ribbon
import sh_std
import sh_study
import sh_xlsx
import std_aisi16
import ui_kit

FILTER = "Sheets workbook (*.opsheet);;All files (*)"
OPEN_FILTER = "Sheets and Excel files (*.opsheet *.xlsx);;Sheets workbook (*.opsheet);;Excel workbook (*.xlsx);;All files (*)"
CHIP = "#1d7a45"
RIBBON_QSS = ("QToolButton{padding:2px;} QToolButton:disabled{color:#a0a0a0;} "
              "QToolButton:checked{background:#cfe3fb; border:1px solid #6aa0e0;} QToolButton::menu-indicator{image:none;}")


def start_standards():
    """Registers the standards that come with Sheets (once) and the ones other add-ons offer."""
    if "aisi-s100-16" not in sh_std.PACKS:
        std_aisi16.register()
    sh_std.load_hooks()


class SheetsTab(QWidget):
    AUTO_DOWNLOAD = True                       # ask to download openpyxl when an Excel file is used (a test turns this off)
    installer = None                           # a test can put its own downloader here (see sh_deps.install)

    def __init__(self, path=None):
        super().__init__()
        start_standards()
        self.host = None
        self.path = None
        self.title_text = "Sheets"
        self.wb = B.Workbook()
        self.saved_version = self.wb.version
        self.extra_dirty = False
        self.dialogs = []                       # windows that stay open next to the grid
        self.panel = None                       # the chart panel to the right of the grid (made when it is first needed)
        self.pic_panel = None                   # the image panel in the same place (one of the two is open at a time)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.build_title())
        self.bar = sh_edit.FormulaEdit()
        self.grid = sh_grid.Grid(self.wb, self.bar)
        lay.addWidget(self.build_ribbon())
        lay.addWidget(self.build_formula_row())
        self.help = QLabel("")
        self.help.setTextFormat(Qt.TextFormat.RichText)
        self.help.setStyleSheet(f"color:{ui_kit.MUTED}; padding:1px 8px; font-size:11px;")
        self.help.setMinimumHeight(18)
        lay.addWidget(self.help)
        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.setChildrenCollapsible(False)
        self.split.setHandleWidth(5)
        self.split.addWidget(self.grid)
        self.split.setStretchFactor(0, 1)
        lay.addWidget(self.split, 1)
        lay.addWidget(self.build_bottom())
        self.wire()
        sh_prefs.on_change(self.prefs_changed)
        self.apply_ribbon_sizes()
        self.on_selection()
        self.wb.listeners.append(self.wb_changed)
        self.rebuild_sheet_tabs()
        if path and os.path.isfile(path):
            self.open_path(path)

    # ------------------------------------------------------------------ building the window
    def build_title(self):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(8, 5, 8, 3)
        h.addWidget(ui_kit.kind_chip("Sheets", CHIP))
        self.title_lbl = QLabel("Sheets")
        self.title_lbl.setStyleSheet(f"font-weight:600; color:{ui_kit.INK};")
        h.addWidget(self.title_lbl)
        h.addStretch(1)
        return w

    def build_formula_row(self):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(6, 3, 6, 3)
        h.setSpacing(4)
        self.name_box = QLineEdit()
        self.name_box.setFixedWidth(104)
        self.name_box.setToolTip("The selected cells. Type a cell (B7), a range (A1:C9) or a name to go there; a new name is defined for the selection.")
        self.name_box.returnPressed.connect(self.name_entered)
        h.addWidget(self.name_box)
        self.b_fx = QPushButton("fx")
        self.b_fx.setFixedWidth(34)
        self.b_fx.setToolTip("Insert or edit a function with its Function Arguments window")
        self.b_fx.clicked.connect(lambda _c=False: self.fx())
        h.addWidget(self.b_fx)
        self.bar.setPlaceholderText("")
        self.bar.setStyleSheet("QLineEdit { border:1px solid #c8d0de; border-radius:3px; padding:3px 5px; background:white; }"
                               "QLineEdit:focus { border:1px solid #2b7de9; }")
        h.addWidget(self.bar, 1)
        return w

    def build_bottom(self):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        self.tabbar = QTabBar()
        self.tabbar.setShape(QTabBar.Shape.RoundedSouth)
        self.tabbar.setMovable(True)
        self.tabbar.setExpanding(False)
        self.tabbar.setDrawBase(False)
        self.tabbar.currentChanged.connect(self.sheet_tab_changed)
        self.tabbar.tabMoved.connect(self.sheet_tab_moved)
        self.tabbar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabbar.customContextMenuRequested.connect(self.sheet_menu)
        self.tabbar.tabBarDoubleClicked.connect(lambda i: self.rename_sheet(i))
        h.addWidget(self.tabbar)
        b = QToolButton()
        b.setText("+")
        b.setToolTip("Add a sheet")
        b.setAutoRaise(True)
        b.clicked.connect(lambda _c=False: self.add_sheet())
        h.addWidget(b)
        self.status = ui_kit.StatusLine("")
        h.addWidget(self.status, 1)
        self.stats = QLabel("")
        self.stats.setStyleSheet(f"color:{ui_kit.MUTED}; padding:2px 10px;")
        h.addWidget(self.stats)
        return w

    # ------------------------------------------------------------------ the ribbon
    def build_ribbon(self):
        self.act = {}
        self.ribbon_buttons = []
        self.ribbon_captions = []
        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        self.ribbon = tabs
        sel = self.grid
        fmts = [("General", "General"), ("Number 0.00", "0.00"), ("Percent", "0%"), ("Scientific", "0.00E+00"), ("Currency", "$#,##0.00"),
                ("Thousands 1,234", "#,##0")]
        home = [
            ("File", [("new", "s_new", "New", "A new workbook in another tab", self.file_new), ("open", "s_open", "Open", "Open a .opsheet or an Excel file", self.open_dialog),
                      ("save", "s_save", "Save", "Save the workbook (Ctrl+S)", lambda: self.save()), ("save_as", "s_save_as", "Save as", "Save under a new name", lambda: self.save(True))]),
            ("Clipboard", [("paste", "s_paste", "Paste", "Paste (Ctrl+V)", sel.paste), ("paste_special", "s_paste_special", "Paste\nspecial", "Paste values, formulas or formats only", self.paste_special),
                           ("cut", "s_cut", "Cut", "Cut (Ctrl+X)", lambda: sel.copy(True)), ("copy", "s_copy", "Copy", "Copy (Ctrl+C)", lambda: sel.copy(False))]),
            ("Font", [("bold", "s_bold", "Bold", "Bold (Ctrl+B)", lambda: self.toggle("bold")), ("italic", "s_italic", "Italic", "Italic (Ctrl+I)", lambda: self.toggle("italic")),
                      ("fg", "s_fg", "Text\ncolour", "Colour of the text", lambda: self.pick_colour("fg")), ("bg", "s_bg", "Fill", "Fill colour", lambda: self.pick_colour("bg"))]),
            ("Number", [("menu", "s_number", "Number\nformat", "How the numbers show", [(t, (lambda _c=False, f=f: self.set_format(f))) for t, f in fmts] + [("More...", self.format_dialog)]),
                        ("dec_up", "s_dec_up", "More\ndecimals", "Show one more decimal", lambda: self.decimals(1)), ("dec_dn", "s_dec_dn", "Fewer\ndecimals", "Show one decimal less", lambda: self.decimals(-1))]),
            ("Cells", [("ins_row", "s_ins_row", "Insert\nrow", "Insert rows above the selection", lambda: self.insert("r")), ("ins_col", "s_ins_col", "Insert\ncolumn", "Insert columns left of the selection", lambda: self.insert("c")),
                       ("del_row", "s_del_row", "Delete\nrow", "Delete the selected rows", lambda: self.delete("r")), ("del_col", "s_del_col", "Delete\ncolumn", "Delete the selected columns", lambda: self.delete("c"))]),
            ("Editing", [("fill_down", "s_fill_down", "Fill\ndown", "Copy the top cell down (Ctrl+D)", sel.fill_down), ("fill_right", "s_fill_right", "Fill\nright", "Copy the left cell right (Ctrl+R)", sel.fill_right),
                         ("clear", "s_clear", "Clear", "Clear the selected cells (Delete)", sel.clear_selection), ("fit", "s_fit", "Fit\nwidth", "Make the columns fit what is in them", sel.autofit_selection),
                         ("undo", "s_undo", "Undo", "Undo (Ctrl+Z)", sel.undo), ("redo", "s_redo", "Redo", "Redo (Ctrl+Y)", sel.redo)]),
        ]
        data = [
            ("Study", [("study_in", "s_study_in", "Import\nstudy", "Bring a finished parametric study onto a sheet", self.study_import),
                       ("study_refresh", "s_study_refresh", "Refresh from\nstudy", "Read the study again; formulas next to it fill down", self.study_refresh),
                       ("study_select", "s_study_sel", "Select\nstudy", "Select all the cells of the imported study the cursor is on", self.study_select),
                       ("study_delete", "s_study_del", "Delete\nstudy", "Take the imported study off the sheet (Refresh no longer fills it)", self.study_delete)]),
            ("Excel", [("xl_in", "s_xl_in", "Import\n.xlsx", "Open an Excel workbook", self.import_xlsx_dialog), ("xl_out", "s_xl_out", "Export\n.xlsx", "Save as an Excel workbook", self.export_xlsx_dialog)]),
            ("Names", [("names", "s_names", "Names", "Names for cells and ranges (NumScrews)", self.names_dialog)]),
            ("Sheets", [("sh_add", "s_sh_add", "Add\nsheet", "Add a sheet", self.add_sheet), ("sh_dup", "s_sh_dup", "Copy\nsheet", "Copy the sheet", self.duplicate_sheet),
                        ("sh_del", "s_sh_del", "Delete\nsheet", "Delete the sheet", self.delete_sheet), ("sh_paste", "s_sh_paste", "Paste to\nsheets", "Copy the selected cells to the same place on other sheets", self.paste_to_sheets)]),
        ]
        charts = [
            ("Insert", [("ch_new", "s_ch_new", "Insert\nchart", "A chart from the selected cells, or an empty one that you fill from the panel on the right", self.chart_new)]),
            ("Chart", [("ch_edit", "s_ch_edit", "Edit\nchart", "Open the chart panel: data, series, look and advanced settings", self.chart_edit), ("ch_copy", "s_ch_copy", "Copy\nchart", "Duplicate the chart", self.chart_copy),
                       ("ch_export", "s_ch_export", "Export\nchart", "Save the chart as PNG, SVG or PDF", self.chart_export), ("ch_del", "s_ch_del", "Delete\nchart", "Remove the chart", self.chart_delete)]),
        ]
        images = [
            ("Insert", [("pic_new", "s_pic_new", "Insert\nimage", "Put a picture file (PNG, JPG ...) on the sheet at the selected cell. To bring in a screenshot, copy it and press Ctrl+V.", self.picture_new)]),
            ("Image", [("pic_edit", "s_pic_edit", "Edit\nimage", "Open the image panel: size", self.picture_edit), ("pic_copy", "s_pic_copy", "Copy\nimage", "Duplicate the image", self.picture_copy),
                       ("pic_export", "s_pic_export", "Export\nimage", "Save the image as a file", self.picture_export), ("pic_del", "s_pic_del", "Delete\nimage", "Remove the image", self.picture_delete)]),
        ]
        eng = [("Functions", [("fx", "s_fx", "Insert\nfunction", "Insert a function with its Function Arguments window", self.fx)]),
               ("Standards", self.standard_items()),
               ("Browse", [("std_select", "s_std_select", "Standard\nselect", "Browse every installed standard", lambda: self.standards(None))])]
        view = [("Ribbon", [("ribbon_size", "s_ribbon_size", "Ribbon\nsize", "Icon size and text size of the ribbon", self.ribbon_size_dialog)])]
        for title, groups in (("Home", home), ("Data", data), ("Charts", charts), ("Images", images), ("Engineering", eng), ("View", view)):
            tabs.addTab(self.ribbon_page(groups), title)
        QTimer.singleShot(0, self.apply_ribbon_sizes)
        return tabs

    def standard_items(self):
        out = []
        for p in sh_std.packs():
            short = p.short
            text = short.replace(" ", "\n", 1) if " " in short else short
            out.append((f"std_{p.id}", "s_std", text, f"{p.title} ({p.edition}, {p.publisher})", (lambda pid=p.id: self.standards(pid))))
        if not out:
            out.append(("std_none", "s_std", "No standards\ninstalled", "No engineering standard is installed", None))
        return out

    def ribbon_page(self, groups):
        page = QWidget()
        lay = QHBoxLayout(page)
        lay.setContentsMargins(6, 2, 6, 0)
        lay.setSpacing(0)
        icon_pt, text_pt = sh_prefs.get("ribbon_icon"), sh_prefs.get("ribbon_text")
        for gi, (caption, items) in enumerate(groups):
            if gi:
                f = QFrame()
                f.setFrameShape(QFrame.Shape.VLine)
                f.setFrameShadow(QFrame.Shadow.Sunken)
                lay.addWidget(f)
            box = QWidget()
            v = QVBoxLayout(box)
            v.setContentsMargins(4, 0, 4, 0)
            v.setSpacing(0)
            row = QHBoxLayout()
            row.setSpacing(2)
            for key, icon_key, text, tip, fn in items:
                b = sh_ribbon.RibbonButton(icon_key, text, icon_pt, text_pt)
                b.setToolTip(tip or text.replace("\n", " "))
                b.setAutoRaise(True)
                b.setStyleSheet(RIBBON_QSS)
                if key == "menu":
                    m = QMenu(b)
                    for label, f2 in fn:
                        m.addAction(label, lambda _c=False, f3=f2: f3())
                    b.setMenu(m)
                    b.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
                elif fn is None:
                    b.setEnabled(False)
                else:
                    b.clicked.connect(lambda _c=False, f2=fn: f2())
                if key in ("bold", "italic"):
                    b.setCheckable(True)
                self.act[key] = b
                self.ribbon_buttons.append(b)
                row.addWidget(b)
            v.addLayout(row)
            cap = QLabel(caption)
            cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cap.setStyleSheet(f"color:{ui_kit.FAINT};")
            self.ribbon_captions.append(cap)
            v.addWidget(cap)
            lay.addWidget(box)
        lay.addStretch(1)
        scroll = QScrollArea()                           # a ribbon that is wider than the window scrolls sideways
        scroll.setWidget(page)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet("QScrollBar:horizontal { height:8px; } QScrollArea { background:transparent; } ")
        page.setObjectName("ribbonpage")
        page.setStyleSheet("#ribbonpage { background:transparent; }")
        return scroll

    def apply_ribbon_sizes(self):
        """Icon size and text size from the settings, onto every button and caption; the ribbon grows or shrinks to fit."""
        icon_pt, text_pt = sh_prefs.get("ribbon_icon"), sh_prefs.get("ribbon_text")
        cap_pt = max(7, text_pt - 1)
        for b in self.ribbon_buttons:
            b.set_sizes(icon_pt, text_pt)
        for cap in self.ribbon_captions:
            f = cap.font()
            f.setPointSizeF(float(cap_pt))
            cap.setFont(f)
        self.ribbon.setFixedHeight(sh_ribbon.page_height(self.ribbon_buttons, cap_pt) + self.ribbon.tabBar().sizeHint().height() + 8)

    def prefs_changed(self, keys):
        if "ribbon_icon" in keys or "ribbon_text" in keys:
            self.apply_ribbon_sizes()

    def ribbon_size_dialog(self):
        sh_ribbon.RibbonSizeDialog(self).exec()

    # ------------------------------------------------------------------ wiring
    def wire(self):
        g = self.grid
        g.selection_changed.connect(self.on_selection)
        g.message.connect(lambda t, lv: self.status.say(t, lv))
        g.command.connect(self.run_command)
        g.charts_changed.connect(self.on_charts_changed)
        g.pictures_changed.connect(self.on_pictures_changed)
        g.edit_text.connect(self.on_edit_text)
        g.edit_started.connect(self.on_edit_started)
        g.edit_ended.connect(self.on_edit_ended)
        g.sheet_asked.connect(self.show_sheet)
        for e in (g.editor, self.bar):
            e.cursorPositionChanged.connect(lambda *_: self.update_help())
        self.bar.installEventFilter(self)

    def eventFilter(self, obj, ev):
        from PyQt6.QtCore import QEvent
        if obj is self.bar and ev.type() == QEvent.Type.FocusIn and self.grid.edit is None:
            QTimer.singleShot(0, self.start_bar_edit)
        return super().eventFilter(obj, ev)

    def start_bar_edit(self):
        if self.grid.edit is None and self.bar.hasFocus():
            pos = self.bar.cursorPosition()
            self.grid.begin_edit(None, enter_mode=False, focus="bar")
            self.bar.setCursorPosition(min(pos, len(self.bar.text())))

    def show_sheet(self, name):
        names = self.wb.sheet_names()
        if name in names:
            self.tabbar.setCurrentIndex(names.index(name))

    def run_command(self, name):
        arg = ""
        if ":" in name:
            name, arg = name.split(":", 1)
        fn = {"bold": lambda: self.toggle("bold"), "italic": lambda: self.toggle("italic"), "format": self.format_dialog, "paste_special": self.paste_special,
              "insert": lambda: self.insert("r"), "delete": lambda: self.delete("r"), "insert_row": lambda: self.insert("r"), "insert_col": lambda: self.insert("c"),
              "delete_row": lambda: self.delete("r"), "delete_col": lambda: self.delete("c"), "chart_new": self.chart_new, "col_width": self.col_width,
              "study_refresh": self.study_refresh, "study_select": self.study_select, "study_delete": self.study_delete, "chart_edit": lambda: self.chart_edit(arg), "chart_export": lambda: self.chart_export(arg),
              "chart_copy": lambda: self.chart_copy(arg), "picture_edit": lambda: self.picture_edit(arg), "picture_export": lambda: self.picture_export(arg),
              "picture_copy": lambda: self.picture_copy(arg)}.get(name)
        if fn:
            fn()

    # ------------------------------------------------------------------ keeping the window in step
    def wb_changed(self, changed, structure):
        if structure:
            self.rebuild_sheet_tabs()
        self.update_ribbon()
        self.update_titles()
        if structure:
            self.follow_pic_panel()                              # (a picture was put back, taken off, or another one is there after an undo)

    def mark_extra(self):
        self.extra_dirty = True
        self.update_titles()

    def is_dirty(self):
        return self.wb.version != self.saved_version or self.extra_dirty

    def update_titles(self):
        self.title_lbl.setText(self.title() + (" *" if self.is_dirty() else ""))          # (the program's tab strip follows by its own timer)

    def title(self):
        return os.path.basename(self.path) if self.path else self.title_text

    def sync_sheet_tab(self):
        """The grid can change the sheet by itself (a formula typed on one sheet was finished): the tab strip follows."""
        names = self.wb.sheet_names()
        i = names.index(self.grid.sheet) if self.grid.sheet in names else -1
        if i >= 0 and self.tabbar.currentIndex() != i and self.tabbar.count() == len(names):
            self.tabbar.blockSignals(True)
            self.tabbar.setCurrentIndex(i)
            self.tabbar.blockSignals(False)

    def on_selection(self):
        g = self.grid
        self.sync_sheet_tab()
        r1, c1, r2, c2 = g.sel()
        if g.edit is None:
            if (r1, c1) == (r2, c2) or g.sel_chart or g.sel_picture:
                self.name_box.setText(E.addr(g.r, g.c))
            else:
                self.name_box.setText(f"{E.addr(r1, c1)}:{E.addr(r2, c2)}")
            self.bar.blockSignals(True)
            self.bar.setText(B.edit_text(self.wb.cell(g.sheet, g.r, g.c)))
            self.bar.blockSignals(False)
            self.bar.setCursorPosition(0)
        self.update_ribbon()
        self.update_stats()
        self.update_help()
        self.follow_panel()
        self.follow_pic_panel()

    def update_stats(self):
        g = self.grid
        rects = g.rects()
        cells = sum((a[2] - a[0] + 1) * (a[3] - a[1] + 1) for a in rects)
        if cells < 2 or cells > 50000:
            self.stats.setText("")
            return
        seen = {(r, c) for a in rects for r in range(a[0], a[2] + 1) for c in range(a[1], a[3] + 1)}      # a cell in two blocks counts once
        vals = [v for v in (self.wb.value(g.sheet, r, c) for r, c in seen) if isinstance(v, float)]
        if not vals:
            self.stats.setText("")
            return
        self.stats.setText(f"Average {sum(vals) / len(vals):.6g}    Count {len(vals)}    Sum {sum(vals):.6g}")

    def update_ribbon(self):
        g = self.grid
        cell = self.wb.cell(g.sheet, g.r, g.c)
        st = cell.st if cell is not None else None
        for key, attr in (("bold", "bold"), ("italic", "italic")):
            b = self.act.get(key)
            if b is not None:
                b.blockSignals(True)
                b.setChecked(bool(st and getattr(st, attr)))
                b.blockSignals(False)
        self.act["undo"].setEnabled(self.wb.can_undo())
        self.act["redo"].setEnabled(self.wb.can_redo())
        s = self.wb.get_sheet(g.sheet)
        has_link = bool(s and s.links)
        for k in ("study_refresh", "study_select", "study_delete"):
            self.act[k].setEnabled(has_link)
        has_chart = bool(s and s.charts)
        for k in ("ch_edit", "ch_copy", "ch_export", "ch_del"):
            self.act[k].setEnabled(has_chart)
        has_pic = bool(s and s.pictures)
        for k in ("pic_edit", "pic_copy", "pic_export", "pic_del"):
            self.act[k].setEnabled(has_pic)
        self.act["sh_del"].setEnabled(len(self.wb.sheets) > 1)

    def on_edit_started(self):
        self.update_help()

    def on_edit_ended(self):
        self.on_selection()

    def on_edit_text(self, text):
        self.bar.blockSignals(True)
        if self.bar.text() != text:
            self.bar.setText(text)
        self.bar.blockSignals(False)
        self.update_help()

    def update_help(self):
        g = self.grid
        text, pos = "", 0
        w = g.editor if g.editor.isVisible() and not self.bar.hasFocus() else self.bar
        if g.edit is not None:
            text, pos = w.text(), w.cursorPosition()
            sig = sh_edit.signature(text, pos)
            if sig:
                name, names, idx, hint = sig
                parts = [f"<b>{n}</b>" if i == idx else n for i, n in enumerate(names)]
                self.help.setText(f"{name}({', '.join(parts)})" + (f"  -  {hint}" if hint else ""))
                self.help.setStyleSheet(f"color:{ui_kit.MUTED}; padding:1px 8px; font-size:11px;")
                return
        elif not g.sel_chart and not g.sel_picture:
            warn = self.wb.warnings.get((g.sheet, g.r, g.c))
            if warn:
                self.help.setText("⚠ " + "; ".join(warn))
                self.help.setStyleSheet(f"color:{ui_kit.WARN}; padding:1px 8px; font-size:11px;")
                return
            s = self.wb.get_sheet(g.sheet)
            ln = sh_study._link_at(s, g.r, g.c) if s else None
            if ln is not None:
                note = "newer results are saved: Data > Refresh from study" if sh_study.is_stale(ln) else "Data > Refresh from study reads it again"
                self.help.setText(f"Imported from {ln.get('name', 'a study')} - {note}")
                self.help.setStyleSheet(f"color:{ui_kit.MUTED}; padding:1px 8px; font-size:11px;")
                return
        self.help.setText("")

    # ------------------------------------------------------------------ the name box
    def name_entered(self):
        t = self.name_box.text().strip()
        g = self.grid
        p = self.wb.parse_range(t, g.sheet)
        if p is not None:
            sh, r1, c1, r2, c2 = p
            if sh != g.sheet:
                self.tabbar.setCurrentIndex(self.wb.sheet_names().index(sh))
            g.select(r1, c1, r2, c2)
            g.setFocus()
            return
        s = g.sheet_obj()
        key = next((k for k in list(s.names) + list(self.wb.names) if k.casefold() == t.casefold()), None)
        if key is not None:
            target = (s.names.get(key) or self.wb.names.get(key) or "").lstrip("=")
            p = self.wb.parse_range(target.replace("$", ""), g.sheet)
            if p:
                if p[0] != g.sheet:
                    self.tabbar.setCurrentIndex(self.wb.sheet_names().index(p[0]))
                g.select(p[1], p[2], p[3], p[4])
                g.setFocus()
                return
        r1, c1, r2, c2 = g.sel()
        ref = f"={E.quote_sheet(g.sheet)}!${E.col_letter(c1)}${r1}" + (f":${E.col_letter(c2)}${r2}" if (r1, c1) != (r2, c2) else "")
        if self.wb.set_name(t, ref, sheet=g.sheet):
            self.status.say(f"{t} now means {ref[1:]} on this sheet. (Names > Names changes it, or makes it work in every sheet.)", "good")
        else:
            self.status.say(f"'{t}' is not a cell, a range or a valid name.", "bad")
        self.on_selection()
        g.setFocus()

    # ------------------------------------------------------------------ the sheet tabs
    def rebuild_sheet_tabs(self):
        names = self.wb.sheet_names()
        cur = [self.tabbar.tabText(i) for i in range(self.tabbar.count())]
        self.tabbar.blockSignals(True)
        if cur != names:
            while self.tabbar.count():
                self.tabbar.removeTab(0)
            for n in names:
                self.tabbar.addTab(n)
        i = names.index(self.grid.sheet) if self.grid.sheet in names else 0
        self.tabbar.setCurrentIndex(i)
        self.tabbar.blockSignals(False)

    def sheet_tab_changed(self, i):
        if i < 0 or i >= len(self.wb.sheets):
            return
        g = self.grid
        name = self.tabbar.tabText(i)
        if g.edit is not None and not g.editor_for_point().can_point():
            if not g.commit_edit():
                self.rebuild_sheet_tabs()
                return
        g.set_sheet(name)
        self.update_ribbon()
        self.follow_panel()

    def sheet_tab_moved(self, frm, to):
        name = self.tabbar.tabText(to)
        self.wb.move_sheet(name, to)
        self.mark_extra()

    def sheet_menu(self, pos):
        i = self.tabbar.tabAt(pos)
        if i < 0:
            return
        m = QMenu(self)
        m.addAction("Rename", lambda _c=False: self.rename_sheet(i))
        m.addAction("Copy", lambda _c=False: self.duplicate_sheet())
        m.addAction("Delete", lambda _c=False: self.delete_sheet(i))
        m.addSeparator()
        m.addAction("Add sheet", lambda _c=False: self.add_sheet())
        m.exec(self.tabbar.mapToGlobal(pos))

    def add_sheet(self):
        s = self.wb.add_sheet()
        self.grid.set_sheet(s.name)
        self.rebuild_sheet_tabs()
        self.mark_extra()

    def duplicate_sheet(self):
        s = self.wb.duplicate_sheet(self.grid.sheet)
        if s is not None:
            self.grid.set_sheet(s.name)
            self.rebuild_sheet_tabs()

    def delete_sheet(self, i=None):
        name = self.tabbar.tabText(i) if isinstance(i, int) else self.grid.sheet
        if len(self.wb.sheets) <= 1:
            self.status.say("A workbook keeps at least one sheet.", "warn")
            return
        if QMessageBox.question(self, "Delete sheet", f"Delete the sheet '{name}'? Formulas that read it will show #REF!. (Undo brings it back.)") != QMessageBox.StandardButton.Yes:
            return
        self.wb.delete_sheet(name)
        self.rebuild_sheet_tabs()
        self.mark_extra()

    def rename_sheet(self, i):
        old = self.tabbar.tabText(i)
        new, ok = QInputDialog.getText(self, "Rename sheet", "Sheet name:", text=old)
        if not ok or new == old:
            return
        if not self.wb.rename_sheet(old, new.strip()):
            self.status.say("That name cannot be used (it is taken, longer than 31 characters or has one of [ ] : * ? / \\).", "bad")
            return
        if self.grid.sheet == old:
            self.grid.sheet = new.strip()
        self.rebuild_sheet_tabs()

    def paste_to_sheets(self):
        g = self.grid
        others = [n for n in self.wb.sheet_names() if n != g.sheet]
        if not others:
            self.status.say("There is no other sheet.", "warn")
            return
        dlg = D.SheetPickDialog(others, "Paste to sheets", "Copy the selected cells to the same cells of these sheets (formulas then read the sheet they land on).", self)
        if dlg.exec():
            t = dlg.ticked()
            if t:
                self.wb.paste_to_sheets(g.sheet, g.sel(), t)
                self.status.say(f"Copied to {', '.join(t)}.", "good")

    # ------------------------------------------------------------------ editing commands
    def style_selection(self, **kw):
        """Changes the style of every selected block as one undo step."""
        g = self.grid
        self.wb.begin("Format")
        for rect in g.rects():
            self.wb.set_style(g.sheet, rect, **kw)
        self.wb.end()

    def toggle(self, attr):
        g = self.grid
        cell = self.wb.cell(g.sheet, g.r, g.c)
        on = not bool(cell and cell.st and getattr(cell.st, attr))
        self.style_selection(**{attr: on})
        self.update_ribbon()

    def pick_colour(self, which):
        c = D.pick_color(self, "#1f2a3c" if which == "fg" else "#fff3bf")
        if c is not None:
            self.style_selection(**{which: c.name()})

    def set_format(self, fmt):
        self.style_selection(fmt=fmt)
        self.grid.viewport().update()

    def decimals(self, d):
        g = self.grid
        cell = self.wb.cell(g.sheet, g.r, g.c)
        fmt = cell.fmt if cell is not None else "General"
        nd = sh_fmt.decimals_of(fmt)
        if nd is None:
            v = self.wb.value(g.sheet, g.r, g.c)
            nd = 2 if isinstance(v, float) and v != int(v) else 0
            fmt = "0"
        self.set_format(sh_fmt.with_decimals(fmt if fmt != "General" else "0", max(0, min(15, nd + d))))

    def format_dialog(self):
        g = self.grid
        cell = self.wb.cell(g.sheet, g.r, g.c)
        dlg = D.FormatDialog(cell.st if cell else None, self)
        if dlg.exec():
            self.style_selection(**dlg.values())

    def paste_special(self):
        dlg = D.PasteSpecialDialog(self)
        if dlg.exec():
            self.grid.paste(dlg.what())

    def insert(self, axis):
        """Inserts rows (or columns) above (left of) every selected block, as many as the block spans; blocks lower down go first so the numbers stay true."""
        g = self.grid
        runs = g.selected_rows() if axis == "r" else g.selected_cols()
        self.wb.begin_group("Insert rows" if axis == "r" else "Insert columns")
        for a, b in reversed(runs):
            self.wb.insert(g.sheet, axis, a, b - a + 1)
        self.wb.end_group()
        g.viewport().update()

    def delete(self, axis):
        g = self.grid
        runs = g.selected_rows() if axis == "r" else g.selected_cols()
        self.wb.begin_group("Delete rows" if axis == "r" else "Delete columns")
        for a, b in reversed(runs):
            self.wb.delete(g.sheet, axis, a, b - a + 1)
        self.wb.end_group()
        g.areas = []
        g.viewport().update()

    def col_width(self):
        w, ok = QInputDialog.getInt(self, "Column width", "Width in pixels:", self.grid.cols.size(self.grid.c), 14, 800)
        if ok:
            self.grid.set_width(w)

    def names_dialog(self):
        g = self.grid
        r1, c1, r2, c2 = g.sel()
        ref = f"={E.quote_sheet(g.sheet)}!${E.col_letter(c1)}${r1}" + (f":${E.col_letter(c2)}${r2}" if (r1, c1) != (r2, c2) else "")
        D.NamesDialog(self.wb, g.sheet, ref, self).exec()
        g.viewport().update()

    # ------------------------------------------------------------------ functions and standards
    def fx(self):
        """The Function Arguments window for the function of the cell (or the one being typed); a list of functions to pick from when there is none."""
        g = self.grid
        text = g.edit_text_now() if g.edit is not None else B.edit_text(self.wb.cell(g.sheet, g.r, g.c))
        call = D.split_call(text) if text.startswith("=") else None
        if call is not None and call[0] in E.FUNCS:
            return self.open_args(call[0], call[1])
        picker = D.FunctionPicker(self)
        if picker.exec() and picker.chosen:
            self.open_args(picker.chosen, None)

    def standards(self, pack_id):
        b = D.StandardsBrowser(pack_id, self)
        if b.exec() and b.chosen is not None:
            self.open_args(b.chosen.full_name, None)

    def open_args(self, name, values):
        g = self.grid
        if g.edit is None:
            r, c = g.r, g.c
            sheet = g.sheet
        else:
            r, c, sheet = g.edit["r"], g.edit["c"], g.edit["sheet"]
        dlg = D.FunctionArgsDialog(self.wb, sheet, r, c, name, values, grid=g, parent=self)
        dlg.accepted_formula.connect(lambda f, s=sheet, r=r, c=c: self.put_formula(f, s, r, c))
        dlg.finished.connect(lambda _x, d=dlg: self.dialogs.remove(d) if d in self.dialogs else None)
        self.dialogs.append(dlg)
        dlg.setWindowModality(Qt.WindowModality.NonModal)
        dlg.show()
        return dlg

    def put_formula(self, formula, sheet, r, c):
        g = self.grid
        if g.edit is not None:
            cur = g.edit_text_now()
            if cur in ("", "=") or D.split_call(cur) is not None:
                g.set_edit_text(formula)
            else:
                pos = self.bar.cursorPosition() if self.bar.hasFocus() else g.editor.cursorPosition()
                g.set_edit_text(cur[:pos] + formula[1:] + cur[pos:])
            g.editor.setFocus()
            return
        if g.sheet != sheet:
            self.tabbar.setCurrentIndex(self.wb.sheet_names().index(sheet))
        g.select(r, c)
        self.wb.set_input(sheet, r, c, formula)
        g.select(r, c)
        g.viewport().update()
        self.on_selection()
        g.setFocus()

    # ------------------------------------------------------------------ charts
    def chart_by_id(self, cid=None):
        g = self.grid
        s = g.sheet_obj()
        cid = cid or g.sel_chart or (s.charts[0]["id"] if s.charts else None)
        return next((c for c in s.charts if c.get("id") == cid), None)

    def chart_new(self):
        """Insert chart: from the selected cells when there are some; otherwise an empty chart and the panel waits for the cells to be picked."""
        g = self.grid
        if sh_deps.matplotlib() is None:
            self.status.say("matplotlib is needed to draw charts.", "bad")
            return
        rects = g.used_rects()
        if len(rects) == 1 and rects[0][:2] == rects[0][2:]:     # one cell: the block of numbers around it, as Excel does
            around = self.region_around(rects[0][0], rects[0][1])
            rects = [around] if around else []
        charts = g.sheet_obj().charts
        preset = sh_presets.get(sh_presets.default_name())
        ch = sh_chart.from_rects(self.wb, g.sheet, rects, charts, preset) if rects else None
        if ch is None or not ch["series"]:
            ch = sh_chart.blank(sh_chart.new_id(charts), preset=preset)
            rects = []
        bounds = (min(a[0] for a in rects), min(a[1] for a in rects), max(a[2] for a in rects), max(a[3] for a in rects)) if rects else None
        ch["pos"] = g.default_chart_pos(bounds)
        g.add_chart(ch)
        self.open_panel(ch, start_pick=not ch["series"])
        self.status.say("Chart added." if ch["series"] else "Chart added. Select its cells on the sheet.", "good")
        self.update_ribbon()

    def region_around(self, r, c):
        s = self.grid.sheet_obj()

        def filled(a, b):
            x = s.cells.get((a, b))
            return x is not None and x.raw is not None
        if not filled(r, c):
            return None
        r1, r2, c1, c2 = r, r, c, c
        grew = True
        while grew:
            grew = False
            if r1 > 1 and any(filled(r1 - 1, k) for k in range(c1 - 1 if c1 > 1 else c1, c2 + 2)):
                r1 -= 1
                grew = True
            if any(filled(r2 + 1, k) for k in range(max(1, c1 - 1), c2 + 2)):
                r2 += 1
                grew = True
            if c1 > 1 and any(filled(k, c1 - 1) for k in range(max(1, r1 - 1), r2 + 2)):
                c1 -= 1
                grew = True
            if any(filled(k, c2 + 1) for k in range(max(1, r1 - 1), r2 + 2)):
                c2 += 1
                grew = True
        return r1, c1, r2, c2

    def chart_edit(self, cid=None):
        ch = self.chart_by_id(cid or None)
        if ch is None:
            self.status.say("There is no chart on this sheet yet: select cells, then Insert chart.", "warn")
            return
        if sh_deps.matplotlib() is None:
            self.status.say("matplotlib is needed to draw charts.", "bad")
            return
        self.grid.pick_chart(ch["id"])
        self.open_panel(ch)

    # ------------------------------------------------------------------ the chart panel
    def ensure_panel(self):
        if self.panel is None:
            import sh_panel
            p = sh_panel.ChartPanel()
            p.set_context(self.wb, self.grid)
            p.changed.connect(self.panel_changed)
            p.closed.connect(self.panel_closed)
            p.export_asked.connect(lambda cid: self.chart_export(cid))
            p.message.connect(lambda t, lv: self.status.say(t, lv))
            p.hide()
            self.split.addWidget(p)
            self.split.setStretchFactor(1, 0)
            self.panel = p
        return self.panel

    def panel_open(self):
        return self.panel is not None and not self.panel.isHidden() and self.panel.chart is not None

    def open_panel(self, ch, start_pick=False):
        if self.pic_panel is not None and not self.pic_panel.isHidden():
            self.pic_panel.close_panel()
        p = self.ensure_panel()
        was_hidden = p.isHidden()
        p.set_context(self.wb, self.grid)
        p.show()
        if was_hidden:
            total = max(self.split.width(), 900)
            self.split.setSizes([max(300, total - 400), 400, 0])
        p.open_chart(ch, self.grid.sheet, start_pick)
        self.grid.reveal_chart(ch["id"])

    def panel_changed(self, cid):
        self.grid.refresh_charts()
        self.mark_extra()

    def panel_closed(self):
        self.grid.setFocus()

    def follow_panel(self):
        """The panel shows the chart that is picked on the sheet; it closes when its chart is gone; while it is picking, the selection goes into its box."""
        if not self.panel_open():
            return
        p, g = self.panel, self.grid
        s = g.sheet_obj()
        ids = {c.get("id"): c for c in (s.charts if s else [])}
        if g.sel_chart in ids and ids[g.sel_chart] is not p.chart:
            p.open_chart(ids[g.sel_chart], g.sheet)
            return
        if ids.get(p.chart.get("id")) is not p.chart and not p.picking():
            p.close_panel()                                    # (its chart was deleted, or this is another sheet)
            return
        p.grid_selection()

    def on_charts_changed(self):
        self.mark_extra()
        self.update_ribbon()
        if self.panel_open():
            self.follow_panel()
            if self.panel_open():
                self.panel.sync_size()

    def chart_copy(self, cid=None):
        ch = self.chart_by_id(cid or None)
        if ch is not None:
            c2 = sh_chart.copy_chart(ch, self.grid.sheet_obj().charts)
            self.grid.add_chart(c2)

    def chart_delete(self):
        ch = self.chart_by_id()
        if ch is not None:
            self.grid.delete_chart(ch["id"])

    def chart_export(self, cid=None):
        ch = self.chart_by_id(cid or None)
        if ch is None:
            self.status.say("There is no chart on this sheet.", "warn")
            return
        if sh_deps.matplotlib() is None:
            self.status.say("matplotlib is needed to draw charts.", "bad")
            return
        p, _ = QFileDialog.getSaveFileName(self, "Export chart", (ch.get("title") or "chart") + ".png", "PNG image (*.png);;SVG drawing (*.svg);;PDF file (*.pdf)")
        if not p:
            return
        if "." not in os.path.basename(p):
            p += ".png"
        msg = sh_chart.export(self.wb, ch, p)
        self.status.say(msg or f"Saved {p}", "bad" if msg else "good")

    # ------------------------------------------------------------------ images
    def picture_by_id(self, pid=None):
        g = self.grid
        s = g.sheet_obj()
        pid = pid or g.sel_picture or (s.pictures[0]["id"] if s.pictures else None)
        return next((p for p in s.pictures if p.get("id") == pid), None)

    def picture_new(self):
        """Insert image: a picture file goes on the sheet at the selected cell and is picked, so it can be dragged at once."""
        start = os.path.dirname(self.path) if self.path else ""
        p, _ = QFileDialog.getOpenFileName(self, "Insert image", start, sh_picture.FILE_FILTER)
        if not p:
            return
        try:
            got = sh_picture.read_file(p)
        except sh_picture.PictureError as ex:
            self.status.say(str(ex), "bad")
            return
        if self.grid.add_picture_data(*got) is not None:
            self.status.say("Image added: drag it to move it, double-click it to set its size.", "good")

    def picture_edit(self, pid=None):
        pic = self.picture_by_id(pid or None)
        if pic is None:
            self.status.say("There is no image on this sheet yet: Insert image, or copy a picture and press Ctrl+V.", "warn")
            return
        self.grid.pick_picture(pic["id"])
        self.open_pic_panel(pic)

    def picture_copy(self, pid=None):
        pic = self.picture_by_id(pid or None)
        if pic is not None:
            self.grid.duplicate_picture(pic["id"])

    def picture_delete(self):
        pic = self.picture_by_id()
        if pic is not None:
            self.grid.delete_picture(pic["id"])

    def picture_export(self, pid=None):
        pic = self.picture_by_id(pid or None)
        if pic is None:
            self.status.say("There is no image on this sheet.", "warn")
            return
        ext = sh_picture.suffix_of(self.wb.images.get(pic["image"], b""))
        p, _ = QFileDialog.getSaveFileName(self, "Export image", (pic.get("name") or "image") + ext, "PNG image (*.png);;JPEG image (*.jpg *.jpeg);;BMP image (*.bmp)")
        if not p:
            return
        if "." not in os.path.basename(p):
            p += ext
        msg = sh_picture.export(self.wb, pic, p)
        self.status.say(msg or f"Saved {p}", "bad" if msg else "good")

    def ensure_pic_panel(self):
        if self.pic_panel is None:
            p = sh_picture.PicturePanel()
            p.set_context(self.wb, self.grid)
            p.changed.connect(self.pic_panel_changed)
            p.closed.connect(self.panel_closed)
            p.export_asked.connect(lambda pid: self.picture_export(pid))
            p.delete_asked.connect(lambda pid: self.grid.delete_picture(pid))
            p.hide()
            self.split.addWidget(p)
            self.split.setStretchFactor(self.split.indexOf(p), 0)
            self.pic_panel = p
        return self.pic_panel

    def pic_panel_open(self):
        return self.pic_panel is not None and not self.pic_panel.isHidden() and self.pic_panel.picture is not None

    def open_pic_panel(self, pic):
        if self.panel is not None and not self.panel.isHidden():
            self.panel.close_panel()
        p = self.ensure_pic_panel()
        was_hidden = p.isHidden()
        p.set_context(self.wb, self.grid)
        p.show()
        if was_hidden:
            total = max(self.split.width(), 900)
            self.split.setSizes([max(300, total - 320), 0, 320])
        p.open_picture(pic, self.grid.sheet)
        self.grid.reveal_picture(pic["id"])

    def pic_panel_changed(self, pid):
        self.grid.refresh_pictures()
        self.update_ribbon()
        self.update_titles()

    def follow_pic_panel(self):
        """The panel shows the picture that is picked on the sheet; it closes when its picture is gone or another sheet is shown."""
        if not self.pic_panel_open():
            return
        p, g = self.pic_panel, self.grid
        s = g.sheet_obj()
        by_id = {x.get("id"): x for x in (s.pictures if s else [])}
        if g.sel_picture in by_id:
            if by_id[g.sel_picture] is not p.picture or p.sheet != g.sheet:
                p.open_picture(by_id[g.sel_picture], g.sheet)
            return
        live = by_id.get(p.picture.get("id")) if p.sheet == g.sheet else None
        if live is None:
            p.close_panel()                                    # (its picture was deleted, or this is another sheet)
        elif live is not p.picture:
            p.open_picture(live, g.sheet)                      # (an undo put it back as a new object)
            return

    def on_pictures_changed(self):
        self.update_ribbon()
        self.update_titles()
        self.follow_pic_panel()
        if self.pic_panel_open():
            self.pic_panel.load()

    # ------------------------------------------------------------------ studies
    def open_study_projects(self):
        out = []
        host = self.host
        tabs = getattr(host, "tabs", None)
        if tabs is not None:
            for i in range(tabs.count()):
                w = tabs.widget(i)
                if getattr(w, "kind", "") == "study":
                    path = getattr(getattr(w, "sw", None), "path", None)
                    if path and sh_study.studies(path):
                        out.append((os.path.basename(path.rstrip("/\\")) or path, path))
        return out

    def study_import(self, choice=None):
        """Import study: `choice` = (project, sub, new_sheet) skips the window (tests)."""
        if choice is None:
            dlg = D.StudyImportDialog(self.open_study_projects(), self)
            if not dlg.exec():
                return None
            choice = dlg.result_choice()
        project, sub, new_sheet = choice
        g = self.grid
        try:
            if new_sheet:
                name = self.wb.unique_name("Study")
                self.wb.add_sheet(name)
                g.set_sheet(name)
                self.rebuild_sheet_tabs()
            link, notes = sh_study.import_study(self.wb, g.sheet, project, sub)
        except sh_study.StudyError as ex:
            self.status.say(str(ex), "bad")
            return None
        r0, c0 = link["origin"]
        g.select(r0, c0, r0 + link["rows"], c0 + link["cols"] - 1, active=(r0, c0))
        self.status.say(f"Imported {link['name']}: {link['rows']} row(s). " + " ".join(notes), "good")
        self.mark_extra()
        return link

    def study_at_cursor(self, title, verb):
        """The imported study an action is for: the one the cursor is on or next to.  With the cursor elsewhere the person is asked - which of several, or whether
        the only one is meant - so that a study is never refilled (or deleted) by an action that was meant for something else.  None when nothing is chosen."""
        g = self.grid
        s = g.sheet_obj()
        near = sh_study._link_at(s, g.r, g.c)
        if near is not None:
            return near
        close = [x for x in s.links if sh_study.is_near(self.wb, s, x, g.r, g.c)]
        if len(close) == 1:
            return close[0]
        label = lambda x: f"{x.get('name', 'study')} ({E.addr(*sh_study.block_rect(x)[:2])}:{E.addr(*sh_study.block_rect(x)[2:])})"
        if len(s.links) == 1:
            x = s.links[0]
            ok = QMessageBox.question(self, title, f"The cursor is not on the study.\n\n{verb.capitalize()} {label(x)}?") == QMessageBox.StandardButton.Yes
            return x if ok else None
        names = [label(x) for x in s.links]
        pick, ok = QInputDialog.getItem(self, title, "Which one?", names, 0, False)
        return s.links[names.index(pick)] if ok else None

    def study_select(self):
        """Selects every cell of the imported study (so it can be moved, copied or cleared as one)."""
        if not self.grid.sheet_obj().links:
            self.status.say("This sheet has no imported study.", "warn")
            return None
        ln = self.study_at_cursor("Select study", "select")
        if ln is None:
            return None
        r1, c1, r2, c2 = sh_study.block_rect(ln)
        self.grid.select(r1, c1, r2, c2, active=(r1, c1))
        self.status.say(f"Selected {ln.get('name', 'the study')}. Drag its border to move it.", "")
        return ln

    def _ask_study_delete(self, ln):
        """'cells' (delete the study and its cells), 'keep' (the numbers stay as plain cells) or None."""
        box = QMessageBox(self)
        box.setWindowTitle("Delete study")
        r1, c1, r2, c2 = sh_study.block_rect(ln)
        box.setText(f"Take {ln.get('name', 'the study')} ({E.addr(r1, c1)}:{E.addr(r2, c2)}) off the sheet?\n\n"
                    "Refresh from study will no longer fill this area. Formulas next to it are not touched.")
        b_cells = box.addButton("Delete the study and its cells", QMessageBox.ButtonRole.DestructiveRole)
        b_keep = box.addButton("Keep the numbers as plain cells", QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        return "cells" if box.clickedButton() is b_cells else ("keep" if box.clickedButton() is b_keep else None)

    def study_delete(self):
        """Removes an imported study from the sheet: its cells go too, or stay as plain numbers.  One undo step."""
        g = self.grid
        if not g.sheet_obj().links:
            self.status.say("This sheet has no imported study.", "warn")
            return None
        ln = self.study_at_cursor("Delete study", "delete")
        if ln is None:
            return None
        choice = self._ask_study_delete(ln)
        if choice is None:
            return None
        name = ln.get("name", "the study")
        sh_study.remove_link(self.wb, g.sheet, ln, clear=(choice == "cells"))
        self.status.say(f"Deleted {name} from the sheet." if choice == "cells" else f"{name} is no longer linked: its numbers stay as plain cells.", "good")
        self.mark_extra()
        g.viewport().update()
        self.update_help()
        return ln

    def study_refresh(self, force=False):
        g = self.grid
        s = g.sheet_obj()
        if not s.links:
            self.status.say("This sheet has no imported study. Data > Import study adds one.", "warn")
            return None
        ln = self.study_at_cursor("Refresh from study", "refresh")
        if ln is None:
            return None
        try:
            done, notes = sh_study.refresh(self.wb, g.sheet, ln, force=force)
        except sh_study.StudyError as ex:
            self.status.say(str(ex), "bad")
            return None
        if not done:
            if QMessageBox.question(self, "Refresh from study", notes[0] + "\n\nReplace them?") == QMessageBox.StandardButton.Yes:
                return self.study_refresh(force=True)
            return None
        self.status.say(f"Refreshed from {ln.get('name', 'the study')}: {ln['rows']} row(s). " + " ".join(notes), "good")
        self.mark_extra()
        g.viewport().update()
        self.update_help()
        return ln

    # ------------------------------------------------------------------ files
    def file_new(self):
        if self.host is not None and hasattr(self.host, "new_addon_tab"):
            self.host.new_addon_tab("sheets")

    def open_dialog(self):
        p, _ = QFileDialog.getOpenFileName(self, "Open", "", OPEN_FILTER)
        if not p:
            return
        if self.host is not None and hasattr(self.host, "new_addon_tab") and (self.is_dirty() or self.path or self.has_content()):
            self.host.new_addon_tab("sheets", p)
        else:
            self.open_path(p)

    def has_content(self):
        return any(s.cells or s.charts for s in self.wb.sheets)

    def ensure_openpyxl(self):
        if sh_deps.openpyxl() is not None:
            return True
        if not self.AUTO_DOWNLOAD:
            self.status.say("openpyxl is needed to read and write Excel files.", "bad")
            return False
        if QMessageBox.question(self, "Excel files", "Reading and writing Excel files needs a small download (openpyxl, about 1 MB, once).\n\nDownload it now? This needs an internet connection.") \
                != QMessageBox.StandardButton.Yes:
            return False
        dlg = QProgressDialog("Downloading openpyxl ...", None, 0, 0, self)
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setCancelButton(None)
        dlg.show()
        res = {}

        def work():
            try:
                sh_deps.install(lambda text, frac=None: None, self.installer)
                res["ok"] = True
            except BaseException as ex:                       # noqa: BLE001 - shown to the person, never raised in a thread
                res["err"] = str(ex)
        th = threading.Thread(target=work, daemon=True)
        th.start()
        while th.is_alive():
            QApplication.processEvents()
            th.join(0.05)
        dlg.close()
        if res.get("ok"):
            return True
        QMessageBox.warning(self, "Excel files", "openpyxl could not be downloaded.\n\n" + (res.get("err", "").strip()[-500:] or "Check the internet connection and try again."))
        return False

    def open_path(self, path):
        low = path.lower()
        try:
            if low.endswith(".xlsx") or low.endswith(".xlsm"):
                if not self.ensure_openpyxl():
                    return False
                wb, notes = sh_xlsx.import_xlsx(path)
                self.load_workbook(wb, None, os.path.basename(path))
                self.status.say(f"Opened {os.path.basename(path)}. " + " ".join(notes), "warn" if notes else "good")
                if notes and self.isVisible():
                    QMessageBox.information(self, "Excel file", "\n".join(notes))
                return True
            wb = B.Workbook.load(path)
        except (OSError, ValueError, sh_xlsx.XlsxError) as ex:
            self.status.say(f"Couldn't open that file: {ex}", "bad")
            return False
        self.load_workbook(wb, path, None)
        self.status.say(f"Opened {path}", "good")
        return True

    def load_workbook(self, wb, path, title):
        try:
            self.wb.listeners.remove(self.wb_changed)
        except ValueError:
            pass
        self.wb = wb
        if self.panel is not None:
            self.panel.close_panel()
            self.panel.set_context(wb, self.grid)
        if self.pic_panel is not None:
            self.pic_panel.close_panel()
            self.pic_panel.set_context(wb, self.grid)
        self.grid.set_workbook(wb)                          # the grid listens first, so it already shows a sheet that exists
        wb.listeners.append(self.wb_changed)
        self.path = path
        self.title_text = title or "Sheets"
        self.saved_version = wb.version
        self.extra_dirty = False
        self.rebuild_sheet_tabs()
        self.on_selection()
        self.update_titles()

    def save(self, as_new=False):
        if self.grid.edit is not None and not self.grid.commit_edit():
            return False
        if not self.path or as_new:
            p, _ = QFileDialog.getSaveFileName(self, "Save", self.path or "workbook.opsheet", FILTER)
            if not p:
                return False
            if not p.lower().endswith(".opsheet"):
                p += ".opsheet"
            self.path = p
        try:
            self.wb.active = self.wb.sheet_names().index(self.grid.sheet) if self.grid.sheet in self.wb.sheet_names() else 0
            self.wb.save(self.path)
        except OSError as ex:
            self.status.say(f"Couldn't save: {ex}", "bad")
            return False
        self.saved_version = self.wb.version
        self.extra_dirty = False
        self.update_titles()
        self.status.say(f"Saved {self.path}", "good")
        return True

    def import_xlsx_dialog(self):
        p, _ = QFileDialog.getOpenFileName(self, "Import Excel workbook", "", "Excel workbook (*.xlsx *.xlsm);;All files (*)")
        if not p:
            return
        if self.host is not None and hasattr(self.host, "new_addon_tab") and (self.is_dirty() or self.path or self.has_content()):
            self.host.new_addon_tab("sheets", p)
        else:
            self.open_path(p)

    def export_xlsx_dialog(self):
        if not self.ensure_openpyxl():
            return
        base = os.path.splitext(self.title())[0] + ".xlsx"
        p, _ = QFileDialog.getSaveFileName(self, "Export Excel workbook", base, "Excel workbook (*.xlsx)")
        if not p:
            return
        if not p.lower().endswith(".xlsx"):
            p += ".xlsx"
        self.export_xlsx(p)

    def export_xlsx(self, p):
        try:
            notes = sh_xlsx.export_xlsx(self.wb, p)
        except (OSError, sh_xlsx.XlsxError) as ex:
            self.status.say(f"Couldn't export: {ex}", "bad")
            return None
        self.status.say(f"Exported {p}. " + " ".join(notes), "warn" if notes else "good")
        return notes

    # ------------------------------------------------------------------ the shell's questions
    def can_close(self):
        g = self.grid
        if g.edit is not None:
            return g.commit_edit()
        return True

    def shutdown(self):
        sh_prefs.off_change(self.prefs_changed)
        if self.panel is not None:
            self.panel.stop_pick()
            self.panel.timer.stop()
            self.panel.note_timer.stop()
        for d in list(self.dialogs):
            d.close()
        self.grid.finish_edit(commit=False)

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_S and ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.save()
            ev.accept()
            return
        super().keyPressEvent(ev)


def make_tab(path=None):
    return SheetsTab(path)
