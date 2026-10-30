"""
sketch_tables.py - the two tables of an open sketch (Dimensions and Relations) share one look and one behaviour:
spreadsheet-style rows, whole-row selection (Shift / Ctrl for several), a Delete button and the Delete key, and selecting a row lights the
dimension label / the lines and points it concerns in the sketch.
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QTableWidgetSelectionRange, QVBoxLayout, QWidget

STYLE = ("QTableWidget { gridline-color: #d5dbe6; alternate-background-color: #f4f7fb; selection-background-color: #cfe3fb; "
         "selection-color: #102a4c; } QHeaderView::section { background: #e9eef6; border: 0; border-bottom: 1px solid #c8d0de; padding: 3px 6px; "
         "font-weight: bold; }")


class ConTable(QTableWidget):
    """One table of the sketch panel.  rows = [(constraint id, [cell texts])]; `editable` = the columns that can be typed in."""

    def __init__(self, headers, editable=()):
        super().__init__(0, len(headers))
        self.editable = tuple(editable)
        self.ids = []
        self.setHorizontalHeaderLabels(headers)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(24)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setAlternatingRowColors(True)
        self.setStyleSheet(STYLE)
        self.setMaximumHeight(170)
        self.setProperty("sk_table", True)

    def fill(self, rows, tips=None):
        self.blockSignals(True)
        self.setRowCount(len(rows))
        self.ids = [cid for cid, _ in rows]
        for r, (cid, cells) in enumerate(rows):
            for j, txt in enumerate(cells):
                it = QTableWidgetItem(str(txt))
                if j not in self.editable:
                    it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if tips and tips.get(cid):
                    it.setToolTip(tips[cid])
                self.setItem(r, j, it)
        self.blockSignals(False)

    def selected_ids(self):
        rows = sorted({i.row() for i in self.selectedIndexes()})
        return [self.ids[r] for r in rows if r < len(self.ids)]

    def select_ids(self, ids):
        """Select the rows of these constraint ids without telling the sketch (it asked)."""
        self.blockSignals(True)
        self.clearSelection()
        for r, cid in enumerate(self.ids):
            if cid in ids:
                self.setRangeSelected(QTableWidgetSelectionRange(r, 0, r, self.columnCount() - 1), True)
        self.blockSignals(False)


def panel(title, table, delete_text, on_delete):
    """A heading, the table and its Delete button as one block for the properties panel."""
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 4, 0, 0)
    lay.addWidget(QLabel(title))
    lay.addWidget(table)
    row = QHBoxLayout()
    b = QPushButton(delete_text)
    b.clicked.connect(on_delete)
    row.addWidget(b)
    row.addStretch(1)
    lay.addLayout(row)
    return box
