"""
dr_icons.py - the drawings of the Drawings icons (ribbon, panels, outline), registered with the program's icon kit (icon_kit.py): the same flat "2000 bevel" look as the Part and
Sheets icons.  Keys start with dr_.

    icon(key, px) -> QIcon          pixmap(key, px, ratio, enabled) -> QPixmap          has(key)         keys()
    ORIENT_ICON[name]               the key of the cube icon of a standard view ("Front" -> "dr_front")
    STYLE_ICON[style]               the key of the icon of a display style ("hlr" -> "dr_hlr")
"""
import icon_kit
from PyQt6.QtCore import QSize

# ---- the cube of the view icons: three faces seen from a corner; the face the view looks at is the accent one.  (x, y) on the 24 grid, flipped for the views from the other side.
_TOP = [(12, 3), (20, 7.5), (12, 12), (4, 7.5)]
_LEFT = [(4, 7.5), (12, 12), (12, 21), (4, 16.5)]
_RIGHT = [(12, 12), (20, 7.5), (20, 16.5), (12, 21)]


def _path(pts, flipx=False, flipy=False):
    q = [((24 - x) if flipx else x, (24 - y) if flipy else y) for x, y in pts]
    return "M" + "L".join(f"{x:g} {y:g}" for x, y in q) + "z"


def cube(face, flipx=False, flipy=False):
    """The three faces of a cube; `face` ("top" | "left" | "right") is the one drawn as the accent."""
    out = []
    for name, pts in (("left", _LEFT), ("right", _RIGHT), ("top", _TOP)):
        out.append(f'<path class="{"a" if name == face else "p"}" d="{_path(pts, flipx, flipy)}"/>')
    return "".join(out)


# ---- the box of the display-style icons: a front square and the back one, shifted up and to the right
_STYLE = {
    "wireframe": ('<path class="l" d="M4 9h11v11H4zM9 4h11v11H9zM4 9l5-5M15 9l5-5M15 20l5-5"/>'),
    "hlv": ('<path class="l" d="M4 9h11v11H4zM4 9l5-5h11M15 9l5-5M15 20l5-5V4"/>'
            '<path class="l" stroke-dasharray="2 1.500" d="M9 4v11h11M4 20l5-5"/>'),
    "hlr": ('<path class="l" d="M4 9h11v11H4zM4 9l5-5h11v11l-5 5M15 9l5-5"/>'),
    "shaded_edges": ('<path class="b" d="M4 9h11v11H4z"/><path class="p" d="M4 9l5-5h11l-5 5z"/><path class="a" d="M15 9l5-5v11l-5 5z"/>'),
    "shaded": ('<path class="b" stroke="none" d="M4 9h11v11H4z"/><path class="p" stroke="none" d="M4 9l5-5h11l-5 5z"/><path class="a" stroke="none" d="M15 9l5-5v11l-5 5z"/>'),
}

