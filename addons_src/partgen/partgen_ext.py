"""partgen_ext.py - plugs the Part Generator into the core Part window (see core/ext.py)."""
from PyQt6.QtWidgets import QDialog, QLabel, QPushButton


def build(doc, f, solid):
    """A part made by the Part Generator (a gear, ...): ONE feature whose parameters are kept in the feature, so the
    generator window can be reopened to change them.  The new solid is added to the part."""
    import partgen
    from pm_model import ModelError
    kind = f.get("gen")
    if kind not in partgen.PART_TYPES:
        raise ModelError(f"unknown generated part type {kind!r}")
    try:
        v = partgen.numbers(kind, f.get("params") or {}, doc.num)
        tool = partgen.build(kind, v)
        pl = f.get("place") or {}
        tool = partgen.placed(tool, pl.get("plane", "Top"), doc.num(pl.get("ox", "0")), doc.num(pl.get("oy", "0")), doc.num(pl.get("oz", "0")))
    except ModelError:
        raise
    except (ValueError, ZeroDivisionError) as ex:
        raise ModelError(str(ex))
    if not tool.is_valid:
        raise ModelError("the generated part is not a valid solid for these inputs")
    return doc.clean(tool if solid is None else solid + tool)


def edit(win, f):
    """Open the Part Generator window to make a new part (f is None) or to change the parameters of the part feature f."""
    import partgen_dialog
    import pm_model as pm
    dlg = partgen_dialog.PartGenDialog(win.doc, f, win)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return
    kind, params, place = dlg.result_data()
    win.snapshot()
    if f is None:
        f = win.doc.add(pm.new_feature("partgen", gen=kind, params=params, place=place))
        win.created_new = f["id"]
    else:
        f["params"], f["place"] = params, place
    win.sel = f["id"]
    win.update_all()
    win.left.setCurrentIndex(1)


def panel(win, form, f):
    """A generated part: a short summary and the button that reopens the Part Generator window on it."""
    import partgen
    form.addRow("Type", QLabel(f.get("gen", "?")))
    try:
        v = partgen.numbers(f["gen"], f.get("params") or {}, win.doc.num)
        for lab, txt in partgen.readouts(f["gen"], v)[:6]:
            form.addRow(lab, QLabel(txt))
    except Exception:
        pass
    b = QPushButton("Edit in Part Generator...")
    b.setToolTip("Change the parameters of this part (double-clicking it in the tree does the same)")
    b.clicked.connect(lambda: edit(win, f))
    form.addRow(b)


def register(ext):
    ext.add_feature("partgen", build=build, edit=edit, panel=panel)
    ext.mark_present("partgen")
