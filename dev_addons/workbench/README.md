# Workbench (workshopping)

A project schematic in the style of ANSYS Workbench, as the first tab of Full dev mode. ONE project file (`.opara`, plain JSON) holds blocks on a canvas; each block is a part, an assembly, an analysis or one of the other tools, with cells (Geometry, Setup, Solution, Results ...) and a status mark on every cell: up to date, incomplete, refresh needed, update needed, failed. Wires join a cell that provides something (the geometry of a part) to a cell that takes it (the geometry of an analysis). Blocks snap to a 20-unit grid, a box selects several, a selection moves as one and the wires follow. Double-click a cell and its usual editor opens in a tab; what is done in the tab is read back into the project when you save it, come back to the Workbench, or press Update.

**Results, meshes and parametric outputs are not saved.** The project keeps what a person typed (the part, the supports, the loads, the mesh size ...). Opening a project never computes anything: the cells say "update" until you press Update Project. Files are kept inside the project, not as links to other folders; the one exception is the Annotator block, whose dataset is too big and stays in its own folder (the block keeps the link).

## The blocks

| Block | What it keeps | Editor |
|---|---|---|
| Part | the part (`.gpd` content) | the part window |
| Assembly | the assembly with its OWN COPY of every component (no live link to the Part blocks; Insert Component can copy from the project's parts) | the assembly window |
| 3D Static Structural, 3D Thermal, 3D Fluid Flow | the analysis project folder without meshes and results (3D Fluid Flow takes one Part, not an Assembly; its Setup is offered to Coupled Physics) | the 3D window |
| 2D Static Structural, 2D Fluid Flow, 2D Thermal, 1D Beam / Truss | the same | the 2D / 1D window |
| Coupled Physics | a heat analysis and a stress analysis of the same geometry (both 2D or both 3D), solved together; the project folder holds the options only | the Coupled Physics window (`dev_addons/coupled`) |
| Sheets, Systems and Controls, Circuits | the document (`.opsheet`, `.opctl`, `.opcirc`) | the tool's tab |
| Truss Generator | the project folder (`project.json`, the sketch) | the Truss tab |
| PDF Editor (no wires) | a folder of the PDFs and page projects (`.oppb`) that are open in it: a PDF opened from anywhere else is COPIED into it (the original is never changed; one copy however often it is opened; past 150 MB of PDFs a file opens where it is and is not kept), a new page project has its file in the folder from the start and names its PDFs relative to itself | the PDF editor tab |
| Annotator (no wires) | a LINK to the annotator project folder (`{"abs", "rel"}`), never a copy: a dataset is photos and video frames. A new block starts on a project in a temporary folder, as the annotator does on its own; when the project is saved to a folder (File > Save in the window) the block takes that folder, and follows the window after Save As. Importing or boxing pictures is a change of the cell; a folder that moved is asked for. Save this system on its own copies the folder | the annotator tab |

Wire a Part or Assembly block into an analysis: its Geometry cell says **refresh** whenever the part changes, and Refresh copies the part into the analysis (an assembly's copies are written as plain files first). A 2D analysis gets the part and you choose the sketch in its tab; a Refresh takes the same sketch again and keeps the supports and loads of a 2D Static Structural analysis that still fit.

Not wired yet (listed in the toolbox as "Not wired"): Visualize, Motor, Trainer. The PDF Editor and the Annotator are blocks with no wires in or out (a Trainer block will take a wire from the Annotator block later: the block keeps its dataset folder as a link so that a wire can hand it on). A Coupled Physics block takes the Setup cells of one Thermal and one Static Structural block (same dimension, same Part or Assembly) in its Physics cell: Update solves the heat analysis, hands its temperature to the stress analysis and solves that; it can also take one Fluid Flow block of the same dimension, 2D or 3D (heat exchange with the solid, pressure on the stress analysis, and, when ticked, the structure moving the flow). The analyses are set up in their own windows (no tabbed single window yet; see `dev_addons/coupled/README.md`).

## Buttons

- **Refresh Project**: copies the geometry again into every analysis whose part changed.
- **Update Project**: Refresh, then solve what is out of date, in the order of the wires. A cell that cannot be done says why.
- **Import...** / **Import Folder...**: a `.gpd` part, a `.gpa` assembly (its part files are read into it), an analysis folder (`.gpv .gpf ...`), `.opsheet .opctl .opcirc`, a `.truss` folder, or another `.opara` (its blocks are added next to the ones here).
- Right-click a block: **Save this system on its own...** writes the block as the ordinary file or folder it was (`.gpd`, `.gpa`, `.gpv` ...), which opens in the program like any other.
- **Load Example Project**: a bar, a plate and a frame with three analyses (3D structural, 2D structural, 3D thermal), one analysis deliberately left without a setup, a heated bar (**Bar heating**, **Bar growth**, **Bar thermal stress**: a Coupled Physics block whose known answer, the far end of the bar growing 0.048 mm, is checked and shown as PASS or FAIL), a 20 mm square in slow air (**Square**, **Air flow**, **Square heat**, **Square bending**, **Air, heat and bending**: the flow, the heat exchange and the bending of the square in one Coupled Physics block, the structure moving the flow, with a known answer of walls at 50 degC), a 30 mm copper block in 3D air (**Block**, **Block air flow**, **Block heat**, **Block pressure**, **Air, heat and pressure 3D**: the same three in 3D, with a known answer of walls at 70 degC; two soft checks of the flow, its energy balance and its temperature range, are expected to show FAIL on its coarse mesh and say so), a parametric study and three tools. Press Update Project to solve them.
- **Project Report**: every block and cell with its status, what Update would do, what is incomplete and why, and which editors are open.

## Files

`wb_project.py` (the project, its cells and their statuses, the file; no Qt), `wb_canvas.py` (the schematic), `wb_tab.py` (the tab, toolbar, toolbox, menus), `wb_nodes.py` (what each kind of block does), `wb_parts.py` (Part and Assembly), `wb_analysis.py` (the analyses), `wb_tools.py` (Sheets, Controls, Circuits, Truss, Drawing, PDF Editor, Annotator), `wb_import.py`, `wb_example.py`, `wb_icons.py`, `wb_ext.py`.
Tests (repository root): `test_wb_project.py`, `test_wb_canvas.py`, `test_wb_shell.py`, `test_wb_parts.py`, `test_wb_analysis.py`, `test_wb_2d.py`, `test_wb_tools.py`, `test_wb_drawing.py`, `test_wb_import.py`, `test_wb_example.py`, `test_wb_fluid3d.py`, `test_wb_coupled_flow3d.py`, `test_wb_pdf_annotator.py`, `test_asm_embed.py`.

Nothing here has been tried on real Windows: everything so far ran headless. The OpenGL views cannot draw there, so how the editors look inside the tabs has not been seen.
- **Layout**: blocks never overlap and keep a gap of 40 (a dragged block stops at its neighbour and slides along it; a new block goes to the nearest free place; a file from before the rule is moved apart when opened). Wires are horizontal and vertical pieces that run round the blocks (`wb_route.py`), never behind them.
- **Study -> Sheets**: the Results cell of a Parametric Study can be wired into the Study Results cell of a Sheets block. In that block's Sheets window, Data > Import study offers only the wired studies; Refresh / Update Project reads the imported tables again.
- **Drawing block** (Component Tools): its Models cell takes Part / Assembly blocks by wire; Open Drawing shows the sheet, model and projected views, a scale and a display style for each view, dimensions (you pick the type first: Horizontal, Vertical, Length / distance, Diameter, Radius, Angle; always the model's true values), center marks, centerlines, notes (text, size, straight or bent leader), balloons, lines / rectangles / circles / arcs drawn on the sheet, and PDF export (`dev_addons/drawings`). Refresh / Update Project re-projects the views from the wired models and says which ones could not be rebuilt.
