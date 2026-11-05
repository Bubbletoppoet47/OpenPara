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
import os
import pickle
import re

STUDY_DIR = "study"
FILE = "study.json"
CASES = "cases"
OPS = ["<", "<=", ">", ">="]
MAX_CASES = 500
GEO = "geo."                                  # ids of the parameters that belong to the source part (its dimensions), not to the adapter


def study_file(project):
    return os.path.join(project, STUDY_DIR, FILE)


def exists(project):
    return bool(project) and os.path.isfile(study_file(project))


def split_list(text):
    """'10, 15,20' -> ['10', '15', '20']"""
    return [v.strip() for v in str(text).replace(";", ",").split(",") if v.strip()]


def grid_rows(cols, lists):
    """Every combination of the value lists, as design rows {column: text}.  ValueError when it would be too many."""
    n = 1
    for v in lists:
        n *= len(v)
    if n > MAX_CASES:
        raise ValueError(f"That would be {n} cases. The most a table makes at once is {MAX_CASES}.")
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

    # ---------------------------------------------------------------- save / load
    def to_json(self):
        return {"format": "openpara-study", "version": 1, "checked": self.checked, "rows": self.rows, "outputs": self.out_checked,
                "exit_conds": self.exit_conds, "cases": self.cases, "run_meta": self.run_meta}

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
    def table(self):
        """(headers, rows of text) of the results: #, one column per changed input, status, one column per recorded output."""
        pm_ = self.run_meta.get("params", [])
        om = self.run_meta.get("outputs", [])
        heads = ["#"] + [lab for _, lab in pm_] + ["Status"] + [lab for _, lab in om]
        rows = []
        for c in self.cases:
            st = c.get("status", "")
            if c.get("early_exit"):
                st += " - EARLY EXIT: " + c["early_exit"]
            rows.append([str(c["label"])] + [str(c["values"].get(p, "")) for p, _ in pm_] + [st] +
                        [fmt_cell(c.get("outputs", {}).get(k)) for k, _ in om])
        return heads, rows

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
