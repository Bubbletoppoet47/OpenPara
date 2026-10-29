"""The Sketcher project file ("name.sketcher"): ONE zip that holds everything of a project.

    manifest.json       what is inside, and the version
    project.json        the project: sketch ids, names, the name counter, which sketch each tab was made from
    sketches/<id>.skt   one entry per sketch, in the readable sketch script
    tabs/<tab>.pkl      the state of the 1D FEA, 2D FEA, CFD and Parameterization tabs (read back with a restricted unpickler that
                        only accepts plain Python containers and NumPy arrays, so a damaged or foreign file cannot run code)
    model3d.json        the model shown in the 3D Model tab and how it is displayed
    model3d/source/...  the imported model file itself (the project is self-contained)
    fea3d/...           the 3D FEA setup, mesh and results (large arrays as .npy files)

The zip is written to a temporary file and then moved over the old one, so a crash cannot destroy the earlier project.  When a project
is opened the zip stays closed on disk; entries that are big (3D arrays, the model file) are unpacked into a local cache folder
(%LOCALAPPDATA%\\Sketcher\\results_cache) and opened memory-mapped, so only what is looked at is read into memory.
"""
import hashlib
import io
import json
import os
import pickle
import re
import shutil
import time
import zipfile

MAGIC = "SKETCHER-PROJECT"
VERSION = 4                                           # 4 = the project file
EXT = ".sketcher"
MAX_ENTRY = 8 * 1024 ** 3                             # refuse a zip entry that claims to be bigger than this
_NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./-]*$")

_SAFE_BUILTINS = {"set", "frozenset", "complex", "slice", "range", "bytearray", "bytes"}
_SAFE_NUMPY = {"_reconstruct", "ndarray", "dtype", "scalar", "_frombuffer", "_reconstruct_array"}


class _Restricted(pickle.Unpickler):
    def find_class(self, module, name):
        if module == "builtins" and name in _SAFE_BUILTINS:
            return super().find_class(module, name)
        if module.split(".")[0] == "numpy" and name in _SAFE_NUMPY:
            return super().find_class(module, name)
        if module == "collections" and name == "OrderedDict":
            return super().find_class(module, name)
        raise pickle.UnpicklingError(f"not allowed in a physics file: {module}.{name}")


def _loads(raw):
    return _Restricted(io.BytesIO(raw)).load()


def _safe_name(name):
    return bool(_NAME.match(name)) and ".." not in name.split("/") and not name.startswith("/")


def cache_root():
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "Sketcher", "results_cache")


def cache_dir(skt_path):
    key = hashlib.sha1(os.path.abspath(skt_path).lower().encode("utf-8", "replace")).hexdigest()[:16]
    return os.path.join(cache_root(), key)


def clear_cache(keep_for=None):
    """Deletes the unpacked data of every project except keep_for (a .sketcher path) - called when another project is opened."""
    root = cache_root()
    keep = os.path.basename(cache_dir(keep_for)) if keep_for else None
    try:
        for d in os.listdir(root):
            if d != keep:
                shutil.rmtree(os.path.join(root, d), ignore_errors=True)
    except OSError:
        pass


