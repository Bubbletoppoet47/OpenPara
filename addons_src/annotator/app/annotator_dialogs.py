"""annotator_dialogs.py - the annotator's secondary windows (Qt): classes, hotkeys, sessions, thin out, import to edit, download models,
open in browser. Each has an `open(app, ...)` that shows it (a second call just brings the open one to the front) and works on the
annotator window `app` the way the Tk windows worked on AnnotatorApp."""
import threading

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QImage, QPixmap
from PyQt6.QtWidgets import (QAbstractItemView, QButtonGroup, QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QPushButton, QRadioButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QHeaderView)

import annotator_core as ac
import annotator_canvas as cv
import hotkeys as hk
import model_download as md
import qtk
import share_zip as sz


def label(text, wrap=True, bold=False):
    lab = QLabel(text)
    lab.setWordWrap(wrap)
    if bold:
        f = lab.font()
        f.setBold(True)
        lab.setFont(f)
    return lab


def buttons(*items):
    """A row of buttons from (text, fn) pairs; returns (layout, {text: button})."""
    row = QHBoxLayout()
    out = {}
    for text, fn in items:
        if text is None:
            row.addStretch(1)
            continue
        b = QPushButton(text)
        b.clicked.connect(lambda _c=False, f=fn: f())
        row.addWidget(b)
        out[text] = b
    return row, out


class _Base(QDialog):
    """A window that is shown once per annotator window: opening it again raises the existing one."""
    key = "dialog"

    @classmethod
    def open(cls, app, *a, **kw):
        cur = app._dialogs.get(cls.key)
        if cur is not None:
            try:
                cur.raise_()
                cur.activateWindow()
                return cur
            except RuntimeError:
                pass
        with app.busy_card("Opening " + cls.key.replace("_", " ")):      # the program window's "Opening ..." card while it is built
            d = cls(app, *a, **kw)
        app._dialogs[cls.key] = d
        d.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        d.destroyed.connect(lambda _o=None, k=cls.key: app._dialogs.pop(k, None))
        d.show()
        return d

    def __init__(self, app, title, size=None):
        super().__init__(app)
        self.app = app
        self.setWindowTitle(title)
        self.setWindowFlag(Qt.WindowType.Tool, True)
        if size:
            self.resize(*size)


