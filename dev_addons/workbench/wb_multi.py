"""wb_multi.py - what the Parametric Study block of the workbench talks to: ONE study over any number of wired blocks.

The study window of the Parametric Studies add-on (study_tab.StudyTab) is built around one 'simulation window'.  Here that window is a StudyHost: it stands for the
whole block and offers what the study window asks of a simulation window (path, tab, ...).  The `tab.study_adapter()` it gives is a MultiAdapter that puts the blocks
wired into the Parameters cell together:

    a Part (wire from its Part cell)        its dimensions are inputs ("A/g:L", "A/d:...").  A value is applied to EVERY wired analysis that works on that Part (it is
                                            the analysis's geometry, or one of its profile parts): the analysis's own copy of the part is changed, so a change of the geometry
                                            flows through the analyses on it.
    an analysis (wire from its Setup cell) its own inputs (material, loads, mesh size ...) and its outputs.  Every case sets all the ticked values and then runs ALL the
                                            wired analyses; the outputs recorded are those of every analysis.
Every id carries the letter of its block ("B/beam.fx": the force of block B), every label and group the block's name, so the study window lists the inputs grouped per block
and the results table says which analysis a column comes from.  The study needs at least one analysis (the outputs come from them).
The study is kept in the study block (node.data["files"], the folder study/ without the full result of each case), not in an analysis.
"""
import copy
import hashlib
import html
import json
import os
import traceback
import types

SEP = "/"                                                     # between the letter of a block and the id of its input or output


def prefixed(label, ident):
    return label + SEP + ident


def split_id(ident):
    """("B", "beam.fx") of "B/beam.fx"; (None, ident) when there is no letter."""
    if SEP not in ident:
        return None, ident
    a, b = ident.split(SEP, 1)
    return a, b


class Member:
    """One wired block: its node, its letter, and (analysis) its window and study adapter, or (part) the dimensions of its document."""
    def __init__(self, node, kind):
        self.node, self.kind = node, kind
        self.label, self.title = node.label, node.title
        self.sw = None                                        # an analysis: the window of the project folder (the Workbench opens it behind the others)
        self.ad = None                                        # its study adapter
        self.cands = []                                       # a part: [(cfg key, label, now)]
        self.why = None                                       # why it cannot be used (a window that did not open ...)

    @property
    def name(self):
        return f"{self.label} {self.title}"


class MultiTab:
    """What the study window asks of `sw.tab`: the adapter, the way to lock the analyses during a run, the states to put back after a case was shown."""
    def __init__(self, host):
        self.host = host

    def study_adapter(self):
        return MultiAdapter(self.host)

    def setEnabled(self, on):
        for m in self.host.analyses(open_missing=False):
            try:
                m.sw.tab.setEnabled(on)
            except (RuntimeError, AttributeError):
                pass

    def export_state(self):
        return {m.label: m.sw.tab.export_state() for m in self.host.analyses(open_missing=False)}

    def import_state(self, states):
        for m in self.host.analyses(open_missing=False):
            st = (states or {}).get(m.label)
            if st is None:
                continue
            m.sw.host._restoring = True
            try:
                m.sw.tab.import_state(st)
            finally:
                m.sw.host._restoring = False


