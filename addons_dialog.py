"""addons_dialog.py - File > Add-ons...: install, update and uninstall the optional parts of OpenPara."""
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

import addons


class AddonsDialog(QDialog):
    def __init__(self, shell):
        super().__init__(shell)
        self.shell = shell
        self.setWindowTitle("Add-ons")
        self.resize(560, 100)
        self.box = QVBoxLayout(self)
        intro = QLabel("The core of OpenPara (parts, sketches, assemblies, STEP / STL exchange) is always there. These parts are optional: "
                       "install what you use, remove what you do not. Your own files are never deleted.")
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
        for aid, m in addons.shipped().items():
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
        try:
            addons.install(aid)
        except Exception as ex:
            QMessageBox.warning(self, "Add-ons", f"Could not install: {ex}")
        self.shell.addons_changed()
        self.fill()

    def do_uninstall(self, aid):
        name = addons.shipped().get(aid, {"name": aid})["name"]
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