# ============================================================================================ classes
class ClassesDialog(_Base):
    key = "classes"

    def __init__(self, app):
        super().__init__(app, "Classes", (420, 440))
        lay = QVBoxLayout(self)
        lay.addWidget(label("Classes in this project (saved with the project)", bold=True))
        self.lb = QListWidget()
        lay.addWidget(self.lb, 1)
        self.note = label("")
        lay.addWidget(self.note)
        row, _b = buttons(("Add...", self.do_add), ("Rename...", self.do_rename), ("Delete...", self.do_delete), (None, None), ("Close", self.close))
        lay.addLayout(row)
        self.lb.itemDoubleClicked.connect(lambda _i: self.do_rename())
        app._classes_refresh = self.refresh
        self.destroyed.connect(lambda _o=None: setattr(app, "_classes_refresh", None))
        self.refresh()

    def refresh(self):
        p = self.app.project
        counts = p.class_box_counts()
        sel = self.lb.currentRow()
        self.lb.clear()
        for i, name in enumerate(p.classes):
            key = self.app._hotkey_label(i)
            it = QListWidgetItem(f"{('[' + key + ']') if key else '   '} {name:<24} {counts[i]} box(es)")
            it.setForeground(QColor(cv.color_for_class(i)))
            self.lb.addItem(it)
        if 0 <= sel < len(p.classes):
            self.lb.setCurrentRow(sel)

    def chosen(self):
        r = self.lb.currentRow()
        if r < 0:
            self.note.setText("Pick a class in the list first.")
            return None
        self.note.setText("")
        return r

    def do_add(self):
        a = self.app
        if a._bg_blocked():
            return
        name = qtk.ask_string(self, "Add class", "Name for the new class (no spaces - use _ or -):")
        if name is None:
            return
        err = a.project.validate_class_name(name, a.project.classes)
        if err:
            qtk.error(self, "Can't add class", err)
            return
        was = a._checked_names()
        a.project.add_class(name.strip())
        a._after_class_change(f"Added class '{name.strip()}'.", was_checked=was)
        self.lb.setCurrentRow(self.lb.count() - 1)

    def do_rename(self):
        a = self.app
        idx = self.chosen()
        if idx is None or a._bg_blocked():
            return
        old = a.project.classes[idx]
        new = qtk.ask_string(self, "Rename class", f"New name for '{old}':", old)
        if new is None or new.strip() == old:
            return
        err = a.project.validate_class_name(new, a.project.classes, ignore=old)
        if err:
            qtk.error(self, "Can't rename", err)
            return
        was = a._checked_names()
        a.project.rename_class(idx, new.strip())
        was = {new.strip() if n == old else n for n in was}
        a._after_class_change(f"Renamed '{old}' to '{new.strip()}'. (A model already trained as '{old}' needs "
                              f"--rename {old}:{new.strip()} when you train again.)", was_checked=was)

    def do_delete(self):
        a = self.app
        idx = self.chosen()
        if idx is None or a._bg_blocked():
            return
        if len(a.project.classes) <= 1:
            qtk.info(self, "Can't delete", "Keep at least one class.")
            return
        name = a.project.classes[idx]
        n_boxes = a.project.class_box_counts()[idx]
        move_to = None
        if n_boxes:
            ans = DeleteClassDialog.ask(self, a, idx, n_boxes)
            if ans is None:
                return
            move_to = ans[0]
        elif not qtk.yesno(self, "Delete class", f"Delete the class '{name}'? It has no boxes."):
            return
        was = a._checked_names() - {name}
        a._bg_job = True
        a.set_progress(f"Deleting class '{name}'...")

        def worker():
            try:
                r = a.project.delete_class(idx, move_to=move_to, progress=lambda d, t: a.post(
                    lambda: a.set_progress(f"Deleting class '{name}': {d * 100 // max(1, t)}%")))
                err = None
            except Exception as e:  # noqa: BLE001
                import traceback
                traceback.print_exc()
                r, err = None, f"{type(e).__name__}: {e}"
            a.post(lambda: finished(r, err))

        def finished(r, err):
            a._bg_job = False
            if err:
                a.set_progress("")
                qtk.error(self, "Couldn't delete the class", err + "\nLabels were backed up in _class_backups.")
                return
            msg = f"Deleted class '{name}'."
            if r['removed']:
                msg += f" {r['removed']} box(es) removed."
            if r['moved']:
                msg += f" {r['moved']} box(es) moved to '{a.project.classes[move_to - (1 if move_to > idx else 0)]}'."
            if r['unannotated']:
                msg += f" {r['unannotated']} image(s) have no boxes left and are back in the to-do list."
            msg += " (Label backup: _class_backups.)"
            a._after_class_change(msg, boxes_changed=True, was_checked=was)
            a._refresh_image_list()
        threading.Thread(target=worker, daemon=True).start()


class DeleteClassDialog(QDialog):
    """Modal: what happens to the boxes of a class being deleted. Returns (move_to,) (move_to an index or None = remove), or None."""

    @staticmethod
    def ask(parent, app, idx, n_boxes):
        d = DeleteClassDialog(parent, app, idx, n_boxes)
        return d.value if d.exec() == QDialog.DialogCode.Accepted else None

    def __init__(self, parent, app, idx, n_boxes):
        super().__init__(parent)
        self.app, self.value = app, None
        self.setWindowTitle("Delete class")
        lay = QVBoxLayout(self)
        lay.addWidget(label(f"'{app.project.classes[idx]}' has {n_boxes} box(es) in the project. What should happen to them?"))
        self.remove = QRadioButton("Delete those boxes")
        self.remove.setChecked(True)
        self.move = QRadioButton("Move them to:")
        lay.addWidget(self.remove)
        row = QHBoxLayout()
        row.addWidget(self.move)
        self.others = [c for i, c in enumerate(app.project.classes) if i != idx]
        self.target = QComboBox()
        self.target.addItems(self.others)
        row.addWidget(self.target)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(label("Labels are backed up in _class_backups first."))
        r, _b = buttons(("Delete class", self.ok), ("Cancel", self.reject))
        lay.addLayout(r)

    def ok(self):
        self.value = (self.app.project.classes.index(self.target.currentText()),) if self.move.isChecked() else (None,)
        self.accept()


