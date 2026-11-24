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


def register(ext):
    ext.add_hook("sim_study", open_study)                # a study is a block of the Workbench, wired to what it varies: no menu entry makes one on its own
