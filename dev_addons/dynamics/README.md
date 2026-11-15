# System dynamics (playground add-on)

Drag-and-drop mechanical systems, straight-line **and** turning, solved as a linear state-space model. Tab: **Dynamics**; files: `.opdyn`.

* **Parts**: translational - mass, spring, damper, force source, fixed wall, lever; rotational - inertia, torsional spring, rotational damper,
  torque source, fixed frame, gear pair, link / arm (hangs from its pivot, gravity linearised); couplers - rack and pinion (turning <-> straight);
  actuators - DC motor with gearbox (resistance, inductance, Kt, Ke, rotor inertia and friction reflected through N²).
* **Drawing**: same as Circuits. Drag parts from the list, wire pin to pin (blue pins are translational, orange are rotational; joining the two
  is flagged), `R` rotate, `F` mirror, `Delete`, `Ctrl+Z / Ctrl+Y`, values accept `4.7k`, `100m`, `2meg`.
* **Equations tab**: the coordinates, the equation of motion of every coordinate (`M q'' + D q' + K q = sources`), the motor equations, M / D / K and
  the state-space A and B matrices.
* **Modes tab**: the poles, natural frequency wn, damping ratio zeta, damped frequency, time constants; undamped natural frequencies.
* **Response tab** (Run): position, velocity or acceleration of any mass / inertia / link / motor shaft against time, with final value, overshoot and
  2 % settling time. Sources are a step, sine, square, ramp or pulse.

## Method (`dyn_core.py`, no Qt)
Mobility analogy: nodes carry (angular) velocity. Walls, gears, levers and rack-and-pinion are ideal ratios between nodes and are eliminated first
(`v_node = T . u`). Masses give `M`, dampers `D`, springs and link gravity `K`; the state is `[q; u; motor currents]` and the response is computed
exactly (matrix exponential, inputs held within a step).  A node that has no mass or inertia is reported (it would need a rigid link or an algebraic
equation); that, a planar rigid-body mode (`M(q) q'' + C q' + G(q) = tau`), controllers and hard stops, Bode / Nyquist / root locus and the
optimiser (critical damping, target values with free-value limits) are the next steps.