# ============================================================================================ hotkeys
class HotkeysDialog(_Base):
    key = "hotkeys"

    def __init__(self, app):
        super().__init__(app, "Hotkeys", (480, 520))
        lay = QVBoxLayout(self)
        lay.addWidget(label("Keyboard shortcuts (saved with the project)", bold=True))
        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["Action", "Key"])
        self.tree.setRootIsDecorated(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.tree, 1)
        self.note = label("Pick an action, press Change..., then the new key. A key does one thing only.")
        lay.addWidget(self.note)
        row, _b = buttons(("Change...", self.change), ("Clear", self.clear), ("Default", self.reset_one), ("All defaults", self.reset_all),
                          (None, None), ("Close", self.close))
        lay.addLayout(row)
        self.tree.itemDoubleClicked.connect(lambda *_a: self.change())
        app._hotkeys_refresh = self.refresh
        self.destroyed.connect(lambda _o=None: setattr(app, "_hotkeys_refresh", None))
        self.refresh()

    def selected(self):
        it = self.tree.currentItem()
        return it.data(0, Qt.ItemDataRole.UserRole) if it else None

    def refresh(self, select=None):
        sel = select or self.selected()
        self.tree.clear()
        keep = None
        for action, title in self.app.hotkeys.actions(self.app.project.classes):
            it = QTreeWidgetItem([title, self.app.hotkeys.label(action) or "(none)"])
            it.setData(0, Qt.ItemDataRole.UserRole, action)
            self.tree.addTopLevelItem(it)
            if action == sel:
                keep = it
        if keep is not None:
            self.tree.setCurrentItem(keep)

    def chosen(self):
        a = self.selected()
        if a is None:
            self.note.setText("Pick an action in the list first.")
        return a

    def change(self):
        action = self.chosen()
        if action is None:
            return
        titles = dict(self.app.hotkeys.actions(self.app.project.classes))
        cap = KeyCapture(self, titles[action])
        if cap.exec() == QDialog.DialogCode.Accepted and cap.binding:
            self.note.setText(self.app._apply_hotkey(action, cap.binding))
            self.refresh(select=action)

    def clear(self):
        action = self.chosen()
        if action is not None:
            self.note.setText(self.app._apply_hotkey(action, None))
            self.refresh(select=action)

    def reset_one(self):
        action = self.chosen()
        if action is None:
            return
        self.app._apply_hotkey(action, self.app.hotkeys.default(action))
        self.note.setText(f"{dict(self.app.hotkeys.actions(self.app.project.classes)).get(action, action)}: "
                          f"back to {self.app.hotkeys.label(action) or 'no key'}")
        self.refresh(select=action)

    def reset_all(self):
        if not qtk.yesno(self, "Hotkeys", "Put every shortcut back to its default?"):
            return
        self.app.hotkeys.reset_all()
        self.app._hotkeys_changed()
        self.refresh()
        self.note.setText("All shortcuts are back to their defaults.")


class KeyCapture(QDialog):
    """'Press the new key' - takes the next real key press (Esc cancels)."""

    def __init__(self, parent, title):
        super().__init__(parent)
        self.binding = None
        self.setWindowTitle("New key")
        lay = QVBoxLayout(self)
        lay.addWidget(label(f"Press the new key for\n{title}\n(Esc = cancel)"))
        self.resize(320, 120)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        b = qtk.from_qt_event(e)
        if b is None:             # only Shift / Ctrl so far - wait for the real key
            return
        self.binding = b
        self.accept()


