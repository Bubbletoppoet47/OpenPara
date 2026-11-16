# Systems and Controls (playground add-on)

Control-systems tools, added one textbook problem at a time. Tab: **Controls**; files: `.opctl`.

The tab is a column of dropdown sections on the left (one tool each; opening one shows its inputs) and the worked answer and plots for the open
section on the right. Adding a tool = one `Section` class in `controls_tab.py` plus its maths in `ctl_core.py`.

## Sections
* **Transfer function: poles, zeros, gain** - type the numerator and denominator of G(s) (`2s+3`, `s^2+3s+2`, `(s+1)(s+2)`, or `[1 3 2]`).
  Shows G(s) as a fraction, the pole-zero form `K (s - z1)... / ((s - p1)...)` (repeated roots as powers, complex pairs as quadratics), the gain K,
  zeros, poles, DC gain G(0) with the working, stability, order, relative degree, system type, time constants / natural frequency / damping ratio,
  and a pole-zero plot. Flags a pole at the origin (infinite DC gain), cancelling pole and zero, and an improper G(s).
  First test: book example 1.4.5.1, G(s) = (2s+3)/(s^2+3s+2): zero -1.5, poles -1 and -2, K = 2, DC gain 1.5.

## Files
* `ctl_core.py` - maths, no Qt (`parse_poly`, `analyze`, `report`).  `controls_tab.py` - the tab.
* Tests: `test_controls_core.py`, `test_controls_tab.py`.

The earlier drawn mechanical-system editor (parts, solver, time response) was removed from this tab; it is in git history (commit daeab49) and
can come back as a section that produces a G(s) when a problem needs it.
