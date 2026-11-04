"""Shared mesh / field drawing for the FEA and CFD views, with a GPU path and a CPU path.

The caller gives screen-space node positions, the triangles and a value per node (smooth) or per triangle
(flat); it gets back a QImage of the coloured mesh.  The GPU path draws through an off-screen OpenGL context
(Qt only; no extra packages).  The CPU path is vectorised numpy.  If the GPU path fails for any reason the
program switches to the CPU path and carries on.

Setting (QSettings "render/mode"): "auto" (default), "cpu" or "gpu".
"""
import numpy as np
from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QImage, QColor

import result_style


def ramp(t):
    """0..1 -> RGB (0..255 floats): the colour scheme shared by all result pictures (result_style.py)."""
    return result_style.ramp(t)


def reload_lut():
    """The shared colour scheme changed: rebuild the GPU colour table (the CPU path asks result_style every time)."""
    if _gpu.get("state") != "ok":
        return
    try:
        from PyQt6.QtOpenGL import QOpenGLTexture
        ctx, surf = _gpu["ctx"], _gpu["surf"]
        if not ctx.makeCurrent(surf):
            raise RuntimeError("context")
        lut = (ramp(np.linspace(0, 1, 256)) + 0.5).astype(np.uint8)
        img = QImage(256, 1, QImage.Format.Format_RGB888)
        for i in range(256):
            img.setPixelColor(i, 0, QColor(*[int(v) for v in lut[i]]))
        tex = QOpenGLTexture(img)
        tex.setMinMagFilters(QOpenGLTexture.Filter.Linear, QOpenGLTexture.Filter.Linear)
        tex.setWrapMode(QOpenGLTexture.WrapMode.ClampToEdge)
        old = _gpu["tex"]
        _gpu["tex"] = tex
        try:
            old.destroy()
        except Exception:
            pass
        ctx.doneCurrent()
    except Exception:
        _gpu["state"] = "failed"


# ---------------------------------------------------------------------------------------------- setting
_gpu = {"state": "untried", "why": "", "ctx": None, "surf": None, "prog": None, "fbo": None, "fsize": None,
        "tex": None, "funcs": None, "buf": None, "info": ""}


def get_mode():
    try:
        m = str(QSettings("Sketcher", "Sketcher").value("render/mode", "auto"))
    except Exception:
        m = "auto"
    return m if m in ("auto", "cpu", "gpu") else "auto"


def set_mode(m):
    try:
        QSettings("Sketcher", "Sketcher").setValue("render/mode", m)
    except Exception:
        pass
    if m != "cpu" and _gpu["state"] == "failed" and str(_qs().value("render/guard", "0")) != "1":
        _gpu["state"] = "untried"       # give the GPU another chance when the person asks for it again


def _qs():
    return QSettings("Sketcher", "Sketcher")


_PROBE = """
import sys, numpy as np
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import meshdraw as md
md._init_gpu()
if md._gpu["state"] != "ok":
    print("FAIL " + md._gpu["why"]); sys.exit(0)
sx = np.array([2.0, 30.0, 2.0]); sy = np.array([2.0, 2.0, 30.0])
img = md._gpu_render(40, 40, sx, sy, np.array([[0, 1, 2]]), np.array([0.0, 0.5, 1.0]), None, None, 0.3)
print("OK " + md._gpu["info"])
"""


def _probe():
    """Try the GPU in a separate process first: a driver that crashes must not take the program down with it."""
    import os, subprocess, sys
    try:
        kw = {}
        if os.name == "nt":
            kw["creationflags"] = 0x08000000            # no console window
        r = subprocess.run([__import__("paths").python_exe(), "-c", _PROBE], cwd=os.path.dirname(os.path.abspath(__file__)),
                           capture_output=True, text=True, timeout=40, **kw)
    except subprocess.TimeoutExpired:
        return False, "the OpenGL test timed out"
    except Exception as e:                              # noqa: BLE001
        return False, "the OpenGL test could not run (" + type(e).__name__ + ")"
    out = (r.stdout or "").strip().splitlines()
    last = out[-1] if out else ""
    if r.returncode == 0 and last.startswith("OK"):
        return True, last[3:]
    if r.returncode != 0:
        return False, f"the OpenGL test crashed (exit code {r.returncode}); the graphics driver does not work with this"
    return False, last[5:] if last.startswith("FAIL") else "the OpenGL test gave no answer"


def backend():
    """'gpu' or 'cpu': what will actually be used right now."""
    m = get_mode()
    if m == "cpu":
        return "cpu"
    if _gpu["state"] == "untried":
        _start_gpu()
    return "gpu" if _gpu["state"] == "ok" else "cpu"


