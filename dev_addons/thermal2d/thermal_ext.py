"""2D Thermal: the window is a document tab of the manifest (File > New 2D Thermal, Open Project Folder).  This module teaches the Simulation add-on's project
machinery the new kind at start-up: the folder extension (.gph), the name, and how a saved state changes unit system.  (The window class itself is registered
when the first tab is made, see thermal_tab.make_thermal: it needs Qt.)"""


def register(ext):
    import sim_project
    import thermal_store
    sim_project.register_kind("thermal", ".gph", "2D Thermal")
    thermal_store.register()
