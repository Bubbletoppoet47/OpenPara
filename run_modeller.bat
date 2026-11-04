@echo off
cd /d "%~dp0"
python -c "import build123d, pyvista, pyvistaqt, PyQt6, scipy" 2>nul || (
  echo Installing the packages once: build123d pyvista pyvistaqt PyQt6 scipy ...
  python -m pip install build123d pyvista pyvistaqt PyQt6 scipy
)
python gpd_app.py %*
pause
