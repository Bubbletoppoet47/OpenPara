"""lab_matrix.py - the Constraint Lab's yardstick: the Mate Matrix.

For one mate engine (a module with Assembly, face_ref, edge_ref, vertex_ref and MateError: core/asm_model.py or the lab's lab_engine.py) it tries every
kind of pick against every kind of pick, for every mate type, from several starting poses, and records what happened:

    ok     the mate was not satisfied at the start, the solve said yes, the mate is satisfied now and the part moved
    FAIL   the solve said no, or it left the mate unsatisfied
    STILL  the solve said yes but nothing moved although the mate was not satisfied (the "it does not move at all" bug)
    noop   the mate was already satisfied at the start (nothing to test)
    ERR    the engine says this pick pair does not make sense for this mate (a MateError: "tangent cannot mate a plane with a point")
    EXC    the engine crashed with something that is not a MateError (a bug to fix)

The moving part is the first pick, the fixed part carries the second pick.  The parts are plain solids made here with build123d (no files).
No GUI in here, so tests and the lab window can both use it."""
import collections
import time

import numpy as np

KINDS = ["plane", "line", "point", "axis", "circle", "sphere"]
MATES = ["coincident", "parallel", "perpendicular", "tangent", "concentric", "distance", "angle"]
# the part that supplies each kind of pick on the moving side (A) and on the fixed side (B)
A_PART = {"plane": "block", "line": "block", "point": "block", "axis": "pin", "circle": "pin", "sphere": "ball"}
B_PART = {"plane": "plate", "line": "plate", "point": "plate", "axis": "plate", "circle": "plate", "sphere": "ball2"}
OUTCOMES = ("ok", "FAIL", "STILL", "noop", "ERR", "EXC")
TOL = 1e-4
TARGET_DISTANCE, TARGET_ANGLE = 7.0, 30.0              # the values the distance and angle mates are asked for (mm, degrees)

_parts = {}


def parts():
    """The five test solids (made once): a plate with a hole, a block, a pin that fits the hole, two balls."""
    if not _parts:
        from build123d import Box, Cylinder, Sphere
        _parts.update({"plate": Box(80, 80, 10) - Cylinder(10, 30), "block": Box(30, 30, 30), "pin": Cylinder(9.9, 40),
                       "ball": Sphere(12), "ball2": Sphere(15)})
    return _parts


def starts():
    """Six starting poses of the moving part: three near, two far and rotated, and one exactly at the origin (the same every run)."""
    rng = np.random.default_rng(11)
    out = []
    for k in range(5):
        far = k >= 3
        out.append((rng.uniform(-300 if far else -60, 300 if far else 60, 3), rng.uniform(-2.5 if far else -0.6, 2.5 if far else 0.6, 3)))
    out.append((np.array([0.0, 0.0, 0.0]), np.zeros(3)))
    return out


def pick(mod, solid, kind, which=0):
    """(ref kind, ref data) of the first plane / cylinder / sphere face, straight / circular edge or vertex of the solid, in the engine's own format."""
    fs, es, vs = solid.faces(), solid.edges(), solid.vertices()
    if kind == "plane":
        pl = [f for f in fs if f.geom_type.name == "PLANE"]
        return "face", mod.face_ref(pl[which % len(pl)])
    if kind == "axis":
        return "face", mod.face_ref([f for f in fs if f.geom_type.name == "CYLINDER"][0])
    if kind == "sphere":
        return "face", mod.face_ref([f for f in fs if f.geom_type.name == "SPHERE"][0])
    if kind == "line":
        ln = [e for e in es if e.geom_type.name == "LINE"]
        return "edge", mod.edge_ref(ln[which % len(ln)])
    if kind == "circle":
        ci = [e for e in es if e.geom_type.name == "CIRCLE"]
        return "edge", mod.edge_ref(ci[which % len(ci)])
    return "vertex", mod.vertex_ref(vs[which % len(vs)])


def one_case(mod, ka, kb, ty, pos, rv):
    """Run one mate from one start pose; returns (outcome, message)."""
    P = parts()
    A = mod.Assembly()
    A.solid_fn = lambda c: P[c["path"]]
    fixed = A.add_component(B_PART[kb], fixed=True)
    mover = A.add_component(A_PART[ka], pos=tuple(pos), fixed=False)
    mover["rv"] = list(rv)
    ra, rb = pick(mod, P[A_PART[ka]], ka), pick(mod, P[B_PART[kb]], kb)
    target = {"distance": {"value": TARGET_DISTANCE}, "angle": {"value": TARGET_ANGLE}}.get(ty, {})      # without a target they would "ask" for the current value: nothing to test
    m = A.add_mate(ty, [{"c": mover["id"], "k": ra[0], "r": ra[1]}, {"c": fixed["id"], "k": rb[0], "r": rb[1]}], **target)
    before = np.array(mover["pos"]), np.array(mover["rv"])
    try:
        A.prepare(m)
        r0 = float(np.max(np.abs(A.mate_residual(m))))
        ok = A.solve(extra=[m])
        r1 = float(np.max(np.abs(A.mate_residual(m))))
        moved = float(np.linalg.norm(np.array(mover["pos"]) - before[0])) + float(np.linalg.norm(np.array(mover["rv"]) - before[1]))
        if r0 <= TOL:
            return "noop", ""
        if ok and r1 <= TOL and moved > 1e-6:
            return "ok", ""
        if ok and moved <= 1e-6:
            return "STILL", ""
        return "FAIL", ""
    except mod.MateError as ex:
        return "ERR", str(ex)
    except Exception as ex:
        return "EXC", type(ex).__name__ + ": " + str(ex)[:80]