# ============================================================================================ sessions
class SessionsDialog(_Base):
    key = "sessions"

    def __init__(self, app):
        super().__init__(app, "Sessions", (1000, 400))
        lay = QVBoxLayout(self)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Session", "Samples", "Annotated", "With depth", "Recorded from"])
        self.tree.setRootIsDecorated(False)
        self.tree.setColumnWidth(0, 300)
        self.tree.header().setStretchLastSection(True)
        lay.addWidget(self.tree, 1)
        self.info = label("")
        lay.addWidget(self.info)
        row, _b = buttons(("Access", self.do_access), ("Rename...", self.do_rename), ("Delete...", self.do_delete), ("Thin Out...", self.do_thin),
                          ("Current Set", self.do_open), (None, None), ("Close", self.close))
        lay.addLayout(row)
        self.tree.itemDoubleClicked.connect(lambda *_a: self.do_access() if (self.sel_id() or "").startswith("person:") else self.do_rename())
        app._sessions_refresh = self.refresh
        app._sessions_access = self.do_access
        self.destroyed.connect(lambda _o=None: setattr(app, "_sessions_refresh", None))
        self.refresh()

    def sel_id(self):
        it = self.tree.currentItem()
        return it.data(0, Qt.ItemDataRole.UserRole) if it else None

    def refresh(self):
        a = self.app
        keep = self.sel_id()
        self.tree.clear()
        rows = a.project.session_summary()
        owner_of = {r['session_id']: sz.session_owner(a.project, r['session_id'], a.me) for r in rows}
        mine = [r for r in rows if not a._is_foreign_owner(owner_of[r['session_id']])]
        people = {}
        for r in rows:
            if a._is_foreign_owner(owner_of[r['session_id']]):
                people.setdefault(owner_of[r['session_id']], []).append(r)
        sel_item = [None]

        def add(r, indent=""):
            it = QTreeWidgetItem([indent + r['session_id'] + ("  (current set)" if r['session_id'] == a.active_session else ""),
                                  str(r['samples']), str(r['annotated']), str(r['with_depth']), str(r['source_path'])])
            it.setData(0, Qt.ItemDataRole.UserRole, r['session_id'])
            self.tree.addTopLevelItem(it)
            if r['session_id'] == keep:
                sel_item[0] = it
        for r in mine:
            add(r)
        for pid in sorted(people, key=lambda x: sz.people_name(a.project, x).lower()):
            grp = people[pid]
            opened = pid in a.access_people
            it = QTreeWidgetItem([f"[{sz.people_name(a.project, pid)}] data - {len(grp)} set(s), {sum(g['samples'] for g in grp)} image(s)"
                                  + ("   (open - click Access to hide)" if opened else "   (click Access to open)"), "", "", "", ""])
            it.setData(0, Qt.ItemDataRole.UserRole, f"person:{pid}")
            self.tree.addTopLevelItem(it)
            if f"person:{pid}" == keep:
                sel_item[0] = it
            if opened:
                for r in grp:
                    add(r, indent="     ")
        if sel_item[0] is not None:
            self.tree.setCurrentItem(sel_item[0])
        shown = mine + [r for pid, g in people.items() if pid in a.access_people for r in g]
        tot = sum(r['samples'] for r in shown)
        self.info.setText((f"{len(shown)} session(s), {tot} sample(s)." + ("  Other people's data is closed until you click Access." if people else ""))
                          if shown or people else "No sessions imported yet - use File > Import Gimble Session...")

    def chosen(self):
        sid = self.sel_id()
        if not sid:
            qtk.info(self, "Pick a session", "Click a session in the list first.")
            return None
        if sid.startswith("person:"):
            qtk.info(self, "Open their data first", "Click Access first, then pick one of their sets.")
            return None
        return sid

    def do_access(self):
        a = self.app
        sid = self.sel_id()
        if not sid:
            qtk.info(self, "Pick a person", "Click a person's row first.")
            return
        if sid.startswith("person:"):
            pid = sid[len("person:"):]
        else:
            pid = sz.session_owner(a.project, sid, a.me)
            if not a._is_foreign_owner(pid):
                qtk.info(self, "Your own data", "That set is yours. Access is for other people's data.")
                return
        if pid in a.access_people:
            a.access_people.discard(pid)
            if a.active_session and sz.session_owner(a.project, a.active_session, a.me) == pid:
                a.active_session = None
        else:
            a.access_people.add(pid)
        a._refresh_session_combo()
        a._refresh_image_list()
        a._update_status()
        self.refresh()

    def do_rename(self):
        a = self.app
        sid = self.chosen()
        if sid is None or a._bg_blocked():
            return
        new = sid
        while True:
            new = qtk.ask_string(self, "Rename session", f"New name for '{sid}':\n(no spaces; every image, label, depth file and\n"
                                 "export entry is renamed to match)", new)
            if new is None:
                return
            new = new.strip()
            if new == sid:
                return
            err = ac.Project.validate_session_name(new)
            if err is None and new in {r['session_id'] for r in a.project.session_summary()}:
                err = f"A session named '{new}' already exists."
            if err is None:
                break
            qtk.error(self, "Can't use that name", err)
        try:
            res = a.project.rename_session(sid, new)
        except Exception as e:  # noqa: BLE001
            qtk.error(self, "Rename failed", str(e))
            return
        cur = a.current_image_id
        if cur in res['id_map']:
            a.current_image_id = res['id_map'][cur]
            a._depth_cache = (None, None)
        if a.active_session == sid:
            a.active_session = new
        a._refresh_image_list()
        a._update_status()
        self.refresh()
        a._announce(f"Renamed {res['renamed']} sample(s) to '{new}'.")

    def do_delete(self):
        a = self.app
        sid = self.chosen()
        if sid is None or a._bg_blocked():
            return
        r = next(x for x in a.project.session_summary() if x['session_id'] == sid)
        if not qtk.yesno(self, "Delete session?", f"Delete session '{sid}'? ({r['samples']} samples, {r['annotated']} annotated)\n"
                         "Its images, boxes and distances are removed. The original recording is not touched. This can't be undone.",
                         default_no=True):
            return
        cur_in = a.current_image_id in set(a.project.session_image_ids(sid))
        n = a.project.delete_session(sid)
        if cur_in:
            a._clear_current()
            a.canvas.redraw()
        a._refresh_image_list()
        a._update_status()
        self.refresh()
        a._announce(f"Deleted {n} sample(s) of '{sid}'.")

    def do_thin(self):
        sid = self.chosen()
        if sid is not None and not self.app._bg_blocked():
            self.app.thin_set(sid, parent=self)

    def do_open(self):
        sid = self.chosen()
        if sid is not None:
            self.app.set_active_session(sid)
            self.close()


