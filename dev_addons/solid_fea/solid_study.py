"""solid_study.py - the parametric-study adapter of the 3D FEA window (see simulation/study_iface.py).

Inputs: the material, the element size, the value of every load; and (through the Parametric Studies add-on) the dimensions of the part.
A geometry case rebuilds the part, finds the supports and loads again by position and normal, meshes and solves."""
import copy
import traceback

import solid_fem as fem
import solid_geom as sg
import solid_model as sm
from study_iface import StudyAdapter, StudyCancelled, fmt_num

MAT = [("E", "Young's modulus E (MPa)"), ("nu", "Poisson's ratio"), ("rho", "Density (kg/m3)"), ("sy", "Yield strength (MPa)"), ("su", "Ultimate strength (MPa)")]
LOADV = {"force": [("fx", "Fx (N)"), ("fy", "Fy (N)"), ("fz", "Fz (N)")], "point": [("fx", "Fx (N)"), ("fy", "Fy (N)"), ("fz", "Fz (N)")],
         "pressure": [("p", "pressure (MPa)")], "gravity": [("g", "g (m/s2)")]}


class SolidStudy(StudyAdapter):
    key = "sf"
    label = "3D FEA"

    def ready(self):
        return sm.check_ready(self.tab.setup) if self.tab.geom is not None else "Import a part first."

    def params(self):
        t = self.tab
        out = []
        for k, lab in MAT:
            out.append({"id": "sf.mat." + k, "group": "3D FEA inputs", "label": lab, "kind": "text", "choices": None, "now": fmt_num(t.setup["material"][k])})
        out.append({"id": "sf.h", "group": "3D FEA inputs", "label": "Element size (mm, 0 = auto)", "kind": "text", "choices": None, "now": fmt_num(t.setup.get("h") or 0.0)})
        for i, l in enumerate(t.setup["loads"]):
            for k, lab in LOADV.get(l["kind"], []):
                if l["kind"] in ("force", "point"):
                    now = l["f"]["xyz".index(k[1])]
                else:
                    now = l[k]
                out.append({"id": f"sf.load{i}.{k}", "group": "3D FEA load values", "label": f"{sm.name_of('Load', i, l)}: {lab}", "kind": "text",
                            "choices": None, "now": fmt_num(now)})
        return out

    def outputs(self):
        rows = [("sf.status", "3D FEA outcome", False), ("sf.umax", "Largest displacement (mm)", True), ("sf.vm", "Largest von Mises stress (MPa)", True),
                ("sf.s1", "Largest principal stress (MPa)", True), ("sf.s3", "Smallest principal stress (MPa)", True),
                ("sf.fos_y", "Factor of safety, yield (on the largest von Mises)", True), ("sf.fos_u", "Factor of safety, ultimate", True),
                ("sf.energy", "Strain energy (N mm)", True), ("sf.rx", "Reaction x (N)", True), ("sf.ry", "Reaction y (N)", True), ("sf.rz", "Reaction z (N)", True),
                ("sf.mass", "Mass (kg)", True), ("sf.volume", "Volume (mm3)", True), ("sf.tets", "Tetrahedra", True), ("sf.nodes", "Nodes", True)]
        return [{"id": k, "group": "3D FEA", "label": lab, "numeric": n} for k, lab, n in rows]

    def apply(self, setup, values):
        known = {d["id"] for d in self.params()}
        for pid, text in values.items():
            if pid not in known:
                raise ValueError(f"The input '{pid}' does not exist in this simulation any more.")
            try:
                v = float(str(text).replace(",", "."))
            except ValueError:
                raise ValueError(f"'{text}' is not a number ({pid}).")
            if pid.startswith("sf.mat."):
                setup["material"][pid[7:]] = v
            elif pid == "sf.h":
                if v < 0:
                    raise ValueError("The element size cannot be negative.")
                setup["h"] = v
            else:
                head, key = pid.split(".")[1], pid.split(".")[2]
                l = setup["loads"][int(head[4:])]
                if l["kind"] in ("force", "point"):
                    l["f"]["xyz".index(key[1])] = v
                else:
                    l[key] = v

    def geometry_state(self, src, vals):
        """The part after changing its dimensions: src is a fresh copy of the project's part."""
        src.set_values({**self.tab.setup.get("dims", {}), **vals})
        return {"geom": sg.analyze(src.doc.solid)}

    def prepare(self, values, ctx, state=None):
        spec = {"error": None, "run": None}
        try:
            setup = copy.deepcopy(self.tab.setup)
            self.apply(setup, values)
            why = sm.check_ready(setup)
            if why:
                raise ValueError(why)
            g = state["geom"] if state else self.tab.geom
            r = sm.resolve(g, setup)
            cache = ctx.setdefault("cache", {})
        except (fem.FemError, sg.GeomError, ValueError) as ex:
            spec["error"] = str(ex)
            return spec
        except Exception:
            spec["error"] = traceback.format_exc()
            return spec

        def run(progress, cancel):
            try:
                res = sm.run(g, r, cache, cancel, progress)
                return {"status": "ok", "result": res}
            except fem.Cancelled:
                raise StudyCancelled()
            except (fem.FemError, sg.GeomError) as ex:
                return {"status": "failed", "error": str(ex)}
            except Exception:
                return {"status": "failed", "error": traceback.format_exc()}
        spec["run"] = run
        return spec

    def case_outputs(self, case, keys):
        r = case.get("result")
        out = {}
        for k in keys:
            v = None
            try:
                if k == "sf.status":
                    v = "FAILED" if case.get("status") == "failed" else case.get("status", "not run")
                elif r is not None:
                    v = {"sf.umax": r["umax"], "sf.vm": r["vm_max"], "sf.s1": r["s1_max"], "sf.s3": r["s3_min"], "sf.fos_y": r["fos_y"],
                         "sf.fos_u": r["fos_u"], "sf.energy": r["energy"], "sf.rx": r["reaction"][0], "sf.ry": r["reaction"][1],
                         "sf.rz": r["reaction"][2], "sf.mass": r["mass"], "sf.volume": r["volume"], "sf.tets": r["n_tets"],
                         "sf.nodes": r["n_nodes"]}.get(k)
            except Exception:
                v = None
            out[k] = v if (v is None or isinstance(v, str)) else float(v)
        return out

    def show(self, case):
        t = self.tab
        g = (case.get("state") or {}).get("geom")
        if g is not None:
            t.geom = g
            P, T, F = sg.display_mesh(g)
            t.view.set_geometry(P, T, F)
            t.fill_faces()
            t.geom_case = True
        t.result = case["result"]
        t.describe()
        t.show_field()
        t.enable_buttons()
