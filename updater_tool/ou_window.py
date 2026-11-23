"""
ou_window.py - the window of the OpenPara Updater (PyQt6).  The logic is in ou_core.py; this file only shows it.

The window shows the build that is installed, the newest build on GitHub and the last 5 builds (a button shows all of them, back to the first).
Buttons:  Update to the newest | Install the selected build (an earlier one is "go back") | Repair (download this build again) | Start safely | Copy report.
Nothing goes back by itself: when a new build does not start properly the window says so and offers "Go back", the person presses it or not.
"""
import os
import sys
import time
import uuid

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton, QTableWidget,
                             QTableWidgetItem, QVBoxLayout, QWidget)

import ou_core as core


class Worker(QThread):
    """Runs fn(progress, cancelled) away from the window and reports back."""
    progress = pyqtSignal(str, float)
    done = pyqtSignal(object)
    failed = pyqtSignal(object)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn
        self.stop = False

    def run(self):
        try:
            self.done.emit(self.fn(lambda text, frac=None: self.progress.emit(str(text), -1.0 if frac is None else float(frac)), lambda: self.stop))
        except BaseException as ex:                              # noqa: BLE001 - whatever it was, the window shows it
            self.failed.emit(ex)


class UpdaterWindow(QWidget):
    SAFE_TIP = "Starts the program with every add-on switched off (and, in the Playground, in Testing mode), for this run only."

    def __init__(self, inst, update_to=None, install=None, wait_pid=None, auto_start=False):
        super().__init__()
        self.inst = inst
        self.update_to = update_to                    # a version the program asked for ("Update now" in OpenPara): installed as soon as the program has closed
        self.install_arg = install                    # a version to put in (command line)
        self.wait_pid = wait_pid
        self.auto_start = bool(auto_start or update_to)
        self.builds = []
        self.builds_error = None
        self.show_all = False
        self.worker = None
        self.busy = False
        self.program_open = False
        self.pending = update_to or install            # what is to be done once the program has closed and the builds are known
        self.setWindowTitle(f"{inst.name} Updater")
        self.resize(640, 520)
        lay = QVBoxLayout(self)
        self.head = QLabel()
        self.head.setStyleSheet("font-size:15px; font-weight:600;")
        lay.addWidget(self.head)
        self.info = QLabel()
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Build", "Date", ""])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 170)
        self.table.setColumnWidth(1, 110)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.update_buttons)
        lay.addWidget(self.table, 1)
        self.b_all = QPushButton()
        self.b_all.clicked.connect(self.toggle_all)
        lay.addWidget(self.b_all)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setVisible(False)
        lay.addWidget(self.bar)
        row = QHBoxLayout()
        self.b_update = QPushButton("Update to the newest")
        self.b_install = QPushButton("Install the selected build")
        self.b_repair = QPushButton("Repair (download this build again)")
        row.addWidget(self.b_update)
        row.addWidget(self.b_install)
        row.addWidget(self.b_repair)
        lay.addLayout(row)
        row2 = QHBoxLayout()
        self.b_safe = QPushButton("Start safely")
        self.b_report = QPushButton("Copy report")
        self.b_close = QPushButton("Close")
        row2.addWidget(self.b_safe)
        row2.addWidget(self.b_report)
        row2.addStretch(1)
        row2.addWidget(self.b_close)
        lay.addLayout(row2)
        self.b_update.clicked.connect(self.on_update)
        self.b_install.clicked.connect(self.on_install)
        self.b_repair.clicked.connect(self.on_repair)
        self.b_safe.clicked.connect(self.on_safe)
        self.b_report.clicked.connect(self.on_report)
        self.b_close.clicked.connect(self.close)
        self.poll = QTimer(self)
        self.poll.timeout.connect(self.check_program)
        self.poll.start(500)
        self.refresh_head()
        self.check_program()
        self.load_builds()

    # ------------------------------------------------------------------ small helpers (tests replace ask / tell)
    def ask(self, title, text, buttons):
        """-> the label of the button that was pressed (the first button is the default; Escape gives the last one)."""
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(text)
        made = [box.addButton(b, QMessageBox.ButtonRole.AcceptRole if i == 0 else QMessageBox.ButtonRole.RejectRole) for i, b in enumerate(buttons)]
        box.setDefaultButton(made[0])
        box.setEscapeButton(made[-1])
        box.exec()
        c = box.clickedButton()
        return buttons[made.index(c)] if c in made else buttons[-1]

    def tell(self, title, text):
        self.ask(title, text, ["OK"])

    def say(self, text):
        self.status.setText(text)
        core.log_line(self.inst, text)

    def set_busy(self, on):
        self.busy = on
        self.bar.setVisible(on)
        self.update_buttons()

    def run_worker(self, fn, done, failed=None, label=""):
        self.set_busy(True)
        self.bar.setValue(0)
        w = Worker(fn, self)
        self.worker = w

        def prog(text, frac):
            if text:
                self.status.setText(text)
            if frac >= 0:
                self.bar.setRange(0, 1000)
                self.bar.setValue(int(frac * 1000))
            else:
                self.bar.setRange(0, 0)

        def fin(res):
            self.set_busy(False)
            self.worker = None
            done(res)

        def bad(ex):
            self.set_busy(False)
            self.worker = None
            (failed or self.show_failure)(ex)
        w.progress.connect(prog)
        w.done.connect(fin)
        w.failed.connect(bad)
        w.finished.connect(w.deleteLater)
        w.start()

    def show_failure(self, ex):
        if isinstance(ex, core.Cancelled):
            self.say("Cancelled.")
            return
        text = str(ex) if isinstance(ex, core.UpdaterError) else f"{type(ex).__name__}: {ex}"
        self.say(text)
        core.log_line(self.inst, "FAILED: " + text)
        self.tell("Updater", text + "\n\nNothing was changed unless the text says so.")

    # ------------------------------------------------------------------ what is shown
    def refresh_head(self):
        cur = self.inst.info_of(self.inst.app)
        self.head.setText(f"{self.inst.name} Updater")
        newest = self.builds[0]["version"] if self.builds else None
        saved = self.inst.saved_version()
        lines = [f"Installed: {cur['version'] or 'cannot be read (the program folder is damaged?)'}"]
        if newest:
            lines.append(f"Newest on GitHub: {newest}")
        elif self.builds_error:
            lines.append(self.builds_error)
        if saved:
            lines.append(f"A saved copy of the earlier program ({saved}) is on this computer.")
        self.info.setText("\n".join(lines))

    def fill_table(self):
        cur = self.inst.version
        saved = self.inst.saved_version()
        rows = self.builds if self.show_all else self.builds[:core.SHOW_FIRST]
        self.table.setRowCount(len(rows))
        for r, b in enumerate(rows):
            note = []
            if b is self.builds[0]:
                note.append("newest")
            if b["version"] == cur:
                note.append("installed")
            if saved and b["version"] == saved:
                note.append("saved copy here")
            for c, text in enumerate((b["version"], b["date"], ", ".join(note))):
                it = QTableWidgetItem(text)
                it.setData(Qt.ItemDataRole.UserRole, b["version"])
                self.table.setItem(r, c, it)
        n = len(self.builds)
        self.b_all.setVisible(n > core.SHOW_FIRST)
        self.b_all.setText("Show only the last %d builds" % core.SHOW_FIRST if self.show_all else f"Show all {n} builds")
        if rows and self.table.currentRow() < 0:
            self.table.selectRow(0)
        self.update_buttons()

    def toggle_all(self):
        self.show_all = not self.show_all
        self.fill_table()

    def selected_build(self):
        r = self.table.currentRow()
        it = self.table.item(r, 0) if r >= 0 else None
        if it is None:
            return None
        v = it.data(Qt.ItemDataRole.UserRole)
        return next((b for b in self.builds if b["version"] == v), None)

    def build_of(self, version):
        return next((b for b in self.builds if b["version"] == str(version)), None)

    def update_buttons(self):
        free = not self.busy and not self.program_open
        cur = self.inst.version
        newest = self.builds[0] if self.builds else None
        sel = self.selected_build()
        self.b_update.setEnabled(free and newest is not None and cur != newest["version"] and (cur is None or core.vkey(newest["version"]) > core.vkey(cur)))
        self.b_install.setEnabled(free and sel is not None and sel["version"] != cur)
        self.b_repair.setEnabled(free and (self.build_of(cur) is not None))
        can_safe = core.supports_safe_start(self.inst)
        self.b_safe.setEnabled(free and os.path.isfile(os.path.join(self.inst.app, "gpd_app.py")) and can_safe)
        self.b_safe.setToolTip(self.SAFE_TIP if can_safe else self.SAFE_TIP + "\n\nThis build is older than the safe start, so the button is off.")
        self.b_report.setEnabled(True)
        if sel is not None and cur is not None and sel["version"] != cur:
            older = core.vkey(sel["version"]) < core.vkey(cur)
            self.b_install.setText(("Go back to " if older else "Install ") + sel["version"])
        else:
            self.b_install.setText("Install the selected build")

    def check_program(self):
        """The program must be closed while its files are replaced."""
        running = core.program_running(self.inst) or (self.wait_pid is not None and core.pid_alive(self.wait_pid))
        if running != self.program_open:
            self.program_open = running
            self.update_buttons()
            self.refresh_wait_status()
            if not running:
                self.maybe_start_pending()
        elif not running and self.pending and not self.busy:
            self.maybe_start_pending()

    def refresh_wait_status(self):
        """While the program is open the buttons wait; the line under the list says why (it never replaces a message about work that is under way)."""
        if self.busy:
            return
        if self.program_open:
            self.status.setText(f"Waiting for {self.inst.name} to close (save your work in it and close it; the buttons here work after that).")
        elif self.status.text().startswith("Waiting for"):
            self.status.setText("")

    # ------------------------------------------------------------------ the list of builds
    def load_builds(self):
        def work(progress, cancelled):
            progress("Asking GitHub for the list of builds...", None)
            return core.list_builds(self.inst)

        def done(builds):
            self.builds, self.builds_error = builds, None
            if not builds:
                self.builds_error = "GitHub has no builds of this program."
            self.refresh_head()
            self.fill_table()
            self.status.setText("")
            self.refresh_wait_status()
            self.maybe_start_pending()

        def bad(ex):
            self.builds, self.builds_error = [], str(ex)
            self.refresh_head()
            self.fill_table()
            self.say(str(ex))
            self.pending = None
        self.run_worker(work, done, bad)

    def maybe_start_pending(self):
        """The program asked for an update ("Update now" in it): once it has closed and the builds are known, it is installed."""
        if not self.pending or self.busy or self.program_open or not self.builds:
            return
        v, self.pending = self.pending, None
        b = self.build_of(v)
        if b is None:
            self.tell("Updater", f"Build {v} was not found on GitHub.")
            return
        cur = self.inst.version
        older = cur is not None and core.vkey(v) < core.vkey(cur)
        self.start_install(b, restore_addons=older, then_start=True)

    # ------------------------------------------------------------------ the buttons
    def on_update(self):
        if self.builds:
            self.confirm_and_install(self.builds[0])

    def on_install(self):
        b = self.selected_build()
        if b is not None:
            self.confirm_and_install(b)

    def on_repair(self):
        b = self.build_of(self.inst.version)
        if b is not None:
            self.confirm_and_install(b, repair=True)

    def confirm_and_install(self, b, repair=False):
        cur = self.inst.version
        v = b["version"]
        older = cur is not None and core.vkey(v) < core.vkey(cur)
        same = cur == v
        if repair or same:
            text = (f"Repair {self.inst.name} {v}?\n\nThe program files are downloaded again from GitHub and replaced, and the add-ons you have installed are set "
                    "back to the ones of this build. Your settings and projects are not touched.")
            go = "Repair"
        elif older:
            text = (f"Go back from {cur} to the earlier build {v} ({b['date']})?\n\nThe program files are replaced by that build's, and the add-ons you have installed "
                    "are set back to the ones of that build so they match it. Your settings and projects are not touched. Documents saved by a newer build may "
                    "not open in an older one.")
            go = "Go back"
        else:
            text = f"Install {v} ({b['date']}) over {cur or 'the damaged program'}?\n\nYour settings and projects are not touched."
            go = "Install"
        text += f"\n\nThe program you have now is kept as a saved copy until the new one has started fine."
        if self.ask("Updater", text, [go, "Cancel"]) != go:
            return
        self.start_install(b, restore_addons=older or repair or same, then_start=None)

    def start_install(self, b, restore_addons, then_start):
        inst = self.inst
        self.say(f"Installing {b['version']}...")
        core.log_line(inst, f"install {b['version']} (was {inst.version}), add-ons restored: {restore_addons}")

        def work(progress, cancelled):
            return core.install_build(inst, b, restore_addons_too=restore_addons, progress=progress, cancel=cancelled, log=lambda t: core.log_line(inst, t))

        def done(res):
            self.refresh_head()
            self.fill_table()
            self.installed(b, res, then_start)

        def bad(ex):
            if isinstance(ex, core.NeedsInstaller):
                self.offer_installer(b, str(ex))
            else:
                self.show_failure(ex)
        self.run_worker(work, done, bad)

    def installed(self, b, res, then_start):
        how = "put back from the saved copy" if res.get("saved") else "installed"
        msg = f"{self.inst.name} {b['version']} is {how}."
        ad = res.get("addons")
        if ad:
            if ad["restored"]:
                msg += " Add-ons set back: " + ", ".join(ad["restored"]) + "."
            if ad["failed"]:
                msg += " Add-ons that could not be set back: " + ", ".join(ad["failed"]) + " (the program offers to update them)."
            if ad["skipped"]:
                msg += " Add-ons this build has no copy of, left as they are: " + ", ".join(ad["skipped"]) + " (if one does not work with it, switch it off in File > Add-ons)."
        self.say(msg)
        start = then_start                                  # True: start it; False: not; None: ask
        if start is None:
            start = self.ask("Updater", msg + f"\n\nStart {self.inst.name} now?", ["Start", "Not now"]) == "Start"
        if start:
            self.start_program(safe=False)

    def offer_installer(self, b, why):
        if not b.get("setup"):
            self.tell("Updater", why + "\n\nThis build has no full installer on GitHub any more, so it cannot be put in here.")
            return
        mb = (b["setup"].get("size") or 0) / 1e6
        if self.ask("Updater", why + f"\n\nDownload the full installer ({mb:.0f} MB) and start it? This window closes first.", ["Download and start", "Cancel"]) != "Download and start":
            return
        inst = self.inst

        def work(progress, cancelled):
            return core.download_installer(inst, b, progress=lambda d, t: progress("Downloading the installer...", (d / t) if t else None), cancel=cancelled)

        def done(path):
            import subprocess
            core.log_line(inst, f"starting the installer {path}")
            subprocess.Popen([path], cwd=os.path.dirname(path), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.close()
        self.run_worker(work, done)

    # ------------------------------------------------------------------ starting the program and watching it
    def start_program(self, safe):
        inst = self.inst
        token = uuid.uuid4().hex
        try:
            proc = core.launch(inst, token=token, safe=safe)
        except OSError as ex:
            self.show_failure(core.UpdaterError(f"The program could not be started ({ex})."))
            return
        core.log_line(inst, f"started the program (safe={safe}, pid {proc.pid})")
        self.say(f"Starting {inst.name}...")

        def work(progress, cancelled):
            progress(f"Starting {inst.name} and waiting for it to come up...", None)
            return core.wait_started(inst, proc, token, timeout=float(os.environ.get("OPARA_UPDATER_WAIT", "120")), cancel=cancelled)

        def done(res):
            outcome, secs, detail = res
            core.log_line(inst, f"start result: {outcome} after {secs:.1f}s {detail}")
            if outcome == "ok":
                self.say(f"{inst.name} {inst.version} started fine. Close it before changing anything here.")
                core.discard_saved_copy(inst)                # the safety copy has done its job
                self.refresh_head()
                self.fill_table()
                if self.auto_start:
                    QTimer.singleShot(1500, self.close)
                return
            if outcome == "running":                                 # an old build cannot report back: no verdict either way; the safety copy stays
                self.say(f"{inst.name} {inst.version} is running. {detail}")
                self.refresh_head()
                self.fill_table()
                return
            if outcome == "cancelled":
                return
            self.did_not_start(detail, safe)
        self.run_worker(work, done)

    def did_not_start(self, detail, safe):
        inst = self.inst
        saved = inst.saved_version()
        prev = self.build_of(saved) if saved else None
        text = f"{inst.name} {inst.version} did not start properly. {detail}\n\nNothing was changed back."
        buttons = []
        if saved:
            buttons.append(f"Go back to {saved}")
        if not safe and core.supports_safe_start(inst):
            buttons.append("Start safely")
        buttons += ["Copy report", "Close"]
        while True:
            c = self.ask("Updater", text, buttons)
            if c.startswith("Go back to "):
                b = prev or {"version": saved, "date": "", "app": None, "setup": None, "addons": {}}
                self.start_install(b, restore_addons=True, then_start=True)
                return
            if c == "Start safely":
                self.start_program(safe=True)
                return
            if c == "Copy report":
                self.on_report()
                continue
            return

    def on_safe(self):
        self.start_program(safe=True)

    def on_report(self):
        text = core.report_text(self.inst, self.builds_error)
        QGuiApplication.clipboard().setText(text)
        self.status.setText("The report is copied - paste it into your message.")

    def closeEvent(self, ev):
        if self.worker is not None and self.worker.isRunning():
            self.worker.stop = True
            self.worker.wait(3000)
        ev.accept()


def run(inst, update_to=None, install=None, wait_pid=None, auto_start=False):
    app = QApplication.instance() or QApplication(sys.argv)
    ico = os.path.join(inst.app, "OpenPara.ico")
    if os.path.isfile(ico):
        from PyQt6.QtGui import QIcon
        app.setWindowIcon(QIcon(ico))
    w = UpdaterWindow(inst, update_to=update_to, install=install, wait_pid=wait_pid, auto_start=auto_start)
    w.show()
    return app.exec()
