"""
study_fea.py - the parametric-study adapter of the 2D FEA tab (see study_iface.py).

Inputs a study can vary: the material and analysis boxes, the element size and auto-refinement boxes, the value of every load, the head width of
every bolt / screw.  Outputs: displacement, stresses, reactions, safety factors, probes, fastener forces.  Ported from the Parameterization tab
of the earlier program.
"""
import copy
import hashlib
import traceback

import numpy as np

import physics_fea as pf
import physics_geom as pg
import physics_materials as pmat
import physics_refine as prefine
import units
from study_iface import StudyAdapter, StudyCancelled, fmt_num, set_widget, widget_params

FEA_PARAMS = [("e_E", "Young's modulus E"), ("e_nu", "Poisson's ratio"), ("e_t", "Thickness"),
              ("rb_strain", "Plane strain (off = plane stress)"), ("e_h", "Element size"), ("cb_auto", "Auto-refine the mesh"),
              ("e_passes", "Max refinement passes"), ("e_maxtris", "Max triangles"),
              ("e_sy", "Yield strength"), ("e_su", "Ultimate strength"), ("e_eu", "Plastic strain at ultimate (%)"),
              ("cb_lin", "Linear solver"), ("cb_nl", "Nonlinear solver"), ("e_nld", "Nonlinear trigger: displacement"),
              ("e_nly", "Nonlinear trigger: stress (% of yield)")]
LOAD_KEYS = {"force": [("fx", "Fx"), ("fy", "Fy")], "pressure": [("p", "pressure")], "traction": [("tx", "Tx"), ("ty", "Ty")]}


