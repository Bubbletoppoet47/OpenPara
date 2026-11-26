"""wb_analysis.py - the analysis blocks of the workbench: 3D Static Structural, 3D Thermal, 2D Static Structural, 2D Thermal, 2D Fluid Flow, 1D Beam / Truss.

Every one of them is an ordinary simulation PROJECT FOLDER (simulation.json, state.sim, source/ ... - addons_src/simulation/sim_project.py) opened in the window the add-on already has.
The block keeps that folder as data (node.data["files"]: the files of the folder, text or base64) without the MESHES and RESULTS (they are worked out again: Update).  Double-click:
the folder is written to the project's workspace and opened in the usual tab.  What is done in the tab is read back (when the project is saved, when the Workbench is shown again,
before Update Project).

The cells:   Geometry (import)  the part or assembly the analysis works on.  With a wire from a Part / Assembly block it is that block's geometry: Refresh copies it into the project
                                 folder again (the same thing the tab's own 'Update from original' does).  An assembly that keeps its parts inside it is first written as plain files.
             Setup (data)        the material, supports, loads, mesh settings ... (what the tab saves); ready when there is something to solve.
             Solution (compute)  Update opens the tab (when it is not open), solves in it and waits for the end.  The result lives in the open tab only: closing the tab makes the
                                 solution 'update' again.
             Results (view)      opens the tab.
Saving a block on its own gives the project folder (.gpv, .gpt, ...) with its copy of the part, so it opens in the program like any other.
"""
import copy
import hashlib
import io
import json
import os
import shutil
import tempfile
import time
import zipfile

import wb_nodes as nodes
import wb_parts
import wb_project as wp

RESULT_KEYS = ("mesh", "result", "frames", "setup_used", "res_html", "frame_index", "field", "sel", "last_mat", "auto_def")   # what a 2D state holds besides the inputs: worked out again
KEEP_SETUP = ("fea",)                                                     # the 2D kinds whose supports and loads (they point at the sketch's edges by id) are carried over a refresh
TARGET_ATTR = {"pt": "pts", "ln": "lns", "ar": "ars", "ci": "cis"}        # where a model keeps the things a support or a load can point at
WAIT_LIMIT = 3600.0                                                       # seconds an Update waits for a solve before it says it did not finish


# ---------------------------------------------------------------------------------------------------------------------------- the files of a project folder
def sim_project():
    import sim_project as sp
    return sp


def state_object(folder):
    """The saved state of an analysis project as plain data WITHOUT its meshes and results ({} when there is none).  A 3D project's state.sim is JSON; a 2D one's is a zip
    of pickles (physics_store)."""
    p = os.path.join(folder, "state.sim")
    if not os.path.isfile(p):
        return {}
    if zipfile.is_zipfile(p):
        import physics_store as pstore
        d = pstore.load(p) or {}
        return {k: ({a: b for a, b in v.items() if a not in RESULT_KEYS} if isinstance(v, dict) else v) for k, v in d.items()}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def stripped_zip(path):
    """The bytes of a 2D project's state.sim without meshes and results (when it cannot be rewritten as it must be read again, the file as it is)."""
    with open(path, "rb") as f:
        raw_file = f.read()
    try:
        import pickle
        import physics_store as pstore
        buf = io.BytesIO()
        with zipfile.ZipFile(path) as zin, zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
            for info in zin.infolist():
                raw = zin.read(info.filename)
                if info.filename.startswith("tabs/") and info.filename.endswith(".pkl"):
                    st = pstore._loads(raw)
                    if isinstance(st, dict):
                        raw = pickle.dumps({k: v for k, v in st.items() if k not in RESULT_KEYS}, protocol=4)
                        pstore._loads(raw)                       # it must read back, or the file is left as it was
                zout.writestr(info.filename, raw)
        return buf.getvalue()
    except Exception:                                            # noqa: BLE001
        return raw_file