DRAWINGS = {
    # the file
    "dr_new": ('<path class="p" d="M4 3h16v18H4z"/><path class="l" d="M7 7h10v10H7z"/><path class="n" stroke-width="1.800" d="M10 12h4M12 10v4"/>', "feat"),
    "dr_open": ('<path class="b" d="M3 6h6l2 2h9v11H3z"/><path class="a" d="M3 19l3-8h16l-3 8z"/>', "ref"),
    "dr_save": ('<path class="b" d="M4 3h13l3 3v15H4z"/><rect class="a" x="7" y="3" width="9" height="6"/><rect class="p" x="7" y="13" width="10" height="8"/>', "feat"),
    "dr_pdf": ('<path class="p" d="M5 3h9l4 4v14H5z"/><path class="l" d="M14 3v4h4"/><path class="n" stroke-width="2" d="M9 14h6M9 17.500h4"/><path class="n" stroke-width="2.200" d="M20 9v8M17.500 14.500L20 17l2.500-2.500"/>', "cut"),
    "dr_sheet": ('<path class="p" d="M3 5h18v14H3z"/><path class="l" d="M5.500 7.500h13v9h-13z"/><path class="n" stroke-width="1.800" d="M9 12h6"/>', "ref"),
    "dr_portrait": ('<path class="p" d="M6 3h12v18H6z"/><path class="l" d="M8.500 5.500h7v13h-7z"/>', "ref"),
    "dr_landscape": ('<path class="p" d="M3 6h18v12H3z"/><path class="l" d="M5.500 8.500h13v7h-13z"/>', "ref"),
    "dr_fit": ('<path class="l" d="M3 8V3h5M16 3h5v5M21 16v5h-5M8 21H3v-5"/><path class="p" d="M7 7h10v10H7z"/>', "cfg"),
    "dr_delete": ('<path class="n" stroke-width="2.600" d="M6 6l12 12M18 6L6 18"/>', "cut"),
    "dr_undo": ('<path class="n" stroke-width="2.200" d="M9 5L4 9.500 9 14M4.500 9.500H14a5.500 5.500 0 0 1 0 11h-4"/>', "feat"),
    "dr_redo": ('<path class="n" stroke-width="2.200" d="M15 5l5 4.500-5 4.500M19.500 9.500H10a5.500 5.500 0 0 0 0 11h4"/>', "feat"),
    # the views
    "dr_model_view": ('<path class="p" d="M3 7h12v12H3z"/><path class="a" d="M3 7l4-4h12l-4 4z"/><path class="b" d="M15 7l4-4v12l-4 4z"/>', "feat"),
    "dr_proj_view": ('<path class="a" d="M3 8h8v8H3z"/><path class="p" d="M14 8h7v8h-7z"/><path class="n" stroke-width="1.800" d="M11.500 12h2M12.500 10.500L14 12l-1.500 1.500"/><path class="l" stroke-dasharray="1.500 1.500" d="M3 20h18"/>', "feat"),
    "dr_part": ('<path class="p" d="M3 8h12v12H3z"/><path class="a" d="M3 8l4-4h12l-4 4z"/><path class="b" d="M15 8l4-4v12l-4 4z"/>', "feat"),
    "dr_assembly": ('<path class="p" d="M2 12h9v9H2z"/><path class="b" d="M2 12l3-3h9l-3 3z"/><path class="p" d="M12 4h9v9h-9z"/><path class="a" d="M12 4l3-3h9l-3 3z"/>', "asm"),
    "dr_view": ('<path class="p" d="M4 5h16v14H4z"/><path class="l" d="M7 8h10v8H7z"/><path class="n" stroke-width="1.800" d="M7 12h10M12 8v8"/>', "feat"),
    "dr_scale": ('<path class="p" d="M3 8h18v8H3z"/><path class="l" d="M6 8v3M9 8v4.500M12 8v3M15 8v4.500M18 8v3"/>', "cfg"),
    "dr_orient": ('<path class="p" d="M4 4h16v16H4z"/><path class="a" d="M4 4h16v6H4z"/><path class="l" d="M4 10h16"/>', "cfg"),
    "dr_style": ('<path class="l" d="M4 9h11v11H4zM9 4h11v11H9zM4 9l5-5M15 9l5-5M15 20l5-5"/>', "cfg"),
    # the annotation tools
    "dr_dim": ('<path class="l" d="M4 4v10M20 4v10"/><path class="n" stroke-width="1.800" d="M4 10.500h16M7 8.500l-3 2 3 2M17 8.500l3 2-3 2"/><path class="k" d="M9 17h6v3H9z"/>', "ref"),
    "dr_dim_dia": ('<circle class="p" cx="12" cy="12" r="8"/><path class="n" stroke-width="1.800" d="M5 19L19 5M5 19l3-.800M5 19l.8-3M19 5l-3 .8M19 5l-.8 3"/>', "ref"),
    "dr_dim_rad": ('<path class="p" d="M3 21V9a6 6 0 0 1 6-6h12v18z"/><path class="n" stroke-width="1.800" d="M3 21L14 8M3 21l1-3.200M3 21l3.200-.8"/>', "ref"),
    "dr_dim_ang": ('<path class="l" d="M4 20h17M4 20L16 5"/><path class="n" stroke-width="1.800" d="M12 20a8 8 0 0 0-1.800-5M16 20a12 12 0 0 0-3-8"/>', "ref"),
    "dr_note": ('<path class="p" d="M3 4h14v11H3z"/><path class="l" d="M6 8h8M6 11.500h5"/><path class="n" stroke-width="1.800" d="M17 15l4 5M21 20l-3.200-.4M21 20l-.4-3.200"/>', "ref"),
    "dr_balloon": ('<circle class="p" cx="15" cy="9" r="6"/><path class="k" d="M13 8h1.600v-1.400l1.600 0v4.800h-1.600V9.400H13z"/><path class="n" stroke-width="1.800" d="M10.500 13.500L4 21M4 21l3.200-.8M4 21l.8-3.200"/>', "ref"),
    "dr_center_mark": ('<circle class="p" cx="12" cy="12" r="7"/><path class="n" stroke-width="1.800" d="M12 3v18M3 12h18"/>', "ref"),
    "dr_centerline": ('<path class="l" d="M4 4h5v16H4zM15 4h5v16h-5z"/><path class="n" stroke-width="1.800" stroke-dasharray="4 1.500 1 1.500" d="M12 2v20"/>', "ref"),
    "dr_note_pattern": ('<path class="p" d="M3 3h8v4H3z"/><path class="p" d="M3 10h8v4H3z"/><path class="p" d="M3 17h8v4H3z"/><path class="n" stroke-width="1.800" d="M14 5h7M14 12h7M14 19h7"/>', "ref"),
    "dr_draw_line": ('<path class="n" stroke-width="2.200" d="M4 20L20 4"/><circle class="d" cx="4" cy="20" r="2"/><circle class="d" cx="20" cy="4" r="2"/>', "cfg"),
    "dr_draw_rect": ('<path class="l" stroke-width="2" d="M4 6h16v12H4z"/><circle class="d" cx="4" cy="6" r="1.800"/><circle class="d" cx="20" cy="18" r="1.800"/>', "cfg"),
    "dr_draw_circle": ('<circle class="l" stroke-width="2" cx="12" cy="12" r="8"/><circle class="d" cx="12" cy="12" r="1.800"/>', "cfg"),
    "dr_draw_arc": ('<path class="l" stroke-width="2" d="M4 19a10 10 0 0 1 16-10"/><circle class="d" cx="4" cy="19" r="1.800"/><circle class="d" cx="20" cy="9" r="1.800"/>', "cfg"),
    "dr_select": ('<path class="k" d="M6 3l12 10h-6.500l3.500 6.500-2.800 1.500-3.500-6.500L6 19z"/>', "cfg"),
    "dr_refresh": ('<path class="n" stroke-width="2.200" d="M19 12a7 7 0 1 1-2.300-5.200"/><path class="n" stroke-width="2.200" d="M19.500 3.500v4.500H15"/>', "ana"),
}
# the six standard views on a cube: the face looked at is the accent one (Back, Left and Bottom: the cube seen from the far side)
DRAWINGS["dr_front"] = (cube("left"), "feat")
DRAWINGS["dr_right"] = (cube("right"), "feat")
DRAWINGS["dr_top"] = (cube("top"), "feat")
DRAWINGS["dr_back"] = (cube("left", flipx=True), "feat")
DRAWINGS["dr_left"] = (cube("right", flipx=True), "feat")
DRAWINGS["dr_bottom"] = (cube("top", flipy=True), "feat")
# the axonometric views: a cube with all three faces seen (the angles are what differs)
DRAWINGS["dr_iso"] = ('<path class="b" d="M4 7.500L12 12v9l-8-4.500z"/><path class="p" d="M12 12l8-4.500v9L12 21z"/><path class="a" d="M12 3l8 4.500-8 4.500-8-4.500z"/>', "ana")
DRAWINGS["dr_dimetric"] = ('<path class="b" d="M3 9l10 3v9L3 17z"/><path class="p" d="M13 12l8-3v8l-8 4z"/><path class="a" d="M10 4l11 5-8 3L3 9z"/>', "ana")
DRAWINGS["dr_trimetric"] = ('<path class="b" d="M3 8.500l9 4v8.500l-9-4.500z"/><path class="p" d="M12 12.500l9-5.500v10l-9 4z"/><path class="a" d="M8 3.500l13 3.500-9 5.500-9-4z"/>', "ana")
for _k, (_style, _hue) in {"wireframe": ("wireframe", "cfg"), "hlv": ("hlv", "cfg"), "hlr": ("hlr", "cfg"), "shaded_edges": ("shaded_edges", "feat"), "shaded": ("shaded", "feat")}.items():
    DRAWINGS["dr_" + _k] = (_STYLE[_style], _hue)

ORIENT_ICON = {"Front": "dr_front", "Back": "dr_back", "Left": "dr_left", "Right": "dr_right", "Top": "dr_top", "Bottom": "dr_bottom",
               "Isometric": "dr_iso", "Trimetric": "dr_trimetric", "Dimetric": "dr_dimetric"}
STYLE_ICON = {"wireframe": "dr_wireframe", "hlv": "dr_hlv", "hlr": "dr_hlr", "shaded_edges": "dr_shaded_edges", "shaded": "dr_shaded"}
icon_kit.register(DRAWINGS)


def icon(key, px=24):
    return icon_kit.qicon(key, px)


def pixmap(key, px=24, ratio=2, enabled=True):
    return icon_kit.pixmap(key, px, ratio, enabled)


def decorate(button, key, px=16):
    """An icon-only button: the drawing instead of a text character (the button's tooltip says what it does)."""
    button.setText("")
    button.setIcon(icon(key, px))
    button.setIconSize(QSize(px, px))


def has(key):
    return key in DRAWINGS


def keys():
    return list(DRAWINGS)
