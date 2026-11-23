# OpenPara Updater

A small separate program that does one job: put the right build of OpenPara (or the OpenPara Playground) in the program folder, and tell you when a
build does not start. It is the only thing that replaces the program files. It uses nothing of OpenPara's own code, so it still works when OpenPara
cannot start.

The installer puts it next to the program:

```
<install folder>\python\            the bundled Python (OpenPara.exe is a renamed pythonw.exe)
<install folder>\app\               the program files (replaced by an update)
<install folder>\updater_tool\      this tool
```

Start it from the Start menu (**OpenPara Updater** / **OpenPara Playground Updater**) or from OpenPara: Help > Open the updater.

## What the window does

| Button | What it does |
| --- | --- |
| Update to the newest | puts in the newest build of *this* program (OpenPara: the newest release; Playground: the newest dev build) |
| Install / Go back to the selected build | any build of this program on GitHub, newer or older. The list shows the last 5; **Show all** shows every earlier build. |
| Repair | downloads the build that is installed and puts it in again (also sets the add-ons you have installed back to that build's code) |
| Start safely | starts the program with every add-on off and, in the Playground, in Testing mode; nothing is installed or saved. For this run only. |
| Copy report | the versions, the add-ons, and the end of the updater log, the error log and the crash log, ready to paste into a message |

* **A rollback only happens when you press the button.** When a build does not start properly the window says so and *offers* "Go back to ..."; it never does it by itself.
* The two programs never mix: OpenPara lists only releases (`v0.x.y`), the Playground only dev builds (`dev-0.x.y.z`).
* Going back to an earlier build also puts that build's add-on code back (from the same GitHub release) for the add-ons you have installed, so the add-ons
  and the program match. The packages an add-on downloaded (its `site\` folder) are kept. A forward update leaves add-ons alone: the program offers to update them.
* A build that needs a different bundled Python / packages ("runtime") cannot be put in as a program zip. The window says so and offers to download and start
  that build's full installer.
* The program files being replaced are kept as `app.old` until the new build has said it started fine; "Go back" right after a failed start uses that
  copy and downloads nothing.
* Your settings, projects and add-on packages live in `%LOCALAPPDATA%\OpenPara` (or `OpenPara Playground`) and are not touched.

## How it knows a build started fine

The updater starts the program with `OPARA_START_TOKEN`. The program writes `run_state.json` in its data folder at once (`ok: false`) and `ok: true`
a few seconds after its window is up (`runstate.py`). No note within two minutes, or the program closing first, counts as "did not start properly". A start-up
error is written to `gpd_error.log`, a hard crash (a fault inside Qt or a DLL) to `gpd_crash.log`.

## Command line

```
OpenPara.exe updater_tool\openpara_updater.py                          the window
... --cli --list [--all]      --cli --report
... --cli --update            --cli --install 0.8.5       --cli --repair       --cli --go-back
... --cli --start             --cli --start-safe          (add --no-start to an install job to leave the program closed)
... --update-to 0.8.7 --wait-pid 1234                     the window; installs once process 1234 (OpenPara) has closed, then starts it ("Update now" in OpenPara)
```

Exit codes of `--cli`: 0 done, 1 a problem (the text says which), 2 that build needs its full installer, 3 the program did not start properly.

## Updating the updater

A newer version of this tool travels inside the program (`app\updater_tool\`). When the updater starts and that copy is newer, it replaces this folder, runs the
new copy's self-test and keeps the old folder as `updater_tool.bak`; if the self-test fails the old folder is put back. An install that was updated inside
the program (without the installer) gets the folder from `app\updater_tool\` when the program starts.

## Tests

`test_updater_tool.py` (core, command line, hand-off), `test_updater_window.py` (the window, offscreen), `test_updater_menu.py` and `test_start_run_state.py`
(the real program's start note) run against a fake GitHub on localhost. Nothing touches the real GitHub.
