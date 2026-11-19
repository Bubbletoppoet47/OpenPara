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
import math
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
    """The test solids (made once): a plate with a hole, a block, a pin that fits the hole, two balls, a block with a hole and a pin that fits that."""
    if not _parts:
        from build123d import Box, Cylinder, Sphere
        _parts.update({"plate": Box(80, 80, 10) - Cylinder(10, 30), "block": Box(30, 30, 30), "pin": Cylinder(9.9, 40),
                       "ball": Sphere(12), "ball2": Sphere(15),
                       "blockh": Box(30, 30, 30) - Cylinder(5, 40), "pin2": Cylinder(4.9, 40)})
    return _parts


def starts():
    """Ten starting poses of the moving part (the same every run): three near, two far and rotated, one at the origin, and four awkward ones."""
    rng = np.random.default_rng(11)
    out = []
    for k in range(5):
        far = k >= 3
        out.append((rng.uniform(-300 if far else -60, 300 if far else 60, 3), rng.uniform(-2.5 if far else -0.6, 2.5 if far else 0.6, 3)))
    out.append((np.array([0.0, 0.0, 0.0]), np.zeros(3)))
    # the awkward ones: exactly half a turn (a rotation vector is ambiguous there), far away and turned most of the way round, almost on the answer
    out.append((np.array([0.0, 0.0, 0.0]), np.array([math.pi, 0.0, 0.0])))
    out.append((np.array([40.0, -30.0, 20.0]), np.array([0.0, math.pi, 0.0])))
    out.append((np.array([1500.0, -900.0, 700.0]), np.array([1.6, -1.7, 1.5])))
    out.append((np.array([1e-3, 1e-3, 0.0]), np.array([1e-3, 0.0, 0.0])))
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
    """Run one mate from one start pose; returns (outcome, message) - for "ok" the message is (distance the part moved in mm, angle it turned in degrees)."""
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
    R_before = mod.rodrigues(before[1])
    try:
        A.prepare(m)
        r0 = float(np.max(np.abs(A.mate_residual(m))))
        ok = A.solve(extra=[m])
        r1 = float(np.max(np.abs(A.mate_residual(m))))
        moved = float(np.linalg.norm(np.array(mover["pos"]) - before[0])) + float(np.linalg.norm(np.array(mover["rv"]) - before[1]))
        if r0 <= TOL:
            return "noop", ""
        if ok and r1 <= TOL and moved > 1e-6:
            dR = mod.rodrigues(mover["rv"]) @ R_before.T
            turn = math.degrees(math.acos(max(-1.0, min(1.0, (float(np.trace(dR)) - 1) / 2))))
            return "ok", (float(np.linalg.norm(np.array(mover["pos"]) - before[0])), turn)
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
    cells, msgs, moves = {}, collections.defaultdict(set), {}
    total, done, t0, cancelled = len(kinds) * len(kinds) * len(mates), 0, time.time(), False
    for ka in kinds:
        for kb in kinds:
            for ty in mates:
                res, mv = [], []
                for pos, rv in st:
                    o, msg = one_case(mod, ka, kb, ty, pos, rv)
                    res.append(o)
                    mv.append(msg if o == "ok" else None)                    # (slide, turn) of a case that worked, aligned with the start poses
                    if o != "ok" and msg:
                        msgs[(ka, kb, ty)].add(msg)
                cells[(ka, kb, ty)] = res
                moves[(ka, kb, ty)] = mv
                done += 1
                if progress is not None and progress(done, total):
                    cancelled = True
                    break
            if cancelled:
                break
        if cancelled:
            break
    return {"cells": cells, "moves": moves, "msgs": dict(msgs), "seconds": time.time() - t0, "cancelled": cancelled, "mates": mates, "kinds": kinds, "n_starts": len(st)}


# ---------------------------------------------------------------------------------------------- several mates together
def _face(solid, kind):
    """A face of a test solid: '+z' '-x' ... the outermost flat face looking that way; 'cyl' the first cylindrical face."""
    if kind == "cyl":
        return [f for f in solid.faces() if f.geom_type.name == "CYLINDER"][0]
    ax, sg = "xyz".index(kind[1]), (1.0 if kind[0] == "+" else -1.0)
    pl = [f for f in solid.faces() if f.geom_type.name == "PLANE" and sg * (f.normal_at().X, f.normal_at().Y, f.normal_at().Z)[ax] > 0.99]
    return max(pl, key=lambda f: sg * (f.center().X, f.center().Y, f.center().Z)[ax])


