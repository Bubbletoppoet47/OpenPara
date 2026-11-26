"""wb_coupled.py - the Coupled Physics block of the workbench: one heat analysis and one stress analysis of the SAME geometry (both 2D or both 3D) solved together, or a Fluid
Flow analysis together with a Thermal analysis (they exchange heat) and / or a Static Structural analysis (it takes the pressure), all 2D or all 3D.

The cells:   Physics (import)   a wire from the Setup of a 2D / 3D Thermal block and one from the Setup of a 2D / 3D Static Structural block, or of a 2D / 3D Fluid Flow block and a
                                Thermal and / or a Static Structural block of the same dimension.  Refresh checks them: one of each, the same dimension, wired from the same Part or Assembly block.
             Setup (data)       the coupling options (the window's state file); always ready.
             Solution (compute) Update opens the window (it shows the analyses wired in, each on its own tab of the strip: Fluid, Thermal, Structural), solves the heat analysis, hands its
                                temperature to the stress analysis and solves that.  The results live in the analyses and in the Coupled Physics window; closing the window makes the solution 'update' again.
             Results (view)     opens the window.
The block is an ordinary project folder (.gpx: simulation.json + state.sim) kept as data in node.data["files"], like the analyses.  The analyses are set up in the strip of its window (they have
no tab of their own while they are wired in: double-clicking one of them opens this window on its tab); a stress analysis wired in needs supports but no load (the temperature is its load).
Saving the block on its own gives the folder.
"""
import hashlib
import os
import shutil

import wb_analysis
import wb_nodes as nodes
import wb_parts
import wb_project as wp

