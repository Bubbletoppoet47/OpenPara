"""
thermal_study.py - the parametric-study adapter of the 2D Thermal tab (see study_iface.py).

Inputs a study can vary: the material, thickness, element size, analysis and flat-face boxes, the value of every condition (temperature, heat flux, heat
flow, convection coefficient and fluid temperature, emissivity and surroundings temperature) and the heat generation of every region.  Numbers are typed in
the tab's units (degC / W / m for metric, degF / Btu / ft for US); what is solved is SI.  Outputs: the temperatures, the largest heat flux, the heat
through every condition, the heat balance, the probe averages.
"""
import copy
import hashlib
import traceback

import numpy as np

import physics_fea as pf
import physics_geom as pg
import thermal_fem as tfem
from study_iface import StudyAdapter, StudyCancelled, fmt_num, set_widget, widget_params

THERMAL_PARAMS = [("e_k", "Conductivity (every region)"), ("e_rho", "Density (every region)"), ("e_cp", "Specific heat (every region)"),
                  ("e_t", "Thickness"), ("e_h", "Element size"),
                  ("order_combo", "Elements (quadratic / linear)"), ("analysis_combo", "Analysis (steady / transient)"),
                  ("e_T0", "Start temperature"), ("e_tend", "End time"), ("time_combo", "Time unit of the end time"), ("e_steps", "Time steps"),
                  ("method_combo", "Time-stepping method"), ("cb_plate", "Heat loss from the flat faces"), ("e_hplate", "Flat faces: convection coefficient"),
                  ("e_Tamb", "Flat faces: fluid temperature"), ("e_eps_plate", "Flat faces: emissivity"), ("e_Tsur", "Flat faces: surroundings temperature")]
# the three material boxes stand for every region in a study (each region also has its own three, below); id -> (key, quantity)
ALL_MATS = {"thermal.e_k": ("k", "k"), "thermal.e_rho": ("rho", "rho"), "thermal.e_cp": ("cp", "cp")}
MAT_LABELS = (("k", "k", "conductivity"), ("rho", "rho", "density"), ("cp", "cp", "specific heat"))
# kind -> [(key stored in the condition, quantity of thermal_units ('eps' is a plain number), label)]
COND_KEYS = {"temp": [("T", "T", "temperature")], "flux": [("q", "q", "heat flux")], "power": [("P", "P", "heat flow")],
             "conv": [("h", "h", "coefficient"), ("Tinf", "T", "fluid temperature")], "rad": [("eps", None, "emissivity"), ("Ts", "T", "surroundings temperature")],
             "ins": []}


