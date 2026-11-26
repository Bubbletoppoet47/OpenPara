"""wb_models_tab.py - the window of a Trained models block: one list of every model, in the look of the Annotator and the Trainer (a ribbon, a sheet of details on the left, the list on
the right, a status bar).  All the model handling is in wb_models (and the block in wb_models_block); this file is the window.

    ribbon  Models:  Import model...  Import folder...  Export...  Rename...  Remove
    list    Model | Kind | Size | Stored | Made | From        (click a heading to sort)
    filter  All models / Embedded models (in this project: inside it or linked) / GitHub models (the shared Models folder)
    left    the details of the model chosen in the list
Model files (.pt) or folders dropped on the window are imported.  A model file can run code when it is loaded, so the person is asked before one is taken.
"""
import os

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QMessageBox, QScrollArea, QSplitter,
                             QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

import ui_kit
import wb_models

FILTERS = (("all", "All models", "Every model there is: the ones trained here, the ones imported and the ones downloaded from GitHub."),
           ("embedded", "Embedded models", "The models of this project: the ones trained in the Trainers wired into this block and the ones imported into it (kept inside the project file, or linked when over 500 MB)."),
           ("github", "GitHub models", "The models in the shared Models folder (the ones downloaded from GitHub, shared with the Annotator). They are only listed here, never copied into the project."))
COLUMNS = ("Model", "Kind", "Size", "Stored", "Made", "From")


class SortItem(QTableWidgetItem):
    """A cell that sorts by a key of its own (a date by its time, not by its text)."""
    def __init__(self, text, key=None):
        super().__init__(text)
        self.key = text.lower() if key is None else key

    def __lt__(self, other):
        a, b = self.key, getattr(other, "key", None)
        try:
            return a < b
        except TypeError:
            return str(a) < str(b)


def model_files(paths):
    """The .pt files of these paths: a file as it is, a folder with the .pt files in it and in the folders under it (three levels down at most)."""
    out = []
    for p in paths:
        if os.path.isdir(p):
            base = p.rstrip("/\\").count(os.sep)
            for root, dirs, files in os.walk(p):
                if root.count(os.sep) - base >= 3:
                    dirs[:] = []
                out += [os.path.join(root, f) for f in sorted(files) if f.lower().endswith(".pt")]
        elif p.lower().endswith(".pt") and os.path.isfile(p):
            out.append(p)
    return out


