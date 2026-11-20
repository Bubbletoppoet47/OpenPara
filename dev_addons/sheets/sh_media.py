"""
sh_media.py - videos on a sheet (the Media ribbon: Insert video).

    prepare(path, cancel, progress) -> dict    a video file (.mp4 or .avi) made ready for the workbook: {"mp4": bytes, "poster": bytes (PNG of the first frame),
                                               "w", "h", "duration", "converted", "name"}.  An AVI (what SolidWorks exports), or any file that is not H.264 in
                                               yuv420p, is converted to an H.264 MP4 with ffmpeg first (the original file is never touched).
    new_video(wb, sheet, prep, pos, room)      the entry for sheet.pictures: a picture (the first frame) that also has "video" (a key of Workbook.images: the
                                               MP4 bytes, stored INSIDE the workbook once) and "loop"
    VideoFrame(grid, picture)                  the video on the grid: the first frame with a play button; click it to play and pause, a scrubber, a Loop tick;
                                               drag to move, the corner to resize, double-click for the panel (it is a PictureFrame with a player)
    export_mp4(wb, picture, path)              saves the video as an .mp4 file ("" or the reason it could not be saved)

ffmpeg comes from the imageio-ffmpeg package (see sh_deps.ffmpeg_exe).  Playing uses Qt's own player (QMediaPlayer with a QVideoSink: the frames are drawn by
the frame itself, so it can sit under the row and column headers and be clipped like a picture); no sound is played (these are animations).
"""
import atexit
import os
import re
import subprocess
import tempfile

from PyQt6.QtCore import QPointF, QSize, Qt, QUrl
from PyQt6.QtGui import QColor, QImage, QPainter, QPolygonF
from PyQt6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QSlider, QStyle, QToolButton, QWidget

import sh_deps
import sh_picture

VIDEO_FILTER = "Videos (*.mp4 *.avi);;MP4 (*.mp4);;AVI (*.avi);;All files (*)"
WARN_BYTES = 50_000_000            # a video bigger than this is stored in the sheet file only after the person says yes
MAX_BYTES = 250_000_000            # ... and one bigger than this is not stored at all
NO_FFMPEG = ("Videos need ffmpeg, a small helper program that comes with the Sheets add-on (imageio-ffmpeg), and it is not on this computer.  "
             "Update the Sheets add-on from the add-on manager, or install ffmpeg.")


class MediaError(Exception):
    """A video that cannot be brought in; the text says why, in words for the person."""


class Cancelled(MediaError):
    """The person pressed Cancel while the video was being prepared."""


# ------------------------------------------------------------------------------------------------------------------ looking at a file
def _clock(txt):
    h, m, s = txt.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def probe(exe, path):
    """{"codec", "pix", "w", "h", "duration" (seconds, 0 when unknown), "audio"} of a video file, read from what `ffmpeg -i` says about it."""
    try:
        r = subprocess.run([exe, "-hide_banner", "-i", path], capture_output=True, text=True, errors="replace", timeout=60, **_quiet())
    except (OSError, subprocess.TimeoutExpired) as ex:
        raise MediaError(f"ffmpeg could not look at this file: {ex}")
    txt = r.stderr or ""
    m = re.search(r"Video:\s*([\w\-]+)[^,\n]*?,\s*(\w+)(?:\([^)]*\))?,\s*(\d+)x(\d+)", txt)
    if not m:
        if re.search(r"Video:", txt):
            raise MediaError("This video is in a form Sheets cannot read.")
        raise MediaError("This is not a video file, or it has no picture in it (Sheets takes .mp4 and .avi).")
    d = re.search(r"Duration:\s*(\d+:\d+:[\d.]+)", txt)
    return {"codec": m.group(1).lower(), "pix": m.group(2).lower(), "w": int(m.group(3)), "h": int(m.group(4)),
            "duration": _clock(d.group(1)) if d else 0.0, "audio": bool(re.search(r"Audio:", txt))}


