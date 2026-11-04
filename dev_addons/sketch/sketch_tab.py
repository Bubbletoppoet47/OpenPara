"""sketch_tab.py - the playground's Sketch/Part tab: a new OpenPara part window, empty, in an isometric view of the three planes with the feature tree.

Nothing is started for you: pick a plane (click it in the view or in the tree) and press Sketch, or start from a feature.  It is OpenPara's own part
window (core/pm_app.py), so the sketcher is the real one: tools, relations, dimensions, equations.  Other add-ons take their input from it the same
way they do in OpenPara (the 2D simulations read the sketch of this tab).  A sketch can stay just a sketch or become a part."""


def new_sketch_tab(host=None):
    import pm_app
    import pm_model as pm
    w = pm_app.MainWindow()
    w.doc = pm.Document()
    w.sel = w.sel_plane = w.sel_face = None
    w.update_all(fit=True)                                  # fit = the isometric view of the planes
    w.saved_json = w.doc.to_json()
    w.left.setCurrentIndex(0)                               # the feature tree
    try:
        w.say("Pick a plane (click it in the view or the tree), then press Sketch.")
    except Exception:
        pass
    return w
