"""
anim_export.py - save the pictures of a result animation as a file: animated GIF (always), MP4 (when OpenCV or imageio-ffmpeg is installed)
or a folder of PNG pictures.  Shared by 1D FEA, 2D FEA and 2D CFD.

  formats()                       the formats that can be written here, e.g. ["gif", "mp4", "png"]
  write(images, path, fmt, fps, playback)   images = QImage list; playback 0 = once, 1 = loop, 2 = back and forth.  -> the path written
  ask_path(parent, base_name)     the Save dialog -> (path, fmt) or None
  capture(parent, n, grab, title) calls grab(k) for k in 0..n-1 with a progress box and a Cancel button -> [QImage] or None
  export(parent, tab_name, n, grab, fps, playback, set_bg=...) all three: ask, capture, write, tell the user.
  Transparent formats (webp, apng, pngt) need set_bg(level): the window draws on that grey level (255 white / 0 black; None = normal).
"""
import os
import shutil
import tempfile

from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication, QDialog, QFileDialog, QLabel, QMessageBox, QProgressBar, QPushButton, QVBoxLayout

FILTERS = {"webp": "Animated WebP, transparent background (*.webp)", "apng": "Animated PNG, transparent background (*.png)",
           "pngt": "PNG pictures, transparent background, one per frame (*.png)", "gif": "Animated GIF (*.gif)", "mp4": "MP4 video (*.mp4)",
           "png": "PNG pictures, one per frame (*.png)"}
EXT = {"webp": ".webp", "apng": ".png", "pngt": ".png", "gif": ".gif", "mp4": ".mp4", "png": ".png"}
TRANSPARENT = ("webp", "apng", "pngt")        # the formats whose background is transparent (only what is drawn is kept)


def is_transparent(fmt):
    return fmt in TRANSPARENT


class ExportError(Exception):
    pass


def _have(mod):
    try:
        __import__(mod)
        return True
    except Exception:  # noqa: BLE001 - a broken install counts as "not available"
        return False


def mp4_available():
    return _have("cv2") or (_have("imageio") and _have("imageio_ffmpeg"))


def formats():
    return ["webp", "apng", "pngt", "gif"] + (["mp4"] if mp4_available() else []) + ["png"]


def matte(on_white, on_black):
    """Two pictures of the same frame, drawn on white and on black -> one QImage with a transparent background.
    A pixel that is the same on both is fully covered (alpha 1); one that differs by the full 255 is background (alpha 0); anything between
    (anti-aliased edges, translucent mesh lines) gets the matching alpha and its true colour back."""
    import numpy as np
    w = _rgb(on_white).astype(np.float32)
    b = _rgb(on_black).astype(np.float32)
    alpha = np.clip(1.0 - (w - b).mean(axis=2) / 255.0, 0.0, 1.0)
    col = np.where(alpha[..., None] > 1e-4, b / np.maximum(alpha[..., None], 1e-4), 0.0)
    out = np.dstack([np.clip(col, 0, 255), alpha * 255.0]).round().astype(np.uint8)
    h, wd = alpha.shape
    q = QImage(out.tobytes(), wd, h, wd * 4, QImage.Format.Format_RGBA8888)
    return q.copy()


