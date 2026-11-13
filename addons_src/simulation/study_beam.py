"""
study_beam.py - the parametric-study adapter of the 1D FEA tab (see study_iface.py).

Inputs a study can vary: the default material, every load value (force, moment, line load, wind, snow), the in-plane depth of members that
carry wind or snow, and every dimension of a member's profile.  A profile drawn as a sketch is varied through the dimensions of its sketch:
  * a profile sketch of the FRAME'S part: its dimensions are among the part's dimensions the study tab lists itself; geometry_state() works the
    profile sketches out again from the changed part, together with the frame;
  * a profile sketch of ANOTHER part (a copy in the project's profiles/): the variables of that part and the dimensions of its profile sketches
    are inputs of this adapter ("bprof"); prepare() changes a fresh copy of the part and reads the sketches again.
Outputs: displacement, fibre stress, safety factors, forces, reactions, and the
same per member and per support.  Ported from the Parameterization tab of the earlier program.
"""
import traceback

import beam1d
import profile_sketch
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
            if not prof or prof.get("shape") in ("custom", "imported", "sketch"):
                continue
            for k, lab in pr1.dim_defs(prof["shape"]):
                out.append({"id": f"beam.mem{mem['lid']}.{k}", "group": "1D FEA profile dimensions", "kind": "text", "choices": None,
                            "label": f"{mem['name']} ({pr1.shape_label(prof['shape'])}): {lab}", "bdim": (mem["lid"], k),
                            "now": fmt_num(prof["dims"][k])})
        out += self.profile_part_params()
        return out

    def profile_part_params(self):
        """The variables and profile-sketch dimensions of the parts copied into the project for their profile sketches."""
        t = self.tab
        src_of = getattr(t.win, "profile_source", None)
        if src_of is None or getattr(t.win, "sim", None) is None:
            return []
        out = []
        for part in sorted({p["part"] for p in t.profs if p["part"] != "main"}):
            sids = {str(p["sid"]) for p in t.profs if p["part"] == part}
            try:
                cands = src_of(part).doc.cfg_candidates()
            except Exception:
                continue
            pname = next(p["part_name"] for p in t.profs if p["part"] == part)
            for key, label, now in cands:
                if not (key.startswith("g:") or (key.startswith("d:") and key.split(":")[1] in sids)):
                    continue
                out.append({"id": f"beam.prof.{part}.{key}", "group": "Profile sketch dimensions (changes the profile)", "kind": "text",
                            "choices": None, "label": f"{pname}: {label}", "now": str(now), "bprof": (part, key)})
        return out

    def profs_changed(self, profs, by_part, ctx, unit):
        """The profile sketches after changing their parts: by_part = {part key: {cfg key: text}}.  Raises ValueError with the reason."""
        t = self.tab
        cache = ctx.setdefault("profile_outlines", {})
        out = []
        for p in profs:
            vals = by_part.get(p["part"])
            if not vals:
                out.append(p)
                continue
            ck = (p["part"], tuple(sorted(vals.items())), unit)
            if ck not in cache:
                src = t.win.profile_source(p["part"], True)
                profile_sketch.check_values(src.doc, vals, [q["sid"] for q in profs if q["part"] == p["part"]])
                src.set_values(vals)
                cache[ck] = src
            try:
                outline, notes, sname = profile_sketch.read(cache[ck].doc, p["sid"], unit)
                pr1.sketch(p["name"], outline)
            except ValueError as ex:
                raise ValueError(f"Profile sketch '{p['name']}': {ex}")
            out.append(dict(p, outline=outline, notes=list(notes), sketch=sname, error=None))
        return out

    def geometry_state(self, src, vals):
        """The state of the tab after changing the dimensions of the frame's part: the frame sketch and the profile sketches of that part."""
        t = self.tab
        profile_sketch.check_values(src.doc, vals, [p["sid"] for p in t.profs if p["part"] == "main"])
        src.set_values(vals)
        sid = getattr(t, "sketch_id", None) or (getattr(getattr(t.win, "sim", None), "meta", None) or {}).get("sid")
        m = src.doc.models.get(sid)
        if m is None:
            raise ValueError("The sketch of the simulation is not in the part any more.")
        st = self.base_state()
        st["model_json"] = m.to_json()
        profs = []
        for p in st.get("profs") or []:
            if p["part"] == "main":
                try:
                    outline, notes, sname = profile_sketch.read(src.doc, p["sid"], t.unit_name())
                    pr1.sketch(p["name"], outline)
                except ValueError as ex:
                    raise ValueError(f"Profile sketch '{p['name']}': {ex}")
                p = dict(p, outline=outline, notes=list(notes), sketch=sname, error=None)
            profs.append(p)
        st["profs"] = profs
        return st

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
        profs = None
        try:
            by_part = {}
            for pid, text in values.items():
                d = self.desc(pid)
                if d is not None and d.get("bprof") is not None:
                    by_part.setdefault(d["bprof"][0], {})[d["bprof"][1]] = text
            bad = self.tab.prof_problems()
            if bad:
                raise ValueError(" ".join(bad) + " Update the profile sketches first.")
            if by_part:                                        # profile sketches of other parts: read again from the changed parts
                state = dict(state if state is not None else self.base_state())
                profs = state["profs"] = self.profs_changed(state.get("profs") or [], by_part, ctx, self.tab.unit_name())
            s = self.scratch(state)
            ov = {"loads": {}, "dims": {}}
            for pid, text in values.items():
                d = self.desc(pid)
                if d is None:
                    raise ValueError(f"The input '{pid}' does not exist in this simulation any more.")
                if d.get("bprof") is not None:
                    continue
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
                case = {"status": "ok", "result": res, "sup_targets": sup_targets, "notes": list(b.get("notes", [])),
                        "excluded": list(b.get("excluded", []))}
                if profs is not None:
                    case["profs"] = profs                      # show() puts the changed profile sketches on the screen with the result
                return case
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
        if case.get("profs") is not None:
            st = dict(st if st is not None else t.export_state(), profs=case["profs"])
        if st is not None:
            t.win._restoring = True
            try:
                t.import_state(st)
            finally:
                t.win._restoring = False
        t.load_case(case["result"])
