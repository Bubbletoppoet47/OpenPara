"""3D Thermal: the window is a document tab of the manifest (File > New 3D Thermal, Open Project Folder).  This module teaches the Simulation add-on's
project machinery the new kind at start-up: the folder extension (.gpt) and the name.  (The window class itself is in thermal3d_tab.make_thermal3d.)"""

KIND = "thermal3d"
EXT = ".gpt"
LABEL = "3D Thermal"

NEEDS_NEWER = ("3D Thermal needs a newer Simulation add-on than the one installed (the installed one cannot take another kind of simulation yet).\n"
               "Update the Simulation add-on in File > Add-ons (or answer Yes when the program offers add-on updates), then start the program again.")


def ensure_registered():
    """Makes the Simulation add-on know the kind 'thermal3d' (project folder .gpt).  Safe to call again."""
    import sim_project
    if not hasattr(sim_project, "register_kind"):
        raise RuntimeError(NEEDS_NEWER + "\n(missing: sim_project.register_kind)")
    if KIND not in sim_project.EXT:
        sim_project.register_kind(KIND, EXT, LABEL)


def register(ext):
    ensure_registered()
