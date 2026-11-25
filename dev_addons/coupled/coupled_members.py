"""coupled_members.py - the analysis windows as members of a Coupled Physics solve: 2D Thermal and 3D Thermal (they send a temperature), 2D Static Structural and
3D Static Structural (they take it), and the 2D and 3D Fluid Flow windows (a flow exchanges heat with the Thermal analysis of its dimension and gives its pressure to the Structural one).  A member drives the window it wraps through the window's own Solve (the setup is the window's: materials, conditions, mesh settings),
waits for it when it runs on a worker thread, and hands the engine (coupled_engine) what it needs: the temperature field and its mesh, or the points of the stress mesh
to ask the temperature for.  Qt is used only to wait for a window's worker."""
import re
import time

import numpy as np

import coupled_engine as ce
import coupled_surface as cs

WAIT_LIMIT = 3600.0                                          # seconds a member waits for a solve before it says it did not finish


def wait_for(w):
    """A window that solves on a worker thread (3D) is waited for; one that solves at once (2D, or a 3D window made with threaded=False) is already done."""
    if getattr(w, "job", None) is None:
        return
    from PyQt6.QtWidgets import QApplication
    t0 = time.monotonic()
    while getattr(w, "job", None) is not None:
        QApplication.processEvents()
        time.sleep(0.01)
        if time.monotonic() - t0 > WAIT_LIMIT:
            raise ce.CoupledError("A solve did not finish in time.")
    QApplication.processEvents()


def why_not(w, label=""):
    """What a 3D window last said when a solve did not give a result: the last line of its error (without the name of the exception class, and without `label` twice), else its status line."""
    err = (getattr(w, "last_error", "") or "").strip().splitlines()
    if err:
        text = re.sub(r"^(?:[A-Za-z_][\w]*\.)*[A-Za-z_]\w*(?:Error|Exception|Cancelled): ", "", err[-1].strip())
    else:
        lbl = getattr(w, "status_lbl", None)
        text = (lbl.text() if lbl is not None else "") or ""
    if label and text.startswith(label):
        text = text[len(label):].lstrip(": ")
    return text


def reset(w):
    w.result = None
    w.last_error = ""


class Thermal2D(ce.Member):
    role, dim, label = "thermal", 2, "2D Thermal"

    def __init__(self, tab):
        self.tab = tab
        self._loc = None

    def solve(self):
        t = self.tab
        if getattr(t, "model", None) is None:
            raise ce.CoupledError(f"{self.label}: no sketch is imported yet.")
        if t.mesh is None:
            t.run_mesh()
            if t.mesh is None:
                raise ce.CoupledError(f"{self.label}: the mesh could not be made (see the message in its tab).")
        t.result = None
        t.run_solve()
        if t.result is None:
            raise ce.CoupledError(f"{self.label}: the solve did not give a result (see the message in its tab).")
        self._loc = None
        return t.result

    def temperature_field(self):
        r = self.tab.result
        mesh = r["mesh"]
        return np.asarray(mesh["nodes"], float), np.asarray(mesh["tris"]), np.asarray(r["T"], float), float(r["Tmean"])      # (a transient run: the temperature at its end)

    # --- with a flowing fluid (a CFD window): the edges it touches exchange heat with it
    @property
    def thickness(self):
        """The thickness of the body in metres (what the heat per metre of depth of the fluid is multiplied by)."""
        t = self.tab
        return float(t.num(t.e_t, "The thickness", positive=True)) * float(t.lscale())

    def set_fluid(self, h_at, Tref_at, keys):
        """The edges `keys` exchange heat with the fluid: q = h (T - Tref), h and Tref functions of the points (sketch units) of those edges."""
        self.tab.coupled_fluid = {tuple(k): {"h": h_at, "Tinf": Tref_at} for k in keys}

    def release(self):
        self.tab.coupled_fluid = None

    def wall_temperature_at(self, P):
        """-> (the temperature (K) of the last solve at the points P (n, 2) of the wall, how far the farthest of them lies from the thermal mesh in element sizes)."""
        r = self.tab.result
        if r is None:
            raise ce.CoupledError(f"{self.label}: there is no result to take the wall temperature from.")
        if self._loc is None or self._loc[0] is not r:
            mesh = r["mesh"]
            self._loc = (r, ce.Locator(np.asarray(mesh["nodes"], float), np.asarray(mesh["tris"])))
        loc = self._loc[1]
        vals, info = loc.interpolate(np.asarray(r["T"], float), np.asarray(P, float))
        return vals, float(info["max_gap"]) / max(loc.h, 1e-300)

    def heat_to_fluid(self):
        """The heat (W) that the last solve gave to the fluid through the edges that exchange heat with it."""
        r = self.tab.result
        return -float(sum(f["Q"] for f in r["flows"] if f["kind"] == "fluid"))