class Bundle:
    """The zip of one project.  Reading never changes the file."""

    def __init__(self, skt_path):
        self.skt = skt_path
        self.path = skt_path if skt_path else None
        self._manifest = None
        self._pruned = False

    def exists(self):
        return bool(self.path) and os.path.isfile(self.path)

    def manifest(self):
        if self._manifest is None:
            with zipfile.ZipFile(self.path) as z:
                man = json.loads(z.read("manifest.json").decode("utf-8"))
            if not isinstance(man, dict) or man.get("magic") != MAGIC:
                raise ValueError(f"{os.path.basename(self.path)} is not a Sketcher project file")
            if man.get("version", 0) > VERSION:
                raise ValueError(f"{os.path.basename(self.path)} was saved by a newer version of the program")
            self._manifest = man
        return self._manifest

    def names(self):
        with zipfile.ZipFile(self.path) as z:
            return z.namelist()

    def has(self, name):
        try:
            return name in self.names()
        except Exception:
            return False

    def read(self, name):
        if not _safe_name(name):
            raise ValueError(f"bad entry name {name!r}")
        with zipfile.ZipFile(self.path) as z:
            info = z.getinfo(name)
            if info.file_size > MAX_ENTRY:
                raise ValueError(f"{name} is too large")
            return z.read(name)

    def extract(self, name):
        """Unpacks one entry into the local cache (once per saved version of the zip) and returns the file path.  Every version of the
        zip gets its own folder, so files that are still open (memory-mapped arrays) are never pulled away by a later save."""
        if not _safe_name(name):
            raise ValueError(f"bad entry name {name!r}")
        st = os.stat(self.path)
        root = os.path.join(cache_dir(self.skt), f"v{st.st_mtime_ns}_{st.st_size}")
        if not self._pruned:
            self._pruned = True
            top = os.path.dirname(root)
            try:
                for d in os.listdir(top):
                    if d != os.path.basename(root):
                        shutil.rmtree(os.path.join(top, d), ignore_errors=True)
            except OSError:
                pass
        dest = os.path.join(root, *name.split("/"))
        if not os.path.isfile(dest):
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with zipfile.ZipFile(self.path) as z:
                info = z.getinfo(name)
                if info.file_size > MAX_ENTRY:
                    raise ValueError(f"{name} is too large")
                tmp = dest + ".part"
                with z.open(info) as src, open(tmp, "wb") as out:
                    shutil.copyfileobj(src, out, 1 << 20)
            os.replace(tmp, dest)
        return dest


    def extract_stable(self, name, file_name=None):
        """Unpacks one entry into a folder that stays the same when the project is saved again (the imported model file, which the
        3D Model tab keeps using).  The folder is named after the entry's checksum and size."""
        if not _safe_name(name):
            raise ValueError(f"bad entry name {name!r}")
        with zipfile.ZipFile(self.path) as z:
            info = z.getinfo(name)
            if info.file_size > MAX_ENTRY:
                raise ValueError(f"{name} is too large")
            top = os.path.join(os.path.dirname(cache_root()), "models")
            root = os.path.join(top, f"{info.CRC:08x}_{info.file_size}")
            leaf = os.path.basename(file_name or name) or os.path.basename(name)
            dest = os.path.join(root, leaf)
            if not os.path.isfile(dest):
                _prune_models(top, root)
                os.makedirs(root, exist_ok=True)
                tmp = dest + ".part"
                with z.open(info) as src, open(tmp, "wb") as out:
                    shutil.copyfileobj(src, out, 1 << 20)
                os.replace(tmp, dest)
        return dest


_MODELS_PRUNED = False


def _prune_models(top, keep):
    """Removes unpacked model files that were not used for 60 days (once per run)."""
    global _MODELS_PRUNED
    if _MODELS_PRUNED:
        return
    _MODELS_PRUNED = True
    try:
        limit = time.time() - 60 * 86400
        for d in os.listdir(top):
            p = os.path.join(top, d)
            if p != keep and os.path.isdir(p) and os.path.getmtime(p) < limit:
                shutil.rmtree(p, ignore_errors=True)
    except OSError:
        pass


def open_bundle(skt_path):
    """-> Bundle for the project file, or None when it does not exist."""
    if not skt_path:
        return None
    b = Bundle(skt_path)
    return b if b.exists() else None


