"""
anim_export.py - save the pictures of a result animation as a file: animated GIF (always), MP4 (when OpenCV or imageio-ffmpeg is installed)
or a folder of PNG pictures.  Shared by 1D FEA, 2D FEA and 2D CFD.

  formats()                       the formats that can be written here, e.g. ["gif", "mp4", "png"]
  write(images, path, fmt, fps, playback)   images = QImage list; playback 0 = once, 1 = loop, 2 = back and forth.  -> the path written
  ask_path(parent, base_name)     the Save dialog -> (path, fmt) or None
  capture(parent, n, grab, title) calls grab(k) for k in 0..n-1 with a progress box and a Cancel button -> [QImage] or None
  export(parent, tab_name, n, grab, fps, playback) all three: ask, capture, write, tell the user
"""
import os
import shutil
import tempfile

from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication, QDialog, QFileDialog, QLabel, QMessageBox, QProgressBar, QPushButton, QVBoxLayout

FILTERS = {"gif": "Animated GIF (*.gif)", "mp4": "MP4 video (*.mp4)", "png": "PNG pictures, one per frame (*.png)"}
EXT = {"gif": ".gif", "mp4": ".mp4", "png": ".png"}


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
    return ["gif"] + (["mp4"] if mp4_available() else []) + ["png"]


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
    if fmt == "png":
        return _write_png(images, path, fps, playback)
    if not path.lower().endswith(EXT[fmt]):
        path += EXT[fmt]
    {"gif": _write_gif, "mp4": _write_mp4}[fmt](images, path, fps, playback)
    return path


def ask_path(parent, base_name, start_dir=""):
    fmts = formats()
    dlg_filter = ";;".join(FILTERS[f] for f in fmts)
    start = os.path.join(start_dir, base_name + ".gif") if start_dir else base_name + ".gif"
    path, flt = QFileDialog.getSaveFileName(parent, "Export animation", start, dlg_filter, FILTERS["gif"])
    if not path:
        return None
    fmt = next((f for f in fmts if FILTERS[f] == flt), None)
    if fmt is None:                                              # the extension decides when the filter text is not recognised
        ext = os.path.splitext(path)[1].lower()
        fmt = next((f for f in fmts if EXT[f] == ext), "gif")
    return path, fmt


def capture(parent, n, grab, title="Drawing the animation frames"):
    """grab(k) -> QImage of frame k.  A progress box with Cancel; returns the list, or None when cancelled."""
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
        out.append(grab(k))
        bar.setValue(k + 1)
        QApplication.processEvents()
    dlg.close()
    return out


def export(parent, tab_name, n, grab, fps, playback, say=None, path_fmt=None):
    """Ask for the file, draw the frames, write them, tell the user.  `path_fmt` = (path, fmt) skips the question (used by tests / scripts).
    -> the path written, or None (cancelled or failed; a failure is shown)."""
    ask = path_fmt or ask_path(parent, f"{tab_name.replace(' ', '_')}_animation")
    if ask is None:
        return None
    path, fmt = ask
    imgs = capture(parent, n, grab)
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
