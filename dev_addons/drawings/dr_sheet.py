"""dr_sheet.py - the sheets of a drawing: the standard sizes only (no custom size), landscape or portrait, in millimetres on the paper.

    SIZES                         [(key, label, width mm, height mm)] with width >= height (the landscape sheet), ANSI A-E (inches) and ISO A4-A0
    size(key)                     (key, label, width, height)
    dims(key, landscape)          (width, height) of the sheet in mm as it lies on the table
    inch_text(w_mm, h_mm)         "11 x 8.5 in" of a sheet (the sheet sizes of ANSI are whole inches)
    DEFAULT                       Letter landscape (ANSI A)
"""
IN = 25.4

SIZES = [
    ("ansi_a", "A (ANSI)  8.5 x 11 in", 11.0 * IN, 8.5 * IN),
    ("ansi_b", "B (ANSI)  11 x 17 in", 17.0 * IN, 11.0 * IN),
    ("ansi_c", "C (ANSI)  17 x 22 in", 22.0 * IN, 17.0 * IN),
    ("ansi_d", "D (ANSI)  22 x 34 in", 34.0 * IN, 22.0 * IN),
    ("ansi_e", "E (ANSI)  34 x 44 in", 44.0 * IN, 34.0 * IN),
    ("iso_a4", "A4 (ISO)  210 x 297 mm", 297.0, 210.0),
    ("iso_a3", "A3 (ISO)  297 x 420 mm", 420.0, 297.0),
    ("iso_a2", "A2 (ISO)  420 x 594 mm", 594.0, 420.0),
    ("iso_a1", "A1 (ISO)  594 x 841 mm", 841.0, 594.0),
    ("iso_a0", "A0 (ISO)  841 x 1189 mm", 1189.0, 841.0),
]
DEFAULT = "ansi_a"
_BY = {s[0]: s for s in SIZES}


def size(key):
    return _BY.get(key) or _BY[DEFAULT]


def dims(key, landscape=True):
    _k, _l, w, h = size(key)
    return (w, h) if landscape else (h, w)


def inch_text(w_mm, h_mm):
    return f"{w_mm / IN:g} x {h_mm / IN:g} in"
