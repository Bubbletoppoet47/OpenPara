"""pe_aipanel.py - the "AI check" section of the PDF reader (pe_reader.ReaderTab inherits it): tick the tests, press the button, and every paragraph of the PDF is
shaded by how many of the tests lean AI.  Click a paragraph to see what each test said about it.

It only looks: nothing is written into the PDF, and nothing here is saved with it.  What a run needs is fetched the first time, after asking: the packages
(pe_deps.install_ai), then the model files of each ticked test (pe_aipacks.install_pack).  A test whose model cannot be had is reported and the others still run.
The work happens in a thread (pe_aicheck.Runner); the window hears about it through the reader's Signals (ai_progress, ai_done) and a timer that redraws the
shading while it goes on.  Tests that need a stand-in put one into AI_MAKE / AI_INSTALLER / AI_META / AI_GETTER, and answer ask_ai_download / ask_ai_memory.
"""
import os
import threading

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QCheckBox, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton

import pe_aicheck
import pe_aidet
import pe_aipacks
import pe_deps
import ui_kit


def size_text(mb):
    return f"{mb / 1000:.1f} GB" if mb >= 1000 else f"{int(mb)} MB"


class AiPanelMixin:
    AI_MAKE = None                 # the factory of the tests: make(test id) -> a pe_aidet.Test (None: the real ones)
    AI_INSTALLER = None            # the downloader of the packages (pe_deps.install_ai)
    AI_META = None                 # pe_aipacks.head_meta
    AI_GETTER = None               # pe_aipacks.fetch

    # ------------------------------------------------------------------ state
    def ai_init(self):
        self.ai_layout = None                      # pe_aidet.Layout of this PDF, made the first time
        self.ai_results, self.ai_errors = {}, {}   # {test id: [None | False | Verdict]}, {test id: sentence}
        self.ai_rects = {}                         # paragraph -> its rectangles on the pages
        self.ai_tally = None
        self.ai_runner = None
        self.ai_busy = False
        self.ai_cancel = threading.Event()
        self.sig.ai_progress.connect(self.ai_progress_slot)
        self.sig.ai_done.connect(self.ai_finished)
        self.ai_timer = QTimer(self)
        self.ai_timer.setInterval(600)
        self.ai_timer.timeout.connect(self.ai_refresh)

    # ------------------------------------------------------------------ the section
    def ai_build(self, v):
        self.ai_banner = ui_kit.note(pe_aicheck.BANNER, ui_kit.WARN)
        v.addWidget(self.ai_banner)
        v.addWidget(ui_kit.note("Every paragraph of the whole PDF is checked by each test you tick. The result is how many tests lean AI - one test alone proves nothing."))
        self.ai_checks, self.ai_notes = {}, {}
        for tid in pe_aidet.ORDER:
            cls = pe_aidet.CLASSES[tid]
            cb = QCheckBox(cls.name)
            cb.setChecked(not cls.heavy)
            cb.setToolTip(cls.blurb)
            cb.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            v.addWidget(cb)
            n = ui_kit.note("")
            n.setIndent(22)
            v.addWidget(n)
            self.ai_checks[tid], self.ai_notes[tid] = cb, n
        row = QHBoxLayout()
        self.ai_b_run = ui_kit.primary(QPushButton("Check this PDF"))
        self.ai_b_run.setToolTip("Run the ticked tests over every paragraph")
        self.ai_b_all = QPushButton("Run all tests")
        self.ai_b_all.setToolTip("Tick every test and run them")
        self.ai_b_stop = QPushButton("Stop")
        self.ai_b_run.clicked.connect(lambda _c=False: self.ai_run(self.ai_selected()))
        self.ai_b_all.clicked.connect(lambda _c=False: self.ai_run_all())
        self.ai_b_stop.clicked.connect(lambda _c=False: self.ai_stop())
        for b in (self.ai_b_run, self.ai_b_all, self.ai_b_stop):
            row.addWidget(b)
        v.addLayout(row)
        self.ai_progress_lbl = ui_kit.note("")
        v.addWidget(self.ai_progress_lbl)
        self.ai_overall = QLabel("")
        self.ai_overall.setWordWrap(True)
        self.ai_overall.setStyleSheet(f"font-weight:600; color:{ui_kit.INK};")
        v.addWidget(self.ai_overall)
        self.ai_tests_lbl = ui_kit.note("")
        v.addWidget(self.ai_tests_lbl)
        self.ai_warn = ui_kit.note("", ui_kit.WARN)
        v.addWidget(self.ai_warn)
        self.ai_detail = QLabel("")
        self.ai_detail.setWordWrap(True)
        self.ai_detail.setStyleSheet("font-size:11px;")
        self.ai_detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(self.ai_detail)
        row = QHBoxLayout()
        self.ai_b_prev, self.ai_b_next = QPushButton("◀ Previous flagged"), QPushButton("Next flagged ▶")
        self.ai_b_prev.setToolTip("Go to the previous paragraph where at least one test leans AI")
        self.ai_b_next.setToolTip("Go to the next paragraph where at least one test leans AI")
        self.ai_b_prev.clicked.connect(lambda _c=False: self.ai_step(-1))
        self.ai_b_next.clicked.connect(lambda _c=False: self.ai_step(1))
        row.addWidget(self.ai_b_prev)
        row.addWidget(self.ai_b_next)
        v.addLayout(row)
        row = QHBoxLayout()
        self.ai_b_csv = QPushButton("Save the numbers...")
        self.ai_b_csv.setToolTip("Write every paragraph's raw numbers to a .csv file, to check the tests against texts whose author you know")
        self.ai_b_clear = QPushButton("Clear")
        self.ai_b_clear.setToolTip("Remove the shading and the results")
        self.ai_b_csv.clicked.connect(lambda _c=False: self.ai_save_csv())
        self.ai_b_clear.clicked.connect(lambda _c=False: self.ai_clear())
        row.addWidget(self.ai_b_csv)
        row.addWidget(self.ai_b_clear)
        v.addLayout(row)
        v.addWidget(ui_kit.note("Shading: purple = some tests lean AI (deeper = more of them); faint green = checked, no test leans AI; none = too short to check. "
                                "Nothing is added to the PDF."))
        self.ai_refresh_rows()                                       # (the viewer does not exist yet: the first ai_refresh comes with the first run)

    def ai_summary(self):
        if self.ai_tally is not None and self.ai_tally.tests_run:
            return pe_aicheck.overall_text(self.ai_tally)
        return "not run"

    def ai_selected(self):
        return [t for t in pe_aidet.ORDER if self.ai_checks[t].isChecked()]

    def ai_row_text(self, tid):
        cls = pe_aidet.CLASSES[tid]
        parts = [cls.blurb[:1].upper() + cls.blurb[1:] + "."]
        if cls.ready():
            parts.append("Downloaded.")
        else:
            mb = cls.missing_mb() + (0 if pe_deps.ai_ready() else pe_deps.AI_MB)
            parts.append(f"Needs a download of about {size_text(mb)}, once.")
        if cls.heavy:
            parts.append(f"Slow (many minutes on a long PDF), and needs about {cls.ram_mb / 1000:.1f} GB of free memory.")
        return " ".join(parts)

    def ai_refresh_rows(self):
        for tid in pe_aidet.ORDER:
            self.ai_notes[tid].setText(self.ai_row_text(tid))
        self.ai_set_enabled()

    def ai_set_enabled(self):
        busy = self.ai_busy
        for cb in self.ai_checks.values():
            cb.setEnabled(not busy)
        have = self.ai_tally is not None and self.ai_tally.tests_run > 0
        flagged = have and any(a > 0 for a, m in self.ai_tally.per_window)
        self.ai_b_run.setEnabled(not busy)
        self.ai_b_all.setEnabled(not busy)
        self.ai_b_stop.setEnabled(busy)
        self.ai_b_prev.setEnabled(bool(flagged))
        self.ai_b_next.setEnabled(bool(flagged))
        self.ai_b_csv.setEnabled(bool(have))
        self.ai_b_clear.setEnabled(not busy and (self.ai_layout is not None))

    # ------------------------------------------------------------------ asking
    def ask_ai_download(self, mb, names, heavy):
        text = (f"The AI check needs a download of about {size_text(mb)}, once: {', '.join(names)}. The files come from huggingface.co and are kept on this computer; "
                "the tests then work without internet.")
        if heavy:
            text += ("\n\nThe 7-billion-parameter test is a big download, needs a lot of memory, and takes many minutes on a long PDF. You can Stop it at any time, "
                     "and what it has checked so far is kept.")
        return QMessageBox.question(self, "PDF editor", text + "\n\nDownload now?") == QMessageBox.StandardButton.Yes

    def ask_ai_memory(self, cls, total, avail):
        gb = lambda x: f"{x / 1e9:.1f} GB"                          # noqa: E731
        text = (f"{cls.name} needs about {cls.ram_mb / 1000:.1f} GB of free memory, and this computer has about {gb(avail)} free"
                + (f" (of {gb(total)})" if total else "") + ". Running it anyway may make the computer very slow, or the program may stop working "
                "(unsaved work in other tabs could be lost).\n\nClose other programs first if you can. Run it anyway?")
        return QMessageBox.question(self, "PDF editor", text, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                    QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

    # ------------------------------------------------------------------ running
    def ai_run_all(self):
        for cb in self.ai_checks.values():
            cb.setChecked(True)
        self.ai_run(list(pe_aidet.ORDER))

    def ai_run(self, ids):
        if self.ai_busy:
            return
        ids = [t for t in pe_aidet.ORDER if t in ids]
        if not ids:
            self.status.say("Tick at least one test.", "warn")
            return
        if self.setup_busy or pe_deps.busy():
            self.status.say("Another download is already running. Press the button again when it has finished.", "warn")
            return
        self.finish_text()
        if self.ai_layout is None:
            self.ai_layout = pe_aidet.build_layout(self.text)
        layout = self.ai_layout
        self.ai_refresh()
        if not layout.windows:
            self.status.say(pe_aicheck.warnings(layout)[0], "warn")
            return
        todo = [t for t in ids if any(v is None for v in self.ai_results.get(t, [None]))]          # (a test that has done every paragraph has nothing left to do)
        keep = []
        for tid in ids:                                              # a test that still has work and needs more memory than is free is asked about first
            cls = pe_aidet.CLASSES[tid]
            total, avail = pe_aidet.memory()
            if tid in todo and cls.ram_mb and avail is not None and avail < cls.ram_mb * 1e6 and not self.ask_ai_memory(cls, total, avail):
                continue
            keep.append(tid)
        ids = keep
        todo = [t for t in todo if t in ids]
        if not ids:
            self.status.say("Nothing was run.", "warn")
            return
        need = sum(pe_aidet.CLASSES[t].missing_mb() for t in todo)
        if todo and not pe_deps.ai_ready():
            need += pe_deps.AI_MB
        if need > 0:
            if not self.AUTO_SETUP:
                self.status.say("The models of the AI check are not downloaded.", "warn")
                return
            names = [pe_aidet.CLASSES[t].name for t in todo if not all(pe_aipacks.pack_ready(p) for p in pe_aidet.CLASSES[t].packs)]
            if todo and not pe_deps.ai_ready():
                names.append("a few small packages")
            if not self.ask_ai_download(need, names, any(pe_aidet.CLASSES[t].heavy and not all(pe_aipacks.pack_ready(p) for p in pe_aidet.CLASSES[t].packs) for t in todo)):
                self.status.say("Nothing was downloaded. Press the button again when you want the AI check.", "warn")
                return
        for t in ids:
            self.ai_errors.pop(t, None)
        self.ai_busy = True
        self.ai_cancel.clear()
        cancel = self.ai_cancel
        runner = pe_aicheck.Runner(layout, self.ai_results, self.ai_errors, ids, make=self.AI_MAKE,
                                   progress=lambda text, frac=None: self.sig.ai_progress.emit(text, -1.0 if frac is None else float(frac)))
        self.ai_runner = runner
        self.ai_set_enabled()
        self.ai_timer.start()
        self.status.say("Starting the AI check ...")

        def prog(text, frac=None):
            if cancel.is_set():
                raise pe_aipacks.Cancelled()
            self.sig.ai_progress.emit(text, -1.0 if frac is None else float(frac))

        def work():
            msg = ""
            try:
                if todo and not pe_deps.ai_ready():
                    prog("Getting the packages of the AI check ...")
                    pe_deps.install_ai(prog, self.AI_INSTALLER)
                ok = []
                for tid in ids:
                    if tid not in todo:
                        ok.append(tid)
                        continue
                    try:
                        for pid in pe_aidet.CLASSES[tid].packs:
                            if not pe_aipacks.pack_ready(pid):
                                pe_aipacks.install_pack(pid, prog, cancel, self.AI_META, self.AI_GETTER)
                        ok.append(tid)
                    except pe_aipacks.Cancelled:
                        raise
                    except Exception as e:                           # noqa: BLE001 - this test is reported, the others still run
                        self.ai_errors[tid] = str(e).strip() or type(e).__name__
                runner.test_ids = ok
                if ok and not cancel.is_set():
                    runner.go()
            except pe_aipacks.Cancelled:
                pass
            except BaseException as e:                               # noqa: BLE001 - shown to the person, never raised in a thread
                msg = str(e).strip() or type(e).__name__
            self.sig.ai_done.emit(msg)
        threading.Thread(target=work, daemon=True).start()

    def ai_stop(self):
        if not self.ai_busy:
            return
        self.ai_cancel.set()
        if self.ai_runner is not None:
            self.ai_runner.stop()
        self.status.say("Stopping ... (a model that is still loading has to finish loading first)")

    def ai_progress_slot(self, text, frac):
        self.ai_progress_lbl.setText(text)
        self.status.say(text)

    def ai_finished(self, message):
        self.ai_busy = False
        self.ai_timer.stop()
        stopped = self.ai_cancel.is_set()
        self.ai_runner = None
        self.ai_progress_lbl.setText("")
        self.ai_refresh()
        self.ai_refresh_rows()
        if message:
            self.status.say("The AI check stopped: " + message.splitlines()[-1], "bad")
        elif stopped:
            self.status.say("Stopped. What was checked so far is kept; run again to go on from there.", "warn")
        elif self.ai_errors:
            self.status.say("Some tests could not run - see the AI check section.", "bad")
        else:
            self.status.say("Done: " + (self.ai_summary() if self.ai_tally and self.ai_tally.tests_run else "no result"), "good")

    # ------------------------------------------------------------------ showing
    def ai_window_rects(self, k):
        r = self.ai_rects.get(k)
        if r is None:
            r = [x for a, b in self.ai_layout.windows[k].runs for x in self.text.rects_for_tokens(a, b)]
            self.ai_rects[k] = r
        return r

    def ai_refresh(self):
        layout = self.ai_layout
        v = self.view
        if layout is None:
            self.ai_tally = None
            v.ai_marks, v.ai_focus = [], None
            self.ai_overall.setText("")
            self.ai_tests_lbl.setText("")
            self.ai_warn.setText("")
            self.ai_detail.setText("")
        else:
            ids = [t for t in pe_aidet.ORDER if t in self.ai_results]
            tally = self.ai_tally = pe_aicheck.Tally(layout, self.ai_results, ids)
            marks = []
            for k, (ai, m) in enumerate(tally.per_window):
                if m:
                    for pno, r in self.ai_window_rects(k):
                        marks.append((pno, r, ai / m, k))
            v.ai_marks = marks
            if v.ai_focus is not None and (v.ai_focus >= len(layout.windows) or not tally.per_window[v.ai_focus][1]):
                v.ai_focus = None
            head = pe_aicheck.overall_text(tally)
            if head:
                n = sum(1 for a, m in tally.per_window if m)
                head = ("So far: " if self.ai_busy else "") + head + f" ({n} paragraph{'s' if n != 1 else ''} checked)"
            self.ai_overall.setText(head)
            self.ai_tests_lbl.setText("\n".join(pe_aicheck.test_line(pe_aidet.CLASSES[t], tally, t) for t in tally.test_ids))
            lines = pe_aicheck.warnings(layout)
            for t in pe_aidet.ORDER:
                if t in self.ai_errors:
                    lines.append(f"{pe_aidet.CLASSES[t].name} could not run: {self.ai_errors[t]}")
            self.ai_warn.setText("\n".join(lines))
            self.ai_show_detail()
        v.sheet.update()
        self.ai_set_enabled()
        for s in self.sections:
            s.refresh_summary()

    def ai_show_detail(self):
        k = self.view.ai_focus
        if k is None or self.ai_layout is None:
            self.ai_detail.setText("")
            return
        win = self.ai_layout.windows[k]
        ids = [t for t in pe_aidet.ORDER if t in self.ai_results]
        lines = [f"Paragraph on page {win.page} ({win.words} words): {pe_aicheck.window_text(self.ai_tally, k)}"]
        lines += [text for _t, text, _ai in pe_aicheck.window_details(self.ai_layout, self.ai_results, k, ids)]
        self.ai_detail.setText("\n".join(lines))

    def ai_clicked(self, tok):
        """The viewer reports a click on word `tok` (None: on empty space)."""
        if self.ai_layout is None or not self.view.ai_marks:
            return
        k = self.ai_layout.window_at(tok) if tok is not None else None
        if k is not None and not self.ai_tally.per_window[k][1]:
            k = None
        self.view.ai_focus = k
        self.ai_show_detail()
        self.view.sheet.update()

    def ai_step(self, d):
        """Go to the next (d=1) or previous (d=-1) paragraph where at least one test leans AI."""
        t = self.ai_tally
        if t is None:
            return
        flagged = [k for k, (a, m) in enumerate(t.per_window) if a > 0]
        if not flagged:
            self.status.say("No test leans AI on any paragraph.", "good")
            return
        cur = self.view.ai_focus
        if cur is None:                                              # from where the window is now
            page = self.view.current_page()
            wins = self.ai_layout.windows
            base = next((k for k, w in enumerate(wins) if w.page - 1 >= page), len(wins))
            cands = [k for k in flagged if (k >= base if d > 0 else k < base)]
        else:
            cands = [k for k in flagged if (k > cur if d > 0 else k < cur)]
        if cands:
            k = cands[0] if d > 0 else cands[-1]
        else:
            k = flagged[0] if d > 0 else flagged[-1]
            self.status.say("Went round to the " + ("first" if d > 0 else "last") + " flagged paragraph.")
        self.view.ai_focus = k
        self.ai_show_detail()
        rects = self.ai_window_rects(k)
        if rects:
            pno, r = rects[0]
            self.view.scroll_to(self.view.page_y[pno] + r[1] * self.view.scale - self.view.viewport().height() * 0.25)
        self.view.sheet.update()

    def ai_clear(self):
        if self.ai_busy:
            return
        self.ai_layout, self.ai_results, self.ai_errors, self.ai_rects, self.ai_tally = None, {}, {}, {}, None
        self.ai_refresh()
        self.status.say("The AI check results were cleared.")

    def ai_save_csv(self):
        if self.ai_layout is None or self.ai_tally is None or not self.ai_tally.tests_run:
            self.status.say("There are no results to save yet.", "warn")
            return
        start = os.path.splitext(self.path)[0] + " - AI check.csv"
        p, _ = QFileDialog.getSaveFileName(self, "Save the numbers", start, "CSV files (*.csv);;All files (*)")
        if not p:
            return
        if not p.lower().endswith(".csv"):
            p += ".csv"
        try:
            pe_aicheck.write_csv(p, self.ai_layout, self.ai_results, [t for t in pe_aidet.ORDER if t in self.ai_results])
        except OSError as e:
            self.status.say("Could not save the numbers: " + str(e), "bad")
            return
        self.status.say("Saved the numbers: " + p, "good")

    def ai_shutdown(self):
        self.ai_cancel.set()
        if self.ai_runner is not None:
            self.ai_runner.stop()
        self.ai_timer.stop()
