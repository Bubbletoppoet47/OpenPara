"""
update_ui.py - the Help menu entries and the dialogs of the updater (the logic is in updater.py).
"""
import json
import os
import subprocess
import sys
import tempfile
import time

from PyQt6.QtCore import QObject, Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QApplication, QMessageBox, QProgressDialog

import paths
import updater
import version


def _state_path():
    return os.path.join(paths.user_dir(), "update_state.json")


def load_state():
    try:
        with open(_state_path(), "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def save_state(st):
    try:
        with open(_state_path(), "w", encoding="utf-8") as fh:
            json.dump(st, fh)
    except OSError:
        pass


class CheckThread(QThread):
    got = pyqtSignal(object)

    def run(self):
        self.got.emit(updater.fetch_latest())


class DownloadThread(QThread):
    progress = pyqtSignal(int, int)
    done = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, asset, dest, parent=None):
        super().__init__(parent)
        self.asset, self.dest, self.cancel = asset, dest, False

    def run(self):
        try:
            updater.download(self.asset, self.dest, progress=lambda d, t: (self.progress.emit(d, t), not self.cancel)[1])
            self.done.emit(self.dest)
        except InterruptedError:
            self.failed.emit("")
        except Exception as ex:
            self.failed.emit(str(ex))


class UpdateController(QObject):
    """Owned by the main window: check_later() at start-up (at most once a day), check_now() from Help."""

    def __init__(self, shell):
        super().__init__(shell)
        self.shell = shell
        self.thread = None
        self.dl = None
        self.manual = False

    # ---- settings
    def auto_enabled(self):
        return load_state().get("auto", True)

    def set_auto(self, on):
        st = load_state()
        st["auto"] = bool(on)
        save_state(st)

    def check_later(self, ms=4000):
        """At every start-up (unless switched off in Help): look for a newer version a few seconds after the window opened."""
        if self.auto_enabled():
            QTimer.singleShot(ms, lambda: self.check(False))

    def check_now(self):
        self.check(True)

    def check(self, manual):
        if self.thread is not None and self.thread.isRunning():
            return
        self.manual = manual
        self.thread = CheckThread(self)
        self.thread.got.connect(self.checked)
        self.thread.start()

    # ---- result of the check
    def checked(self, rel):
        st = load_state()
        st["last"] = time.time()
        save_state(st)
        if rel is None:
            if not self.manual:
                try:
                    self.shell.statusBar().showMessage("Could not check for updates (no internet connection?).", 8000)
                except Exception:
                    pass
            if self.manual:
                QMessageBox.information(self.shell, "Updates", "Could not reach GitHub to look for updates (no internet, or the project is private "
                                        "and no access token is set).")
            return
        if not updater.is_newer(rel["version"]):
            if self.manual:
                QMessageBox.information(self.shell, "Updates", f"OpenPara {version.__version__} is the newest version.")
            return
        if not self.manual and st.get("skip") == rel["version"]:
            return
        self.offer(rel)

    def offer(self, rel):
        box = QMessageBox(self.shell)
        box.setWindowTitle("Update available")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(f"OpenPara {rel['version']} is available (you have {version.__version__}).\n\nUpdate now?")
        notes = (rel.get("notes") or "").strip()
        if notes:
            box.setDetailedText(notes)
        lay = updater.installed_layout()
        can_app = lay is not None and rel.get("app") is not None
        b_inst = box.addButton("Update now", QMessageBox.ButtonRole.AcceptRole) if can_app else None
        b_page = box.addButton("Open download page", QMessageBox.ButtonRole.ActionRole)
        b_skip = box.addButton("Skip this version", QMessageBox.ButtonRole.RejectRole)
        box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        if lay is None:
            box.setInformativeText("This copy was not installed with the installer (it runs from source), so it cannot update itself.")
        box.exec()
        c = box.clickedButton()
        if c is b_inst:
            self.install(rel)
        elif c is b_page:
            QDesktopServices.openUrl(QUrl(rel.get("page") or updater.RELEASES_PAGE))
        elif c is b_skip:
            st = load_state()
            st["skip"] = rel["version"]
            save_state(st)

    # ---- download + install
    def install(self, rel):
        dest = os.path.join(tempfile.mkdtemp(prefix="opara_update_"), rel["app"]["name"])
        dlg = QProgressDialog("Downloading the update...", "Cancel", 0, 100, self.shell)
        dlg.setWindowTitle("Update")
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(0)
        t = DownloadThread(rel["app"], dest, self)
        self.dl = t

        def prog(d, tot):
            dlg.setValue(int(100 * d / tot) if tot else 0)
        t.progress.connect(prog)
        dlg.canceled.connect(lambda: setattr(t, "cancel", True))
        t.done.connect(lambda p: (dlg.close(), self.apply(p, rel)))
        t.failed.connect(lambda m: (dlg.close(), QMessageBox.warning(self.shell, "Update", f"The download failed: {m}") if m else None))
        t.start()

    def apply(self, zip_path, rel):
        lay = updater.installed_layout()
        try:
            info = updater.zip_info(zip_path)
            if int(info.get("runtime", 0)) != int(version.RUNTIME):
                QMessageBox.information(self.shell, "Update", "This version needs a newer base package, which only the full installer contains.\n"
                                        "The download page opens now.")
                QDesktopServices.openUrl(QUrl(rel.get("page") or updater.RELEASES_PAGE))
                return
            updater.install_app_zip(zip_path, lay[1])
        except Exception as ex:
            QMessageBox.warning(self.shell, "Update", f"The update could not be installed: {ex}\nYour current version is unchanged.")
            return
        r = QMessageBox.question(self.shell, "Update", f"OpenPara {rel['version']} is installed.\nRestart now? (open documents are asked about first)",
                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if r == QMessageBox.StandardButton.Yes:
            self.shell.close()
            if not self.shell.isVisible():
                subprocess.Popen(updater.restart_command(), cwd=lay[0])
                QApplication.quit()

    def about(self):
        QMessageBox.about(self.shell, "About OpenPara",
                          f"<b>OpenPara</b> {version.__version__}<br>An open-source parametric CAD modeller.<br><br>"
                          f"Licence: GNU GPL v3<br><a href='https://github.com/{updater.REPO}'>github.com/{updater.REPO}</a>")
