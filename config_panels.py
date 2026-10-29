from PyQt6.QtCore import QTimer
"""The Configurations and Display tabs of the left panel (for parts and for assemblies)."""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor, QFont
from PyQt6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QMenu, QMessageBox,
                             QPushButton, QSlider, QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)


def color_css(c):
    return "#%02x%02x%02x" % tuple(int(round(255 * x)) for x in c)


# ---------------------------------------------------------------------------------------------- configurations
class ConfigPanel(QWidget):
    """Tree of configurations + the configuration table.  `owner` is the part window or the assembly window;
    `model` (a property of the owner) is its Document / Assembly, which provides the cfg_* methods."""

    def __init__(self, owner, noun):
        super().__init__()
        self.owner, self.noun = owner, noun
        self.busy = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setMaximumHeight(150)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.tree_menu)
        self.tree.itemDoubleClicked.connect(lambda it, _c: self.activate(it.data(0, Qt.ItemDataRole.UserRole)))
        lay.addWidget(self.tree)
        row = QHBoxLayout()
        b = QPushButton("Add Configuration")
        b.clicked.connect(self.add_config)
        row.addWidget(b)
        self.col_btn = QPushButton("Add Column")
        self.col_btn.setToolTip("Put a global, a dimension or a suppress switch in the table")
        self.col_menu = QMenu(self.col_btn)
        self.col_menu.aboutToShow.connect(self.fill_col_menu)
        self.col_btn.setMenu(self.col_menu)
        row.addWidget(self.col_btn)
        b = QPushButton("Remove Column")
        b.clicked.connect(self.remove_column)
        row.addWidget(b)
        lay.addLayout(row)
        self.table = QTableWidget(0, 1)
        self.table.itemChanged.connect(self.cell_changed)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectItems)
        lay.addWidget(self.table, 1)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)

    @property
    def m(self):
        return self.owner.cfg_model()

    # ----- the pieces the owner supplies ---------------------------------------------------
    def title(self):
        return f"{self.owner.title().rsplit('.', 1)[0]} Configuration(s)"

    def refresh(self):
        m = self.m
        self.busy = True
        m.cfg_capture()
        c = m.cfg
        self.tree.clear()
        root = QTreeWidgetItem(self.tree, [self.title()])
        root.setExpanded(True)
        for n in c["names"]:
            act = n == c["active"]
            it = QTreeWidgetItem(root, [("✔  " if act else "      ") + f"{n} [{self.owner.title().rsplit('.', 1)[0]}]"])
            it.setData(0, Qt.ItemDataRole.UserRole, n)
            if act:
                f = it.font(0)
                f.setBold(True)
                it.setFont(0, f)
        cols = c["cols"]
        t = self.table
        t.clear()
        t.setRowCount(len(c["names"]))
        t.setColumnCount(1 + len(cols))
        t.setHorizontalHeaderLabels(["Configuration"] + [m.cfg_label(k) for k in cols])
        for r, n in enumerate(c["names"]):
            it = QTableWidgetItem(n)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if n == c["active"] else Qt.CheckState.Unchecked)
            if n == c["active"]:
                f = it.font()
                f.setBold(True)
                it.setFont(f)
                it.setBackground(QBrush(QColor("#e1ecfb")))
            t.setItem(r, 0, it)
            for j, k in enumerate(cols):
                self.fill_cell(r, 1 + j, n, k, c["cells"].get(n, {}).get(k))
        self.hint.setText("Tick a box to activate a configuration (one is always active); double-click a name to rename it. Edit the cells to change a configuration; "
                          f"the table is the only place its values are stored.  Add Column puts {self.noun} items in the table.")
        self.busy = False

    def fill_cell(self, r, col, name, key, val):
        t = self.table
        if self.is_flag(key):
            it = QTableWidgetItem("")
            it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if val else Qt.CheckState.Unchecked)
            t.setItem(r, col, it)
        elif self.choices(key) is not None:
            cb = QComboBox()
            opts = self.choices(key)
            cb.addItems(opts)
            cb.setCurrentText(str(val) if val in opts else (opts[0] if opts else ""))
            cb.currentTextChanged.connect(lambda txt, n=name, k=key: self.set_value(n, k, txt))
            t.setCellWidget(r, col, cb)
        else:
            t.setItem(r, col, QTableWidgetItem("" if val is None else (f"{val:.6g}" if isinstance(val, float) else str(val))))

    def is_flag(self, key):
        return key.startswith(("s:", "x:", "m:"))

    def choices(self, key):
        return self.owner.cfg_choices(key)

    def cell_changed(self, it):
        if self.busy:
            return
        m = self.m
        r, col = it.row(), it.column()
        name = m.cfg["names"][r]
        if col == 0:
            if it.text() == name:          # only the check box changed
                if it.checkState() == Qt.CheckState.Checked and name != m.cfg["active"]:
                    self.activate(name)
                else:                      # unchecking the active one (or a stray change): put the checks back
                    QTimer.singleShot(0, self.refresh)
                return
            try:
                self.owner.snapshot()
                m.cfg_rename(name, it.text())
            except Exception as ex:
                self.owner.say(str(ex))
            self.owner.config_changed()
            return
        key = m.cfg["cols"][col - 1]
        if self.is_flag(key):
            self.set_value(name, key, it.checkState() == Qt.CheckState.Checked)
        else:
            txt = it.text().strip()
            try:
                val = float(txt) if self.numeric(key) else txt
            except ValueError:
                val = txt
            self.set_value(name, key, val)

    def numeric(self, key):
        return key.startswith(("v:", "n:", "d:"))

    def set_value(self, name, key, val):
        if self.busy:
            return
        self.owner.snapshot()
        self.m.cfg_set_cell(name, key, val)
        self.owner.config_changed()

    # ----- commands -----------------------------------------------------------------------
    def activate(self, name):
        if not name or name == self.m.cfg["active"]:
            return
        self.owner.snapshot()
        try:
            self.m.cfg_apply(name)
        except Exception as ex:
            self.owner.say(str(ex))
            return
        self.owner.config_changed()
        self.owner.say(f"Configuration {name} is active.")

    def add_config(self, copy_of=None):
        name, ok = QInputDialog.getText(self, "Add Configuration", "Name:", text=f"Config{len(self.m.cfg['names']) + 1}")
        if not ok:
            return
        try:
            self.owner.snapshot()
            self.m.cfg_add(name, copy_of if isinstance(copy_of, str) else None)
        except Exception as ex:
            self.owner.undo_pop()
            QMessageBox.warning(self, "Add Configuration", str(ex))
            return
        self.owner.config_changed()

    def tree_menu(self, pos):
        it = self.tree.itemAt(pos)
        name = it.data(0, Qt.ItemDataRole.UserRole) if it is not None else None
        menu = QMenu(self)
        if name:
            menu.addAction("Activate").triggered.connect(lambda: self.activate(name))
            menu.addAction("Copy").triggered.connect(lambda: self.add_config(name))
            menu.addAction("Rename").triggered.connect(lambda: self.rename(name))
            menu.addAction("Delete").triggered.connect(lambda: self.delete(name))
        else:
            menu.addAction("Add Configuration").triggered.connect(self.add_config)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def rename(self, name):
        new, ok = QInputDialog.getText(self, "Rename", "New name:", text=name)
        if ok:
            try:
                self.owner.snapshot()
                self.m.cfg_rename(name, new)
            except Exception as ex:
                self.owner.undo_pop()
                QMessageBox.warning(self, "Rename", str(ex))
                return
            self.owner.config_changed()

    def delete(self, name):
        try:
            self.owner.snapshot()
            self.m.cfg_delete(name)
        except Exception as ex:
            self.owner.undo_pop()
            QMessageBox.warning(self, "Delete", str(ex))
            return
        self.owner.config_changed()

    def fill_col_menu(self):
        menu = self.col_menu
        menu.clear()
        cols = set(self.m.cfg["cols"])
        any_ = False
        for key, label, _v in self.owner.cfg_candidates():
            if key in cols:
                continue
            any_ = True
            menu.addAction(label).triggered.connect(lambda _c=False, k=key: self.add_column(k))
        if not any_:
            menu.addAction("(everything is already in the table)").setEnabled(False)

    def add_column(self, key):
        try:
            self.owner.snapshot()
            self.m.cfg_add_col(key)
        except Exception as ex:
            self.owner.undo_pop()
            QMessageBox.warning(self, "Add Column", str(ex))
            return
        self.owner.config_changed()

    def remove_column(self):
        col = self.table.currentColumn()
        cols = self.m.cfg["cols"]
        if col < 1 or col > len(cols):
            self.owner.say("Click a cell in the column to remove first.")
            return
        self.owner.snapshot()
        self.m.cfg_del_col(cols[col - 1])
        self.owner.config_changed()