class Structural2D(ce.Member):
    role, dim, label = "structural", 2, "2D Static Structural"

    def summary(self):
        return _summary_2d(self.tab)

    def __init__(self, tab):
        self.tab = tab
        self.last_weights = self.last_points = None
        self._shear = False
        self._cfd = None

    def solve(self, temperature_at=None, cfd=None):
        """temperature_at: the temperature of a Thermal analysis (None when there is none); cfd: the fluid pressure ({"info", "edges", "shear"}, None when there is no fluid)."""
        t = self.tab
        if getattr(t, "model", None) is None:
            raise ce.CoupledError(f"{self.label}: no sketch is imported yet.")
        if t.mesh is None:
            t.run_mesh()
            if t.mesh is None:
                raise ce.CoupledError(f"{self.label}: the mesh could not be made (see the message in its tab).")

        def ask(points):
            mesh = t.mesh
            self.last_points = np.asarray(points, float)
            self.last_weights = ce.lumped_weights(mesh["nodes"], mesh["tris"], n=len(points))
            return temperature_at(points)
        t.result = None
        t.coupled_pressure_edges = ()
        t.coupled_in = ask if temperature_at is not None else None
        t.coupled_cfd = cfd
        self._shear = bool(cfd and cfd.get("shear"))
        self._cfd = cfd
        try:
            t.run_solve()
        finally:
            t.coupled_in = None
            t.coupled_cfd = None
        if t.result is None:
            if cfd is not None and not t.coupled_pressure_edges and temperature_at is None:
                raise ce.CoupledError(f"{self.label} got no fluid pressure: every edge the fluid touches is held by a support here, or is not an edge of this sketch, so nothing "
                                      "loads it. Check that the two analyses use the same sketch and release the edge the fluid pushes on.")
            raise ce.CoupledError(f"{self.label}: the solve did not give a result (see the message in its tab).")
        return t.result

    def displacement_at(self, P):
        """-> (the displacement (n, 2) of the last solve at the points P (n, 2) of the body as drawn, in the units of the sketch; how far the farthest of them lies from the stress mesh
        in element sizes)."""
        t = self.tab
        r = t.result
        if r is None:
            raise ce.CoupledError(f"{self.label}: there is no result to take the displacement from.")
        if getattr(self, "_dloc", None) is None or self._dloc[0] is not r:
            mesh = r["mesh"]
            self._dloc = (r, ce.Locator(np.asarray(mesh["nodes"], float), np.asarray(mesh["tris"])))
        loc = self._dloc[1]
        u = np.asarray(r["u"], float)
        out, gap = np.zeros((len(P), 2)), 0.0
        for j in (0, 1):
            out[:, j], info = loc.interpolate(u[:, j], np.asarray(P, float))
            gap = max(gap, float(info["max_gap"]))
        return out, gap / max(loc.h, 1e-300)

    def pressure_report(self):
        """What the last solve took from the fluid: {"edges": the edges that got the pressure, "force": (fx, fy) N per metre of depth, "same_geometry": bool, "left_out": [edges]}."""
        import physics_cfd as pcfd
        import physics_materials as pm
        import units
        t = self.tab
        edges = [tuple(k) for k in t.coupled_pressure_edges]
        tally = (t.result or {}).get("cfd_tally") or {}
        F = np.zeros(2)
        for k in edges:
            v = tally.get(k)
            if v is not None:
                F += np.asarray(v["p"], float) + (np.asarray(v["s"], float) if self._shear else 0.0)
        F = F / float(pm.from_mpa(1e-6, t.stress_unit())) * float(units.get(t.unit_name())["L_m"])          # (stress unit x length unit) per unit thickness -> N per metre
        mine = {e["src"]: pcfd.edge_geometry(t.model, e) for e in t.geom["edges"]}
        same = True
        geoms = ((self._cfd or {}).get("info") or {}).get("edge_geoms") or {}
        if geoms:
            vals = [abs(v) for g in list(mine.values()) + list(geoms.values()) for v in _flat(g)]
            tol = 1e-6 * max(vals + [1.0])
            same = all(k in geoms and pcfd.same_edge(mine[k], geoms[k], tol) for k in edges if k in mine)
        return {"edges": edges, "force": (float(F[0]), float(F[1])), "same_geometry": same}


def _flat(g):
    """The numbers of an edge description (pcfd.edge_geometry) in one list."""
    out = []
    for v in g.values():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out.append(float(v))
        elif isinstance(v, (tuple, list)):
            out += [float(x) for x in v if isinstance(x, (int, float))]
    return out


def _summary_2d(tab):
    """The largest displacement and von Mises stress of a 2D stress result, in the unit system of the sketch: {"umax", "L", "vm_max", "S"}."""
    import units
    r = tab.result
    uu = units.get(tab.unit_name())
    return {"umax": float(np.max(np.hypot(r["u"][:, 0], r["u"][:, 1]))), "L": uu["L"], "vm_max": float(np.max(r["vm"])), "S": uu["S"]}


def _summary_3d(win):
    """The same for a 3D stress result (the solver works in mm and MPa; shown in the program's units)."""
    import solid_base
    import solid_tab
    r, D = win.result, solid_base.UD()
    return {"umax": float(solid_base.l_out(r["umax"])), "L": D["L"], "vm_max": float(solid_tab.s_out(r["vm_max"])), "S": D["S"]}


