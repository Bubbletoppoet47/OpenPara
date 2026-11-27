# Visualize node

**Status:** drawn 2026-11-26 from Ian's decisions on VIS-1 (`../../ISSUES.md`). **Waiting for Ian to approve** before anything is built. Not *Approved* yet.

Hosted copy, interactive, on Ian's Claude account: <https://claude.ai/artifact/6CUNc7WPchrP1nXatpZpDo>

## Boards

| Picture | Board title | What it shows |
|---|---|---|
| `1-workbench-two-nodes.png` | 1 · Workbench: two Visualize nodes | A part wired to a Visualize node (render studio) and Coupled Physics wired to another (result view). A second analysis wired to the same input is refused. The cells of the node and what each can show. |
| `2-result-window.png` | 2 · Visualize window: a simulation result | The result view: the dark vacuum picture, the colour bar, the Result, Look and Rotation cards, and one timeline for the result frames and the turn. |
| `3-render-studio-window.png` | 3 · Visualize window: a part or an assembly | Today's render studio, with the two differences that come from the wire. |
| `4-export-tab.png` | 4 · Visualize window: Export | Format, size, speed, file name, the dashed picture frame, the summary and a progress bar. |
| `5-what-moves.png` | 5 · What moves out of the simulation windows | The Animate box before and after, and each simulation window with the button that moves. |

The numbers and the picture on the boards are examples.

## What the boards decide

- **Block on the Workbench.** `Visualize` stays in *Component Tools* and becomes a block with cells *Input*, *Setup*, *Kept copy* and *Export*. *Input* takes one wire. A small label on the title row says which mode it is in (*Render studio* or *Result view*). Board 1.
- **One input, enforced.** A second wire to the same input is refused, and the block says why. To show two analyses together, wire both into one Coupled Physics block (VIS-1 point 1).
- **Two modes, by the input** (VIS-1 point 2). A part, geometry or assembly opens the render studio. A simulation result opens the result view.
- **Its own copy** (VIS-1 point 3). *Kept copy* shows what the copy adds to the project file. When the simulation was run again the cell shows an orange *source changed* mark; the node changes only when the person updates it (the node's Update, or Update Project). Opening a project changes nothing.
- **Result view** (board 2). A ribbon with *Play*, *Loop*, *Speed*; the start views *Iso*, *Front*, *Top*, *Right*, *Fit to screen*; *Update result* and *Open simulation*. Two tabs: *View* and *Export*.
  - *Result* card: the one field the node took (read-only), its source, frame count, size in the project, when it was copied, and *Update from simulation* (VIS-1 point 4).
  - *Look* card: *Dark*, *White* or *Custom* background, colour bar, edges, axis symbol. No lights, no sky, no floor: the vacuum look.
  - *Rotation* card: animation length, number of rotations (0 gives a still picture in the chosen view), axis X, Y, Z or a direction entered as x, y, z, and the start view (VIS-1 point 6).
  - One timeline holds the result frames (a tick for each saved frame, no cap: VIS-1 point 7) and the turn (0 to 360 degrees), with one playhead.
- **Render studio** (board 3) is today's window: Scene, Appearance, Sun and sky, Spot light, Floor, Cameras, Preview, Render. Two things change: *Import source...* goes, because the wire is the source; and the Scene section shows the size of the copy in the project.
- **Export** (board 4). *Animation* or *Still picture*. Formats are the six `anim_export.py` writes today: MP4, GIF, WebP and APNG (the last two with a transparent background), PNG pictures one per frame, PNG pictures with a transparent background. Size, frames per second, quality, playback (once, loop, back and forth), file name and folder (inside the project by default). A summary says the size, frames and time before writing; a progress bar and Cancel show while it writes.
- **What moves** (board 5, VIS-1 point 5). The seven simulation windows keep the basic view, the field choice and the Animate preview. *Export animation...* (and in the Coupled Physics Viz tab *Save image* and *Save animation...*) moves to the node. The auto-turn of the Viz tab goes (CPL-5).
- **Style** (VIS-1 point 9). The boards use the program's palette (`../theme/`) and the ribbon of the Annotator window. The one colour not in the palette is the dark picture background `#1b1f27` and the viridis colour bar, which are the picture, not the window.

## For Ian to say

1. **Background of the vacuum look.** The boards draw it dark. Today's simulation windows draw on white. The *Look* card has *Dark / White / Custom...* so either can be the default. Which should it open with?
2. **Open simulation** in the ribbon of the result view is mine, not in your list: it opens the window the result came from, to change the field before updating. Keep or drop?
3. **Two tabs** (*View* and *Export*), with the rotation settings on *View*. Or a third tab for *Rotation*?
4. **Estimates** on the Export tab (size about 9 MB, about 25 s to write) are examples. They would be worked out from the frames and the format; say if you would rather not see them.

## Where the build is

Not started. When approved it is built in steps, each with its own item (VIS-1 *Fixed when*). CPL-5 (remove the auto-turn) does not wait for this.

`source/` holds the board files for the Design artifact type. They need that type's runtime to open; open the hosted copy instead.