# ---------------------------------------------------------------------------------------------- display
class DisplayPanel(QWidget):
    """Colour, transparency and visibility.  `owner.display_items()` gives [(label, store dict, has_visible)] where store has
    "color" (None = default), "opacity" and, for assembly components, "hidden"."""

    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(6, 6, 6, 6)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["", "Color", "Transparency", "Shown"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.lay.addWidget(self.table, 1)
        self.lay.addWidget(QLabel("Color: click the swatch.  Transparency: 0 = solid, 100 = nearly invisible."))

    def refresh(self):
        items = self.owner.display_items()
        t = self.table
        t.clearContents()
        t.setRowCount(len(items))
        for r, (label, store, visible_key, default_color) in enumerate(items):
            it = QTableWidgetItem(label)
            it.setFlags(Qt.ItemFlag.ItemIsEnabled)
            t.setItem(r, 0, it)
            b = QPushButton("")
            col = store.get("color") or default_color
            b.setStyleSheet(f"background:{color_css(col)}; border:1px solid #6b778c; min-height:18px;")
            b.setToolTip("Choose a color (right-click: back to the default)")
            b.clicked.connect(lambda _c=False, s=store, d=default_color: self.pick(s, d))
            b.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            b.customContextMenuRequested.connect(lambda _p, s=store: self.reset(s))
            t.setCellWidget(r, 1, b)
            sl = QSlider(Qt.Orientation.Horizontal)
            sl.setRange(0, 95)
            sl.setValue(int(round((1.0 - float(store.get("opacity", 1.0))) * 100)))
            sl.valueChanged.connect(lambda v, s=store: self.set_opacity(s, v))
            sl.sliderReleased.connect(self.owner.display_changed)
            t.setCellWidget(r, 2, sl)
            if visible_key:
                cb = QCheckBox()
                cb.setChecked(not store.get(visible_key))
                cb.toggled.connect(lambda on, s=store, k=visible_key: self.set_shown(s, k, on))
                t.setCellWidget(r, 3, cb)
        t.resizeColumnsToContents()
        t.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        t.setColumnWidth(2, 120)

    def pick(self, store, default):
        cur = store.get("color") or default
        c = QColorDialog.getColor(QColor(*[int(round(255 * x)) for x in cur]), self, "Color")
        if c.isValid():
            self.owner.snapshot()
            store["color"] = [c.redF(), c.greenF(), c.blueF()]
            self.owner.display_changed()

    def reset(self, store):
        self.owner.snapshot()
        store["color"] = None
        store["opacity"] = 1.0
        self.owner.display_changed()

    def set_opacity(self, store, v):
        store["opacity"] = 1.0 - v / 100.0
        self.owner.display_live()

    def set_shown(self, store, key, on):
        self.owner.snapshot()
        store[key] = not on
        self.owner.display_changed()


def unused(*_a):
    return QFont
