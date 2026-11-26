"""coupled_handover.py - what the Coupled Physics window hands over from one analysis to another, as rows an analysis shows in its own Outline: the green, locked rows ("Air pressure · from Air
flow" under Loads of the stress analysis, "Air film · from Air flow" under Conditions of the heat analysis, ...).  No Qt: it reads the windows of the analyses (the 2D ones) and the options of the
block, and gives plain dicts, so that a test can look at them.

A row says what is handed over, from which analysis, and WHERE (the edges, or the whole body); the window of the analysis draws those edges in green while the row is selected.  Nothing is
solved to make a row: the edges are the ones the engine will use (the walls of the fluid that the heat exchange covers; the walls of the fluid that the stress analysis has and no support holds;
the whole body for the temperature), read from the setup as it is now.  A row is only listed when the analysis it comes from is wired in, so a window shown on its own has none.

A row:  {"what", "name", "type", "where", "value", "note", "keys", "arrows", "dashed"}   keys: the edge keys (kind, id) or None for the whole body; arrows: draw the pressure arrows;
dashed: draw the edges dashed (the air on the heat analysis)."""

NAMES = {"pt": "Point", "ln": "Line", "ar": "Arc", "ci": "Circle"}
WHAT = ("wall_temperature", "moved_walls", "air_film", "air_pressure", "body_temperature")


def edges_text(keys):
    """'Line 5, 6, 7' / 'Line 5 and Arc 2' (grouped by kind, in order); 'the whole body' for None."""
    if keys is None:
        return "the whole body"
    groups = {}
    for k in sorted(tuple(k) for k in keys):
        groups.setdefault(k[0], []).append(k[1])
    order = [k for k in ("ln", "ar", "ci", "pt") if k in groups] + sorted(k for k in groups if k not in ("ln", "ar", "ci", "pt"))
    parts = []
    for kind in order:
        parts.append(NAMES.get(kind, str(kind)) + " " + ", ".join(str(i) for i in groups[kind]))
    return " and ".join(parts)


def own_edges(tab):
    """The keys of the edges of the sketch of a 2D analysis (a set; empty without geometry)."""
    g = getattr(tab, "geom", None)
    return {tuple(e["src"]) for e in g["edges"]} if g is not None else set()


def held_edges(tab):
    """The edges a support of the stress analysis holds (they get no pressure)."""
    out = set()
    for s in getattr(tab, "supports", None) or ():
        for k in s.get("targets") or ():
            out.add((k[0], k[1]))
    return out


def flow_walls(fl):
    """The keys of the walls of the fluid analysis: the edges of the bodies in the flow (known once the flow is meshed), else the ones its heat conditions name."""
    sel = None
    try:
        sel = fl.selectable()
    except Exception:                                                  # noqa: BLE001 - a window that is being rebuilt has no walls yet
        sel = None
    if sel:
        return {tuple(k) for k in sel}
    try:
        return {tuple(k) for k in fl.coupled_keys()}
    except Exception:                                                  # noqa: BLE001
        return set()


def row(what, name, source, keys, value, note, arrows=False, dashed=False):
    keys = None if keys is None else sorted(tuple(k) for k in keys)
    where = edges_text(keys)
    return {"what": what, "name": name, "type": f"from {source}", "where": where, "value": value, "keys": keys, "arrows": bool(arrows), "dashed": bool(dashed),
            "note": note.replace("{where}", where)}


def set_by_hand(tab, keys):
    """True when a condition set by hand in the analysis (a support / temperature or a load) is on one of the edges `keys`."""
    ks = {tuple(k) for k in keys}
    for lst in (getattr(tab, "supports", None) or (), getattr(tab, "loads", None) or ()):
        for it in lst:
            if any((t[0], t[1]) in ks for t in it.get("targets") or ()):
                return True
    return False


def rows_for(role, tabs, labels, options=None):
    """The rows the analysis `role` ('fluid', 'thermal', 'structural') shows.  tabs: {role: the 2D window of the analysis, or None}; labels: {role: its name}; options: those of the block."""
    opt = options or {}
    fl, th, st = tabs.get("fluid"), tabs.get("thermal"), tabs.get("structural")
    lf, lt, ls = labels.get("fluid") or "the fluid", labels.get("thermal") or "the heat analysis", labels.get("structural") or "the stress analysis"
    out = []
    if role == "fluid" and fl is not None:
        if th is not None:
            keys = [k for k in fl.coupled_keys()]
            if keys:
                out.append(row("wall_temperature", "Walls of the thermal analysis", lt, keys, "gives and takes heat",
                               f"Handed over, not set here. At every pass of the coupled solve ‘{lt}’ gives this analysis the temperature of its wall on {{where}}; the heat the fluid takes goes back to it. "
                               "Which walls these are is set on the Fluid and flow page (Wall of the thermal analysis); the exchange is solved in the Coupled tab."))
        if st is not None and opt.get("moves_flow"):
            keys = sorted(flow_walls(fl) & own_edges(st))
            if keys:
                out.append(row("moved_walls", "Moved walls", ls, keys, "every pass",
                               f"Handed over, not set here. ‘{ls}’ moves the body by its displacement, and the flow is solved again round the moved body: the walls on {{where}}. "
                               "It is switched on and off in the Coupled tab (the structure moves the flow)."))
    elif role == "thermal" and th is not None and fl is not None:
        keys = sorted({tuple(k) for k in fl.coupled_keys()} & own_edges(th))
        if keys:
            out.append(row("air_film", "Heat exchange with the air", lf, keys, "h and air temperature",
                           f"Handed over, not set here. On {{where}} the heat leaves the body into the air of ‘{lf}’: a film coefficient and an air temperature that the flow gives at every pass."
                           + (" A condition you set by hand on one of these edges is replaced by the air in the Coupled solve." if set_by_hand(th, keys) else ""), dashed=True))
    elif role == "structural" and st is not None:
        if fl is not None:
            keys = sorted((flow_walls(fl) & own_edges(st)) - held_edges(st))
            if keys:
                out.append(row("air_pressure", "Pressure of the air", lf, keys, "every pass",
                               f"Handed over, not set here. ‘{lf}’ pushes on {{where}} with the pressure of its settled flow. Edges a support holds get none. "
                               "The flow is solved in the Coupled tab.", arrows=True))
        if th is not None:
            out.append(row("body_temperature", "Temperature", lt, None, "from the heat result",
                           f"Handed over, not set here. The temperature field of ‘{lt}’ is given to every node of this body; the thermal expansion coefficient and the reference temperature "
                           "are the ones of the material on the Material and analysis page."))
    return out


def same(a, b):
    """Are two lists of rows the same rows (the same thing, from the same place, on the same edges)?"""
    key = lambda r: (r["what"], r["name"], r["type"], r["where"], r["value"], r["note"], tuple(map(tuple, r["keys"])) if r["keys"] is not None else None, r["arrows"], r["dashed"])   # noqa: E731
    return [key(x) for x in (a or ())] == [key(x) for x in (b or ())]


def apply(tab, rows):
    """Gives the window of an analysis its rows.  The rows it has are kept (the same objects, so that a row selected in the Outline stays selected) when nothing changed.  -> True when it changed."""
    old = getattr(tab, "handover", None) or []
    if same(old, rows):
        return False
    tab.handover = list(rows)
    return True