def run(mod, mates=None, kinds=None, n_starts=None, progress=None):
    """{"cells": {(first kind, second kind, mate): [outcome per start]}, "msgs": {(first, second, mate): {messages}}, "seconds": s, "cancelled": bool}.
    progress(done, total) is called after every pick pair and may return True to stop."""
    mates, kinds = list(mates or MATES), list(kinds or KINDS)
    st = starts()[:n_starts] if n_starts else starts()
    cells, msgs = {}, collections.defaultdict(set)
    total, done, t0, cancelled = len(kinds) * len(kinds) * len(mates), 0, time.time(), False
    for ka in kinds:
        for kb in kinds:
            for ty in mates:
                res = []
                for pos, rv in st:
                    o, msg = one_case(mod, ka, kb, ty, pos, rv)
                    res.append(o)
                    if msg:
                        msgs[(ka, kb, ty)].add(msg)
                cells[(ka, kb, ty)] = res
                done += 1
                if progress is not None and progress(done, total):
                    cancelled = True
                    break
            if cancelled:
                break
        if cancelled:
            break
    return {"cells": cells, "msgs": dict(msgs), "seconds": time.time() - t0, "cancelled": cancelled, "mates": mates, "kinds": kinds, "n_starts": len(st)}


def short(res):
    """One grid cell: the single outcome, or each outcome with its count (most common first), e.g. ok4/FAIL2."""
    c = collections.Counter(res)
    if len(c) == 1:
        return next(iter(c))
    return "/".join(f"{k}{v}" for k, v in c.most_common())


def totals(result, ty=None):
    """Counts of every outcome over all runs of one mate type (or of all of them) and the score = ok / (ok + FAIL + STILL), None when nothing was solvable."""
    c = collections.Counter()
    for (ka, kb, t), res in result["cells"].items():
        if ty is None or t == ty:
            c.update(res)
    solvable = c["ok"] + c["FAIL"] + c["STILL"]
    c["score"] = (c["ok"] / solvable) if solvable else None
    return c


def _pct(score):
    return "  -  " if score is None else f"{100 * score:4.0f}%"


def summary_text(results):
    """A table: one row per mate type, per engine the number of ok / FAIL (+STILL) / unsupported (ERR) / crashes (EXC) and the score."""
    names = list(results)
    first = next(iter(results.values()))
    out = ["Score = ok / (ok + FAIL + STILL): of the pick pairs the engine tries to solve, how many end up satisfied.  ERR = the engine says the pair does not",
           "make sense for that mate; EXC = it crashed instead of saying so; noop = already satisfied at the start.", ""]
    head = f"{'mate':<15}" + "".join(f"{n:<34}" for n in names)
    out += [head, "-" * len(head)]
    for ty in first["mates"] + [None]:
        row = f"{ty or 'ALL':<15}"
        for n in names:
            c = totals(results[n], ty)
            row += f"{_pct(c['score'])} ok{c['ok']:<4} FAIL{c['FAIL'] + c['STILL']:<4} ERR{c['ERR']:<4} EXC{c['EXC']:<3}".ljust(34)
        out.append(row)
    return "\n".join(out)


def grid_text(result, name):
    out = [f"=== {name}  ({result['n_starts']} start poses per cell; rows = the pick that moves, columns = the pick on the fixed part)"]
    kinds = result["kinds"]
    for ty in result["mates"]:
        out += ["", f"--- {ty}", f"{'':<8}" + "".join(f"{kb:<16}" for kb in kinds)]
        for ka in kinds:
            out.append(f"{ka:<8}" + "".join(f"{short(result['cells'].get((ka, kb, ty), [])) if (ka, kb, ty) in result['cells'] else '.':<16}" for kb in kinds))
    return "\n".join(out)


def diff_text(results):
    """Where the engines differ (two or more engines): the pick pairs whose outcomes are not the same, with each engine's outcome."""
    names = list(results)
    first = results[names[0]]
    lines = []
    for key in first["cells"]:
        outs = [short(results[n]["cells"].get(key, [])) for n in names]
        if len(set(outs)) > 1:
            ka, kb, ty = key
            lines.append(f"{ty:<14}{ka + ' -> ' + kb:<20}" + "   ".join(f"{n}: {o}" for n, o in zip(names, outs)))
    return "\n".join(lines) if lines else "The engines give the same result for every pick pair."


def report(results):
    """The whole text of the Mate Matrix window for {engine name: run() result}."""
    names = list(results)
    first = results[names[0]]
    out = [summary_text(results), ""]
    if first["n_starts"] < len(starts()):
        out += [f"Quick run: only the first {first['n_starts']} of {len(starts())} start poses (the near ones), so the scores look better than a full run's.", ""]
    if len(names) > 1:
        out += ["Where the engines differ", "", diff_text(results), ""]
    out.append("Time: " + ", ".join(f"{n} {results[n]['seconds']:.0f} s" for n in names) + ("   (stopped early)" if any(r["cancelled"] for r in results.values()) else ""))
    out.append("")
    for n in names:
        out += [grid_text(results[n], n), ""]
    msgs = {}
    for n in names[:1]:
        for (ka, kb, ty), s in sorted(results[n]["msgs"].items()):
            for mm in s:
                msgs.setdefault((ty, mm), f"{ty:<14}{ka}+{kb}: {mm}")
    if msgs:
        out += [f"--- messages of the unsupported or crashing pairs ({names[0]})"] + list(msgs.values())
    return "\n".join(out)