class Thermal3D(ce.Member):
    role, dim, label = "thermal", 3, "3D Thermal"

    def __init__(self, win):
        self.win = win

    def solve(self):
        w = self.win
        if w.geom is None:
            raise ce.CoupledError(f"{self.label}: no part is imported yet.")
        reset(w)
        if w.run_solve() is False and getattr(w, "job", None) is None:
            raise ce.CoupledError(f"{self.label}: " + (why_not(w, self.label) or "it could not be started (see the message in its tab)."))
        wait_for(w)
        if w.result is None:
            raise ce.CoupledError(f"{self.label}: " + (why_not(w, self.label) or "the solve did not give a result."))
        return w.result

    def temperature_field(self):
        r = self.win.result
        conn = np.asarray(r["conn"])
        return np.asarray(r["nodes"], float), conn[:, :4], np.asarray(r["T"], float), float(r["Tmean"])

    # --- with a flowing fluid (a 3D Fluid Flow window): the faces it touches exchange heat with it
    def set_fluid(self, h_at, Tref_at, fids):
        """The faces `fids` exchange heat with the fluid: q = h (T - Tref), h and Tref functions of the points (n, 3) in mm of those faces."""
        self.win.coupled_fluid = {"fids": [int(f) for f in fids], "h_at": h_at, "Tinf_at": Tref_at}
        self._wall = None

    def release(self):
        self.win.coupled_fluid = None

    _wall = None

    def wall_temperature_at(self, P):
        """-> (the temperature (K) of the last solve at the points P (n, 3) mm near the exchange faces, how far the farthest of them lies from those faces in element sizes)."""
        w = self.win
        r = w.result
        fl = w.coupled_fluid
        if r is None or fl is None:
            raise ce.CoupledError(f"{self.label}: there is no result to take the wall temperature from.")
        if self._wall is None or self._wall[0] is not r:
            tris = cs.faces_triangles(r["mesh"], fl["fids"])
            if not len(tris):
                raise ce.CoupledError(f"{self.label}: its mesh has no elements on the faces that exchange heat with the fluid (is the face numbering the same as in the fluid analysis?).")
            self._wall = (r, cs.SurfaceLocator(np.asarray(r["nodes"], float), tris))
        loc = self._wall[1]
        vals, info = loc.interpolate(np.asarray(r["T"], float), np.asarray(P, float))
        return vals, float(info["max_gap"]) / max(loc.h, 1e-300)

    def heat_to_fluid(self):
        """The heat (W) that the last solve gave to the fluid through the faces that exchange heat with it."""
        import thermal3d_model as tm
        r = self.win.result
        return -float(sum(f["Q"] for f in r["flows"] if f["name"] == tm.FLUID_NAME))

    def exchange_faces(self):
        """The face records ({"id", "center", "area"}) of the part as this analysis numbers them."""
        return list(self.win.geom["faces"])


class Structural3D(ce.Member):
    role, dim, label = "structural", 3, "3D Static Structural"

    def summary(self):
        return _summary_3d(self.win)

    def far_end(self, axis=0):
        """How far the end of the body that is farthest along `axis` has moved along it (mm; the mean over the nodes of that end): what a free bar's growth is."""
        r = self.win.result
        n, u = np.asarray(r["nodes"], float), np.asarray(r["u"], float)
        x = n[:, axis]
        end = np.abs(x - x.max()) < 1e-6 * max(1.0, float(np.ptp(x)))
        return float(u[end, axis].mean())

    def __init__(self, win):
        self.win = win
        self.last_weights = self.last_points = None

    def solve(self, temperature_at=None, cfd=None):
        """temperature_at: the temperature of a Thermal analysis (None when there is none); cfd: the fluid pressure ({"info": Fluid3D.pressure_info()["info"], "edges", "shear"}, None
        when there is no fluid)."""
        w = self.win
        if w.geom is None:
            raise ce.CoupledError(f"{self.label}: no part is imported yet.")

        def ask(points, q=None):
            self.last_points = np.asarray(points, float)
            tets = None if q is None or len(q.get("hexes", ())) or len(q.get("pyrs", ())) else q.get("tets")
            self.last_weights = None if tets is None else ce.lumped_weights(points, tets, n=len(points))      # (a mesh with bricks: no average check)
            return temperature_at(points)
        reset(w)
        self._cfd = cfd
        self._fluid_seen = {}
        w.coupled_in = ask if temperature_at is not None else None
        w.coupled_fluid = self._fluid_loader(cfd) if cfd is not None else None
        try:
            if w.run_solve() is False and getattr(w, "job", None) is None:
                raise ce.CoupledError(f"{self.label}: " + (why_not(w, self.label) or "it could not be started (see the message in its tab)."))
            wait_for(w)
        finally:
            w.coupled_in = None
            w.coupled_fluid = None
        if w.result is None:
            raise ce.CoupledError(f"{self.label}: " + (why_not(w, self.label) or "the solve did not give a result."))
        return w.result

    # --- the pressure of a flow
    _cfd = None
    _fluid_seen = None
    _dloc = None

    def wetted_faces(self):
        """The faces of the part that a flow pushes on: all of them but those a support holds."""
        import solid_model as sm
        g, s = self.win.geom, self.win.setup
        held = set()
        for i, sup in enumerate(s.get("supports") or []):
            held |= {int(f) for f in sm._fids(g, sup["faces"], sm.name_of("Support", i, sup))}
        return [int(f["id"]) for f in g["faces"] if int(f["id"]) not in held and not f.get("interface")]

    def _fluid_loader(self, cfd):
        """The function the window calls when its mesh is made: (the nodes of the mesh (n, 3) mm, the mesh) -> {"fids": the faces to load, "p": the pressure (MPa) at every node}."""
        info = cfd["info"]
        loc = cs.SurfaceLocator(info["points"], info["tris"])
        pa = np.asarray(info["p"], float)

        def load(nodes, q):
            fids = [f for f in self.wetted_faces() if f in (q.get("faces") or {})]
            if not fids:
                raise ce.CoupledError(f"{self.label} got no fluid pressure: every face of the part is held by a support here, or the mesh has no elements on the faces the fluid touches. "
                                      "Release the faces the fluid pushes on.")
            tris = np.vstack([np.asarray(q["faces"][f], np.int64) for f in fids])
            on = np.unique(tris)
            t, wts, dist = loc.locate(np.asarray(nodes, float)[on])
            p = np.einsum("nk,nk->n", wts, pa[loc.T[t]])
            pn = np.zeros(len(nodes))
            pn[on] = p * 1e-6                                                          # Pa -> MPa
            P = np.asarray(nodes, float)
            h = float(np.median(np.linalg.norm(P[tris[:, 1]] - P[tris[:, 0]], axis=1)))
            self._fluid_seen = {"fids": fids, "points": int(len(on)), "max_gap": float(dist.max()), "h": h}
            return {"fids": fids, "p": pn}
        return load

    def pressure_report(self):
        """What the last solve took from the fluid: {"edges": the faces that got the pressure, "force": (fx, fy, fz) N, "same_geometry": bool, "differs": [faces], "gap": element sizes,
        "points": n}."""
        r = self.win.result or {}
        fl = r.get("fluid")
        seen = self._fluid_seen or {}
        fids = [int(f) for f in (fl["faces"] if fl else [])]
        info = ((self._cfd or {}).get("info") or {})
        same, bad = (True, [])
        if info.get("faces") is not None:
            same, bad = cs.same_faces(self.win.geom["faces"], info["faces"], fids)
        F = fl["force"] if fl else [0.0, 0.0, 0.0]
        return {"edges": fids, "force": (float(F[0]), float(F[1]), float(F[2])), "same_geometry": same, "differs": bad,
                "gap": float(seen.get("max_gap", 0.0)) / max(float(seen.get("h", 1.0)), 1e-300), "points": int(seen.get("points", 0))}

    def displacement_at(self, P):
        """-> (the displacement (n, 3) mm of the last solve at the points P (n, 3) mm of the surface of the part as drawn, how far the farthest of them lies from the surface of the stress
        mesh in element sizes)."""
        r = self.win.result
        if r is None:
            raise ce.CoupledError(f"{self.label}: there is no result to take the displacement from.")
        if self._dloc is None or self._dloc[0] is not r:
            surf = r.get("surface") or {}
            if not surf:
                raise ce.CoupledError(f"{self.label}: its result has no surface to take the displacement from.")
            self._dloc = (r, cs.SurfaceLocator(np.asarray(r["nodes"], float), np.vstack([cs.split_triangles(t) for t in surf.values()])))
        loc = self._dloc[1]
        out, info = loc.interpolate(np.asarray(r["u"], float), np.asarray(P, float))
        return out, float(info["max_gap"]) / max(loc.h, 1e-300)