class ThermalStudy(StudyAdapter):
    key = "thermal"
    label = "2D Thermal"

    def ready(self):
        t = self.tab
        if getattr(t, "model", None) is None:
            return "Import a sketch or a slice in the simulation first."
        if not (t.supports or t.loads or any(v for v in (t.region_q or {}).values())):
            return "The simulation has no conditions and no heat generation yet."
        return None

    # ------------------------------------------------------------------ inputs
    def params(self):
        t = self.tab
        fam = t.family()
        out = widget_params(t, THERMAL_PARAMS, "Thermal inputs")
        for p in out:
            p["id"] = "thermal." + p["id"]
        for is_sup, items in ((True, t.supports), (False, t.loads)):
            for idx, it in enumerate(items):
                for key, q, lab in COND_KEYS[it["kind"]]:
                    now = it[key] if q is None else fam.from_si(q, it[key])
                    unit = "" if q is None else f" ({fam.unit(q)})"
                    out.append({"id": f"thermal.{'sup' if is_sup else 'load'}{idx}.{key}", "group": "Thermal condition values", "kind": "text", "choices": None,
                                "cond": (is_sup, idx, key, q), "label": f"{t.cond_name(is_sup, idx)} ({it['kind']} on {t.names(it['targets'])}): {lab}{unit}",
                                "now": fmt_num(now)})
        for f in t.geom["faces"] if t.geom is not None else []:
            if f["included"]:
                m = (t.region_mats or {}).get(f["id"])
                for key, q, lab in MAT_LABELS if m else ():
                    out.append({"id": f"thermal.mat{f['id']}.{key}", "group": "Thermal material values", "kind": "text", "choices": None, "mat": (f["id"], key, q),
                                "label": f"Region {f['id'] + 1}: {lab} ({fam.unit(q)})", "now": fmt_num(fam.from_si(q, m[key]))})
                out.append({"id": f"thermal.gen{f['id']}", "group": "Thermal condition values", "kind": "text", "choices": None, "gen": f["id"],
                            "label": f"Region {f['id'] + 1}: heat generation ({fam.unit('qv')})",
                            "now": fmt_num(fam.from_si("qv", (t.region_q or {}).get(f["id"], 0.0)))})
        return out

    def outputs(self):
        t = self.tab
        fam = t.family()
        rows = [("thermal.status", "Thermal outcome", False), ("thermal.Tmax", f"Highest temperature ({fam.temp})", True),
                ("thermal.Tmin", f"Lowest temperature ({fam.temp})", True), ("thermal.Tmean", f"Average temperature ({fam.temp})", True),
                ("thermal.qmax", f"Largest heat flux ({fam.unit('q')})", True), ("thermal.heat_in", f"Heat in ({fam.unit('P')})", True),
                ("thermal.heat_out", f"Heat out ({fam.unit('P')})", True), ("thermal.stored", f"Heat stored ({fam.unit('P')})", True),
                ("thermal.balance", "Heat balance error (fraction of the heat flowing)", True), ("thermal.tris", "Triangles", True),
                ("thermal.newton", "Radiation iterations (Newton)", True)]
        res = [{"id": k, "group": "Thermal", "label": lab, "numeric": num} for k, lab, num in rows]
        for i, c in enumerate(list(t.supports) + list(t.loads)):
            is_sup = i < len(t.supports)
            nm = t.cond_name(is_sup, i if is_sup else i - len(t.supports))
            res.append({"id": f"thermal.flow{i}", "group": "Thermal", "label": f"Heat through '{nm}' ({fam.unit('P')}, positive = into the body)", "numeric": True})
        for i, q in enumerate(t.probes):
            for sfx, lab in (("avg", f"average temperature ({fam.temp})"), ("max", f"highest temperature ({fam.temp})"),
                             ("min", f"lowest temperature ({fam.temp})"), ("q", f"average heat flux ({fam.unit('q')})")):
                res.append({"id": f"thermal.probe{i}.{sfx}", "group": "Thermal", "label": f"Probe '{q['name']}': {lab}", "numeric": True})
        return res

    # ------------------------------------------------------------------ a case
    def prepare(self, values, ctx, state=None):
        spec = {"error": None, "run": None}
        try:
            s = self.scratch(state)
            self.apply(s, values)
            fam = s.family()
            setup = s.read_setup(need_mesh=False)
            conds = copy.deepcopy(setup["conds"])
            region_q = dict(setup["region_q"])
            n_sup = len(s.supports)
            for pid, text in values.items():                # the three boxes first: every region; a region's own value (below) then wins
                if pid in ALL_MATS:
                    key, q = ALL_MATS[pid]
                    for m_ in setup["region_mats"].values():
                        m_[key] = fam.to_si(q, float(text))
            for pid, text in values.items():
                d = self.desc(pid)
                if d is None:
                    continue
                if d.get("mat") is not None:
                    fid, key, q = d["mat"]
                    if fid in setup["region_mats"]:
                        setup["region_mats"][fid][key] = fam.to_si(q, float(text))
                elif d.get("cond") is not None:
                    is_sup, idx, key, q = d["cond"]
                    v = float(text)
                    v = v if q is None else fam.to_si(q, v)
                    conds[idx if is_sup else n_sup + idx][key] = v
                elif d.get("gen") is not None:
                    v = fam.to_si("qv", float(text))
                    if v:
                        region_q[d["gen"]] = v
                    else:
                        region_q.pop(d["gen"], None)
            for c in conds:
                k = c["kind"]
                if (k == "temp" and not c["T"] > 0) or (k == "conv" and (c["h"] < 0 or not c["Tinf"] > 0)) or \
                        (k == "rad" and (not 0 <= c["eps"] <= 1 or not c["Ts"] > 0)):
                    raise pf.ModelError(f"The condition '{c['name']}' has a value that is not possible (a temperature must be above absolute zero, "
                                        "a coefficient cannot be negative, an emissivity is between 0 and 1).")
            setup["conds"], setup["region_q"] = conds, region_q
            h = float(s.e_h.text())
            included = {f["id"] for f in s.geom["faces"] if f["included"]}
            m, g = s.model, s.geom
            probes = [dict(q) for q in s.probes]
            key = (hashlib.md5(m.to_json().encode("utf-8")).hexdigest(), h, tuple(sorted(included)))
            cache = ctx.setdefault("cache", {})
        except (pf.ModelError, pg.GeometryError, ValueError) as ex:
            spec["error"] = str(ex)
            return spec
        except Exception:                                   # noqa: BLE001
            spec["error"] = traceback.format_exc()
            return spec

        def run(progress, cancel):
            try:
                base = cache.get(key)
                if base is None:
                    progress("meshing")
                    base = pg.mesh_faces(m, g, included, h, None, cancel)
                    cache[key] = base
                progress("solving")
                res = tfem.solve(base, setup, None, cancel)
                res["probe_stats"] = tfem.probe_stats(res, probes) if probes else []
                notes = [n for n in res.get("notes") or []]
                return {"status": "ok" if not notes else "ok, with notes", "mesh": base, "result": res, "notes": notes}
            except (pg.Cancelled, pf.Cancelled):
                raise StudyCancelled()
            except (pf.ModelError, pg.GeometryError) as ex:
                return {"status": "failed", "error": str(ex)}
            except Exception:                               # noqa: BLE001
                return {"status": "failed", "error": traceback.format_exc()}
        spec["run"] = run
        return spec

    def desc(self, pid):
        if not hasattr(self, "_desc"):
            self._desc = {d["id"]: d for d in self.params()}
        return self._desc.get(pid)

    def apply(self, s, values):
        """The widget inputs of the values go into the scratch tab (condition values and heat generation are handled by the caller)."""
        for pid, text in values.items():
            d = self.desc(pid)
            if d is None:
                raise ValueError(f"The input '{pid}' does not exist in this simulation any more.")
            if d.get("cond") is not None or d.get("gen") is not None or d.get("mat") is not None:
                continue
            set_widget(s, d["attr"], d["kind"], text, d.get("choices"))
        s.tr_box.setVisible(s.analysis_combo.currentIndex() == 1)
        s.plate_box.setVisible(s.cb_plate.isChecked())

    def mesh_refinement(self):
        return {"sizes": ["thermal.e_h"], "extra": {}, "count": "thermal.tris", "dim": 2,
                "outputs": ["thermal.status", "thermal.Tmax", "thermal.Tmean", "thermal.qmax", "thermal.tris"], "unit": ""}

    # ------------------------------------------------------------------ results
    def case_outputs(self, case, keys):
        fr = case.get("result")
        out = {}
        for key in keys:
            v = None
            try:
                if key == "thermal.status":
                    v = "FAILED" if case.get("status") == "failed" else case.get("status", "not run")
                elif fr is not None:
                    v = self.one(case, fr, key)
            except Exception:                               # noqa: BLE001
                v = None
            out[key] = v if (v is None or isinstance(v, str)) else float(v)
        return out

    def one(self, case, fr, key):
        fam = self.tab.family()
        if key == "thermal.Tmax":
            return fam.from_si("T", fr["Tmax"])
        if key == "thermal.Tmin":
            return fam.from_si("T", fr["Tmin"])
        if key == "thermal.Tmean":
            return fam.from_si("T", fr["Tmean"])
        if key == "thermal.qmax":
            return fam.from_si("q", float(np.max(fr["qmag"])))
        if key == "thermal.heat_in":
            return fam.from_si("P", fr["balance"]["in"])
        if key == "thermal.heat_out":
            return fam.from_si("P", fr["balance"]["out"])
        if key == "thermal.stored":
            return fam.from_si("P", fr["balance"]["stored"])
        if key == "thermal.balance":
            return fr["balance"]["relative_error"]
        if key == "thermal.tris":
            return len(case["mesh"]["tris"])
        if key == "thermal.newton":
            return None if fr.get("newton") is None else fr["newton"]["iterations"]
        if key.startswith("thermal.flow"):
            return fam.from_si("P", fr["flows"][int(key[len("thermal.flow"):])]["Q"])
        if key.startswith("thermal.probe"):
            head, what = key.split(".")[1:3]
            q = (fr.get("probe_stats") or [])[int(head[5:])]
            if q["avg"] is None:
                return None
            if what == "q":
                return fam.from_si("q", q["q_avg"])
            return fam.from_si("T", q[{"avg": "avg", "max": "max", "min": "min"}[what]])
        return None

    def show(self, case):
        t = self.tab
        st = case.get("state")
        if st is not None:                                  # a geometry case: the tab takes that geometry first
            t.win._restoring = True
            try:
                t.import_state(st)
            finally:
                t.win._restoring = False
        t.load_case(case["mesh"], case["result"])