def pack(folder):
    """{relative path: stored file} of a project folder without meshes and results."""
    files = wp.pack_folder(folder, skip=lambda rel: rel.endswith(".tmp") or rel.endswith(".new") or (rel.startswith("study/") and "/cases/" in rel))   # (the full result of every study case is not kept)
    sp = os.path.join(folder, "state.sim")
    if "state.sim" in files and zipfile.is_zipfile(sp):
        files["state.sim"] = wp.pack_bytes(stripped_zip(sp))
    return files


def digests(folder):
    """{"geometry": ..., "setup": ...}: what the project folder holds as a copy of the source, and what it holds as inputs (not the results, not the times of saving)."""
    out = {}
    h = hashlib.sha1()
    sd = os.path.join(folder, "source")
    for root, dirs, fs in os.walk(sd):
        dirs.sort()
        for fn in sorted(fs):
            full = os.path.join(root, fn)
            h.update(os.path.relpath(full, sd).replace(os.sep, "/").encode())
            with open(full, "rb") as f:
                h.update(f.read())
    out["geometry"] = h.hexdigest()
    h = hashlib.sha1()
    sd = os.path.join(folder, "study")
    for root, dirs, fs in os.walk(sd):
        dirs.sort()
        for fn in sorted(fs):
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, sd).replace(os.sep, "/")
            if "cases/" in rel or rel.endswith(".tmp"):
                continue
            h.update(rel.encode())
            with open(full, "rb") as f:
                h.update(f.read())
    out["study"] = h.hexdigest()                                 # the parametric study kept in the folder: it is saved with the block but never makes the solution out of date
    st = state_object(folder)
    try:
        m = json.load(open(os.path.join(folder, "simulation.json"), encoding="utf-8"))
        meta = m.get("meta")
    except (OSError, ValueError):
        meta = None
    out["setup"] = hashlib.sha1(json.dumps([st, meta], sort_keys=True, default=repr).encode()).hexdigest()
    return out


def fits(model, item):
    """True when every edge or point a support / load points at is still in the sketch `model`."""
    ts = item.get("targets") if isinstance(item, dict) else None
    if not ts:
        return False
    for tg in ts:
        try:
            kind, i = tg
        except (TypeError, ValueError):
            return False
        if i not in getattr(model, TARGET_ATTR.get(kind, ""), {}):
            return False
    return True


def has_source(folder):
    try:
        return bool(sim_project().source_file(folder))
    except Exception:                                            # noqa: BLE001
        return False


# ---------------------------------------------------------------------------------------------------------------------------- what 'setup is ready' means without a window
def _lists(st, *keys):
    return all(bool(st.get(k)) for k in keys)


def _driven(s):
    """Loads, or a support that moves its points by a given amount (a Displacement): either one drives the analysis."""
    if s.get("loads"):
        return True
    try:
        import sim_disp
    except ImportError:
        return False
    return sim_disp.has_imposed(s.get("supports"))


def ready_solid(st):
    s = st.get("setup") or {}
    return bool(s.get("supports")) and _driven(s)


def ready_thermal3d(st):
    s = st.get("setup") or {}
    try:
        import thermal3d_model as tm
        return any(s.get(k) for k in tm.KEYS)
    except ImportError:
        return False


def ready_fluid3d(st):
    """3D Fluid Flow: the setup is ready when the fluid has a flow in it (a speed and a direction) and the box of fluid around the part is set."""
    s = st.get("setup") or {}
    fl = s.get("flow") or {}
    return bool(fl) and bool(s.get("domain")) and bool(s.get("fluid"))


def ready_fea(st):
    m = st.get("main") or {}
    return bool(m.get("supports")) and _driven(m)


def ready_beam(st):
    m = st.get("main") or {}
    return _lists(m, "members", "supports")


def ready_has_model(st):
    return bool((st.get("main") or {}).get("model_json"))


