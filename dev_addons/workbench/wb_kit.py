"""wb_kit.py - the pictures of the workbench, drawn by the program's icon kit (icon_kit.py) like the icons of Sheets, so a block, a cell, the toolbox and the status marks
look like the rest of the program: flat blue-grey bodies with a raised edge, a navy outline and one muted accent colour.

The kit already has the pictures of the part, the assembly, the sketch and of the 3D / 2D analyses (the icons of their tabs); the drawings below are the ones the workbench adds
(keys start with wb_): the thermal analyses, the tools of Component Tools, the cells (parameters, solution, results, profile) and the five status marks.

    KIND[kind]            the kit key of a kind of block
    cell_key(kind, key)   the kit key of a cell of a block of that kind (the Geometry cell of a 3D analysis is a part, that of a 2D one a sketch ...)
    STATUS[status]        the kit key of a status mark
    draw(p, key, rect)    paints the picture into rect with a QPainter, crisp at the zoom the painter has
    icon(key, px)         a QIcon, pixmap(key, px) a QPixmap
    ready()               False when this program's core has no icon kit (an older core): the callers then draw the old pictures (wb_icons.py)
"""
import math

from PyQt6.QtGui import QPainter

try:
    import icon_kit
except Exception:                                            # noqa: BLE001  (a core without the kit)
    icon_kit = None