def _quiet():
    """Windows: no console window flashes up for every ffmpeg run."""
    if os.name == "nt":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        return {"startupinfo": si, "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    return {}


def needs_conversion(path, info):
    """An H.264 MP4 in yuv420p with even sides plays everywhere and is stored as it is; everything else is converted."""
    return not (os.path.splitext(path)[1].lower() == ".mp4" and info["codec"] == "h264" and info["pix"] == "yuv420p" and info["w"] % 2 == 0 and info["h"] % 2 == 0)


# ------------------------------------------------------------------------------------------------------------------ making it ready
def _convert(exe, src, dst, duration, cancel, progress):
    cmd = [exe, "-y", "-hide_banner", "-loglevel", "error", "-nostats", "-progress", "pipe:1", "-i", src, "-map", "0:v:0", "-map", "0:a:0?",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
           "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", dst]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace", **_quiet())
    except OSError as ex:
        raise MediaError(f"ffmpeg could not be started: {ex}")
    try:
        for line in proc.stdout:
            if cancel is not None and cancel():
                proc.kill()
                raise Cancelled("Cancelled.")
            if progress is not None and duration > 0 and line.startswith(("out_time_us=", "out_time_ms=")):
                try:
                    progress(min(0.99, max(0.0, int(line.split("=", 1)[1]) / 1e6 / duration)))
                except ValueError:
                    pass
        err = proc.stderr.read()
        rc = proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
    if rc != 0 or not os.path.isfile(dst) or os.path.getsize(dst) == 0:
        raise MediaError("This video could not be converted to MP4." + (f"  ffmpeg says: {err.strip()[-300:]}" if err.strip() else ""))


def _poster(exe, mp4, png):
    r = subprocess.run([exe, "-y", "-hide_banner", "-loglevel", "error", "-i", mp4, "-frames:v", "1", png], capture_output=True, text=True, errors="replace",
                       timeout=120, **_quiet())
    if r.returncode != 0 or not os.path.isfile(png):
        raise MediaError("The first picture of this video could not be read." + (f"  ffmpeg says: {r.stderr.strip()[-300:]}" if r.stderr.strip() else ""))


def prepare(path, cancel=None, progress=None):
    """A video file (.mp4 / .avi) -> {"mp4": bytes, "poster": PNG bytes of the first frame, "w", "h", "duration", "converted", "name"}.  Raises MediaError (with
    a sentence for the person) or Cancelled.  `cancel()` is asked often; `progress(fraction)` is called while a conversion runs.  Runs in any thread."""
    exe = sh_deps.ffmpeg_exe()
    if exe is None:
        raise MediaError(NO_FFMPEG)
    if not os.path.isfile(path):
        raise MediaError("The file is not there any more.")
    info = probe(exe, path)
    work = tempfile.mkdtemp(prefix="opara_media_")
    try:
        converted = needs_conversion(path, info)
        mp4 = os.path.join(work, "video.mp4")
        if converted:
            _convert(exe, path, mp4, info["duration"], cancel, progress)
        else:
            mp4 = path
        size = os.path.getsize(mp4)
        if size > MAX_BYTES:
            raise MediaError(f"This video is {size / 1e6:.0f} MB as an MP4, which is too much to keep inside a sheet (the limit is {MAX_BYTES // 1_000_000} MB).  "
                             "Make it shorter or smaller first.")
        png = os.path.join(work, "poster.png")
        _poster(exe, mp4, png)
        with open(mp4, "rb") as fh:
            mp4_bytes = fh.read()
        with open(png, "rb") as fh:
            poster = fh.read()
        if progress is not None:
            progress(1.0)
        return {"mp4": mp4_bytes, "poster": poster, "w": info["w"] - info["w"] % 2, "h": info["h"] - info["h"] % 2, "duration": info["duration"],
                "converted": converted, "name": os.path.splitext(os.path.basename(path))[0]}
    finally:
        import shutil
        shutil.rmtree(work, ignore_errors=True)


def new_video(wb, sheet, prep, pos, room=None):
    """The entry for sheet.pictures: the first frame as a picture, plus "video" (the MP4, kept once in wb.images) and "loop"."""
    image = QImage.fromData(prep["poster"])
    if image.isNull():
        raise MediaError("The first picture of this video could not be read.")
    pic = sh_picture.new_picture(wb, sheet, prep["poster"], image, prep["name"], pos, room)
    pic["video"] = wb.add_image(prep["mp4"])
    pic["loop"] = False
    pic["dur"] = float(prep.get("duration") or 0.0)
    return pic


def export_mp4(wb, pic, path):
    data = wb.images.get(pic.get("video") or "")
    if not data:
        return "The video's data is missing."
    try:
        with open(path, "wb") as fh:
            fh.write(data)
        return ""
    except OSError as ex:
        return f"{os.path.basename(path)} could not be saved: {ex.strerror or ex}"


# ------------------------------------------------------------------------------------------------------------------ a file for the player
_made = set()


def cache_file(wb, key):
    """The MP4 of the workbook's video `key` as a file the player can open (made once; removed when the program ends)."""
    d = os.path.join(tempfile.gettempdir(), "opara_sheets_media")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"{key}.mp4")
    data = wb.images.get(key, b"")
    if not os.path.isfile(path) or os.path.getsize(path) != len(data):
        with open(path, "wb") as fh:
            fh.write(data)
    _made.add(path)
    return path