def _start_gpu():
    q = _qs()
    if str(q.value("render/guard", "0")) == "1":
        _gpu["state"], _gpu["why"] = "failed", "the GPU stopped the program last time, so it was switched off (press 'Check the GPU again' to retry)"
        return
    ok, info = _probe()
    if not ok:
        _gpu["state"], _gpu["why"] = "failed", info
        return
    q.setValue("render/guard", "1")                     # cleared again after the first picture; still set = the program died in OpenGL
    q.sync()
    _init_gpu()
    if _gpu["state"] != "ok":
        q.setValue("render/guard", "0")


def guard_clear():
    if _gpu["state"] == "ok":
        _qs().setValue("render/guard", "0")


def recheck():
    _qs().setValue("render/guard", "0")
    _gpu["state"] = "untried"


def status_text():
    m = get_mode()
    if m == "cpu":
        return "Drawing with the CPU."
    if _gpu["state"] == "untried":
        _start_gpu()
    if _gpu["state"] == "ok":
        return "GPU ready: " + _gpu["info"]
    return "GPU not available (" + (_gpu["why"] or "unknown reason") + "); drawing with the CPU."


# ---------------------------------------------------------------------------------------------- GPU
_VS = """
attribute vec2 pos;
attribute float val;
uniform vec2 size;
varying float t;
void main() {
    gl_Position = vec4(2.0 * pos.x / size.x - 1.0, 1.0 - 2.0 * pos.y / size.y, 0.0, 1.0);
    t = val;
}
"""
_FS = """
uniform sampler2D ramp;
uniform vec4 flat_colour;
uniform float use_flat;
varying float t;
void main() {
    if (use_flat > 0.5) { gl_FragColor = flat_colour; }
    else { gl_FragColor = vec4(texture2D(ramp, vec2(clamp(t, 0.0, 1.0) * 0.99609375 + 0.001953125, 0.5)).rgb, 1.0); }
}
"""


def _init_gpu():
    _gpu["state"] = "failed"
    try:
        from PyQt6.QtGui import QOpenGLContext, QOffscreenSurface, QSurfaceFormat
        from PyQt6.QtOpenGL import (QOpenGLShaderProgram, QOpenGLShader, QOpenGLBuffer, QOpenGLTexture,
                                    QOpenGLVersionFunctionsFactory, QOpenGLVersionProfile)
        fmt = QSurfaceFormat()
        fmt.setRenderableType(QSurfaceFormat.RenderableType.OpenGL)
        fmt.setVersion(2, 1)
        fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.NoProfile)
        surf = QOffscreenSurface()
        surf.setFormat(fmt)
        surf.create()
        ctx = QOpenGLContext()
        ctx.setFormat(fmt)
        if not ctx.create():
            raise RuntimeError("no OpenGL context")
        if not surf.isValid() or not ctx.makeCurrent(surf):
            raise RuntimeError("OpenGL surface unusable")
        prof = QOpenGLVersionProfile()
        prof.setVersion(2, 1)
        funcs = QOpenGLVersionFunctionsFactory.get(prof, ctx)
        if funcs is None:
            raise RuntimeError("OpenGL 2.1 functions missing")
        funcs.initializeOpenGLFunctions()
        prog = QOpenGLShaderProgram()
        if not prog.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Vertex, _VS):
            raise RuntimeError("vertex shader: " + prog.log())
        if not prog.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Fragment, _FS):
            raise RuntimeError("fragment shader: " + prog.log())
        prog.bindAttributeLocation("pos", 0)
        prog.bindAttributeLocation("val", 1)
        if not prog.link():
            raise RuntimeError("shader link: " + prog.log())
        lut = (ramp(np.linspace(0, 1, 256)) + 0.5).astype(np.uint8)
        img = QImage(256, 1, QImage.Format.Format_RGB888)
        for i in range(256):
            img.setPixelColor(i, 0, QColor(*[int(v) for v in lut[i]]))
        tex = QOpenGLTexture(img)
        tex.setMinMagFilters(QOpenGLTexture.Filter.Linear, QOpenGLTexture.Filter.Linear)
        tex.setWrapMode(QOpenGLTexture.WrapMode.ClampToEdge)
        buf = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
        buf.create()
        _gpu.update(ctx=ctx, surf=surf, prog=prog, tex=tex, funcs=funcs, buf=buf, fbo=None, fsize=None)
        s = lambda e: (funcs.glGetString(e) or b"")
        try:
            r = s(0x1F01)
            v = s(0x1F02)
            _gpu["info"] = (r.decode() if isinstance(r, (bytes, bytearray)) else str(r)) + ", OpenGL " + \
                           (v.decode() if isinstance(v, (bytes, bytearray)) else str(v))
        except Exception:
            _gpu["info"] = "OpenGL"
        _gpu["state"] = "ok"
        _gpu["why"] = ""
        ctx.doneCurrent()
    except Exception as e:                                  # noqa: BLE001 - any failure means 'use the CPU'
        _gpu["why"] = str(e).strip().splitlines()[0][:120] if str(e).strip() else type(e).__name__
        _gpu["state"] = "failed"


