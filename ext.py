"""
ext.py - the few places where an add-on plugs into the core windows (Sketch/Part and Assembly).

The core knows nothing about what an add-on does.  An add-on that wants to add a feature kind to the Part window calls
    ext.add_feature(kind, build=..., panel=..., edit=...)
from its  register(ext)  function, and the shell tells the core which add-ons are there with  ext.mark_present(id).  Without an add-on
the core still opens and saves the files that use it (the data stays in the file); the feature is shown as "needs the <add-on>".

    build(doc, feature, solid) -> solid          rebuilds the feature (raise pm_model.ModelError for a problem)
    panel(window, form, feature)                  fills the property panel of the feature
    edit(window, feature_or_None)                 opens the add-on's window to make (None) or change the feature
"""
OPTIONAL = {
    "partgen": ("Part Generator", "gears (spur, helical, herringbone) and other parts made from a few parameters"),
    "simulation": ("Simulation", "1D / 2D FEA and 2D CFD of a sketch or a slice of a part or assembly"),
    "render": ("Renderer", "photorealistic pictures and videos of a part or assembly"),
    "truss": ("Truss Generator", "the members of a truss built from the lines of a sketch"),
}
_present = set()
FEATURES = {}
installer = None            # set by the shell: installer(addon_id, parent) offers to install / enable an add-on


def mark_present(aid, on=True):
    (_present.add if on else _present.discard)(aid)


def present(aid):
    return aid in _present


def add_feature(kind, **spec):
    FEATURES[kind] = spec


def feature(kind):
    return FEATURES.get(kind)


def label(aid):
    return OPTIONAL.get(aid, (aid, ""))[0]


def need_text(aid):
    return f"needs the {label(aid)} add-on (File > Add-ons)"


def ask_install(aid, parent=None):
    """The user pressed something that belongs to an add-on that is not there: say so, and offer the installer when the shell has one."""
    if installer is not None:
        return installer(aid, parent)
    from PyQt6.QtWidgets import QMessageBox
    QMessageBox.information(parent, label(aid), f"This needs the {label(aid)} add-on ({OPTIONAL.get(aid, ('', ''))[1]}).\n\nInstall it from File > Add-ons.")
    return False
