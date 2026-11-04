"""
sketcher_script.py - plain-text sketch files (APDL-style: one command per line, '!' starts a comment).

One .skt file holds everything: geometry, constraints, dimensions, the symbol table and ALL configurations.

    ! Breezeway left frame
    CONFIG, 120in
    CONFIG, 123in
    ACTIVE, 1
    PARAM, l12, INPUT,  60,   61.5        ! one value per CONFIG, in order
    PARAM, l10, INPUT,  29.5, 29.5
    PARAM, l11, OUTPUT, 33.1, 33.1        ! solved from the inputs
    PARAM, theta1, DEFINE, atand(p)       ! a symbol defined by a formula
    PT,  1, 0, 0                          ! id, x, y  (where it was drawn)
    LINE, 5, 1, 2                         ! id, point, point
    CIRCLE, 7, 3, 2.5                     ! id, centre point, radius
    ARC,  8, 3, 4, 5                      ! id, centre, start, end (counter-clockwise)
    CON, 1, horizontal, ln5
    CON, 2, fixed, pt1, xy=0:0
    DIM, 3, dim_h, ln5, expr=l12, value=60, sign=1, name=H1

References are pt<id>, ln<id>, ci<id>, ar<id>.  Dimensions marked expr=... take their number from the symbol
table for the active configuration.
"""
import re

import sketcher_core as sc
import units

REF = re.compile(r"^(pt|ln|ci|ar)(\d+)$")


def _num(v):
    v = round(float(v), 9) + 0.0        # drop float noise such as 1e-16 and -0.0
    return f"{v:.12g}"


def to_script(m, title="Sketcher script"):
    L = [f"! {title}", "! Commands: UNITS, CONFIG, ACTIVE, PARAM, PT, LINE, CIRCLE, ARC, CONSTRUCTION, CON, DIM   ('!' starts a comment)", "",
         f"UNITS, {units.id_of(m.unit_system)}        ! {m.unit_system}", ""]
    for c in m.configs:
        L.append(f"CONFIG, {c}")
    L.append(f"ACTIVE, {m.active + 1}")
    L.append("")
    for name, p in m.params.items():
        if p.get("expr"):
            L.append(f"PARAM, {name}, DEFINE, {p['expr']}")
        else:
            kind = "INPUT" if p.get("input", True) else "OUTPUT"
            L.append(f"PARAM, {name}, {kind}, " + ", ".join(_num(v) for v in p["vals"]))
    L.append("")
    for pid, (x, y) in m.pts.items():
        if pid == 0:
            continue                      # the origin is implicit
        L.append(f"PT, {pid}, {_num(x)}, {_num(y)}")
    for lid, (a, b) in m.lns.items():
        L.append(f"LINE, {lid}, {a}, {b}")
    for cid, c in m.cis.items():
        L.append(f"CIRCLE, {cid}, {c['c']}, {_num(c['r'])}")
    for aid, a in m.ars.items():
        L.append(f"ARC, {aid}, {a['c']}, {a['s']}, {a['e']}")
    L.append("")
    locks = [f"pt{i}" for i in sorted(m.lock_pts)] + [f"ci{i}" for i in sorted(m.lock_cis)]
    if locks:
        L.append("LOCK, " + ", ".join(locks) + "        ! frozen at the positions given above")
        L.append("")
    if m.constr:
        L.append("CONSTRUCTION, " + ", ".join(f"{k}{i}" for k, i in sorted(m.constr)))
        L.append("")
    for c in m.cons:
        if c.get("origin"):
            continue
        refs = ", ".join(f"{k}{i}" for k, i in c["refs"])
        extra = []
        if c["type"] in sc.DIMENSIONS:
            if c.get("expr"):
                extra.append(f"expr={c['expr']}")
            extra.append(f"value={_num(c['value'])}")
            if "sign" in c:
                extra.append(f"sign={c['sign']}")
            extra.append(f"name={c['name']}")
            if c["type"] == "dim_ang" and "s1" in c:
                extra.append(f"rays={c['s1']}:{c['s2']}:{c['eps']}")
            if "offw" in c:
                extra.append(f"offw={_num(c['offw'])}")        # label distance, in sketch units (zoom-proof)
            if "tpos" in c and abs(c["tpos"] - 0.5) > 1e-6:
                extra.append(f"tpos={_num(c['tpos'])}")
            if "ang" in c and abs(c["ang"] - 45) > 1e-6:
                extra.append(f"ang={_num(c['ang'])}")
            if c.get("align"):                                 # offset dimensions: ends kept straight across, group, hidden member
                extra.append("align=" + ":".join(str(int(k)) for k in c["align"]))
            if c.get("tan") and any(t is not None for t in c["tan"]):
                extra.append("tan=" + ":".join("-" if t is None else str(int(t)) for t in c["tan"]))
            if c.get("grp") is not None:
                extra.append(f"grp={int(c['grp'])}")
            if c.get("hide"):
                extra.append("hide=1")
        elif c["type"] == "fixed":
            extra.append(f"xy={_num(c['xy'][0])}:{_num(c['xy'][1])}")
        elif c["type"].startswith("rigid_"):
            extra.append(f"inst={c['inst']}")
        elif c["type"] == "proj_pt":
            extra.append(f"part={c['part']}")
            extra.append("q=" + ":".join(_num(v) for v in c["q"]))
        cmd = "DIM" if c["type"] in sc.DIMENSIONS else "CON"
        L.append(f"{cmd}, {c['id']}, {c['type']}, {refs}" + ("".join(", " + e for e in extra)))
    for pid, d in m.p3.items():                                   # 3D placed parts seen in this sketch (their points/lines are above)
        L.append(f"P3, {pid}, sig={':'.join(str(v) for v in d['sig'])}, keys=" + ";".join(f"{k}:{v}" for k, v in d["keys"].items()) +
                 ", ents=" + ";".join(f"{k}:" + ":".join(str(i) for i in ids) for k, ids in d["ents"].items()))
    for iid, ins in m.insts.items():                              # placed parts: the geometry itself is above, this is how it is held
        L.append(f"INST, {iid}, src={ins['src']}, view={ins['view']}, flip={int(bool(ins['flip']))}, B={ins['B']}, A={ins['A']}, "
                 f"aloc={_num(ins['A_loc'][0])}:{_num(ins['A_loc'][1])}, "
                 "loc=" + ";".join(f"{p}:{_num(x)}:{_num(y)}" for p, (x, y) in ins["loc"].items()) + ", "
                 "rad=" + ";".join(f"{c}:{_num(r)}" for c, r in ins["rad"].items()) + ", "
                 "keys=" + ";".join(f"{k}:{v}" for k, v in ins["keys"].items()) + ", "
                 "ents=" + ";".join(f"{k}:" + ":".join(str(i) for i in ids) for k, ids in ins["ents"].items()))
    L.append("")
    return "\n".join(L)