class FEAStudy(StudyAdapter):
    key = "fea"
    label = "2D FEA"

    def ready(self):
        t = self.tab
        if getattr(t, "model", None) is None:
            return "Import a sketch or a slice in the simulation first."
        if not t.supports or not t.loads:
            return "The simulation has no supports or no loads yet."
        return None

    # ------------------------------------------------------------------ inputs
    def params(self):
        t = self.tab
        out = widget_params(t, FEA_PARAMS, "FEA inputs")
        for p in out:
            p["id"] = "fea." + p["id"]
        for i, ld in enumerate(t.loads):
            for key, lab in LOAD_KEYS.get(ld["kind"], []):
                tg = t.names(ld["targets"]) if ld.get("targets") else ""
                out.append({"id": f"fea.load{i}.{key}", "group": "FEA load values", "kind": "text", "choices": None, "load": (i, key),
                            "label": f"{t.cond_name(False, i)} ({ld['kind']} on {tg}): {lab}", "now": fmt_num(ld.get(key, 0.0))})
        for i, sp_ in enumerate(t.supports):
            if sp_["mode"] in ("bolt", "screw"):
                out.append({"id": f"fea.sup{i}.d", "group": "FEA load values", "kind": "text", "choices": None, "sup": (i, "d"),
                            "label": f"{t.cond_name(True, i)} ({sp_['mode']} on {t.names(sp_['targets'])}): head width",
                            "now": fmt_num(sp_.get("d", 0.0))})
        return out

    def outputs(self):
        t = self.tab
        u = units.get(t.unit_name())
        out = [("fea.status", "FEA outcome"), ("fea.umax", f"Largest displacement ({u['L']})"),
               ("fea.vm", f"Largest von Mises stress ({u['S']})"), ("fea.s1", f"Largest principal stress ({u['S']})"),
               ("fea.s2", f"Smallest principal stress ({u['S']})"), ("fea.energy", f"Strain energy ({u['F']} {u['L']})"),
               ("fea.rx", f"Reaction, x ({u['F']})"), ("fea.ry", f"Reaction, y ({u['F']})"), ("fea.tris", "Triangles (final mesh)"),
               ("fea.pull", f"Largest bolt / screw pull-off ({u['F']}, per slice of depth)"),
               ("fea.fshear", f"Largest bolt / screw shear ({u['F']}, per slice of depth)"),
               ("fea.fos_y", "Factor of safety, yield (marked probe average, else largest von Mises)"),
               ("fea.fos_u", "Factor of safety, ultimate (marked probe average, else largest von Mises)"),
               ("fea.fos_y_peak", "Factor of safety, yield on the largest von Mises"),
               ("fea.fos_u_peak", "Factor of safety, ultimate on the largest von Mises"),
               ("fea.solver", "Solver used (linear / nonlinear)"), ("fea.nl_ok", "Nonlinear solve converged? (yes / no / n/a)"),
               ("fea.peeq", "Largest equivalent plastic strain (%)")]
        res = [{"id": k, "group": "FEA", "label": lab, "numeric": k not in ("fea.status", "fea.solver", "fea.nl_ok")} for k, lab in out]
        for i, q in enumerate(t.probes):
            nm = q["name"]
            for sfx, lab in (("avg", f"average von Mises ({u['S']})"), ("max", f"peak von Mises ({u['S']})"),
                             ("fos_y", "factor of safety, yield (on its average)"), ("fos_u", "factor of safety, ultimate (on its average)")):
                res.append({"id": f"fea.probe{i}.{sfx}", "group": "FEA", "label": f"Probe '{nm}': {lab}", "numeric": True})
        return res

    # ------------------------------------------------------------------ a case
    def prepare(self, values, ctx, state=None):
        spec = {"error": None, "run": None}
        try:
            s = self.scratch(state)
            self.apply(s, values)
            mat = s.read_material()
            h = float(s.e_h.text())
            included = {f["id"] for f in s.geom["faces"] if f["included"]}
            loads = copy.deepcopy(s.loads)
            sups = [dict(x) for x in s.supports]
            for pid, text in values.items():
                d = self.desc(pid)
                if d is not None and d.get("load") is not None:
                    i, k = d["load"]
                    loads[i][k] = float(text)
                elif d is not None and d.get("sup") is not None:
                    i, k = d["sup"]
                    sups[i][k] = float(text)
            if not sups or not loads:
                raise pf.ModelError("The simulation has no supports or no loads.")
            loads = s.resolved_loads(loads)
            unconv = any(l["kind"] == "cfd" and not l.get("converged", True) for l in loads)
            auto = None
            if s.cb_auto.isChecked():
                auto = {"passes": int(float(s.e_passes.text())), "max_tris": int(float(s.e_maxtris.text()))}
                if auto["passes"] < 1 or auto["max_tris"] < 100:
                    raise ValueError("Auto-refine: passes must be at least 1 and the triangle limit at least 100.")
            m, g = s.model, s.geom
            key = (hashlib.md5(m.to_json().encode("utf-8")).hexdigest(), h, tuple(sorted(included)))
            cache = ctx.setdefault("cache", {})
        except (pf.ModelError, pg.GeometryError, ValueError) as ex:
            spec["error"] = str(ex)
            return spec
        except Exception:
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
                if auto:
                    out = prefine.fea_auto(m, g, included, h, base, mat, sups, loads, auto["passes"], auto["max_tris"],
                                           progress=lambda t_, fr=0.0: progress(t_), cancel=cancel)
                    res, mesh = out["result"], out["mesh"]
                    res["refine"] = {"log": out["log"], "reason": out["reason"]}
                else:
                    res = pf.solve(base, mat, sups, loads, None, cancel)
                    mesh = base
                res["cfd_unconverged"] = unconv
                status = "ok" if not unconv else "ok, CFD not converged"
                if res.get("solver") == "nonlinear" and not (res.get("nl") or {}).get("converged", True):
                    status += f", nonlinear NOT converged ({100 * (res['nl'].get('load_fraction') or 0):.0f} % of the load)"
                return {"status": status, "mesh": mesh, "result": res}
            except (pg.Cancelled, pf.Cancelled):
                raise StudyCancelled()
            except (pf.ModelError, pg.GeometryError) as ex:
                return {"status": "failed", "error": str(ex)}
            except Exception:
                return {"status": "failed", "error": traceback.format_exc()}
        spec["run"] = run
        return spec

    def desc(self, pid):
        if not hasattr(self, "_desc"):
            self._desc = {d["id"]: d for d in self.params()}
        return self._desc.get(pid)

    def apply(self, s, values):
        """The widget inputs of the values go into the scratch tab (loads and supports are handled by the caller)."""
        for pid, text in values.items():
            d = self.desc(pid)
            if d is None:
                raise ValueError(f"The input '{pid}' does not exist in this simulation any more.")
            if d.get("load") is not None or d.get("sup") is not None:
                continue
            set_widget(s, d["attr"], d["kind"], text, d.get("choices"))

    # ------------------------------------------------------------------ results
    def case_outputs(self, case, keys):
        fr = case.get("result")
        out = {}
        for key in keys:
            v = None
            try:
                if key == "fea.status":
                    v = "FAILED" if case.get("status") == "failed" else case.get("status", "not run")
                elif fr is not None:
                    v = self.one(case, fr, key)
            except Exception:
                v = None
            out[key] = v if (v is None or isinstance(v, str)) else float(v)
        return out

    @staticmethod
    def one(case, fr, key):
        if key == "fea.umax":
            return np.max(np.hypot(fr["u"][:, 0], fr["u"][:, 1]))
        if key == "fea.vm":
            return np.max(fr["vm"])
        if key == "fea.s1":
            return np.max(fr["s1"])
        if key == "fea.s2":
            return np.min(fr["s2"])
        if key == "fea.energy":
            return fr["energy"]
        if key == "fea.rx":
            return fr["equilibrium"]["reactions"]["fx"]
        if key == "fea.ry":
            return fr["equilibrium"]["reactions"]["fy"]
        if key == "fea.tris":
            return len(case["mesh"]["tris"])
        if key == "fea.pull":
            return max((x["axial"] for x in fr.get("fasteners", []) if x["mode"] in ("bolt", "screw")), default=None)
        if key == "fea.fshear":
            return max((abs(x["shear"]) for x in fr.get("fasteners", []) if x["mode"] in ("bolt", "screw")), default=None)
        if key == "fea.fos_y":
            return fr.get("fos_yield")
        if key == "fea.fos_u":
            return fr.get("fos_ult")
        if key == "fea.fos_y_peak":
            return fr.get("fos_yield_peak")
        if key == "fea.fos_u_peak":
            return fr.get("fos_ult_peak")
        if key == "fea.solver":
            return fr.get("solver", "linear")
        if key == "fea.nl_ok":
            return "n/a" if fr.get("solver") != "nonlinear" else ("yes" if (fr.get("nl") or {}).get("converged", True) else "no")
        if key == "fea.peeq":
            return float(np.max(fr["peeq"])) * 100.0 if fr.get("peeq") is not None else 0.0
        if key.startswith("fea.probe"):
            head, what = key.split(".")[1:3]
            q = fr.get("probes", [])[int(head[5:])]
            mt = fr["mat"]
            if what == "avg":
                return q["avg_vm"]
            if what == "max":
                return q["max_vm"]
            f = "sy" if what == "fos_y" else "su"
            return (mt.get(f) / q["avg_vm"]) if q["avg_vm"] and (mt.get(f) or 0) > 0 else None
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
