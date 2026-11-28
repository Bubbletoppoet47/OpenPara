# Slicer in OpenPara: the integration plan

**Status.** Stage 1 (the plan) is written: Draft 1, 2026-11-28. Ian asked for it on 2026-11-27 and, going to bed on 2026-11-28 at 00:03, said to go on into Stage 2 once it was done and push to `dev`. He has **not read this draft**. Stage 2 (the build) starts from it; where Ian has not answered a decision, chapter 14.1's default is used and written down (below).

**The idea.** Embed Orca Slicer's own slicing engine inside OpenPara, not as a separate program, with the same workflow as Orca, so that a Part or Assembly can go to a Slicer block and its toolpaths can feed a printed-part (anisotropic) analysis. The first printer is the Elegoo Centauri Carbon with Elegoo filament presets; any printer should work.

## Files

| File | What it is |
|---|---|
| [`OpenPara_Slicer_Integration_Plan.pdf`](OpenPara_Slicer_Integration_Plan.pdf) | The plan: 55 pages. Start here. Chapter 1 is the plan on two pages |
| [`PLAN.md`](PLAN.md) | The same text in Markdown. This is the document; the PDF is made from it |
| [`build_pdf.py`](build_pdf.py) | Makes the PDF from `PLAN.md` and `figures/` (`python build_pdf.py`; needs `markdown-it-py` and Playwright with Chromium) |
| [`figures/`](figures/) | The three pictures (`.mmd` source and `.png`, made with `mmdc -c figures/mmd_config.json -i X.mmd -o X.png -s 2 -b white -w 1500`) |
| [`evidence/`](evidence/README.md) | What was run to check the plan: the trial compile of Orca's engine, the script that prints the Elegoo preset tables |

## What the plan decides (chapter 1.2, D1 to D8)

Compile a cut-down copy of Orca's `libslic3r` with a pybind11 wrapper (module `orca_core`); three levels of use (a whole job, a staged session, single tools); results copied into numpy tables; slicing in a separate worker process; delivered as a Windows wheel through a new `slicer` add-on (hidden in `NOT_RELEASED` until released); the window rebuilt in OpenPara's style with settings pages generated from Orca's option list; Orca's profiles shipped unchanged; Orca's own release used only as the test oracle, never shipped; the module is an AGPL-3.0 derivative with public source.

## What was and was not checked

Checked: Orca's source read (commit `1044ef4407d7`, 2.6.0-dev; latest stable tag then `v2.5.2`); the engine's source files compiled one by one here (compile only); Elegoo presets read and tabulated.
**Not** done: the engine has not been linked or run; nothing was built or run on Windows; Orca's own program was not run; no real print; the anisotropic analysis's accuracy is unknown. The licence reading (GPL-3.0 and AGPL-3.0) is mine and is not legal advice.

## Decisions waiting for Ian, and what is used until he answers

Chapter 14.1 has twelve. Defaults in use: D1 to D8 accepted; newest stable Orca tag that has the Centauri Carbon presets (check `v2.5.2` first); block in the *Component Tools* group; results not saved with the project; original Centauri Carbon, 0.4 nozzle, Elegoo PLA; engine build files in `engines/orca_core/` of this repository (patches, bindings and build files only; Orca's source is fetched by the workflow, never copied in); development behind `NOT_RELEASED` until the licence reading is confirmed; one plate first; names `slicer`, `orca_core`, block "Slicer". Any change Ian makes later is cheaper the earlier it is made.

## Where the work is

Open items are `SLC-0` to `SLC-12` and `PA-1` to `PA-5` in [`../../ISSUES.md`](../../ISSUES.md). Each item there says what it needs and how we will know it is done.

## Changing this document

Edit `PLAN.md`, add a line to its revision log, run `python build_pdf.py`, and commit `PLAN.md`, the figures and the PDF together. Planning-only pushes do not start a build.