def _gpu_render(W, H, sx, sy, tris, nodal, tval, edges, edge_alpha):
    from PyQt6.QtOpenGL import QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat
    g = _gpu
    ctx, surf, prog, funcs, tex, buf = g["ctx"], g["surf"], g["prog"], g["funcs"], g["tex"], g["buf"]
    if not ctx.makeCurrent(surf):
        raise RuntimeError("cannot make the OpenGL context current")
    try:
        if g["fbo"] is None or g["fsize"] != (W, H):
            fmt = QOpenGLFramebufferObjectFormat()
            fbo = QOpenGLFramebufferObject(W, H, fmt)
            if not fbo.isValid():
                raise RuntimeError("framebuffer unusable")
            g["fbo"], g["fsize"] = fbo, (W, H)
        fbo = g["fbo"]
        fbo.bind()
        GL_COLOR_BUFFER_BIT, GL_TRIANGLES, GL_LINES, GL_FLOAT = 0x4000, 0x0004, 0x0001, 0x1406
        GL_BLEND, GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA, GL_TEXTURE_2D, GL_TEXTURE0 = 0x0BE2, 0x0302, 0x0303, 0x0DE1, 0x84C0
        funcs.glViewport(0, 0, W, H)
        funcs.glDisable(0x0B71)                                     # depth test
        funcs.glDisable(0x0B44)                                     # cull face
        funcs.glClearColor(1.0, 1.0, 1.0, 1.0)
        funcs.glClear(GL_COLOR_BUFFER_BIT)
        prog.bind()
        prog.setUniformValue("size", float(W), float(H))
        prog.setUniformValue("ramp", 0)
        funcs.glActiveTexture(GL_TEXTURE0)
        tex.bind()
        buf.bind()
        funcs.glEnableVertexAttribArray(0)
        funcs.glEnableVertexAttribArray(1)

        def draw(data, mode, flat=None):
            data = np.ascontiguousarray(data, dtype=np.float32)
            buf.allocate(data.tobytes(), data.nbytes)
            funcs.glVertexAttribPointer(0, 2, GL_FLOAT, 0, 12, 0)
            funcs.glVertexAttribPointer(1, 1, GL_FLOAT, 0, 12, 8)
            if flat is None:
                prog.setUniformValue("use_flat", 0.0)
            else:
                prog.setUniformValue("use_flat", 1.0)
                prog.setUniformValue("flat_colour", *flat)
            funcs.glDrawArrays(mode, 0, len(data))

        T = tris
        if nodal is not None:
            v = np.empty((len(T) * 3, 3), dtype=np.float32)
            v[:, 0] = sx[T].ravel()
            v[:, 1] = sy[T].ravel()
            v[:, 2] = nodal[T].ravel()
        else:
            v = np.empty((len(T) * 3, 3), dtype=np.float32)
            v[:, 0] = sx[T].ravel()
            v[:, 1] = sy[T].ravel()
            v[:, 2] = np.repeat(tval, 3)
        if len(v):
            draw(v, GL_TRIANGLES)
            if nodal is None:                       # flat colours: also outline each triangle in its own colour (no gaps)
                funcs.glPolygonMode(0x0408, 0x1B01)  # GL_FRONT_AND_BACK, GL_LINE
                draw(v, GL_TRIANGLES)
                funcs.glPolygonMode(0x0408, 0x1B02)
        if edges is not None and len(edges):
            funcs.glEnable(GL_BLEND)
            funcs.glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            e = np.empty((len(edges) * 2, 3), dtype=np.float32)
            e[0::2, 0], e[0::2, 1] = sx[edges[:, 0]], sy[edges[:, 0]]
            e[1::2, 0], e[1::2, 1] = sx[edges[:, 1]], sy[edges[:, 1]]
            e[:, 2] = 0.0
            draw(e, GL_LINES, flat=(0.0, 0.0, 0.0, float(edge_alpha)))
            funcs.glDisable(GL_BLEND)
        funcs.glDisableVertexAttribArray(0)
        funcs.glDisableVertexAttribArray(1)
        buf.release()
        tex.release()
        prog.release()
        funcs.glFinish()
        img = fbo.toImage()
        fbo.release()
        guard_clear()
        return img.convertToFormat(QImage.Format.Format_RGB32)
    finally:
        ctx.doneCurrent()


