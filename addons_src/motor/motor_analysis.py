"""motor_analysis.py - numbers and plain-words verdicts from recordings and settings (no GUI, no hardware)."""
import json
import math

import motor_model as M


def hall_facts(pole_pairs, speed_turns_s=None):
    """What Hall sensors can give you, for a motor with `pole_pairs`."""
    pp = max(1, int(pole_pairs))
    steps = 6 * pp
    d = {"steps_per_turn": steps, "degrees_per_step": 360.0 / steps, "arc_minutes": 21600.0 / steps}
    if speed_turns_s:
        d["step_rate_hz"] = abs(speed_turns_s) * steps
        d["ms_between_steps"] = 1000.0 / d["step_rate_hz"] if d["step_rate_hz"] else None
    return d


def hall_summary(pole_pairs):
    f = hall_facts(pole_pairs)
    return (f"{f['steps_per_turn']} steps per turn ({f['degrees_per_step']:.2f} degrees each). "
            f"The position is known only to about +/- {f['degrees_per_step'] / 2:.2f} degrees without help; between steps the board interpolates by speed, "
            f"so slow motion is rough and holding still has a dead band of one step.")


def mean_std(xs):
    xs = [float(x) for x in xs]
    if not xs:
        return 0.0, 0.0
    m = sum(xs) / len(xs)
    return m, math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))


def ripple(vels):
    """Speed ripple of a steady run: (mean, std, percent of mean)."""
    m, s = mean_std(vels)
    return m, s, (100.0 * s / abs(m) if abs(m) > 1e-9 else 0.0)