# ============================================================================================ thin out
class ThinDialog(QDialog):
    """Remove redundant frames from a set: keep every Nth frame, or drop frames that look almost the same as the last kept one."""

    @staticmethod
    def open(app, sid, parent=None, modal=True):
        total, annotated = app.project.session_progress().get(sid, (0, 0))
        if total == 0:
            return None
        d = ThinDialog(app, sid, total, annotated, parent or app)
        app._thin_ui = d
        if modal:
            d.exec()
        else:
            d.show()
        return d

    def __init__(self, app, sid, total, annotated, parent):
        super().__init__(parent)
        self.app, self.sid = app, sid
        self.thumbs, self.busy, self.plan = None, False, None
        self.setWindowTitle(f"Thin out '{sid}'")
        lay = QVBoxLayout(self)
        lay.addWidget(label(f"'{sid}' has {total} frame(s), {annotated} annotated. Annotated frames are never removed. "
                            "Removed frames are deleted from the project."))
        self.similar = QRadioButton("Remove near-duplicates (frames that differ from the last kept one by less than)")
        self.nth = QRadioButton("Keep every")
        self.similar.setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self.similar)
        grp.addButton(self.nth)
        lay.addWidget(self.similar)
        r1 = QHBoxLayout()
        self.dvar = QLineEdit("3.0")
        self.dvar.setFixedWidth(60)
        r1.addSpacing(24)
        r1.addWidget(self.dvar)
        r1.addWidget(QLabel("%   (bigger = removes more; try 2-6, check the preview)"))
        r1.addStretch(1)
        lay.addLayout(r1)
        r2 = QHBoxLayout()
        self.nvar = QLineEdit("2")
        self.nvar.setFixedWidth(50)
        r2.addWidget(self.nth)
        r2.addWidget(self.nvar)
        r2.addWidget(QLabel("th frame (2 = half of them, 3 = a third ...)"))
        r2.addStretch(1)
        lay.addLayout(r2)
        self.status = label("")
        lay.addWidget(self.status)
        row, _b = buttons(("Preview", self.preview), ("Remove frames", self.apply), ("Cancel", self.reject))
        lay.addLayout(row)
        self.setMinimumWidth(480)

    # the Tk version exposed these names to its tests
    def mode(self):
        return "nth" if self.nth.isChecked() else "similar"

    def settings(self):
        try:
            if self.mode() == "nth":
                n = int(self.nvar.text())
                if n < 1:
                    raise ValueError
                return dict(every_n=n)
            d = float(self.dvar.text())
            if not (0 <= d <= 100):
                raise ValueError
            return dict(difference_pct=d)
        except ValueError:
            self.status.setText("Type a whole number (every Nth) or a percentage between 0 and 100.")
            return None

    def make_plan(self):
        kw = self.settings()
        if kw is None:
            return None
        self.plan = self.app.project.plan_thin(self.sid, thumbs=self.thumbs, **kw)
        return self.plan

    def show_plan(self, plan):
        self.status.setText(f"Would remove {len(plan['remove'])} of {plan['total']} frame(s) and keep {len(plan['keep'])}"
                            + (f" ({plan['annotated']} annotated kept)." if plan['annotated'] else "."))

    def preview(self):
        a = self.app
        if self.busy or self.settings() is None:
            return
        if self.mode() == "similar" and self.thumbs is None:
            self.busy = True
            self.status.setText("Reading frames: 0")

            def worker():
                try:
                    th, err = a.project.frame_thumbnails(self.sid, progress_cb=lambda d, t: a.post(
                        lambda: self.status.setText(f"Reading frames: {d}/{t}") if self.isVisible() else None)), None
                except Exception as e:  # noqa: BLE001
                    th, err = None, str(e)

                def done():
                    self.busy = False
                    if not self.isVisible():
                        return
                    if err:
                        self.status.setText("Couldn't read the frames: " + err)
                        return
                    self.thumbs = th
                    plan = self.make_plan()
                    if plan:
                        self.show_plan(plan)
                a.post(done)
            threading.Thread(target=worker, daemon=True).start()
            return
        plan = self.make_plan()
        if plan:
            self.show_plan(plan)

    def apply(self):
        a = self.app
        if self.busy:
            return
        if self.mode() == "similar" and self.thumbs is None:
            self.status.setText("Click Preview first to see what would be removed.")
            return
        plan = self.make_plan()
        if not plan:
            return
        if not plan['remove']:
            self.status.setText("Nothing would be removed with these settings.")
            return
        if not qtk.yesno(self, "Remove frames?", f"Permanently remove {len(plan['remove'])} of {plan['total']} frame(s) from '{self.sid}'?\n"
                         "This can't be undone.", default_no=True):
            return
        cur_gone = a.current_image_id in set(plan['remove'])
        n = a.project.thin_session(self.sid, plan['remove'])
        self.accept()
        if cur_gone:
            a._clear_current()
            a.canvas.redraw()
        a._refresh_image_list()
        a._update_status()
        if a._sessions_refresh:
            a._sessions_refresh()
        a._announce(f"Removed {n} frame(s) from '{self.sid}'.")