# ---------------------------------------------------------------------------------------------------------------------------- the adapter
class AnalysisAdapter(nodes.Adapter):
    first_cell = "geometry"
    simulation = True                # opening the block brings its geometry up to date from the wire (never the solve): wb_tab.refresh_geometry_on_open

    def __init__(self, kind, tab_kind, sim_kind, setup_ready, addon, two_d=False):
        self.kind, self.tab_kind, self.sim_kind, self.setup_ready, self.addon, self.two_d = kind, tab_kind, sim_kind, setup_ready, addon, two_d

    # ---- is it possible here
    def available(self, tab):
        try:
            import addons
            kinds = addons.tab_kinds()
        except Exception:                                        # noqa: BLE001
            kinds = {}
        if self.tab_kind not in kinds:
            return False, f"This system needs the add-on '{self.addon}', which is not installed or is switched off (Add-ons)."
        try:
            sim_project()
        except ImportError:
            return False, "This system needs the add-on 'Simulation (1D FEA, 2D FEA, 2D CFD)', which is not installed or is switched off (Add-ons)."
        return True, ""

    # ---- the project folder in the workspace
    def folder_of(self, tab, node):
        return os.path.join(nodes.workspace_of(tab, node), nodes.safe_stem(node.title) + sim_project().EXT[self.sim_kind])

    def state(self, tab, node):
        return tab.node_state.setdefault(node.id, {})

    def materialize(self, tab, node):
        """Writes the block's project folder to the workspace (a new, empty project when it has none yet); -> the folder."""
        sp = sim_project()
        st = self.state(tab, node)
        f = self.folder_of(tab, node)
        shutil.rmtree(f, ignore_errors=True)
        files = node.data.get("files")
        if files:
            wp.unpack_folder(files, f)
        else:
            sp.create(f, self.sim_kind)
        st["folder"] = f
        return f

    def window(self, tab, folder, threaded=True):
        """The analysis window of a project folder (made, not shown)."""
        import importlib
        import addons
        spec = addons.tab_kinds()[self.tab_kind]
        w = getattr(importlib.import_module(spec["module"]), spec["factory"])(tab.host, folder)
        w.kind = self.tab_kind
        if hasattr(w, "threaded"):
            w.threaded = threaded
        return w

    def hostable(self):
        """True when the panes of this kind of analysis can be shown inside a Coupled Physics window (coupled_host)."""
        try:
            import coupled_host
        except ImportError:
            return False
        return coupled_host.can_host(self.kind)

    def hosting_block(self, tab, node):
        """The Coupled Physics block whose window shows this analysis, or None: it is wired into the Physics cell of that block (and so is one of its members), and the Coupled Physics add-on is
        there and can show this kind of analysis.  Such an analysis has no tab of its own: it is set up in the strip of that window."""
        if not self.hostable():
            return None
        cn = self.coupled_nodes(tab, node)
        ca = nodes.adapter_for("coupled")
        if not cn or ca is None:
            return None
        ok, _why = ca.available(tab)
        if not ok:
            return None
        return cn[0] if node.id in {m.id for m in ca.member_nodes(tab, cn[0])} else None

    def open_cell(self, tab, node, key):
        blk = self.hosting_block(tab, node)
        if blk is not None:                                      # part of a Coupled Physics block: it opens in that block's window, on its own tab of the strip
            return nodes.adapter_for("coupled").open_member(tab, blk, node, say=True)
        w = tab.editor_of(node.id)
        if w is not None:
            self.show(tab, w)
            return w
        w = self.open_editor(tab, node)
        if w is not None:
            tab.say(f"{node.label} {node.title}: work in its tab. The project takes the changes when you save it or come back here. The results stay in the tab only.")
        return w

    def show(self, tab, w):
        h = tab.host
        if h is not None and hasattr(h, "tabs"):
            h.tabs.setCurrentWidget(w)

    def open_editor(self, tab, node, front=True, hosted=True):
        """The editor of the analysis: its window (a tab of its own, or a place in the window of the Coupled Physics block it is wired into: `hosted` False asks for a tab of its own even then,
        which is how the setups of the example project are made).  An analysis already open is returned as it is."""
        w = tab.editor_of(node.id)
        if w is not None:
            return w
        if hosted:
            blk = self.hosting_block(tab, node)
            if blk is not None:
                return nodes.adapter_for("coupled").open_member(tab, blk, node, front=front, say=False)
        h = tab.host
        if h is None or not hasattr(h, "new_addon_tab"):
            tab.say(f"'{node.title}' opens in the program window; there is none here.")
            return None
        front_w = h.tabs.currentWidget() if hasattr(h, "tabs") else None
        tab.sync_editors()
        f = self.materialize(tab, node)
        w = h.new_addon_tab(self.tab_kind, f)
        if w is None:
            return None
        tab.adopt_editor(node, w)
        st = self.state(tab, node)
        try:
            if w.is_dirty():                                     # a window may find its own housekeeping to write (a first state): that is not the person's change
                w.save()
        except Exception:                                        # noqa: BLE001
            pass
        st["base"] = digests(f)
        st["had_editor"] = True
        if not front and front_w is not None:
            h.tabs.setCurrentWidget(front_w)
        return w

    # ---- reading back
    COUPLED_KINDS = ("solid", "fea")                         # the stress analyses: wired into Coupled Physics they need supports but no load (the temperature is the load)

    def coupled_nodes(self, tab, node):
        """The Coupled Physics blocks that this analysis's Setup is wired into."""
        out = []
        for k in tab.project.outgoing(node.id, "setup"):
            n = tab.project.nodes.get(k.b)
            if n is not None and n.kind == "coupled":
                out.append(n)
        return out

    def supported(self, folder):
        """True when the setup in the project folder has supports (a stress analysis in Coupled Physics: that is all it needs of its own)."""
        try:
            st = state_object(folder)
        except Exception:                                    # noqa: BLE001
            return False
        s = (st.get("setup") if self.kind == "solid" else st.get("main")) or {}
        return bool(s.get("supports"))

    def setup_is_ready(self, w, folder, tab=None, node=None):
        if tab is not None and node is not None and self.kind in self.COUPLED_KINDS and self.coupled_nodes(tab, node):
            return self.supported(folder)
        if w is not None and hasattr(w, "ready"):
            try:
                return not w.ready()
            except Exception:                                    # noqa: BLE001
                pass
        try:
            return bool(self.setup_ready(state_object(folder)))
        except Exception:                                        # noqa: BLE001
            return False

    def sync(self, tab, node):
        st = tab.node_state.get(node.id)
        if not st or "base" not in st:
            return None                                          # never opened: nothing to read back
        w = tab.editor_of(node.id)
        folder = st.get("folder")
        if not folder or not os.path.isdir(folder):
            return None
        changed = []
        if w is not None:
            try:
                if w.is_dirty():
                    w.save()
            except Exception as ex:                              # noqa: BLE001
                tab.say(f"'{node.title}' could not be saved into the project: {ex}")
        elif st.get("had_editor"):
            st["had_editor"] = False                             # its tab was closed: the results went with it
            tab.project.set_ready(node.id, "solution", False)
            changed.append(None)
        d = digests(folder)
        base = st["base"]
        for key in ("geometry", "setup"):
            if d[key] != base.get(key):
                changed.append(key)
        study_changed = d.get("study") != base.get("study")
        if "geometry" in changed or "setup" in changed or study_changed:
            node.data["files"] = pack(folder)
            if study_changed and not changed:
                tab.project.changed()                            # (the file needs saving, but no cell of the analysis changed)
        st["base"] = d
        if "geometry" in changed:
            tab.project.set_ready(node.id, "geometry", has_source(folder))
        if "setup" in changed or "geometry" in changed:
            tab.project.set_ready(node.id, "setup", self.setup_is_ready(w, folder, tab, node))
        keys = [k for k in changed if k]
        return keys or None

    def relink(self, tab, node):
        """Wired into (or taken out of) Coupled Physics: a stress analysis needs a load of its own or not.  Looked at again for the setup the block has now."""
        if self.kind not in self.COUPLED_KINDS:
            return
        st = tab.node_state.get(node.id)
        folder = st.get("folder") if st else None
        if not folder or not os.path.isdir(folder):
            return                                           # never opened: there is no setup to look at
        w = tab.editor_of(node.id)
        try:
            if w is not None and w.is_dirty():
                w.save()
        except Exception:                                    # noqa: BLE001
            return
        tab.project.set_ready(node.id, "setup", self.setup_is_ready(w, folder, tab, node))

    def created(self, tab, node):
        """A 1D Beam / Truss starts with its Profile cell ready: profiles are optional (the frame's own sketches work without any wire)."""
        if node.spec is not None and node.spec.cell("profile") is not None:
            tab.project.set_ready(node.id, "profile", True)

    # ---- refresh: the geometry from the wire
    def source_of(self, tab, node, key):
        """(name, text or flat file path, kind) of the block the geometry cell is wired to, or an error text."""
        k = tab.project.incoming(node.id, key)
        if k is None:
            return None
        src = tab.project.node(k.a)
        if src.kind == "part" and src.data.get("doc") is not None:
            return src, json.dumps(src.data["doc"])
        if src.kind == "assembly" and src.data.get("asm") is not None:
            return src, src.data["asm"]
        return src, None

    def refresh_profiles(self, tab, node):
        """Every Part wired into the Profile cell is copied into the project's profiles/ (again, when it is there already: the profile sketches taken from it stay linked
        and are worked out again); a part whose wire is gone leaves the project.  -> None, or the text of what went wrong."""
        prj = tab.project
        wired = []
        for k in prj.incoming_all(node.id, "profile"):
            src = prj.node(k.a)
            if src.kind != "part" or src.data.get("doc") is None:
                return f"'{src.title}' is empty: there is no part to take profile sketches from."
            wired.append(src)
        sp = sim_project()
        tab.sync_editors()
        reopen = tab.editor_of(node.id) is not None
        if reopen:
            self.close_editor(tab, node)
        f = self.materialize(tab, node)
        w = None
        err = None
        try:
            have = {e["wb"]: e for e in sp.profile_parts(f) if e.get("wb")}
            for src in wired:
                old = have.pop(src.id, None)
                sp.import_profile_part(f, text=json.dumps(src.data["doc"]), name=src.title, key=old["key"] if old else None, extra={"wb": src.id})
            for e in have.values():
                sp.remove_profile_part(f, e["key"])
            if has_source(f):                                    # the profile sketches of the members are worked out again from the new copies
                w = self.window(tab, f, threaded=False)
                notes = w.tab.refresh_profs() if hasattr(w.tab, "refresh_profs") else []
                w.save()
                if notes:
                    tab.note(f"{node.label} {node.title}: " + " ".join(notes))
        except Exception as ex:                                  # noqa: BLE001
            err = f"{type(ex).__name__}: {ex}"
        finally:
            if w is not None:
                self.drop_window(w)
        if err:
            return err
        st = self.state(tab, node)
        node.data["files"] = pack(f)
        st["base"] = digests(f)
        if reopen:
            self.open_editor(tab, node, front=False)
        return None

    def refresh(self, tab, node, key):
        if key == "profile":
            return self.refresh_profiles(tab, node)
        if key != "geometry":
            return None
        got = self.source_of(tab, node, key)
        if got is None:
            return "There is no wire into this cell: nothing to refresh from."
        src, payload = got
        if payload is None:
            return f"'{src.title}' is empty: there is no geometry to take."
        sp = sim_project()
        tab.sync_editors()
        reopen = tab.editor_of(node.id) is not None
        if reopen:
            self.close_editor(tab, node)
        f = self.materialize(tab, node)
        tmp = tempfile.mkdtemp(prefix="opara_wbsrc_")
        err = None
        w = None
        try:
            name = nodes.safe_stem(src.title)
            if src.kind == "assembly":
                import asm_embed
                flat = asm_embed.flatten_to_files(payload, tmp, name)
                orig, text = flat, None
            else:
                orig, text = os.path.join(tmp, name + ".gpd"), payload
            if has_source(f):                                    # the analysis has a copy already: the window's own 'Update from original' does it (and keeps what it keeps)
                w = self.window(tab, f, threaded=False)
                w.original_text = lambda o=orig, t=text: (o, t)
                if hasattr(w, "src"):
                    w.src["name"] = name
                keep = self.setup_before(w)
                w.refresh()
                if getattr(w, "source", None) is None:
                    err = "the geometry could not be copied into the analysis"
                else:
                    lost = self.setup_after(w, keep)
                    if lost:
                        tab.note(f"{node.label} {node.title}: {lost} support(s) or load(s) pointed at edges the new sketch does not have and were dropped.")
            else:                                                # the first copy
                sp.import_source(f, orig_path=orig, text=text, name=name)
            m = sp.read(f)
            if m.get("source"):
                m["source"]["orig"] = None                       # (a path on this computer does not belong in the project file)
                sp.write(f, m)
        except Exception as ex:                                  # noqa: BLE001
            err = f"{type(ex).__name__}: {ex}"
        finally:
            if w is not None:
                self.drop_window(w)
            shutil.rmtree(tmp, ignore_errors=True)
        if err:
            return err
        st = self.state(tab, node)
        node.data["files"] = pack(f)
        st["base"] = digests(f)
        tab.project.set_ready(node.id, "setup", self.setup_is_ready(None, f))
        if reopen:
            self.open_editor(tab, node, front=False)
        return None

    def setup_before(self, w):
        """What a 2D analysis keeps over a refresh (the window's own 'Update from original' imports the sketch again, which clears it): the supports, the loads and the element size."""
        t = getattr(w, "tab", None)
        if self.kind not in KEEP_SETUP or t is None or getattr(t, "model", None) is None:
            return None
        return {"supports": copy.deepcopy(t.supports), "loads": copy.deepcopy(t.loads), "h": t.e_h.text()}

    def setup_after(self, w, keep):
        """Puts back what still fits the new sketch.  -> how many supports and loads had to be dropped."""
        t = getattr(w, "tab", None)
        if keep is None or t is None or getattr(t, "model", None) is None:
            return 0
        sup = [x for x in keep["supports"] if fits(t.model, x)]
        lds = [x for x in keep["loads"] if fits(t.model, x)]
        t.supports, t.loads = sup, lds
        t.e_h.setText(keep["h"])
        t.refresh_lists()
        w.save()
        return len(keep["supports"]) - len(sup) + len(keep["loads"]) - len(lds)

    def drop_window(self, w):
        try:
            if hasattr(w, "shutdown"):
                w.shutdown()
            w.deleteLater()
        except Exception:                                        # noqa: BLE001
            pass

    # ---- update: solve
    def update(self, tab, node, key):
        if key != "solution":
            return None
        cn = self.coupled_nodes(tab, node)
        if cn:                                               # it is solved together with its partner: that is the answer of both
            ca = nodes.adapter_for("coupled")
            if ca is not None:
                return ca.update(tab, cn[0], "solution")
        w = tab.editor_of(node.id)
        if w is None:
            w = self.open_editor(tab, node, front=False)
        if w is None:
            return "The analysis could not be opened to solve it."
        try:
            err = self.solve(w)
        except Exception as ex:                                  # noqa: BLE001
            return f"{type(ex).__name__}: {ex}"
        if err is None:
            self.absorb(tab, node, w)
        return err

    def absorb(self, tab, node, w):
        """A solve changes nothing the person typed: what the window holds now is the project's, and it is not a change that makes the solution out of date."""
        st = self.state(tab, node)
        folder = st.get("folder")
        if not folder or not os.path.isdir(folder):
            return
        try:
            if w.is_dirty():
                w.save()
        except Exception:                                        # noqa: BLE001
            return
        d = digests(folder)
        if d != st.get("base"):
            node.data["files"] = pack(folder)
            st["base"] = d

    def take_study(self, tab, node):
        """The parametric study of this analysis was saved in its folder: the block takes it (and the file needs saving).  -> True when it changed."""
        st = self.state(tab, node)
        folder = st.get("folder")
        if not folder or not os.path.isdir(folder):
            return False
        d = digests(folder)
        base = st.get("base") or {}
        if d.get("study") == base.get("study"):
            return False
        node.data["files"] = pack(folder)
        st["base"] = {**base, "study": d["study"]}
        tab.project.changed()
        return True

    def close_studies(self, tab, node):
        """The tabs of the Parametric Study blocks wired to this analysis close with it (a study needs the analysis's window)."""
        sa = nodes.adapter_for("study")
        for k in list(tab.project.outgoing(node.id, "setup")):
            sn = tab.project.nodes.get(k.b)
            if sn is not None and sn.kind == "study" and sa is not None:
                sa.close_editor(tab, sn)

    def solve_2d(self, w):
        """A 2D / 1D window holds a solver tab that meshes and solves in a progress dialog of its own (it returns when it is done)."""
        t = getattr(w, "tab", None)
        if t is None or getattr(t, "model", None) is None:
            return "No sketch has been imported into this analysis yet: choose one in its tab and press Import."
        t.result = None
        m_ = getattr(t, "mesh", None)
        if hasattr(t, "run_mesh") and (m_ is None or (isinstance(m_, dict) and m_.get("deformed"))):          # (a mesh that follows a body a structure moved is meshed again as drawn)
            t.run_mesh()
            if t.mesh is None:
                return "the mesh could not be made (see the message in its tab)"
        fn = getattr(t, "run_solve", None) or getattr(t, "solve", None)
        if fn is None:
            return "this kind of analysis has no solver to call"
        fn()
        if getattr(t, "result", None) is None:
            return "the solve did not give a result (see the message in its tab)"
        return None

    def solve(self, w):
        from PyQt6.QtWidgets import QApplication
        if not hasattr(w, "run_job"):
            return self.solve_2d(w)
        why = w.ready()
        if why:
            return why
        if hasattr(w, "invalidate"):
            w.invalidate()
        if w.run_solve() is False and getattr(w, "job", None) is None:
            return getattr(w, "last_error", "") or "it could not be started (see the message in its tab)"
        t0 = time.monotonic()
        while getattr(w, "job", None) is not None:
            QApplication.processEvents()
            time.sleep(0.01)
            if time.monotonic() - t0 > WAIT_LIMIT:
                return "the solve did not finish in time"
        QApplication.processEvents()
        if getattr(w, "result", None) is None:
            return getattr(w, "last_error", "") or "the solve did not give a result"
        return None

    # ---- closing, saving on its own
    def close_editor(self, tab, node):
        w = tab.editor_of(node.id)
        h = tab.host
        if w is None:
            return
        self.close_studies(tab, node)
        owner = tab.hosted_by(node.id)
        if owner is not None:                                    # shown in the window of a Coupled Physics block: it leaves that window (saved), there is no tab to close
            nodes.adapter_for("coupled").release_member(tab, tab.project.nodes[owner], node)
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
        ext = sim_project().EXT[self.sim_kind]
        dest = wb_parts.unique_path(folder, nodes.safe_stem(node.title), ext)
        wp.unpack_folder(files, dest)
        return dest


def register_all():
    for args in (("solid", "solid", "solid", ready_solid, "3D FEA (parametric parts)"),
                 ("thermal3d", "thermal3d", "thermal3d", ready_thermal3d, "3D Thermal"),
                 ("fluid3d", "fluid3d", "fluid3d", ready_fluid3d, "3D Fluid Flow"),
                 ("fea", "fea", "fea", ready_fea, "Simulation (1D FEA, 2D FEA, 2D CFD)", True),
                 ("cfd", "cfd", "cfd", ready_has_model, "Simulation (1D FEA, 2D FEA, 2D CFD)", True),
                 ("beam", "beam", "beam", ready_beam, "Simulation (1D FEA, 2D FEA, 2D CFD)", True),
                 ("thermal", "thermal", "thermal", ready_has_model, "2D Thermal", True)):
        nodes.register(AnalysisAdapter(*args))


register_all()