# name -> (what it is, parts that stay fixed, parts that float, mates in the order they are made, what must come out)
# a mate is (type, (component, face), (component, face), {options set after prepare}); components count fixed ones first, then the floating ones
SCENARIOS = {
    "pin in hole": ("a pin concentric with a hole, its top flush with the plate", ["plate"], ["pin"],
                    [("concentric", (1, "cyl"), (0, "cyl"), {}), ("coincident", (1, "+z"), (0, "+z"), {"al": "aligned"})], "holds"),
    "block in corner": ("a block on a plate with two of its sides flush with the plate's sides (fully fixed)", ["plate"], ["block"],
                        [("coincident", (1, "-z"), (0, "+z"), {"al": "opposed"}), ("coincident", (1, "+x"), (0, "+x"), {"al": "aligned"}),
                         ("coincident", (1, "+y"), (0, "+y"), {"al": "aligned"})], "holds"),
    "chain of two": ("a block in the corner of a plate and a pin in the block's hole", ["plate"], ["blockh", "pin2"],
                     [("coincident", (1, "-z"), (0, "+z"), {"al": "opposed"}), ("coincident", (1, "+x"), (0, "+x"), {"al": "aligned"}),
                      ("coincident", (1, "+y"), (0, "+y"), {"al": "aligned"}), ("concentric", (2, "cyl"), (1, "cyl"), {}),
                      ("coincident", (2, "+z"), (1, "+z"), {"al": "aligned"})], "holds"),
    "redundant mate": ("a block on a plate with a parallel mate that the first one already implies", ["plate"], ["block"],
                       [("coincident", (1, "-z"), (0, "+z"), {"al": "opposed"}), ("parallel", (1, "-z"), (0, "+z"), {}),
                        ("coincident", (1, "+x"), (0, "+x"), {"al": "aligned"})], "holds"),
    "conflict": ("two different distances between the same two faces: the second must be refused, the first kept", ["plate"], ["block"],
                 [("distance", (1, "-z"), (0, "+z"), {"value": 5.0}), ("distance", (1, "-z"), (0, "+z"), {"value": 9.0})], "conflict"),
}


def one_scenario(mod, name, k):
    """Start the floating parts from start poses k, k+3, ... and make the mates one at a time, solving after each, as the window does.
    -> "ok" | "FAIL" | "EXC"."""
    _, fixed_names, float_names, mates, expect = SCENARIOS[name]
    P = parts()
    A = mod.Assembly()
    A.solid_fn = lambda c: P[c["path"]]
    comps = [A.add_component(n, fixed=True) for n in fixed_names]
    sts = starts()
    for j, n in enumerate(float_names):
        pos, rv = sts[(k + 3 * j) % len(sts)]
        c = A.add_component(n, pos=tuple(pos), fixed=False)
        c["rv"] = list(rv)
        comps.append(c)
    made, last_ok = [], True
    try:
        for ty, (ia, fa), (ib, fb), opts in mates:
            refs = [{"c": comps[i]["id"], "k": "face", "r": mod.face_ref(_face(P[comps[i]["path"]], f))} for i, f in ((ia, fa), (ib, fb))]
            m = A.add_mate(ty, refs)
            A.prepare(m)
            m.update(opts)
            made.append(m)
            last_ok = A.solve()
        if expect == "conflict":
            held = [x for x in made[:-1] if float(np.max(np.abs(A.mate_residual(x)))) <= TOL]
            return "ok" if (not last_ok and len(held) == len(made) - 1 and str(A.status.get(made[-1]["id"], "")).startswith("error")) else "FAIL"
        if not last_ok:
            return "FAIL"
        return "ok" if all(float(np.max(np.abs(A.mate_residual(x)))) <= TOL for x in made) else "FAIL"
    except mod.MateError:
        return "FAIL"
    except Exception:
        return "EXC"


