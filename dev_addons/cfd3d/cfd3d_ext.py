"""3D Fluid Flow: the window is a document tab of the manifest (File > New 3D Fluid Flow, Open Project Folder).  This module teaches the Simulation add-on's
project machinery the new kind at start-up: the folder extension (.gpw) and the name.  (The window class itself is in cfd3d_tab.make_fluid3d.)"""

KIND = "fluid3d"
EXT = ".gpw"
LABEL = "3D Fluid Flow"

NEEDS_NEWER = ("3D Fluid Flow needs a newer Simulation add-on than the one installed (the installed one cannot take another kind of simulation yet).\n"
               "Update the Simulation add-on in File > Add-ons (or answer Yes when the program offers add-on updates), then start the program again.")


def ensure_registered():
    """Makes the Simulation add-on know the kind 'fluid3d' (project folder .gpw).  Safe to call again."""
    import sim_project
    if not hasattr(sim_project, "register_kind"):
        raise RuntimeError(NEEDS_NEWER + "\n(missing: sim_project.register_kind)")
    if KIND not in sim_project.EXT:
        sim_project.register_kind(KIND, EXT, LABEL)


def register(ext):
    ensure_registered()
