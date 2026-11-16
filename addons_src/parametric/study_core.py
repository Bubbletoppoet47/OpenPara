"""
study_core.py - the data and the rules of a parametric study, with no window in it (study_tab.py is the window).

A study = the inputs that change (columns), the design points (rows), the outputs to record, the early-exit conditions and the cases run so far.
It lives in  <project folder>/study/study.json  (the table, the outputs of every case) and  study/cases/<n>.pkl  (the full result of a case, so it
can be shown again in the simulation tab).  The add-on knows nothing about FEA or CFD: what a column or an output means is the business of the
study adapter of the simulation (see simulation/study_iface.py).
"""
import csv
import itertools
import json
import math
import os
import pickle
import re
import shutil

STUDY_DIR = "study"
FILE = "study.json"
CASES = "cases"
STUDIES = "studies"                          # the studies after the first one live in study/studies/<name>/ ; the first one stays in study/
INDEX = "index.json"
FIRST = "Study 1"
OPS = ["<", "<=", ">", ">="]
MAX_CASES = 1_000_000                       # not a real limit: only a guard against typing a count that would never finish or fill the memory
CONFIRM_ABOVE = 2000                         # a table this long is made only after the user confirms
FLUSH_EVERY = 200                            # during a long run the finished cases are written to disk and dropped from memory this often
GEO = "geo."                                  # ids of the parameters that belong to the source part (its dimensions), not to the adapter


def root_of(project, sub=""):
    """The folder of one study: study/ for the first, study/studies/<sub>/ for the others."""
    return os.path.join(project, STUDY_DIR, STUDIES, sub) if sub else os.path.join(project, STUDY_DIR)


def study_file(project, sub=""):
    return os.path.join(root_of(project, sub), FILE)


def index_file(project):
    return os.path.join(project, STUDY_DIR, INDEX)


def exists(project):
    return bool(project) and (os.path.isfile(study_file(project)) or os.path.isfile(index_file(project)))


def read_index(project):
    """([{"name", "sub"}], current): the studies of a project (a project from before there were several has just the first one)."""
    studies, cur = [], 0
    try:
        with open(index_file(project), encoding="utf-8") as f:
            j = json.load(f)
    except (OSError, ValueError, TypeError):
        j = None
    if isinstance(j, dict) and j.get("format") == "openpara-study-index":
        for x in j.get("studies", []):
            if isinstance(x, dict) and isinstance(x.get("name"), str) and isinstance(x.get("sub", ""), str):
                studies.append({"name": x["name"], "sub": x.get("sub", "")})
        cur = j.get("current", 0)
    if not any(x["sub"] == "" for x in studies):
        studies.insert(0, {"name": FIRST, "sub": ""})
    if not isinstance(cur, int) or not 0 <= cur < len(studies):
        cur = 0
    return studies, cur


def write_index(project, studies, current):
    os.makedirs(os.path.join(project, STUDY_DIR), exist_ok=True)
    tmp = index_file(project) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"format": "openpara-study-index", "version": 1, "studies": studies, "current": current}, f, indent=1)
    os.replace(tmp, index_file(project))


def new_sub(name, studies):
    """A folder name for a new study: from its name, never one that is taken."""
    base = re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_").lower() or "study"
    taken = {x["sub"] for x in studies}
    sub, i = base, 2
    while sub in taken:
        sub, i = f"{base}_{i}", i + 1
    return sub


def delete_files(project, sub):
    """Removes the folder of a study (never the first one: that one can be cleared and renamed, not deleted)."""
    if not sub:
        raise ValueError("The first study cannot be deleted.")
    shutil.rmtree(root_of(project, sub), ignore_errors=True)


def split_list(text):
    """'10, 15,20' -> ['10', '15', '20']"""
    return [v.strip() for v in str(text).replace(";", ",").split(",") if v.strip()]


def spaced(start, end, n, log=False):
    """n numbers from start to end, both included, as text: equal steps (like numpy.linspace) or equal ratios (log spacing, like numpy.geomspace).
    ValueError for a bad count or, with log spacing, for values that are zero or of different sign."""
    a, b = float(start), float(end)
    n = int(n)
    if n < 1:
        raise ValueError("The count must be at least 1.")
    if n > MAX_CASES:
        raise ValueError(f"A count of {n:,} is too many (the most is {MAX_CASES:,}).")
    if log:
        if a == 0 or b == 0 or (a < 0) != (b < 0):
            raise ValueError("Log spacing needs a start and an end that are not zero and have the same sign.")
        sgn = -1.0 if a < 0 else 1.0
        la, lb = math.log(abs(a)), math.log(abs(b))
        vals = [sgn * math.exp(la + (lb - la) * k / (n - 1)) for k in range(n)] if n > 1 else [a]
        if n > 1:
            vals[0], vals[-1] = a, b
    else:
        vals = [a + (b - a) * k / (n - 1) for k in range(n)] if n > 1 else [a]
        if n > 1:
            vals[-1] = b
    return [format(v, ".10g") for v in vals]


