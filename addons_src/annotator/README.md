# General Classification Annotator (add-on)

Draw bounding boxes on photos for object detection: import Gimble sessions (camera + LiDAR, with a distance overlay and per-box distance
picking) or videos, pre-label with YOLO models, publish to a shared folder (one folder per person), annotate from a tablet in a browser.

Rebuilt in Qt from the Tkinter program in the General-Classification-Annotator repository, so it lives in a tab (and later in OpenPara).

- `app/annotator_window.py`  the window: says what each button does (class / image lists, AI assist, sharing, import, model handling)
- `app/annotator_ribbon.py`  the ribbon on top: Annotate / Data / Models / Setup tabs of icon buttons (greyed when there is nothing to act on)
- `app/annotator_panel.py`   the side panel: the classes, then Frames (working set, thumbnails), Selected box and AI assist tabs
- `app/annotator_icons.py`   the `ann_*` drawings in OpenPara's icon look (text-only buttons when the icon kit is not there)
- `app/annotator_canvas.py`  the picture area (zoom, pan, boxes, LiDAR dots, distance hover, hint and frame number)
- `app/annotator_dialogs.py` classes, hotkeys, sessions, thin out, import to edit, download models, open in browser
- `app/qtk.py`               message boxes, input dialogs, thread hand-over, key names
- the rest of `app/` is the toolkit-free code of the original, unchanged: `annotator_core` (projects, boxes, files, import, export),
  `share_zip`, `web_mode` / `web_page` (tablet page), `model_*`, `gimble_*`, `hotkeys`.

The old File / Edit / Manage menus are gone: every command has a ribbon button (Data: import video / zip, export zip, tablet mode, sessions, sync deleted files, plus the buttons add-ons bring, such as
Import Gimble session; Models: load AI model, download models, AI confidence; Setup: classes, hotkeys, my name; Annotate: confirm, previous / next, fit, rotate, delete frame, LiDAR distance, clear distance, delete box, clear and retry AI).
What is not here on purpose: *File > Check for updates* and *Update folder location* (the old self-updater); OpenPara's add-on updates take
its place. *Dataset location* reopens the new dataset in the same tab instead of restarting the program.
Tests: `test_annotator_qt.py` (projects, zips, add-on buttons), `test_annotator_ribbon.py` (ribbon, side panel, thumbnails, stand-alone fallback).

In the Workbench (`dev_addons/workbench`) the Annotator is a block with no wires in or out: it opens this tab and keeps a link to the project folder (no copy of the
dataset).  A new block works in a temporary project until you save it to a folder; then the block follows that folder.  A Trainer block will take a wire from it later.
Nothing in the annotator itself changed.  Test: `test_wb_pdf_annotator.py`.

Needs: pillow, numpy, opencv-python (required); qrcode (optional); torch, torchvision, ultralytics (AI pre-labeling, large). See requirements.txt.
Your dataset, models and settings stay where the original program keeps them (`~/.trash_annotator.json`, the dataset folder, `~/yolo_runs`).
