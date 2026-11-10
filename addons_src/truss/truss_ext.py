"""Truss Generator: its command in the program window's Add menu - a truss made straight from a sketch of the part that is on screen."""


def truss_from_part(shell):
    """Add > Truss Generator: a new truss tab whose sketch is copied from the part on screen (asks for the .truss folder first, and which sketch
    when the part has several).  With no part on screen it says what is needed."""
    from PyQt6.QtWidgets import QMessageBox
    src = shell.cur()
    doc = getattr(src, "doc", None)
    is_part = doc is not None and hasattr(doc, "features") and not hasattr(src, "asm")
    if not is_part or not any(f["kind"] == "sketch" for f in doc.features):
        QMessageBox.information(shell, "Truss Generator", "Show the part that holds the truss's sketch first (a sketch whose lines are the "
                                "members), then choose Add > Truss Generator again.\n\nFile > New Truss Generator starts an empty truss.")
        return None
    text = doc.to_json()                                 # the part as it is now, unsaved edits included
    t = shell.new_addon_tab("truss")
    if t is None:
        return None
    if not t.need_folder("The truss gets its own .truss folder, with a copy of the sketch inside."):
        return t                                         # no folder chosen: the empty truss stays, with its guidance
    t.import_doc(text)
    return t


def register(ext):
    ext.add_command("add", "Truss Generator - members from a sketch of this part", truss_from_part,
                    tip="Makes a truss project from the lines of a sketch of the part on screen")