def range_rows(cols, specs, together, log=False, rows=None):
    """specs {column: (start, end, count)}.  together=True: `rows` rows, every column stepping at once (row 1 = all starts, last row = all ends);
    False: every combination of the columns' own counts.  -> design rows."""
    if together:
        lists = [spaced(specs[p][0], specs[p][1], rows, log) for p in cols]
        return [dict(zip(cols, vals)) for vals in zip(*lists)]
    return grid_rows(cols, [spaced(specs[p][0], specs[p][1], specs[p][2], log) for p in cols])


def grid_rows(cols, lists):
    """Every combination of the value lists, as design rows {column: text}.  ValueError when it would be too many."""
    n = 1
    for v in lists:
        n *= len(v)
    if n > MAX_CASES:
        raise ValueError(f"That would be {n:,} cases. The most a table makes at once is {MAX_CASES:,}.")
    return [dict(zip(cols, combo)) for combo in itertools.product(*lists)]


def check_exit(conds, outputs):
    """Text describing the first ticked condition that `outputs` ({key: number|text|None}) meets, or None."""
    for c in conds:
        if not c.get("on", True):
            continue
        v = outputs.get(c["key"])
        if v is None or isinstance(v, str):
            continue
        try:
            lim = float(c["value"])
        except (TypeError, ValueError):
            continue
        op = c.get("op", ">")
        if op not in OPS:
            continue
        if {"<": v < lim, "<=": v <= lim, ">": v > lim, ">=": v >= lim}[op]:
            return f"{c['key']} = {v:.5g} {op} {lim:g}"
    return None


def exit_keys(conds):
    return sorted({c["key"] for c in conds if c.get("on", True)})


def fmt_cell(v):
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    return f"{v:.6g}"