ROLE = {"thermal": "thermal", "thermal3d": "thermal", "fea": "structural", "solid": "structural", "cfd": "fluid", "fluid3d": "fluid"}      # what each kind of analysis is to the coupling
DIM = {"thermal": 2, "fea": 2, "cfd": 2, "thermal3d": 3, "solid": 3, "fluid3d": 3}
TWO_D = ("thermal", "fea", "cfd")
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
        """{"thermal": node or None, "structural": node or None, "fluid": node or None} of the analyses wired in (the first of each)."""
        out = {"thermal": None, "structural": None, "fluid": None}
        for n in self.member_nodes(tab, node):
            out.setdefault(ROLE[n.kind], None)
            if out[ROLE[n.kind]] is None:
                out[ROLE[n.kind]] = n
        return out

    def problems(self, tab, node):
        """The reason, in words, why what is wired in cannot be coupled, or None."""
        ms = self.member_nodes(tab, node)
        r = {"thermal": [n for n in ms if ROLE[n.kind] == "thermal"], "structural": [n for n in ms if ROLE[n.kind] == "structural"], "fluid": [n for n in ms if ROLE[n.kind] == "fluid"]}
        if r["fluid"]:
            return self.fluid_problems(tab, r)
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

    def fluid_problems(self, tab, r):
        """The wiring with a Fluid Flow analysis: it needs a Thermal and / or a Static Structural analysis next to it, all of its dimension, all of the same geometry."""
        if len(r["thermal"]) > 1 or len(r["structural"]) > 1 or len(r["fluid"]) > 1:
            return "One Fluid Flow, one Thermal and one Static Structural analysis can be coupled at a time for now: take the others out of the Physics cell."
        dim = DIM[r["fluid"][0].kind]
        if not r["thermal"] and not r["structural"]:
            return (f"A {dim}D Fluid Flow analysis is coupled with a Thermal analysis (heat exchange) or a Static Structural analysis (pressure): wire the Setup of a {dim}D Thermal or a "
                    f"{dim}D Static Structural analysis into the Physics cell as well.")
        members = [x[0] for x in (r["fluid"], r["thermal"], r["structural"]) if x]
        for n in members:
            if DIM[n.kind] != dim:
                return (f"{self.name_of(n)} is {DIM[n.kind]}D and {self.name_of(r['fluid'][0])} is {dim}D: a Fluid Flow analysis is coupled with analyses of its own dimension, so wire in "
                        f"{dim}D analyses.")
        src = {}
        for n in members:
            g = tab.project.incoming(n.id, "geometry")
            if g is None:
                return "Every analysis needs its geometry first: wire each of them from the same Part or Assembly block."
            src[n.id] = g.a
        if len(set(src.values())) > 1:
            names = "; ".join(f"{self.name_of(n)} works on {self.name_of(tab.project.nodes[src[n.id]])}" for n in members)
            return f"The analyses must work on the same geometry, so wire all of them from the same Part or Assembly block ({names})."
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
        fl = self.roles(tab, node).get("fluid")
        roles = self.roles(tab, node)
        return {"windows": lambda: self.windows(tab, node), "labels": self.labels(tab, node), "titles": {r: (n.title if n is not None else "") for r, n in roles.items()},
                "show": show, "problem": why, "note": None,
                "dim": (DIM[fl.kind] if fl is not None else None), "part": self.part_name(tab, node), "marks": lambda: self.setup_marks(tab, node),
                "deps_key": lambda: self.deps_key(tab, node)}

    def part_name(self, tab, node):
        """The name of the part or assembly the analyses work on (the first one found), or None."""
        for n in self.member_nodes(tab, node):
            g = tab.project.incoming(n.id, "geometry")
            if g is not None and g.a in tab.project.nodes:
                return tab.project.nodes[g.a].title
        return None

    def setup_marks(self, tab, node):
        """{role: 'ok' | 'incomplete' | 'update'} from the Setup cell of each analysis wired in (what the strip of the window shows)."""
        out = {}
        for role, n in self.roles(tab, node).items():
            if n is None:
                continue
            st = tab.project.status(n.id, "setup")
            out[role] = "ok" if st == wp.OK else ("incomplete" if st == wp.INCOMPLETE else "update")
        return out

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
        self.host_members(tab, node, w)
        if not front and front_w is not None:
            h.tabs.setCurrentWidget(front_w)
        return w

    # ---- the analyses shown inside the window
    def hostable(self, n):
        try:
            import coupled_host
        except ImportError:
            return False
        return coupled_host.can_host(n.kind)

    def host_members(self, tab, node, cw):
        """Every analysis wired in that the window can show is shown in it: its own tab (if it has one) is closed first, the window of its project folder is made without a tab and its panes go
        into the strip of `cw`."""
        out = {}
        for role, n in self.roles(tab, node).items():
            if n is not None and self.hostable(n):
                out[role] = self.host_member(tab, node, cw, n)
        cw.refresh()
        return out

    def host_member(self, tab, node, cw, n):
        """The analysis `n` is shown inside the window `cw` of the Coupled Physics block `node`.  -> its window (already hosted: the same one), or None when it could not be made."""
        if tab.hosted_by(n.id) == node.id:
            return tab.editor_of(n.id)
        a = nodes.adapter_for(n.kind)
        ok, why = a.available(tab)
        if not ok:
            tab.say(why)
            return None
        if tab.editor_of(n.id) is not None:                      # it has a tab of its own (or another block shows it): saved and closed, its state travels in its project folder
            a.close_editor(tab, n)
        tab.sync_editors()                                       # what was done in it is taken before its folder is written again
        f = a.materialize(tab, n)
        mw = a.window(tab, f, threaded=True)
        tab.register_hosted(n, mw, node)
        cw.host_member(ROLE[n.kind], mw)
        st = a.state(tab, n)
        try:
            if mw.is_dirty():                                    # (a window may find its own housekeeping to write: that is not the person's change)
                mw.save()
        except Exception:                                        # noqa: BLE001
            pass
        st["base"] = wb_analysis.digests(f)
        st["had_editor"] = True
        return mw

    def release_member(self, tab, node, n):
        """The analysis `n` leaves the window of the Coupled Physics block `node` (it is not wired in any more, or its geometry is refreshed): saved, read back into the project, its window shut
        down.  Its results go with it, so its solution says 'update' again."""
        mw = tab.editor_of(n.id)
        a = nodes.adapter_for(n.kind)
        if mw is None or tab.hosted_by(n.id) != node.id:
            return
        try:
            if mw.is_dirty():
                mw.save()
        except Exception:                                        # noqa: BLE001
            pass
        for key in (a.sync(tab, n) or []):
            tab.project.touch(n.id, key)
        cw = tab.editor_of(node.id)
        if cw is not None:
            cw.unhost_member(ROLE[n.kind])
        tab.hosted.pop(n.id, None)
        a.drop_window(mw)
        a.state(tab, n)["had_editor"] = False
        tab.project.set_ready(n.id, "solution", False)

    def open_member(self, tab, node, n, front=True, say=True):
        """The analysis `n` (wired into the block `node`) opens in the window of that block, on its own tab of the strip.  -> the analysis window."""
        cw = tab.editor_of(node.id)
        if cw is None:
            cw = self.open_editor(tab, node, front=front)
        elif front:
            self.show(tab, cw)
        if cw is None:
            return None
        if tab.hosted_by(n.id) != node.id and self.hostable(n):
            self.host_member(tab, node, cw, n)
            cw.refresh()
        if front:
            cw.show_role(ROLE[n.kind])
            if say:
                text = f"‘{n.title}’ is part of ‘{node.title}’: it opens here."
                cw.line.setText(text)
                tab.say(text)
        return tab.editor_of(n.id)

    def relink(self, tab, node):
        """A wire was made or removed: an open window shows the analyses that are wired in now (one that was taken out is saved and leaves; one that was put in moves in, from its own tab)."""
        cw = tab.editor_of(node.id)
        if cw is None:
            return
        want = {n.id: n for n in self.roles(tab, node).values() if n is not None and self.hostable(n)}
        for nid in [i for i, (_w, owner) in list(tab.hosted.items()) if owner == node.id and i not in want]:
            if nid in tab.project.nodes:
                self.release_member(tab, node, tab.project.nodes[nid])
            else:
                tab.hosted.pop(nid, None)
        for n in want.values():
            if tab.hosted_by(n.id) != node.id:
                self.host_member(tab, node, cw, n)
        cw.refresh()
        tab.scene.refresh()

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
        for nid in [i for i, (_w, owner) in list(tab.hosted.items()) if owner == node.id]:        # the analyses it showed went with it (their results too: their solutions say 'update' at the next read-back)
            tab.hosted.pop(nid, None)

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
