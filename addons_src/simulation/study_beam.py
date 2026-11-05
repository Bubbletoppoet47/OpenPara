"""
study_beam.py - the parametric-study adapter of the 1D FEA tab (see study_iface.py).

Inputs a study can vary: the default material, every load value (force, moment, line load, wind, snow), the in-plane depth of members that
carry wind or snow, and every dimension of a member's profile.  Outputs: displacement, fibre stress, safety factors, forces, reactions, and the
same per member and per support.  Ported from the Parameterization tab of the earlier program.
"""
import traceback

import beam1d
import profiles1d as pr1
import units
from study_iface import StudyAdapter, StudyCancelled, fmt_num, set_widget, widget_params

BEAM_PARAMS = [("e_E", "Default material: E"), ("e_sy", "Default material: yield strength"), ("e_su", "Default material: ultimate strength")]
BEAM_LOAD_KEYS = {"force": [("fx", "Fx"), ("fy", "Fy")], "moment": [("mz", "Mz")], "dist": [("q1", "q1"), ("q2", "q2")],
                  "wind": [("V", "wind speed"), ("angle", "wind direction (deg)"), ("cp", "Cp"), ("rho", "air density")],
                  "snow": [("h", "snow height"), ("rho", "snow density"), ("shape", "shape factor")]}


