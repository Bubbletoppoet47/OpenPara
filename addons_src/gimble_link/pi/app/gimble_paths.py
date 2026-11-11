"""
gimble_paths.py - the one place that says where things are on the Gimble drive.

    Gimble_Pi/
        Gimble.desktop, Record data.desktop, Test model.desktop     double-click to start
        app/                 the programs (this folder)
        settings/            camera and LiDAR calibration, the target layout, the dot range
        model/               the model Test model runs: gimble_model.onnx + gimble_model.json   (OpenPara sends it here)
        dataset/             recordings of Record data (camera + LiDAR), one folder per session
        test_videos/         videos recorded in Test model, with the predictions drawn in, and a table of them
        calibration_data/    what the calibration captured
        logs/                gimble_log.txt

Every program asks here, so nothing else has a folder name written into it.
"""
import os
import shutil

APP = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(APP) if os.path.basename(APP).lower() == "app" else APP
SETTINGS = os.path.join(ROOT, "settings")
MODEL = os.path.join(ROOT, "model")
MODEL_FILE = os.path.join(MODEL, "gimble_model.onnx")
DATASET = os.path.join(ROOT, "dataset")
TEST_VIDEOS = os.path.join(ROOT, "test_videos")
CALIBRATION = os.path.join(ROOT, "calibration_data")
LOGS = os.path.join(ROOT, "logs")
LOG_FILE = os.path.join(LOGS, "gimble_log.txt")
VERSION_FILE = os.path.join(APP, "VERSION")


def version():
    try:
        with open(VERSION_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return "?"


def setting(name):
    """The path of a settings / calibration file: settings/<name>.  A file that still lies in the main folder from before the tidy-up
    is copied over the first time, so a calibration is never lost by the move."""
    new, old = os.path.join(SETTINGS, name), os.path.join(ROOT, name)
    if not os.path.exists(new) and os.path.exists(old):
        try:
            os.makedirs(SETTINGS, exist_ok=True)
            shutil.copy2(old, new)
        except OSError:
            return old
    return new


def ensure():
    """Makes the folders the programs write to (never the recordings: those are made when one starts)."""
    for d in (SETTINGS, LOGS):
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            pass


ensure()
