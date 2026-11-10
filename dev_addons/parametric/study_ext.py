"""Parametric Studies: plugs into the Simulation windows through the "sim_study" hook (their 'Create / Open parametric study' button)."""
import os

_open = {}                                       # project folder -> its StudyTab


def _alive(t, shell):
    """True while the study tab still exists and is still a tab of the window.  A closed tab is deleted by Qt; touching it raises RuntimeError."""
    try:
        t.objectName()
        return shell is None or shell.tabs.indexOf(t) >= 0
    except RuntimeError:
        return False


def forget(t):
    """A study tab says it is closing."""
    for k in [k for k, v in _open.items() if v is t]:
        _open.pop(k, None)


def open_study(sw, threaded=True):
    """Opens (or shows again) the parametric study of the simulation project of `sw`; the first time it also creates the study folder."""
    import study_tab
    key = os.path.abspath(sw.path)
    shell = getattr(sw, "shell", None)
    t = _open.get(key)
    if t is not None and not _alive(t, shell):          # its tab was closed: Qt has deleted it, a new one is made
        _open.pop(key, None)
        t = None
    if t is not None:
        if shell is not None:
            shell.tabs.setCurrentWidget(t)
        t.refresh_params()
        return t
    t = study_tab.StudyTab(sw, threaded=threaded)
    _open[key] = t
    if not os.path.isfile(os.path.join(key, "study", "study.json")):
        t.save()
    if shell is not None:
        shell.add_tab(t)
    sw.refresh_study_button()
    return t


def new_study(shell):
    """File > New Parametric Study: which simulation, where to save the project, which part to study, and the study opens (its tab says
    what is still missing, such as the sketch, the supports or the loads)."""
    from PyQt6.QtWidgets import QInputDialog, QMessageBox
    if not shell.need_addon("simulation", "A parametric study"):
        return None
    import sim_tab
    names = {"1D FEA (frames and trusses) - of a part": "beam", "2D FEA": "fea", "2D CFD": "cfd"}
    pick, ok = QInputDialog.getItem(shell, "New Parametric Study", "What do you want to study?", list(names), 0, False)
    if not ok:
        return None
    kind = names[pick]
    src = shell.cur()
    is_asm = src is not None and hasattr(src, "asm")
    is_part = src is not None and not is_asm and hasattr(getattr(src, "doc", None), "features") and not isinstance(src, sim_tab.SimWindow)
    if not (is_asm or is_part) or (kind == "beam" and is_asm):
        src = None                                       # nothing suitable on screen: the import window offers the open parts and a file browser
    w = sim_tab.SimWindow(kind, shell=shell, src_tab=src)
    shell.add_tab(w)
    if not w.import_source():                            # asks where to save the project, then which part or assembly to copy into it
        if not w.project_ok():
            shell.close_tab(shell.tabs.indexOf(w))
        return None
    try:
        return w.open_study()
    except Exception:
        import traceback
        QMessageBox.warning(shell, "Parametric study", "The study could not be opened:\n\n" + traceback.format_exc())
        return None


def register(ext):
    ext.add_hook("sim_study", open_study)
    ext.add_command("file.new", "New Parametric Study...", new_study,
                    tip="Vary the inputs of a 1D FEA, 2D FEA or 2D CFD project and record the outputs")
