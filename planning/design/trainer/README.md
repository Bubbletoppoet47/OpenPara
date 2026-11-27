# Trainer, Trained models and Model testing

**Status:** approved by Ian (he called these "the trainer mockups that we already did", 2026-11-26). Built to boards 2 and 3 locally, waiting for Ian to look (TRN-1, TRN-2 in `../../ISSUES.md`).

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

Rebuilt to boards 2 and 3 (`6dcdb6a`, `404d675`, local, not pushed): four pages, the kind as ribbon buttons, the layers table and the neurons-per-layer bars, every option of the PDF's network on the Model page, the classic regressors' tuning, and on the Train page the runs, the run now and live charts while a network trains, with Stop that finishes the run that is going first. It differs from the boards in five places (TRN-1 and TRN-2 in `../../ISSUES.md` list them): a *Models made here* list on the Train page, Start/Stop on both pages, the *Shape* read-out (`32 x 4` where the board says `8 : 1`), five rows that the PDF asks for and the board does not show, and a Log tab beside the live charts.

Spec behind the Model tab and the Train tab: `../spec/Distance_Model_Comparison_Handoff.pdf` (the model families and the network ladder in section 7, what the Trainer must do in section 9).

`source/` holds the board files. They need the Design artifact runtime to open (see `../README.md`); look at the pictures.
