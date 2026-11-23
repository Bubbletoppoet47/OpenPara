"""
openpara_updater.py - starts the OpenPara Updater (the window), or runs one job from the command line.

    python\\OpenPara.exe updater_tool\\openpara_updater.py                      the window
    ... --update-to 0.8.7 --wait-pid 1234                                      the window; installs 0.8.7 as soon as process 1234 (the program) has closed,
                                                                               then starts the program ("Update now" in OpenPara does this)
    ... --cli --list [--all]            the builds on GitHub          --cli --report         the text of the report
    ... --cli --update                  the newest build              --cli --install 0.8.5  one build (an earlier one = going back; add-ons set back too)
    ... --cli --go-back                 the saved copy of the earlier program (no download)   --cli --repair   the same build again
    ... --cli --start | --start-safe    start the program and wait for its "started fine" note
    --root FOLDER and --channel playground|release say which installation (default: the folder above this one).

Nothing here imports OpenPara's own code.  The installer puts this folder next to python\\ and app\\; a later version of the tool comes inside the program
(app\\updater_tool\\) and replaces this folder the next time the updater starts (the old one is kept as updater_tool.bak and put back if the new one fails
its self-test).  Exit codes of --cli: 0 done, 1 a problem (the text says which), 2 that build needs its full installer, 3 the program did not start properly.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)                 # the embedded Python does not put the script's folder on sys.path

for _n in ("stdout", "stderr"):              # pythonw.exe: no console, no streams
    if getattr(sys, _n, None) is None:
        try:
            setattr(sys, _n, open(os.devnull, "w", encoding="utf-8"))
        except OSError:
            pass

REQUIRED = ("ou_core.py", "ou_window.py", "openpara_updater.py")


# ---------------------------------------------------------------------------------------------------- the tool refreshes itself from the program
def tool_version_of(folder):
    try:
        with open(os.path.join(folder, "ou_core.py"), encoding="utf-8") as f:
            m = re.search(r"^TOOL_VERSION\s*=\s*(\d+)", f.read(), re.M)
        return int(m.group(1)) if m else 0
    except OSError:
        return 0


def check_syntax(path):
    """Raises SyntaxError when a .py file does not compile (nothing is written)."""
    with open(path, "rb") as f:
        compile(f.read(), path, "exec")


def refresh_from_app(tool_dir, app_tool_dir):
    """The program carries the newest version of this tool in app\\updater_tool\\.  When that one is newer, it replaces this folder - but only after its own
    self-test passed; otherwise the folder stays as it is.  -> True when the folder was replaced."""
    if not os.path.isdir(app_tool_dir) or os.path.abspath(app_tool_dir) == os.path.abspath(tool_dir):
        return False
    if any(not os.path.isfile(os.path.join(app_tool_dir, n)) for n in REQUIRED):
        return False
    if tool_version_of(app_tool_dir) <= tool_version_of(tool_dir):
        return False
    new, bak = tool_dir + ".new", tool_dir + ".bak"
    try:
        shutil.rmtree(new, ignore_errors=True)
        shutil.copytree(app_tool_dir, new, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for n in os.listdir(new):
            if n.endswith(".py"):
                check_syntax(os.path.join(new, n))
        shutil.rmtree(bak, ignore_errors=True)
        os.replace(tool_dir, bak)
        try:
            os.replace(new, tool_dir)
        except OSError:
            os.replace(bak, tool_dir)
            raise
    except Exception:                                                  # noqa: BLE001 - whatever went wrong, the folder stays (or is put back) as it was
        shutil.rmtree(new, ignore_errors=True)
        return False
    ok = False
    try:
        r = subprocess.run([sys.executable, os.path.join(tool_dir, "openpara_updater.py"), "--selftest"], capture_output=True, timeout=60, stdin=subprocess.DEVNULL,
                           env=dict(os.environ, OPARA_UPDATER_REFRESHED="1"))
        ok = r.returncode == 0
    except Exception:                                                  # noqa: BLE001
        ok = False
    if not ok:                                                         # the new tool does not even start: the old one comes back
        shutil.rmtree(tool_dir, ignore_errors=True)
        os.replace(bak, tool_dir)
        return False
    return True


def selftest():
    import ou_core
    check_syntax(os.path.join(HERE, "ou_window.py"))
    try:
        import PyQt6.QtWidgets                                          # noqa: F401
    except ImportError:
        pass                                                           # no Qt: the plain message-box way is used (run_plain); nothing more to check
    else:
        import ou_window                                               # noqa: F401 - must import with the Qt that is installed
    assert ou_core.vkey("dev-0.8.6.115") == (0, 8, 6, 115)
    print(f"updater tool {ou_core.TOOL_VERSION} ok")
    return 0


# ---------------------------------------------------------------------------------------------------- command line jobs
def say(text=""):
    try:
        print(text, flush=True)
    except Exception:                                                  # noqa: BLE001
        pass


def build_named(builds, version):
    v = str(version).strip()
    for b in builds:
        if v in (b["version"], b["tag"]):
            return b
    return None


def wait_program_closed(core, inst, pid, timeout):
    if pid and not core.wait_for_exit(pid, timeout=timeout):
        raise core.UpdaterError(f"The program (process {pid}) is still running; close it first.")
    if core.program_running(inst):
        raise core.UpdaterError(f"{inst.name} is running; close it first (the program files cannot be replaced while it is open).")


def start_and_wait(core, inst, safe, wait):
    import uuid
    token = uuid.uuid4().hex
    proc = core.launch(inst, token=token, safe=safe)
    core.log_line(inst, f"started the program (safe={safe}, pid {proc.pid})")
    outcome, secs, detail = core.wait_started(inst, proc, token, timeout=wait)
    core.log_line(inst, f"start result: {outcome} after {secs:.1f}s {detail}")
    if outcome == "ok":
        say(f"{inst.name} {inst.version} started fine ({secs:.1f} s).")
        if not safe:
            core.discard_saved_copy(inst)
        return 0
    if outcome == "running":                                           # an old build that cannot report back: no verdict, and the safety copy stays
        say(f"{inst.name} {inst.version}: {detail}")
        return 0
    say(f"{inst.name} {inst.version} did not start properly: {detail}")
    saved = inst.saved_version()
    if saved:
        say(f"The earlier program {saved} is kept; put it back with:  --cli --go-back")
    return 3


def run_cli(args):
    import ou_core as core
    inst = core.find_install(args.root, args.channel)
    if not core.take_lock(inst):
        say("Another updater is already running for this installation.")
        return 1
    try:
        wait = float(os.environ.get("OPARA_UPDATER_WAIT", "120"))
        if args.report:
            say(core.report_text(inst))
            return 0
        if args.list:
            builds = core.list_builds(inst)
            cur = inst.version
            for b in (builds if args.all else builds[:core.SHOW_FIRST]):
                say(f"{b['version']:<18} {b['date']}  {'installed' if b['version'] == cur else ''}")
            if not args.all and len(builds) > core.SHOW_FIRST:
                say(f"({len(builds) - core.SHOW_FIRST} earlier builds; --all shows them)")
            return 0
        if args.start or args.start_safe:
            wait_program_closed(core, inst, args.wait_pid, wait)
            if args.start_safe and not core.supports_safe_start(inst):
                say(f"{inst.name} {inst.version} is older than the safe start: it would start with its add-ons on, so it was not started.")
                return 1
            return start_and_wait(core, inst, bool(args.start_safe), wait)
        if args.update or args.install or args.go_back or args.repair or args.update_to:
            wait_program_closed(core, inst, args.wait_pid, wait)
            cur = inst.version
            progress = lambda text, frac=None: say(text) if text else None
            log = lambda t: core.log_line(inst, t)
            if args.go_back:
                saved = inst.saved_version()
                if not saved:
                    raise core.UpdaterError("There is no saved copy of an earlier program on this computer.")
                try:
                    builds = core.list_builds(inst)
                except core.UpdaterError:
                    builds = []                              # going back to the saved copy needs no download; only the add-on code does
                b = build_named(builds, saved) or {"version": saved, "tag": saved, "date": "", "app": None, "setup": None, "addons": {}}
                restore = True
            else:
                builds = core.list_builds(inst)
                if not builds:
                    raise core.UpdaterError("GitHub has no builds of this program.")
                if args.repair:
                    b = build_named(builds, cur or "")
                    if b is None:
                        raise core.UpdaterError(f"Build {cur} is not on GitHub any more; choose another build.")
                    restore = True
                elif args.update:
                    b = builds[0]
                    restore = False
                    if cur is not None and core.vkey(cur) >= core.vkey(b["version"]):
                        say(f"{inst.name} {cur} is already the newest build.")
                        return 0
                else:
                    want = args.install or args.update_to
                    b = build_named(builds, want)
                    if b is None:
                        raise core.UpdaterError(f"Build {want} was not found on GitHub.")
                    restore = cur is not None and core.vkey(b["version"]) < core.vkey(cur)
            say(f"{inst.name}: {cur} -> {b['version']}" + (" (add-ons of that build are put back)" if restore else ""))
            core.log_line(inst, f"cli install {b['version']} (was {cur}), add-ons restored: {restore}")
            try:
                res = core.install_build(inst, b, restore_addons_too=restore, progress=progress, log=log)
            except core.NeedsInstaller as ex:
                say(str(ex))
                say("Its full installer: " + ((b.get("setup") or {}).get("browser_download_url") or core.RELEASES_PAGE))
                return 2
            ad = res.get("addons")
            if ad:
                say(f"Add-ons put back: {', '.join(ad['restored']) or 'none'}" + (f"; could not: {', '.join(ad['failed'])}" if ad["failed"] else ""))
            say(f"{inst.name} {inst.version} is installed" + (" (from the saved copy)." if res["saved"] else "."))
            if args.no_start:
                return 0
            return start_and_wait(core, inst, False, wait)
        say("Nothing to do: give one of --list --report --update --install --go-back --repair --start --start-safe")
        return 1
    except core.UpdaterError as ex:
        say(str(ex))
        core.log_line(inst, "FAILED: " + str(ex))
        return 1
    finally:
        core.drop_lock(inst)


# ---------------------------------------------------------------------------------------------------- the window
def run_window(args):
    import ou_core as core
    inst = core.find_install(args.root, args.channel)
    if not core.take_lock(inst):
        core.message_box(f"The {inst.name} updater is already open.")
        return 0
    try:
        try:
            import ou_window
        except ImportError as ex:                                      # no Qt (the runtime is damaged): the plain Windows way
            return run_plain(core, inst, args, ex)
        return ou_window.run(inst, update_to=args.update_to or args.install, wait_pid=args.wait_pid, auto_start=bool(args.update_to))
    finally:
        core.drop_lock(inst)


def run_plain(core, inst, args, why):
    """The window cannot be made (PyQt6 missing): the same job with plain Windows message boxes."""
    core.log_line(inst, f"no window: {why}")
    try:
        builds = core.list_builds(inst)
    except core.UpdaterError as ex:
        core.message_box(str(ex))
        return 1
    want = args.update_to or args.install
    b = build_named(builds, want) if want else (builds[0] if builds else None)
    if b is None:
        core.message_box("No build to install was found on GitHub.")
        return 1
    if not core.message_box(f"The updater window cannot be shown ({why}).\n\nInstall {b['version']} now? Your settings and projects are not touched.", question=True):
        return 0
    try:
        wait_program_closed(core, inst, args.wait_pid, 120)
        core.install_build(inst, b, restore_addons_too=core.vkey(b["version"]) < core.vkey(inst.version or "0"))
    except core.NeedsInstaller as ex:
        core.message_box(str(ex) + "\n\nOpen the releases page and download that build's full installer.")
        return 2
    except core.UpdaterError as ex:
        core.message_box(str(ex))
        return 1
    return start_and_wait(core, inst, False, 120)


# ---------------------------------------------------------------------------------------------------- main
def parse(argv):
    p = argparse.ArgumentParser(prog="openpara_updater", add_help=True)
    p.add_argument("--root")
    p.add_argument("--channel", choices=("playground", "release"))
    p.add_argument("--update-to", dest="update_to", help="window: install this build as soon as the program has closed, then start it")
    p.add_argument("--wait-pid", dest="wait_pid", type=int)
    p.add_argument("--cli", action="store_true", help="no window: do the job given below")
    p.add_argument("--list", action="store_true")
    p.add_argument("--all", action="store_true")
    p.add_argument("--report", action="store_true")
    p.add_argument("--update", action="store_true")
    p.add_argument("--install", metavar="VERSION")
    p.add_argument("--go-back", dest="go_back", action="store_true")
    p.add_argument("--repair", action="store_true")
    p.add_argument("--start", action="store_true")
    p.add_argument("--start-safe", dest="start_safe", action="store_true")
    p.add_argument("--no-start", dest="no_start", action="store_true", help="--cli install jobs: do not start the program afterwards")
    p.add_argument("--selftest", action="store_true")
    return p.parse_args(argv)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    args = parse(argv)
    if args.selftest:
        return selftest()
    try:
        os.chdir(args.root or os.environ.get("OPARA_UPDATER_ROOT") or os.path.dirname(HERE))      # never sit inside app\ (Windows cannot rename a folder that is in use)
    except OSError:
        pass
    if not os.environ.get("OPARA_UPDATER_REFRESHED") and not os.environ.get("OPARA_UPDATER_NO_REFRESH"):
        root = args.root or os.environ.get("OPARA_UPDATER_ROOT") or os.path.dirname(HERE)
        if refresh_from_app(HERE, os.path.join(root, "app", "updater_tool")):
            return subprocess.call([sys.executable, os.path.join(HERE, "openpara_updater.py"), *argv], stdin=subprocess.DEVNULL,
                                   env=dict(os.environ, OPARA_UPDATER_REFRESHED="1"))
    try:
        if args.cli or args.list or args.report:
            return run_cli(args)
        return run_window(args)
    except Exception:                                                  # noqa: BLE001 - the updater must never end without a word
        text = traceback.format_exc()
        try:
            import ou_core
            ou_core.log_line(ou_core.find_install(args.root, args.channel), "CRASH: " + text)
            ou_core.message_box("The updater ran into a problem:\n\n" + text[-1500:])
        except Exception:                                              # noqa: BLE001
            say(text)
        return 1


if __name__ == "__main__":
    sys.exit(main())
