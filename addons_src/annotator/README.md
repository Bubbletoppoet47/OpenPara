# General Classification Annotator (add-on)

Draw bounding boxes on photos for object detection: import Gimble sessions (camera + LiDAR, with a distance overlay and per-box distance
picking) or videos, pre-label with YOLO models, publish to a shared folder (one folder per person), annotate from a tablet in a browser.

Rebuilt in Qt from the Tkinter program in the General-Classification-Annotator repository, so it lives in a tab (and later in OpenPara).

- `app/annotator_window.py`  the window (menus, class / image lists, AI assist, sharing, import, model handling)
- `app/annotator_canvas.py`  the picture area (zoom, pan, boxes, LiDAR dots, distance hover)
- `app/annotator_dialogs.py` classes, hotkeys, sessions, thin out, import to edit, download models, open in browser
- `app/qtk.py`               message boxes, input dialogs, thread hand-over, key names
- the rest of `app/` is the toolkit-free code of the original, unchanged: `annotator_core` (projects, boxes, files, import, export),
  `share_zip`, `web_mode` / `web_page` (tablet page), `model_*`, `gimble_*`, `hotkeys`.

What is not here on purpose: *File > Check for updates* and *Update folder location* (the old self-updater); OpenPara's add-on updates take
its place. *Dataset location* reopens the new dataset in the same tab instead of restarting the program.

Needs: pillow, numpy, opencv-python (required); qrcode (optional); torch, torchvision, ultralytics (AI pre-labeling, large). See requirements.txt.
Your dataset, models and settings stay where the original program keeps them (`~/.trash_annotator.json`, the dataset folder, `~/yolo_runs`).
