# Annotator redesign

**Status:** the redesign Ian expects the Annotator to match (his screenshot of 2026-11-26 says it does not: ANN-1 in `../../ISSUES.md`). Layout A (Analyse as a ribbon tab) is the one that was built.

Hosted copy, interactive, on Ian's Claude account: <https://claude.ai/artifact/4EAKEnCLijgBBsTPML7fn1>

## Boards

| Picture | Board title | What it shows |
|---|---|---|
| `1-annotate-tab.png` | A · Annotate: ribbon on top, one side panel | The window as it opens, on the Annotate tab. |
| `2-analyse-tab.png` | A · Analyse as a ribbon tab (sample numbers) | The new Analyse tab: a model checked against the LiDAR on a recorded session. |
| `3-ribbon-tabs.png` | The five ribbon tabs | Every button on Annotate, Data, Models, Analyse and Setup. |
| `4-where-things-go.png` | Where every current button goes | Each old menu item, toolbar button and panel control, and where it went. |

Not filed here: the *Today* board (the old window with stand-in pictures) and board B, *Analyse from a mode rail on the left*, which was not chosen and not built. Board 4 still mentions B as the alternative to the Analyse tab.

## What the boards decide

- **A ribbon on top, like the Part window,** with five tabs: *Annotate*, *Data*, *Models*, *Analyse*, *Setup*. The window opens on Annotate. A badge and the project name sit at the right of the tab row.
- **One side panel** at the left. The *Classes* list is at the top and always visible, with the number of boxes per class. Below it, three icon tabs: *Frames* (working set, To do / All, the image list with thumbnails), *Selected box*, *AI assist*.
- **The picture area is dark,** with one hint line on the picture and the LiDAR depth caption. The paragraphs of help text that filled the old panels become hover tips.
- **The old menus (File, Edit, Manage) are gone.** Every item has a place in a ribbon tab (board 4). Buttons keep today's wording, shortened to fit under an icon.
- **Analyse** has Open session, Run analysis, Stop; Dots in boxes and All dots; Save frame image, Export CSV, Export report. The left panel shows the setup (session folder, model, confidence, pass band) and the results (closest point, median, average, boxes with no LiDAR, pass by distance). The picture shows each box with its dots and a pass or fail mark. A strip along the bottom shows every frame: teal when all boxes pass, orange when a box fails, grey when there is no LiDAR. The numbers on the board are samples.
- **The Analyse tab stays in the Annotator** until the Model testing block does everything it does (ANN-2).

## Where the build is

`b828756` (ribbon on top and one side panel, 2026-11-25) and `85513fc` (the Analyse tab, 2026-11-25). Differences from the boards are not listed yet (ANN-1).

`source/` holds the board files and the picture they use (`source/_blob/`, referred to as `/_blob/<id>` in the HTML).