# ============================================================================================ import data to edit
class ImportEditDialog(_Base):
    key = "import_edit"

    def __init__(self, app, merged, sets, me):
        super().__init__(app, "Import data to edit", (700, 420))
        self.merged, self.sets, self.me = merged, sets, me
        lay = QVBoxLayout(self)
        lay.addWidget(label("Pick sets to fix. They are copied into your project, and your changes go out at the next Publish."))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Annotated by", "Set", "Images", "With depth"])
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setColumnWidth(0, 160)
        self.tree.setColumnWidth(1, 260)
        for i, g in enumerate(sets):
            it = QTreeWidgetItem([str(g['name']), str(g['set']), str(g['images']), str(g['with_depth'])])
            it.setData(0, Qt.ItemDataRole.UserRole, i)
            self.tree.addTopLevelItem(it)
        lay.addWidget(self.tree, 1)
        row, _b = buttons(("Import selected", lambda: self.go(False)), ("Import everything", lambda: self.go(True)), (None, None),
                          ("Close", self.close))
        lay.addLayout(row)

    def go(self, everything):
        if everything:
            picks = None
        else:
            sel = self.tree.selectedItems()
            if not sel:
                qtk.info(self, "Pick a set", "Click one or more sets in the list first.")
                return
            idx = [it.data(0, Qt.ItemDataRole.UserRole) for it in sel]
            picks = [(self.sets[i]['owner_id'], self.sets[i]['set']) for i in idx]
        entries = sz.select_entries(self.merged, picks)
        self.close()
        self.app._run_import(entries, self.merged['people'], self.me)