SHAPES = {
    "wb_thermal2d": ('<path class="b" d="M3 5h14v14H3z"/><path class="n" d="M3 12h14M10 5v14"/><rect class="p" x="16.500" y="3" width="4.500" height="12" rx="2.250"/>'
                     '<circle class="a" cx="18.750" cy="17.500" r="3"/><path class="n" stroke-width="2" d="M18.750 6.500v10"/>', "ana"),
    "wb_thermal3d": ('<path class="b" d="M9.500 3l6.500 3.750v7.500L9.500 18 3 14.250v-7.500z"/><path class="n" d="M3 6.750l6.500 3.750 6.500-3.750M9.500 10.500V18"/>'
                     '<rect class="p" x="17" y="6" width="4" height="10" rx="2"/><circle class="a" cx="19" cy="18.500" r="2.800"/><path class="n" stroke-width="2" d="M19 8.500v9"/>', "ana"),
    "wb_fluid3d": ('<path class="b" d="M9.500 3l6.500 3.750v7.500L9.500 18 3 14.250v-7.500z"/><path class="n" d="M3 6.750l6.500 3.750 6.500-3.750M9.500 10.500V18"/>'
                   '<path class="n" stroke-width="1.800" d="M17 6.500c1.500-1.500 2.500 1.500 4 0M17 10.500c1.500-1.500 2.500 1.500 4 0M17 14.500c1.500-1.500 2.500 1.500 4 0"/>', "ana"),
    "wb_coupled": ('<rect class="b" x="2.500" y="10" width="10" height="10"/><path class="n" d="M2.500 15h10M7.500 10v10"/><rect class="p" x="15" y="3" width="4" height="10" rx="2"/>'
                   '<circle class="a" cx="17" cy="15.500" r="2.800"/><path class="n" stroke-width="2" d="M17 5.500v9"/><path class="n" stroke-width="2" d="M3 6h7M8 4l2 2-2 2"/>', "ana"),
    "wb_sheets": ('<rect class="p" x="3" y="4" width="18" height="16" rx="1"/><path class="l" d="M3 9.300h18M3 14.600h18M9 4v16M15 4v16"/><rect class="a" x="3" y="4" width="18" height="5.300"/>', "dat"),
    "wb_pdf": ('<path class="p" d="M5 3h9l5 5v13H5z"/><path class="l" d="M14 3v5h5"/><rect class="a" x="8" y="11" width="8" height="3"/><path class="l" d="M8 17h8M8 19.500h5"/>', "cut"),
    "wb_controls": ('<rect class="b" x="2.500" y="7" width="7" height="8"/><rect class="b" x="14.500" y="7" width="7" height="8"/><path class="n" stroke-width="2" d="M9.500 11h5M12.500 9l2 2-2 2"/>'
                    '<path class="l" d="M18 15v4.500H6V15"/>', "ana"),
    "wb_circuits": ('<path class="n" stroke-width="2" d="M2 12h4l2-5 3.500 10 3-10 2 5h5.500"/><circle class="d" cx="3" cy="12" r="1.600"/><circle class="d" cx="21" cy="12" r="1.600"/>', "asm"),
    "wb_visualize": ('<path class="p" d="M2 12c3-5 6-7 10-7s7 2 10 7c-3 5-6 7-10 7s-7-2-10-7z"/><circle class="a" cx="12" cy="12" r="3.600"/><circle class="k" cx="12" cy="12" r="1.300"/>', "ana"),
    "wb_motor": ('<circle class="b" cx="12" cy="12" r="8"/><path class="l" d="M8.500 15.500v-7l3.500 4.500 3.500-4.500v7"/><path class="l" d="M2 12h2M20 12h2"/>', "cfg"),
    "wb_trainer": ('<path class="l" d="M5 6l7 6-7 6M12 12h8"/><circle class="a" cx="5" cy="6" r="2.300"/><circle class="a" cx="5" cy="18" r="2.300"/><circle class="a" cx="12" cy="12" r="2.300"/>'
                   '<circle class="a" cx="20" cy="12" r="2.300"/>', "ai"),
    "wb_trained_models": ('<rect class="p" x="3" y="3.500" width="18" height="5"/><rect class="p" x="3" y="9.500" width="18" height="5"/><rect class="p" x="3" y="15.500" width="18" height="5"/>'
                          '<circle class="a" cx="6.200" cy="6" r="1.400"/><circle class="a" cx="6.200" cy="12" r="1.400"/><circle class="a" cx="6.200" cy="18" r="1.400"/><path class="l" d="M10 6h8M10 12h8M10 18h8"/>', "ai"),
    "wb_model_test": ('<rect class="p" x="3" y="5" width="18" height="14" rx="1"/><path class="l" d="M3 15h18M7 15v2M11 15v2M15 15v2M19 15v2"/><circle class="a" cx="9" cy="10" r="2.200"/>'
                      '<path class="n" stroke-width="2" d="M13 10.500l2 2 3.500-4"/>', "ai"),
    "wb_annotator": ('<rect class="p" x="3" y="4" width="18" height="16"/><rect class="a" x="7" y="8" width="10" height="8" style="opacity:.6"/><path class="l" d="M3 8V4h4M21 8V4h-4M3 16v4h4M21 16v4h-4"/>', "ai"),
    "wb_truss": ('<path class="b" d="M2 18L12 6l10 12z"/><path class="l" d="M7 12l5 6 5-6M12 6v12"/>', "feat"),
    "wb_slicer": ('<path class="l" d="M3 4.500h18"/><path class="a" d="M12 4.500v3"/><rect class="p" x="5" y="8.500" width="14" height="3" rx="1"/><rect class="p" x="5" y="12.500" width="14" height="3" rx="1"/><rect class="a" x="5" y="16.500" width="14" height="3" rx="1"/>', "ref"),
    "wb_drawing": ('<path class="p" d="M4 3h16v18H4z"/><path class="l" d="M7 6h10v6H7z"/><path class="a" d="M7 14.500h10v4H7z"/>', "ref"),
    "wb_models": ('<path class="p" d="M3 8h11v11H3z"/><path class="a" d="M3 8l4-4h11l-4 4z"/><path class="b" d="M14 8l4-4v11l-4 4z"/>', "feat"),
    "wb_params": ('<path class="l" d="M3 7h18M3 12h18M3 17h18"/><rect class="a" x="7" y="4.500" width="4" height="5"/><rect class="a" x="14" y="9.500" width="4" height="5"/><rect class="a" x="5" y="14.500" width="4" height="5"/>', "ana"),
    "wb_solve": ('<rect class="b" x="3" y="4" width="18" height="16" rx="1.500"/><path class="a" d="M10 8.500l6 3.500-6 3.500z"/>', "ana"),
    "wb_results": ('<path class="l" d="M3 20h18"/><rect class="a" x="4.500" y="12" width="4" height="8"/><rect class="b" x="10" y="6" width="4" height="14"/><rect class="a" x="15.500" y="9" width="4" height="11"/>', "ana"),
    "wb_profile": ('<path class="b" d="M5 4h14v4h-5v8h5v4H5v-4h5V8H5z"/>', "feat"),
    "wb_ok": ('<circle class="p" cx="12" cy="12" r="9"/><path class="n" stroke-width="2.800" d="M7 12.500l3.500 3.500L17 8.500"/>', "dat"),
    "wb_incomplete": ('<circle class="p" cx="12" cy="12" r="9"/><path class="n" stroke-width="2.400" d="M9 9.800a3 3 0 1 1 4.600 2.500c-1 .6-1.600 1.200-1.600 2.500"/><circle class="d" cx="12" cy="17.600" r="1.200"/>', "feat"),
    "wb_update": ('<circle class="p" cx="12" cy="12" r="9"/><path class="n" stroke-width="2.800" d="M14 4.500L8.500 12.800h6.500L10 19.500"/>', "ref"),
    "wb_refresh": ('<circle class="p" cx="12" cy="12" r="9"/><path class="n" stroke-width="2.400" d="M16.800 12a4.800 4.800 0 1 1-1.500-3.500M16.800 6.500v3.500h-3.500"/>', "asm"),
    "wb_failed": ('<circle class="p" cx="12" cy="12" r="9"/><path class="n" stroke-width="2.800" d="M8.500 8.500l7 7M15.500 8.500l-7 7"/>', "cut"),
}