def import_models(parent, tab, node, paths, host=None):
    """Takes the model files of `paths` into the block `node` (inside the project up to 500 MB, linked above that).  A model file can run code when it is loaded, so the person is asked
    once.  -> (how many were taken, or None when nothing was done, and the sentence for the status bar)."""
    files = model_files(paths)
    if not files:
        return None, "There is no model file (.pt) in that."
    r = QMessageBox.question(parent, "Import model", "A model file (.pt) can contain code that runs when it is loaded.\n\nImport only models you made or trust. Import " + (
        f"these {len(files)} files?" if len(files) > 1 else os.path.basename(files[0]) + "?"), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
    if r != QMessageBox.StandardButton.Yes:
        return None, ""
    import contextlib
    busy = getattr(host, "busy", None)
    done, again, failed = [], [], []
    with (busy("Importing models") if callable(busy) else contextlib.nullcontext()):
        for p in files:
            try:
                got = wb_models.store_file(tab, node, p)
            except (OSError, ValueError, MemoryError) as e:
                failed.append(f"{os.path.basename(p)}: {e}")
                continue
            (done if got is not None else again).append(os.path.basename(p))
    return len(done), ((f"Imported {', '.join(done)}. " if done else "") + (f"{', '.join(again)} {'was' if len(again) == 1 else 'were'} here already. " if again else "") + "; ".join(failed))


def pane_head(text):
    lb = QLabel(text.upper())
    lb.setStyleSheet("color:#4a5872; font-size:11px; font-weight:600; letter-spacing:1px;")
    return lb


class ModelsWindow(QWidget):
    kind = "trainedmodels"
    path = None
    model_files = staticmethod(model_files)

    def __init__(self, tab, node, adapter):
        super().__init__()
        self.tab, self.node, self.adapter = tab, node, adapter
        self.host = tab.host
        self.rows = []
        self._fp = None
        self.setAcceptDrops(True)
        self._build()
        self.reload()
        self.timer = QTimer(self)
        self.timer.timeout.connect(lambda: self.reload(only_if_changed=True))
        self.timer.start(1000)

    # ------------------------------------------------------------------ the tab protocol
    def title(self):
        return f"{self.node.label} {self.node.title}"

    def is_dirty(self):
        return False                                         # (the models are in the project: it is the project that is saved)

    def save(self, as_new=False):
        return True

    def can_close(self):
        return True

    def shutdown(self):
        self.timer.stop()

    # ------------------------------------------------------------------ the window
    def _build(self):
        import annotator_ribbon as rib
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        B = rib.button
        self.ribbon = R = rib.Ribbon()
        outer.addWidget(R)
        made = R.add_page("Models", [
            B("import_model", "ann_import_zip", "Import\nmodel...", "Takes model files (.pt) into this block. A model up to 500 MB is kept inside the project file, a bigger one is linked.", self.import_model),
            B("import_folder", "ann_import_zip", "Import\nfolder...", "Takes every model file (.pt) of a folder into this block.", self.import_folder),
            "|",
            B("export_model", "ann_export_zip", "Export...", "Writes the model chosen in the list out as a file: the .pt and its information (.json) beside it.", self.export_model),
            B("rename_model", "ann_name", "Rename...", "Gives the model chosen in the list another name (its file keeps its name).", self.rename_model),
            B("remove_model", "ann_delete_box", "Remove", "Removes the model chosen in the list from this block (only a model imported into it).", self.remove_model),
        ])
        self.buttons = made
        corner = QWidget()
        cl = QHBoxLayout(corner)
        cl.setContentsMargins(0, 0, 8, 0)
        cl.addWidget(ui_kit.kind_chip("Trained models", "#2f7d6b"))
        self.bar_lbl = QLabel("")
        self.bar_lbl.setStyleSheet(f"color:{ui_kit.MUTED};")
        cl.addWidget(self.bar_lbl)
        R.setCornerWidget(corner, Qt.Corner.BottomRightCorner)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(6, 4, 6, 2)
        bl.addWidget(split, 1)
        outer.addWidget(body, 1)

        left = QWidget()                                     # the details of the model chosen
        lv = QVBoxLayout(left)
        lv.setContentsMargins(4, 2, 6, 6)
        self.detail_title = QLabel("")
        self.detail_title.setWordWrap(True)
        self.detail_title.setStyleSheet("font-size:14px; font-weight:600;")
        lv.addWidget(self.detail_title)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.fields = {}
        for key, label in (("name", "Name"), ("kind", "Kind"), ("size", "Size"), ("classes", "Classes"), ("scores", "Scores"), ("trainer", "Made by"), ("made", "Made"),
                           ("based_on", "Based on"), ("stored", "Stored"), ("bytes", "File size"), ("file", "File"), ("from", "From"), ("used", "Used by")):
            lab = QLabel("")
            lab.setWordWrap(True)
            lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.fields[key] = lab
            form.addRow(label + ":", lab)
        lv.addLayout(form)
        lv.addStretch(1)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QScrollArea.Shape.NoFrame)
        sc.setWidget(left)
        sc.setMinimumWidth(260)
        split.addWidget(sc)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(4, 2, 4, 4)
        head = QHBoxLayout()
        self.list_head = pane_head("Models in this project")
        head.addWidget(self.list_head)
        head.addStretch(1)
        head.addWidget(QLabel("Show:"))
        self.filter_box = QComboBox()
        for key, text, tip in FILTERS:
            self.filter_box.addItem(text, key)
            self.filter_box.setItemData(self.filter_box.count() - 1, tip, Qt.ItemDataRole.ToolTipRole)
        self.filter_box.setToolTip("Which models the list shows: " + " ".join(f"{t}: {tip}" for _k, t, tip in FILTERS))
        self.filter_box.currentIndexChanged.connect(lambda _i: self.fill())
        head.addWidget(self.filter_box)
        rv.addLayout(head)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, len(COLUMNS)):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSortingEnabled(True)
        self.table.itemSelectionChanged.connect(self.show_detail)
        rv.addWidget(self.table, 1)
        self.drop_lbl = QLabel("Drop model files (.pt) or a folder of them here to import them.")
        self.drop_lbl.setStyleSheet(f"color:{ui_kit.MUTED}; font-size:11px;")
        rv.addWidget(self.drop_lbl)
        split.addWidget(right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([300, 700])

        foot = QWidget()
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(8, 2, 8, 2)
        self.foot_lbl = QLabel("")
        self.foot_lbl.setStyleSheet(f"color:{ui_kit.MUTED};")
        fl.addWidget(self.foot_lbl)
        self.status = QLabel("")
        self.status.setStyleSheet(f"color:{ui_kit.WARN};")
        fl.addWidget(self.status, 1)
        outer.addWidget(foot)

    # ------------------------------------------------------------------ the list
    def used_by(self):
        """The blocks that take this block's models through a wire."""
        prj = self.tab.project
        return [f"{prj.nodes[k.b].label} {prj.nodes[k.b].title}" for k in prj.links if k.a == self.node.id and k.a_cell == "models" and k.b in prj.nodes]

    def reload(self, only_if_changed=False):
        """Reads the list of models again (the models of the wired Trainers and the shared folder change without this window doing anything)."""
        rows = wb_models.models_of(self.tab, self.node.id)
        fp = wb_models.fingerprint(rows)
        if only_if_changed and fp == self._fp:
            return
        self._fp = fp
        self.rows = rows
        self.fill()

    def shown(self):
        mode = self.filter_box.currentData()
        return [r for r in self.rows if mode == "all" or (mode == "github" and r["origin"] == "shared") or (mode == "embedded" and r["origin"] != "shared")]

    def fill(self):
        keep = self.chosen()
        keep_id = keep["id"] if keep else None
        t = self.table
        t.setSortingEnabled(False)
        t.setRowCount(0)
        shown = self.shown()
        for r in shown:
            i = t.rowCount()
            t.insertRow(i)
            kind = r["kind"] if r["key"] in wb_models.KEYS else r["key"]
            size = r["size_text"]
            cells = [SortItem(r["name"]), SortItem(kind), SortItem(size), SortItem(wb_models.STORED_TEXT.get(r["stored"], r["stored"])),
                     SortItem(wb_models.when(r["created"]).split(" ")[0], r["created"] or 0), SortItem(r["from"])]
            for c, it in enumerate(cells):
                it.setToolTip(r["file"])
                t.setItem(i, c, it)
            t.item(i, 0).setData(Qt.ItemDataRole.UserRole, r["id"])
        t.setSortingEnabled(True)
        t.sortItems(4, Qt.SortOrder.DescendingOrder)
        row = 0 if t.rowCount() else -1
        for i in range(t.rowCount()):
            if t.item(i, 0).data(Qt.ItemDataRole.UserRole) == keep_id:
                row = i
        if row >= 0:
            t.selectRow(row)
        self.show_detail()
        embedded = sum(1 for r in self.rows if r["origin"] != "shared")
        github = len(self.rows) - embedded
        self.bar_lbl.setText(f"{embedded} embedded, {github} from GitHub")
        proj = os.path.basename(self.tab.path) if self.tab.path else "a project that is not saved yet"
        by = self.used_by()
        self.foot_lbl.setText(f"Project: {proj}   |   " + (f"Used by {', '.join(by)}" if by else "Not used by a Model testing block yet") + f"   |   showing {len(shown)} of {len(self.rows)}")
        self.list_head.setText("MODELS IN THIS PROJECT" if self.filter_box.currentData() != "github" else "MODELS FROM GITHUB (THE SHARED MODELS FOLDER)")

    def chosen(self):
        """The row of describe() chosen in the list (the only one when there is just one), or None."""
        t = self.table
        i = t.currentRow() if t.selectedItems() else (0 if t.rowCount() == 1 else -1)
        if i < 0 or t.item(i, 0) is None:
            return None
        rid = t.item(i, 0).data(Qt.ItemDataRole.UserRole)
        return next((r for r in self.rows if r["id"] == rid), None)

    def show_detail(self):
        r = self.chosen()
        f = self.fields
        if r is None:
            self.detail_title.setText("No model chosen" if self.rows else "No models yet")
            for lab in f.values():
                lab.setText("")
            return
        sc = r["scores"] or {}
        score_bits = []
        if sc.get("map50_95") is not None:
            score_bits.append(f"mAP50-95 {sc['map50_95']}")
        if sc.get("map50") is not None:
            score_bits.append(f"mAP50 {sc['map50']}")
        if sc.get("dist_median_err") is not None:
            try:
                score_bits.append(f"distance error {float(sc['dist_median_err']) * 100:.1f} % (median)")
            except (TypeError, ValueError):
                pass
        self.detail_title.setText(r["name"])
        f["name"].setText(r["name"])
        f["kind"].setText(r["kind"])
        f["size"].setText(r["size_text"] or "not known (a model pasted in by hand)")
        f["classes"].setText(", ".join(str(c) for c in r["classes"]) if r["classes"] else "")
        f["scores"].setText(", ".join(score_bits))
        f["trainer"].setText(r["trainer"])
        f["made"].setText(wb_models.when(r["created"]))
        f["based_on"].setText(str(r["based_on"] or ""))
        f["stored"].setText(wb_models.STORED_TEXT.get(r["stored"], r["stored"]) + (" (" + (r["entry"].get("link") or {}).get("abs", "") + ")" if r["stored"] == "linked" else ""))
        f["bytes"].setText(wb_models.mb(r["bytes"]))
        f["file"].setText(r["file"])
        f["from"].setText(r["from"])
        f["used"].setText(", ".join(self.used_by()))

    def say(self, text):
        self.status.setText(text)

    def changed(self):
        """What was done here goes into the project at once (the cells say so), then the list is read again."""
        self.adapter.changed_in_window(self.tab)
        self.reload()

    # ------------------------------------------------------------------ importing
    def import_model(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Import model file(s)", "", "Model (*.pt)")
        if paths:
            self.import_paths(paths)

    def import_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Import every model file (.pt) of a folder")
        if d:
            self.import_paths([d])

    def import_paths(self, paths):
        """Takes the model files into the block (inside the project up to 500 MB, linked above that).  A model file can run code when it is loaded, so the person is asked once.
        -> how many were taken."""
        done, text = import_models(self, self.tab, self.node, paths, self.host)
        if done is None:
            if text:
                self.say(text)
            return 0
        self.changed()
        self.say(text)
        return done

    # ------------------------------------------------------------------ the chosen model
    def own_row(self, what):
        """The chosen row when it is a model of this block (imported into it); else None, and the person is told why `what` cannot be done."""
        r = self.chosen()
        if r is None:
            QMessageBox.information(self, what, "Choose a model in the list first.")
            return None
        if r["origin"] == "shared":
            QMessageBox.information(self, what, "This model is in the shared Models folder (the ones downloaded from GitHub). It is shared with the Annotator, so it is only listed here: it cannot be changed from this project.")
            return None
        if r["origin"] == "wired":
            QMessageBox.information(self, what, f"This model is in {r['from']}: change it there.")
            return None
        return r

    def export_model(self):
        r = self.chosen()
        if r is None:
            QMessageBox.information(self, "Export model", "Choose a model in the list first.")
            return
        dest, _ = QFileDialog.getSaveFileName(self, "Export the model as a file", r["file"], "Model (*.pt)")
        if not dest:
            return
        try:
            out = wb_models.export_entry(self.tab, r["node"], r["entry"], dest)
        except (OSError, ValueError) as e:
            QMessageBox.critical(self, "Export model", f"Could not write the model: {e}")
            return
        self.say(f"Exported {os.path.basename(out)}, with its information beside it.")

    def rename_model(self):
        r = self.own_row("Rename model")
        if r is None:
            return
        name, ok = QInputDialog.getText(self, "Rename model", "Name:", text=r["name"])
        name = (name or "").strip()
        if not ok or not name or name == r["name"]:
            return
        r["entry"]["name"] = name
        self.changed()
        self.say(f"Renamed to {name}.")

    def remove_model(self):
        r = self.own_row("Remove model")
        if r is None:
            return
        a = QMessageBox.question(self, "Remove model", f"Remove {r['name']} from this block?\n\nIt cannot be got back from here (export it first to keep a copy).",
                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if a != QMessageBox.StandardButton.Yes:
            return
        lst = self.node.data.get("models", [])
        if r["entry"] in lst:
            lst.remove(r["entry"])
        self.changed()
        self.say(f"Removed {r['name']}.")

    # ------------------------------------------------------------------ dropping files
    def dragEnterEvent(self, e):
        if any(u.toLocalFile().lower().endswith(".pt") or os.path.isdir(u.toLocalFile()) for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.import_paths([u.toLocalFile() for u in e.mimeData().urls()])
