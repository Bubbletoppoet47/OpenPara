"""wb_coupled.py - the Coupled Physics block of the workbench: one heat analysis and one stress analysis of the SAME geometry (both 2D or both 3D) solved together.

The cells:   Physics (import)   a wire from the Setup of a 2D / 3D Thermal block and one from the Setup of a 2D / 3D Static Structural block.  Refresh checks them: one of each,
                                the same dimension, wired from the same Part or Assembly block.
             Setup (data)       the coupling options (the window's state file); always ready.
             Solution (compute) Update opens the window (and the two analyses, when they are not open), solves the heat analysis, hands its temperature to the stress analysis and
                                solves that.  The results live in the windows of the two analyses and in the Coupled Physics window; closing the window makes the solution 'update' again.
             Results (view)     opens the window.
The block is an ordinary project folder (.gpx: simulation.json + state.sim) kept as data in node.data["files"], like the analyses.  The two analyses are set up in their own windows
as usual; a stress analysis wired in needs supports but no load (the temperature is its load).  Saving the block on its own gives the folder.
"""
import hashlib
import os
import shutil

import wb_analysis
import wb_nodes as nodes
import wb_parts
import wb_project as wp

ROLE = {"thermal": "thermal", "thermal3d": "thermal", "fea": "structural", "solid": "structural"}      # what each kind of analysis is to the coupling
DIM = {"thermal": 2, "fea": 2, "thermal3d": 3, "solid": 3}
TWO_D = ("thermal", "fea")
ADDON = "Coupled Physics"


def sim_project():
    import sim_project as sp
    return sp


def state_digest(folder):
    """What the window saved as the options of the block (not the times of saving)."""
    p = os.path.join(folder, "state.sim")
    if not os.path.isfile(p):
        return ""
    with open(p, "rb") as f:
        return hashlib.sha1(f.read()).hexdigest()