# ============================================================================================ download models from GitHub
class DownloadModels(_Base):
    key = "download_models"

    @classmethod
    def open(cls, app, first_run, fetch, install):
        app.setCursor(Qt.CursorShape.WaitCursor)
        try:
            entries, err = fetch(), None
        except (OSError, ValueError) as e:
            entries, err = [], e
        finally:
            app.unsetCursor()
        if err or not entries:
            qtk.info(app, "Download models", "Couldn't reach GitHub. Check your internet and try File > Download models from GitHub later."
                     if err else "No models on GitHub yet.")
            return None
        return super().open(app, first_run, entries, install)

    def __init__(self, app, first_run, entries, install):
        super().__init__(app, "Download models", (520, 0))
        self.entries, self.install, self.state = entries, install, {"busy": False, "result": None}
        self.models_dir = app._default_models_dir()
        lay = QVBoxLayout(self)
        lay.addWidget(label("Download ready-made AI models? They pre-label photos for you. You can do this later from File > Download "
                            "models from GitHub." if first_run else "Pick the AI models to download."))
        n = len(md.pick(entries, "newest"))
        self.r_newest = QRadioButton(f"Just the newest of each size ({n} model{'s' if n != 1 else ''})")
        self.r_all = QRadioButton(f"All of them ({len(entries)} model{'s' if len(entries) != 1 else ''})")
        self.r_none = QRadioButton("No thanks, just the annotator")
        self.r_newest.setChecked(True)
        lay.addWidget(self.r_newest)
        lay.addWidget(self.r_all)
        if first_run:
            lay.addWidget(self.r_none)
        box = QListWidget()
        for e in entries:
            box.addItem(md.describe(e) + ("   (already here)" if md.already_have(self.models_dir, e) else ""))
        box.setMaximumHeight(160)
        lay.addWidget(box)
        lay.addWidget(label(f"They are saved in: {self.models_dir}"))
        self.status = label("")
        lay.addWidget(self.status)
        row, b = buttons(("Close" if not first_run else "Not now", self.close), ("Download", self.go))
        lay.addLayout(row)
        self.go_btn = b["Download"]
        app._models_dialog = self

    def mode(self):
        return "none" if self.r_none.isChecked() else ("all" if self.r_all.isChecked() else "newest")

    def go(self):
        a = self.app
        if self.state["busy"]:
            return
        if self.mode() == "none":
            self.close()
            return
        chosen = md.pick(self.entries, self.mode())
        self.state["busy"] = True
        self.go_btn.setEnabled(False)
        box = {"text": "Starting...", "result": None}

        def work():
            def prog(i, n, name, done):
                box["text"] = f"Downloading {i + 1} of {n}: {name} ({done / 1048576:.1f} MB)"
            try:
                box["result"] = self.install(self.models_dir, chosen, prog)
            except Exception as ex:  # noqa: BLE001
                box["result"] = {"installed": [], "skipped": [], "errors": [("models", str(ex))]}
        threading.Thread(target=work, daemon=True).start()

        def poll():
            if not self.isVisible():
                return
            if box["result"] is not None:
                self.finish(box["result"])
            else:
                self.status.setText(box["text"])
                qtk.later(150, poll)
        poll()

    def finish(self, res):
        a = self.app
        self.state.update(busy=False, result=res)
        a._models_changed()
        lines = []
        if res["installed"]:
            lines.append(f"Downloaded {len(res['installed'])}: " + ", ".join(res["installed"]))
        if res["skipped"]:
            lines.append(f"Already had {len(res['skipped'])}.")
        for f, m in res["errors"]:
            lines.append(f"Couldn't get {f}: {m}")
        lines.append("\nPick one in the AI model box at the top of the window.")
        self.close()
        qtk.info(a, "Download models", "\n".join(lines))


