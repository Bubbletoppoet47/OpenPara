"""coupled_steps.py - the passes of a coupled solve in the order they ran, in plain words: what the Solve page of the Coupled Physics window lists under the Solve button.  No Qt: it reads
the result of coupled_engine.solve_coupled (and the options of the window) and gives rows (key, what happened, how much) that a test can look at.  Nothing is worked out here that the engine
did not already report: a row is only listed when the part of the solve it names ran (no fluid wired in: no row about the flow)."""


def seconds_text(x):
    """'0.02 s', '40 s' (two figures), or '' when there is no time."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return ""
    return f"{x:.2g} s"


def step_rows(res, options=None):
    """[(key, title, detail)] in the order the passes of the loop ran, from a result of solve_coupled.  `options` is the window's options (the limits the passes were held to: fsi_max, fsi_tol_pct).
    An empty list for no result."""
    if not res:
        return []
    opt = options or {}
    fl, th, st, fs = res.get("fluid"), res.get("thermal"), res.get("structural"), res.get("fsi")
    rows = []
    if fl:
        flow = f"{fl['steps']} steps" if fl.get("steps") else str(fl.get("status", ""))
        rows.append(("flow", "Flow round the body", flow))
        if "iterations" in fl:
            rows.append(("heat", "Heat exchange, solid ⇄ air", f"{fl['iterations']} iterations"))
    elif th:
        rows.append(("heat", "Heat analysis", seconds_text(th.get("seconds"))))
    if st:
        what = []
        if fl:
            what.append("pressure")
        if th:
            what.append("temperature")
        if what:
            rows.append(("handover", " and ".join(what).capitalize() + " to the structure", "handed over"))
        rows.append(("stress", "Stress analysis", seconds_text(st.get("seconds"))))
    if fs:
        n = int(fs["iterations"])
        rows.append(("moved", "Body moved, flow solved again", f"pass {n} of at most {int(opt.get('fsi_max', fs.get('limit', n)))}" if len(fs.get("history", [])) > 1 or n > 1 else "no movement to follow"))
        last = (fs.get("history") or [{}])[-1].get("change")
        tol = fs.get("tol")
        if last is not None and n > 1:
            rows.append(("settled", "Displacement stopped changing" if fs.get("converged") else "Displacement did not stop changing",
                         f"{100 * float(last):.2g} %" + (f" (limit {100 * float(tol):g} %)" if tol is not None else "")))
    return rows


def header_text(res):
    """The line above the rows: 'Solved in 40 s. Passes of the loop, in order:'."""
    if not res:
        return ""
    return f"Solved in {seconds_text(res.get('seconds'))}. Passes of the loop, in order:" if res.get("ok", True) else \
           f"Solved in {seconds_text(res.get('seconds'))}, but a check that stops the result failed. Passes of the loop, in order:"


def live_rows(texts, keep=40):
    """[(done, text)] for the list of messages the engine sent while it ran (each message a step of the solve, in order, the same message twice in a row counted once): every step but the last is
    done, the last is what is being worked on now.  At most `keep` rows (the earliest are dropped).  The engine's own words: nothing is added to them."""
    rows, last = [], None
    for t in texts:
        t = str(t).strip()
        if not t or t == last or t.lower() in ("done", "done."):
            continue
        rows.append(t)
        last = t
    rows = rows[-int(keep):]
    return [(i < len(rows) - 1, t) for i, t in enumerate(rows)]
