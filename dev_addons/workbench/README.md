# Workbench (workshopping)

A project schematic in the style of ANSYS Workbench, as the first tab of Full dev mode. ONE project file (`.opara`, plain JSON) holds blocks on a canvas; each block is a part, an assembly, an analysis or one of the other tools, with cells (Geometry, Setup, Solution, Results ...) and a status mark on every cell: up to date, incomplete, refresh needed, update needed, failed. Wires join a cell that provides something (the geometry of a part) to a cell that takes it (the geometry of an analysis). Blocks snap to a 20-unit grid, a box selects several, a selection moves as one and the wires follow. Double-click a cell and its usual editor opens in a tab; what is done in the tab is read back into the project when you save it, come back to the Workbench, or press Update.

**Results, meshes and parametric outputs are not saved.** The project keeps what a person typed (the part, the supports, the loads, the mesh size ...). Opening a project never computes anything: the cells say "update" until you press Update Project. Big files are kept as files inside the project, not as links to other folders.

## The blocks

| Block | What it keeps | Editor |
|---|---|---|
| Part | the part (`.gpd` content) | the part window |
| Assembly | the assembly with its OWN COPY of every component (no live link to the Part blocks; Insert Component can copy from the project's parts) | the assembly window |
| 3D Static Structural, 3D Thermal | the analysis project folder without meshes and results | the 3D window |
| 2D Static Structural, 2D Fluid Flow, 2D Thermal, 1D Beam / Truss | the same | the 2D / 1D window |
| Sheets, Systems and Controls, Circuits | the document (`.opsheet`, `.opctl`, `.opcirc`) | the tool's tab |
| Truss Generator | the project folder (`project.json`, the sketch) | the Truss tab |

Wire a Part or Assembly block into an analysis: its Geometry cell says **refresh** whenever the part changes, and Refresh copies the part into the analysis (an assembly's copies are written as plain files first). A 2D analysis gets the part and you choose the sketch in its tab; a Refresh takes the same sketch again and keeps the supports and loads of a 2D Static Structural analysis that still fit.

Not wired yet (listed in the toolbox as "Not wired"): PDF editor, Visualize, Motor, Trainer, Annotator, Study. An analysis that takes the result of another analysis (thermal into structural) is not there.

## Buttons

- **Refresh Project**: copies the geometry again into every analysis whose part changed.
- **Update Project**: Refresh, then solve what is out of date, in the order of the wires. A cell that cannot be done says why.
- **Import...** / **Import Folder...**: a `.gpd` part, a `.gpa` assembly (its part files are read into it), an analysis folder (`.gpv .gpf ...`), `.opsheet .opctl .opcirc`, a `.truss` folder, or another `.opara` (its blocks are added next to the ones here).
- Right-click a block: **Save this system on its own...** writes the block as the ordinary file or folder it was (`.gpd`, `.gpa`, `.gpv` ...), which opens in the program like any other.
- **Load Example Project**: a bar, a plate and a frame with three analyses (3D structural, 2D structural, 3D thermal), one analysis deliberately left without a setup, and three tools. Press Update Project to solve the three.
- **Project Report**: every block and cell with its status, what Update would do, what is incomplete and why, and which editors are open.

## Files

`wb_project.py` (the project, its cells and their statuses, the file; no Qt), `wb_canvas.py` (the schematic), `wb_tab.py` (the tab, toolbar, toolbox, menus), `wb_nodes.py` (what each kind of block does), `wb_parts.py` (Part and Assembly), `wb_analysis.py` (the analyses), `wb_tools.py` (Sheets, Controls, Circuits, Truss, Drawing), `wb_import.py`, `wb_example.py`, `wb_icons.py`, `wb_ext.py`.
Tests (repository root): `test_wb_project.py`, `test_wb_canvas.py`, `test_wb_shell.py`, `test_wb_parts.py`, `test_wb_analysis.py`, `test_wb_2d.py`, `test_wb_tools.py`, `test_wb_drawing.py`, `test_wb_import.py`, `test_wb_example.py`, `test_asm_embed.py`.

Nothing here has been tried on real Windows: everything so far ran headless. The OpenGL views cannot draw there, so how the editors look inside the tabs has not been seen.
- **Layout**: blocks never overlap and keep a gap of 40 (a dragged block stops at its neighbour and slides along it; a new block goes to the nearest free place; a file from before the rule is moved apart when opened). Wires are horizontal and vertical pieces that run round the blocks (`wb_route.py`), never behind them.
- **Study -> Sheets**: the Results cell of a Parametric Study can be wired into the Study Results cell of a Sheets block. In that block's Sheets window, Data > Import study offers only the wired studies; Refresh / Update Project reads the imported tables again.
- **Drawing block** (Component Tools): its Models cell takes Part / Assembly blocks by wire; Open Drawing shows the sheet, model and projected views, scales, display styles and PDF export (`dev_addons/drawings`). Refresh / Update Project re-projects the views from the wired models and says which ones could not be rebuilt.
