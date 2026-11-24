"""wb_ext.py - what the Workbench add-on adds to the program window: the Workbench is the first tab when the program starts (Playground Full dev mode)."""


def open_home(shell):
    """Called once after the program window is up (and the tabs of the last run are back): puts a Workbench project in front when there is none yet.
    When tabs were brought back, the Workbench goes first in the strip but the tab that was in front stays in front."""
    import wb_tab
    for i in range(shell.tabs.count()):
        if isinstance(shell.tabs.widget(i), wb_tab.WorkbenchTab):
            return shell.tabs.widget(i)
    had = shell.tabs.count()
    front = shell.tabs.currentWidget() if had else None
    w = shell.new_addon_tab("workbench", None)
    if w is None:
        return None
    bar = shell.tabs.tabBar()
    bar.moveTab(shell.tabs.indexOf(w), 0)
    shell.tabs.setCurrentWidget(front if front is not None else w)
    return w


def register(ext):
    ext.add_hook("shell.start", open_home)
