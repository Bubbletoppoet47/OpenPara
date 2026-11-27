# Design: approved mock-ups and the choices behind them

This folder keeps the designs we have agreed, as pictures you can open without anything else, with a short note on what each one decides. It is for looking things up: *what did we say this window would look like, and why?* The running list of what is open and done is `../ISSUES.md`.

`planning/` is not copied into the installer, and a push that changes only files in it does not start a build.

## Index

| Area | Folder | Status | Built in | Open items |
|---|---|---|---|---|
| Trainer, Trained models, Model testing, and the four blocks wired | [`trainer/`](trainer/README.md) | Approved by Ian, 2026-11-26. Built to the boards, local and not pushed; five differences for Ian to say are in its README | `88ab86b`, `01570a9`, `b03f554`, `d37321a`, `a25d364`, `612d624`; local: `6dcdb6a`, `404d675` | TRN-1, TRN-2 (done locally) |
| Annotator redesign (ribbon, side panel, Analyse tab) | [`annotator/`](annotator/README.md) | The redesign Ian expects. Built; the window now matches board 1 (local, not pushed); three differences for Ian to say are in its README | `b828756`, `85513fc`; local: `8b39da8` | ANN-1 (done locally), ANN-2 |
| Combined Physics window (Fluid, Thermal, Structural, Coupled, Viz) | [`combined-physics/`](combined-physics/README.md) | Built | `2ffb240`, `e9a58d7`, `970764c` | CPL-1 to CPL-4 |
| 2D Static Structural (material per region, Supports and Loads pages, Mesh page) | [`static-structural-2d/`](static-structural-2d/README.md) | Built | `320c6f4` | none |
| FEA Outline and Details (every analysis window) | [`fea-outline/`](fea-outline/README.md) | Outline and Details column built; whether each analysis matches the outline board is unchecked | `6324847` | none |
| Workbench look: the quiet header | [`workbench-look/`](workbench-look/README.md) | Option 3 of 4, built | `77f5c57` | none |
| Visualize node (Workbench block, result window, render studio, Export, what moves out of the simulation windows) | [`visualize/`](visualize/README.md) | Drawn 2026-11-26. Waiting for Ian to approve. Not built | none | VIS-1 |
| 3D view: look, hover and the geometry selector (part, assembly and 3D simulation windows) | [`viewport/`](viewport/README.md) | Asked for and confirmed by Ian, 2026-11-27. No boards (his reference was another program's screenshots, not filed). Built and pushed to `dev` the same day; Ian has not yet looked at it in a running window | `HASH` | VW-1 to VW-4 (done) |
| Theme and palette | [`theme/`](theme/README.md) | Written from the code; the plan approved by Ian 2026-11-26; swatch sheet not yet looked at by him | `tools/check_palette.py`, `test_palette.py` | GEN-5 |

**Status words.** *Approved* means Ian said so, with the date. *Built* means it is in the program, with the commit. A design that is built has no separate sign-off recorded unless it says *Approved*.

## Specifications

- [`spec/Distance_Model_Comparison_Handoff.pdf`](spec/Distance_Model_Comparison_Handoff.pdf): the distance-model comparison suite (three arms, the scoring harness, the network ladder, what the Trainer must do). Behind the Trainer boards and TRN-1.
- [`spec/OpenPara_Combined_Physics_Window_Spec.pdf`](spec/OpenPara_Combined_Physics_Window_Spec.pdf): the build specification of the Combined Physics window.

## What is in each folder

- `README.md`: status, a link to the hosted board, a table of the pictures, what the boards decide, where the build is.
- Numbered `.png` files: the boards, rendered at twice their size. These are what to look at. Example numbers on a board are example numbers.
- `source/`: the board files (HTML for the Design artifact type) and the pictures they use (`_blob/`, referred to as `/_blob/<id>` in the HTML). They need that type's runtime to open, and the runtime is not kept here. Open the hosted copy instead, or render them with `tools/render_boards.py`.

The hosted copies are on Ian's Claude account; the links open for him.

## Filing a new design

1. Render the boards with `tools/render_boards.py` (scale 2) and look at every picture. A board that rendered blank or without its pictures is not filed.
2. Make `planning/design/<area>/` with the numbered PNGs, `source/` and a `README.md` like the others: status, hosted link, pictures, what the boards decide, where the build is.
3. Add a row to the index above.
4. Point the open items in `../ISSUES.md` at the folder.
5. Run `python tools/check_palette.py` on every new icon, stylesheet or screen that goes with the design, and look at the swatches in [`theme/`](theme/README.md): the board uses the program's palette, or says in its README which colours it adds and why.
6. Write *Approved* only when Ian said so, with the date. Do not delete a design that is replaced: change its status to *Replaced by* and say what by. Git keeps the history either way.

## Not filed

Boards that show the old window (*Today* in the Annotator and Combined Physics designs), board B of the Annotator (the rail, not chosen), options 1, 2 and 4 of the Workbench look, and two design artifacts on Ian's account that were not part of this: *Annotator logo options* and *OpenPara icon looks*.
