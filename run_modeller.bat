@echo off
cd /d "%~dp0"
python -c "import build123d, pyvista, pyvistaqt, PyQt6, gmsh, scipy, mitsuba, imageio_ffmpeg" 2>nul || (
  echo Installing the packages once: build123d pyvista pyvistaqt PyQt6 gmsh scipy mitsuba imageio-ffmpeg ...
  python -m pip install build123d pyvista pyvistaqt PyQt6 gmsh scipy mitsuba imageio-ffmpeg
)
python gpd_app.py %*
pause