class CoupledAdapter(nodes.Adapter):
    kind = "coupled"
    first_cell = "physics"

    # ---- is it possible here
    def available(self, tab):
        try:
            import addons
            kinds = addons.tab_kinds()
        except Exception:                                        # noqa: BLE001
            kinds = {}
        if "coupled" not in kinds:
            return False, f"This block needs the add-on '{ADDON}', which is not installed or is switched off (Add-ons)."
        try:
            sim_project()
        except ImportError:
            return False, "This block needs the add-on 'Simulation (1D FEA, 2D FEA, 2D CFD)', which is not installed or is switched off (Add-ons)."
        return True, ""

    def created(self, tab, node):
        tab.project.set_ready(node.id, "setup", True)            # the options have defaults: nothing to set up before it can be used

    # ---- the analyses wired in
    def member_nodes(self, tab, node):
        out = []
        for k in tab.project.incoming_all(node.id, "physics"):
            n = tab.project.nodes.get(k.a)
            if n is not None and n.kind in ROLE:
                out.append(n)
        return out

    @staticmethod
    def name_of(n):
        return f"{n.spec.label} {n.label} '{n.title}'" if n.spec is not None else f"{n.label} '{n.title}'"

    def roles(self, tab, node):
        """{"thermal": node or None, "structural": node or None} of the analyses wired in (the first of each)."""
        out = {"thermal": None, "structural": None}
        for n in self.member_nodes(tab, node):
            out.setdefault(ROLE[n.kind], None)
            if out[ROLE[n.kind]] is None:
                out[ROLE[n.kind]] = n
        return out

    def problems(self, tab, node):
        """The reason, in words, why what is wired in cannot be coupled, or None."""
        ms = self.member_nodes(tab, node)
        r = {"thermal": [n for n in ms if ROLE[n.kind] == "thermal"], "structural": [n for n in ms if ROLE[n.kind] == "structural"]}
        if not r["thermal"] or not r["structural"]:
            missing = " and ".join(t for t, k in (("a 2D or 3D Thermal analysis", "thermal"), ("a 2D or 3D Static Structural analysis", "structural")) if not r[k])
            return f"Coupled Physics needs both a heat problem and a stress problem: wire the Setup of {missing} into the Physics cell."
        if len(r["thermal"]) > 1 or len(r["structural"]) > 1:
            return "One Thermal and one Static Structural analysis can be coupled at a time for now: take the others out of the Physics cell."
        th, st = r["thermal"][0], r["structural"][0]
        if DIM[th.kind] != DIM[st.kind]:
            return (f"{self.name_of(th)} is {DIM[th.kind]}D and {self.name_of(st)} is {DIM[st.kind]}D: wire in two analyses of the same dimension "
                    f"(a 2D Thermal with a 2D Static Structural, or a 3D Thermal with a 3D Static Structural).")
        a, b = tab.project.incoming(th.id, "geometry"), tab.project.incoming(st.id, "geometry")
        if a is None or b is None:
            return "Both analyses need their geometry first: wire each of them from the same Part or Assembly block."
        if a.a != b.a:
            na, nb = tab.project.nodes[a.a], tab.project.nodes[b.a]
            return (f"{self.name_of(th)} works on {self.name_of(na)} and {self.name_of(st)} on {self.name_of(nb)}: the two analyses must work on the same geometry, so wire both "
                    f"from the same Part or Assembly block.")
        return None

    def labels(self, tab, node):
        return {role: (self.name_of(n) if n is not None else "") for role, n in self.roles(tab, node).items()}

    def windows(self, tab, node):
        """{kind: the window (3D) or the solver tab (2D)} of the two analyses, opened in the background when they are not open."""
        import coupled_engine as ce
        out = {}
        for role, n in self.roles(tab, node).items():
            if n is None:
                continue
            a = nodes.adapter_for(n.kind)
            w = tab.editor_of(n.id)
            if w is None and a is not None:
                w = a.open_editor(tab, n, front=False)
            if w is None:
                raise ce.CoupledError(f"{self.name_of(n)} could not be opened.")
            out[n.kind] = getattr(w, "tab", None) if n.kind in TWO_D else w
            if out[n.kind] is None:
                raise ce.CoupledError(f"{self.name_of(n)} has no solver window.")
        return out

    def source(self, tab, node):
        """What the Coupled Physics window asks the block for: the analyses (opened only when it solves), their names, how to bring them forward, and whether they fit."""
        show = {}
        for role, n in self.roles(tab, node).items():
            if n is not None:
                show[role] = (lambda n=n: tab.open_cell(n.id, "geometry"))
        why = self.problems(tab, node)
        return {"windows": lambda: self.windows(tab, node), "labels": self.labels(tab, node), "show": show, "problem": why, "note": None}

    # ---- the project folder in the workspace
    def state(self, tab, node):
        return tab.node_state.setdefault(node.id, {})

    def folder_of(self, tab, node):
        return os.path.join(nodes.workspace_of(tab, node), nodes.safe_stem(node.title) + sim_project().EXT["coupled"])

    def materialize(self, tab, node):
        sp = sim_project()
        st = self.state(tab, node)
        f = self.folder_of(tab, node)
        shutil.rmtree(f, ignore_errors=True)
        files = node.data.get("files")
        if files:
            wp.unpack_folder(files, f)
        else:
            sp.create(f, "coupled")
        st["folder"] = f
        return f

    def open_cell(self, tab, node, key):
        w = tab.editor_of(node.id)
        if w is not None:
            self.show(tab, w)
            return w
        return self.open_editor(tab, node)

    def show(self, tab, w):
        h = tab.host
        if h is not None and hasattr(h, "tabs"):
            h.tabs.setCurrentWidget(w)

    def open_editor(self, tab, node, front=True):
        h = tab.host
        if h is None or not hasattr(h, "new_addon_tab"):
            tab.say(f"'{node.title}' opens in the program window; there is none here.")
            return None
        front_w = h.tabs.currentWidget() if hasattr(h, "tabs") else None
        tab.sync_editors()
        f = self.materialize(tab, node)
        w = h.new_addon_tab("coupled", f)
        if w is None:
            return None
        tab.adopt_editor(node, w)
        w.members_source = lambda: self.source(tab, node)
        w.refresh()
        try:
            if w.is_dirty():
                w.save()
        except Exception:                                        # noqa: BLE001
            pass
        st = self.state(tab, node)
        st["base"] = state_digest(f)
        st["had_editor"] = True
        if not node.data.get("files"):                           # a block that was never opened has no folder yet: the one the window just made is the block's
            node.data["files"] = wb_analysis.pack(f)
            tab.project.changed()
        if not front and front_w is not None:
            h.tabs.setCurrentWidget(front_w)
        return w

    # ---- reading back
    def sync(self, tab, node):
        st = tab.node_state.get(node.id)
        if not st or "base" not in st:
            return None
        w = tab.editor_of(node.id)
        folder = st.get("folder")
        if not folder or not os.path.isdir(folder):
            return None
        keys = []
        if w is not None:
            try:
                if w.is_dirty():
                    w.save()
            except Exception as ex:                              # noqa: BLE001
                tab.say(f"'{node.title}' could not be saved into the project: {ex}")
        elif st.get("had_editor"):
            st["had_editor"] = False                             # its tab was closed: the results went with it
            st.pop("solved_key", None)
            tab.project.set_ready(node.id, "solution", False)
        d = state_digest(folder)
        if d != st["base"]:
            node.data["files"] = wb_analysis.pack(folder)
            st["base"] = d
            keys.append("setup")
        return keys or None

    # ---- refresh and update
    def refresh(self, tab, node, key):
        """Physics: what is wired in is looked at again (one of each, the same dimension, the same geometry)."""
        if key != "physics":
            return None
        why = self.problems(tab, node)
        w = tab.editor_of(node.id)
        if w is not None:
            try:
                w.refresh()
            except Exception:                                    # noqa: BLE001
                pass
        return why

    def deps_key(self, tab, node):
        """What a solve depends on: the stamps of the Geometry and Setup cells of both analyses and the options of the block (the same key = the solve is still good)."""
        parts = [("self", node.cells["setup"]["stamp"])]
        for role, n in sorted(self.roles(tab, node).items()):
            if n is not None:
                parts.append((n.id, n.cells["geometry"]["stamp"], n.cells["setup"]["stamp"]))
        return tuple(parts)

    def update(self, tab, node, key):
        """Solution: the heat analysis, the hand-over, the stress analysis.  A step that the two analyses ask for as well (their own Solution) finds it done."""
        if key != "solution":
            return None
        why = self.problems(tab, node)
        if why:
            return why
        w = tab.editor_of(node.id)
        if w is None:
            w = self.open_editor(tab, node, front=False)
        if w is None:
            return "The Coupled Physics window could not be opened to solve."
        st = self.state(tab, node)
        k = self.deps_key(tab, node)
        r = getattr(w, "result", None)
        if st.get("solved_key") == k and r is not None and r.get("ok"):
            return None
        ok = w.solve()
        if not ok:
            return (w.last_error or "the solve did not run").strip().splitlines()[-1]
        r = w.result
        if not r["ok"]:
            bad = "; ".join(f"{c['name']}: {c['detail']}" for c in r["checks"] if c["hard"] and not c["ok"])
            return "A check that stops the result failed: " + bad
        soft = [c["name"] for c in r["checks"] if not c["ok"]]
        if soft:
            tab.note(f"{node.title}: the result is there, but a check failed: {', '.join(soft)} (see the Coupled Physics window).")
        st["solved_key"] = k
        for n in self.member_nodes(tab, node):                   # the windows of the two analyses hold the results of this solve
            a = nodes.adapter_for(n.kind)
            mw = tab.editor_of(n.id)
            if a is not None and mw is not None and hasattr(a, "absorb"):
                a.absorb(tab, n, mw)
        return None

    # ---- closing, saving on its own
    def close_editor(self, tab, node):
        w = tab.editor_of(node.id)
        h = tab.host
        if w is None:
            return
        try:
            if w.is_dirty():
                w.save()
        except Exception:                                        # noqa: BLE001
            pass
        st = self.state(tab, node)
        st["had_editor"] = False
        if h is not None and hasattr(h, "tabs"):
            i = h.tabs.indexOf(w)
            if i >= 0:
                h.close_tab(i)
        tab.editors.pop(node.id, None)

    def closed(self, tab, node):
        self.close_editor(tab, node)
        tab.node_state.pop(node.id, None)

    def export(self, tab, node, folder):
        tab.sync_editors()
        files = node.data.get("files")
        if not files:
            raise ValueError(f"'{node.title}' has nothing in it yet: open it first.")
        dest = wb_parts.unique_path(folder, nodes.safe_stem(node.title), sim_project().EXT["coupled"])
        wp.unpack_folder(files, dest)
        return dest


nodes.register(CoupledAdapter())
