# Circuits (playground add-on)

Drag-and-drop circuit diagrams with a built-in simulator. Tab: **Circuits**; files: `.opcirc`.

* **Parts**: battery / DC supply, wall outlet (120 V 60 Hz or 230 V 50 Hz), function generator, ground; resistor, potentiometer, capacitor,
  inductor, switch (double-click), fuse, lamp; diode, LED (colour + glow), zener, NPN, PNP, N-MOSFET; buck and boost converters (averaged models);
  voltmeter, ammeter (in series), ohmmeter (circuit unpowered), oscilloscope (4 channels).
* **Drawing**: drag parts from the list (or click, then click the sheet). Start a wire on any pin, click corners, finish on a pin or on another wire
  (Space flips the elbow). `R` rotate, `F` mirror, `Delete`, `Ctrl+Z / Ctrl+Y`, middle mouse pans, wheel zooms. Values accept `4.7k`, `100n`, `2meg`.
* **Simulation**: meters and LED glow update live (DC operating point). **Run** simulates over time for the oscilloscope; meters then show average (or RMS).
  The checks list warns about a missing ground, unconnected pins, an LED without a resistor, over-current and blown fuses.
* Solver: `netsolve.py` (modified nodal analysis, Newton for nonlinear parts, trapezoidal transient, AC sweep). Part library: `parts.py`.

Not yet: microcontrollers (Arduino / ESP32), breadboard view, real chip models.
