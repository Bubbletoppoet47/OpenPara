"""
measure_targets.py

Measure how your four printed ArUco squares sit on the wall, from one ordinary
phone photo (JPG/PNG). You mark the corners of each black square by hand, tell
the tool the real edge length of the squares (measure one with a ruler), and it
works out the distances between the squares - correcting for the camera angle.

How it gets real-world lengths from a photo
-------------------------------------------
Everything lies on one flat wall, so image and wall are related by a
perspective transform (a homography). A square of known edge length whose four
corners you've marked pins that transform down exactly. If you tick several
squares as "reference", they are all fitted together (least squares), which
averages out corner-placement error and is noticeably more accurate than using
one square - so tick all four unless one looks bad.

Workflow
--------
  1. Open image...        (file browser)
  2. Type the square edge length (measure a printed square with a ruler) and
     pick in or cm.
  3. For each ID: press "Place", then click its corners in this order:
         top-left, top-right, bottom-right, bottom-left
     "Top" means the side where the TOP arrow printed on the page points.
     Drag any corner handle afterwards to fine-tune. Zoom in first!
  4. Tick the lines you want measured (top-left corner to top-left corner).
  5. Calculate - review lengths (tick in and/or cm). Shows fit quality.
  6. Save - writes target_layout.json (and an annotated PNG) next to the image.

Mouse / keys
------------
  wheel or + / -    zoom (around the cursor)        F   fit to window
  left-drag         move a corner handle (or pan if you grab empty space)
  right/middle-drag pan          arrow keys  pan          Esc  cancel placing

Needs: numpy, pillow, scipy (scipy optional, only for multi-square fit), opencv-python
    pip install numpy pillow scipy opencv-python
"""
import json
import math
import os
import sys

import numpy as np

MM_PER_IN = 25.4
PAIRS = [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)]
CORNER_NAMES = ["top-left", "top-right", "bottom-right", "bottom-left"]
ID_COLORS = ["#ff5050", "#40c040", "#4090ff", "#ffb000"]


# ---------------------------------------------------------------------------
# Geometry (no GUI - unit-testable)
# ---------------------------------------------------------------------------


def apply_h(H, pts):
    pts = np.asarray(pts, float).reshape(-1, 2)
    p = np.hstack([pts, np.ones((len(pts), 1))]) @ H.T
    return p[:, :2] / p[:, 2:3]


def square_corners(s):
    return np.array([[0, 0], [s, 0], [s, s], [0, s]], float)


def rigid_fit(src, dst):
    """Rotation+translation mapping src -> dst (2D Procrustes, no scale)."""
    cs, cd = src.mean(0), dst.mean(0)
    U, _, Vt = np.linalg.svd((src - cs).T @ (dst - cd))
    R = Vt.T @ U.T
    if np.linalg.det(R) < 0:
        Vt[-1] *= -1
        R = Vt.T @ U.T
    return R, cd - R @ cs


