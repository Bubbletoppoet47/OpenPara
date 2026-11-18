"""
mate_icons.py - the little icons of the Mate panel: one name per mate type, drawn by the icon kit (icon_kit.py, the program's one icon look;
the drawings are icon_shapes.py's m_<name>).  icon(name) returns a QIcon, pixmap(name, size) a QPixmap.
To add an icon for a new mate type: draw m_<name> in icon_shapes.py and add the name to NAMES.
"""
import icon_kit

NAMES = ("coincident", "parallel", "perpendicular", "tangent", "concentric", "lock", "distance", "angle", "symmetric", "face", "edge", "vertex")


def pixmap(name, size=48, ratio=2):
    return icon_kit.pixmap("m_" + name, size, ratio)


def icon(name):
    """The QIcon of one of NAMES (needs a QApplication)."""
    return icon_kit.qicon("m_" + name, 24)