def _rgb(img):
    import numpy as np
    q = img.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = q.width(), q.height()
    raw = np.frombuffer(bytes(q.constBits().asarray(q.sizeInBytes())), dtype=np.uint8).reshape(h, q.bytesPerLine() // 4, 4)
    return raw[:, :w, :3]


def ordered(images, playback):
    """The frames in playing order: back and forth = forward, then back again without repeating the end pictures."""
    if playback == 2 and len(images) > 2:
        return list(images) + list(images[-2:0:-1])
    return list(images)


def _pil(img):
    from PIL import Image
    q = img.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = q.width(), q.height()
    raw = bytes(q.constBits().asarray(q.sizeInBytes()))
    im = Image.frombuffer("RGBA", (w, h), raw, "raw", "RGBA", q.bytesPerLine(), 1)
    bg = Image.new("RGB", (w, h), "white")
    bg.paste(im, mask=im.split()[3])
    return bg


def _rgba(img):
    from PIL import Image
    q = img.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = q.width(), q.height()
    raw = bytes(q.constBits().asarray(q.sizeInBytes()))
    return Image.frombuffer("RGBA", (w, h), raw, "raw", "RGBA", q.bytesPerLine(), 1).copy()


def _write_webp(images, path, fps, playback):
    ims = [_rgba(i) for i in ordered(images, playback)]
    ims[0].save(path, "WEBP", save_all=True, append_images=ims[1:], duration=max(20, int(round(1000.0 / max(fps, 0.1)))),
                loop=1 if playback == 0 else 0, lossless=False, quality=92, alpha_quality=100, method=4, exact=True)


def _write_apng(images, path, fps, playback):
    ims = [_rgba(i) for i in ordered(images, playback)]
    ims[0].save(path, "PNG", save_all=True, append_images=ims[1:], duration=max(20, int(round(1000.0 / max(fps, 0.1)))),
                loop=1 if playback == 0 else 0, disposal=1)


def _write_gif(images, path, fps, playback):
    from PIL import Image
    frames = [_pil(i).convert("P", palette=Image.Palette.ADAPTIVE, colors=256) for i in ordered(images, playback)]
    kw = {"save_all": True, "append_images": frames[1:], "duration": max(20, int(round(1000.0 / max(fps, 0.1)))), "optimize": False}
    if playback != 0:
        kw["loop"] = 0                                           # forever (no loop entry = once)
    frames[0].save(path, "GIF", **kw)


def _write_mp4(images, path, fps, playback):
    frames = ordered(images, playback)
    w, h = frames[0].width() // 2 * 2, frames[0].height() // 2 * 2          # even sizes: players insist on them
    arrs = []
    import numpy as np
    for q in frames:
        a = np.array(_pil(q))[:h, :w]
        arrs.append(a)
    tmp_dir = tempfile.mkdtemp()
    tmp = os.path.join(tmp_dir, "anim.mp4")                      # written to a plain temp path: OpenCV cannot open every Windows path
    try:
        done = False
        if _have("cv2"):
            import cv2
            vw = cv2.VideoWriter(tmp, cv2.VideoWriter_fourcc(*"mp4v"), float(fps), (w, h))
            if vw.isOpened():
                for a in arrs:
                    vw.write(a[:, :, ::-1])
                vw.release()
                done = os.path.getsize(tmp) > 0
        if not done and _have("imageio") and _have("imageio_ffmpeg"):
            import imageio
            with imageio.get_writer(tmp, fps=float(fps), codec="libx264", quality=7, macro_block_size=1) as wr:
                for a in arrs:
                    wr.append_data(a)
            done = os.path.getsize(tmp) > 0
        if not done:
            raise ExportError("The MP4 could not be written (no working video encoder). Use the GIF or PNG pictures instead.")
        shutil.move(tmp, path)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _write_png(images, path, fps, playback):
    base = os.path.splitext(path)[0]
    os.makedirs(base, exist_ok=True)
    name = os.path.basename(base)
    for k, q in enumerate(ordered(images, playback), 1):
        if not q.save(os.path.join(base, f"{name}_{k:04d}.png"), "PNG"):
            raise ExportError("A picture could not be written to " + base)
    return base


def write(images, path, fmt, fps=10.0, playback=0):
    """Writes the frames.  -> the file (or, for png, the folder) that now exists."""
    if not images:
        raise ExportError("There are no frames to save.")
    if fmt not in formats():
        raise ExportError(f"The format {fmt} is not available here.")
    if fmt in ("png", "pngt"):
        return _write_png(images, path, fps, playback)
    if not path.lower().endswith(EXT[fmt]):
        path += EXT[fmt]
    {"webp": _write_webp, "apng": _write_apng, "gif": _write_gif, "mp4": _write_mp4}[fmt](images, path, fps, playback)
    return path


def ask_path(parent, base_name, start_dir=""):
    fmts = formats()
    dlg_filter = ";;".join(FILTERS[f] for f in fmts)
    start = os.path.join(start_dir, base_name + ".webp") if start_dir else base_name + ".webp"
    path, flt = QFileDialog.getSaveFileName(parent, "Export animation", start, dlg_filter, FILTERS["webp"])
    if not path:
        return None
    fmt = next((f for f in fmts if FILTERS[f] == flt), None)
    if fmt is None:                                              # the extension decides when the filter text is not recognised
        ext = os.path.splitext(path)[1].lower()
        fmt = next((f for f in fmts if EXT[f] == ext), "webp")
    return path, fmt


def capture(parent, n, grab, title="Drawing the animation frames", set_bg=None):
    """grab(k) -> QImage of frame k.  A progress box with Cancel; returns the list, or None when cancelled.
    `set_bg(level)` (level 255 = white, 0 = black): when given, every frame is grabbed on white and on black and made transparent (matte)."""
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setModal(True)
    dlg.setMinimumWidth(380)
    lay = QVBoxLayout(dlg)
    lbl = QLabel("Starting...")
    bar = QProgressBar()
    bar.setRange(0, n)
    btn = QPushButton("Cancel")
    for w in (lbl, bar, btn):
        lay.addWidget(w)
    state = {"stop": False}
    btn.clicked.connect(lambda: state.update(stop=True))
    dlg.show()
    out = []
    for k in range(n):
        if state["stop"]:
            dlg.close()
            return None
        lbl.setText(f"Frame {k + 1} of {n}")
        if set_bg is None:
            out.append(grab(k))
        else:
            set_bg(255)
            on_white = grab(k)
            set_bg(0)
            out.append(matte(on_white, grab(k)))
        bar.setValue(k + 1)
        QApplication.processEvents()
    dlg.close()
    return out


def export(parent, tab_name, n, grab, fps, playback, say=None, path_fmt=None, set_bg=None):
    """Ask for the file, draw the frames, write them, tell the user.  `path_fmt` = (path, fmt) skips the question (used by tests / scripts).
    -> the path written, or None (cancelled or failed; a failure is shown)."""
    ask = path_fmt or ask_path(parent, f"{tab_name.replace(' ', '_')}_animation")
    if ask is None:
        return None
    path, fmt = ask
    if is_transparent(fmt) and set_bg is None:
        QMessageBox.warning(parent, "Export animation", "A transparent background is not available for this window yet. Use GIF, MP4 or PNG pictures.")
        return None
    imgs = capture(parent, n, grab, set_bg=set_bg if is_transparent(fmt) else None)
    if set_bg is not None:
        set_bg(None)
    if imgs is None:
        if say:
            say("Export cancelled.")
        return None
    try:
        out = write(imgs, path, fmt, fps, playback)
    except (ExportError, OSError, ValueError) as ex:
        QMessageBox.warning(parent, "Export animation", f"The animation could not be saved:\n{ex}")
        if say:
            say("Export failed.")
        return None
    if say:
        say(f"Animation saved: {out}  ({len(imgs)} frames, {fmt.upper()})")
    return out