class BeamStudy(StudyAdapter):
    key = "beam"
    label = "1D FEA"

    def ready(self):
        t = self.tab
        if getattr(t, "model", None) is None:
            return "Import a sketch in the simulation first."
        if not t.supports:
            return "The simulation has no supports yet."
        return None

    # ------------------------------------------------------------------ inputs
    def params(self):
        t = self.tab
        out = widget_params(t, BEAM_PARAMS, "1D FEA inputs")
        for p in out:
            p["id"] = "beam." + p["id"]
        for i, ld in enumerate(t.loads):
            for key, lab in BEAM_LOAD_KEYS.get(ld["kind"], []):
                out.append({"id": f"beam.load{i}.{key}", "group": "1D FEA load values", "kind": "text", "choices": None, "bload": (i, key),
                            "label": f"{t.cond_name(False, i)}: {lab}", "now": fmt_num(ld[key]) if ld.get(key) is not None else ""})
        wl = {x for ld in t.loads if ld["kind"] in ("wind", "snow") for x in ld["targets"]}
        for mem in t.members:
            if mem.get("depth") is not None or mem["lid"] in wl:
                out.append({"id": f"beam.mem{mem['lid']}.depth", "group": "1D FEA profile dimensions", "kind": "text", "choices": None,
                            "label": f"{mem['name']}: in-plane depth (wind / snow)", "bdim": (mem["lid"], "depth"),
                            "now": "" if mem.get("depth") is None else fmt_num(mem["depth"])})
            prof = mem.get("profile")
            if not prof or prof.get("shape") in ("custom", "imported"):
                continue
            for k, lab in pr1.dim_defs(prof["shape"]):
                out.append({"id": f"beam.mem{mem['lid']}.{k}", "group": "1D FEA profile dimensions", "kind": "text", "choices": None,
                            "label": f"{mem['name']} ({pr1.shape_label(prof['shape'])}): {lab}", "bdim": (mem["lid"], k),
                            "now": fmt_num(prof["dims"][k])})
        return out

    def outputs(self):
        t = self.tab
        u = units.get(t.cur_unit)
        base = [("beam.status", "1D FEA outcome"), ("beam.umax", f"Largest displacement ({u['L']})"),
                ("beam.sigma", f"Largest fibre stress ({u['S']})"), ("beam.fos_y", "Lowest factor of safety, yield"),
                ("beam.fos_u", "Lowest factor of safety, ultimate"), ("beam.N", f"Largest axial force ({u['F']})"),
                ("beam.V", f"Largest shear force ({u['F']})"), ("beam.M", f"Largest bending moment ({u['F']} {u['L']})"),
                ("beam.rx", f"Sum of reactions, x ({u['F']})"), ("beam.ry", f"Sum of reactions, y ({u['F']})"),
                ("beam.euler", "Largest compression / Euler load ratio (information only)"),
                ("beam.resid", "Equilibrium residual (relative)")]
        out = [{"id": k, "group": "1D FEA", "label": lab, "numeric": k != "beam.status"} for k, lab in base]
        for mem in t.members:
            if mem.get("profile"):
                nm, lid = mem["name"], mem["lid"]
                for sfx, lab in (("sigma", f"largest fibre stress ({u['S']})"), ("fos_y", "factor of safety, yield"),
                                 ("M", f"largest bending moment ({u['F']} {u['L']})"), ("N", f"largest axial force ({u['F']})"),
                                 ("umax", f"largest displacement ({u['L']})")):
                    out.append({"id": f"beam.m{lid}.{sfx}", "group": "1D FEA", "label": f"Member '{nm}': {lab}", "numeric": True})
        for i, _sp in enumerate(t.supports):
            for sfx, lab in (("rx", f"reaction x ({u['F']})"), ("ry", f"reaction y ({u['F']})"), ("mz", f"reaction moment ({u['F']} {u['L']})")):
                out.append({"id": f"beam.sup{i}.{sfx}", "group": "1D FEA", "label": f"{t.cond_name(True, i)}: {lab}", "numeric": True})
        return out

    # ------------------------------------------------------------------ a case
    def desc(self, pid):
        if not hasattr(self, "_desc"):
            self._desc = {d["id"]: d for d in self.params()}
        return self._desc.get(pid)

    def prepare(self, values, ctx, state=None):
        spec = {"error": None, "run": None}
        try:
            s = self.scratch(state)
            ov = {"loads": {}, "dims": {}}
            for pid, text in values.items():
                d = self.desc(pid)
                if d is None:
                    raise ValueError(f"The input '{pid}' does not exist in this simulation any more.")
                if d.get("bload") is not None:
                    i, k = d["bload"]
                    ov["loads"].setdefault(i, {})[k] = float(text)
                elif d.get("bdim") is not None:
                    lid, k = d["bdim"]
                    ov["dims"].setdefault(lid, {})[k] = float(text)
                else:
                    set_widget(s, d["attr"], d["kind"], text, d.get("choices"))
            b = s.make_spec(ov)
            sup_targets = [list(x["targets"]) for x in s.supports]
        except (beam1d.BeamError, ValueError) as ex:
            spec["error"] = str(ex)
            return spec
        except Exception:
            spec["error"] = traceback.format_exc()
            return spec

        def run(progress, cancel):
            if cancel():
                raise StudyCancelled()
            progress("solving")
            try:
                res = beam1d.solve(*b["args"])
                return {"status": "ok", "result": res, "sup_targets": sup_targets, "notes": list(b.get("notes", [])),
                        "excluded": list(b.get("excluded", []))}
            except beam1d.BeamError as ex:
                return {"status": "failed", "error": str(ex)}
            except Exception:
                return {"status": "failed", "error": traceback.format_exc()}
        spec["run"] = run
        return spec

    # ------------------------------------------------------------------ results
    def case_outputs(self, case, keys):
        br = case.get("result")
        out = {}
        for key in keys:
            v = None
            try:
                if key == "beam.status":
                    v = "FAILED" if case.get("status") == "failed" else case.get("status", "not run")
                elif br is not None:
                    v = self.one(case, br, key)
            except Exception:
                v = None
            out[key] = v if (v is None or isinstance(v, str)) else float(v)
        return out

    @staticmethod
    def one(case, br, key):
        simple = {"beam.umax": "umax", "beam.sigma": "sigma_max", "beam.fos_y": "fos_y", "beam.fos_u": "fos_u", "beam.N": "N_peak",
                  "beam.V": "V_peak", "beam.M": "M_peak", "beam.euler": "euler_max"}
        if key in simple:
            v = br.get(simple[key])
            return abs(v) if key in ("beam.N", "beam.V", "beam.M") and v is not None else v
        if key == "beam.rx":
            return sum(r[0] for r in br["reactions"].values())
        if key == "beam.ry":
            return sum(r[1] for r in br["reactions"].values())
        if key == "beam.resid":
            return br["equilibrium"]["relative"]
        parts = key.split(".")
        if parts[1].startswith("sup"):
            i = int(parts[1][3:])
            tg = case["sup_targets"][i]
            k = {"rx": 0, "ry": 1, "mz": 2}[parts[2]]
            return sum(br["reactions"][p][k] for p in tg if p in br["reactions"])
        lid = int(parts[1][1:])
        m = next((x for x in br["members"] if x["id"] == lid), None)
        if m is None:
            return None
        return {"sigma": m["sigma_max"], "fos_y": m["fos_y"], "M": abs(m["M_peak"]), "N": abs(m["N_peak"]), "umax": m["umax"]}[parts[2]]

    def show(self, case):
        t = self.tab
        st = case.get("state")
        if st is not None:
            t.win._restoring = True
            try:
                t.import_state(st)
            finally:
                t.win._restoring = False
        t.load_case(case["result"])
