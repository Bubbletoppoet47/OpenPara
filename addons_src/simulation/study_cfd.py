"""
study_cfd.py - the parametric-study adapter of the 2D CFD tab (see study_iface.py).

Inputs a study can vary: the fluid and flow boxes (wind speed and direction, density, viscosity), the domain margins, the mesh sizes, the
turbulence model and its settings, the solver settings, auto-refinement.  Outputs: the forces on the bodies, wall pressure, y+, mass balance,
steps and triangles.  Ported from the Parameterization tab of the earlier program.
"""
import traceback

import physics_cfd as pcfd
import physics_geom as pg
import physics_refine as prefine
from study_iface import StudyAdapter, StudyCancelled, set_widget, widget_params

CFD_PARAMS = [("e_speed", "Wind speed"), ("e_angle", "Wind direction (deg)"), ("e_rho", "Density"), ("e_mu", "Viscosity"),
              ("e_ml", "Domain margin, left (body sizes)"), ("e_mr", "Domain margin, right (body sizes)"),
              ("e_mb", "Domain margin, bottom (body sizes)"), ("e_mt", "Domain margin, top (body sizes)"),
              ("e_hb", "Element size at the body"), ("e_hf", "Element size far away"), ("e_tr", "Growth distance (body sizes)"),
              ("turb", "Turbulence model"), ("e_int", "Turbulence intensity (%)"), ("e_vr", "Eddy viscosity ratio"),
              ("e_yp", "Target y+"), ("e_gr", "Boundary-layer growth ratio"), ("e_first", "First layer height"),
              ("e_bt", "Boundary-layer thickness"), ("e_cfl", "CFL"), ("e_dt", "Time step (s)"), ("e_steps", "Maximum steps"),
              ("cb_until", "Run until converged"), ("e_tol", "Stop when change <"), ("e_ramp", "Gentle start (steps)"),
              ("cb_auto", "Auto-refine the mesh"), ("e_passes", "Max refinement passes"), ("e_maxtris", "Max triangles")]


