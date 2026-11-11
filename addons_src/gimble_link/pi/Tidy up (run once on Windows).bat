@echo off
rem Tidy up the Gimble drive - run once, on Windows, by double-clicking.
rem It moves the files of the OLD layout that still lie in this folder to old\before_tidy\ . Nothing is deleted.
rem dataset\, calibration_data\, model\, test_videos\ and anything not named below are never touched.
rem (If you do not run it, the Gimble's start screen does the same the first time it starts on the Pi.)
cd /d "%~dp0"
if not exist "app\gimble_menu.py" (
  echo The new programs are not here: app\gimble_menu.py is missing. Nothing was changed.
  pause
  exit /b 1
)
set "OLD=old\before_tidy"
if not exist "%OLD%" mkdir "%OLD%"
if not exist "settings" mkdir "settings"
if not exist "logs" mkdir "logs"
for %%F in ("camera_intrinsics.json" "lidar_camera_extrinsics.json" "lidar_camera_extrinsics.json.bak" "target_layout.json" "gimble_settings.json") do (
  if exist %%F (
    if not exist "settings\%%~F" copy /y %%F "settings\" >nul
    if exist "settings\%%~F" move /y %%F "%OLD%\" >nul
  )
)
for %%F in ("calib_selftest.py" "calibrate_lidar_camera.py" "gimble_detect.py" "gimble_pi.py" "lidar_camera_overlay.py" "lidar_receiver.py" "lidar_udp_reader.py" "measure_targets.py" "view_dataset.py" "setup_pi.sh" "start_gimble.sh" "README_PI.md" "1 Start Gimble.desktop" "2 Calibrate.desktop" "3 View Recorded Data.desktop" "4 Measure Wall Targets.desktop" "5 First-Time Setup.desktop" "6 Detect.desktop") do (
  if exist %%F move /y %%F "%OLD%\" >nul
)
if exist "gimble_log.txt" move /y "gimble_log.txt" "logs\gimble_log_before_tidy.txt" >nul
if exist "__pycache__" if not exist "%OLD%\__pycache__" move /y "__pycache__" "%OLD%\" >nul
echo.
echo Done. The old programs and launchers are in old\before_tidy\ - delete that folder when the new ones work for you.
echo What is in the Gimble folder now:
echo.
dir /b
echo.
pause
(goto) 2>nul & del "%~f0"