def sketch_key(model_json):
    """A text that is the same for the same drawn geometry (numbers rounded); used to tell whether the sketch changed."""
    def rnd(v):
        if isinstance(v, float):
            return round(v, 4) + 0.0
        if isinstance(v, dict):
            return {k: rnd(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [rnd(x) for x in v]
        return v
    d = json.loads(model_json)
    return json.dumps(rnd({k: d.get(k) for k in ("pts", "lns", "cis", "ars")}), sort_keys=True)


def save(skt_path, tabs, extras=None):
    """tabs = {"beam": tab, "phys": tab, "cfd": tab, "param": tab} (entries may be None).  extras = {entry name: bytes or a file path}
    for the project, the sketches and the other tabs (3D model, 3D FEA ...).  Writes the project file skt_path.  Returns the keys of the
    tabs whose state was saved."""
    path = skt_path
    saved, raws = [], {}
    for key, tab in tabs.items():
        st = tab.export_state() if tab is not None and getattr(tab, "model", None) is not None else None
        if st is None:
            continue
        raw = pickle.dumps(st, protocol=4)
        _loads(raw)                                     # it must be readable again, or do not touch the old file
        raws[key] = raw
        saved.append(key)
    extras = {k: v for k, v in dict(extras or {}).items() if v is not None}
    for name, blob in extras.items():
        if not _safe_name(name):
            raise ValueError(f"bad entry name {name!r}")
        if isinstance(blob, str) and not os.path.isfile(blob):
            raise ValueError(f"the file for {name} is missing: {blob}")
    man = {"magic": MAGIC, "version": VERSION, "saved": time.strftime("%Y-%m-%d %H:%M:%S"),
           "tabs": {k: f"tabs/{k}.pkl" for k in raws}, "extras": sorted(extras)}
    tmp = path + ".tmp"
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            z.writestr("manifest.json", json.dumps(man, indent=1))
            for k, raw in raws.items():
                z.writestr(f"tabs/{k}.pkl", raw)
            for name, blob in extras.items():
                if isinstance(blob, str):                         # a file on disk (big arrays): streamed, not held in memory
                    z.write(blob, name, compress_type=zipfile.ZIP_DEFLATED, compresslevel=3)
                else:
                    z.writestr(name, blob)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    return saved


def load(skt_path):
    """The saved state dict {"beam": state, ...} of the tabs, or None if the file has no zip.  Raises ValueError for an unreadable one."""
    b = open_bundle(skt_path)
    if b is None:
        return None
    try:
        man = b.manifest()
        data = {"magic": MAGIC, "version": VERSION}
        for key, entry in man.get("tabs", {}).items():
            if not entry.startswith("tabs/"):
                continue
            data[key] = _loads(b.read(entry))
    except Exception as ex:
        raise ValueError(f"{os.path.basename(b.path)} could not be read ({type(ex).__name__}: {ex})")
    return data


# --- helpers shared by the tabs
def get_inputs(tab, names):
    from PyQt6.QtWidgets import QAbstractButton, QComboBox, QLineEdit
    out = {}
    for n in names:
        w = getattr(tab, n, None)
        if isinstance(w, QLineEdit):
            out[n] = w.text()
        elif isinstance(w, QComboBox):
            out[n] = w.currentText()
        elif isinstance(w, QAbstractButton):
            out[n] = w.isChecked()
    return out


def set_inputs(tab, values):
    """Sets the widgets quietly (no signals), so loading never triggers a unit conversion or a library lookup."""
    from PyQt6.QtWidgets import QAbstractButton, QComboBox, QLineEdit
    for n, v in values.items():
        w = getattr(tab, n, None)
        if w is None:
            continue
        w.blockSignals(True)
        try:
            if isinstance(w, QLineEdit):
                w.setText(str(v))
            elif isinstance(w, QComboBox):
                i = w.findText(str(v))
                if i >= 0:
                    w.setCurrentIndex(i)
            elif isinstance(w, QAbstractButton):
                w.setChecked(bool(v))
        finally:
            w.blockSignals(False)


# --- unit changes: the same transformation is used when the program's unit system changes and when a saved state is loaded
#     into a program whose unit system differs
def _scale_text(inputs, name, factor):
    if name in inputs and str(inputs[name]).strip():
        try:
            inputs[name] = f"{float(inputs[name]) * factor:.10g}"
        except ValueError:
            pass


def _convert_model(st, old, new, convert):
    import sketcher_core as sc
    m = sc.Model()
    m.from_json(st["model_json"])
    m.unit_system = old
    m.convert_units(new, convert)
    st["model_json"] = m.to_json()


def _sc(d, keys, f):
    for k in keys:
        if k in d and d[k] is not None:
            d[k] = d[k] * f


def scale_probes(probes, lf):
    out = []
    for q in probes or []:
        q = dict(q)
        _sc(q, ("x0", "y0", "x1", "y1", "cx", "cy", "r"), lf)
        out.append(q)
    return out


def _scale_mat(m, sf, lf):
    _sc(m, ("E", "sy", "su"), sf)
    _sc(m, ("t", "nl_disp"), lf)
    if m.get("probes"):
        m["probes"] = scale_probes(m["probes"], lf)
    if m.get("profile"):
        m["profile"] = dict(m["profile"], h=m["profile"]["h"] * lf, c=m["profile"]["c"] * lf)


def _scale_mesh_stats(stats, lf):
    stats = dict(stats)
    _sc(stats, ("edge_min", "edge_max", "alt_min", "h", "h_body", "h_far"), lf)
    _sc(stats, ("area_min", "area_mean", "area_max"), lf * lf)
    if stats.get("bl"):
        stats["bl"] = dict(stats["bl"])
        _sc(stats["bl"], ("h1", "thickness"), lf)
    return stats


def scale_fea_mesh(mesh, lf):
    if mesh is None:
        return None
    m = dict(mesh)
    m["nodes"] = m["nodes"] * lf
    if "stats" in m:
        m["stats"] = _scale_mesh_stats(m["stats"], lf)
    return m


def scale_fea_result(r, lf, sf, ff):
    """The FEA result in the new units.  Every stored number is a fixed multiple of its unit, so this is exact."""
    if r is None:
        return None
    r = dict(r)
    r["u"] = r["u"] * lf
    for k in ("sx", "sy", "txy", "szz", "vm", "s1", "s2", "tmax"):
        if k in r:
            r[k] = r[k] * sf
    if "area" in r:
        r["area"] = r["area"] * lf * lf
    for k in ("f", "reaction_on_body"):
        if k in r:
            r[k] = r[k] * ff
    r["energy"] = r["energy"] * ff * lf
    r["mat"] = dict(r["mat"])
    _scale_mat(r["mat"], sf, lf)
    if r.get("probes"):
        r["probes"] = [dict(q, **({"avg_vm": q["avg_vm"] * sf} if q.get("avg_vm") is not None else {}),
                            **({"max_vm": q["max_vm"] * sf} if q.get("max_vm") is not None else {}), area=q["area"] * lf * lf)
                       for q in r["probes"]]
    if r.get("equilibrium"):
        eq = dict(r["equilibrium"])
        _sc(eq, ("sum_fx", "sum_fy"), ff)
        _sc(eq, ("sum_mz",), ff * lf)
        for k in ("applied", "reactions"):
            if k in eq:
                eq[k] = dict(eq[k])
                _sc(eq[k], ("fx", "fy"), ff)
                _sc(eq[k], ("mz",), ff * lf)
        r["equilibrium"] = eq
    if r.get("mesh") is not None:
        r["mesh"] = scale_fea_mesh(r["mesh"], lf)
    fl = []
    for x in r.get("fasteners", []):
        x = dict(x)
        _sc(x, ("d",), lf)
        _sc(x, ("Rx", "Ry", "axial", "shear"), ff)
        if x.get("per_depth"):
            x["per_depth"] = {k: v * ff / lf for k, v in x["per_depth"].items()}
        fl.append(x)
    if "fasteners" in r:
        r["fasteners"] = fl
    if r.get("refine"):
        rf = dict(r["refine"])
        log = []
        for e in rf.get("log", []):
            e = dict(e)
            _sc(e, ("energy",), ff * lf)
            _sc(e, ("umax",), lf)
            _sc(e, ("vmax",), sf)
            log.append(e)
        rf["log"] = log
        r["refine"] = rf
    return r


def scale_cfd_mesh(mesh, lf):
    m = dict(mesh)
    m["nodes"] = m["nodes"] * lf
    m["box"] = tuple(v * lf for v in m["box"])
    m["body_box"] = tuple(v * lf for v in m["body_box"])
    m["size"] = m["size"] * lf
    m["stats"] = _scale_mesh_stats(m["stats"], lf)
    return m


def scale_cfd_setup(su, lf, lm_new):
    su = dict(su)
    su["lscale"] = lm_new
    _sc(su, ("h_body",), lf)
    eg = {}
    for k, g in (su.get("edge_geoms") or {}).items():
        g = dict(g)
        for kk in ("a", "b", "c"):
            if kk in g:
                g[kk] = (g[kk][0] * lf, g[kk][1] * lf)
        _sc(g, ("r",), lf)
        eg[k] = g
    su["edge_geoms"] = eg
    return su


def scale_cfd_result(r, lf, lm_new):
    r = dict(r)
    r["lscale"] = lm_new
    r["xy_sketch"] = r["xy_sketch"] * lf
    walls = {}
    for k, w in r["walls"].items():
        w = dict(w)
        for kk in ("s_a", "s_b", "L"):
            w[kk] = w[kk] * lf
        walls[k] = w
    r["walls"] = walls
    return r


def convert_fea_state(st, old, new, convert):
    """The FEA tab's state in the new unit system.  The mesh and the result are converted in place (not cleared)."""
    import units
    st = dict(st)
    st["inputs"] = dict(st.get("inputs", {}))
    _convert_model(st, old, new, convert)
    st["inputs"]["unit_combo"] = new
    st["cur_unit"] = new
    if not convert:
        return st
    lf, sf, ff = units.length_factor(old, new), units.stress_factor(old, new), units.force_factor(old, new)
    for n in ("e_E", "e_sy", "e_su"):
        _scale_text(st["inputs"], n, sf)
    for n in ("e_t", "e_h", "e_nld"):
        _scale_text(st["inputs"], n, lf)
    sup = []
    for s_ in st.get("supports", []):
        s_ = dict(s_)
        if s_.get("d") is not None:
            s_["d"] = s_["d"] * lf                      # the head width keeps its physical size; only the unit changes
        sup.append(s_)
    st["supports"] = sup
    loads = []
    for ld in st.get("loads", []):
        ld = dict(ld)
        if ld["kind"] == "force":
            ld["fx"], ld["fy"] = ld["fx"] * ff, ld["fy"] * ff
        elif ld["kind"] == "pressure":
            ld["p"] = ld["p"] * sf
        elif ld["kind"] == "traction":
            ld["tx"], ld["ty"] = ld["tx"] * sf, ld["ty"] * sf
        elif ld["kind"] == "cfd" and ld.get("live"):
            pass                                       # a link to the CFD result carries no numbers: it stays valid
        else:
            continue                                   # a load taken from a CFD result is tied to the old numbers: add it again
        loads.append(ld)
    st["loads"] = loads
    st["probes"] = scale_probes(st.get("probes"), lf)
    if st.get("profile"):
        pr = dict(st["profile"])
        pr["A_w"] = pr["A_w"] * lf
        pr["I_w"] = pr["I_w"] * lf ** 3
        pr["c_top"], pr["c_bottom"] = pr["c_top"] * lf, pr["c_bottom"] * lf
        st["profile"] = pr
    st["mesh"] = scale_fea_mesh(st.get("mesh"), lf)
    st["result"] = scale_fea_result(st.get("result"), lf, sf, ff)
    if st.get("last_mat"):
        lm = dict(st["last_mat"])
        _scale_mat(lm, sf, lf)
        st["last_mat"] = lm
    return st


def convert_beam_state(st, old, new, convert):
    """The 1D FEA tab's state in the new unit system.  No result is stored (the tab solves again after loading), so only the inputs
    change: the sketch copy, the default material, every member's own material and profile, and the loads."""
    import profiles1d
    import units
    st = dict(st)
    st["inputs"] = dict(st.get("inputs", {}))
    _convert_model(st, old, new, convert)
    st["cur_unit"] = new
    if not convert:
        return st
    lf, sf, ff = units.length_factor(old, new), units.stress_factor(old, new), units.force_factor(old, new)
    for n in ("e_E", "e_sy", "e_su"):
        _scale_text(st["inputs"], n, sf)
    mems = []
    for m in st.get("members", []):
        m = dict(m)
        if m.get("mat"):
            mt = dict(m["mat"])
            _sc(mt, ("E", "sy", "su"), sf)
            m["mat"] = mt
        if m.get("profile"):
            m["profile"] = profiles1d.scale(m["profile"], lf)
        _sc(m, ("depth",), lf)
        mems.append(m)
    st["members"] = mems
    loads = []
    for ld in st.get("loads", []):
        ld = dict(ld)
        if ld["kind"] == "force":
            _sc(ld, ("fx", "fy"), ff)
        elif ld["kind"] == "moment":
            _sc(ld, ("mz",), ff * lf)
        elif ld["kind"] == "dist":
            _sc(ld, ("q1", "q2"), ff / lf)
        elif ld["kind"] == "wind":
            _sc(ld, ("V",), units.speed_factor(old, new))
            _sc(ld, ("rho",), units.density_factor(old, new))
        elif ld["kind"] == "snow":
            _sc(ld, ("h",), lf)
            _sc(ld, ("rho",), units.density_factor(old, new))
        loads.append(ld)
    st["loads"] = loads
    return st


def convert_cfd_state(st, old, new, convert):
    """The CFD tab's state in the new unit system.  With a conversion the mesh and the result are converted in place
    (the flow fields are stored in SI; only the sketch-unit geometry and the length scale change).  A relabel changes the
    physical size of the model, so the mesh and the result are cleared then."""
    import units
    st = dict(st)
    st["inputs"] = dict(st.get("inputs", {}))
    _convert_model(st, old, new, convert)
    if convert:
        lf = units.length_factor(old, new)
        for n in ("e_hb", "e_hf", "e_first", "e_bt"):
            _scale_text(st["inputs"], n, lf)
        _scale_text(st["inputs"], "e_speed", units.speed_factor(old, new))
        _scale_text(st["inputs"], "e_rho", units.density_factor(old, new))
        _scale_text(st["inputs"], "e_mu", units.viscosity_factor(old, new))
        st["body_size"] = st.get("body_size", 1.0) * lf
        lm_new = units.get(new)["L_m"]
        if st.get("mesh") is not None:
            st["mesh"] = scale_cfd_mesh(st["mesh"], lf)
        if st.get("setup_used") is not None:
            st["setup_used"] = scale_cfd_setup(st["setup_used"], lf, lm_new)
        if st.get("result") is not None:
            st["result"] = scale_cfd_result(st["result"], lf, lm_new)
        st["res_html"] = None                          # rebuilt from the result in the new units
        return st
    st["mesh"] = None
    st["result"] = None
    st["frames"] = []
    st["setup_used"] = None
    st["res_html"] = ""
    return st
