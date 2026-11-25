"""
sim_meshui.py - the Mesh page of the FEA and Thermal windows, 2D and 3D, built from one piece: the same widgets, in the same order, with the same words.

    Element size                       (2D: a box; 3D: the table of the parts, which an assembly needs - the window makes it)
    [ ] Advanced mesh options
          Mesh type                    (3D only: tetrahedra or hex-dominant)
          Element order
          Minimum size
          Growth rate
          [x] Refine at curved edges / surfaces   [10 per circle]
          Smaller elements on single edges, points and regions / faces: select them, type a size, press the button
          [size] [Set on selection]
          Where | Size                 the list of the local sizes, a size can be edited
          [Remove selected size]
          Mesh follows                 (3D only)
    [ ] Adaptive mesh (h)              (FEA only; the window makes it)
    [ Mesh ]
    the line about the mesh, and the Mesh quality box (only with the advanced options on)

`build_advanced(host, v, dim)` puts the advanced options into the layout `v` and gives the window the widgets under the names the 3D window always used (cb_adv, adv_box, type_combo,
order_combo, e_hmin, hmin_label, e_growth, cb_curv, sp_curv, local_hdr, e_face_h, b_face_size, face_table, b_face_size_del, follows_combo).  What the window has to offer: inputs_changed(),
adv_toggled(on), curv_toggled(on), set_face_size(), remove_face_size(), face_item_changed(item).  `build_quality(host, v)` adds the quality box (quality_box, quality_lbl).
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QTableWidget, QVBoxLayout, QWidget)

import sim_ui

HINT_STYLE = "color:#555555; font-size:11px;"
NOUN = {2: "edges, points and regions", 3: "faces", "cfd": "edges and points of the bodies"}
CURVED = {2: "edges", 3: "surfaces", "cfd": "edges"}
WHAT = {2: "select them in the view (or, for a region, in the Regions list)", 3: "select the face(s) in the view (or the Faces list)",
        "cfd": "select them in the view"}
ADV_TIP = {2: "Element order, a minimum size and a growth rate, refinement at curved edges and on single edges, points or regions, and a quality report. "
              "Off = the plain automatic mesh (quadratic triangles).",
           3: "Mesh type (tetrahedra or hex-dominant), element order, a minimum size and a growth rate, refinement at curved surfaces and on "
              "single faces, and a quality report. Off = the plain automatic mesh (quadratic tetrahedra).",
           "cfd": "A minimum size and a growth rate, refinement at curved edges and on single edges or points of the bodies, and a quality report. "
                  "Off = the plain automatic mesh."}
ORDER_TIP = {"cfd": "", 2: "Quadratic elements (a node in the middle of every edge: 6-node triangles) bend and carry stress gradients much better, so they are the right choice almost "
                "always. Linear elements (corner nodes only) are quicker but stiffer in bending: they need a much finer mesh for the same accuracy. The mesh and its "
                "size do not change.",
             3: "Quadratic elements (mid-edge nodes: 10-node tetrahedra, 20-node bricks) bend and carry stress gradients much better, so they "
                "are the right choice almost always. Linear elements (corner nodes only) are quicker but stiffer in bending: they need a "
                "much finer mesh for the same accuracy."}
HMIN_TIP = {2: "The smallest element edge the mesher may make (blank = no limit).",
            "cfd": "The smallest element edge the mesher may make (blank = no limit). With the turbulence model the thickness of the first boundary layer "
                   "sets the smallest element and this box is not used.",
            3: "The smallest element edge the mesher may make (blank = a sixth of the smallest element size)."}
CURV_TIP = {2: "Makes the elements smaller where an edge is curved (arcs, circles, splines), so the curve is followed.",
            "cfd": "Makes the elements smaller where the edge of a body is curved (arcs, circles), so the curve is followed.",
            3: "Makes the elements smaller where a surface is curved (holes, fillets), so the curve is followed."}
LOCAL_TIP = {2: "Gives the selected edges, points or regions a smaller element size than the global one. The elements grow back to the global size away from them, "
                "at the growth rate above.",
             "cfd": "Gives the selected edges or points of the bodies a smaller element size than the one at the body. The elements grow back to it away from them, "
                    "at the growth rate above.",
             3: "Gives the selected faces (or patches of a split face) a smaller element size than the global one. The elements grow "
                "back to the global size away from them, at the growth rate above."}


def build_advanced(host, v, dim, orders, growth_range, curv_range, types=None, follows=None):
    """The 'Advanced mesh options' tick box and what it reveals.  `dim`: 2 or 3.  `orders`: {order: text}; `types`, `follows`: {key: text} (3D only, else None)."""
    host.cb_adv = QCheckBox("Advanced mesh options")
    host.cb_adv.setToolTip(ADV_TIP[dim])
    v.addWidget(host.cb_adv)
    host.adv_box = QWidget()
    al = QVBoxLayout(host.adv_box)
    al.setContentsMargins(14, 0, 0, 0)
    al.setSpacing(3)
    f = QFormLayout()
    host.type_combo = None
    if types:
        host.type_combo = QComboBox()
        for k, text in types.items():
            host.type_combo.addItem(text, k)
        host.type_combo.setToolTip("Tetrahedra: the whole part is filled with them. Hex-dominant: a block of brick elements (hexahedra) inside the part, and "
                                   "tetrahedra, joined to the bricks by pyramids, between it and the surface. The surface mesh is the same either way, so the "
                                   "borders of split patches stay mesh edges. A part with no room for bricks (thin, small, or a fine element size) gets "
                                   "tetrahedra, and the mesh quality box says so. The share of bricks grows as the elements get small compared to the part.")
        sim_ui.tame(host.type_combo, 24)
        f.addRow("Mesh type", host.type_combo)
    host.order_combo = None                                              # (the CFD elements are fixed: quadratic velocity, linear pressure)
    if orders:
        host.order_combo = QComboBox()
        for k, text in orders.items():
            host.order_combo.addItem(text, k)
        host.order_combo.setToolTip(ORDER_TIP[dim])
        sim_ui.tame(host.order_combo, 24)
        f.addRow("Element order", host.order_combo)
    host.e_hmin = QLineEdit()
    host.e_hmin.setPlaceholderText("auto")
    host.e_hmin.setToolTip(HMIN_TIP[dim])
    host.hmin_label = QLabel("Minimum size")
    f.addRow(host.hmin_label, host.e_hmin)
    host.e_growth = QLineEdit("1.3")
    host.e_growth.setToolTip(f"How fast elements grow away from a refined {'face' if dim == 3 else 'edge or point' if dim == 'cfd' else 'edge, point or region'}: 1.3 = every layer of elements is 30 % longer "
                             f"than the one before. {growth_range[0]:g} to {growth_range[1]:g}. Smaller = a smoother mesh with more elements.")
    f.addRow("Growth rate", host.e_growth)
    al.addLayout(f)
    row = QHBoxLayout()
    host.cb_curv = QCheckBox(f"Refine at curved {CURVED[dim]}")
    host.cb_curv.setChecked(dim == 3)                                   # (3D: on by default, 10 per circle is the plain mesh; 2D: the plain mesh does not refine at curves)
    host.cb_curv.setToolTip(CURV_TIP[dim])
    row.addWidget(host.cb_curv)
    host.sp_curv = QSpinBox()
    host.sp_curv.setRange(*curv_range)
    host.sp_curv.setValue(10)
    host.sp_curv.setEnabled(dim == 3)
    host.sp_curv.setToolTip("Elements around a full circle (a hole, a round edge). 10 is the automatic choice; more gives a rounder, finer mesh.")
    host.sp_curv.setSuffix(" per circle")
    row.addWidget(host.sp_curv)
    al.addLayout(row)
    host.local_hdr = QLabel(f"Smaller elements on single {NOUN[dim]}: {WHAT[dim]}, type a size, press the button.")
    host.local_hdr.setWordWrap(True)
    host.local_hdr.setStyleSheet(HINT_STYLE)
    al.addWidget(host.local_hdr)
    row = QHBoxLayout()
    host.e_face_h = QLineEdit()
    host.e_face_h.setPlaceholderText("size")
    row.addWidget(host.e_face_h, 1)
    host.b_face_size = QPushButton("Set on selection")
    host.b_face_size.setToolTip(LOCAL_TIP[dim])
    host.b_face_size.clicked.connect(host.set_face_size)
    row.addWidget(host.b_face_size)
    al.addLayout(row)
    host.face_table = QTableWidget(0, 2)
    host.face_table.setHorizontalHeaderLabels(["Where", "Size"])
    host.face_table.verticalHeader().hide()
    host.face_table.setMinimumHeight(70)
    host.face_table.setMaximumHeight(130)
    host.face_table.horizontalHeader().setStretchLastSection(True)
    host.face_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    host.face_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    host.face_table.setToolTip("Double-click a size to change it.")
    host.face_table.itemChanged.connect(host.face_item_changed)
    al.addWidget(host.face_table)
    host.b_face_size_del = QPushButton("Remove selected size")
    host.b_face_size_del.clicked.connect(host.remove_face_size)
    al.addWidget(host.b_face_size_del)
    host.follows_combo = None
    if follows:
        f = QFormLayout()
        host.follows_combo = QComboBox()
        for k, text in follows.items():
            host.follows_combo.addItem(text, k)
        host.follows_combo.setToolTip("What the mesh follows: the borders of the patches of a split face lie on mesh edges, so a load or support on a patch "
                                      "covers exactly the patch.")
        f.addRow("Mesh follows", host.follows_combo)
        al.addLayout(f)
    host.adv_box.setVisible(False)
    v.addWidget(host.adv_box)
    host.cb_adv.toggled.connect(host.adv_toggled)
    if host.order_combo is not None:
        host.order_combo.activated.connect(lambda _i: host.inputs_changed())
    if host.type_combo is not None:
        host.type_combo.activated.connect(lambda _i: host.inputs_changed())
    if host.follows_combo is not None:
        host.follows_combo.activated.connect(lambda _i: host.inputs_changed())
    host.e_hmin.editingFinished.connect(host.inputs_changed)
    host.e_growth.editingFinished.connect(host.inputs_changed)
    host.cb_curv.toggled.connect(host.curv_toggled)
    host.sp_curv.valueChanged.connect(lambda _v: host.inputs_changed())


def build_quality(host, v):
    """The Mesh quality box under the Mesh button (shown only with the advanced options on, when there is a mesh)."""
    host.quality_box = QWidget()
    ql = QVBoxLayout(host.quality_box)
    ql.setContentsMargins(0, 0, 0, 0)
    ql.addWidget(QLabel("<b>Mesh quality</b>"))
    host.quality_lbl = QLabel("")
    host.quality_lbl.setWordWrap(True)
    host.quality_lbl.setTextFormat(Qt.TextFormat.RichText)
    host.quality_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    ql.addWidget(host.quality_lbl)
    host.quality_box.setVisible(False)
    v.addWidget(host.quality_box)


VERDICT_COLOUR = {"good": "#1b7f3b", "acceptable": "#a86a00", "poor": "#b3261e"}


def quality_html2d(qr, verdict, to_unit, unit, kind=None):
    """The text of the quality box for a 2D mesh (sim_mesh2d.quality): `to_unit` turns a length of the sketch into the unit shown, `unit` is its name; `kind`: what is
    said in the brackets after the number of nodes (default: the element order)."""
    n = qr["elements"]
    kind = kind or ("quadratic" if qr["order"] == 2 else "linear")
    return (f"{n:,} triangles, {qr['nodes']:,} nodes ({kind})<br>"
            f"Edge length: smallest {to_unit(qr['edge_min']):.4g}, average {to_unit(qr['edge_mean']):.4g}, largest {to_unit(qr['edge_max']):.4g} {unit}<br>"
            f"Worst element, radius ratio: {qr['ratio_min']:.3f} (1 = perfect; below 0.1 is poor)<br>"
            f"Angles: smallest {qr['angle_min']:.0f}&deg;, largest {qr['angle_max']:.0f}&deg;<br>"
            f"Elements below 0.2: {qr['below_02']:,} ({100.0 * qr['below_02'] / max(n, 1):.1f} %)<br>"
            f"Overall: <b style='color:{VERDICT_COLOUR[verdict]}'>{verdict}</b>")
