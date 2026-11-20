"""
icons.py - the ribbon icons: a button label -> the drawing of the icon kit (icon_kit.py, the program's one icon look).

icon(name) -> QIcon, name is the lower-case button label ("line", "extruded boss/base", ...); unknown names give None.
"""

# exact label -> drawing
EXACT = {
    "sketch": "sketch_tool", "normal to": "normal_to", "select": "select", "line": "line", "centerline": "centerline", "rectangle": "rectangle",
    "circle": "circle", "arc": "arc", "spline": "spline", "slot": "slot", "polygon": "polygon", "point": "point", "measure": "measure",
    "insert components": "insert_components", "edit component": "edit_component", "tab tree": "panel_tree", "tab properties": "panel_properties",
    "tab configurations": "panel_configurations", "tab equations": "panel_equations", "tab display": "panel_display",
    "linear pattern": "sketch_pattern", "construction": "construction", "dimension": "dimension", "shell": "shell",
    "1d fea (frames)": "fea_1d", "1d fea": "fea_1d", "2d fea": "fea_2d", "2d cfd": "cfd_2d", "new render": "new_render",
    "preview / render": "render", "wrap": "wrap", "boundary boss/base": "boundary_boss", "boundary cut": "boundary_cut", "rib": "rib", "draft": "draft", "intersect": "intersect",
}
# label start -> drawing (a label that begins like this, e.g. "Mirror Entities", "Trim Entities")
PREFIX = (
    ("exit", "exit_sketch"), ("sketch fillet", "sketch_fillet"), ("trim", "trim"), ("offset", "offset"), ("mass", "mass_properties"), ("section", "section_properties"),
    ("mirror", "mirror_entities"), ("sketch pattern", "sketch_pattern"), ("move", "move_entities"), ("convert", "convert_entities"),
    ("add relation", "add_relation"),
)

_cache = {}


def key_of(name):
    """The drawing a button label stands for (None when it has none)."""
    n = name.lower().replace("\n", " ").strip()
    if n in EXACT:
        return EXACT[n]
    for start, key in PREFIX:
        if n.startswith(start):
            return key
    return None


def icon(name, size=40):
    key = (name.lower().replace("\n", " "), size)
    if key in _cache:
        return _cache[key]
    import icon_kit
    import icon_set
    ic = icon_set.by_label(name, size)              # the tree / feature drawings first (extruded boss, fillet, mate ...)
    if ic is None:
        k = key_of(name)
        ic = icon_kit.qicon(k, size) if k else None
    _cache[key] = ic
    return ic
