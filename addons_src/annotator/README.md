# General Classification Annotator (add-on)

Draw bounding boxes on photos for object detection: import Gimble sessions (camera + LiDAR, with a distance overlay and per-box distance
picking) or videos, pre-label with YOLO models, publish to a shared folder (one folder per person), annotate from a tablet in a browser.

Rebuilt in Qt from the Tkinter program in the General-Classification-Annotator repository, so it lives in a tab (and later in OpenPara).

- `app/annotator_window.py`  the window: says what each button does (class / image lists, AI assist, sharing, import, model handling)
- `app/annotator_ribbon.py`  the ribbon on top: Annotate / Data / Models / Analyse / Setup tabs of icon buttons (greyed when there is nothing to act on)
- `app/annotator_panel.py`   the side panel: the classes, then Frames (working set, thumbnails), Selected box and AI assist tabs
- `app/annotator_icons.py`   the `ann_*` drawings in OpenPara's icon look (text-only buttons when the icon kit is not there)
- `app/annotator_analysis.py` the Analyse tab's numbers (no toolkit): sessions, the LiDAR inside each box, the three comparisons, results, CSV, report, a made-up session
- `app/annotator_analyse.py` the Analyse tab's screens: setup card, Results / Boxes / Frames, the picture with its verdict colours, the scrubber, the exports
- `app/annotator_canvas.py`  the picture area (zoom, pan, boxes, LiDAR dots, distance hover, hint and frame number)
- `app/annotator_dialogs.py` classes, hotkeys, sessions, thin out, import to edit, download models, open in browser
- `app/qtk.py`               message boxes, input dialogs, thread hand-over, key names
- the rest of `app/` is the toolkit-free code of the original, unchanged: `annotator_core` (projects, boxes, files, import, export),
  `share_zip`, `web_mode` / `web_page` (tablet page), `model_*`, `gimble_*`, `hotkeys`.

The old File / Edit / Manage menus are gone: every command has a ribbon button (Data: import video / zip, export zip, tablet mode, sessions, sync deleted files, plus the buttons add-ons bring, such as
Import Gimble session; Models: load AI model, download models, AI confidence; Setup: classes, hotkeys, my name; Annotate: confirm, previous / next, fit, rotate, delete frame, LiDAR distance, clear distance, delete box, clear and retry AI).
What is not here on purpose: *File > Check for updates* and *Update folder location* (the old self-updater); OpenPara's add-on updates take
its place. *Dataset location* reopens the new dataset in the same tab instead of restarting the program.
Tests: `test_annotator_qt.py` (projects, zips, add-on buttons), `test_annotator_ribbon.py` (ribbon, side panel, thumbnails, stand-alone fallback),
`test_annotator_analyse.py` (the Analyse tab).

**Analyse tab: how well does a model's distance agree with the LiDAR?** Open a recorded Gimble session folder (`images/`, `depth/`, `index.csv`; a dataset
folder with several sessions asks which), pick a model of the Annotator's list and press *Run analysis*. The model runs once over every frame
(down to 10 % confidence, on a background thread, with a progress bar and *Stop*, which keeps what is done). The confidence (85 % to start with),
the tolerance (+-10 %) and the way the LiDAR is read are only filters over that run, so moving them re-judges everything at once. A box is compared
with the LiDAR returns inside it three ways: *closest point* (the return nearest the prediction, which forgives the LiDAR's delay and the wall behind
the object; the one that judges the boxes to start with), *median* (what the Pi's own number is) and *average*. A box passes when the number is within
the tolerance of the predicted distance; a box with fewer than 3 returns is *no LiDAR* (neither pass nor fail), and a model that gives no distance
shows its boxes but judges none. *Middle 60 % of each box only* reads the returns as the Pi does. The side panel has Results (% passing by each way and by
distance), Boxes and Frames lists; the picture shows each box in its verdict colour (teal pass, orange fail, grey dashed no LiDAR) with the LiDAR dots,
the closest return ringed, a card with the numbers of the selected box, and under it a scrubber (arrows, Home / End, Up / Down for the boxes, a click on
the colour strip, filters *All frames / With a fail / No LiDAR*), so you can judge by eye whether the test is fair. *Save frame image*, *Export CSV* (one row
per box) and *Export report* (one self-contained page: settings, tables, the worst misses and some passing frames as pictures) are for the write-up.
*Try the example* and *Self-check* run a made-up session and a made-up model and check answers worked out by hand. The Pi needs no change.
**Not run with a real model while this was built** (no torch there): the screens and numbers are tested with made-up models, and the adapter for the
Annotator's two model kinds with stand-ins. The PC runs the `.pt` while the Pi runs the converted copy, so the two can differ slightly.

In the Workbench (`dev_addons/workbench`) the Annotator is a block with no wires in or out: it opens this tab and keeps a link to the project folder (no copy of the
dataset).  A new block works in a temporary project until you save it to a folder; then the block follows that folder.  A Trainer block will take a wire from it later.
Nothing in the annotator itself changed.  Test: `test_wb_pdf_annotator.py`.

Needs: pillow, numpy, opencv-python (required); qrcode (optional); torch, torchvision, ultralytics (AI pre-labeling, large). See requirements.txt.
Your dataset, models and settings stay where the original program keeps them (`~/.trash_annotator.json`, the dataset folder, `~/yolo_runs`).