class Fluid2D(ce.Member):
    """The 2D Fluid Flow window.  The flow is solved ONCE (the window's own solver, on its worker, waited for); the temperature of the fluid is then solved for the wall
    temperatures the solid gives, as often as the heat exchange loop asks (coupled_fluid.py); the pressure of the settled flow is what the stress analysis is loaded with."""
    role, dim, label = "fluid", 2, "2D Fluid Flow"

    def __init__(self, tab):
        self.tab = tab
        self._attached = False
        self._iso = None
        self._bp = None                                                                    # the points of the outline that a structure can move (boundary_points)
        self._shape = None
        self._shapes = None
        self._moved = False

    # --- the flow
    def solve_flow(self):
        t = self.tab
        if getattr(t, "model", None) is None:
            raise ce.CoupledError(f"{self.label}: no sketch is imported yet.")
        moved = self._shape is not None
        if moved:
            t.run_mesh(shape=self._shape)                                                  # the body as the structure moved it
            if t.mesh is None or not t.mesh.get("deformed"):
                raise ce.CoupledError(f"{self.label}: the mesh of the body as the structure moved it could not be made (see the message in its tab): the outline may have folded over "
                                      "itself, which means the deformation is too large for this method.")
        elif t.mesh is None or t.mesh.get("deformed"):                                     # (a mesh a coupled solve left in the window follows a moved body: mesh the sketch as drawn)
            t.run_mesh()
            if t.mesh is None:
                raise ce.CoupledError(f"{self.label}: the mesh could not be made (see the message in its tab).")
        t.result = None
        self._attached = False
        self._iso = None
        t.coupled_flow_only = True
        t.deformed_shapes = self._shapes if moved else None
        try:
            t.run_solve()
            self._wait()
        finally:
            t.coupled_flow_only = False
            t.deformed_shapes = None
        if t.result is None:
            raise ce.CoupledError(f"{self.label}: the solve did not give a result (see the message in its tab).")
        self._moved = moved
        if moved:
            self._attached = True                                                          # (the window shows the flow round the moved body when the solve is over)
        return {"status": t.result["status"], "steps": t.result.get("steps")}

    # --- the structure moves the flow
    def check_movable(self):
        """Raises CoupledError, in words, when the body cannot be moved in this window."""
        t = self.tab
        if t.cb_auto.isChecked():
            raise ce.CoupledError(f"{self.label}: automatic refinement is on. A body that a structure moves is meshed again at every pass with the sizes of the window: switch off "
                                  "'Refine automatically' in the fluid window.")
        if not t.body_on:
            raise ce.CoupledError(f"{self.label}: no body is switched on.")
        self.boundary_points()

    def boundary_points(self):
        """The points of the outline of the bodies that are on, as drawn: {"P": (M, 2) sketch units, "edges": {edge index: (first row, one past the last row)}} - the places where the
        displacement of the structure is asked for (about every two element sizes along each edge)."""
        import physics_cfd as pcfd
        t = self.tab
        if self._bp is not None and self._bp["key"] == (id(t.model), tuple(sorted(t.body_on)), t.e_hb.text()):
            return self._bp
        faces = [f for f in t.geom["faces"] if f["id"] in t.body_on and f["depth"] == 0]
        hb = float(t.num(t.e_hb, "The element size at the body"))
        edges = t.geom["edges"]
        used = sorted({k for loop in pcfd.body_loops(t.geom, faces) for k, _ in loop})
        rows, spans, S = [], {}, {}
        n0 = 0
        for k in used:
            e = edges[k]
            if e["kind"] == "ln":
                a, b = t.model.pts[e["a"]], t.model.pts[e["b"]]
                length = float(np.hypot(b[0] - a[0], b[1] - a[1]))
            elif e["kind"] == "ar":
                a0, a1, r = pcfd.pg.arc_angles(t.model, e)
                length = abs(a1 - a0) * r
            else:
                length = 2.0 * np.pi * float(e["r"])
            n = int(min(120, max(6, np.ceil(length / (2.0 * hb)) + 1)))
            pts, s = pcfd.sample_edge(t.model, e, n)
            rows.append(pts)
            S[k] = s
            spans[k] = (n0, n0 + len(pts))
            n0 += len(pts)
        self._bp = {"P": np.vstack(rows), "edges": spans, "s": S, "used": used, "key": (id(t.model), tuple(sorted(t.body_on)), t.e_hb.text()),
                    "size": float(t.body_size)}
        return self._bp

    def length_scale(self):
        """How big the body is (sketch units): what a displacement is compared with."""
        return float(self.boundary_points()["size"])

    def set_shape(self, D):
        """The next flow is solved round the body moved by D (M, 2) at the points of boundary_points() (sketch units); None: the body as drawn."""
        import physics_cfd as pcfd
        if D is None:
            self._shape = self._shapes = None
            return
        bp = self.boundary_points()
        t = self.tab
        D = np.array(D, float)
        corner = {}
        for k in bp["used"]:                                                               # an end that two edges share is moved once
            e = t.geom["edges"][k]
            if e["kind"] in ("ln", "ar"):
                i0, i1 = bp["edges"][k]
                corner.setdefault(e["a"], []).append(i0)
                corner.setdefault(e["b"], []).append(i1 - 1)
        for rows_ in corner.values():
            D[rows_] = D[rows_].mean(axis=0)
        shape, shapes = {}, {}
        for k in bp["used"]:
            i0, i1 = bp["edges"][k]
            pts = bp["P"][i0:i1] + D[i0:i1]
            shape[k] = pts
            e = t.geom["edges"][k]
            shapes[e["src"]] = pcfd.poly_geometry(pts, bp["s"][k], closed=e["kind"] == "ci")
        self._shape, self._shapes = {"edges": shape}, shapes

    def mesh_summary(self):
        s = self.tab.mesh["stats"]
        return {"triangles": int(s["n_tris"]), "angle_min": float(s["angle_min"]), "aspect_max": float(s["aspect_max"]), "moved": bool(self.tab.mesh.get("deformed"))}

    def _wait(self):
        """The window solves on a worker: wait for it, keeping the application alive, and stop it when the Coupled Physics solve is cancelled."""
        from PyQt6.QtWidgets import QApplication
        t = self.tab
        t0 = time.monotonic()
        stopped = False
        while getattr(t, "worker", None) is not None:
            QApplication.processEvents()
            time.sleep(0.01)
            if not stopped and self.cancel is not None and self.cancel():
                t.stop_solve()
                stopped = True
            if time.monotonic() - t0 > WAIT_LIMIT:
                raise ce.CoupledError("The flow solve did not finish in time.")
        QApplication.processEvents()
        if stopped:
            raise ce.Cancelled()

    def flow_summary(self):
        r = self.tab.result
        return {"status": r["status"], "steps": r.get("steps"), "t": r.get("t"), "tol": r.get("tol"), "triangles": int(len(self.tab.mesh["tris"]))}

    # --- the heat
    @property
    def T_in(self):
        return float(self._heat_base()["T_in"])

    def coupled_keys(self):
        return self.tab.coupled_keys()

    def _heat_base(self):
        """The window's heat inputs (SI) with the walls of the thermal analysis left out."""
        import physics_cfd as pcfd
        t = self.tab
        if not t.cb_heat.isChecked():
            raise ce.CoupledError(f"{self.label}: heat transfer is switched off. Tick 'Include heat transfer' in the CFD window and choose 'Wall of the thermal analysis' for the "
                                  "edges where the fluid touches the solid.")
        try:
            return t.read_heat(allow_coupled=True)
        except pcfd.ModelError as ex:
            raise ce.CoupledError(f"{self.label}: {ex}")

    def h_iso(self):
        import physics_cfd as pcfd
        import physics_cfd_heat as pheat
        t = self.tab
        base = self._heat_base()
        keys = self.coupled_keys()
        try:
            hv, _r = pheat.heat_transfer_coefficient(t.mesh, t.result, dict(base, walls={k: None for k in keys}), 1.0)
            prof = pheat.WallProfile(t.mesh, keys, hv)
        except pcfd.ModelError as ex:
            raise ce.CoupledError(f"{self.label}: {ex}")
        self._iso = hv
        return hv, prof

    def profile(self, values):
        import physics_cfd_heat as pheat
        return pheat.WallProfile(self.tab.mesh, list(values), values)

    def solve_temperature(self, Tw_at):
        import physics_cfd as pcfd
        import physics_cfd_heat as pheat
        t = self.tab
        base = self._heat_base()
        walls = dict(base["walls"])
        for k in self.coupled_keys():
            walls[k] = {"kind": "temp", "T": Tw_at}
        try:
            hres = pheat.solve_temperature(t.mesh, t.result, dict(base, walls=walls), cancel=self.cancel)
        except pcfd.Cancelled:
            raise ce.Cancelled()
        except pcfd.ModelError as ex:
            raise ce.CoupledError(f"{self.label}: {ex}")
        pheat.attach(t.result, hres)
        self._attached = True
        return hres

    def release(self):
        """Shows the temperature of the last pass in the window (the data is attached to its result)."""
        t = self.tab
        self._shape = self._shapes = None
        t.deformed_shapes = None
        if self._attached and t.result is not None:
            try:
                t.show_result(t.result)
            except Exception:                                                              # noqa: BLE001 - the window repaints itself; the numbers are in the result
                pass
        self._attached = False

    # --- the pressure
    def pressure_info(self):
        t = self.tab
        info = t.transfer_info()
        if info is None:
            raise ce.CoupledError(f"{self.label}: there is no flow result to take the pressure from.")
        return {"info": info, "edges": sorted(tuple(k) for k in t.result["walls"])}

    def pressure_force(self, edges, shear=False):
        """The force of the fluid on the given edges, N per metre of depth: ((fx, fy), the sum of the sizes of the forces of the wall segments)."""
        r = self.tab.result
        F, S = np.zeros(2), 0.0
        for k in edges:
            tb = r["walls"].get(tuple(k))
            if tb is None:
                continue
            Lm = np.asarray(tb["L"], float) * float(r["lscale"])
            fp = (Lm * 0.5 * (np.asarray(tb["p_a"], float) + np.asarray(tb["p_b"], float)))[:, None] * np.asarray(tb["nf"], float)
            F += fp.sum(axis=0)
            S += float(np.hypot(fp[:, 0], fp[:, 1]).sum())
            if shear:
                fv = Lm[:, None] * 0.5 * (np.asarray(tb["tv_a"], float) + np.asarray(tb["tv_b"], float))
                F += fv.sum(axis=0)
                S += float(np.hypot(fv[:, 0], fv[:, 1]).sum())
        return (float(F[0]), float(F[1])), S