# ---------------------------------------------------------------------------------------------- CPU
def raster(W, H, sx, sy, tris):
    """Which triangle covers each pixel and where in it: returns (pixel_index, tri_index, L) with L the (k, 3)
    barycentric weights.  Vectorised numpy; later triangles win where they overlap (callers assign in order)."""
    tris = np.asarray(tris, dtype=np.int64)
    M = len(tris)
    if M == 0:
        return np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int64), np.zeros((0, 3))
    X = sx[tris]
    Y = sy[tris]
    x0 = np.clip(np.floor(X.min(axis=1)), 0, W - 1).astype(np.int64)
    x1 = np.clip(np.ceil(X.max(axis=1)), 0, W - 1).astype(np.int64)
    y0 = np.clip(np.floor(Y.min(axis=1)), 0, H - 1).astype(np.int64)
    y1 = np.clip(np.ceil(Y.max(axis=1)), 0, H - 1).astype(np.int64)
    vis = (X.max(axis=1) >= 0) & (X.min(axis=1) <= W) & (Y.max(axis=1) >= 0) & (Y.min(axis=1) <= H)
    bw = x1 - x0 + 1
    bh = y1 - y0 + 1
    order = np.nonzero(vis)[0]
    cls = np.ceil(np.log2(np.maximum(np.maximum(bw[order], bh[order]), 1))).astype(np.int64)
    P, Tn, Ls = [], [], []
    for c in np.unique(cls):
        ids = order[cls == c]
        side = 1 << int(c)
        per = max(1, 1_500_000 // (side * side))
        gx, gy = np.meshgrid(np.arange(side), np.arange(side))
        gx, gy = gx.ravel(), gy.ravel()
        for s in range(0, len(ids), per):
            ch = ids[s:s + per]
            px = x0[ch][:, None] + gx[None, :]
            py = y0[ch][:, None] + gy[None, :]
            inb = (px <= x1[ch][:, None]) & (py <= y1[ch][:, None])
            cx = px + 0.5
            cy = py + 0.5
            xa, xb, xc = X[ch, 0][:, None], X[ch, 1][:, None], X[ch, 2][:, None]
            ya, yb, yc = Y[ch, 0][:, None], Y[ch, 1][:, None], Y[ch, 2][:, None]
            det = (yb - yc) * (xa - xc) + (xc - xb) * (ya - yc)
            det = np.where(np.abs(det) < 1e-12, 1e-12, det)
            l1 = ((yb - yc) * (cx - xc) + (xc - xb) * (cy - yc)) / det
            l2 = ((yc - ya) * (cx - xc) + (xa - xc) * (cy - yc)) / det
            l3 = 1.0 - l1 - l2
            ins = inb & (l1 >= -1e-9) & (l2 >= -1e-9) & (l3 >= -1e-9)
            k, j = np.nonzero(ins)
            P.append(py[k, j] * W + px[k, j])
            Tn.append(ch[k])
            Ls.append(np.stack([l1[k, j], l2[k, j], l3[k, j]], axis=1))
            tiny = np.nonzero((bw[ch] <= 1) & (bh[ch] <= 1))[0]       # smaller than a pixel: still mark the pixel under its centre
            if len(tiny):
                t = ch[tiny]
                cxp = np.clip(np.floor(X[t].mean(axis=1)), 0, W - 1).astype(np.int64)
                cyp = np.clip(np.floor(Y[t].mean(axis=1)), 0, H - 1).astype(np.int64)
                P.append(cyp * W + cxp)
                Tn.append(t)
                Ls.append(np.full((len(t), 3), 1.0 / 3.0))
    if not P:
        return np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int64), np.zeros((0, 3))
    P, Tn, Ls = np.concatenate(P), np.concatenate(Tn), np.concatenate(Ls)
    o = np.argsort(Tn, kind="stable")                                  # later triangles win, as when painting
    return P[o], Tn[o], np.clip(Ls[o], 0.0, None)


