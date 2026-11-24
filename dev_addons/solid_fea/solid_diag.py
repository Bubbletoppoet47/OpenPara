"""solid_diag.py - the DIAGNOSTICS REPORT of the 3D windows (3D Thermal, 3D CFD): one plain-text page that says what computer and program this ran on, what the
geometry and the mesh were, what the setup was in plain numbers, how long every stage took, how the solver converged and every message the window gave
(errors in full).  The text is meant to be pasted to whoever is looking for a fault, so it holds no opinions: only numbers and words.

The builders return lists of lines and need no window (the physics windows add their own parts: the setup and the results); show_report() is the dialog with
Copy to clipboard and Save as text file, and writes the same text into the project folder as diagnostics.txt every time it opens.
"""
import os
import platform
import sys
import time

FILE_NAME = "diagnostics.txt"


def _version_of(name, attr="__version__"):
    try:
        mod = __import__(name)
        v = getattr(mod, attr, None)
        return str(v) if v is not None else "present (no version)"
    except Exception as ex:                                                  # noqa: BLE001 - a missing package is a line of the report, not an error
        return f"NOT AVAILABLE ({type(ex).__name__}: {ex})"


def package_versions():
    """[(name, version text)] of the packages the 3D windows stand on."""
    out = [("numpy", _version_of("numpy")), ("scipy", _version_of("scipy")), ("gmsh", _version_of("gmsh")), ("pyvista", _version_of("pyvista")),
           ("pyamg", _version_of("pyamg"))]
    try:
        import vtk
        out.append(("vtk", vtk.vtkVersion.GetVTKVersion()))
    except Exception as ex:                                                  # noqa: BLE001
        out.append(("vtk", f"NOT AVAILABLE ({type(ex).__name__})"))
    try:
        from PyQt6 import QtCore
        out.append(("PyQt6", f"{QtCore.PYQT_VERSION_STR} (Qt {QtCore.QT_VERSION_STR})"))
    except Exception as ex:                                                  # noqa: BLE001
        out.append(("PyQt6", f"NOT AVAILABLE ({type(ex).__name__})"))
    return out


def memory_bytes():
    """(total, available) bytes of memory, or (None, None) when this computer will not say."""
    try:
        import psutil
        m = psutil.virtual_memory()
        return int(m.total), int(m.available)
    except Exception:                                                        # noqa: BLE001
        pass
    try:
        if sys.platform.startswith("win"):
            import ctypes

            class Status(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong), ("avail", ctypes.c_ulonglong),
                            ("tpage", ctypes.c_ulonglong), ("apage", ctypes.c_ulonglong), ("tvirt", ctypes.c_ulonglong), ("avirt", ctypes.c_ulonglong),
                            ("ext", ctypes.c_ulonglong)]
            st = Status()
            st.length = ctypes.sizeof(Status)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
            return int(st.total), int(st.avail)
        info = {}
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                k, _, v = line.partition(":")
                info[k.strip()] = int(v.split()[0]) * 1024
        return info.get("MemTotal"), info.get("MemAvailable")
    except Exception:                                                        # noqa: BLE001
        return None, None


def gb(n):
    return "unknown" if n is None else f"{n / 2 ** 30:.1f} GB"


def program_lines(title):
    """The computer and the program: what the report is about, when, and which versions of everything."""
    L = [title, time.strftime("%Y-%m-%d %H:%M:%S %z"), ""]
    try:
        import channel
        import version
        mode = ""
        try:
            mode = ", Full dev mode" if channel.is_full_dev() else ", Testing mode"
        except Exception:                                                    # noqa: BLE001
            pass
        L.append(f"program: {channel.app_name()} {version.__version__}{mode if channel.is_playground() else ''}")
    except Exception as ex:                                                  # noqa: BLE001
        L.append(f"program: unknown ({type(ex).__name__}: {ex})")
    L.append(f"python {sys.version.split()[0]} ({platform.architecture()[0]}) on {platform.platform()}")
    tot, av = memory_bytes()
    L.append(f"processor: {platform.processor() or platform.machine() or 'unknown'}, {os.cpu_count()} logical cores; memory {gb(tot)}, {gb(av)} free now")
    L.append("packages: " + ", ".join(f"{n} {v}" for n, v in package_versions()))
    try:
        import addons
        act = [a for a in addons.dev_ids() if addons.is_active(a)]
        if act:
            L.append("development add-ons active: " + ", ".join(act))
    except Exception:                                                        # noqa: BLE001
        pass
    return L