class Fluid3D(ce.Member):
    """The 3D Fluid Flow window.  The flow is solved ONCE (the window's own solver, on its worker, waited for); the temperature of the fluid is then solved for the wall temperatures
    the solid gives, as often as the heat exchange loop asks (coupled_fluid3d.py); the pressure of the settled flow is what the stress analysis is loaded with.  A structure can move
    the flow: the air mesh follows the part (cfd3d_morph) and the flow is solved again on the same tetrahedra."""
    role, dim, label = "fluid", 3, "3D Fluid Flow"

    def __init__(self, win):
        self.win = win
        self._res = None                                  # the result of the last solve_flow (its temperature is the one of the last heat solve)
        self._heat = None
        self._D = None                                    # the displacement of the part's nodes the next flow is solved with (None: as drawn)
        self._bp = None
        self._wall = None
        self._ref = None                                  # the nodes of the air mesh as drawn, when the last flow was solved on a moved mesh (None: the flow's own nodes are the reference)
        self._resolved = None
        self._shrink = 1.0

    # --- what the window says
    def _run_spec(self):
        import cfd3d_model as cm
        w = self.win
        if w.geom is None:
            raise ce.CoupledError(f"{self.label}: no part is imported yet.")
        why = w.ready()                                   # (reads what is typed in the window into its setup, as its own Solve does, and says what is missing)
        if why:
            raise ce.CoupledError(f"{self.label}: {why}")
        key = (id(w.geom), json_key(w.setup))
        if self._resolved is None or self._resolved[0] != key:
            try:
                self._resolved = (key, cm.resolve(w.geom, w.setup))
            except Exception as ex:                       # noqa: BLE001 - a face that is gone, a setup that is not ready: in words
                raise ce.CoupledError(f"{self.label}: {ex}")
        return self._resolved[1]

    def coupled_keys(self):
        import cfd3d_model as cm
        return cm.exch_fids(self._run_spec())

    @property
    def T_in(self):
        r = self._run_spec()
        if not r["heat"]:
            raise ce.CoupledError(f"{self.label}: heat transfer is switched off. Tick 'Include the temperature of the fluid' in the 3D Fluid Flow window and add the condition "
                                  "'Wall of the thermal analysis' for the faces where the fluid touches the solid.")
        return float(r["T_in"])

    # --- the flow
    def solve_flow(self):
        w = self.win
        self._run_spec()
        D = self._D
        reset(w)
        w.coupled_nodes = None if D is None else self._mover(D)
        self._res = self._heat = self._wall = None
        try:
            if w.run_solve() is False and getattr(w, "job", None) is None:
                raise ce.CoupledError(f"{self.label}: " + (why_not(w, self.label) or "it could not be started (see the message in its tab)."))
            self._wait()
        finally:
            w.coupled_nodes = None
        if w.result is None:
            raise ce.CoupledError(f"{self.label}: " + (why_not(w, self.label) or "the solve did not give a result."))
        self._res = w.result
        self._ref = None if D is None else np.asarray(self.boundary_points()["q"]["nodes"], float)       # (the mesh as drawn: where the material points of the part are)
        return {"status": w.result["status"], "steps": w.result.get("steps")}

    def _wait(self):
        """The window solves on a worker: wait for it, keeping the application alive, and stop it when the Coupled Physics solve is cancelled."""
        from PyQt6.QtWidgets import QApplication
        w = self.win
        t0 = time.monotonic()
        stopped = False
        while getattr(w, "job", None) is not None:
            QApplication.processEvents()
            time.sleep(0.01)
            if not stopped and self.cancel is not None and self.cancel():
                w.cancel()
                stopped = True
            if time.monotonic() - t0 > WAIT_LIMIT:
                raise ce.CoupledError("The flow solve did not finish in time.")
        QApplication.processEvents()
        if stopped:
            raise ce.Cancelled()

    def flow_summary(self):
        r = self._res
        return {"status": r["status"], "steps": r.get("steps"), "t": r.get("t"), "tol": r.get("tol"), "cells": int(len(r["mesh"]["tets"])), "nodes": int(len(r["mesh"]["nodes"]))}

    def mesh_summary(self):
        r = self._res
        return {"cells": int(len(r["mesh"]["tets"])), "moved": self._D is not None, "shrink": self._shrink}

    # --- the heat
    def _reference(self, nodes):
        """Where the wall nodes `nodes` are in the part AS DRAWN (mm).  When a structure moved the flow, the fluid's wall nodes are the displaced material points of the part: the other
        analyses (the solid, the stress analysis) know the part as drawn, so a field is handed over by the place of the material point and not by where the fluid has it now."""
        q = self._res["mesh"]
        ref = self._ref if self._ref is not None and len(self._ref) == len(q["nodes"]) else np.asarray(q["nodes"], float)
        return np.asarray(ref, float)[nodes]

    def wall_surface(self):
        """The wall of the exchange faces in the flow mesh: {"points" (n, 3) mm (where the material points of the wall are in the part as drawn), "tris" (nt, 3) rows of points,
        "nodes" (n,) numbers in the mesh, "area" (n,) m2 (of the wall as the flow has it)}."""
        import cfd3d_model as cm
        if self._wall is not None and self._wall[0] is self._res:
            return self._wall[1]
        q = self._res["mesh"]
        fids = self.coupled_keys()
        tris = cm.wall_triangles(q, fids)
        if not len(tris):
            raise ce.CoupledError(f"{self.label}: the faces of the exchange have no mesh in the flow: they are not faces of the part.")
        nodes, inv = np.unique(tris.ravel(), return_inverse=True)
        surf = {"points": self._reference(nodes), "tris": inv.reshape(-1, 3), "nodes": nodes, "area": cm.node_areas(q["nodes"], tris, len(q["nodes"]))[nodes]}
        self._wall = (self._res, surf)
        return surf

    def solve_temperature(self, Tw_at):
        """The temperature of the fluid with the walls of the exchange held at Tw_at(points (n, 3) mm) -> K: {"T", "q" (W/m2 into the fluid), "area", "Q" (W)} at wall_surface()'s points."""
        import cfd3d_flow as cf
        import cfd3d_model as cm
        res = self._res
        if res is None:
            raise ce.CoupledError(f"{self.label}: the flow has not been solved.")
        self.T_in                                          # (refuses a window without heat)
        fids = self.coupled_keys()
        surf = self.wall_surface()
        try:
            out, wall = cm.solve_wall_heat(res, fids, Tw_at, cancel=self.cancel, x_ref=self._ref)          # (the solid knows the part as drawn: it is asked for the material points)
        except cf.FlowError as ex:
            raise ce.CoupledError(f"{self.label}: {ex}")
        if len(wall["nodes"]) != len(surf["nodes"]) or not np.array_equal(wall["nodes"], surf["nodes"]):
            raise ce.CoupledError(f"{self.label}: the wall nodes of the heat solve differ from the wall of the exchange (an internal check).")
        self._heat = out
        return wall

    def heat_summary(self):
        res = self._heat
        if res is None:
            raise ce.CoupledError(f"{self.label}: the temperature has not been solved.")
        f = res["run"]["fluid"]
        T, fixed = np.asarray(res["T"], float), np.asarray(res["heat"]["fixed"], bool)
        lo, hi = float(T[fixed].min()), float(T[fixed].max())                              # the temperatures that were given (inlet, walls): the fluid cannot be outside them
        tmin, tmax = float(res["T_range"][0]), float(res["T_range"][1])
        return {"Tmin": tmin, "Tmax": tmax, "balance": {"relative": float(res["energy"]["mismatch"])}, "notes": [], "Pr": float(f["mu"]) * float(f["cp"]) / float(f["k"]),
                "overshoot": max(lo - tmin, tmax - hi, 0.0)}

    def release(self):
        """Shows the temperature of the last pass in the window (the data is attached to its result)."""
        import cfd3d_model as cm
        w = self.win
        self._D = None
        w.coupled_nodes = None
        res = self._heat
        if res is not None and w.result is not None and res.get("mesh") is w.result.get("mesh") and getattr(w, "geom", None) is not None:
            try:
                res["summary"] = cm.summarise(w.geom, res["run"], res["mesh"], res)
                w.result = res
                w.describe()
                w.show_field()
                w.colour()
            except Exception:                                                              # noqa: BLE001 - the window repaints itself; the numbers are in the result
                pass

    # --- the pressure
    def pressure_info(self):
        import cfd3d_model as cm
        res = self._res
        if res is None:
            raise ce.CoupledError(f"{self.label}: there is no flow result to take the pressure from.")
        fids = sorted(nm for nm in res["walls"] if isinstance(nm, int))
        wp = cm.wall_pressure(res, fids)
        wp["points"] = self._reference(wp["nodes"])                                        # (the stress analysis loads the part as drawn)
        faces = [{"id": int(f["id"]), "center": list(f["center"]), "area": float(f["area"])} for f in self.win.geom["faces"]]
        return {"info": {"points": wp["points"], "tris": wp["tris"], "p": wp["p"], "faces": faces, "fids": fids}, "edges": fids}

    def pressure_force(self, edges, shear=False):
        """The force (N) of the fluid on the faces `edges`: ((fx, fy, fz), the sum of the sizes of the forces of the wall triangles).  Friction is not in it."""
        import cfd3d_model as cm
        if shear:
            raise ce.CoupledError(f"{self.label}: the friction of the flow cannot be handed to the stress analysis in 3D yet: only the pressure.")
        F, S = cm.pressure_force(self._res, [int(e) for e in edges])
        return (float(F[0]), float(F[1]), float(F[2])), S

    # --- the structure moves the flow
    def check_movable(self):
        """Raises CoupledError, in words, when the part cannot be moved in this window."""
        self.boundary_points()

    def boundary_points(self):
        """The nodes of the part's walls in the air mesh as drawn: {"P": (M, 3) mm, "nodes": (M,) numbers in the mesh, "size": mm} - the places where the displacement of the structure is asked for."""
        import cfd3d_model as cm
        w = self.win
        r = self._run_spec()
        try:
            q = cm.get_mesh(w.geom, r, w.cache)
        except Exception as ex:                          # noqa: BLE001 - the mesh could not be made: in words
            raise ce.CoupledError(f"{self.label}: the mesh could not be made ({ex}).")
        if self._bp is None or self._bp["q"] is not q:
            nodes = cm.part_nodes(q)
            self._bp = {"q": q, "nodes": nodes, "P": np.asarray(q["nodes"], float)[nodes], "size": float(cm.part_size(w.geom))}
        return self._bp

    def length_scale(self):
        return float(self.boundary_points()["size"])

    def set_shape(self, D):
        """The next flow is solved round the part moved by D (M, 3) mm at the points of boundary_points(); None: the part as drawn."""
        self._D = None if D is None else np.array(D, float)

    def _mover(self, D):
        import cfd3d_model as cm
        import cfd3d_morph as mo

        def nodes(q):
            new = cm.moved_nodes(q, D)
            self._shrink = mo.shrink(q["nodes"], new, q["tets"])
            return new
        return nodes