class StudyData:
    def __init__(self):
        self.checked = []             # ticked parameter ids, in display order
        self.rows = [{}]              # design points: [{parameter id: text}]
        self.out_checked = []         # output ids to record
        self.exit_conds = []          # [{"on", "key", "op", "value"}]
        self.cases = []               # [{"label", "values", "status", "outputs", "early_exit", "early_skipped", "error", "notes", "file"}]
        self.run_meta = {"params": [], "outputs": [], "unit": None}
        self.heavy = {}               # case index -> the full case (in memory)
        self.unsaved = set()          # case indexes whose pickle is not on disk yet
        self.folder = None
        self.sub = ""                 # which study of the project this is ("" = the first)
        self.refine = None            # set for a mesh refinement study: {"sizes": [ids], "count": id, "dim": 2|3, "ratio", "levels", "tol"}
        self.fill = {}                # what the Fill grid / Fill range windows held when they were last closed: {"grid": ..., "range": ...}

    # ---------------------------------------------------------------- save / load
    def to_json(self):
        return {"format": "openpara-study", "version": 1, "checked": self.checked, "rows": self.rows, "outputs": self.out_checked,
                "exit_conds": self.exit_conds, "cases": self.cases, "run_meta": self.run_meta,
                "fill": self.fill, "refine": self.refine}

    def save(self, project):
        d = root_of(project, self.sub)
        cd = os.path.join(d, CASES)
        os.makedirs(cd, exist_ok=True)
        keep = set()
        for i, c in enumerate(self.cases):
            if c.get("file"):
                keep.add(c["file"])
        for i in sorted(self.unsaved):
            if i >= len(self.cases) or i not in self.heavy:
                continue
            name = f"case_{i + 1:04d}_{re.sub(r'[^A-Za-z0-9_.-]', '_', str(self.cases[i]['label']))}.pkl"
            tmp = os.path.join(cd, name + ".tmp")
            with open(tmp, "wb") as f:
                pickle.dump(self.heavy[i], f, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(tmp, os.path.join(cd, name))
            self.cases[i]["file"] = name
            keep.add(name)
        self.unsaved.clear()
        for fn in os.listdir(cd):                              # cases of an older run that no longer exist
            if fn not in keep:
                try:
                    os.remove(os.path.join(cd, fn))
                except OSError:
                    pass
        tmp = os.path.join(d, FILE + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.to_json(), f, indent=1)
        os.replace(tmp, os.path.join(d, FILE))
        self.folder = project

    @classmethod
    def load(cls, project, sub=""):
        s = cls()
        s.sub = sub
        with open(study_file(project, sub), encoding="utf-8") as f:
            j = json.load(f)
        if j.get("format") != "openpara-study":
            raise ValueError("This is not a parametric study file.")
        s.checked = list(j.get("checked", []))
        s.rows = [dict(r) for r in j.get("rows", [])] or [{}]
        s.out_checked = list(j.get("outputs", []))
        s.exit_conds = [dict(c) for c in j.get("exit_conds", [])]
        s.cases = list(j.get("cases", []))
        s.run_meta = j.get("run_meta") or {"params": [], "outputs": [], "unit": None}
        s.fill = dict(j.get("fill") or {})
        s.refine = dict(j["refine"]) if isinstance(j.get("refine"), dict) else None
        s.folder = project
        return s

    def case(self, i):
        """The full case (what the adapter shows), from memory or from its file; None when it has none."""
        if i in self.heavy:
            return self.heavy[i]
        c = self.cases[i] if 0 <= i < len(self.cases) else None
        if not c or not c.get("file") or not self.folder:
            return None
        p = os.path.join(root_of(self.folder, self.sub), CASES, c["file"])
        if not os.path.isfile(p):
            return None
        with open(p, "rb") as f:
            self.heavy[i] = pickle.load(f)
        return self.heavy[i]

    def clear_cases(self):
        self.cases, self.heavy, self.unsaved = [], {}, set()

    def add_case(self, summary, heavy):
        self.cases.append(summary)
        if heavy is not None:
            self.heavy[len(self.cases) - 1] = heavy
            self.unsaved.add(len(self.cases) - 1)

    # ---------------------------------------------------------------- the results table
    def heads(self):
        pm_ = self.run_meta.get("params", [])
        om = self.run_meta.get("outputs", [])
        return ["#"] + [lab for _, lab in pm_] + ["Status"] + [lab for _, lab in om]

    def row_cells(self, c):
        """The text cells of one case in the results table."""
        pm_ = self.run_meta.get("params", [])
        om = self.run_meta.get("outputs", [])
        st = c.get("status", "")
        if c.get("early_exit"):
            st += " - EARLY EXIT: " + c["early_exit"]
        return [str(c["label"])] + [str(c["values"].get(p, "")) for p, _ in pm_] + [st] + [fmt_cell(c.get("outputs", {}).get(k)) for k, _ in om]

    def table(self):
        """(headers, rows of text) of the results: #, one column per changed input, status, one column per recorded output."""
        return self.heads(), [self.row_cells(c) for c in self.cases]

    def flush(self, project):
        """Writes the finished cases to disk and frees their full results from memory (they are read back when a case is shown)."""
        self.save(project)
        for i in list(self.heavy):
            if self.cases[i].get("file"):
                del self.heavy[i]

    def write_csv(self, path):
        heads, rows = self.table()
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(heads)
            w.writerows(rows)

    @staticmethod
    def severity(case):
        """'bad' (failed), 'warn' (did not converge, early exit...) or '' for a row."""
        st = str(case.get("status", ""))
        if st == "failed" or st.startswith("FAILED"):
            return "bad"
        if case.get("early_exit") or case.get("early_skipped") or (st and not (st == "ok" or st == "converged")):
            return "warn"
        return ""


# ---------------------------------------------------------------------------------------------------------------- mesh refinement
REFINE_MIN_RATIO, REFINE_MAX_RATIO = 0.2, 0.95
REFINE_MAX_LEVELS = 12


def refine_check(start, ratio, levels):
    """The numbers of a refinement study, validated: (start, ratio, levels) or ValueError in plain words."""
    try:
        start, ratio, levels = float(start), float(ratio), int(levels)
    except (TypeError, ValueError):
        raise ValueError("The start size, the factor and the number of levels must be numbers.")
    if not start > 0:
        raise ValueError("The start element size must be greater than 0.")
    if not REFINE_MIN_RATIO <= ratio <= REFINE_MAX_RATIO:
        raise ValueError(f"The factor per level must be between {REFINE_MIN_RATIO:g} and {REFINE_MAX_RATIO:g} (0.7 makes every level 30% finer).")
    if not 2 <= levels <= REFINE_MAX_LEVELS:
        raise ValueError(f"The number of levels must be from 2 to {REFINE_MAX_LEVELS}.")
    return start, ratio, levels


def refinement_rows(sizes, nows, start, ratio, levels, extra=None):
    """The design-point rows of a refinement study.  `sizes`: the size inputs (ids); the first starts at `start`, the others keep their
    proportion to it (CFD: body and far-field sizes together).  `nows`: {id: current value text}.  `extra`: {id: text} for columns that are
    the same in every row (such as 'Auto-refine the mesh' = no)."""
    start, ratio, levels = refine_check(start, ratio, levels)
    try:
        base0 = float(nows[sizes[0]])
    except (KeyError, ValueError, TypeError):
        base0 = 0.0
    rows = []
    for k in range(levels):
        row = {}
        for pid in sizes:
            if pid == sizes[0]:
                base = start
            else:
                try:
                    base = float(nows[pid]) * (start / base0 if base0 > 0 else 1.0)
                except (KeyError, ValueError, TypeError):
                    raise ValueError("The input '%s' has no number to scale yet." % pid)
            row[pid] = format(base * ratio ** k, ".4g")
        row.update(extra or {})
        rows.append(row)
    return rows


def _num(x):
    if isinstance(x, bool) or x is None or isinstance(x, str):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def convergence(levels, dim=2, tol=2.0):
    """How the outputs of a refinement study settle as the mesh gets finer.

    levels: [{"label", "h", "n", "outputs": {output id: number}}], any order (sorted here by the number of elements, coarse to fine).
    Returns {"levels", "outputs": {id: info}, "recommend": index of the coarsest level that is good enough, or None, "notes", "tol"}.
    info: values, pct (change from the previous level, in %), order, limit (Richardson extrapolation), verdict, text, idx (the levels it has a value at).
    """
    lv = sorted([l for l in levels if _num(l.get("n")) and l["n"] > 0], key=lambda l: l["n"])
    res = {"levels": lv, "outputs": {}, "recommend": None, "tol": tol, "notes": []}
    ids = []
    for l in lv:
        for k in l.get("outputs", {}):
            if k not in ids:
                ids.append(k)
    for k in ids:
        pts = [(i, _num(l["outputs"].get(k))) for i, l in enumerate(lv)]
        pts = [(i, v) for i, v in pts if v is not None]
        if len(pts) < 2:
            continue
        idx = [i for i, _ in pts]
        vals = [v for _, v in pts]
        pct = [None]
        for a, b in zip(vals, vals[1:]):
            pct.append(0.0 if a == b else ((b - a) / abs(b) * 100.0 if b != 0 else None))
        info = {"idx": idx, "values": vals, "pct": pct, "order": None, "limit": None, "verdict": "", "text": ""}
        last = pct[-1]
        r = (lv[idx[-1]]["n"] / lv[idx[-2]]["n"]) ** (1.0 / dim)
        d2 = vals[-1] - vals[-2]
        shrinking = False
        if len(vals) >= 3:
            d1 = vals[-2] - vals[-3]
            if d1 * d2 > 0:
                shrinking = abs(d2) < 0.9 * abs(d1)
                if shrinking and r > 1.02:
                    p = math.log(abs(d1 / d2)) / math.log(r)
                    if 0.5 <= p <= 4.0 and r ** p > 1.0001:
                        info["order"] = p
                        info["limit"] = vals[-1] + d2 / (r ** p - 1.0)
            elif d1 != 0 and d2 != 0:
                info["oscillating"] = True
        small = last is not None and abs(last) <= tol
        prev_small = len(pct) > 2 and pct[-2] is not None and abs(pct[-2]) <= tol
        if last is None:
            info["verdict"], info["text"] = "too few levels", "no relative change (the value is 0)"
        elif len(vals) == 2:
            info["verdict"] = "looks converged" if small else "still changing"
            info["text"] = (f"last change {abs(last):.2g}%" + (" (only two levels: add one to be sure)" if small else ""))
        elif info.get("oscillating") and not small:
            info["verdict"], info["text"] = "oscillating", f"goes up and down; last change {abs(last):.2g}%"
        elif small and (prev_small or shrinking):
            info["verdict"] = "converged"
            info["text"] = f"last change {abs(last):.2g}%" + (f", estimated limit {info['limit']:.5g}" if info["limit"] is not None else "")
        elif small:
            info["verdict"], info["text"] = "looks converged", f"last change {abs(last):.2g}%, but the change before it was larger"
        elif d1 * d2 > 0 and not shrinking:
            info["verdict"], info["text"] = "not converging", f"changes are not getting smaller (last {abs(last):.2g}%)"
        else:
            info["verdict"] = "still changing"
            info["text"] = f"last change {abs(last):.2g}%" + (f", estimated limit {info['limit']:.5g}" if info["limit"] is not None else "")
        res["outputs"][k] = info
    judged = [info for info in res["outputs"].values() if info["verdict"] in ("converged", "looks converged")]
    res["pending"] = [k for k, info in res["outputs"].items() if info["verdict"] in ("still changing", "too few levels")]
    if judged and not res["pending"]:                      # an output that is still changing means: refine further before choosing a size
        for lvl in range(len(lv)):
            ok = True
            for info in judged:
                if lvl not in info["idx"]:
                    ok = False
                    break
                pos = info["idx"].index(lvl)
                later = info["pct"][pos + 1:]
                if any(x is None or abs(x) > tol for x in later):
                    ok = False
                    break
            if ok:
                res["recommend"] = lvl
                break
    for k, info in res["outputs"].items():
        if info["verdict"] in ("not converging", "oscillating"):
            res["notes"].append(k)
    return res
