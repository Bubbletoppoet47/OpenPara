"""
sim_links.py - the link between a part / assembly and its simulations.

The simulations stay separate .gps files.  The part (.gpd) / assembly (.gpa) file keeps a list "sims" of their paths (relative to the file when
possible), shown in its project tree under "Simulations".  Double-clicking one opens it (nothing opens by itself when the part opens), and
saving the part / assembly also saves the linked simulations that are open and have changes.
"""
import os


def holder(w):
    """The model object that stores the list: the assembly of an assembly window, else the part document."""
    return getattr(w, "asm", None) or getattr(w, "doc", None)


def links(w, attr="sims"):
    """The list of linked files of a part / assembly: attr = "sims" (simulations, .gps) or "renders" (render projects, .gpr)."""
    h = holder(w)
    if h is None:
        return []
    if not hasattr(h, attr):
        setattr(h, attr, [])
    return getattr(h, attr)


def sims(w):
    return links(w, "sims")


def renders(w):
    return links(w, "renders")


def base_dir(w):
    p = getattr(w, "path", None)
    return os.path.dirname(os.path.abspath(p)) if p else None


def key(p):
    return os.path.normcase(os.path.abspath(p))


def abs_of(w, entry, base=None):
    p = entry["path"]
    if os.path.isabs(p):
        return os.path.normpath(p)
    b = base or base_dir(w) or os.getcwd()
    return os.path.normpath(os.path.join(b, p))


def store_path(w, sim_path, base=None):
    b = base or base_dir(w)
    if b is None:
        return os.path.abspath(sim_path)
    try:
        return os.path.relpath(os.path.abspath(sim_path), b)
    except ValueError:                                  # another drive
        return os.path.abspath(sim_path)


def add(w, sim_path, attr="sims"):
    """Links a simulation / render file; False when it was linked already."""
    L = links(w, attr)
    if any(key(abs_of(w, e)) == key(sim_path) for e in L):
        return False
    L.append({"path": store_path(w, sim_path)})
    return True


def remove(w, sim_path, attr="sims"):
    L = links(w, attr)
    n = len(L)
    L[:] = [e for e in L if key(abs_of(w, e)) != key(sim_path)]
    return len(L) != n


def rebase(w, old_base):
    """After 'Save as' to another folder: the relative paths are rewritten for the new place of the file."""
    for attr in ("sims", "renders"):
        for e in links(w, attr):
            a = abs_of(w, e, base=old_base)
            e["path"] = store_path(w, a)


def shell_of(w):
    s = w.window() if hasattr(w, "window") else None
    return s if s is not None and hasattr(s, "tabs") else None


def open_sim(w, entry):                 # also used for render projects (.gpr)
    """Opens a linked simulation (a tab of the main window); the simulation is told which tab it belongs to."""
    s = shell_of(w)
    p = abs_of(w, entry)
    if s is None or not os.path.exists(p):
        return None
    t = s.open_path(p)
    if t is not None and hasattr(t, "src_tab") and getattr(t, "src_tab", None) is None:
        t.src_tab = w
    return t


def open_windows(w):
    """The simulation tabs that are open and linked to this part / assembly."""
    s = shell_of(w)
    if s is None:
        return []
    mine = {key(abs_of(w, e)) for e in sims(w)}
    out = []
    for i in range(s.tabs.count()):
        t = s.tabs.widget(i)
        if getattr(t, "kind", None) in ("fea", "cfd", "beam") and getattr(t, "path", None) and key(t.path) in mine:
            out.append(t)
    return out


def open_renders(w):
    """The render tabs that are open and linked to this part / assembly."""
    s = shell_of(w)
    if s is None:
        return []
    mine = {key(abs_of(w, e)) for e in renders(w)}
    out = []
    for i in range(s.tabs.count()):
        t = s.tabs.widget(i)
        if getattr(t, "kind", None) == "render" and getattr(t, "path", None) and key(t.path) in mine:
            out.append(t)
    return out


def save_open(w):
    """Called after a part / assembly was saved: saves its open simulations and renders that have changes.  Returns the names saved."""
    done = []
    for t in open_windows(w) + open_renders(w):
        try:
            if t.is_dirty() and t.save():
                done.append(os.path.basename(t.path))
        except Exception:
            pass
    return done


def missing(w, entry):
    return not os.path.exists(abs_of(w, entry))


def label(entry):
    return os.path.splitext(os.path.basename(entry["path"]))[0]