@atexit.register
def _cleanup():
    for p in list(_made):
        try:
            os.remove(p)
        except OSError:
            pass


def _mmss(ms):
    s = max(0, int(round(ms / 1000.0)))
    return f"{s // 60}:{s % 60:02d}"


# ------------------------------------------------------------------------------------------------------------------ the video on the grid
class _JumpSlider(QSlider):
    """A slider that jumps to where it is clicked."""

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton and self.maximum() > self.minimum():
            x = ev.position().x()
            self.setValue(int(self.minimum() + (self.maximum() - self.minimum()) * min(1.0, max(0.0, x / max(1, self.width())))))
            self.sliderMoved.emit(self.value())
        super().mousePressEvent(ev)


class VideoFrame(sh_picture.PictureFrame):
    """A video floating over the cells.  Click it to play or pause, drag it to move it, drag the corner to resize it.  The bar at the bottom has the play
    button, the scrubber, the time and the Loop tick."""
    BAR = 26

    def __init__(self, grid, pic):
        super().__init__(grid, pic)
        self.player = None
        self.sink = None
        self.img = None                          # the latest picture of the running video
        self.pos_ms = 0
        self.dur_ms = int(float(pic.get("dur") or 0.0) * 1000)
        self.playing = False
        self.problem = ""
        self._scrubbing = False
        self.bar = QWidget(self)
        self.bar.setAutoFillBackground(True)
        self.bar.setStyleSheet("QWidget { background: rgba(24, 30, 40, 200); color: white; } QCheckBox { spacing: 4px; } "
                               "QToolButton { border: none; background: transparent; } QSlider::groove:horizontal { height: 4px; background: #5b6676; border-radius: 2px; } "
                               "QSlider::sub-page:horizontal { background: #6fb1ff; border-radius: 2px; } "
                               "QSlider::handle:horizontal { width: 10px; margin: -4px 0; background: white; border-radius: 5px; }")
        lay = QHBoxLayout(self.bar)
        lay.setContentsMargins(4, 0, 4, 0)
        lay.setSpacing(6)
        self.btn = QToolButton()
        self.btn.setToolTip("Play / pause (or click the video)")
        self.btn.clicked.connect(lambda _c=False: self.toggle())
        self.slider = _JumpSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.setToolTip("Drag to move through the video")
        self.slider.sliderPressed.connect(lambda: setattr(self, "_scrubbing", True))
        self.slider.sliderReleased.connect(lambda: setattr(self, "_scrubbing", False))
        self.slider.sliderMoved.connect(self.scrub)
        self.time = QLabel("0:00")
        self.loop_cb = QCheckBox("Loop")
        self.loop_cb.setToolTip("Start again when the video ends (saved with the sheet)")
        self.loop_cb.toggled.connect(self.loop_toggled)
        for w in (self.btn, self.slider, self.time, self.loop_cb):
            lay.addWidget(w)
        lay.setStretch(1, 1)
        self.set_button()
        self.sync()

    # ----- the picture's own fields
    def sync(self):
        p = self.pic()
        if p is None:
            return
        self.loop_cb.blockSignals(True)
        self.loop_cb.setChecked(bool(p.get("loop")))
        self.loop_cb.blockSignals(False)
        if not self.dur_ms:
            self.dur_ms = int(float(p.get("dur") or 0.0) * 1000)
        self.show_time()

    def loop_toggled(self, on):
        p = self.pic()
        if p is None or bool(p.get("loop")) == bool(on):
            return
        before = self.grid.wb.picture_state(self.grid.sheet, self.pid)
        p["loop"] = bool(on)
        if self.grid.wb.record_picture("Video loop", self.grid.sheet, self.pid, before):
            self.changed.emit(self.pid)

    def place(self):
        super().place()
        p = self.pic()
        if p is None:
            return
        w, h = self.width(), self.height()
        small = h < 3 * self.BAR or w < 120
        self.bar.setVisible(not small)
        self.bar.setGeometry(0, h - self.BAR, max(1, w - self.CORNER), self.BAR)         # (the corner stays free for resizing)
        self.time.setVisible(w >= 260)
        self.loop_cb.setVisible(w >= 200)
        self.sync()

    def show_time(self):
        self.time.setText(f"{_mmss(self.pos_ms)} / {_mmss(self.dur_ms)}" if self.dur_ms else _mmss(self.pos_ms))
        if not self._scrubbing:
            self.slider.blockSignals(True)
            self.slider.setValue(int(1000 * self.pos_ms / self.dur_ms) if self.dur_ms else 0)
            self.slider.blockSignals(False)

    def set_button(self):
        icon = QStyle.StandardPixmap.SP_MediaPause if self.playing else QStyle.StandardPixmap.SP_MediaPlay
        self.btn.setIcon(self.style().standardIcon(icon))
        self.btn.setIconSize(QSize(16, 16))

    # ----- playing
    def _ensure_player(self):
        if self.player is not None:
            return True
        p = self.pic()
        if p is None or not p.get("video") or p["video"] not in self.grid.wb.images:
            self.problem = "The video's data is missing."
            return False
        try:
            from PyQt6.QtMultimedia import QMediaPlayer, QVideoSink
        except ImportError:
            self.problem = "This computer's Qt has no video player, so the video cannot be played here."
            return False
        try:
            path = cache_file(self.grid.wb, p["video"])
        except OSError as ex:
            self.problem = f"The video could not be prepared for playing: {ex.strerror or ex}"
            return False
        self._Status = QMediaPlayer.MediaStatus
        self.player = QMediaPlayer(self)
        self.sink = QVideoSink(self)
        self.player.setVideoSink(self.sink)
        self.sink.videoFrameChanged.connect(self.on_frame)
        self.player.positionChanged.connect(self.on_position)
        self.player.durationChanged.connect(self.on_duration)
        self.player.mediaStatusChanged.connect(self.on_status)
        self.player.errorOccurred.connect(self.on_error)
        self.player.setSource(QUrl.fromLocalFile(path))
        return True

    def toggle(self):
        if self.playing:
            self.pause()
        else:
            self.play()

    def play(self):
        if not self._ensure_player():
            self.grid.message.emit(self.problem, "bad")
            return
        self.problem = ""
        if self.dur_ms and self.pos_ms >= self.dur_ms - 50:
            self.player.setPosition(0)
        self.player.play()
        self.playing = True
        self.set_button()
        self.update()

    def pause(self):
        if self.player is not None:
            self.player.pause()
        self.playing = False
        self.set_button()
        self.update()

    def scrub(self, value):
        if not self._ensure_player():
            return
        ms = int(self.dur_ms * value / 1000.0)
        self.player.setPosition(ms)
        self.pos_ms = ms
        self.show_time()
        self.update()

    def on_frame(self, frame):
        img = frame.toImage()
        if not img.isNull():
            self.img = img
            self.update()

    def on_position(self, ms):
        self.pos_ms = int(ms)
        self.show_time()
        if ms == 0 and not self.playing:
            self.update()

    def on_duration(self, ms):
        if ms > 0:
            self.dur_ms = int(ms)
            self.show_time()

    def on_status(self, status):
        if status == self._Status.EndOfMedia:
            if self.loop_cb.isChecked():
                self.player.setPosition(0)
                self.player.play()
            else:
                self.playing = False
                self.set_button()
                self.update()

    def on_error(self, _err, text=""):
        self.playing = False
        self.problem = "This video could not be played here." + (f" ({text})" if text else "")
        self.set_button()
        self.grid.message.emit(self.problem, "bad")
        self.update()

    def release(self):
        """The frame is going away (the video was deleted or another sheet is shown): the player stops."""
        pl, self.player = self.player, None
        if pl is not None:
            try:
                pl.stop()
                pl.setVideoSink(None)
                pl.setSource(QUrl())
                pl.deleteLater()
            except RuntimeError:
                pass
        self.playing = False

    # ----- drawing and the mouse
    def paintEvent(self, ev):
        p = QPainter(self)
        r = self.rect()
        showing_video = self.img is not None and (self.playing or self.pos_ms > 0)
        if showing_video:
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, not (self._drag is not None and self._drag[0] == "size"))
            p.drawImage(r, self.img)
        else:
            self.draw_picture(p, r)
        if not self.playing:                                             # the big play button over the first frame
            d = max(24, min(64, min(r.width(), r.height()) // 3))
            c = QPointF(r.width() / 2.0, (r.height() - (self.BAR if self.bar.isVisible() else 0)) / 2.0)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(20, 26, 36, 170))
            p.drawEllipse(c, d / 2.0, d / 2.0)
            p.setBrush(QColor("white"))
            k = d * 0.2
            p.drawPolygon(QPolygonF([QPointF(c.x() - k * 0.7, c.y() - k * 1.1), QPointF(c.x() - k * 0.7, c.y() + k * 1.1), QPointF(c.x() + k * 1.2, c.y())]))
        if self.problem:
            p.setPen(QColor("#ffb4b4"))
            p.drawText(r.adjusted(6, 4, -6, -self.BAR - 4), Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap, self.problem)
        self.draw_selection(p, r)
        p.end()

    def mouseReleaseEvent(self, ev):
        d = self._drag
        click = (d is not None and d[0] == "move" and ev.button() == Qt.MouseButton.LeftButton
                 and (ev.globalPosition().toPoint() - d[1]).manhattanLength() < 4)
        super().mouseReleaseEvent(ev)
        if click:
            self.toggle()


def make_frame(grid, pic):
    """The widget for a picture of a sheet: a video gets a VideoFrame, a picture a PictureFrame.  It remembers what it was made for (see frame_fits)."""
    f = VideoFrame(grid, pic) if pic.get("video") else sh_picture.PictureFrame(grid, pic)
    f.owner = grid.sheet_obj()
    f.kind = pic.get("video") or ""
    return f


def frame_fits(f, pic, sheet):
    """True when the widget `f` may go on showing `pic` of `sheet`.  A picture's id is only its number on ITS sheet ("pic1" is on every sheet that has a picture),
    so the id alone cannot tell two pictures apart: a frame is kept only for the sheet it was made for, and for a video only while it is that same video
    (a photo never becomes a video's widget or the other way round, and a video never plays on a sheet it was not put on)."""
    return getattr(f, "owner", None) is sheet and getattr(f, "kind", None) == (pic.get("video") or "")
