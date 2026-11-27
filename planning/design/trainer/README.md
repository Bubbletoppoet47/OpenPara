# Trainer, Trained models and Model testing

**Status:** approved by Ian (he called these "the trainer mockups that we already did", 2026-11-26). Partly built; the build does not look like the boards yet (TRN-1, TRN-2 in `../../ISSUES.md`).

Hosted copy, interactive, on Ian's Claude account: <https://claude.ai/artifact/QYgZwSXJrNatemHwBkNntQ>

## Boards

| Picture | Board title | What it shows |
|---|---|---|
| `1-workbench-four-blocks.png` | 1 · Workbench: four nodes wired | The Workbench with A Annotator, B Trainer, C Trained models, D Model testing, and the wires between them. |
| `2-trainer-model-tab.png` | 2 · Trainer window, Model tab | The ribbon picks the kind of model; the tab holds the layers, the learning settings and the data. |
| `3-trainer-train-tab.png` | 3 · Trainer window, Train tab | Seeds and learning rates, the list of runs, and two live charts. |
| `4-trained-models.png` | 4 · Trained models window | One list of every model, and the details of the selected one. |
| `5-model-testing.png` | 5 · Model testing window | Several models checked against the LiDAR on the same frames. |

The numbers on the boards are example numbers.

## What the boards decide

- **Wires.** The Annotator's *Dataset* and *Distances* go into the Trainer's *Dataset* and *Distances* (Distances is optional). The Trainer's *Models* goes into Trained models. Trained models' *Models* goes into Model testing, which takes any number of models.
- **Layout.** The Trainer window uses the Annotator's layout: a ribbon on top, tabs *Data*, *Model*, *Train*, *Setup*, a status bar at the bottom.
- **Model tab.** The ribbon chooses the kind: *Detector*, *Detector + distance*, *Distance: classic*, *Distance: network*. Under *Distance: network* the tab shows the layers as a table, the learning settings (recipe, loss, optimiser, learning rate, weight decay, epochs, stop early, batch norm) and a bar chart of neurons per layer. *Parameters* and *Shape* are read-outs in the ribbon.
- **Train tab.** *Seeds* times *Learning rates* is the number of runs. The tab lists the runs and draws median relative error (with the target as a dashed line) and gradient norm per layer. Saturated and dead units is an optional third chart.
- **Trained models.** One list of every model: kind (detector, detector + distance, distance only), size, where it is stored (*Inside project* or *Linked*), date, and which Trainer made it. Buttons: Import model, Import folder, Export, Rename, Remove. Models live inside the `.opara` (embedded up to 500 MB, linked above that). Models are not pushed to GitHub.
- **Model testing.** It is the Annotator's Analyse tab as a block of its own. Tick any number of models, choose which model draws the boxes, choose the test data, set confidence and the pass band, press Run. Results are per model (closest point, median, average) and per distance band.
- **Setup** stays a tab of the Trainer. **Update Project** never trains or runs a model.

## Where the build is

Built so far: the window in the Annotator's layout (`88ab86b`), the wires from the Annotator (`01570a9`), Trained models (`b03f554`), Model testing (`d37321a`, `a25d364`), the distance-only model types (`2094ed2` to `8cc6d65`), the Charts tab (`612d624`), models inside the `.opara` (`684ccda`).

Not matching yet: Ian's screenshot of 2026-11-26 shows five tabs (*Data*, *Model*, *Models*, *Train*, *Setup*) where boards 2 and 3 have four. The full comparison is TRN-2; the neural-network options of the PDF are TRN-1.

Spec behind the Model tab and the Train tab: `../spec/Distance_Model_Comparison_Handoff.pdf` (the model families and the network ladder in section 7, what the Trainer must do in section 9).

`source/` holds the board files. They need the Design artifact runtime to open (see `../README.md`); look at the pictures.