class StudyHost:
    """Stands in for the simulation window of the study window: one per study block."""
    kind = "study"
    study_geometry = False
    source = None
    shell = None

    def __init__(self, wb, node, folder):
        self.wb, self.node, self.path = wb, node, folder
        self.meta = {}
        self.host = types.SimpleNamespace(_restoring=False)
        self.tab = MultiTab(self)
        self.parts_cache = {}

    def refresh_study_button(self):
        pass

    def goto(self):
        """'Go to the simulation': shows the Workbench (the blocks are there)."""
        h = self.wb.host
        if h is not None and hasattr(h, "tabs"):
            h.tabs.setCurrentWidget(self.wb)

    # ---- the wired blocks
    def wires(self):
        prj = self.wb.project
        return [(k, prj.node(k.a)) for k in prj.incoming_all(self.node.id, "setup")]

    def analyses(self, open_missing=True):
        """[Member] of the analyses wired in.  A window that is not open is opened (behind the others) unless `open_missing` is False."""
        out = []
        for k, src in self.wires():
            c = src.spec.cell(k.a_cell) if src.spec is not None else None
            if c is None or "analysis" not in c.provides:
                continue
            m = Member(src, "analysis")
            sw = self.wb.editor_of(src.id)
            a = None
            if sw is None and open_missing:
                import wb_nodes as nodes
                a = nodes.adapter_for(src.kind)
                sw = a.open_editor(self.wb, src, front=False) if a is not None and hasattr(a, "open_editor") else None
                if sw is None:
                    m.why = f"'{src.title}' could not be opened (see the message above)."
            if sw is None:
                if open_missing:
                    out.append(m)
                continue
            m.sw = sw
            fn = getattr(getattr(sw, "tab", None), "study_adapter", None)
            if not callable(fn):
                m.why = f"'{src.title}' has no parametric study."
            else:
                m.ad = fn()
            out.append(m)
        return out

    def parts(self):
        """[Member] of the parts wired in, with the dimensions of their documents."""
        out = []
        for k, src in self.wires():
            c = src.spec.cell(k.a_cell) if src.spec is not None else None
            if c is None or "dimensions" not in c.provides or src.kind != "part":
                continue
            m = Member(src, "part")
            doc = src.data.get("doc")
            if doc is None:
                m.why = f"'{src.title}' is empty: it has no dimensions."
            else:
                m.cands = self.dimensions_of(src, doc)
            out.append(m)
        return out

    def dimensions_of(self, node, doc):
        """[(cfg key, label, now)] of a part document (worked out once per version of the document)."""
        text = json.dumps(doc, sort_keys=True)
        h = hashlib.sha1(text.encode("utf-8")).hexdigest()
        got = self.parts_cache.get(node.id)
        if got is not None and got[0] == h:
            return got[1]
        import pm_model as pm
        d = pm.Document.from_json(json.dumps(doc))
        d.rebuild()
        cands = [(k, lab, now) for k, lab, now in d.cfg_candidates()]
        self.parts_cache[node.id] = (h, cands)
        return cands

    # ---- which analysis works on which part
    def geometry_source(self, a):
        """The id of the block whose geometry (or sketch) the analysis `a` works on, or None."""
        k = self.wb.project.incoming(a.node.id, "geometry")
        return k.a if k is not None else None

    def profile_sources(self, a):
        """{block id: key of its copy in the analysis's profiles/} of the parts wired into the Profile cell of the analysis `a`."""
        prj = self.wb.project
        if a.node.spec is None or a.node.spec.cell("profile") is None or a.sw is None:
            return {}
        import sim_project as sp
        wired = {k.a for k in prj.incoming_all(a.node.id, "profile")}
        try:
            return {e["wb"]: e["key"] for e in sp.profile_parts(a.sw.path) if e.get("wb") in wired}
        except Exception:                                     # noqa: BLE001
            return {}