def geometry_lines(win):
    """The part or assembly the window holds: source, bodies, faces, size, splits, dimensions."""
    g = win.geom
    if g is None:
        return ["Nothing imported yet."]
    src = win.src or {}
    bb = g["bbox"]
    size = [bb[1][i] - bb[0][i] for i in range(3)]
    o = g.get("orig") or g
    L = [f"source: {src.get('type', 'part')} '{src.get('name') or '?'}' (original: {src.get('path') or 'not known'})",
         f"project folder: {win.path or 'not saved yet'}",
         f"size {size[0]:.6g} x {size[1]:.6g} x {size[2]:.6g} mm, volume {g['volume']:.8g} mm3, diagonal {g['diag']:.6g} mm",
         f"faces {len(o['faces'])}" + (f" ({len(g['faces'])} with the patches)" if g.get("orig") else "") + f", vertices {len(g['verts'])}"]
    kinds = {}
    for f in o["faces"]:
        kinds[f["kind"]] = kinds.get(f["kind"], 0) + 1
    L.append("face kinds: " + ", ".join(f"{k} {n}" for k, n in sorted(kinds.items())))
    if g.get("bodies"):
        L.append(f"assembly of {len(g['bodies'])} bodies, bond distance {win.setup.get('bond_tol') or 'automatic'}, "
                 f"faces between bodies {sum(1 for f in g['faces'] if f.get('interface'))}")
        for b in g["bodies"]:
            m = b.get("material") or {}
            L.append(f"  body '{b['name']}': material '{m.get('name') or '?'}'" + (f", volume {b['volume']:.6g} mm3" if "volume" in b else ""))
    if win.setup.get("splits"):
        L.append(f"split faces: {len(win.setup['splits'])}")
    if win.setup.get("dims"):
        L.append("dimensions edited: " + ", ".join(f"{k}={v}" for k, v in win.setup["dims"].items()))
    for t in g.get("notes") or []:
        L.append("note: " + t)
    for t in g.get("hints") or []:
        L.append("hint: " + t)
    return L


def mesh_lines(q, h=None, opts=None):
    """The mesh a solve was made on: counts, order, sizes and the quality report."""
    if q is None:
        return ["No mesh yet."]
    qr = q.get("quality")
    note = None
    if qr is None:
        try:
            import solid_mesh
            qr = solid_mesh.quality(q)
        except Exception as ex:                                              # noqa: BLE001
            qr = None
            note = f"quality could not be measured: {type(ex).__name__}: {ex}"
    L = []
    nodes = len(q["nodes"])
    tets = len(q["tets"])
    L.append(f"{tets:,} tetrahedra, {nodes:,} nodes, {'quadratic' if q.get('order', 2) == 2 else 'linear'} elements" + (f", element size asked for {h:.6g} mm" if h else ""))
    if opts:
        L.append("mesh options: " + ", ".join(f"{k}={v}" for k, v in sorted(opts.items()) if k not in ("face_sizes", "local")))
        if opts.get("face_sizes"):
            L.append(f"  sizes on single faces: {len(opts['face_sizes'])}")
    if qr:
        L.append(f"edge length mm: smallest {qr['edge_min']:.5g}, average {qr['edge_mean']:.5g}, largest {qr['edge_max']:.5g}")
        L.append(f"worst radius ratio {qr['ratio_min']:.4f}, average {qr['ratio_mean']:.4f}; elements below 0.2: {qr['below_02']:,}, below 0.1: {qr['below_01']:,}")
        L.append(f"dihedral angles {qr['dihedral_min']:.1f} to {qr['dihedral_max']:.1f} degrees; inverted elements {qr['inverted']}; "
                 f"element volume {qr['vol_min']:.4g} to {qr['vol_max']:.4g} mm3; total {qr['volume']:.8g} mm3")
    elif note:
        L.append(note)
    return L


