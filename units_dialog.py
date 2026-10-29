"""File > Units: the one unit system of the whole program, and the speed unit (a separate choice)."""
from PyQt6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QVBoxLayout

import unitctl
import units


class UnitsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Units")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("These units are used everywhere: sketch dimensions, features, assemblies, measuring, mass,\n"
                             "slices, renders, and the 1D / 2D FEA and CFD tabs.  Your files are not changed - a part stays\n"
                             "exactly the same size; a simulation is converted to the new units."))
        form = QFormLayout()
        self.system = QComboBox()
        self.system.addItems(units.names())
        self.system.setCurrentText(unitctl.system())
        self.speed = QComboBox()
        self.speed.addItems(units.speed_names())
        self.speed.setCurrentText(unitctl.speed())
        form.addRow("Unit system", self.system)
        form.addRow("Speed", self.speed)
        lay.addLayout(form)
        self.info = QLabel()
        self.info.setStyleSheet("color:#506080;")
        lay.addWidget(self.info)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.system.currentTextChanged.connect(self.show_info)
        self.show_info()

    def show_info(self, *_):
        u = units.get(self.system.currentText())
        self.info.setText(f"Length {u['L']}   Force {u['F']}   Stress / pressure {u['S']}   Density {u['rho']}")

    def choice(self):
        return self.system.currentText(), self.speed.currentText()