class MultiAdapter:
    """The study adapter of the whole block (study_iface.StudyAdapter's interface): inputs and outputs of every wired block, a case runs every analysis."""
    key = "multi"
    label = "Parametric study"

    def __init__(self, host):
        self.host = host
        self.tab = host.tab
        self.win = host
        self.ana = host.analyses()
        self.prts = host.parts()
        self.ids = {}                                         # analysis letter -> {ids of the analysis's own inputs}
        self.profs = {a.label: host.profile_sources(a) for a in self.ana if a.sw is not None}

    # ---- helpers
    def usable(self):
        return [a for a in self.ana if a.ad is not None]

    def wired_parts(self):
        return {p.node.id: p for p in self.prts}

    def used_by(self, p):
        """The analyses that work on the part `p` (as their geometry or as one of their profile parts)."""
        out = []
        for a in self.usable():
            if self.host.geometry_source(a) == p.node.id or p.node.id in self.profs.get(a.label, {}):
                out.append(a)
        return out

    def own_ids(self, a):
        if a.label not in self.ids:
            self.ids[a.label] = {d["id"] for d in a.ad.params()}
        return self.ids[a.label]

    def heading(self):
        names = [html.escape(a.name) for a in self.usable()]
        parts = [html.escape(p.name) for p in self.prts]
        text = "<b>Parametric study</b> of " + (", ".join(f"<b>{n}</b>" for n in names) if names else "no analysis yet")
        if parts:
            text += " (dimensions of " + ", ".join(f"<b>{n}</b>" for n in parts) + ")"
        return text

    # ---- the interface
    def ready(self):
        if not self.ana:
            return "Wire the Setup cell of at least one analysis into Parameters: a study records the outputs of the analyses it runs."
        for a in self.ana:
            if a.why:
                return a.why
        for a in self.usable():
            why = a.ad.ready()
            if why:
                return f"{a.name}: {why}"
        return None

    def params(self):
        import study_core as core
        import study_tab
        out = []
        wired = self.wired_parts()
        for p in self.prts:
            used = self.used_by(p)
            grp = f"{p.name} (part): dimensions" + ("" if used else " - no wired analysis works on this part")
            for key, label, now in p.cands:
                is_bool = key.startswith("s:")
                out.append({"id": prefixed(p.label, key), "group": grp, "label": f"{p.label}: {label}", "kind": "bool" if is_bool else "text", "choices": None,
                            "now": ("yes" if now else "no") if is_bool else str(now), "part": (p.label, key)})
        for a in self.usable():
            hidden = tuple("beam.prof." + key + "." for bid, key in self.profs.get(a.label, {}).items() if bid in wired)
            for d in a.ad.params():
                if hidden and d["id"].startswith(hidden):
                    continue                                  # the dimensions of a wired part are among the part's
                e = dict(d)
                e["id"] = prefixed(a.label, d["id"])
                e["group"] = f"{a.name}: {d['group']}"
                e["label"] = f"{a.label}: {d['label']}"
                out.append(e)
            if self.host.geometry_source(a) not in wired:     # the part is not wired into the study: its dimensions stay among the analysis's own inputs
                for key, label, now in study_tab.geo_candidates(a.sw):
                    is_bool = key.startswith("s:")
                    out.append({"id": prefixed(a.label, core.GEO + key), "group": f"{a.name}: Part dimensions (changes the geometry)", "label": f"{a.label}: {label}",
                                "kind": "bool" if is_bool else "text", "choices": None, "now": ("yes" if now else "no") if is_bool else str(now), "geo": key})
        return out

    def outputs(self):
        out = []
        for a in self.usable():
            for o in a.ad.outputs():
                e = dict(o)
                e["id"] = prefixed(a.label, o["id"])
                e["group"] = f"{a.name}: {o['group']}"
                e["label"] = f"{a.label}: {o['label']}"
                out.append(e)
        return out

    def state_of(self, a, geo, ctx):
        """The state of the analysis `a` after changing the dimensions of its part (worked out once per set of values in a run)."""
        import study_tab
        key = (a.label, tuple(sorted(geo.items())))
        cache = ctx.setdefault("geo", {})
        if key not in cache:
            cache[key] = study_tab.geometry_state(a.sw, a.ad, geo)
        return cache[key]

    def prepare(self, values, ctx, state=None):
        import study_core as core
        spec = {"error": None, "run": None}
        plan = []
        try:
            for a in self.usable():
                pre = prefixed(a.label, "")
                mine = {k[len(pre):]: v for k, v in values.items() if k.startswith(pre)}
                geo = {k[len(core.GEO):]: v for k, v in mine.items() if k.startswith(core.GEO)}
                plain = {k: v for k, v in mine.items() if not k.startswith(core.GEO)}
                gsrc = self.host.geometry_source(a)
                for p in self.prts:
                    ppre = prefixed(p.label, "")
                    pv = {k[len(ppre):]: v for k, v in values.items() if k.startswith(ppre)}
                    if not pv:
                        continue
                    if gsrc == p.node.id:
                        geo.update(pv)
                    pkey = self.profs.get(a.label, {}).get(p.node.id)
                    if pkey:
                        own = self.own_ids(a)
                        for k, v in pv.items():
                            if "beam.prof." + pkey + "." + k in own:
                                plain["beam.prof." + pkey + "." + k] = v
                st = self.state_of(a, geo, ctx) if geo else None
                sp = a.ad.prepare(plain, ctx.setdefault("m:" + a.label, {}), st)
                if sp.get("error"):
                    raise ValueError(f"{a.name}: {sp['error']}")
                plan.append((a, sp, st))
        except ValueError as ex:
            spec["error"] = str(ex)
            return spec
        except Exception:                                     # noqa: BLE001
            spec["error"] = traceback.format_exc()
            return spec

        def run(progress, cancel):
            from study_iface import StudyCancelled
            parts, failed = {}, []
            for a, sp, st in plan:
                lab = a.label
                case = sp["run"](lambda t, lab=lab: progress(f"{lab}: {t}"), cancel)
                if cancel():
                    raise StudyCancelled()
                if st is not None:
                    case["state"] = st
                parts[lab] = case
                if case.get("status") not in ("ok", "converged"):
                    failed.append(f"{lab}: {case.get('error') or case.get('status')}")
            return {"status": "failed" if failed else "ok", "error": "; ".join(failed) or None, "parts": parts,
                    "result": True if any(c.get("result") is not None for c in parts.values()) else None}
        spec["run"] = run
        return spec

    def case_outputs(self, case, keys):
        out = {}
        parts = (case or {}).get("parts") or {}
        for a in self.usable():
            pre = prefixed(a.label, "")
            want = [k[len(pre):] for k in keys if k.startswith(pre)]
            if not want:
                continue
            ca = parts.get(a.label)
            res = a.ad.case_outputs(ca, want) if ca is not None else {}
            for k in want:
                out[pre + k] = res.get(k)
        return out

    def show(self, case):
        """Every analysis shows its own part of the case (its window comes to the front)."""
        parts = (case or {}).get("parts") or {}
        front = None
        for a in self.usable():
            ca = parts.get(a.label)
            if ca is None or ca.get("result") is None:
                continue
            a.sw.host._restoring = True
            try:
                a.ad.show(ca)
            finally:
                a.sw.host._restoring = False
            front = front or a
        if front is not None:
            sh = getattr(front.sw, "shell", None)
            if sh is not None and hasattr(sh, "tabs"):
                sh.tabs.setCurrentWidget(front.sw)

    def mesh_refinement(self):
        """Only where one analysis is wired: its refinement, with the letter in front of every id."""
        ana = self.usable()
        if len(ana) != 1:
            return None
        a = ana[0]
        spec = a.ad.mesh_refinement()
        if spec is None:
            return None
        pre = prefixed(a.label, "")
        spec = copy.deepcopy(spec)
        spec["sizes"] = [pre + p for p in spec["sizes"]]
        spec["extra"] = {pre + p: v for p, v in (spec.get("extra") or {}).items()}
        spec["count"] = pre + spec["count"]
        spec["outputs"] = [pre + o for o in spec["outputs"]]
        return spec

    def set_live(self, pid, text):
        lab, rest = split_id(pid)
        a = next((x for x in self.usable() if x.label == lab), None)
        if a is None:
            raise ValueError(f"The input '{pid}' cannot be set from here.")
        a.ad.set_live(rest, text)

    def base_state(self):
        return {a.label: a.ad.base_state() for a in self.usable()}
