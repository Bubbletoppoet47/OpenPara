"""gimble_ext.py - File > Import Gimble Session... for the Annotator window.  A session folder recorded by gimble_pi.py (index.csv + images/ +
depth/), or the dataset folder holding several of them.  Re-importing only adds samples that are not there yet, so annotations are never
disturbed.  The annotator keeps no Gimble code of its own except the reader in annotator_core (Project.import_gimble_session)."""


def import_gimble_session(win):
    import os
    import threading
    import annotator_core as ac
    import qtk
    if not win.ensure_saved("Importing a session puts a copy of its photos in the project."):
        return
    path = qtk.ask_dir(win, "Select a Gimble session folder (or the dataset folder)")
    if not path:
        return
    if ac.is_gimble_session(path):
        sessions = [path]
    else:
        sessions = sorted(os.path.join(path, d) for d in os.listdir(path) if ac.is_gimble_session(os.path.join(path, d)))
        if not sessions:
            qtk.error(win, "Not a Gimble session", "No session in that folder (needs index.csv + images/). Pick a folder like 20260930_095437.")
            return
        if not qtk.yesno(win, "Import all sessions?", f"Found {len(sessions)} session(s) in this folder. Import all of them?"):
            return
    stride = qtk.ask_int(win, "Sample interval", "Import every Nth sample (recordings are ~3 per second, so\n"
                         "neighbouring samples are often near-duplicates; 1 = all):", 1, 1)
    if not stride:
        return
    if win._bg_job:
        qtk.info(win, "Busy", "Wait for the current import to finish first.")
        return
    win._bg_job = True
    win.set_progress("Importing samples: 0")

    def worker():
        added = skipped = 0
        missing, no_depth = [], []
        try:
            for sess in sessions:
                r = win.project.import_gimble_session(sess, stride=stride, copy_lidar=True,
                                                      progress_cb=lambda d, t: win.post(lambda: win.set_progress(f"Importing samples: {d}/{t}")))
                added += len(r['new_ids'])
                skipped += r['skipped_existing']
                missing += r['missing']
                no_depth += r['no_depth']
        except Exception as e:  # noqa: BLE001
            err = str(e)

            def failed():
                qtk.error(win, "Import failed", err)
                win.set_progress("")
                win._bg_job = False
            win.post(failed)
            return

        def done():
            win.set_progress("")
            win._bg_job = False
            win._refresh_image_list()
            if win._sessions_refresh:
                win._sessions_refresh()
            win._update_status()
            lines = [f"Added {added} new sample(s) from {len(sessions)} session(s)."]
            if skipped:
                lines.append(f"{skipped} were already in the project and were left alone.")
            if no_depth:
                lines.append(f"{len(no_depth)} sample(s) came in without usable depth data.")
            if missing:
                lines.append(f"{len(missing)} sample(s) listed in index.csv had no image file.")
            qtk.info(win, "Import complete", "\n".join(lines))
        win.post(done)
    threading.Thread(target=worker, daemon=True).start()


def register(ext):
    ext.add_menu_item("annotator.file", "Import Gimble Session...", import_gimble_session)
