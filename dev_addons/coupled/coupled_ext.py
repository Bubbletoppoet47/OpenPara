"""Coupled Physics: the window is a document tab of the manifest (a block of the Workbench).  This module teaches the Simulation add-on's project machinery the kind:
the folder extension (.gpx) and the name.  (The window class itself is in coupled_tab.make_coupled.)"""

KIND = "coupled"
EXT = ".gpx"
LABEL = "Coupled Physics"

NEEDS_NEWER = ("Coupled Physics needs a newer Simulation add-on than the one installed (the installed one cannot take another kind of simulation yet).\n"
               "Update the Simulation add-on in File > Add-ons (or answer Yes when the program offers add-on updates), then start the program again.")


def ensure_registered():
    """Makes the Simulation add-on know the kind 'coupled' (project folder .gpx).  Safe to call again."""
    import sim_project
    if not hasattr(sim_project, "register_kind"):
        raise RuntimeError(NEEDS_NEWER + "\n(missing: sim_project.register_kind)")
    if KIND not in sim_project.EXT:
        sim_project.register_kind(KIND, EXT, LABEL)


def register(ext):
    ensure_registered()
