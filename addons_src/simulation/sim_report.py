"""
sim_report.py - the one look of the result text of the 1D FEA, 2D FEA and 3D FEA windows (rich text for a QLabel), in the program's global units.

Blocks:  Summary (the numbers you read results for) - Probe - Mesh refinement - Solver check.  Each block is a small heading with one value per line,
the unit in grey beside it; no run-on lines.  The builders return HTML; nothing here touches a window.
"""

TEAL = "#0b6b73"
GREY = "#808080"
RED = "#b00020"
AMBER = "#b36b00"
GREEN = "#1d6b2f"


def num(v, sig=5):
    """A number for reading: 5 significant figures, scientific for very small / large values; None -> n/a."""
    if v is None:
        return "n/a"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return str(v)
    if v != v:
        return "n/a"
    if v == 0:
        return "0"
    a = abs(v)
    if a < 1e-4 or a >= 1e7:
        return f"{v:.{sig - 1}e}".replace("e-0", "e-").replace("e+0", "e+")
    return f"{v:.{sig}g}"


def unit(u):
    return f" <span style='color:{GREY}'>{u}</span>" if u else ""


def heading(title, sub=None):
    t = f"<p style='margin-top:12px; margin-bottom:3px'><b style='color:{TEAL}'>{title}</b>"
    if sub:
        t += f" <span style='color:{GREY}'>{sub}</span>"
    return t + "</p>"


def subhead(title, u=None):
    return f"<p style='margin-top:6px; margin-bottom:1px'><b>{title}</b>" + (f" <span style='color:{GREY}'>({u})</span>" if u else "") + "</p>"


def note(text, color=GREY):
    return f"<p style='margin-top:2px; margin-bottom:2px'><span style='color:{color}'>{text}</span></p>"


def chip(text, kind="ok"):
    bg, fg = {"ok": ("#e3f4e6", GREEN), "warn": ("#fff0d6", AMBER), "bad": ("#fde0e0", RED)}[kind]
    return f"<span style='background-color:{bg}; color:{fg}'>&nbsp;<b>{text}</b>&nbsp;</span>"


def kv(rows, bold=False):
    """rows: (label, value text, unit or None).  A two column table, values right aligned."""
    out = ["<table width='100%' cellspacing='0' cellpadding='2'>"]
    for lab, val, u in rows:
        v = f"<b>{val}</b>" if bold else val
        out.append(f"<tr><td>{lab}</td><td align='right'>{v}{unit(u)}</td></tr>")
    out.append("</table>")
    return "".join(out)


def temp_text(k, digits=5):
    """A temperature given in kelvin in the degree of File > Units (degC when the heat-transfer units are not there)."""
    try:
        import thermal_units as tu
        import unitctl
        return tu.temp_text(k, tu.family_of(unitctl.system()), digits)
    except Exception:                                  # noqa: BLE001
        return f"{k - 273.15:.{digits}g} \u00b0C"


def thermal_block(th):
    """The 'Temperature' block of a stress result that was solved with a temperature field.  th = {"T_min", "T_max" (kelvin), and when known "alpha_min", "alpha_max" (1/K),
    "Tref_min", "Tref_max" (kelvin)}."""
    def rng(a, b, f):
        return f(a) if abs(b - a) <= 1e-12 * max(1.0, abs(a)) else f(a) + " to " + f(b)
    rows = [("Temperature of the body", rng(th["T_min"], th["T_max"], temp_text), None)]
    if th.get("Tref_min") is not None:
        rows.append(("Free of thermal stress at", rng(th["Tref_min"], th["Tref_max"], temp_text), None))
    if th.get("alpha_min") is not None:
        rows.append(("Thermal expansion coefficient", rng(th["alpha_min"], th["alpha_max"], lambda v: f"{v:.4g}"), "1/K"))
    return heading("Temperature", "from Coupled Physics") + kv(rows) + note(
        "The stress comes from the strain that the temperature does NOT account for: a body that is free to grow and has the same temperature everywhere has none.")


def grid(headers, rows):
    out = ["<table width='100%' cellspacing='0' cellpadding='3'><tr>"]
    for i, h in enumerate(headers):
        out.append(f"<th align='{'left' if i == 0 else 'right'}'><span style='color:{GREY}'>{h}</span></th>")
    out.append("</tr>")
    for r in rows:
        out.append("<tr>" + "".join(f"<td align='{'left' if i == 0 else 'right'}'>{c}</td>" for i, c in enumerate(r)) + "</tr>")
    out.append("</table>")
    return "".join(out)


def fos_rows(yield_, ult):
    def one(v):
        if v is None:
            return "n/a"
        col = RED if v < 1 else GREEN
        return f"<span style='color:{col}'>{num(v, 4)}</span>"
    return [("Safety factor, yield", one(yield_), None), ("Safety factor, ultimate", one(ult), None)]


# ---------------------------------------------------------------------------------------------------------------- blocks
def summary(fos_y, fos_u, rows):
    """fos_y / fos_u numbers or None; rows: (label, value text, unit) lines under them."""
    return heading("Summary") + kv(fos_rows(fos_y, fos_u), bold=True) + kv(rows)


def refine_block(entries, why, ok, u_len, u_str, tol_pct=None):
    """entries: [{"pass", "n", "umax", "vmax", "change" (fraction or None), "skipped"}]."""
    rows = []
    for e in entries:
        if e.get("skipped"):
            rows.append([str(e["pass"]), f"{e['n']:,}", "over your limit", "not used"])
            continue
        rows.append([str(e["pass"]), f"{e['n']:,}", num(e["umax"], 4), num(e["vmax"], 5)])
    out = heading("Mesh refinement") + grid(["Pass", "Elements", f"Max |u| ({u_len})", f"Max von Mises ({u_str})"], rows)
    last = next((e for e in reversed(entries) if e.get("change") is not None), None)
    if last is not None:
        out += note(f"Change between the last two meshes: {100 * last['change']:.2f} %" + (f" (limit {tol_pct:g} %)" if tol_pct else ""))
    out += f"<p style='margin-top:4px'>{chip('Converged', 'ok') if ok else chip('Not converged', 'warn')} {why}</p>"
    return out


def solver_block(solver, residual, balance_ok, sums, extra=None):
    """sums: text such as 'ΣFx 2.6e-10, ΣFy 2.0e-9'."""
    rows = [("Solver", solver, None), ("Residual", num(residual, 3), None),
            ("Force balance", chip("OK", "ok") + " sums ≈ 0" if balance_ok else chip("CHECK", "bad"), None)]
    out = heading("Solver check") + kv(rows)
    if sums:
        out += note(sums)
    if not balance_ok:
        out += note("The residual or the force balance is too large, so this result cannot be trusted. Check that the supports stop all "
                    "rigid-body motion.", RED)
    for x in extra or []:
        out += note(x, AMBER)
    return out


def probe_block(title, where, disp_rows, stress_rows, u_len, u_str, foot=None, extra_rows=None):
    """A node probe.  disp_rows / stress_rows: (label, value text, None)."""
    out = heading(title) + note(where)
    out += subhead("Displacement", u_len) + kv(disp_rows)
    out += subhead("Stress", u_str) + kv(stress_rows)
    if extra_rows:
        out += kv(extra_rows)
    if foot:
        out += note(foot)
    return out
