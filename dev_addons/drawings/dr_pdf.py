"""dr_pdf.py - a drawing as a PDF: vector lines (never a picture), the page the size of the sheet (true paper size: an ANSI A sheet is 8.5 x 11 in, an A3 sheet 297 x 420 mm).

    export_pdf(drawing, path)     writes the file; raises OSError when it cannot be written
"""
import os

from PyQt6.QtCore import QMarginsF, QSizeF
from PyQt6.QtGui import QPageLayout, QPageSize, QPainter, QPdfWriter

import dr_render as R

DPI = 1200


def export_pdf(drawing, path):
    w, h = drawing.sheet_dims()
    folder = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(folder):
        raise OSError(f"The folder {folder} is not there.")
    wr = QPdfWriter(path)
    wr.setResolution(DPI)
    wr.setCreator("OpenPara Drawings")
    wr.setTitle(os.path.splitext(os.path.basename(path))[0])
    layout = QPageLayout(QPageSize(QSizeF(min(w, h), max(w, h)), QPageSize.Unit.Millimeter, matchPolicy=QPageSize.SizeMatchPolicy.ExactMatch),
                         QPageLayout.Orientation.Landscape if w >= h else QPageLayout.Orientation.Portrait, QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Millimeter)
    wr.setPageLayout(layout)
    p = QPainter()
    if not p.begin(wr):
        raise OSError(f"{path} could not be written.")
    try:
        k = wr.resolution() / 25.4
        p.scale(k, k)
        R.Renderer(drawing).paint(p, min_px=None)
    finally:
        p.end()
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        raise OSError(f"{path} could not be written.")
    return path
