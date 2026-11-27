# Combined Physics window

**Status:** built since `2ffb240` (2026-11-26). The boards were titled *Proposed*. No separate sign-off is recorded.

Hosted copy, interactive, on Ian's Claude account: <https://claude.ai/artifact/UxsE2hLb9hKVzTMTGBBdc2>

## Boards

| Picture | Board title | What it shows |
|---|---|---|
| `1-fluid-tab.png` | Proposed: Fluid tab | Air round a square body; the left wall at a fixed temperature, the other walls handed to the thermal analysis. |
| `2-thermal-tab.png` | Proposed: Thermal tab | The same body; the air's walls shown locked and dashed. |
| `3-structural-tab.png` | Proposed: Structural tab | A fixed support, the pressure and temperature from the other tabs as locked loads, the bent outline. |
| `4-coupled-tab.png` | Proposed: Coupled tab (the iterative solve) | Solve, the passes of the loop, the checks with PASS and FAIL. |
| `5-viz-tab.png` | Proposed: Viz tab (the rendered result, from the real example) | Layers, tracers, animation controls and the picture. |

Not filed: the *Today* board (four tabs with buttons that opened each analysis).

## What the boards decide

- **One window for the 2D analyses of one sketch,** with five tabs: *Fluid*, *Thermal*, *Structural*, *Coupled*, *Viz*. Each tab carries a mark: done, or needs updating.
- **Each analysis tab** has an Outline and a Details panel at the left and the model view at the right, like the other analysis windows.
- **Handed-over rows.** A condition that comes from another analysis is a lettered green row (B, C) and is locked in the tab that receives it. A note says where it comes from: the heat exchange with the air (from Fluid), the pressure of the air (from Fluid), the temperature (from Thermal).
- **Coupled tab.** *Solve* and *Cancel*, then the steps of the loop in order, a table of passes (largest displacement, change from the pass before) and the self-check with PASS or FAIL for each check, including a known-answer check.
- **Viz tab.** Layers as tick boxes (air temperature, tracers, body displacement, bent outline, air pressure, von Mises stress), the tracer settings, Play, Loop, Speed, a frame slider, Save image (PNG) and Save animation (MP4). Viz only shows the last solve; nothing in it changes the result.

## Where the build is

`2ffb240` (the window, the hand-overs, a Viz tab), `e9a58d7` (Viz draws a 3D heat and stress solve), `970764c` (heat-flux tracers for a heat and stress solve with no flow, and inside a 3D part; the heat-flux tracers are not on board 5). Open items: CPL-1 to CPL-4 in `../../ISSUES.md`.

Build specification of this window: `../spec/OpenPara_Combined_Physics_Window_Spec.pdf`.

`source/` holds the board files and the picture of board 5 (`source/_blob/`, referred to as `/_blob/<id>` in the HTML).