def json_key(setup):
    import json
    return json.dumps(setup, sort_keys=True, default=str)


def wrap(kind, window):
    """The member for a window of kind 'thermal' (2D Thermal), 'thermal3d', 'fea' (2D Static Structural), 'solid' (3D Static Structural), 'cfd' (2D Fluid Flow) or 'fluid3d' (3D Fluid Flow)."""
    cls = {"thermal": Thermal2D, "thermal3d": Thermal3D, "fea": Structural2D, "solid": Structural3D, "cfd": Fluid2D, "fluid3d": Fluid3D}.get(kind)
    if cls is None:
        raise ce.CoupledError(f"A '{kind}' analysis cannot take part in Coupled Physics yet.")
    return cls(window)


def pair(windows):
    """{kind: window} -> {"thermal": member, "structural": member} of ONE dimension; with a Fluid Flow window ("cfd": 2D, "fluid3d": 3D) also {"fluid": member} and at least one of the
    other two of its dimension (the flow exchanges heat with the thermal analysis and loads the structural one).  Raises CoupledError in words (what is missing, what does not fit)."""
    th = [(k, w) for k, w in windows.items() if k in ("thermal", "thermal3d")]
    st = [(k, w) for k, w in windows.items() if k in ("fea", "solid")]
    fl = [(k, w) for k, w in windows.items() if k in ("cfd", "fluid3d")]
    if len(th) > 1 or len(st) > 1 or len(fl) > 1:
        raise ce.CoupledError("One Thermal, one Structural and one Fluid Flow analysis can be coupled at a time for now.")
    if fl:
        dim = 3 if fl[0][0] == "fluid3d" else 2
        if not th and not st:
            raise ce.CoupledError(f"A {dim}D Fluid Flow analysis is coupled with a Thermal analysis (heat exchange) or a Structural analysis (pressure): wire in a {dim}D Thermal or a "
                                  f"{dim}D Static Structural analysis next to it.")
        out = {"fluid": wrap(*fl[0])}
        if th:
            out["thermal"] = wrap(*th[0])
        if st:
            out["structural"] = wrap(*st[0])
        for role in ("thermal", "structural"):
            if role in out and out[role].dim != dim:
                raise ce.CoupledError(f"The {out[role].label} analysis cannot be coupled with a {dim}D fluid flow: wire in the {dim}D analyses (a flow and the analyses it is coupled with "
                                      "work in the same dimension).")
        return out
    if not th or not st:
        need = " and ".join(n for n, got in (("a 2D or 3D Thermal analysis", th), ("a 2D or 3D Static Structural analysis", st)) if not got)
        raise ce.CoupledError(f"Coupled Physics needs both a heat problem and a stress problem: wire in {need}.")
    a, b = wrap(*th[0]), wrap(*st[0])
    if a.dim != b.dim:
        raise ce.CoupledError(f"The thermal analysis is {a.dim}D and the structural analysis is {b.dim}D: wire in two of the same dimension.")
    return {"thermal": a, "structural": b}