class CFDStudy(StudyAdapter):
    key = "cfd"
    label = "2D CFD"

    def ready(self):
        t = self.tab
        if getattr(t, "model", None) is None:
            return "Import a sketch or a slice in the simulation first."
        if not t.body_on:
            return "Tick at least one solid body in the simulation first."
        return None

    def params(self):
        out = widget_params(self.tab, CFD_PARAMS, "CFD inputs")
        for p in out:
            p["id"] = "cfd." + p["id"]
        return out

    def outputs(self):
        t = self.tab
        fu = t.force_txt(0.0)[1]
        pu = t.pressure_txt(0.0)[1]
        rows = [("cfd.status", "Did the CFD converge?", False), ("cfd.along", f"Force along the wind ({fu})", True),
                ("cfd.across", f"Force across the wind ({fu})", True), ("cfd.pmax", f"Highest wall pressure ({pu})", True),
                ("cfd.pmin", f"Lowest wall pressure ({pu})", True), ("cfd.yplus", "Highest y+ at the first node", True),
                ("cfd.mass", "Mass balance (net flux / inflow)", True), ("cfd.steps", "Time steps used", True),
                ("cfd.tris", "Triangles (final mesh)", True)]
        return [{"id": k, "group": "CFD", "label": lab, "numeric": num} for k, lab, num in rows]

    def desc(self, pid):
        if not hasattr(self, "_desc"):
            self._desc = {d["id"]: d for d in self.params()}
        return self._desc.get(pid)

    def prepare(self, values, ctx, state=None):
        spec = {"error": None, "run": None}
        try:
            s = self.scratch(state)
            for pid, text in values.items():
                d = self.desc(pid)
                if d is None:
                    raise ValueError(f"The input '{pid}' does not exist in this simulation any more.")
                set_widget(s, d["attr"], d["kind"], text, d.get("choices"))
            setup = s.read_setup(check_mesh=False)
            args = s.read_mesh_inputs(quiet=True)
            if args is None:
                raise pcfd.ModelError(getattr(s, "last_input_problem", "The CFD mesh settings are not valid."))
            m, g, ids, margins, hb, hf, tr, bl = args
            key = (tuple(margins), hb, hf, tr, tuple(sorted(bl.items())) if bl else None, tuple(sorted(ids)), hash(m.to_json()))
            auto = None
            if s.cb_auto.isChecked():
                auto = {"passes": int(float(s.e_passes.text())), "max_tris": int(float(s.e_maxtris.text()))}
                if auto["passes"] < 1 or auto["max_tris"] < 100:
                    raise ValueError("CFD: passes must be at least 1 and the triangle limit at least 100.")
            cache = ctx.setdefault("cache", {})
        except (pcfd.ModelError, pg.GeometryError, ValueError) as ex:
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
                    base = pcfd.mesh_fluid(m, g, ids, margins, hb, hf, tr, None, cancel, bl=bl)
                    cache[key] = base
                st = dict(setup)
                st["on_stall"] = lambda info: "stop"                     # a batch cannot ask: a run that stops improving ends
                last = [None]

                def prog(step, mx, t, du, dp, dt_, sec):
                    if step == 1 or step % 10 == 0:
                        progress(f"step {step}, change {max(du, dp, dt_):.1e}")

                def frame(fr):
                    last[0] = fr
                if auto:
                    out = prefine.cfd_auto(base, st, args, auto["passes"], auto["max_tris"], progress=prog, frame=frame, cancel=cancel)
                    res, mesh = out["result"], out["mesh"]
                    res["refine"] = {"log": out["log"], "reason": out["reason"]}
                    res["all_history"] = out["all_history"]
                else:
                    res = pcfd.solve(base, st, progress=prog, frame=frame, cancel=cancel)
                    mesh = base
                if cancel():
                    raise StudyCancelled()
                st.pop("on_stall", None)
                return {"status": res["status"], "mesh": mesh, "result": res, "frame": last[0], "setup": st}
            except (pg.Cancelled, pcfd.Cancelled):
                raise StudyCancelled()
            except (pcfd.ModelError, pg.GeometryError) as ex:
                return {"status": "failed", "error": str(ex)}
            except StudyCancelled:
                raise
            except Exception:
                return {"status": "failed", "error": traceback.format_exc()}
        spec["run"] = run
        return spec

    def case_outputs(self, case, keys):
        t = self.tab
        cr = case.get("result")
        out = {}
        for key in keys:
            v = None
            try:
                if key == "cfd.status":
                    s = case.get("status", "not run")
                    v = "FAILED" if s == "failed" else "converged" if s == "converged" else "NOT converged (" + s + ")"
                elif cr is not None:
                    if key == "cfd.along":
                        v = t.force_txt(cr["forces"]["along"])[0]
                    elif key == "cfd.across":
                        v = t.force_txt(cr["forces"]["across"])[0]
                    elif key == "cfd.pmax":
                        v = t.pressure_txt(max(float(max(w["p_a"].max(), w["p_b"].max())) for w in cr["walls"].values()))[0]
                    elif key == "cfd.pmin":
                        v = t.pressure_txt(min(float(min(w["p_a"].min(), w["p_b"].min())) for w in cr["walls"].values()))[0]
                    elif key == "cfd.yplus":
                        v = max(w[2] for w in cr["yplus"].values()) if cr.get("yplus") else None
                    elif key == "cfd.mass":
                        v = cr["mass"]["relative"]
                    elif key == "cfd.steps":
                        v = len(cr.get("all_history") or cr["history"])
                    elif key == "cfd.tris":
                        v = len(case["mesh"]["tris"])
            except Exception:
                v = None
            out[key] = v if (v is None or isinstance(v, str)) else float(v)
        return out

    def show(self, case):
        t = self.tab
        st = case.get("state")
        if st is not None:
            t.win._restoring = True
            try:
                t.import_state(st)
            finally:
                t.win._restoring = False
        t.load_case(case["mesh"], case["result"], case.get("frame"), case.get("setup"))