def jobs_lines(job_log):
    """How long every job took and the stages in it.  A stage that ran many times (a factorisation in every Newton step) is one line: how many times, the
    total, the mean and the longest."""
    if not job_log:
        return ["No job has run in this window yet."]
    L = []
    for j in job_log:
        L.append(f"{j['title']}: {'finished' if j['ok'] else 'FAILED or cancelled'} in {j['seconds']:.2f} s")
        agg = {}
        for key, size, sec in j.get("stages") or []:
            a = agg.setdefault(key, {"n": 0, "size": size, "total": 0.0, "max": 0.0, "sizes": set()})
            a["n"] += 1
            a["total"] += sec
            a["max"] = max(a["max"], sec)
            a["size"] = size
            a["sizes"].add(round(size))
        for key, a in agg.items():
            if a["n"] == 1:
                L.append(f"    stage {key:<9} size {a['size']:>14,.0f}  {a['total']:9.3f} s")
            else:
                same = "each" if len(a["sizes"]) == 1 else "last"
                L.append(f"    stage {key:<9} {a['n']} times, size {a['size']:>14,.0f} {same}  total {a['total']:.3f} s, mean {a['total'] / a['n']:.3f} s, "
                         f"longest {a['max']:.3f} s")
    return L


def events_lines(events, limit=200):
    """What the window said, oldest first; an error is printed in full."""
    if not events:
        return ["Nothing was said."]
    L = []
    for t, level, text in events[-limit:]:
        stamp = time.strftime("%H:%M:%S", time.localtime(t))
        lines = str(text).strip().splitlines() or [""]
        L.append(f"{stamp} {level.upper():<5} {lines[0]}")
        L.extend("                " + x for x in lines[1:])
    return L


def section(title, lines):
    return ["", f"== {title} =="] + list(lines)


def write_report(folder, text):
    """Writes the report into the project folder as diagnostics.txt -> the path, or None when the folder cannot be written."""
    if not folder or not os.path.isdir(folder):
        return None
    path = os.path.join(folder, FILE_NAME)
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text if text.endswith("\n") else text + "\n")
        os.replace(tmp, path)
        return path
    except OSError:
        return None


def show_report(parent, text, folder=None, title="Diagnostics report"):
    """The report in a window: Copy to clipboard, Save as text file...; it is also written to the project folder.  -> the path written (or None)."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QFont, QGuiApplication
    from PyQt6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout
    path = write_report(folder, text)
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.resize(860, 660)
    lay = QVBoxLayout(dlg)
    lab = QLabel(f"Saved in the project folder as <b>{path}</b>" if path else "Not saved in a project folder (save the project first, or use Save as).")
    lab.setWordWrap(True)
    lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    lay.addWidget(lab)
    box = QPlainTextEdit()
    box.setReadOnly(True)
    box.setFont(QFont("Consolas", 9))
    box.setPlainText(text)
    lay.addWidget(box, 1)
    row = QHBoxLayout()
    b_copy = QPushButton("Copy to clipboard")
    b_copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(box.toPlainText()))
    row.addWidget(b_copy)
    b_save = QPushButton("Save as text file...")

    def save():
        p, _ = QFileDialog.getSaveFileName(dlg, "Save report", os.path.join(folder or "", FILE_NAME), "Text (*.txt)")
        if p:
            with open(p, "w", encoding="utf-8") as f:
                f.write(box.toPlainText())
    b_save.clicked.connect(save)
    row.addWidget(b_save)
    row.addStretch(1)
    b_close = QPushButton("Close")
    b_close.clicked.connect(dlg.accept)
    row.addWidget(b_close)
    lay.addLayout(row)
    dlg.exec()
    return path
