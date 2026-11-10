"""addons_dialog.py - File > Add-ons...: install, update and uninstall the optional parts of OpenPara."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QProgressDialog, QPushButton, QScrollArea, QVBoxLayout,
                             QWidget)

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
    """File > Add-ons: one row per add-on - what it is, what it puts into the program, its state - with Install / Update / Uninstall.
    An add-on that could not be loaded says so in red and shows the error on request.  The list scrolls, whatever its length."""
    def __init__(self, shell):
        super().__init__(shell)
        self.shell = shell
        self.setWindowTitle("Add-ons")
        self.resize(680, 560)
        self.box = QVBoxLayout(self)
        intro = QLabel("The core of OpenPara (parts, sketches, assemblies, STEP / STL exchange) is always there. These parts are optional: "
                       "install what you use (they are downloaded from GitHub, so this needs an internet connection), remove what you do not. "
                       "Your own files are never deleted.")
        intro.setWordWrap(True)
        self.box.addWidget(intro)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        self.rows = QVBoxLayout(inner)
        self.rows.setContentsMargins(0, 0, 6, 0)
        self.scroll.setWidget(inner)
        self.box.addWidget(self.scroll, 1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        self.box.addWidget(close)
        self.row_info = {}                      # add-on id -> {"text": label text, "buttons": [button texts]} (what the row shows)
        self.fill()

    @staticmethod
    def row_text(aid):
        """The rich text of one row: name, state, description, what it adds, and the load error line when there is one."""
        m = addons.info(aid)
        st = addons.status(aid)
        dev = addons.is_dev(aid)
        im = addons.installed_manifest(aid) or {}
        if dev:
            state = "Playground add-on (Full dev mode)" + (f", {im['status']}" if im.get("status") else "")
        else:
            state = {"installed": "installed", "update": "update available", "not installed": "not installed"}[st]
            if st != "not installed":
                state += f" (v{im.get('version', '?')})"
        text = f"<b>{m['name']}</b> &nbsp; <i>{state}</i><br>{m['description']}"
        adds = addons.adds(aid)
        if adds:
            text += "<br><span style='color:#4a5872'>Adds: " + "; ".join(adds) + ".</span>"
        if aid in addons.load_errors():
            text += "<br><span style='color:#b00020'><b>Could not be loaded</b> - it is switched off for now. Update or reinstall it; Details shows the error.</span>"
        return text

    def fill(self):
        while self.rows.count():
            it = self.rows.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.row_info = {}
        errs = addons.load_errors()
        for aid in addons.known():
            st = addons.status(aid)
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 6, 0, 6)
            text = QLabel(self.row_text(aid))
            text.setWordWrap(True)
            text.setTextFormat(Qt.TextFormat.RichText)
            h.addWidget(text, 1)
            col = QVBoxLayout()
            names = []

            def button(label, fn, col=col, names=names):
                b = QPushButton(label)
                b.clicked.connect(fn)
                col.addWidget(b)
                names.append(label)
            if not addons.is_dev(aid):                                     # a Playground add-on is used where it is: nothing to install or remove
                if st in ("not installed", "update"):
                    button("Install" if st == "not installed" else "Update", lambda _c=False, a=aid: self.do_install(a))
                if st != "not installed":
                    button("Uninstall", lambda _c=False, a=aid: self.do_uninstall(a))
            if aid in errs:
                button("Details...", lambda _c=False, a=aid: self.show_error(a))
            col.addStretch(1)
            h.addLayout(col)
            self.rows.addWidget(row)
            line = QFrame()
            line.setFrameShape(QFrame.Shape.HLine)
            line.setStyleSheet("color:#e1e6ef;")
            self.rows.addWidget(line)
            self.row_info[aid] = {"text": text.text(), "buttons": names}
        self.rows.addStretch(1)

    def show_error(self, aid):
        import gpd_app
        gpd_app.show_error_text(self, addons.load_errors().get(aid, ""), title="Add-ons",
                                head=f"'{addons.info(aid)['name']}' could not be loaded. This is the error:")

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
