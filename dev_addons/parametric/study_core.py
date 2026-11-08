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

STUDY_DIR = "study"
FILE = "study.json"
CASES = "cases"
OPS = ["<", "<=", ">", ">="]
MAX_CASES = 1_000_000                       # not a real limit: only a guard against typing a count that would never finish or fill the memory
CONFIRM_ABOVE = 2000                         # a table this long is made only after the user confirms
FLUSH_EVERY = 200                            # during a long run the finished cases are written to disk and dropped from memory this often
GEO = "geo."                                  # ids of the parameters that belong to the source part (its dimensions), not to the adapter


def study_file(project):
    return os.path.join(project, STUDY_DIR, FILE)


def exists(project):
    return bool(project) and os.path.isfile(study_file(project))


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
        self.fill = {}                # what the Fill grid / Fill range windows held when they were last closed: {"grid": ..., "range": ...}

    # ---------------------------------------------------------------- save / load
    def to_json(self):
        return {"format": "openpara-study", "version": 1, "checked": self.checked, "rows": self.rows, "outputs": self.out_checked,
                "exit_conds": self.exit_conds, "cases": self.cases, "run_meta": self.run_meta,
                "fill": self.fill}

    def save(self, project):
        d = os.path.join(project, STUDY_DIR)
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
    def load(cls, project):
        s = cls()
        with open(study_file(project), encoding="utf-8") as f:
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
        s.folder = project
        return s

    def case(self, i):
        """The full case (what the adapter shows), from memory or from its file; None when it has none."""
        if i in self.heavy:
            return self.heavy[i]
        c = self.cases[i] if 0 <= i < len(self.cases) else None
        if not c or not c.get("file") or not self.folder:
            return None
        p = os.path.join(self.folder, STUDY_DIR, CASES, c["file"])
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
