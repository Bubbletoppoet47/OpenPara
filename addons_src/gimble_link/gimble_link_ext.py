"""gimble_link_ext.py - File > Gimble ... in the Annotator: send a trained model to the Gimble rig's Raspberry Pi, download its recordings,
see its status.  Everything goes through the Remote helper on the Pi (the Remote Computer add-on); the Gimble's own programs are untouched.
Playground only for now (addons.NOT_RELEASED)."""
import os
import tempfile
import threading
import time

PAGES = {"status": 0, "model": 1, "recordings": 2}


def _missing(win, what):
    from PyQt6.QtWidgets import QMessageBox
    QMessageBox.information(win, "Gimble", f"This needs the {what} add-on. Install it in File > Add-ons (in the program window), then try again.")


def open_dialog(win, page="status"):
    try:
        import remote_link  # noqa: F401
    except ImportError:
        _missing(win, "Remote Computer")
        return None
    dlg = getattr(win, "_gimble_dialog", None)
    if dlg is None:
        dlg = win._gimble_dialog = make_dialog(win)
    dlg.pages.setCurrentIndex(PAGES.get(page, 0))
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    dlg.opened()
    return dlg


def make_dialog(win):
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import (QComboBox, QDialog, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QProgressBar,
                                 QPushButton, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)
    import gimble_core as GC
    import remote_link as RL
    import remote_tab as RT
    import ui_kit

    class GimbleDialog(QDialog):
        def __init__(self):
            super().__init__(win)
            self.setWindowTitle("Gimble")
            self.resize(760, 560)
            self.link = None
            self.folder = None
            self.busy = None                    # {"stop": bool} while something long runs
            self.connecting = False
            self.found = []
            self.poster = RT.Poster()
            self.models, self.sess = [], []
            self.extra_models = []              # model files added with Choose a file (not in a Models folder)
            self.st = None                      # the Gimble's last status
            self._build()
            self.fill_computers()
            self.fill_models()
            self.update_ui()

        # ---------------------------------------------------------------- layout
        def _build(self):
            lay = QVBoxLayout(self)
            row = QHBoxLayout()
            row.addWidget(QLabel("Gimble computer:"))
            self.combo = QComboBox()
            self.combo.setMinimumWidth(260)
            row.addWidget(self.combo, 1)
            self.find_btn = QPushButton("Search network")
            self.find_btn.clicked.connect(self.search)
            self.addr_btn = QPushButton("Add by address...")
            self.addr_btn.clicked.connect(self.add_by_address)
            self.conn_btn = ui_kit.primary(QPushButton("Connect"))
            self.conn_btn.clicked.connect(self.toggle_connect)
            for b in (self.find_btn, self.addr_btn, self.conn_btn):
                row.addWidget(b)
            lay.addLayout(row)
            self.state = ui_kit.StatusLine("Not connected.")
            lay.addWidget(self.state)
            self.pages = QTabWidget()
            lay.addWidget(self.pages, 1)

            # ---- status
            sp = QWidget()
            sl = QVBoxLayout(sp)
            self.status_lbl = QLabel("")
            self.status_lbl.setWordWrap(True)
            self.status_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            sl.addWidget(self.status_lbl, 1)
            sl.addWidget(ui_kit.note("The Pi has to be on, on the same Wi-Fi or hotspot as this PC, with the Remote helper running "
                                     "(the Remote Computer tab has 'Get the helper'). The thumb drive stays in the Pi."))
            row = QHBoxLayout()
            self.refresh_btn = QPushButton("Refresh")
            self.refresh_btn.clicked.connect(self.refresh_status)
            row.addWidget(self.refresh_btn)
            self.programs_btn = QPushButton("Update the Gimble's programs...")
            self.programs_btn.setToolTip("Sends the Gimble programs this OpenPara carries (start screen, Record data, Test model with video "
                                         "recording ...) to the Gimble. Settings, calibration, the model and everything recorded stay as they are.")
            self.programs_btn.clicked.connect(self.update_programs)
            row.addWidget(self.programs_btn)
            row.addStretch(1)
            sl.addLayout(row)
            self.pages.addTab(sp, "Status")

            # ---- send a model
            mp = QWidget()
            ml = QVBoxLayout(mp)
            self.model_tree = QTreeWidget()
            self.model_tree.setHeaderLabels(["Model", "Kind", "Classes", "From", "File"])
            self.model_tree.setRootIsDecorated(False)
            self.model_tree.setColumnWidth(0, 170)
            self.model_tree.setColumnWidth(1, 165)
            self.model_tree.setColumnWidth(2, 110)
            self.model_tree.setColumnWidth(3, 130)
            self.model_tree.itemSelectionChanged.connect(self.update_ui)
            self.model_tree.setAcceptDrops(True)                     # a .pt dropped on the list is added to it, like Choose a file
            self.model_tree.viewport().setAcceptDrops(True)
            self.model_tree.dragEnterEvent = self.model_tree.dragMoveEvent = self._drag_models
            self.model_tree.dropEvent = self._drop_models
            ml.addWidget(self.model_tree, 1)
            ml.addWidget(ui_kit.note("The trained models on this PC, newest first: from OpenPara's and the Playground's Models folders, and "
                                     "any .pt you add with Choose a file or drop on this list. Sending converts the model to the form the "
                                     "Gimble runs; a .pt copied to the Gimble by hand cannot run there. A Classes + boxes + distance model "
                                     "(a detector and a distance model) becomes one file on the Gimble and shows its own distance; a "
                                     "Classes + boxes model shows the LiDAR distance only. The model that was on the Gimble is kept one "
                                     "step back. Start Test model again on the Gimble to use the new one."))
            row = QHBoxLayout()
            self.send_btn = ui_kit.primary(QPushButton("Send to the Gimble"))
            self.send_btn.clicked.connect(self.send_model)
            self.back_btn = QPushButton("Put the previous model back")
            self.back_btn.clicked.connect(self.restore_previous)
            self.start_btn = QPushButton("Start Test model on the Gimble")
            self.start_btn.setToolTip("Starts the Test model program on the Gimble's own screen (as its TEST MODEL button does).")
            self.start_btn.clicked.connect(self.start_test)
            self.file_btn = QPushButton("Choose a file...")
            self.file_btn.setToolTip("Any trained model file (.pt) on this PC, wherever it is.")
            self.file_btn.clicked.connect(self.choose_model)
            self.reload_btn = QPushButton("Refresh list")
            self.reload_btn.clicked.connect(self.fill_models)
            row.addWidget(self.send_btn)
            row.addWidget(self.back_btn)
            row.addWidget(self.start_btn)
            row.addStretch(1)
            row.addWidget(self.file_btn)
            row.addWidget(self.reload_btn)
            ml.addLayout(row)
            self.pages.addTab(mp, "Send a model")

            # ---- recordings
            rp = QWidget()
            rl = QVBoxLayout(rp)
            self.sess_tree = QTreeWidget()
            self.sess_tree.setHeaderLabels(["Recording on the Gimble", "On this PC"])
            self.sess_tree.setRootIsDecorated(False)
            self.sess_tree.setColumnWidth(0, 300)
            self.sess_tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
            self.sess_tree.itemSelectionChanged.connect(self.update_ui)
            rl.addWidget(self.sess_tree, 1)
            row = QHBoxLayout()
            row.addWidget(QLabel("Save to:"))
            self.dest_edit = QLineEdit(GC.load_settings().get("recordings") or os.path.join(os.path.expanduser("~"), "Gimble recordings"))
            self.dest_edit.editingFinished.connect(self.fill_sessions)
            row.addWidget(self.dest_edit, 1)
            b = QPushButton("Choose...")
            b.clicked.connect(self.choose_dest)
            row.addWidget(b)
            rl.addLayout(row)
            row = QHBoxLayout()
            self.get_btn = ui_kit.primary(QPushButton("Download"))
            self.get_btn.setToolTip("The selected recordings, or all that are not on this PC yet when none is selected.")
            self.get_btn.clicked.connect(self.download)
            self.import_btn = QPushButton("Import into this project...")
            self.import_btn.setToolTip("Opens Import Gimble Session with the folder above.")
            self.import_btn.clicked.connect(self.import_now)
            self.videos_btn = QPushButton("Download test videos")
            self.videos_btn.setToolTip("The videos recorded in Test model (REC VIDEO), with their tables of predictions, into "
                                       "test_videos in the folder above. What is already here is left alone.")
            self.videos_btn.clicked.connect(self.download_videos)
            row.addWidget(self.get_btn)
            row.addWidget(self.import_btn)
            row.addStretch(1)
            row.addWidget(self.videos_btn)
            rl.addLayout(row)
            self.pages.addTab(rp, "Recordings")

            row = QHBoxLayout()
            self.job_lbl = QLabel("")
            self.job_bar = QProgressBar()
            self.job_bar.setRange(0, 1000)
            self.stop_btn = QPushButton("Stop")
            self.stop_btn.clicked.connect(self.stop)
            row.addWidget(self.job_lbl, 2)
            row.addWidget(self.job_bar, 1)
            row.addWidget(self.stop_btn)
            self.job_row = QWidget()
            self.job_row.setLayout(row)
            row.setContentsMargins(0, 0, 0, 0)
            lay.addWidget(self.job_row)
            row = QHBoxLayout()
            row.addStretch(1)
            close = QPushButton("Close")
            close.clicked.connect(self.close)
            row.addWidget(close)
            lay.addLayout(row)

        def say(self, text, level=""):
            self.state.say(text, level)

        def connected(self):
            return self.link is not None and not self.link.closed and self.folder is not None

        def update_ui(self):
            on, idle = self.connected(), self.busy is None
            self.conn_btn.setText("Disconnect" if self.link is not None and not self.link.closed else ("Connecting..." if self.connecting else "Connect"))
            self.conn_btn.setEnabled((idle and not self.connecting) and (self.link is not None or self.combo.count() > 0))
            for b in (self.find_btn, self.addr_btn):
                b.setEnabled(self.link is None and not self.connecting)
            self.combo.setEnabled(self.link is None and not self.connecting)
            self.refresh_btn.setEnabled(on and idle)
            self.send_btn.setEnabled(on and idle and bool(self.model_tree.selectedItems()))
            self.back_btn.setEnabled(on and idle)
            self.start_btn.setEnabled(on and idle)
            self.file_btn.setEnabled(idle)
            self.programs_btn.setEnabled(on and idle)
            self.videos_btn.setEnabled(on and idle)
            self.get_btn.setEnabled(on and idle and bool(self.sess))
            self.import_btn.setEnabled(idle)
            self.job_row.setVisible(not idle)

        # ---------------------------------------------------------------- the computer
        def fill_computers(self):
            last = GC.load_settings().get("computer") or {}
            self.combo.clear()
            seen = set()
            for c in RL.load_computers() + self.found:
                key = (c["host"], int(c.get("port", RL.PORT)))
                if key in seen:
                    continue
                seen.add(key)
                self.combo.addItem(f"{c.get('name') or c['host']}   ({c['host']})", c)
                if key == (last.get("host"), int(last.get("port", RL.PORT))):
                    self.combo.setCurrentIndex(self.combo.count() - 1)

        def search(self):
            self.say("Searching this network ...")
            self.find_btn.setEnabled(False)

            def work():
                found = RL.discover(1.8)
                self.poster.post(lambda: self.search_done(found))
            threading.Thread(target=work, daemon=True).start()

        def search_done(self, found):
            self.found = found
            self.fill_computers()
            self.update_ui()
            self.say(f"Found {len(found)} computer(s) with the helper running." if found else
                     "No helper answered. Is the Pi on, with the helper running, on the same Wi-Fi or hotspot? Or use Add by address.",
                     "" if found else "warn")

        def add_by_address(self):
            text, ok = QInputDialog.getText(self, "Gimble computer", "The Pi's address or name on the network\n(for example 192.168.1.42 or raspberrypi.local):")
            if ok and text.strip():
                RL.remember(text.strip(), text.strip())
                self.fill_computers()
                self.combo.setCurrentIndex(max(0, self.combo.findText(text.strip(), Qt.MatchFlag.MatchContains)))
                self.update_ui()

        def opened(self):
            """Shown (again): connect by itself when the Gimble was used before and its code is remembered."""
            self.fill_sessions()
            c = self.combo.currentData()
            last = GC.load_settings().get("computer") or {}
            if self.link is None and not self.connecting and c and c.get("code") and c["host"] == last.get("host"):
                self.start_connect(c, c["code"], True)

        def toggle_connect(self):
            if self.link is not None:
                self.disconnect_now()
                self.say("Disconnected.")
                return
            c = self.combo.currentData()
            if not c:
                return
            code, keep = c.get("code"), bool(c.get("code"))
            if not code:
                d = RT.CodeDialog(self, c.get("name") or c["host"])
                if d.exec() != QDialog.DialogCode.Accepted or not d.edit.text().strip():
                    return
                code, keep = d.edit.text().strip(), d.keep.isChecked()
            self.start_connect(c, code, keep)

        def start_connect(self, c, code, keep):
            self.connecting = True
            self.say(f"Connecting to {c.get('name') or c['host']} ...")
            self.update_ui()
            link = RL.Link(c["host"], c.get("port", RL.PORT), code)

            def work():
                try:
                    link.connect()
                    folder = GC.find_gimble(link)
                    st = GC.status(link, folder)
                    self.poster.post(lambda: self.connect_done(link, folder, st, c, code, keep, None))
                except RL.RemoteError as e:
                    link.close()
                    self.poster.post(lambda e=e: self.connect_done(None, None, None, c, code, keep, str(e)))
            threading.Thread(target=work, daemon=True).start()

        def connect_done(self, link, folder, st, c, code, keep, err):
            self.connecting = False
            if err:
                if "access code" in err.lower() and c.get("code"):
                    RL.remember(c.get("name") or c["host"], c["host"], c.get("port", RL.PORT))          # a remembered code that stopped working
                    self.fill_computers()
                self.update_ui()
                self.say(err, "bad")
                self.status_lbl.setText("Could not connect to the Gimble.\n\n" + err)        # the whole reason, where there is room to read it
                self.pages.setCurrentIndex(0)
                return
            self.link, self.folder = link, folder
            link.on_closed = lambda why: self.poster.post(lambda: self.link_closed(link, why))
            RL.remember(link.label(), c["host"], c.get("port", RL.PORT), code if keep else None)
            GC.save_settings(computer={"host": c["host"], "port": int(c.get("port", RL.PORT))})
            self.fill_computers()
            self.show_status(st)
            self.say(f"Connected to {link.label()}.", "good")
            self.update_ui()
            self.load_sessions()

        def disconnect_now(self):
            link, self.link, self.folder = self.link, None, None
            if link is not None:
                link.on_closed = None
                link.close()
            self.sess = []
            self.fill_sessions()
            self.status_lbl.setText("")
            self.update_ui()

        def link_closed(self, link, why):
            if link is self.link:
                self.link, self.folder, self.sess = None, None, []
                self.fill_sessions()
                self.update_ui()
                self.say(why, "bad")

        def closeEvent(self, ev):
            if self.busy is not None:
                self.busy["stop"] = True
            self.disconnect_now()
            super().closeEvent(ev)

        # ---------------------------------------------------------------- long work
        def run(self, label, work, done):
            """work(progress, stop) in the background; done(result) afterwards in the window.  One at a time."""
            if self.busy is not None:
                return
            job = self.busy = {"stop": False}
            self.job_lbl.setText(label)
            self.job_bar.setRange(0, 0)
            self.update_ui()
            last = [0.0]

            def progress(done_b, total_b, text=""):
                if time.time() - last[0] > 0.1 or done_b >= total_b:
                    last[0] = time.time()
                    self.poster.post(lambda: (self.job_bar.setRange(0, 1000), self.job_bar.setValue(int(1000 * done_b / max(total_b, 1))),
                                              self.job_lbl.setText(f"{label}  {RT.human_size(done_b)} of {RT.human_size(total_b)}  {text}")))

            def step(text):
                self.poster.post(lambda: (self.job_bar.setRange(0, 0), self.job_lbl.setText(f"{label}  {text} ...")))

            def thread():
                err = res = None
                try:
                    res = work(progress, lambda: job["stop"], step)
                except RL.Stopped:
                    err = "Stopped."
                except RL.RemoteError as e:
                    err = str(e)
                except OSError as e:
                    err = f"{e.strerror or e}" + (f": {e.filename}" if e.filename else "")
                self.poster.post(lambda: self.finished(job, err, res, done))
            threading.Thread(target=thread, daemon=True).start()

        def finished(self, job, err, res, done):
            if self.busy is job:
                self.busy = None
            self.update_ui()
            if err:
                self.say(err, "warn" if err == "Stopped." else "bad")
                if err != "Stopped." and "\n" in err:
                    QMessageBox.warning(self, "Gimble", err)
            else:
                done(res)

        def stop(self):
            if self.busy is not None:
                self.busy["stop"] = True
                self.job_lbl.setText("Stopping ...")

        # ---------------------------------------------------------------- status
        def show_status(self, st):
            self.st = st
            self.status_lbl.setText(GC.status_text(st))
            new = GC.programs_outdated(st)
            self.programs_btn.setText("Update the Gimble's programs..." if new else "Send the Gimble's programs again...")
            (ui_kit.primary if new else (lambda b: b.setStyleSheet("")))(self.programs_btn)

        def update_programs(self):
            st = getattr(self, "st", None) or {}
            mine, theirs = GC.my_programs_version(), st.get("programs")
            if st.get("running"):
                QMessageBox.information(self, "Gimble", f"{', '.join(st['running'])} is running on the Gimble. Close it there first (QUIT), "
                                        "then press Refresh and try again.")
                return
            r = QMessageBox.question(
                self, "Update the Gimble's programs",
                f"Send the Gimble programs version {mine} to {self.link.label()}?\n\n"
                + (f"It has version {theirs} now." if theirs else "It has the programs from before the tidy-up now; they are moved to "
                   "old/before_tidy/ on the drive, not deleted.")
                + "\n\nOnly the programs, the launchers and the read-me are written. The calibration and settings, the model, the "
                  "recordings (dataset), the test videos and the calibration captures are not touched.")
            if r != QMessageBox.StandardButton.Yes:
                return
            link, folder = self.link, self.folder

            def work(progress, stop, step):
                n, tidied = GC.update_programs(link, folder, progress, stop)
                return n, tidied, GC.status(link, folder)

            def done(r):
                n, tidied, st2 = r
                self.show_status(st2)
                self.say(f"The Gimble has the programs version {st2.get('programs')} now ({n} files sent"
                         + (f", {tidied} old files moved to old/before_tidy" if tidied else "") + "). Start it with 'Gimble' on the drive.", "good")
            self.run("Updating the Gimble's programs", work, done)

        def refresh_status(self):
            link, folder = self.link, self.folder
            self.run("Asking the Gimble", lambda p, s, step: GC.status(link, folder),
                     lambda st: (self.show_status(st), self.say("Status updated.")))

        # ---------------------------------------------------------------- models
        def fill_models(self):
            self.models = GC.list_models() + [m for m in self.extra_models if os.path.isfile(m["path"])]
            self.models.sort(key=lambda m: m["ts"], reverse=True)
            self.model_tree.clear()
            for m in self.models:
                cls = m["classes"] or []
                it = QTreeWidgetItem([m["label"], GC.KIND_TEXT.get(m["kind"], GC.KIND_TEXT[None]),
                                      ", ".join(str(c) for c in cls[:4]) + (" ..." if len(cls) > 4 else ""), m.get("where") or "", m["file"]])
                it.setData(0, Qt.ItemDataRole.UserRole, m)
                for col in range(5):
                    it.setToolTip(col, m["path"])
                self.model_tree.addTopLevelItem(it)
            if self.models:
                self.model_tree.setCurrentItem(self.model_tree.topLevelItem(0))
            else:
                it = QTreeWidgetItem(["No trained model found", "", "", "", "Train one in the Trainer, or use Choose a file..."])
                it.setDisabled(True)
                it.setToolTip(0, "Looked in:\n" + "\n".join(d for _w, d in GC.model_folders()))
                self.model_tree.addTopLevelItem(it)
            self.update_ui()

        def choose_model(self):
            start = next((d for _w, d in GC.model_folders() if os.path.isdir(d)), os.path.expanduser("~"))
            path, _ = QFileDialog.getOpenFileName(self, "Choose a trained model", GC.load_settings().get("model_folder") or start,
                                                  "Trained models (*.pt)")
            if not path:
                return
            GC.save_settings(model_folder=os.path.dirname(os.path.abspath(path)))
            self.add_models([path])

        def add_models(self, paths, where="chosen file"):
            """Adds .pt files to the list (Choose a file, or dropped on it) and selects the last one."""
            added = None
            for path in paths:
                path = os.path.abspath(path)
                m = GC.model_entry(path, None, where) if path.lower().endswith(".pt") and os.path.isfile(path) else None
                if m is None:
                    self.say(f"{os.path.basename(path)} is not a trained model file (.pt) that can be read.", "bad")
                    continue
                self.extra_models = [e for e in self.extra_models if os.path.normcase(e["path"]) != os.path.normcase(path)] + [m]
                added = path
            if added is None:
                return
            self.fill_models()
            for i in range(self.model_tree.topLevelItemCount()):
                d = self.model_tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)
                if d and os.path.normcase(d["path"]) == os.path.normcase(added):
                    self.model_tree.setCurrentItem(self.model_tree.topLevelItem(i))
            self.say(f"Added {os.path.basename(added)} to the list. Send to the Gimble converts it and puts it there.")

        def _drag_models(self, ev):
            if ev.mimeData().hasUrls() and any(u.isLocalFile() for u in ev.mimeData().urls()):
                ev.acceptProposedAction()
            else:
                ev.ignore()

        def _drop_models(self, ev):
            paths = [u.toLocalFile() for u in ev.mimeData().urls() if u.isLocalFile()]
            if paths:
                ev.acceptProposedAction()
                self.add_models(paths, "dropped file")

        def check_picture(self):
            """The picture open in the Annotator, when there is one: the converted model is checked on it as well as on a test pattern."""
            try:
                img_id = getattr(win, "current_image_id", None)
                path = win.project.image_path(img_id) if img_id is not None else None
                return path if path and os.path.isfile(path) else None
            except Exception:  # noqa: BLE001  (a window without a project open)
                return None

        def start_test(self):
            link, folder = self.link, self.folder
            self.run("Starting Test model on the Gimble", lambda p, s, step: GC.start_program(link, folder, "test"),
                     lambda pid: self.say("Test model is starting on the Gimble's screen. REC VIDEO there records the test.", "good"))

        def send_model(self):
            items = self.model_tree.selectedItems()
            m = items[0].data(0, Qt.ItemDataRole.UserRole) if items else None
            if not m or not self.connected():
                return
            link, folder = self.link, self.folder
            out = tempfile.mkdtemp(prefix="opara_gimble_")
            picture = self.check_picture()

            def work(progress, stop, step):
                try:
                    res = GC.export_model(m["path"], out, m["label"], on_step=step, stop=stop, check_image=picture)
                    step("Sending it to the Gimble")
                    GC.send_model(link, folder, res["onnx"], res["json"], lambda d, t: progress(d, t, "gimble_model.onnx"), stop)
                    return res, GC.status(link, folder)
                finally:
                    import shutil
                    shutil.rmtree(out, ignore_errors=True)

            def done(r):
                res, st = r
                self.show_status(st)
                running = "gimble_detect.py" in st.get("running", [])
                what = f", {res['parts']} in one file" if res.get("parts") else ""
                found = res.get("found")
                check = "" if found is None else (" On the picture open in the Annotator this model finds nothing (no box of confidence "
                                                  "0.1 or more)." if not found else
                                                  f" Checked on the picture open in the Annotator: it finds {found} "
                                                  f"{'box' if found == 1 else 'boxes'} there, the same as before the conversion.")
                self.say(f"Sent {m['label']} ({res['mb']} MB{what}) to the Gimble.{check} " +
                         ("Test model is running there: close it and start it again to use the new model." if running else
                          "Start Test model on the Gimble to use it (the button here, or TEST MODEL on its screen)."), "good")
            self.run(f"{m['label']}:", work, done)

        def restore_previous(self):
            if QMessageBox.question(self, "Gimble", "Put the model that was on the Gimble before the last send back in place?\n\n"
                                    "The current one is replaced.") != QMessageBox.StandardButton.Yes:
                return
            link, folder = self.link, self.folder

            def work(progress, stop, step):
                GC.restore_previous(link, folder)
                return GC.status(link, folder)
            self.run("Putting the previous model back", work, lambda st: (self.show_status(st), self.say("The previous model is back in place.", "good")))

        # ---------------------------------------------------------------- recordings
        def dest(self):
            return os.path.abspath(os.path.expanduser(self.dest_edit.text().strip() or "~"))

        def choose_dest(self):
            d = QFileDialog.getExistingDirectory(self, "Save the recordings to this folder", self.dest())
            if d:
                self.dest_edit.setText(d)
                self.fill_sessions()

        def load_sessions(self):
            if not self.connected():
                return
            try:
                self.sess = GC.sessions(self.link, self.folder)
            except RL.RemoteError as e:
                self.say(str(e), "bad")
                self.sess = []
            self.fill_sessions()

        def fill_sessions(self):
            self.sess_tree.clear()
            for s in reversed(self.sess):                       # newest first (their names are dates)
                here = GC.is_local_session(os.path.join(self.dest(), s["name"]))
                it = QTreeWidgetItem([s["name"], "yes" if here else "not yet"])
                it.setData(0, Qt.ItemDataRole.UserRole, s)
                self.sess_tree.addTopLevelItem(it)
            self.update_ui()

        def download(self):
            picked = [it.data(0, Qt.ItemDataRole.UserRole) for it in self.sess_tree.selectedItems()]
            if not picked:
                picked = [s for s in self.sess if not GC.is_local_session(os.path.join(self.dest(), s["name"]))]
            if not picked:
                self.say("Every recording on the Gimble is already on this PC. Select one to copy it again.")
                return
            dest, link = self.dest(), self.link
            GC.save_settings(recordings=dest)

            def done(r):
                self.fill_sessions()
                self.say(f"Downloaded {len(picked)} recording{'s' if len(picked) != 1 else ''} to {dest}  "
                         f"({r[0]} files copied" + (f", {r[1]} were already here" if r[1] else "") + ").", "good")
            self.run("Downloading", lambda progress, stop, step: GC.download_sessions(link, picked, dest, progress, stop), done)

        def download_videos(self):
            dest, link, folder = self.dest(), self.link, self.folder
            GC.save_settings(recordings=dest)

            def done(r):
                if r == (0, 0):
                    self.say("There are no test videos on the Gimble yet. REC VIDEO in Test model records one.")
                else:
                    self.say(f"Test videos are in {os.path.join(dest, 'test_videos')}  ({r[0]} files copied"
                             + (f", {r[1]} were already here" if r[1] else "") + ").", "good")
            self.run("Downloading test videos", lambda progress, stop, step: GC.download_videos(link, folder, dest, progress, stop), done)

        def import_now(self):
            try:
                import gimble_ext
            except ImportError:
                _missing(self, "Gimble sessions for the Annotator")
                return
            dest = self.dest()
            if not os.path.isdir(dest):
                self.say("Nothing has been downloaded to that folder yet.", "warn")
                return
            gimble_ext.import_gimble_session(win, dest)

    return GimbleDialog()


def item_model(win):
    return open_dialog(win, "model")


def item_recordings(win):
    return open_dialog(win, "recordings")


def item_status(win):
    return open_dialog(win, "status")


def register(ext):
    import addons
    if not addons.offered("gimble_link"):
        return
    ext.add_menu_item("annotator.file", "Gimble: Send a Model...", item_model)
    ext.add_menu_item("annotator.file", "Gimble: Download Recordings...", item_recordings)
    ext.add_menu_item("annotator.file", "Gimble: Status...", item_status)
