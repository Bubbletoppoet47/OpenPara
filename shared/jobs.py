"""Shared background-job machinery: a Worker thread, the progress window, and a mixin that gives any window run_task / cancel / progress.

A window that uses JobMixin needs: self.quiet, self.threaded, self.panel (the widget disabled while a job runs) and statusBar()."""
import time
import traceback

from PyQt6.QtCore import QObject, QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import QApplication, QDialog, QLabel, QMessageBox, QProgressBar, QPushButton, QVBoxLayout

from tasks import Cancelled


class Worker(QObject):
    progress = pyqtSignal(str, float)       # stage, fraction (-1: unknown)
    done = pyqtSignal(object)
    failed = pyqtSignal(str, bool)          # message, was cancelled

    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.cancel = False

    def cb(self, stage, frac=None):
        if self.cancel:
            raise Cancelled()
        self.progress.emit(stage, -1.0 if frac is None else float(frac))

    def run(self):
        try:
            res = self.fn(self.cb)
        except Cancelled:
            self.failed.emit("Cancelled", True)
        except Exception as ex:
            self.failed.emit(f"{type(ex).__name__}: {ex}", False)
            traceback.print_exc()
        else:
            self.done.emit(res)


class ProgressWindow(QDialog):
    """Its own window for a running job: what it is doing, a large bar, seconds elapsed / left, and Cancel."""

    def __init__(self, parent, on_cancel):
        super().__init__(parent)
        self.setWindowTitle("Working...")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowTitleHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.CustomizeWindowHint)
        self.setModal(False)              # other tabs stay usable while this one works
        self.setMinimumWidth(520)
        self.on_cancel = on_cancel
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(10)
        self.title = QLabel("")
        f = self.title.font()
        f.setPointSize(f.pointSize() + 3)
        f.setBold(True)
        self.title.setFont(f)
        self.stage = QLabel("")
        self.stage.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setMinimumHeight(28)
        self.bar.setTextVisible(True)
        self.time = QLabel("")
        self.btn = QPushButton("Cancel")
        self.btn.setMinimumHeight(32)
        self.btn.clicked.connect(self.cancel)
        for x in (self.title, self.stage, self.bar, self.time):
            lay.addWidget(x)
        lay.addWidget(self.btn, alignment=Qt.AlignmentFlag.AlignRight)

    def cancel(self):
        self.btn.setEnabled(False)
        self.stage.setText("Cancelling... (stops at the next safe point)")
        self.on_cancel()

    def closeEvent(self, ev):
        ev.ignore()
        self.cancel()

    def begin(self, name):
        self.title.setText(name)
        self.stage.setText("Starting")
        self.time.setText("")
        self.bar.setRange(0, 0)
        self.bar.setFormat("")
        self.btn.setEnabled(True)

    def update_progress(self, stage, frac, elapsed):
        if self.btn.isEnabled():
            self.stage.setText(stage)
        if frac >= 0:
            if self.bar.maximum() == 0:
                self.bar.setRange(0, 1000)
            self.bar.setValue(int(1000 * min(frac, 1.0)))
            self.bar.setFormat(f"{100 * min(frac, 1.0):.0f} %")
        else:
            self.bar.setRange(0, 0)
        txt = f"{elapsed:.0f} s elapsed"
        if frac > 0.05:
            txt += f"  ·  about {elapsed * (1 - frac) / frac:.0f} s left"
        else:
            txt += "  ·  time left not known yet"
        self.time.setText(txt)

    def place(self):
        p = self.parent()
        if p is not None:
            c = p.mapToGlobal(p.rect().center())
            self.adjustSize()
            self.move(c.x() - self.width() // 2, c.y() - self.height() // 2)


class JobMixin:
    busy = False
    thread = None
    worker = None
    job_cancelled = False
    last_error = ""

    def init_jobs(self):
        self.progress_win = ProgressWindow(self, self.cancel_job)
        self.tick_timer = QTimer(self)
        self.tick_timer.timeout.connect(self.update_clock)
        self.show_timer = QTimer(self)                       # the window only appears when a job takes longer than a moment
        self.show_timer.setSingleShot(True)
        self.show_timer.timeout.connect(self.show_progress_window)

    # ------------------------------------------------------------------------------------------------------ jobs (threads, progress, cancel)
    def fail(self, what, ex):
        self.last_error = f"{what}: {ex}"
        self.statusBar().showMessage(self.last_error)
        if not self.quiet:
            QMessageBox.warning(self, what, str(ex))

    def run_task(self, name, fn, on_done):
        """Run fn(progress) -> result; then on_done(result) in the window's thread.  Threaded: bar + Cancel; otherwise straight through."""
        if self.busy:
            return self.fail(name, "Another job is still running.")
        self.last_error = ""
        self.job_cancelled = False
        if not self.threaded:
            try:
                res = fn(lambda stage, frac=None: None)
            except Cancelled:
                self.job_cancelled = True
                return None
            except Exception as ex:
                traceback.print_exc()
                return self.fail(name, ex)
            return on_done(res)
        self.busy = True
        self.job_name, self.job_t0, self.job_stage, self.job_frac = name, time.time(), "Starting", -1.0
        self.panel.setEnabled(False)
        self.progress_win.begin(name)
        self.show_timer.start(500)
        self.tick_timer.start(250)
        self.thread = QThread(self)
        self.worker = Worker(fn)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.on_progress)
        self.worker.done.connect(lambda res: self.job_finished(on_done, res))
        self.worker.failed.connect(lambda msg, cancelled: self.job_failed(name, msg, cancelled))
        self.thread.start()

    def show_progress_window(self):
        if self.busy:
            self.progress_win.place()
            self.progress_win.show()
            self.progress_win.raise_()
            self.update_clock()

    def on_progress(self, stage, frac):
        self.job_stage, self.job_frac = stage, frac
        self.update_clock()

    def update_clock(self):
        if self.busy:
            self.progress_win.update_progress(self.job_stage, self.job_frac, time.time() - self.job_t0)

    def cancel_job(self):
        if self.worker:
            self.worker.cancel = True

    def end_job(self):
        self.tick_timer.stop()
        self.show_timer.stop()
        self.busy = False
        self.panel.setEnabled(True)
        self.progress_win.hide()
        if self.thread:
            self.thread.quit()
            self.thread.wait(5000)
            self.thread = None
        self.worker = None

    def job_finished(self, on_done, res):
        secs = time.time() - self.job_t0
        self.end_job()
        try:
            on_done(res)
        except Exception as ex:
            traceback.print_exc()
            self.fail(self.job_name, ex)
        else:
            self.statusBar().showMessage(self.statusBar().currentMessage() + f"   ({secs:.1f} s)")

    def job_failed(self, name, msg, cancelled):
        self.end_job()
        self.job_cancelled = cancelled
        if cancelled:
            self.statusBar().showMessage(f"{name} cancelled - the mesh is unchanged.")
            self.last_error = ""
        else:
            self.fail(name, msg)

    def wait_idle(self, timeout=120.0):
        """Tests: let the event loop run until the current job has finished."""
        t0 = time.time()
        while self.busy and time.time() - t0 < timeout:
            QApplication.processEvents()
            time.sleep(0.01)
        QApplication.processEvents()