# ============================================================================================ open in browser (tablet)
class WebWindow(_Base):
    key = "web"

    def __init__(self, app, share):
        super().__init__(app, "Open in browser", None)
        self.share = share
        lay = QVBoxLayout(self)
        lay.addWidget(label("On the tablet (same Wi-Fi), scan this or open the address:", wrap=False))
        try:
            import qrcode
            from PIL import ImageOps  # noqa: F401
            im = qrcode.make(share.login_url).convert("RGB").resize((220, 220))
            qi = QImage(im.tobytes("raw", "RGB"), 220, 220, 660, QImage.Format.Format_RGB888).copy()
            pic = QLabel()
            pic.setPixmap(QPixmap.fromImage(qi))
            pic.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lay.addWidget(pic)
        except Exception:  # noqa: BLE001  (no QR picture is fine; the address and code still work)
            pass
        u = label(share.url, wrap=False, bold=True)
        u.setAlignment(Qt.AlignmentFlag.AlignCenter)
        u.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(u)
        c = label(f"Code: {share.code}", wrap=False, bold=True)
        f = c.font()
        f.setPointSize(f.pointSize() + 6)
        c.setFont(f)
        c.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(c)
        lay.addWidget(label("Pen draws. Fingers pan and zoom. Own Wi-Fi only."))
        row, _b = buttons((None, None), ("Hide", self.close), ("Stop sharing", self.stop))
        lay.addLayout(row)
        app._web_win = self

    def stop(self):
        self.share.stop()
        self.close()


# ============================================================================================ first start: link the dataset
def ask_dataset_location(parent=None):
    """First start with no dataset linked: link an existing folder or make a new empty one. Returns the folder or None. Nothing is copied."""
    d = QDialog(parent)
    d.setWindowTitle("Link your dataset")
    out = {"path": None}
    lay = QVBoxLayout(d)
    lay.addWidget(label("Where is your dataset? It stays where it is; the program just links to it."))

    def existing():
        p = qtk.ask_dir(d, "Pick your dataset folder (the one with manifest.json inside)")
        if not p:
            return
        import os
        if not os.path.exists(os.path.join(p, "manifest.json")) and not qtk.yesno(d, "Link your dataset", f"No dataset in:\n{p}\nStart a new empty one there?"):
            return
        out["path"] = p
        d.accept()

    def new():
        p = qtk.ask_dir(d, "Pick or make a folder for the new dataset")
        if p:
            out["path"] = p
            d.accept()
    for text, fn in (("Link an existing dataset folder...", existing), ("Make a new, empty dataset...", new), ("Quit", d.reject)):
        b = QPushButton(text)
        b.clicked.connect(lambda _c=False, f=fn: f())
        lay.addWidget(b)
    d.exec()
    return out["path"]
