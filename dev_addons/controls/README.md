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

* **Dynamic simulation: balance a drawn system** - draw a mechanism in 2-D from preset parts, say what it should do, and the program **learns the PID
  gains itself**. You give the *geometry* (parts: **Wheel** that rolls without slipping, **Cart**, **Pivot**, **Link** (a rod pinned to the picked part),
  **Mass**, and one ideal **motor** with a maximum torque, which is the hardware limit), the *objective* (reach and hold a goal x: a fixed point, a step, or a ramp
  at a speed) and the *condition* (it must not tip past the fall angle, default 45 degrees, or touch the ground). Connection rules are checked in plain words.
  **Learn** starts from a linear-quadratic design for the drawing and then tries gains by a CMA-ES search over the four gains of the controller (an inner tilt PD
  with the derivative on the measured rate, anti-windup and the motor limit, plus an outer position PD that turns the error from the goal into a tilt target). Each
  candidate is one **trial**: a full non-linear run (RK4, controller at its own sample rate). A trial that tips or touches the ground fails and new gains are tried;
  one that balances is scored on tracking, overshoot, settling, tilt, motor effort and chatter, and is also run from the other side and with a push, so the gains
  are not tuned to one lucky start. It stops when you press **Stop**, when the trial limit is reached (default 400), when the best gains stop improving, or when
  they are **critically damped or better** (every closed-loop pole has damping ratio at least 0.95 and the run overshoots by under 2 %). **Continue learning**
  carries on; changing the drawing or the goal starts afresh. The best gains are written into the controller as one undo step and the best run is shown with plots
  of tilt, position against its goal and motor effort. You watch it either **in the background** (full speed; trials are replayed quickly on the drawing, every
  trial, every 10th, or only the new bests, a little behind the learning) or **live at real-time speed** (every trial plays in real time at 1x, 2x or 5x and the learner
  waits for the screen; a trial lasts as long as its run, 10 s for the example); the choice can be flipped while it runs. A score graph shows every trial (green
  balanced, red failed) with the best so far. The learned gains are under **Advanced**, read-only unless you tick *Set the gains by hand*; there you can also press
  **Suggest gains**, **Run** once with a start tilt and a push, and **Open G(s) in Transfer function** (poles, zeros and the Routh test).
  For now Learn is set up for the self-balancing robot (one wheel with one body link); a drawing with a cart or a pivot is refused in plain words, and its gains
  are set by hand (the engine, with the cart and pendulum examples, is tested and ready for when a project needs it). Units are SI (File > Units does not apply here yet).
  Limits: one base, a tree of links (no closed loops), one motor, ideal sensors, no wheel slip; the learning runs use a slightly coarser physics step and the answer is
  re-run with the normal one.

## Files
* `ctl_core.py` - transfer-function maths, no Qt (`parse_poly`, `analyze`, `report`, `response_of`).  `ctl_circuit.py` - drawn networks to G(s), no Qt
  (`solve`, `Poly`, analogies, examples).  `ctl_canvas.py` - the drawing surface.  `controls_tab.py` - the tab and its sections.
  `ctl_section.py` - the Section base class and axis ticks.  `ctl_dyn.py` - the dynamics engine, no Qt (sketch data, plain-word checks, equations of motion, run, linearise, gains, examples).
  `ctl_learn.py` - the gain learner, no Qt (`Learner`, the CMA-ES search, the score, `Worker` for the background thread).  `ctl_dyn_view.py` - the animation canvas,
  signal plots and score graph.  `ctl_dyn_section.py` - the Dynamic simulation section; `ctl_dyn_learn_ui.py` - its Learn panel and trial replay; `ctl_dyn_widgets.py` - shared fields.
* Tests: `test_controls_core.py`, `test_controls_circuit.py`, `test_controls_tab.py`, `test_controls_network.py`, `test_controls_dyn.py` (physics against known answers), `test_controls_learn.py` (the learner), `test_controls_dyn_tab.py`.

The earlier drawn mechanical-system editor (parts, solver, time response) was removed from this tab; it is in git history (commit daeab49) and
can come back as a section that produces a G(s) when a problem needs it.
