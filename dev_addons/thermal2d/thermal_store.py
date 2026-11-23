"""thermal_store.py - a saved 2D Thermal tab in another unit system (no Qt).

What a thermal tab stores is SI and absolute: every condition (kelvin, W/m2, ...), the heat generation of the regions, the materials of the regions and
the solved fields.  The unit system of the program (File > Units) therefore decides only
  * the sketch length unit: the sketch copy, the mesh and the result's drawing mesh, the probes, the element size and the thickness are scaled;
  * the family of the numbers in the boxes (metric: degC and W, US: degF and Btu): the boxes in `FAMILY_BOXES` are converted through SI.
A relabel (the numbers stay, the unit name changes) keeps what was typed and changes what it means, so the stored SI values are re-read in the new unit
and the mesh and result, which no longer fit the model, are cleared.
"""
import units
import physics_store as pstore
import thermal_units as tu

KIND = "thermal"
LENGTH_BOXES = ("e_t", "e_h")
# input box -> quantity of thermal_units
FAMILY_BOXES = {"e_k": "k", "e_rho": "rho", "e_cp": "cp", "e_T0": "T", "e_hplate": "h", "e_Tamb": "T", "e_Tsur": "T"}
# stored value of a condition -> quantity
COND_VALUES = {"temp": {"T": "T"}, "flux": {"q": "q"}, "power": {"P": "P"}, "conv": {"h": "h", "Tinf": "T"}, "rad": {"Ts": "T"}}


def _reread(v, q, fo, fn):
    """A stored SI number that is to keep its DISPLAYED value when the unit family changes (a relabel)."""
    return fn.to_si(q, fo.from_si(q, v))


def scale_result(r, lf, lscale_new):
    """The result with its drawing mesh in the new length unit (everything else in it is SI and does not change)."""
    if r is None:
        return None
    r = dict(r)
    if r.get("mesh") is not None:
        r["mesh"] = pstore.scale_fea_mesh(r["mesh"], lf)
    r["lscale"] = lscale_new
    return r


def convert_state(st, old, new, convert):
    st = dict(st)
    st["inputs"] = dict(st.get("inputs", {}))
    pstore._convert_model(st, old, new, convert)
    st["cur_unit"] = new
    fo, fn = tu.family_of(old), tu.family_of(new)
    if convert:
        lf = units.length_factor(old, new)
        for n in LENGTH_BOXES:
            pstore._scale_text(st["inputs"], n, lf)
        if fo.us != fn.us:                                   # the same physical value, written in the other family
            for n, q in FAMILY_BOXES.items():
                txt = str(st["inputs"].get(n, "")).strip()
                if txt:
                    try:
                        st["inputs"][n] = f"{fn.from_si(q, fo.to_si(q, float(txt))):.10g}"
                    except ValueError:
                        pass
        st["mesh"] = pstore.scale_fea_mesh(st.get("mesh"), lf)
        st["result"] = scale_result(st.get("result"), lf, units.get(new)["L_m"])
        st["probes"] = pstore.scale_probes(st.get("probes"), lf)
        return st
    # a relabel: the numbers in the boxes stay; the stored SI values are read again in the new family; the mesh and result do not fit any more
    if fo.us != fn.us:
        for key in ("supports", "loads"):
            out = []
            for it in st.get(key, []):
                it = dict(it)
                for k, q in COND_VALUES.get(it.get("kind"), {}).items():
                    if it.get(k) is not None:
                        it[k] = _reread(it[k], q, fo, fn)
                out.append(it)
            st[key] = out
        st["region_q"] = {f: _reread(v, "qv", fo, fn) for f, v in (st.get("region_q") or {}).items()}
        # (the materials are library values in SI: they keep their physical value)
    st["mesh"] = None
    st["result"] = None
    st["frame"] = 0
    return st


def register():
    pstore.register_converter(KIND, convert_state)