def spectrum_peak(ts, vs):
    """Strongest ripple frequency (Hz) of a speed recording by a plain DFT of the detrended signal; (freq, amplitude)."""
    n = len(vs)
    if n < 16:
        return 0.0, 0.0
    dt = (ts[-1] - ts[0]) / (n - 1)
    m, _ = mean_std(vs)
    x = [v - m for v in vs]
    best, bk = 0.0, 0
    for k in range(1, n // 2):
        re = sum(x[i] * math.cos(2 * math.pi * k * i / n) for i in range(n))
        im = sum(x[i] * math.sin(2 * math.pi * k * i / n) for i in range(n))
        a = 2 * math.hypot(re, im) / n
        if a > best:
            best, bk = a, k
    return bk / (n * dt), best


def hall_verdict(pole_pairs, speed, ts, vs):
    """Plain sentences about a steady-speed recording with Hall sensors (list of (level, text))."""
    out = []
    m, s, pct = ripple(vs)
    out.append(("ok" if pct < 5 else "warn" if pct < 15 else "bad", f"Speed ripple at {m:.2f} turn/s: {pct:.1f}% of the speed (std {s:.3f} turn/s)."))
    f = hall_facts(pole_pairs, m)
    if f.get("step_rate_hz"):
        out.append(("warn" if f["step_rate_hz"] < 100 else "ok",
                    f"At this speed a Hall step arrives every {f['ms_between_steps']:.1f} ms ({f['step_rate_hz']:.0f} steps/s)."
                    + (" Below about 100 steps/s the speed estimate between steps is a guess." if f["step_rate_hz"] < 100 else "")))
    fq, amp = spectrum_peak(ts, vs)
    if amp > 0 and f.get("step_rate_hz") and abs(fq - f["step_rate_hz"] / 6 * 1) < 0.2 * f["step_rate_hz"] / 6 + 1e-9:
        out.append(("warn", f"The ripple repeats about {fq:.1f} times a second, once per electrical turn: the Hall edges are not evenly spaced (normal for cheap sensors)."))
    return out


def lowest_usable_speed(pole_pairs, min_step_hz=100.0):
    """Speed (turn/s) below which Hall steps come slower than `min_step_hz`."""
    return min_step_hz / (6 * max(1, int(pole_pairs)))


# -- configuration backup ---------------------------------------------------------------------------------------------------------
def backup(link):
    """{path: value} for every setting the board has."""
    d = {}
    for f in M.ALL_FIELDS:
        v = link.get(f.path)
        if v is not None:
            d[f.path] = v
    return d


def backup_text(link, meta=None):
    return json.dumps({"format": "openpara-motor-config", "version": 1, "meta": meta or {}, "settings": backup(link)}, indent=2)


def restore_plan(text, link):
    """Compare a backup file to the board: [(field, saved, now)] of what would change; raises ValueError for a wrong file."""
    try:
        d = json.loads(text)
    except Exception as e:
        raise ValueError("That is not a Motor Control settings file.") from e
    if not isinstance(d, dict) or d.get("format") != "openpara-motor-config":
        raise ValueError("That is not a Motor Control settings file.")
    by = {f.path: f for f in M.ALL_FIELDS}
    out = []
    for p, v in d.get("settings", {}).items():
        if p in by:
            out.append((by[p], v, link.get(p)))
    return out


def restore(text, link):
    n = 0
    for f, saved, now in restore_plan(text, link):
        if now is None:
            continue
        if saved != now:
            link.set(f.path, saved)
            n += 1
    return n


def check_settings(vals):
    """Warnings about a settings dict {path: value} before calibration - list of (level, text)."""
    out = []
    g = lambda p: vals.get(p)
    mode, cpr, pp = g(M.a("encoder.config.mode")), g(M.a("encoder.config.cpr")), g(M.a("motor.config.pole_pairs"))
    ign = g(M.a("encoder.config.ignore_illegal_hall_state"))
    if mode == M.HALL_MODE and cpr is not None and pp:
        c, p6, p4 = int(cpr), 6 * int(pp), 4 * int(pp)
        if c == p4 and ign:
            out.append(("warn", f"{c} counts per turn = 4 x pole pairs: right for 60-degree Hall sensors (states 0 and 7 are skipped). That is only 4 uneven steps per "
                                "electrical turn, so position and speed are coarse."))
        elif c != p6:
            out.append(("warn", f"Hall sensors normally need counts per turn = 6 x pole pairs = {p6} (120-degree sensors), or 4 x pole pairs = {p4} for 60-degree sensors "
                                f"with 'ignore illegal Hall states' on. You have {c}; the board may refuse to calibrate (sensor error)."))
    bw = g(M.a("encoder.config.bandwidth"))
    if mode == M.HALL_MODE and bw is not None and bw > 300:
        out.append(("warn", f"A sensor filter bandwidth of {bw:g} rad/s is high for Hall sensors: the speed reading gets jumpy. Try 50 to 200."))
    cur = g(M.a("motor.config.current_lim"))
    if cur is not None and cur > 40:
        out.append(("warn", f"A current limit of {cur:g} A is high for a first test: start with a few amps."))
    cal = g(M.a("motor.config.calibration_current"))
    if cur is not None and cal is not None and cal > cur:
        out.append(("warn", "The calibration current is above the current limit."))
    return out


def hall_wiring(states):
    """Verdict from the Hall states seen while the motor was turned by hand (list of ints): (all_ok, [(level, text)])."""
    states = [int(x) for x in states if x is not None]
    seen = set(states)
    flips = [bin(x ^ y).count("1") for x, y in zip(states, states[1:]) if x != y]
    if {0, 7} <= seen and len(seen) == 6 and flips and all(f == 1 for f in flips):
        return True, [("ok", "The sensors work and are the 60-degree type: states 0 and 7 are normal for them. The board expects 120-degree sensors (states 1 to 6), so it "
                             "needs 'ignore illegal Hall states' on and counts per turn = 4 x pole pairs (coarse). Inverting one sensor signal would make them 120-degree.")]
    valid = {x for x in states if x in M.HALL_LEGAL}
    if not states:
        return False, [("warn", "No Hall readings: this board does not report them.")]
    if not valid:
        return False, [("bad", f"The Hall state stayed at {states[-1]} (legal states are 1 to 6). No sensor signal is changing: check the 5 V and ground to the "
                               "sensor board and each of the three signal wires.")]
    out = []
    dead = [n for bit, n in ((1, "A"), (2, "B"), (4, "C")) if len({(x & bit) > 0 for x in valid}) < 2]
    for n in dead:
        out.append(("bad", f"Sensor {n} never changed: its wire is loose or stuck."))
    if len(valid) == 6:
        out.append(("ok", "All six Hall states were seen: the three sensors are wired and working."))
        return True, out
    miss = sorted(set(M.HALL_LEGAL) - valid)
    out.append(("warn" if not dead else "bad", f"Only {len(valid)} of 6 states were seen (missing {', '.join(map(str, miss))}). Turn the motor a full turn, slowly, or check the wiring."))
    return False, out