def colour_raster(W, H, R, nodal, tris, tri_vals):
    """A QImage from a raster() result and values already scaled to 0..1."""
    P, Tn, L = R
    out = np.full(W * H, 0xFFFFFFFF, dtype=np.uint32)
    if len(P):
        if nodal is not None:
            v = (L * nodal[tris[Tn]]).sum(axis=1) / np.maximum(L.sum(axis=1), 1e-12)
        else:
            v = tri_vals[Tn]
        c = (ramp(v) + 0.5).astype(np.uint32)
        out[P] = 0xFF000000 | (c[:, 0] << 16) | (c[:, 1] << 8) | c[:, 2]
    return QImage(out.reshape(H, W).copy().data, W, H, W * 4, QImage.Format.Format_RGB32).copy()


def _cpu_render(W, H, sx, sy, tris, nodal, tval, edges, edge_alpha, lo, span):
    return colour_raster(W, H, raster(W, H, sx, sy, tris), nodal, tris, tval)


def draw_edges_on(img, sx, sy, edges, alpha):
    from PyQt6.QtGui import QPainter, QPen, QColor
    from PyQt6.QtCore import QLineF
    q = QPainter(img)
    q.setPen(QPen(QColor(0, 0, 0, int(alpha * 255)), 0.7))
    q.drawLines([QLineF(sx[a], sy[a], sx[b], sy[b]) for a, b in edges])
    q.end()


_edge_cache = {"key": None, "ref": None, "val": None}


def unique_edges(tris):
    k = (id(tris), len(tris))
    if _edge_cache["key"] == k and _edge_cache["ref"] is tris:
        return _edge_cache["val"]
    e = _unique_edges(tris)
    _edge_cache.update(key=k, ref=tris, val=e)
    return e


def _unique_edges(tris):
    e = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    return np.unique(np.sort(e, axis=1), axis=0)


def render(W, H, sx, sy, tris, nodal=None, tri_vals=None, lo=0.0, hi=1.0, edges=None, edge_alpha=0.35):
    """Return a QImage (RGB32, white background) of the triangles coloured by value.

    sx, sy: screen positions of the nodes (pixels, y down).  Give `nodal` (one value per node, smooth) or
    `tri_vals` (one per triangle, flat).  Values are mapped lo..hi onto the colour ramp.
    `edges`: optional (k, 2) node pairs drawn as thin translucent black lines.
    """
    W, H = max(int(W), 2), max(int(H), 2)
    sx = np.asarray(sx, dtype=float)
    sy = np.asarray(sy, dtype=float)
    tris = np.asarray(tris, dtype=np.int64)
    span = (hi - lo) or 1.0
    if nodal is not None:
        nodal = (np.asarray(nodal, dtype=float) - lo) / span
    else:
        tri_vals = (np.asarray(tri_vals, dtype=float) - lo) / span
    if backend() == "gpu":
        try:
            return _gpu_render(W, H, sx, sy, tris, nodal, tri_vals, edges, edge_alpha)
        except Exception as e:                              # noqa: BLE001
            _gpu["state"] = "failed"
            _gpu["why"] = "drawing failed: " + (str(e).strip().splitlines()[0][:100] if str(e).strip() else type(e).__name__)
            try:
                _gpu["ctx"].doneCurrent()
            except Exception:
                pass
    img = _cpu_render(W, H, sx, sy, tris, nodal, tri_vals, edges, edge_alpha, 0.0, 1.0)
    if edges is not None and len(edges):
        draw_edges_on(img, sx, sy, edges, edge_alpha)
    return img


def edge_overlay(W, H, sx, sy, edges, alpha=0.31):
    """A transparent QImage with the edges drawn in translucent black (GPU when available)."""
    W, H = max(int(W), 2), max(int(H), 2)
    sx = np.asarray(sx, dtype=float)
    sy = np.asarray(sy, dtype=float)
    if backend() == "gpu":
        try:
            img = _gpu_render(W, H, sx, sy, np.zeros((0, 3), dtype=np.int64), None, np.zeros(0), edges, alpha)
            ptr = img.constBits()
            ptr.setsize(img.sizeInBytes())
            a = np.frombuffer(ptr, dtype=np.uint8).reshape(H, img.bytesPerLine() // 4, 4)[:, :W, :]
            out = np.zeros((H, W), dtype=np.uint32)
            out |= (255 - a[:, :, 1].astype(np.uint32)) << 24                  # darkness of the line = opacity
            return QImage(out.data, W, H, W * 4, QImage.Format.Format_ARGB32).copy()
        except Exception as e:                                  # noqa: BLE001
            _gpu["state"] = "failed"
            _gpu["why"] = "drawing failed: " + (str(e).strip().splitlines()[0][:100] if str(e).strip() else type(e).__name__)
    img = QImage(W, H, QImage.Format.Format_ARGB32)
    img.fill(0)
    draw_edges_on(img, sx, sy, edges, alpha)
    return img
