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
  (one block or blocks in series, set on the left), Step response, Impulse response (final value dashed). The chosen view is saved in the file.
  A new tool later (Bode, Nyquist, root locus) = one view class plus one entry in `TransferFunctionSection.VIEWS`.
  First test: book example 1.4.5.1, G(s) = (2s+3)/(s^2+3s+2): zero -1.5, poles -1 and -2, K = 2, DC gain 1.5.

* **Mechanical / Electrical systems** - draw the system on a grid (parts palette: source, R, L, C, ground, output probe; or mass, spring, damper,
  wall, force, output) and get G(s) with your part names (`1 / (C L s² + C R s + 1)`) and, once Value cells hold numbers, the poles, the step and
  impulse responses and the plots. The solver is modified nodal analysis in s with exact polynomial algebra (no outside library); a mechanical
  system is solved through the force-current analogy and its output is displacement (velocity / s). The lower-left text also lists the analogy
  (force-voltage): a series R-L-C loop is drawn as one rigid body with spring, damper and mass, and one rigid body as a series loop; other networks
  get the correspondence lines only. Examples: book 1.5.5.2, 1.5.5.3, 1.5.5.4. "Open G(s) in Transfer function" sends the numbers across.
  Electrical and mechanical drawings are kept separately in the file.

## Files
* `ctl_core.py` - transfer-function maths, no Qt (`parse_poly`, `analyze`, `report`, `response_of`).  `ctl_circuit.py` - drawn networks to G(s), no Qt
  (`solve`, `Poly`, analogies, examples).  `ctl_canvas.py` - the drawing surface.  `controls_tab.py` - the tab and its sections.
* Tests: `test_controls_core.py`, `test_controls_circuit.py`, `test_controls_tab.py`, `test_controls_network.py`.

The earlier drawn mechanical-system editor (parts, solver, time response) was removed from this tab; it is in git history (commit daeab49) and
can come back as a section that produces a G(s) when a problem needs it.
