"""coupled_members.py - the analysis windows as members of a Coupled Physics solve: 2D Thermal and 3D Thermal (they send a temperature), 2D Static Structural and
3D Static Structural (they take it), and the 2D Fluid Flow window (it exchanges heat with a 2D Thermal analysis and gives its pressure to a 2D Structural analysis).  A member drives the window it wraps through the window's own Solve (the setup is the window's: materials, conditions, mesh settings),
waits for it when it runs on a worker thread, and hands the engine (coupled_engine) what it needs: the temperature field and its mesh, or the points of the stress mesh
to ask the temperature for.  Qt is used only to wait for a window's worker."""
import time

import numpy as np

import coupled_engine as ce

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


def why_not(w):
    """What a 3D window last said when a solve did not give a result: the last line of its error, else its status line."""
    err = (getattr(w, "last_error", "") or "").strip().splitlines()
    if err:
        return err[-1]
    lbl = getattr(w, "status_lbl", None)
    return (lbl.text() if lbl is not None else "") or ""


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
            raise ce.CoupledError(f"{self.label}: " + (why_not(w) or "it could not be started (see the message in its tab)."))
        wait_for(w)
        if w.result is None:
            raise ce.CoupledError(f"{self.label}: " + (why_not(w) or "the solve did not give a result."))
        return w.result

    def temperature_field(self):
        r = self.win.result
        conn = np.asarray(r["conn"])
        return np.asarray(r["nodes"], float), conn[:, :4], np.asarray(r["T"], float), float(r["Tmean"])


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

    def solve(self, temperature_at):
        w = self.win
        if w.geom is None:
            raise ce.CoupledError(f"{self.label}: no part is imported yet.")

        def ask(points, q=None):
            self.last_points = np.asarray(points, float)
            tets = None if q is None or len(q.get("hexes", ())) or len(q.get("pyrs", ())) else q.get("tets")
            self.last_weights = None if tets is None else ce.lumped_weights(points, tets, n=len(points))      # (a mesh with bricks: no average check)
            return temperature_at(points)
        reset(w)
        w.coupled_in = ask
        try:
            if w.run_solve() is False and getattr(w, "job", None) is None:
                raise ce.CoupledError(f"{self.label}: " + (why_not(w) or "it could not be started (see the message in its tab)."))
            wait_for(w)
        finally:
            w.coupled_in = None
        if w.result is None:
            raise ce.CoupledError(f"{self.label}: " + (why_not(w) or "the solve did not give a result."))
        return w.result


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


def wrap(kind, window):
    """The member for a window of kind 'thermal' (2D Thermal), 'thermal3d', 'fea' (2D Static Structural), 'solid' (3D Static Structural) or 'cfd' (2D Fluid Flow)."""
    cls = {"thermal": Thermal2D, "thermal3d": Thermal3D, "fea": Structural2D, "solid": Structural3D, "cfd": Fluid2D}.get(kind)
    if cls is None:
        raise ce.CoupledError(f"A '{kind}' analysis cannot take part in Coupled Physics yet.")
    return cls(window)


def pair(windows):
    """{kind: window} -> {"thermal": member, "structural": member} of ONE dimension; with a 2D Fluid Flow window ("cfd") also {"fluid": member} and at least one of the other two
    (the flow exchanges heat with the thermal analysis and loads the structural one).  Raises CoupledError in words (what is missing, what does not fit)."""
    th = [(k, w) for k, w in windows.items() if k in ("thermal", "thermal3d")]
    st = [(k, w) for k, w in windows.items() if k in ("fea", "solid")]
    fl = [(k, w) for k, w in windows.items() if k == "cfd"]
    if len(th) > 1 or len(st) > 1 or len(fl) > 1:
        raise ce.CoupledError("One Thermal, one Structural and one Fluid Flow analysis can be coupled at a time for now.")
    if fl:
        if not th and not st:
            raise ce.CoupledError("A 2D Fluid Flow analysis is coupled with a Thermal analysis (heat exchange) or a Structural analysis (pressure): wire in a 2D Thermal or a 2D Static "
                                  "Structural analysis next to it.")
        out = {"fluid": wrap(*fl[0])}
        if th:
            out["thermal"] = wrap(*th[0])
        if st:
            out["structural"] = wrap(*st[0])
        for role in ("thermal", "structural"):
            if role in out and out[role].dim != 2:
                raise ce.CoupledError(f"The {out[role].label} analysis cannot be coupled with a 2D fluid flow: Coupled Physics with a flow works in 2D, so wire in the 2D analyses.")
        return out
    if not th or not st:
        need = " and ".join(n for n, got in (("a 2D or 3D Thermal analysis", th), ("a 2D or 3D Static Structural analysis", st)) if not got)
        raise ce.CoupledError(f"Coupled Physics needs both a heat problem and a stress problem: wire in {need}.")
    a, b = wrap(*th[0]), wrap(*st[0])
    if a.dim != b.dim:
        raise ce.CoupledError(f"The thermal analysis is {a.dim}D and the structural analysis is {b.dim}D: wire in two of the same dimension.")
    return {"thermal": a, "structural": b}
