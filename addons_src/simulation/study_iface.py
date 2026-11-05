"""
study_iface.py - THE INTERFACE between a simulation tab and the Parametric Studies add-on.

The Parametric Studies add-on knows nothing about FEA or CFD.  It only talks to a `study adapter`: an object a simulation tab offers as
`tab.study_adapter()`.  A new kind of simulation (3D FEA, heat, ...) takes part in parametric studies by writing one adapter, with no change
to the Parametric Studies add-on.  A case is always run on a SCRATCH copy of the tab (built from the tab's own saved state), so the tab on screen
is never touched by a study.

    class MyStudy(StudyAdapter):
        key = "fea"                       # short id; the prefix of the ids of its parameters and outputs
        label = "2D FEA"
        def ready(self)                   -> None, or the reason why nothing can run yet ("Import a sketch first")
        def params(self)                  -> [{"id", "group", "label", "kind": "text" | "bool" | "choice", "choices", "now"}]
                                             the inputs a study can vary; `now` is the value in the tab (a string)
        def outputs(self)                 -> [{"id", "group", "label", "numeric": bool}]   what a case can record
        def prepare(self, values, ctx, state=None) -> {"run": fn(progress, cancel) -> case dict, "error": None | text}
                                             MAIN thread.  values = {param id: text}.  Builds everything the case needs; `run` is pure compute
                                             (no widget access) and is called on a worker thread.  `ctx` is a dict that lives for one study run
                                             (a place to cache meshes).  `state` replaces the tab's saved state (geometry studies).
        def case_outputs(self, case, keys) -> {output id: number | text | None}     MAIN thread
        def show(self, case)              -> puts a finished case on the tab's screen (MAIN thread)

`run` returns the case: {"status": "ok" | "failed" | ..., "error": text, ...whatever the adapter needs to show it...}.  Raise `StudyCancelled`
inside `run` when `cancel()` says so.  The case is pickled into the project (study/cases/), so keep it to numpy arrays and plain Python.
"""
import copy

from PyQt6.QtWidgets import QAbstractButton, QComboBox, QLineEdit


class StudyCancelled(Exception):
    pass


class StudyAdapter:
    key = "sim"
    label = "Simulation"

    def __init__(self, tab):
        self.tab = tab

    # --- to be written by each simulation
    def ready(self):
        return None

    def params(self):
        return []

    def outputs(self):
        return []

    def prepare(self, values, ctx, state=None):
        raise NotImplementedError

    def case_outputs(self, case, keys):
        return {}

    def show(self, case):
        raise NotImplementedError

    # --- shared helpers
    def base_state(self):
        """The saved state of the tab without its mesh and result (the starting point of a case)."""
        st = dict(self.tab.export_state())
        st["mesh"] = None
        st["result"] = None
        for k in ("supports", "loads", "inputs", "probes", "members", "profile", "region_mats", "region_names"):
            if k in st and st[k] is not None:
                st[k] = copy.deepcopy(st[k])
        return st

    def scratch(self, state=None):
        """A tab of the same kind (never shown) in the given state: the case is set up and read from it."""
        t = self.tab
        host = ScratchHost(t.win)
        s = type(t)(host)
        host._restoring = True
        try:
            s.import_state(state if state is not None else self.base_state())
        finally:
            host._restoring = False
        return s


class ScratchHost:
    """The 'window' of a scratch tab: what the solver tabs call their window.  Nothing it is asked changes the program."""

    def __init__(self, real):
        self.doc = None
        self.m = getattr(real, "m", None)
        self._restoring = False
        self.cfd = None
        self.sim = None

    def status(self, text):
        pass

    def sketch_list(self):
        return []

    def sketch_json(self, sid):
        return None


# ---------------------------------------------------------------------------------------------------------------- small helpers
def parse_bool(text):
    if isinstance(text, bool):
        return text
    t = str(text).strip().lower()
    if t in ("1", "true", "yes", "y", "on", "x"):
        return True
    if t in ("0", "false", "no", "n", "off", ""):
        return False
    raise ValueError(f"'{text}' is not yes/no.")


def widget_value(w):
    if isinstance(w, QLineEdit):
        return w.text()
    if isinstance(w, QComboBox):
        return w.currentText()
    if isinstance(w, QAbstractButton):
        return bool(w.isChecked())
    return None


def fmt_num(v):
    return format(float(v), ".10g")


def widget_params(tab, table, group):
    """Parameter dicts for the widgets of `tab` named in table = [(attribute, label)]: text boxes, tick boxes and combos."""
    out = []
    for attr, label in table:
        w = getattr(tab, attr, None)
        if w is None:
            continue
        kind = "bool" if isinstance(w, QAbstractButton) else "choice" if isinstance(w, QComboBox) else "text"
        v = widget_value(w)
        out.append({"id": f"{attr}", "group": group, "label": label, "kind": kind, "attr": attr,
                    "choices": [w.itemText(i) for i in range(w.count())] if isinstance(w, QComboBox) else None,
                    "now": ("yes" if v else "no") if kind == "bool" else str(v)})
    return out


def set_widget(tab, attr, kind, text, choices=None):
    """Sets one input widget of a scratch tab from a table cell (text)."""
    from physics_store import set_inputs
    if kind == "bool":
        v = parse_bool(text)
        if attr == "rb_strain":
            (tab.rb_strain if v else tab.rb_stress).setChecked(True)
            return
        set_inputs(tab, {attr: v})
    elif kind == "choice":
        if text not in (choices or []):
            raise ValueError(f"'{text}' is not one of: " + ", ".join(choices or []))
        set_inputs(tab, {attr: text})
    else:
        set_inputs(tab, {attr: str(text)})
