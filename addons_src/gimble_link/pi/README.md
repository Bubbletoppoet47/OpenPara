# Gimble drive

Double-click **Gimble** (choose Execute if asked). The start screen has two big buttons:

- **RECORD DATA** - live camera with the LiDAR dots. Tap **REC** to record a session for training (about 3 samples a second), **STOP** to
  end it. Each session is a folder in `dataset/`.
- **TEST MODEL** - runs the trained model live: every box shows the class and confidence, the model's own distance when the model has
  one, and what the LiDAR measures inside the box. Tap **REC VIDEO** to record the test: the video (with everything drawn in) and a
  table of every prediction go to `test_videos/`.

The small buttons: **CALIBRATE** (LiDAR to camera), **VIEW DATA** (page through the newest recording), **MEASURE** (wall targets from a
photo), **SETUP** (first time on a new Pi: installs what is needed), **QUIT**.
`Record data` and `Test model` next to `Gimble` start those two directly.

## What is where

| Folder | What |
|---|---|
| `app/` | the programs. `gimble_paths.py` is the one place that says where everything is |
| `settings/` | camera calibration, LiDAR-to-camera calibration, the wall target layout, the dot range |
| `model/` | the model TEST MODEL runs: `gimble_model.onnx` + `gimble_model.json`; `previous/` is the one before |
| `dataset/` | recordings from RECORD DATA: `images/`, `depth/`, `depth_vis/`, `lidar/`, `index.csv`, `meta.json` per session |
| `test_videos/` | videos from TEST MODEL: `<date_time>.mp4`, `.csv` (every prediction per frame), `.json` (which model, settings) |
| `calibration_data/` | what the calibration captured |
| `logs/` | `gimble_log.txt` - look here when something did not start |
| `old/` | what lay in the main folder before the tidy-up (the old programs and launchers). Delete it when the new ones work for you |

## A new model

From OpenPara: Annotator > File > **Gimble: Send a Model...** sends a trained model over the network into `model/` (the thumb drive stays
in the Pi). Sending converts it: the PC's model file (`.pt`) becomes the two files the Pi runs, `gimble_model.onnx` and
`gimble_model.json`. A `.pt` copied into `model/` by hand cannot run here (there is no PyTorch on the Pi); the start screen says so.

- A **Classes + boxes** model shows the LiDAR distance but no distance of its own.
- A **Classes + boxes + distance** model is two models on the PC (a detector, then a distance model). The conversion joins them into
  the one file, so the Gimble runs it like any other: the start screen says "boxes + distance, two models". Its distance model
  looks at the boxes with a confidence of 0.1 or more (the 50 surest at most), which keeps a picture as quick as with the detector alone.
- A model from before (one network for boxes and distance) keeps working.

Start TEST MODEL again to use a new model. **Put the previous model back** in OpenPara undoes the last send.

## Details

- Recording: `depth/*.png` is 16-bit millimetres (0 = no LiDAR return) in the pixel grid of the raw image; `lidar/*.npz` keeps the raw
  points so depth can be made again after a better calibration. The dot range (the `0.15-15 m` button) limits what is drawn and recorded.
- Options when started from a terminal: `python3 app/gimble_pi.py --help`, `python3 app/gimble_detect.py --help`
  (`--windowed`, `--screen 1024x600`, `--hz`, `--conf`, `--video-fps` ...).
- LiDAR shows "NO LIDAR DATA": check its power, the cable, and that the Pi's wired port has 192.168.1.2 (`ip addr show eth0`; SETUP sets it).
- Calibrating: tape the four squares on the wall (`settings/target_layout.json` describes them), CALIBRATE, stand about 1 m back with
  all four in view, CAPTURE 10-15 times while turning and tilting the rig a little, SAVE when it says GOOD.