class ScriptError(Exception):
    pass


def from_script(m, text):
    """Replace the contents of model m by the script.  Raises ScriptError(line number, message)."""
    m.reset()
    m.units_in_file = False                     # True when the file says which units its numbers are in
    cfg_names, params_raw, lock_refs = [], [], []
    active = 0
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.split("!", 1)[0].strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        cmd, args = parts[0].upper(), parts[1:]
        try:
            if cmd == "UNITS":
                name = units.name_of(args[0])
                if name is None:
                    raise ValueError(f"unknown unit system '{args[0]}'")
                m.unit_system = name
                m.units_in_file = True
            elif cmd == "CONFIG":
                cfg_names.append(args[0])
            elif cmd == "ACTIVE":
                active = int(args[0]) - 1
            elif cmd == "LOCK":
                for a in args:
                    mt = REF.match(a)
                    if not mt or mt.group(1) not in ("pt", "ci"):
                        raise ValueError(f"cannot lock '{a}'")
                    lock_refs.append((mt.group(1), int(mt.group(2))))
            elif cmd == "CONSTRUCTION":
                for a in args:
                    mt = REF.match(a)
                    if not mt or mt.group(1) == "pt":
                        raise ValueError(f"cannot make '{a}' construction")
                    m.constr.add((mt.group(1), int(mt.group(2))))
            elif cmd == "PARAM":
                params_raw.append((n, args))
            elif cmd in ("BOOK", "BOOKSET", "BOOKNAME", "BOOKSRC", "LINK"):
                pass                                         # workbook settings of older versions: no longer used
            elif cmd == "REPORT":
                pass                                         # symbolic-report choice of older versions: no longer used
            elif cmd == "PT":
                m.pts[int(args[0])] = [float(args[1]), float(args[2])]
            elif cmd == "LINE":
                m.lns[int(args[0])] = [int(args[1]), int(args[2])]
            elif cmd == "CIRCLE":
                m.cis[int(args[0])] = {"c": int(args[1]), "r": float(args[2])}
            elif cmd == "ARC":
                m.ars[int(args[0])] = {"c": int(args[1]), "s": int(args[2]), "e": int(args[3])}
            elif cmd in ("CON", "DIM"):
                cid, typ = int(args[0]), args[1].lower()
                if typ not in sc.GEOMETRIC and typ not in sc.DIMENSIONS:
                    raise ValueError(f"unknown constraint type '{typ}'")
                refs, kw = [], {}
                for a in args[2:]:
                    mt = REF.match(a)
                    if mt:
                        refs.append((mt.group(1), int(mt.group(2))))
                    elif "=" in a:
                        k, v = a.split("=", 1)
                        kw[k.strip()] = v.strip()
                    else:
                        raise ValueError(f"cannot read '{a}'")
                c = {"id": cid, "type": typ, "refs": refs}
                if typ in sc.DIMENSIONS:
                    c["value"] = float(kw.get("value", 0))
                    if "expr" in kw:
                        c["expr"] = kw["expr"]
                    if "sign" in kw:
                        c["sign"] = int(kw["sign"])
                    c["name"] = kw.get("name", f"{sc.DIM_PREFIX[typ]}{cid}")
                    if "offw" in kw:
                        c["offw"] = float(kw["offw"])
                    elif "off" in kw:
                        c["off"] = float(kw["off"])          # older file: pixels; converted to sketch units when the view is fitted
                    if "rays" in kw:
                        r = kw["rays"].split(":")
                        c["s1"], c["s2"], c["eps"] = int(r[0]), int(r[1]), int(r[2])
                    if "tpos" in kw:
                        c["tpos"] = float(kw["tpos"])
                    if "ang" in kw:
                        c["ang"] = float(kw["ang"])
                    if kw.get("align"):
                        c["align"] = [int(k) for k in kw["align"].split(":")]
                    if kw.get("tan"):
                        c["tan"] = [None if t == "-" else int(t) for t in kw["tan"].split(":")]
                    if "grp" in kw:
                        c["grp"] = int(kw["grp"])
                    if kw.get("hide") == "1":
                        c["hide"] = True
                elif typ == "fixed":
                    x, y = kw["xy"].split(":")
                    c["xy"] = (float(x), float(y))
                elif typ.startswith("rigid_"):
                    c["inst"] = kw["inst"]
                elif typ == "proj_pt":
                    c["inst"] = "3d"
                    c["part"] = kw["part"]
                    c["q"] = [float(v) for v in kw["q"].split(":")]
                m.cons.append(c)
            elif cmd == "P3":
                kw = {}
                for a in args[1:]:
                    k, v = a.split("=", 1)
                    kw[k.strip()] = v.strip()
                m.p3[args[0]] = sc.fix_p3({
                    "sig": [int(x) for x in kw.get("sig", "").split(":") if x],
                    "keys": {e.split(":", 1)[0]: e.split(":", 1)[1] for e in kw.get("keys", "").split(";") if e},
                    "ents": {e.split(":")[0]: [i for i in e.split(":")[1:] if i] for e in kw.get("ents", "").split(";") if e}})
            elif cmd == "INST":
                kw = {}
                for a in args[1:]:
                    k, v = a.split("=", 1)
                    kw[k.strip()] = v.strip()
                al = kw["aloc"].split(":")
                m.insts[args[0]] = sc.fix_inst({
                    "src": kw["src"], "view": kw["view"], "name": kw.get("name", ""), "flip": kw.get("flip") == "1", "B": kw["B"], "A": kw["A"],
                    "A_loc": (float(al[0]), float(al[1])),
                    "loc": {p[0]: (p[1], p[2]) for p in (e.split(":") for e in kw.get("loc", "").split(";") if e)},
                    "rad": {p[0]: p[1] for p in (e.split(":") for e in kw.get("rad", "").split(";") if e)},
                    "keys": {e.split(":", 1)[0]: e.split(":", 1)[1] for e in kw.get("keys", "").split(";") if e},
                    "ents": {e.split(":")[0]: [i for i in e.split(":")[1:] if i] for e in kw.get("ents", "").split(";") if e}})
            else:
                raise ValueError(f"unknown command '{cmd}'")
        except (IndexError, ValueError, KeyError) as ex:
            raise ScriptError(f"line {n}: {ex}  ->  {raw.strip()}")
    m.configs = cfg_names or ["Config 1"]
    m.active = min(max(active, 0), len(m.configs) - 1)
    for n, a in params_raw:
        try:
            name, kind = a[0], a[1].upper()
            if kind == "DEFINE":
                m.params[name] = {"vals": [0.0] * len(m.configs), "input": False, "expr": ",".join(a[2:])}
            else:
                vals = [float(v) for v in a[2:]] or [0.0]
                vals += [vals[-1]] * (len(m.configs) - len(vals))
                m.params[name] = {"vals": vals[:len(m.configs)], "input": kind != "OUTPUT", "expr": None}
        except (IndexError, ValueError) as ex:
            raise ScriptError(f"line {n}: PARAM {a}: {ex}")
    # validate references and rebuild counters
    tables = {"ln": m.lns, "ci": m.cis, "ar": m.ars}
    m.constr = {r for r in m.constr if r[1] in tables[r[0]]}
    for c in m.cons:
        for k, i in c["refs"]:
            table = {"pt": m.pts, "ln": m.lns, "ci": m.cis, "ar": m.ars}[k]
            if i not in table:
                raise ScriptError(f"constraint {c['id']} refers to missing {k}{i}")
    ids = list(m.pts) + list(m.lns) + list(m.cis) + list(m.ars)
    for k, i in lock_refs:
        if k == "pt" and i in m.pts and i:
            m.lock_pts[i] = list(m.pts[i])
        elif k == "ci" and i in m.cis:
            m.lock_cis[i] = m.cis[i]["r"]
    m.ensure_origin()
    ids = [i for i in ids if i]
    m.nid = (max(ids) if ids else 0) + 1
    m.ncon = (max((c["id"] for c in m.cons), default=0)) + 1
    m.ndim = sum(1 for c in m.cons if c["type"] in sc.DIMENSIONS) + 1
    return m
