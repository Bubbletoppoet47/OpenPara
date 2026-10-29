"""The drop-down + Import button that the 1D FEA, 2D FEA and CFD tabs use to choose which sketch of the project they work on."""
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class SketchPicker(QWidget):
    def __init__(self, win, on_import, tip=""):
        """on_import(sketch id, sketch as JSON text, sketch name) is called when Import is pressed."""
        super().__init__()
        self.win = win
        self.on_import = on_import
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(QLabel("Sketch of the project"))
        row = QHBoxLayout()
        self.combo = QComboBox()
        self.combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.combo.setMinimumContentsLength(12)
        self.btn = QPushButton("Import")
        self.btn.setToolTip(tip or "Makes a copy of the chosen sketch as it is now. Later changes in the sketch do not affect this copy.")
        self.btn.clicked.connect(self.go)
        row.addWidget(self.combo, 1)
        row.addWidget(self.btn)
        lay.addLayout(row)
        self.refresh()

    def refresh(self):
        keep = self.combo.currentData()
        self.combo.blockSignals(True)
        self.combo.clear()
        try:
            items = self.win.sketch_list()
        except Exception:
            items = []
        for sid, name in items:
            self.combo.addItem(name, sid)
        i = self.combo.findData(keep)
        if i >= 0:
            self.combo.setCurrentIndex(i)
        elif self.win.doc is not None:                                  # the sketch being used is the natural first choice
            j = self.combo.findData(self.win.doc.get("id"))
            if j >= 0:
                self.combo.setCurrentIndex(j)
        if not items:
            self.combo.addItem("(no sketch yet: Add > Sketch)", None)
        self.combo.blockSignals(False)
        self.btn.setEnabled(bool(items))

    def select(self, sid):
        i = self.combo.findData(sid)
        if i >= 0:
            self.combo.setCurrentIndex(i)

    def go(self):
        sid = self.combo.currentData()
        if sid is None:
            return
        got = self.win.sketch_json(sid)
        if got is None:
            return
        name, text = got
        self.on_import(sid, text, name)
