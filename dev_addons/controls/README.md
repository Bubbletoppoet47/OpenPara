# Systems and Controls (playground add-on)

Control-systems tools, added one textbook problem at a time. Tab: **Controls**; files: `.opctl`.

The tab is a column of dropdown sections on the left (one tool each; opening one shows its inputs) and the worked answer and plots for the open
section on the right. Adding a tool = one `Section` class in `controls_tab.py` plus its maths in `ctl_core.py`.

## Sections
* **Transfer function: poles, zeros, gain** - type the numerator and denominator of G(s) (`2s+3`, `s^2+3s+2`, `(s+1)(s+2)`, or `[1 3 2]`).
  The short answer: G(s) in pole-zero form on one line, zeros, poles, gain K, DC gain G(0), stable / unstable / marginal; extra lines only
  when they matter (complex pair: wn and zeta; integrator: infinite DC gain; cancelling pole and zero; improper G(s)). "Show the full working"
  adds the polynomial form, how K and G(0) are found, order, relative degree, type and the time constants.
  Step and impulse responses of G(s) as closed-form answers (partial fractions; repeated poles give t*e^(-at), complex poles give
  e^(sigma t)(A cos wt + B sin wt), a pole at the origin gives a ramp, an improper G(s) gives delta(t) terms; a cancelling pole and zero are reduced first).
  The full working adds Y(s) in partial fractions.
  The right side is two halves: the text answer on top, and below it one view picked from a dropdown: Pole-zero plot, Block diagram
  (one block or blocks in series, set on the left), Step response, Impulse response (final value dashed), Routh-Hurwitz (the array as a table with the
  first column shaded, the verdict and number of right-half-plane poles, the necessary condition, a zero in the first column handled with epsilon, a row of
  zeros handled with the auxiliary equation, and a cross-check against the roots; a row is coloured when it is special). Leave the Numerator empty to type
  only Q(s) (taken as 1). The chosen view is saved in the file.
  A new tool later (Bode, Nyquist, root locus) = one view class plus one entry in `TransferFunctionSection.VIEWS`.
  First test: book example 1.4.5.1, G(s) = (2s+3)/(s^2+3s+2): zero -1.5, poles -1 and -2, K = 2, DC gain 1.5.

* **Mechanical / Electrical systems** - draw the system on a grid (parts palette: source, R, L, C, ground, output probe; or mass, spring, damper,
  wall, force, output) and get G(s) with your part names (`1 / (C L s² + C R s + 1)`) and, once Value cells hold numbers, the poles, the step and
  impulse responses and the plots. The solver is modified nodal analysis in s with exact polynomial algebra (no outside library); a mechanical
  system is solved through the force-current analogy and its output is displacement (velocity / s). The lower-left text also lists the analogy
  (force-voltage): a series R-L-C loop is drawn as one rigid body with spring, damper and mass, and one rigid body as a series loop; other networks
  get the correspondence lines only. Examples: book 1.5.5.2, 1.5.5.3, 1.5.5.4. "Open G(s) in Transfer function" sends the numbers across.
  Electrical and mechanical drawings are kept separately in the file.

* **Dynamic simulation: balance a drawn system** - draw a mechanism in 2-D from preset parts and run it in time with a PID controller. Parts: **Wheel**
  (rolls on the ground without slipping), **Cart** (slides), **Pivot** (a fixed pin), **Link** (a rod pinned to the picked part, at a distance
  along it), **Mass** (a point mass on a link), and **one motor** on a joint (an ideal motor with a maximum torque, or force for a cart; no
  losses or back-EMF). Every part has editable numbers (lengths, masses, drawn angle, spring and damper in a joint). Connection rules are checked in plain words
  (nothing to stand on, a link not attached, a mass off the end of its link, no motor, two motors, a link with no mass, drawn below the ground).
  The controller keeps one link upright: an inner **tilt PID** (derivative from the measured rate, anti-windup, saturating at the motor limit) and an outer
  **position PID** that turns the error from a goal x into a tilt target (clamped). The goal is a fixed point, a step, or a ramp at an adjustable speed.
  The torque direction is found automatically from the linearised closed loop. **Run** integrates the full non-linear motion (RK4, controller at its own sample rate)
  and plays it back with plots of tilt, position against its goal, and motor effort; the run ends when the tilt passes the fall limit (default 45°) or any part
  touches the ground. A push can be applied once to the top. **Suggest gains** designs an LQR on the linearised model and writes it as cascade PID gains;
  **Open G(s) in Transfer function** sends the plant (motor command to tilt, matching pole-zero pairs cancelled) to the first section for its poles, zeros and Routh test.
  Examples: self-balancing robot, cart and pole, inverted pendulum on a pivot, hanging pendulum. Units are SI (File > Units does not apply here yet).
  Limits of this first version: one base, a tree of links (no closed loops), one motor, ideal sensors, no wheel slip.

## Files
* `ctl_core.py` - transfer-function maths, no Qt (`parse_poly`, `analyze`, `report`, `response_of`).  `ctl_circuit.py` - drawn networks to G(s), no Qt
  (`solve`, `Poly`, analogies, examples).  `ctl_canvas.py` - the drawing surface.  `controls_tab.py` - the tab and its sections.
  `ctl_section.py` - the Section base class and axis ticks.  `ctl_dyn.py` - the dynamics engine, no Qt (sketch data, plain-word checks, equations of motion, run, linearise, gains, examples).
  `ctl_dyn_view.py` - the animation canvas and signal plots.  `ctl_dyn_section.py` - the Dynamic simulation section.
* Tests: `test_controls_core.py`, `test_controls_circuit.py`, `test_controls_tab.py`, `test_controls_network.py`, `test_controls_dyn.py` (physics against known answers), `test_controls_dyn_tab.py`.

The earlier drawn mechanical-system editor (parts, solver, time response) was removed from this tab; it is in git history (commit daeab49) and
can come back as a section that produces a G(s) when a problem needs it.
