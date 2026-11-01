"""addons_dialog.py - File > Add-ons...: install, update and uninstall the optional parts of OpenPara."""
from PyQt6.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QMessageBox, QProgressDialog, QPushButton, QVBoxLayout, QWidget

import addons


def install_with_progress(parent, aid):
    """Install / update an add-on with a progress window that can be cancelled. True when it is installed afterwards."""
    name = addons.info(aid)["name"]
    dlg = QProgressDialog(f"Installing '{name}' ...", "Cancel", 0, 0, parent)
    dlg.setWindowTitle("Add-ons")
    dlg.setMinimumDuration(0)
    dlg.setMinimumWidth(420)
    dlg.setAutoClose(False)
    dlg.setAutoReset(False)
    dlg.show()

    def progress(text, frac):
        dlg.setLabelText(f"Installing '{name}'\n{text}")
        if frac is None:
            dlg.setRange(0, 0)
        else:
            dlg.setRange(0, 1000)
            dlg.setValue(int(frac * 1000))
        QApplication.processEvents()
        return not dlg.wasCanceled()
    try:
        addons.install(aid, progress=progress)
        return True
    except addons.Cancelled:
        return False
    except Exception as ex:
        QMessageBox.warning(parent, "Add-ons", f"Could not install '{name}':\n\n{ex}")
        return False
    finally:
        dlg.close()


class AddonsDialog(QDialog):
    def __init__(self, shell):
        super().__init__(shell)
        self.shell = shell
        self.setWindowTitle("Add-ons")
        self.resize(560, 100)
        self.box = QVBoxLayout(self)
        intro = QLabel("The core of OpenPara (parts, sketches, assemblies, STEP / STL exchange) is always there. These parts are optional: "
                       "install what you use (they are downloaded from GitHub, so this needs an internet connection), remove what you do not. "
                       "Your own files are never deleted.")
        intro.setWordWrap(True)
        self.box.addWidget(intro)
        self.rows = QVBoxLayout()
        self.box.addLayout(self.rows)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        self.box.addWidget(close)
        self.fill()

    def fill(self):
        while self.rows.count():
            it = self.rows.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for aid in addons.known():
            m = addons.info(aid)
            st = addons.status(aid)
            row = QWidget()
            h = QHBoxLayout(row)
            text = QLabel(f"<b>{m['name']}</b> &nbsp; <i>{ {'installed': 'installed', 'update': 'update available', 'not installed': 'not installed'}[st] }"
                          f"{' (v' + addons.installed_manifest(aid)['version'] + ')' if st != 'not installed' else ''}</i><br>{m['description']}")
            text.setWordWrap(True)
            h.addWidget(text, 1)
            if st in ("not installed", "update"):
                b = QPushButton("Install" if st == "not installed" else "Update")
                b.clicked.connect(lambda _c=False, a=aid: self.do_install(a))
                h.addWidget(b)
            if st != "not installed":
                u = QPushButton("Uninstall")
                u.clicked.connect(lambda _c=False, a=aid: self.do_uninstall(a))
                h.addWidget(u)
            self.rows.addWidget(row)

    def do_install(self, aid):
        install_with_progress(self, aid)
        self.shell.addons_changed()
        self.fill()

    def do_uninstall(self, aid):
        name = addons.info(aid)["name"]
        tabs = self.shell.addon_tabs(aid)
        extra = f"\n\nThe {len(tabs)} open tab(s) that belong to it will be closed (you are asked about unsaved changes)." if tabs else ""
        if QMessageBox.question(self, "Uninstall", f"Uninstall '{name}'?{extra}\n\nYour saved files stay as they are; you can install it again any time.") != QMessageBox.StandardButton.Yes:
            return
        if not self.shell.close_addon_tabs(aid):
            return
        if not addons.uninstall(aid):
            QMessageBox.information(self, "Add-ons", "Some files are still in use. They are removed the next time OpenPara starts.")
        self.shell.addons_changed()
        self.fill()
