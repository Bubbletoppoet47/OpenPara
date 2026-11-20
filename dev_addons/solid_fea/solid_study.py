"""solid_study.py - the parametric-study adapter of the 3D FEA window (see simulation/study_iface.py).

Inputs: the material, the element size, the value of every load; and (through the Parametric Studies add-on) the dimensions of the part.
A geometry case rebuilds the part, finds the supports and loads again by position and normal, meshes and solves."""
import copy
import traceback

import solid_adapt as sad
import solid_fem as fem
import solid_geom as sg
import solid_model as sm
from study_iface import StudyAdapter, StudyCancelled, fmt_num, parse_bool

MAT = [("E", "Young's modulus E (MPa)"), ("nu", "Poisson's ratio"), ("rho", "Density (kg/m3)"), ("sy", "Yield strength (MPa)"), ("su", "Ultimate strength (MPa)")]
LOADV = {"force": [("fx", "Fx (N)"), ("fy", "Fy (N)"), ("fz", "Fz (N)")], "point": [("fx", "Fx (N)"), ("fy", "Fy (N)"), ("fz", "Fz (N)")],
         "pressure": [("p", "pressure (MPa)")], "gravity": [("g", "g (m/s2)")]}


class SolidStudy(StudyAdapter):
    key = "sf"
    label = "3D FEA"

    def ready(self):
        return sm.check_ready(self.tab.setup, self.tab.geom) if self.tab.geom is not None else "Import a part first."

    def params(self):
        t = self.tab
        out = []
        for k, lab in MAT:
            out.append({"id": "sf.mat." + k, "group": "3D FEA inputs", "label": lab, "kind": "text", "choices": None, "now": fmt_num(t.setup["material"][k])})
        out.append({"id": "sf.h", "group": "3D FEA inputs", "label": "Element size (mm, 0 = auto)", "kind": "text", "choices": None, "now": fmt_num(t.setup.get("h") or 0.0)})
        ad = sad.options(t.setup)
        crits = [name for name, _u in sad.CRITERIA.values()]
        out += [{"id": "sf.ad.on", "group": "3D FEA adaptive mesh", "label": "Adaptive mesh (single part or bonded parts, tetrahedra)", "kind": "bool", "choices": None,
                 "now": "yes" if ad["on"] else "no"},
                {"id": "sf.ad.crit", "group": "3D FEA adaptive mesh", "label": "Adaptive mesh: criterion", "kind": "choice", "choices": crits,
                 "now": sad.CRITERIA[ad["crit"]][0]},
                {"id": "sf.ad.tol", "group": "3D FEA adaptive mesh", "label": "Adaptive mesh: tolerance (%)", "kind": "text", "choices": None, "now": fmt_num(ad["tol"])},
                {"id": "sf.ad.loops", "group": "3D FEA adaptive mesh", "label": "Adaptive mesh: maximum loops", "kind": "text", "choices": None, "now": str(ad["loops"])}]
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
                ("sf.mass", "Mass (kg)", True), ("sf.volume", "Volume (mm3)", True), ("sf.tets", "Elements", True), ("sf.nodes", "Nodes", True),
                ("sf.adapt", "Adaptive mesh outcome", False), ("sf.converged", "Adaptive mesh converged (1 = yes, 0 = no)", True),
                ("sf.loops", "Adaptive mesh loops used", True), ("sf.change", "Adaptive mesh: last change of the criterion (%)", True),
                ("sf.err", "Adaptive mesh: estimated error (%)", True)]
        return [{"id": k, "group": "3D FEA", "label": lab, "numeric": n} for k, lab, n in rows]

    def mesh_refinement(self):
        return {"sizes": ["sf.h"], "extra": {}, "count": "sf.tets", "dim": 3, "outputs": ["sf.status", "sf.umax", "sf.vm", "sf.energy", "sf.tets", "sf.nodes"],
                "unit": "mm"}

    def set_live(self, pid, text):
        """The element size goes into the window's box in the program's units (the study works in mm)."""
        if pid != "sf.h":
            raise ValueError(f"The input '{pid}' cannot be set from here.")
        import sys
        mod = sys.modules[type(self.tab).__module__]
        self.tab.set_size(format(mod.l_out(float(text)), ".8g"))
        self.tab.inputs_changed()

    def apply(self, setup, values):
        known = {d["id"] for d in self.params()}
        for pid, text in values.items():
            if pid not in known:
                raise ValueError(f"The input '{pid}' does not exist in this simulation any more.")
            if pid.startswith("sf.ad."):
                ad = setup["adapt"] = sad.complete(setup.get("adapt"))
                if pid == "sf.ad.on":
                    ad["on"] = parse_bool(text)
                elif pid == "sf.ad.crit":
                    key = next((k for k, (name, _u) in sad.CRITERIA.items() if name == str(text)), None)
                    if key is None:
                        raise ValueError(f"'{text}' is not one of: " + ", ".join(n for n, _u in sad.CRITERIA.values()))
                    ad["crit"] = key
                else:
                    try:
                        v = float(str(text).replace(",", "."))
                    except ValueError:
                        raise ValueError(f"'{text}' is not a number ({pid}).")
                    if pid == "sf.ad.tol":
                        ad["tol"] = v
                    else:
                        ad["loops"] = int(round(v))
                continue
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
        return {"geom": sg.analyze(src.doc.solid, self.tab.setup.get("splits"))}

    def prepare(self, values, ctx, state=None):
        spec = {"error": None, "run": None}
        try:
            setup = copy.deepcopy(self.tab.setup)
            self.apply(setup, values)
            g = state["geom"] if state else self.tab.geom
            why = sm.check_ready(setup, g)
            if why:
                raise ValueError(why)
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
                ad = (r or {}).get("adapt")
                if k == "sf.adapt":
                    v = None if r is None else ("off" if not ad else ("converged" if ad["converged"] else "not converged"))
                elif k.startswith("sf.") and k[3:] in ("converged", "loops", "change", "err"):
                    v = None if not ad else {"converged": 1.0 if ad["converged"] else 0.0, "loops": ad["loops"], "change": ad["change"], "err": ad["err"]}[k[3:]]
                elif k == "sf.status":
                    v = "FAILED" if case.get("status") == "failed" else case.get("status", "not run")
                elif r is not None:
                    v = {"sf.umax": r["umax"], "sf.vm": r["vm_max"], "sf.s1": r["s1_max"], "sf.s3": r["s3_min"], "sf.fos_y": r["fos_y"],
                         "sf.fos_u": r["fos_u"], "sf.energy": r["energy"], "sf.rx": r["reaction"][0], "sf.ry": r["reaction"][1],
                         "sf.rz": r["reaction"][2], "sf.mass": r["mass"], "sf.volume": r["volume"], "sf.tets": r.get("n_elements", r["n_tets"]),
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