KIND = {"part": "tab_part", "assembly": "assembly", "solid": "tab_solid", "thermal3d": "wb_thermal3d", "fluid3d": "wb_fluid3d", "coupled": "wb_coupled", "fea": "tab_fea", "thermal": "wb_thermal2d", "cfd": "tab_cfd",
        "beam": "tab_beam", "sheets": "wb_sheets", "pdf": "wb_pdf", "controls": "wb_controls", "circuits": "wb_circuits", "visualize": "wb_visualize", "motor": "wb_motor",
        "trainer": "wb_trainer", "trained_models": "wb_trained_models", "model_test": "wb_model_test", "annotator": "wb_annotator", "truss": "wb_truss", "study": "wb_params", "drawing": "wb_drawing", "slicer": "wb_slicer"}
STATUS = {"ok": "wb_ok", "incomplete": "wb_incomplete", "update": "wb_update", "refresh": "wb_refresh", "failed": "wb_failed"}
CELL = {"profile": "wb_profile", "setup": "wb_params", "solution": "wb_solve", "results": "wb_results", "models": "wb_models"}
SOLID_KINDS = ("solid", "thermal3d", "fluid3d")                         # their Geometry cell holds a solid (a part or an assembly); the other analyses hold a sketch

_state = {"ok": None}


def ready():
    """True when the kit is there and has the drawings of the workbench."""
    if _state["ok"] is None:
        ok = False
        if icon_kit is not None:
            try:
                icon_kit.register(SHAPES)
                ok = all(icon_kit.has(k) for k in list(KIND.values()) + list(STATUS.values()) + list(CELL.values()) + ["sketch"])
            except Exception:                                # noqa: BLE001
                ok = False
        _state["ok"] = ok
    return _state["ok"]


def cell_key(kind, key):
    """The kit key of the cell `key` of a block of kind `kind`."""
    if key == "geometry":
        if kind == "assembly":
            return "assembly"
        return "tab_part" if kind in ("part",) + SOLID_KINDS else "sketch"
    if key == "document":
        return KIND.get(kind, "wb_params")
    return CELL.get(key, "wb_params")


def _scale(p):
    """How many device pixels one unit of the painter's coordinates is (the zoom of the view, the pixel ratio of the screen)."""
    t = p.combinedTransform()
    return max(1.0, math.hypot(t.m11(), t.m12()))


def draw(p, key, rect):
    """Paints the kit picture `key` into the QRectF `rect`: drawn at the size it has on the screen, so it stays sharp when the schematic is zoomed."""
    if not ready() or not icon_kit.has(key):
        return False
    ratio = max(1, min(4, int(math.ceil(_scale(p) - 0.01))))
    size = max(8, int(round(rect.width())))
    img = icon_kit.image(key, size, ratio)
    p.save()
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    p.drawImage(rect, img)
    p.restore()
    return True


def icon(key, px=18):
    return icon_kit.qicon(key, px) if ready() else None


def pixmap(key, px=18, ratio=2, enabled=True):
    return icon_kit.pixmap(key, px, ratio, enabled) if ready() else None