def fit_wall_transform(ref_corners_px, s_mm):
    """
    ref_corners_px: {id: (4,2) image corners TL,TR,BR,BL} for the reference squares.
    Returns dict with:
      G       wall(mm) -> image(px) homography
      Ginv    image -> wall
      frame_id  first reference id (its top-left is the wall origin, its top edge is +x)
      rms_px  reprojection error over reference corners
    """
    import cv2
    ids = sorted(ref_corners_px)
    if not ids:
        raise ValueError("no reference squares selected")
    q = square_corners(s_mm)
    c0 = np.asarray(ref_corners_px[ids[0]], float)
    G0 = cv2.getPerspectiveTransform(q.astype(np.float32), c0.astype(np.float32))
    G0 = G0 / G0[2, 2]
    if len(ids) == 1:
        G = G0
        poses = {ids[0]: (0.0, 0.0, 0.0)}
    else:
        try:
            from scipy.optimize import least_squares
        except ImportError:
            print("[warn] scipy not installed - using only the first reference square. "
                  "pip install scipy for the multi-square fit.")
            return fit_wall_transform({ids[0]: ref_corners_px[ids[0]]}, s_mm)
        Ginv0 = np.linalg.inv(G0)
        p0 = []
        for k in ids[1:]:
            w = apply_h(Ginv0, ref_corners_px[k])
            R, t = rigid_fit(q, w)
            p0 += [t[0], t[1], math.atan2(R[1, 0], R[0, 0])]

        def unpack(x):
            H = np.append(x[:8], 1.0).reshape(3, 3)
            return H, x[8:]

        def resid(x):
            H, p = unpack(x)
            out = []
            for n, k in enumerate(ids):
                if n == 0:
                    w = q
                else:
                    tx, ty, th = p[3 * (n - 1): 3 * n]
                    c, s_ = math.cos(th), math.sin(th)
                    w = q @ np.array([[c, s_], [-s_, c]]) + [tx, ty]
                out.append((apply_h(H, w) - np.asarray(ref_corners_px[k], float)).ravel())
            return np.concatenate(out)

        x0 = np.concatenate([G0.ravel()[:8], p0])
        sol = least_squares(resid, x0, x_scale="jac", method="lm")
        G, p = unpack(sol.x)
        poses = {ids[0]: (0.0, 0.0, 0.0)}
        for n, k in enumerate(ids[1:]):
            poses[k] = tuple(p[3 * n: 3 * n + 3])
    r = []
    for k in ids:
        tx, ty, th = poses[k]
        c, s_ = math.cos(th), math.sin(th)
        w = q @ np.array([[c, s_], [-s_, c]]) + [tx, ty]
        r.append((apply_h(G, w) - np.asarray(ref_corners_px[k], float)).ravel())
    rms = float(np.sqrt(np.mean(np.concatenate(r) ** 2)))
    return dict(G=G, Ginv=np.linalg.inv(G), frame_id=ids[0], rms_px=rms, poses=poses)


def measure(corners_px, ref_ids, s_mm, pairs):
    """Full calculation. corners_px: {id: (4,2)} for every placed square."""
    fit = fit_wall_transform({k: corners_px[k] for k in ref_ids}, s_mm)
    wall = {k: apply_h(fit["Ginv"], c) for k, c in corners_px.items()}
    sides = {}
    for k, w in wall.items():
        sides[k] = [float(np.linalg.norm(w[(i + 1) % 4] - w[i])) for i in range(4)]
    dists = {}
    for a, b in pairs:
        if a in wall and b in wall:
            dists[(a, b)] = float(np.linalg.norm(wall[a][0] - wall[b][0]))
    rot = {}
    for k, w in wall.items():
        e = w[1] - w[0]
        rot[k] = math.degrees(math.atan2(e[1], e[0]))
    return dict(fit=fit, wall=wall, sides=sides, dists=dists, rot_deg=rot)


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------


