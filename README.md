# OpenPara

An open-source parametric CAD modeller written in Python (working title: *Gen Parametric Designer*).

- Parametric parts: sketches with a constraint solver, extrude / cut / revolve, fillet / chamfer, configurations
- Assemblies with mates and sub-assemblies
- Built-in simulations: 1D beam / frame FEA, 2D FEA, 2D CFD (results and slicing)
- Photorealistic renderer ("Renderer" tab): sun and sky from date / time / place, spot light, floor, several cameras, still pictures and MP4 videos (Mitsuba 3)

Built on [build123d](https://github.com/gumyr/build123d) (OpenCascade), PyQt6, pyvista / VTK, gmsh and Mitsuba 3.

## Run

Windows: double-click `run_modeller.bat` (installs the packages the first time), or

    pip install -r requirements.txt
    python gpd_app.py

The render studio can also run on its own: `run_render_studio.bat`.

## Guides

- `docs/README_modeller.txt` - how the modeller works
- `docs/README_render.txt` - the render studio

## Tests

Each `test_*.py` runs on its own, for example `QT_QPA_PLATFORM=offscreen python test_links.py`.

## Status

Early and in active development. Not everything is tested on every machine (for example CUDA rendering and the OptiX denoiser).

## License

GNU General Public License v3.0 - see `LICENSE`.
