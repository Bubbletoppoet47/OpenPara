"""
gimble_tidy.py - moves what lay loose in the drive's main folder before the tidy-up out of the way, once.

The programs now live in app/, the calibration and settings in settings/, the log in logs/.  The copies that the old layout had in the
main folder (old programs, old launchers, the settings that were copied to settings/) are moved to  old/before_tidy/ ; nothing is
deleted, and dataset/, calibration_data/, model/, test_videos/ and anything this list does not name are never touched.
The start screen calls tidy() every time it starts; after the first time there is nothing left to do.
"""
import os
import shutil

import gimble_paths as gpaths

OLD_PROGRAMS = ("calib_selftest.py", "calibrate_lidar_camera.py", "gimble_detect.py", "gimble_pi.py", "lidar_camera_overlay.py",
                "lidar_receiver.py", "lidar_udp_reader.py", "measure_targets.py", "view_dataset.py", "setup_pi.sh", "start_gimble.sh",
                "README_PI.md", "1 Start Gimble.desktop", "2 Calibrate.desktop", "3 View Recorded Data.desktop",
                "4 Measure Wall Targets.desktop", "5 First-Time Setup.desktop", "6 Detect.desktop",
                "Tidy up (run once on Windows).bat")
SETTINGS = ("camera_intrinsics.json", "lidar_camera_extrinsics.json", "lidar_camera_extrinsics.json.bak", "target_layout.json",
            "gimble_settings.json")
OLD_DIR = os.path.join(gpaths.ROOT, "old", "before_tidy")


def tidy(root=None):
    """Returns how many files were moved.  Safe to call any number of times; a file that cannot be moved is left where it is."""
    root = root or gpaths.ROOT
    if os.path.abspath(root) == os.path.abspath(gpaths.APP):          # the programs are not in app/: this is the old layout, leave it
        return 0
    old = os.path.join(root, "old", "before_tidy")
    moved = 0

    def move(name, dest_dir, dest_name=None):
        nonlocal moved
        src = os.path.join(root, name)
        if not os.path.isfile(src):
            return
        try:
            os.makedirs(dest_dir, exist_ok=True)
            dest = os.path.join(dest_dir, dest_name or name)
            if os.path.exists(dest):
                base, ext = os.path.splitext(dest)
                dest = f"{base}_{int(os.path.getmtime(src))}{ext}"
            shutil.move(src, dest)
            moved += 1
        except OSError:
            pass

    for name in SETTINGS:                       # the settings first: settings/ must have each one before its old copy leaves
        src, new = os.path.join(root, name), os.path.join(root, "settings", name)
        if os.path.isfile(src):
            try:
                if not os.path.exists(new):
                    os.makedirs(os.path.dirname(new), exist_ok=True)
                    shutil.copy2(src, new)
            except OSError:
                continue
            if os.path.exists(new):
                move(name, old)
    for name in OLD_PROGRAMS:
        move(name, old)
    move("gimble_log.txt", os.path.join(root, "logs"), "gimble_log_before_tidy.txt")
    cache = os.path.join(root, "__pycache__")   # Python's own scratch files of the old programs go with them
    if os.path.isdir(cache) and not os.path.exists(os.path.join(old, "__pycache__")):
        try:
            os.makedirs(old, exist_ok=True)
            shutil.move(cache, os.path.join(old, "__pycache__"))
            moved += 1
        except OSError:
            pass
    return moved
if __name__ == "__main__":
    print(f"moved {tidy()} file(s) to old/before_tidy")