def run_gui(image_path=None, mainloop=True):
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    from PIL import Image, ImageDraw, ImageOps, ImageTk

    Image.MAX_IMAGE_PIXELS = None

    class App:
        def __init__(self, root):
            self.root = root
            root.title("Measure ArUco targets from a photo")
            root.geometry("1400x860")
            self.img = None
            self.small = None
            self.small_f = 1.0
            self.path = None
            self.z = 1.0                     # screen px per image px
            self.ox = self.oy = 0.0          # image coords at canvas top-left
            self.pts = {i: [] for i in range(4)}   # image px, TL,TR,BR,BL
            self.placing = None              # (id, n_done)
            self.drag = None                 # ("pt", id, idx) | ("pan", x, y, ox, oy)
            self.photo = None
            self.calc = None
            self._build()
            root.bind("<plus>", lambda e: self.zoom_by(1.25))
            root.bind("<equal>", lambda e: self.zoom_by(1.25))
            root.bind("<KP_Add>", lambda e: self.zoom_by(1.25))
            root.bind("<minus>", lambda e: self.zoom_by(0.8))
            root.bind("<KP_Subtract>", lambda e: self.zoom_by(0.8))
            root.bind("<underscore>", lambda e: self.zoom_by(0.8))
            root.bind("<f>", lambda e: self.fit())
            root.bind("<F>", lambda e: self.fit())
            root.bind("<Escape>", lambda e: self.cancel_place())
            for key, dx, dy in (("<Left>", -60, 0), ("<Right>", 60, 0), ("<Up>", 0, -60), ("<Down>", 0, 60)):
                root.bind(key, lambda e, dx=dx, dy=dy: self.pan_px(dx, dy))
            if image_path:
                root.after(100, lambda: self.load(image_path))

        # ---- layout ----
        def _build(self):
            root = self.root
            side = ttk.Frame(root, padding=8)
            side.pack(side="right", fill="y")
            self.canvas = tk.Canvas(root, bg="#202020", highlightthickness=0, cursor="arrow")
            self.canvas.pack(side="left", fill="both", expand=True)
            self.canvas.bind("<Configure>", lambda e: self.redraw())
            self.canvas.bind("<ButtonPress-1>", self.on_down)
            self.canvas.bind("<B1-Motion>", self.on_move)
            self.canvas.bind("<ButtonRelease-1>", self.on_up)
            for b in (2, 3):
                self.canvas.bind(f"<ButtonPress-{b}>", self.pan_start)
                self.canvas.bind(f"<B{b}-Motion>", self.pan_move)
            self.canvas.bind("<MouseWheel>", self.on_wheel)
            self.canvas.bind("<Button-4>", lambda e: self.zoom_by(1.25, e.x, e.y))
            self.canvas.bind("<Button-5>", lambda e: self.zoom_by(0.8, e.x, e.y))

            ttk.Button(side, text="Open image...", command=self.open_dialog).pack(fill="x")
            self.lbl_file = ttk.Label(side, text="(no image)", wraplength=300)
            self.lbl_file.pack(fill="x", pady=(2, 8))

            f = ttk.LabelFrame(side, text="Square edge length (real, measured)", padding=6)
            f.pack(fill="x")
            self.edge_var = tk.StringVar(value="7.0")
            ttk.Entry(f, textvariable=self.edge_var, width=9).pack(side="left")
            self.edge_unit = tk.StringVar(value="in")
            ttk.Radiobutton(f, text="in", variable=self.edge_unit, value="in").pack(side="left", padx=6)
            ttk.Radiobutton(f, text="cm", variable=self.edge_unit, value="cm").pack(side="left")

            f = ttk.LabelFrame(side, text="ID squares  (corners: TL, TR, BR, BL)", padding=6)
            f.pack(fill="x", pady=8)
            self.ref_vars, self.status_lbls = [], []
            for i in range(4):
                row = ttk.Frame(f)
                row.pack(fill="x", pady=1)
                tk.Label(row, text=f" ID {i} ", bg=ID_COLORS[i], fg="black", width=6).pack(side="left")
                v = tk.BooleanVar(value=True)
                self.ref_vars.append(v)
                ttk.Checkbutton(row, text="ref", variable=v).pack(side="left", padx=2)
                ttk.Button(row, text="Place", width=6, command=lambda i=i: self.start_place(i)).pack(side="left")
                ttk.Button(row, text="Clear", width=6, command=lambda i=i: self.clear_id(i)).pack(side="left", padx=2)
                lb = ttk.Label(row, text="0/4")
                lb.pack(side="left", padx=4)
                self.status_lbls.append(lb)
            ttk.Label(f, text="ref = use this square to set scale & angle", foreground="#777").pack(anchor="w")

            f = ttk.LabelFrame(side, text="Lines (top-left to top-left)", padding=6)
            f.pack(fill="x")
            self.pair_vars = {}
            for n, (a, b) in enumerate(PAIRS):
                v = tk.BooleanVar(value=True)
                self.pair_vars[(a, b)] = v
                ttk.Checkbutton(f, text=f"ID {a} to ID {b}", variable=v, command=self.redraw).grid(
                    row=n // 2, column=n % 2, sticky="w", padx=4)

            f = ttk.LabelFrame(side, text="Show results in", padding=6)
            f.pack(fill="x", pady=8)
            self.show_in = tk.BooleanVar(value=True)
            self.show_cm = tk.BooleanVar(value=True)
            ttk.Checkbutton(f, text="inches", variable=self.show_in, command=self.show_results).pack(side="left")
            ttk.Checkbutton(f, text="cm", variable=self.show_cm, command=self.show_results).pack(side="left", padx=10)

            row = ttk.Frame(side)
            row.pack(fill="x")
            ttk.Button(row, text="Calculate", command=self.calculate).pack(side="left", expand=True, fill="x")
            self.btn_save = ttk.Button(row, text="Save...", command=self.save, state="disabled")
            self.btn_save.pack(side="left", expand=True, fill="x", padx=(6, 0))

            row = ttk.Frame(side)
            row.pack(fill="x", pady=6)
            ttk.Button(row, text="-", width=4, command=lambda: self.zoom_by(0.8)).pack(side="left")
            ttk.Button(row, text="+", width=4, command=lambda: self.zoom_by(1.25)).pack(side="left", padx=4)
            ttk.Button(row, text="Fit", width=5, command=self.fit).pack(side="left")
            self.lbl_zoom = ttk.Label(row, text="")
            self.lbl_zoom.pack(side="left", padx=8)

            box = ttk.Frame(side)
            box.pack(fill="both", expand=True)
            sb = ttk.Scrollbar(box, orient="vertical")
            self.txt = tk.Text(box, width=44, height=14, font=("Consolas", 9), state="disabled",
                               bg="#f4f4f4", yscrollcommand=sb.set)
            sb.config(command=self.txt.yview)
            sb.pack(side="right", fill="y")
            self.txt.pack(side="left", fill="both", expand=True)
            self.status = ttk.Label(side, text="Open an image to begin.", wraplength=320, foreground="#0050a0")
            self.status.pack(fill="x", pady=(6, 0))

        # ---- image & view ----
        def open_dialog(self):
            p = filedialog.askopenfilename(
                title="Choose the photo",
                filetypes=[("Images", "*.jpg *.jpeg *.png *.bmp *.tif *.tiff"), ("All files", "*.*")])
            if p:
                self.load(p)

        def load(self, path):
            try:
                im = Image.open(path)
                im = ImageOps.exif_transpose(im).convert("RGB")
            except Exception as e:   # noqa: BLE001
                messagebox.showerror("Can't open image", str(e))
                return
            self.img, self.path = im, path
            f = min(1.0, 2400.0 / max(im.size))
            self.small_f = f
            self.small = im.resize((max(1, int(im.width * f)), max(1, int(im.height * f))), Image.LANCZOS) \
                if f < 1.0 else im
            self.pts = {i: [] for i in range(4)}
            self.calc = None
            self.btn_save.config(state="disabled")
            self.lbl_file.config(text=os.path.basename(path) + f"  ({im.width}x{im.height})")
            side = self.sidecar()
            if os.path.exists(side):
                try:
                    with open(side) as fh:
                        d = json.load(fh)
                    for k, v in d.get("points_px", {}).items():
                        self.pts[int(k)] = [tuple(p) for p in v]
                    if "edge_length" in d:
                        self.edge_var.set(str(d["edge_length"]))
                        self.edge_unit.set(d.get("edge_unit", "in"))
                    self.set_status("Loaded saved corner positions for this photo.")
                except (OSError, ValueError):
                    pass
            else:
                self.set_status("Zoom in, press Place for ID 0, then click its 4 corners: TL, TR, BR, BL.")
            self.refresh_counts()
            self.root.update_idletasks()
            self.fit()

        def sidecar(self):
            return os.path.splitext(self.path)[0] + "_targets_points.json"

        def fit(self):
            if self.img is None:
                return
            cw, ch = max(self.canvas.winfo_width(), 50), max(self.canvas.winfo_height(), 50)
            self.z = min(cw / self.img.width, ch / self.img.height)
            self.ox = -(cw / self.z - self.img.width) / 2
            self.oy = -(ch / self.z - self.img.height) / 2
            self.redraw()

        def to_img(self, x, y):
            return self.ox + x / self.z, self.oy + y / self.z

        def to_scr(self, X, Y):
            return (X - self.ox) * self.z, (Y - self.oy) * self.z

        def zoom_by(self, k, x=None, y=None):
            if self.img is None:
                return
            cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
            if x is None:
                x, y = cw / 2, ch / 2
            X, Y = self.to_img(x, y)
            self.z = float(np.clip(self.z * k, 0.02, 40.0))
            self.ox, self.oy = X - x / self.z, Y - y / self.z
            self.redraw()

        def on_wheel(self, e):
            self.zoom_by(1.25 if e.delta > 0 else 0.8, e.x, e.y)

        def pan_px(self, dx, dy):
            self.ox += dx / self.z
            self.oy += dy / self.z
            self.redraw()

        def pan_start(self, e):
            self.drag = ("pan", e.x, e.y, self.ox, self.oy)

        def pan_move(self, e):
            if self.drag and self.drag[0] == "pan":
                _, x0, y0, ox0, oy0 = self.drag
                self.ox = ox0 - (e.x - x0) / self.z
                self.oy = oy0 - (e.y - y0) / self.z
                self.redraw()

        # ---- drawing ----
        def redraw(self):
            c = self.canvas
            c.delete("all")
            if self.img is None:
                c.create_text(20, 20, anchor="nw", fill="#aaa",
                              text="Click 'Open image...' to choose your phone photo.")
                return
            cw, ch = c.winfo_width(), c.winfo_height()
            x0, y0 = self.to_img(0, 0)
            x1, y1 = self.to_img(cw, ch)
            X0, Y0 = max(0.0, x0), max(0.0, y0)
            X1, Y1 = min(float(self.img.width), x1), min(float(self.img.height), y1)
            if X1 > X0 and Y1 > Y0:
                src, f = (self.small, self.small_f) if self.z <= self.small_f else (self.img, 1.0)
                crop = src.crop((int(X0 * f), int(Y0 * f), math.ceil(X1 * f), math.ceil(Y1 * f)))
                cx0, cy0 = int(X0 * f) / f, int(Y0 * f) / f
                cx1, cy1 = math.ceil(X1 * f) / f, math.ceil(Y1 * f) / f
                sw, sh = max(1, round((cx1 - cx0) * self.z)), max(1, round((cy1 - cy0) * self.z))
                res = Image.NEAREST if self.z > 3 else Image.BILINEAR
                self.photo = ImageTk.PhotoImage(crop.resize((sw, sh), res))
                sx, sy = self.to_scr(cx0, cy0)
                c.create_image(sx, sy, image=self.photo, anchor="nw")
            # squares
            for i in range(4):
                p = self.pts[i]
                col = ID_COLORS[i]
                sp = [self.to_scr(*q) for q in p]
                if len(sp) >= 2:
                    poly = sp + ([sp[0]] if len(sp) == 4 else [])
                    c.create_line(*[v for q in poly for v in q], fill=col, width=2)
                for k, (sx, sy) in enumerate(sp):
                    r = 6 if k else 8
                    c.create_oval(sx - r, sy - r, sx + r, sy + r, outline=col, width=2)
                    c.create_line(sx - 12, sy, sx + 12, sy, fill=col)
                    c.create_line(sx, sy - 12, sx, sy + 12, fill=col)
                    c.create_text(sx + 12, sy - 12, text=f"{i}{['TL','TR','BR','BL'][k]}", fill=col,
                                  anchor="sw", font=("Segoe UI", 9, "bold"))
            # measurement lines
            for (a, b), v in self.pair_vars.items():
                if v.get() and self.pts[a] and self.pts[b]:
                    (ax, ay), (bx, by) = self.to_scr(*self.pts[a][0]), self.to_scr(*self.pts[b][0])
                    c.create_line(ax, ay, bx, by, fill="#00e5ff", width=2, dash=(6, 3))
                    txt = f"{a}-{b}"
                    if self.calc and (a, b) in self.calc["dists"]:
                        txt += "  " + self.fmt_len(self.calc["dists"][(a, b)])
                    c.create_text((ax + bx) / 2, (ay + by) / 2 - 8, text=txt, fill="#00e5ff",
                                  font=("Segoe UI", 10, "bold"))
            self.lbl_zoom.config(text=f"{self.z * 100:.0f}%")

        # ---- placing / dragging ----
        def start_place(self, i):
            if self.img is None:
                self.set_status("Open an image first.")
                return
            self.pts[i] = []
            self.placing = (i, 0)
            self.canvas.config(cursor="crosshair")
            self.set_status(f"ID {i}: click the {CORNER_NAMES[0].upper()} corner (zoom in with + / wheel first).")
            self.refresh_counts()
            self.redraw()

        def cancel_place(self):
            self.placing = None
            self.canvas.config(cursor="arrow")
            self.set_status("Placement cancelled.")

        def clear_id(self, i):
            self.pts[i] = []
            if self.placing and self.placing[0] == i:
                self.cancel_place()
            self.calc = None
            self.refresh_counts()
            self.redraw()

        def hit(self, x, y):
            best, bd = None, 12.0
            for i in range(4):
                for k, q in enumerate(self.pts[i]):
                    sx, sy = self.to_scr(*q)
                    d = math.hypot(sx - x, sy - y)
                    if d < bd:
                        best, bd = (i, k), d
            return best

        def on_down(self, e):
            if self.img is None:
                return
            if self.placing:
                i, n = self.placing
                self.pts[i].append(self.to_img(e.x, e.y))
                n += 1
                if n >= 4:
                    self.placing = None
                    self.canvas.config(cursor="arrow")
                    self.set_status(f"ID {i} placed. Drag corners to fine-tune, or Place the next ID.")
                else:
                    self.placing = (i, n)
                    self.set_status(f"ID {i}: click the {CORNER_NAMES[n].upper()} corner.")
                self.calc = None
                self.refresh_counts()
                self.redraw()
                return
            h = self.hit(e.x, e.y)
            if h:
                self.drag = ("pt", h[0], h[1])
            else:
                self.drag = ("pan", e.x, e.y, self.ox, self.oy)

        def on_move(self, e):
            if not self.drag:
                return
            if self.drag[0] == "pt":
                _, i, k = self.drag
                self.pts[i][k] = self.to_img(e.x, e.y)
                self.calc = None
                self.redraw()
            else:
                self.pan_move(e)

        def on_up(self, e):
            self.drag = None

        def refresh_counts(self):
            for i in range(4):
                self.status_lbls[i].config(text=f"{len(self.pts[i])}/4")

        def set_status(self, s):
            self.status.config(text=s)

        # ---- calculation ----
        def edge_mm(self):
            try:
                v = float(self.edge_var.get())
            except ValueError:
                return None
            if v <= 0:
                return None
            return v * MM_PER_IN if self.edge_unit.get() == "in" else v * 10.0

        def calculate(self):
            s = self.edge_mm()
            if s is None:
                messagebox.showwarning("Edge length", "Type the real square edge length (a positive number).")
                return
            placed = {i: np.array(self.pts[i], float) for i in range(4) if len(self.pts[i]) == 4}
            refs = [i for i in placed if self.ref_vars[i].get()]
            if not refs:
                messagebox.showwarning("Reference", "Place at least one ID square and tick its 'ref' box.")
                return
            pairs = [p for p, v in self.pair_vars.items() if v.get()]
            self.calc = measure(placed, refs, s, pairs)
            self.calc["s_mm"] = s
            self.calc["refs"] = refs
            self.btn_save.config(state="normal")
            self.show_results()
            self.redraw()

        def fmt_len(self, mm):
            parts = []
            if self.show_in.get():
                parts.append(f"{mm / MM_PER_IN:.3f} in")
            if self.show_cm.get():
                parts.append(f"{mm / 10:.2f} cm")
            return "  /  ".join(parts) if parts else f"{mm:.1f} mm"

        def show_results(self):
            t = self.txt
            t.config(state="normal")
            t.delete("1.0", "end")
            if self.calc is None:
                t.insert("end", "Press Calculate to see lengths.")
            else:
                c = self.calc
                s = c["s_mm"]
                t.insert("end", f"Reference edge: {self.fmt_len(s)}\n")
                t.insert("end", f"Refs used: {', '.join(map(str, c['refs']))}   "
                                f"fit error: {c['fit']['rms_px']:.2f} px\n")
                t.insert("end", f"Wall origin: ID {c['fit']['frame_id']} top-left\n\n")
                t.insert("end", "Distances (top-left corners):\n")
                for (a, b), d in c["dists"].items():
                    t.insert("end", f"  ID {a}-{b}:  {self.fmt_len(d)}\n")
                t.insert("end", "\nSquare edge lengths measured\n(TOP, RIGHT, BOTTOM, LEFT):\n")
                for k in sorted(c["sides"]):
                    sd = c["sides"][k]
                    tag = "ref" if k in c["refs"] else "   "
                    if self.show_in.get():
                        t.insert("end", f"  ID {k} {tag}: " + "  ".join(f"{x / MM_PER_IN:.3f}" for x in sd) + "  in\n")
                    if self.show_cm.get():
                        t.insert("end", f"  ID {k} {tag}: " + "  ".join(f"{x / 10:.2f}" for x in sd) + "  cm\n")
                worst = max(abs(x - s) / s for sd in c["sides"].values() for x in sd)
                t.insert("end", f"\nWorst edge vs reference: {worst * 100:.2f}%\n")
                t.insert("end", "\nRotation vs ID %d (deg):\n" % c["fit"]["frame_id"])
                r0 = c["rot_deg"][c["fit"]["frame_id"]]
                for k in sorted(c["rot_deg"]):
                    t.insert("end", f"  ID {k}: {c['rot_deg'][k] - r0:+.2f}\n")
                if len(c["refs"]) == 1:
                    t.insert("end", "\n! Only ONE reference square: perspective is\n  extrapolated from a small target, so distances\n  can be off by 1-2%. Tick 'ref' on all four.\n")
                if c["fit"]["rms_px"] > 3 or worst > 0.03:
                    t.insert("end", "\n! Large errors - re-check corner positions\n  (zoom in) or untick a bad 'ref'.\n")
            t.config(state="disabled")

        # ---- save ----
        def save(self):
            if self.calc is None or self.path is None:
                return
            c = self.calc
            default = os.path.join(os.path.dirname(self.path), "target_layout.json")
            out = filedialog.asksaveasfilename(title="Save layout", initialfile="target_layout.json",
                                               initialdir=os.path.dirname(default),
                                               defaultextension=".json",
                                               filetypes=[("JSON", "*.json")])
            if not out:
                return
            data = dict(
                image=os.path.basename(self.path),
                wall_frame="millimetres; origin = top-left corner of ID %d; +x along that square's top edge; +y down"
                           % c["fit"]["frame_id"],
                square_edge_mm=c["s_mm"],
                reference_ids=c["refs"],
                fit_rms_px=c["fit"]["rms_px"],
                tags={str(k): dict(corners_mm=w.tolist(), edge_lengths_mm=c["sides"][k],
                                   rotation_vs_frame_deg=c["rot_deg"][k] - c["rot_deg"][c["fit"]["frame_id"]])
                      for k, w in c["wall"].items()},
                distances_mm={f"{a}-{b}": d for (a, b), d in c["dists"].items()},
                distances_in={f"{a}-{b}": d / MM_PER_IN for (a, b), d in c["dists"].items()},
                points_px={str(k): [list(p) for p in v] for k, v in self.pts.items() if v},
                edge_length=self.edge_var.get(), edge_unit=self.edge_unit.get(),
            )
            with open(out, "w") as f:
                json.dump(data, f, indent=2)
            with open(self.sidecar(), "w") as f:
                json.dump(dict(points_px=data["points_px"], edge_length=data["edge_length"],
                               edge_unit=data["edge_unit"]), f, indent=2)
            png = os.path.splitext(out)[0] + "_annotated.png"
            self.annotated(png)
            self.set_status(f"Saved {os.path.basename(out)} and {os.path.basename(png)}")

        def annotated(self, path):
            im = self.img.copy()
            d = ImageDraw.Draw(im)
            w = max(2, im.width // 700)
            for i in range(4):
                p = self.pts[i]
                if len(p) == 4:
                    d.line(p + [p[0]], fill=ID_COLORS[i], width=w)
                    d.text((p[0][0] + 8, p[0][1] - 18), f"ID {i}", fill=ID_COLORS[i])
            for (a, b), v in self.pair_vars.items():
                if v.get() and len(self.pts[a]) == 4 and len(self.pts[b]) == 4:
                    pa, pb = self.pts[a][0], self.pts[b][0]
                    d.line([pa, pb], fill="#00e5ff", width=w)
                    if self.calc and (a, b) in self.calc["dists"]:
                        d.text(((pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2 - 14),
                               f"{a}-{b}: {self.calc['dists'][(a, b)] / MM_PER_IN:.2f} in", fill="#00e5ff")
            im.save(path)

    root = tk.Tk()
    app = App(root)
    if mainloop:
        root.mainloop()
    return root, app


if __name__ == "__main__":
    run_gui(sys.argv[1] if len(sys.argv) > 1 else None)
