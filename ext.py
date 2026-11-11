"""
ext.py - the few places where an add-on plugs into the core windows (Sketch/Part and Assembly).

The core knows nothing about what an add-on does.  An add-on that wants to add a feature kind to the Part window calls
    ext.add_feature(kind, build=..., panel=..., edit=...)
from its  register(ext)  function, and the shell tells the core which add-ons are there with  ext.mark_present(id).  Without an add-on
the core still opens and saves the files that use it (the data stays in the file); the feature is shown as "needs the <add-on>".

    build(doc, feature, solid) -> solid          rebuilds the feature (raise pm_model.ModelError for a problem)
    panel(window, form, feature)                  fills the property panel of the feature
    edit(window, feature_or_None)                 opens the add-on's window to make (None) or change the feature

What else an add-on can plug into (all from its  register(ext)):
    ext.add_command(place, text, fn)              a command in the program window's File / Add / View / Help menu (and the start page)
    ext.add_hook(name, fn)                        a button another add-on's window offers (e.g. "sim_study")
    ext.add_menu_item(menu, text, fn)             an item in the menu of another add-on's window (e.g. "annotator.file")
    ext.add_shell_mixin(cls)                      helpers its tabs expect from the program window
A tab of an add-on may offer:  title(), path, is_dirty(), save(), can_close(), shutdown(), depends_on() (the tab it belongs to: closed with it).
"""
OPTIONAL = {
    "partgen": ("Part Generator", "gears (spur, helical, herringbone) and other parts made from a few parameters"),
    "simulation": ("Simulation", "1D / 2D FEA and 2D CFD of a sketch or a slice of a part or assembly"),
    "render": ("Renderer", "photorealistic pictures and videos of a part or assembly"),
    "truss": ("Truss Generator", "the members of a truss built from the lines of a sketch"),
}
_present = set()
FEATURES = {}
MENU_ITEMS = {}              # {menu name: [(text, fn(window))]}: items an add-on puts in the menu of another add-on's window, e.g. "annotator.file"
MODEL_TRAINERS = {}          # {model type key: spec}: model types an add-on adds to the Trainer (see add_model_trainer)
SHELL_MIXINS = []           # classes an add-on adds to the program window (gpd_app.AppShell) to give its tabs the helpers they use
HOOKS = {}                  # {hook name: [fn]}: places where an add-on adds to a window of another add-on, e.g. "sim_study" (see add_hook)
COMMANDS = {}               # {place: [{"text", "fn", "key", "tip"}]}: commands an add-on puts in the program window's menus (see add_command)
PLACES = ("file.new", "file", "add", "view", "help")
installer = None            # set by the shell: installer(addon_id, parent) offers to install / enable an add-on


def mark_present(aid, on=True):
    (_present.add if on else _present.discard)(aid)


def present(aid):
    return aid in _present


def add_feature(kind, **spec):
    FEATURES[kind] = spec


def add_hook(name, fn):
    """An add-on offers `fn` to the hook `name` of another add-on's window.  The Simulation windows use "sim_study": fn(sim_window) -> opens
    (or creates) the parametric study of that simulation project; the window then shows its 'parametric study' button."""
    HOOKS.setdefault(name, [])
    if fn not in HOOKS[name]:
        HOOKS[name].append(fn)


def hooks(name):
    return list(HOOKS.get(name, []))


def add_command(place, text, fn, key=None, tip=None):
    """An add-on puts a command in a menu of the program window.  place: "file.new" (with New Part / New Assembly; also a button on the start
    page), "file" (with Import / Export), "add" (the Add menu: things made from the document on screen), "view" or "help".
    fn(shell) runs it (shell is the program window: shell.cur() is the tab on screen, shell.add_tab(widget) shows a new one).
    key: an optional shortcut such as "Ctrl+Alt+P".  tip: one short line for the status bar and the start page.
    Registered again every time the add-ons change, so call it from register(ext); the same place + text is listed once."""
    if place not in PLACES:
        raise ValueError(f"add_command: unknown place '{place}' (one of {', '.join(PLACES)})")
    items = COMMANDS.setdefault(place, [])
    for it in items:
        if it["text"] == text:
            it.update(fn=fn, key=key, tip=tip)
            return
    items.append({"text": text, "fn": fn, "key": key, "tip": tip})


def commands(place):
    return list(COMMANDS.get(place, []))


def add_shell_mixin(cls):
    if cls not in SHELL_MIXINS:
        SHELL_MIXINS.append(cls)


def add_menu_item(menu, text, fn):
    """An add-on puts an item in the menu of another add-on's window ("annotator.file").  fn(window) runs it.  The same menu + text is
    listed once: registering again (after add-ons were installed or updated, which loads their code anew) replaces the function."""
    items = MENU_ITEMS.setdefault(menu, [])
    for i, (t, _f) in enumerate(items):
        if t == text:
            items[i] = (text, fn)
            return
    items.append((text, fn))


def add_model_trainer(key, **spec):
    """Adds a model type to the Trainer add-on's model list.  spec: label, script (a Python file the Trainer runs in the background with
    the path of a job.json as its argument; see trainer/job_common.py), sizes (e.g. ("n", "s")), default_size, models_key ("assist" or
    "scratch": the folder of the Models folder its results go to), needs (names of extra Python packages it imports)."""
    MODEL_TRAINERS[key] = spec


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
