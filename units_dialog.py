"""File > Units: the one unit system of the whole program, the speed unit (a separate choice) and the heat-transfer units (a third one)."""
from PyQt6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QLabel, QVBoxLayout

import heatunits
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

        # the heat-transfer units (the 2D Thermal tab): a preset, or one unit for every quantity
        box = QGroupBox("Heat transfer (2D Thermal)")
        hl = QVBoxLayout(box)
        note = QLabel("A well-known combination of units, or choose each one yourself.  The temperature and heat units only change how\n"
                      "numbers are shown and typed; the physics is solved in SI.")
        note.setStyleSheet("color:#506080;")
        hl.addWidget(note)
        hform = QFormLayout()
        self.heat = QComboBox()
        self.heat.addItems(heatunits.preset_names())
        self.heat.setToolTip("'Follow the unit system' uses degC, W and W/(m K) with the metric systems and degF and Btu with the US ones.")
        hform.addRow("Heat transfer units", self.heat)
        self.heat_boxes = {}
        for q in heatunits.QUANTITIES:
            c = QComboBox()
            c.addItems(heatunits.unit_names(q))
            self.heat_boxes[q] = c
            hform.addRow(heatunits.LABELS[q], c)
        hl.addLayout(hform)
        lay.addWidget(box)
        self.heat_info = QLabel()
        self.heat_info.setStyleSheet("color:#506080;")
        hl.addWidget(self.heat_info)
        self._fill_heat(unitctl.heat(), unitctl.heat_custom())

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.system.currentTextChanged.connect(self.show_info)
        self.system.currentTextChanged.connect(self.system_changed)
        self.heat.currentTextChanged.connect(self.heat_picked)
        for c in self.heat_boxes.values():
            c.currentTextChanged.connect(self.heat_unit_picked)
        self.show_info()

    def show_info(self, *_):
        u = units.get(self.system.currentText())
        self.info.setText(f"Length {u['L']}   Force {u['F']}   Stress / pressure {u['S']}   Density {u['rho']}")

    # ------------------------------------------------------------------------------------------------ the heat-transfer units
    def _fill_heat(self, preset, custom):
        """Shows `preset` (and, for 'Custom', `custom`): the unit of every quantity follows."""
        self._filling = True
        try:
            self.heat.setCurrentText(preset)
            u = heatunits.resolve(preset, custom, self.system.currentText())
            for q, c in self.heat_boxes.items():
                c.setCurrentText(u[q])
        finally:
            self._filling = False
        self.show_heat_info()

    def system_changed(self, *_):
        """'Follow the unit system' shows the units of the system picked now."""
        if self.heat.currentText() == heatunits.FOLLOW:
            self._fill_heat(heatunits.FOLLOW, {})

    def heat_picked(self, name):
        if getattr(self, "_filling", False):
            return
        self._fill_heat(name, self.heat_units() if name == heatunits.CUSTOM else {})

    def heat_unit_picked(self, *_):
        """A unit was changed by hand: the choice is 'Custom', or the preset that has exactly these units."""
        if getattr(self, "_filling", False):
            return
        self._filling = True
        try:
            self.heat.setCurrentText(heatunits.preset_of(self.heat_units()))
        finally:
            self._filling = False
        self.show_heat_info()

    def heat_units(self):
        """The unit chosen for every quantity: {'T': '°C', ...}."""
        return {q: c.currentText() for q, c in self.heat_boxes.items()}

    def show_heat_info(self):
        n = self.heat.currentText()
        self.heat_info.setText("Uses the units shown, by the unit system chosen above." if n == heatunits.FOLLOW else "")

    def choice(self):
        return self.system.currentText(), self.speed.currentText()

    def heat_choice(self):
        """-> (name, custom units): what unitctl.set_heat takes.  The units are only kept for 'Custom'."""
        n = self.heat.currentText()
        return n, (self.heat_units() if n == heatunits.CUSTOM else {})
