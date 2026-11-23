"""2D Thermal: the window is a document tab of the manifest (File > New 2D Thermal, Open Project Folder).  This module teaches the Simulation add-on's project
machinery the new kind at start-up: the folder extension (.gph), the name, and how a saved state changes unit system.  (The window class itself is registered
when the first tab is made, see thermal_tab.make_thermal: it needs Qt.)"""


NEEDS_NEWER = ("2D Thermal needs a newer Simulation add-on than the one installed (the installed one cannot take another kind of simulation yet).\n"
               "Update the Simulation add-on in File > Add-ons (or answer Yes when the program offers add-on updates), then start the program again.")


def check_simulation(*modules):
    """Raises a plain message when the installed Simulation add-on is older than the hooks this add-on needs (sim_project / sim_tab / physics_store)."""
    for mod, name in modules:
        if not hasattr(mod, name):
            raise RuntimeError(NEEDS_NEWER + f"\n(missing: {mod.__name__}.{name})")


def register(ext):
    import physics_store
    import sim_project
    import thermal_store
    check_simulation((sim_project, "register_kind"), (physics_store, "register_converter"))
    sim_project.register_kind("thermal", ".gph", "2D Thermal")
    thermal_store.register()