def run_scenarios(mod, n_starts=None, progress=None):
    """{scenario name: [outcome per start]} and the time, for every scenario in SCENARIOS from every start pose."""
    n = n_starts or len(starts())
    out, t0, done, total = {}, time.time(), 0, len(SCENARIOS) * n
    for name in SCENARIOS:
        res = []
        for k in range(n):
            res.append(one_scenario(mod, name, k))
            done += 1
            if progress is not None and progress(done, total):
                return {"outcomes": out, "seconds": time.time() - t0, "cancelled": True}
        out[name] = res
    return {"outcomes": out, "seconds": time.time() - t0, "cancelled": False}


def scenario_text(results):
    """A table: one row per scenario, per engine how many start poses ended right."""
    names = [n for n in results if results[n].get("scen")]
    if not names:
        return ""
    out = ["Several mates together (made one at a time, solved after each, from every start pose):", ""]
    head = f"{'scenario':<18}" + "".join(f"{n:<16}" for n in names) + "what it is"
    out += [head, "-" * len(head)]
    for sc, (what, *_rest) in SCENARIOS.items():
        row = f"{sc:<18}"
        for n in names:
            o = results[n]["scen"]["outcomes"].get(sc, [])
            row += f"{sum(x == 'ok' for x in o)}/{len(o)}".ljust(16)
        out.append(row + what)
    return "\n".join(out)


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
    mv = [x for (ka, kb, t), v in result.get("moves", {}).items() if ty is None or t == ty for x in v if x is not None]
    c["slide"] = float(np.mean([x[0] for x in mv])) if mv else None        # how far the part moved on average (mm) and turned (degrees) to get there:
    c["turn"] = float(np.mean([x[1] for x in mv])) if mv else None         # the smaller the better for the same starting poses (no needless spinning)
    return c


def _pct(score):
    return "  -  " if score is None else f"{100 * score:4.0f}%"


def summary_text(results):
    """A table: one row per mate type, per engine the number of ok / FAIL (+STILL) / unsupported (ERR) / crashes (EXC) and the score."""
    names = list(results)
    first = next(iter(results.values()))
    out = ["Score = ok / (ok + FAIL + STILL): of the pick pairs the engine tries to solve, how many end up satisfied.  ERR = the engine says the pair does not",
           "make sense for that mate; EXC = it crashed instead of saying so; noop = already satisfied at the start.",
           "move = how far the part slid (mm) and turned (degrees) on average to get there, over the cases that worked: less is better for the same starts.", ""]
    head = f"{'mate':<15}" + "".join(f"{n:<58}" for n in names)
    out += [head, "-" * len(head)]
    for ty in first["mates"] + [None]:
        row = f"{ty or 'ALL':<15}"
        for n in names:
            c = totals(results[n], ty)
            mv = "  -" if c["slide"] is None else f"{c['slide']:.0f}mm {c['turn']:.0f}deg"
            row += f"{_pct(c['score'])} ok{c['ok']:<4} FAIL{c['FAIL'] + c['STILL']:<4} ERR{c['ERR']:<4} EXC{c['EXC']:<4} {mv}".ljust(58)
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


def paired_text(results):
    """The movement of two engines on the very same cases, the ones both solved: the fair comparison (the totals in the table count different cases)."""
    names = [n for n in results if results[n].get("moves")]
    if len(names) < 2:
        return ""
    a, b = names[0], names[1]
    pa, pb = [], []
    for key, va in results[a]["moves"].items():
        for xa, xb in zip(va, results[b]["moves"].get(key, [])):
            if xa is not None and xb is not None:
                pa.append(xa)
                pb.append(xb)
    if not pa:
        return ""
    f = lambda v: f"{np.mean([x[0] for x in v]):.1f} mm slide, {np.mean([x[1] for x in v]):.1f} deg turn"
    return f"On the {len(pa)} cases both engines solved:  {a} moved the part {f(pa)};  {b} {f(pb)}."


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
        pt = paired_text(results)
        out += ["Where the engines differ", "", diff_text(results), ""] + ([pt, ""] if pt else [])
    sc = scenario_text(results)
    if sc:
        out += [sc, ""]
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
