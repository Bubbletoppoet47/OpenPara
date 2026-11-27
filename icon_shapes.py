"""
icon_shapes.py - the drawings of the program's icons that are not in icon_set.py: sketch tools, tools, panel tabs, analysis, mates, loads.

One drawing per icon on a 24 x 24 grid.  The elements carry a role (b body, p paper, a accent, l line, n accent line, d dot, k solid ink, th pipe) and the
drawing a hue (feat blue, cut red, ref amber, asm teal, ana purple, cfg grey, ai magenta, dat green); icon_kit.py dresses them.
"""

CORE = {
    # ---- sketch tools
    "sketch_tool": ('<path class="b" d="M15 3.5l5.5 5.5L9.5 20l-5.500.5.5-5.500z"/><path class="a" d="M4 20.500l.5-5.500 5 5z"/><path class="l" d="M12.500 6l5.500 5.500"/>', "feat"),
    "exit_sketch": ('<path class="n" stroke-width="3" d="M4.500 12.500l5 5 10-11"/>', "dat"),
    "normal_to": ('<rect class="b" x="7" y="7" width="10" height="10" rx="1"/><path class="n" d="M12 2.500v3M12 18.500v3M2.500 12h3M18.500 12h3"/>', "feat"),
    "select": ('<path class="b" d="M6 3.500l12 9.500-5.500 1 3.200 5.800-2.600 1.400-3.200-5.800-3.900 3.800z"/>', "feat"),
    "line": ('<path class="l" stroke-width="2" d="M5 19L19 5"/><circle class="d" cx="5" cy="19" r="2"/><circle class="d" cx="19" cy="5" r="2"/>', "feat"),
    "centerline": ('<path class="l" stroke-width="2" stroke-dasharray="4 2 1 2" d="M5 19L19 5"/><circle class="d" cx="5" cy="19" r="2"/><circle class="d" cx="19" cy="5" r="2"/>', "feat"),
    "rectangle": ('<rect class="b" x="4" y="6" width="16" height="12"/><circle class="d" cx="4" cy="6" r="1.900"/><circle class="d" cx="20" cy="18" r="1.900"/>', "feat"),
    "circle": ('<circle class="b" cx="12" cy="12" r="8"/><circle class="d" cx="12" cy="12" r="1.900"/>', "feat"),
    "arc": ('<path class="l" stroke-width="2" d="M3.500 18a8.500 8.500 0 0 1 17 0"/><path class="l" stroke-width="1" stroke-dasharray="1.500 1.500" d="M3.500 18h17"/><circle class="d" cx="3.500" cy="18" r="2"/><circle class="d" cx="20.500" cy="18" r="2"/><circle class="d" cx="12" cy="18" r="1.500"/>', "feat"),
    "spline": ('<path class="l" stroke-width="2" d="M4 18C6 8 9 8 12 13s6 3 8-8"/><circle class="d" cx="4" cy="18" r="1.900"/><circle class="d" cx="20" cy="5" r="1.900"/>', "feat"),
    "slot": ('<rect class="b" x="3" y="8" width="18" height="8" rx="4"/><circle class="d" cx="7" cy="12" r="1.500"/><circle class="d" cx="17" cy="12" r="1.500"/>', "feat"),
    "polygon": ('<path class="b" d="M12 3l7.800 4.500v9L12 21l-7.800-4.500v-9z"/><circle class="d" cx="12" cy="12" r="1.900"/>', "feat"),
    "point": ('<path class="l" d="M12 3v5M12 16v5M3 12h5M16 12h5"/><circle class="d" cx="12" cy="12" r="2.800"/>', "feat"),
    "sketch_fillet": ('<path class="n" stroke-width="2" d="M5 20V11a6 6 0 0 1 6-6h9"/><circle class="d" cx="5" cy="20" r="1.900"/><circle class="d" cx="20" cy="5" r="1.900"/>', "feat"),
    "trim": ('<path class="l" stroke-width="2" d="M8 3v18M3 16h8"/><path class="n" stroke-width="1.600" stroke-dasharray="2 2" d="M11 16h4"/><path class="n" stroke-width="2.200" d="M15 7l6 6M21 7l-6 6"/>', "cut"),
    "offset": ('<rect class="b" x="3.500" y="3.500" width="17" height="17" rx="4"/><rect class="a" x="8" y="8" width="8" height="8" rx="2"/>', "feat"),
    "mirror_entities": ('<path class="a" d="M3 5l7 7-7 7z"/><path class="b" d="M21 5l-7 7 7 7z"/><path class="n" stroke-dasharray="2 2" d="M12 2.500v19"/>', "feat"),
    "sketch_pattern": ('<rect class="b" x="2.500" y="8" width="5" height="8" rx="1"/><rect class="b" x="9.500" y="8" width="5" height="8" rx="1"/><rect class="a" x="16.500" y="8" width="5" height="8" rx="1"/>', "feat"),
    "move_entities": ('<path class="n" stroke-width="2" d="M12 3v18M3 12h18M9.500 5.500L12 3l2.500 2.500M9.500 18.500L12 21l2.500-2.500M5.500 9.500L3 12l2.500 2.500M18.500 9.500L21 12l-2.500 2.500"/><circle class="d" cx="12" cy="12" r="2"/>', "feat"),
    "construction": ('<path class="l" stroke-width="2" stroke-dasharray="4 2.500" d="M3.500 20.500L20.500 3.500"/><circle class="d" cx="12" cy="12" r="1.800"/>', "feat"),
    "convert_entities": ('<rect class="b" x="3" y="3" width="9" height="9"/><path class="n" stroke-width="2" d="M9 9l10 10M19 12.500V19h-6.500"/>', "feat"),
    "add_relation": ('<path class="l" stroke-width="2" d="M5 3.500v16.500h16"/><rect class="a" x="5" y="14" width="6" height="6"/>', "feat"),
    "dimension": ('<path class="l" d="M4 4v8M20 4v8"/><path class="n" stroke-width="1.800" d="M4 8h16M4 8l3-2.200M4 8l3 2.200M20 8l-3-2.200M20 8l-3 2.200"/><rect class="p" x="8" y="14" width="8" height="6" rx="1"/>', "feat"),
    # ---- features and tools
    "shell": ('<rect class="b" x="3.500" y="3.500" width="17" height="17" rx="1.500"/><rect class="p" x="8" y="8" width="8" height="8"/>', "feat"),
    "mass_properties": ('<path class="l" stroke-width="1.800" d="M12 5v14.500M7 20.500h10M4.500 8h15"/><path class="b" d="M4.500 8L2 14h5z"/><path class="b" d="M19.500 8L17 14h5z"/><circle class="d" cx="12" cy="4.500" r="1.800"/>', "ref"),
    "section_properties": ('<path class="b" d="M6 4h12v3.500h-4.500v9H18V20H6v-3.500h4.500v-9H6z"/><path class="n" stroke-width="1.600" stroke-dasharray="2.500 1.500" d="M2.500 12h19"/><circle class="d" cx="12" cy="12" r="1.900"/>', "ref"),
    "measure": ('<path class="b" d="M4 16L16 4l4 4L8 20z"/><path class="l" d="M7 13l2 2M10 10l2 2M13 7l2 2"/>', "ref"),
    "insert_components": ('<path class="b" d="M3 9h10v10H3z"/><path class="b" d="M3 9l4-4h10l-4 4z"/><path class="b" d="M13 9l4-4v10l-4 4z"/><path class="n" stroke-width="2.200" d="M19 3v6M16 6h6"/>', "asm"),
    "edit_component": ('<path class="b" d="M3 10h10v10H3z"/><path class="b" d="M3 10l4-4h10l-4 4z"/><path class="b" d="M13 10l4-4v10l-4 4z"/><path class="a" d="M19.500 3l2 2-7 7-3 1 1-3z"/>', "asm"),
    # ---- tools that have no ribbon button yet (drawn in icons.py as a grey square before)
    "wrap": ('<path class="b" d="M5 8c0-2.500 3-4 7-4s7 1.500 7 4v8c0 2.500-3 4-7 4s-7-1.500-7-4z"/><ellipse class="p" cx="12" cy="8" rx="7" ry="3"/><path class="a" d="M5 12.500c0 1.700 3.100 3 7 3s7-1.300 7-3v3c0 1.700-3.100 3-7 3s-7-1.300-7-3z"/>', "feat"),
    "boundary_boss": ('<path class="b" d="M4 6c5-2.500 11-2.500 16 0v11c-5 2.500-11 2.500-16 0z"/><path class="n" d="M4 6c5 2.500 11 2.500 16 0M4 17c5-2.500 11-2.500 16 0"/>', "feat"),
    "boundary_cut": ('<path class="b" d="M4 6c5-2.500 11-2.500 16 0v11c-5 2.500-11 2.500-16 0z"/><path class="n" d="M4 6c5 2.500 11 2.500 16 0M4 17c5-2.500 11-2.500 16 0"/><path class="n" stroke-dasharray="2 2" d="M12 5v14"/>', "cut"),
    "rib": ('<path class="b" d="M3 20h18v-4H3z"/><path class="a" d="M9.500 16V5l7 11z"/>', "feat"),
    "draft": ('<path class="b" d="M4 20V5h9v15z"/><path class="a" d="M13 5l6 15h-6z"/>', "feat"),
    "intersect": ('<circle class="b" cx="9" cy="12" r="6"/><circle class="b" cx="15" cy="12" r="6"/><path class="a" d="M12 7.100a6 6 0 0 1 0 9.800 6 6 0 0 1 0-9.800z"/>', "feat"),
    # ---- side-panel tabs
    "panel_tree": ('<rect class="b" x="3" y="3" width="7" height="5" rx="1"/><path class="l" d="M6.500 8v10.500M6.500 12h5.500M6.500 18.500h5.500"/><rect class="a" x="12" y="9.700" width="9" height="4.600" rx="1"/><rect class="a" x="12" y="16.200" width="9" height="4.600" rx="1"/>', "asm"),
    "panel_properties": ('<rect class="p" x="3" y="3.500" width="18" height="17" rx="2"/><path class="n" stroke-width="2" d="M6 8h3M6 12h3M6 16h3"/><path class="l" d="M11.500 8h6M11.500 12h6M11.500 16h6"/>', "cfg"),
    "panel_configurations": ('<rect class="p" x="3" y="4" width="18" height="16" rx="1.500"/><path class="l" d="M3 9h18M3 14.500h18M9 9v11"/><path class="n" stroke-width="2" d="M4.500 12.200l1.600 1.600 2.400-3"/>', "dat"),
    "panel_equations": ('<path class="l" stroke-width="2.400" d="M3 9h7M3 15h7"/><path class="n" stroke-width="2.400" d="M14 6l7 12M21 6l-7 12"/>', "cfg"),
    "panel_display": ('<circle class="b" cx="12" cy="12" r="8.500"/><path class="a" d="M3.800 13.500a8.500 8.500 0 0 0 16.400 0c-3.300 2-13.100 2-16.400 0z"/><path class="n" stroke-width="1.600" d="M3.600 11.500c3.600 2.600 13.200 2.600 16.800 0"/><ellipse class="p" cx="8.800" cy="7.800" rx="2.400" ry="1.500"/>', "ana"),
    # ---- analysis and render
    "fea_1d": ('<path class="l" stroke-width="1.800" d="M4 19h16M4 19l8-11 8 11M8.500 13h7"/><circle class="d" cx="12" cy="8" r="1.700"/><path class="n" stroke-width="1.800" d="M12 2v3.500M10 4l2 2 2-2"/>', "ana"),
    "fea_2d": ('<rect class="b" x="3" y="4" width="18" height="16" rx="1"/><path class="n" d="M3 9.300h18M3 14.700h18M9 4v16M15 4v16"/><circle class="p" cx="12" cy="12" r="3.200"/>', "ana"),
    "cfd_2d": ('<circle class="b" cx="11" cy="12" r="3.400"/><path class="n" stroke-width="1.800" d="M2 6h9c5 0 7 1 11 1M2 18h9c5 0 7-1 11-1M2 12h4M16 12h6"/>', "ana"),
    "new_render": ('<rect class="b" x="2.500" y="8" width="16" height="12" rx="2"/><circle class="a" cx="10.500" cy="14" r="3.400"/><path class="l" d="M6 8l1.200-2.500h6.600L15 8"/><path class="n" stroke-width="2" d="M20 2.500v5M17.500 5h5"/>', "ana"),
    # ---- mates (mate_icons.py names, with m_ in front)
    "m_coincident": ('<path class="l" d="M3 19h18"/><rect class="b" x="7" y="8" width="10" height="11"/><circle class="d" cx="12" cy="19" r="1.900"/>', "asm"),
    "m_parallel": ('<path class="n" stroke-width="2.200" d="M7 20L15 4M13 20l8-16"/>', "asm"),
    "m_perpendicular": ('<path class="l" stroke-width="2" d="M3 19h18"/><path class="n" stroke-width="2.200" d="M12 4v15"/><rect class="a" x="12" y="15" width="4" height="4"/>', "asm"),
    "m_tangent": ('<circle class="b" cx="12" cy="10" r="6.500"/><path class="l" stroke-width="1.800" d="M3 16.500h18"/><circle class="d" cx="12" cy="16.500" r="1.900"/>', "asm"),
    "m_concentric": ('<circle class="b" cx="12" cy="12" r="9"/><circle class="p" cx="12" cy="12" r="5"/><circle class="d" cx="12" cy="12" r="1.900"/>', "asm"),
    "m_lock": ('<path class="l" stroke-width="2" d="M8 11V8a4 4 0 0 1 8 0v3"/><rect class="b" x="5" y="11" width="14" height="10" rx="2"/><circle class="d" cx="12" cy="16" r="1.700"/>', "asm"),
    "m_distance": ('<path class="l" stroke-width="1.800" d="M4 4v16M20 4v16"/><path class="n" stroke-width="1.800" d="M4 12h16M4 12l3-2.500M4 12l3 2.500M20 12l-3-2.500M20 12l-3 2.500"/>', "asm"),
    "m_angle": ('<path class="l" stroke-width="2" d="M4 20h17M4 20L17 5"/><path class="n" stroke-width="1.800" d="M12 20A8 8 0 0 0 9.200 14"/>', "asm"),
    "m_symmetric": ('<rect class="b" x="3" y="8" width="6" height="8"/><rect class="a" x="15" y="8" width="6" height="8"/><path class="n" stroke-dasharray="2 2" d="M12 3v18"/>', "asm"),
    "m_face": ('<path class="b" d="M3 18l5-12h13l-5 12z"/>', "asm"),
    "m_edge": ('<rect class="b" x="4" y="10" width="10" height="10"/><path class="l" d="M4 10l5-5h10l-5 5M19 5v10l-5 5"/><path class="n" stroke-width="3" d="M4 20h10"/>', "asm"),
    "m_vertex": ('<path class="l" stroke-width="1.800" d="M12 12L4 17M12 12l8 5M12 12V3"/><circle class="d" cx="12" cy="12" r="2.800"/>', "asm"),
    # ---- the geometry selector of the 3D views (view3d.py): General, Point, Edge, Face, Body
    "sel_general": ('<path class="b" d="M6 3.500l12 9.500-5.500 1 3.200 5.800-2.600 1.400-3.200-5.800-3.900 3.800z"/>', "feat"),
    "sel_point": ('<path class="l" d="M4 9h10v10H4zM9 4h10v10H9zM4 9l5-5M14 9l5-5M14 19l5-5"/><circle class="d" cx="14" cy="9" r="2.600"/>', "feat"),
    "sel_edge": ('<path class="l" d="M4 9h10v10H4zM9 4h10v10H9zM4 9l5-5M14 9l5-5M14 19l5-5"/><path class="n" stroke-width="3" d="M4 9h10"/>', "feat"),
    "sel_face": ('<path class="b" d="M9 4h10v10H9z" opacity="0.5"/><path class="l" d="M4 9h10v10H4zM9 4h10v10H9zM4 9l5-5M14 9l5-5M14 19l5-5"/><rect class="a" x="4" y="9" width="10" height="10"/>', "feat"),
    "sel_body": ('<path class="b" d="M4 9l5-5h10v10l-5 5H4z"/><path class="l" d="M4 9h10v10H4zM9 4h10v10H9zM4 9l5-5M14 9l5-5M14 19l5-5"/>', "feat"),
    # ---- loads and supports (sim_icons.py names, with l_ in front)
    "l_pressure_cfd": ('<path class="n" stroke-width="1.800" d="M3.500 3.500L8.500 8.500M4.500 8.500h4v-4M20.500 3.500L15.500 8.500M19.500 8.500h-4v-4M3.500 20.500L8.500 15.500M4.500 15.500h4v4M20.500 20.500L15.500 15.500M19.500 15.500h-4v4"/><path class="b" d="M12 9l3 3-3 3-3-3z"/>', "ana"),
    "l_pressure": ('<path class="n" stroke-width="1.800" d="M6 3v9M12 3v9M18 3v9M3.500 9.500L6 12l2.500-2.500M9.500 9.500L12 12l2.500-2.500M15.500 9.500L18 12l2.500-2.500"/><rect class="b" x="3" y="14.500" width="18" height="4" rx="1"/>', "ana"),
    "l_fixed": ('<rect class="b" x="8" y="3.500" width="8" height="6.500"/><path class="l" stroke-width="2" d="M3 10h18"/><path class="l" d="M5 18l4-8M10 18l4-8M15 18l4-8"/>', "ana"),
    "l_bolt": ('<rect class="b" x="3" y="8" width="18" height="3"/><rect class="b" x="3" y="13" width="18" height="3"/><rect class="a" x="10.500" y="5" width="3" height="16"/><rect class="a" x="8" y="3" width="8" height="3" rx=".8"/>', "ana"),
    "l_screw": ('<path class="a" d="M9 6h6v11l-3 4-3-4z"/><path class="l" d="M9 9.500l6 2M9 13l6 2"/><rect class="b" x="6" y="3" width="12" height="3.500" rx="1"/>', "ana"),
    "l_contact": ('<rect class="b" x="7" y="4" width="10" height="8"/><path class="l" d="M3 12h18M5 17h14M8 21h8"/><path class="n" stroke-width="2.600" d="M7 12h10"/>', "ana"),
    "l_line_load": ('<path class="n" stroke-width="1.800" d="M5 3v11M10 3v11M15 3v11M20 3v11M3.500 11.500L5 14l1.500-2.500M8.500 11.500L10 14l1.500-2.500M13.500 11.500L15 14l1.500-2.500M18.500 11.500L20 14l1.500-2.500"/><path class="l" stroke-width="2.400" d="M3 18h18"/>', "ana"),
    "l_ux": ('<path class="n" stroke-width="1.800" d="M3 12h18M3 12l3-3M3 12l3 3M21 12l-3-3M21 12l-3 3"/><path class="l" stroke-width="2.200" d="M10 17l4-10"/>', "ana"),
    "l_uy": ('<path class="n" stroke-width="1.800" d="M12 3v18M12 3l-3 3M12 3l3 3M12 21l-3-3M12 21l3-3"/><path class="l" stroke-width="2.200" d="M7 10l10 4"/>', "ana"),
    "l_force": ('<path class="n" stroke-width="2.200" d="M3 12h17M15 7l5 5-5 5"/>', "ana"),
    "l_disp": ('<path class="l" stroke-width="2" d="M3 18h18"/><path class="l" d="M5 22l3-4M10 22l3-4M15 22l3-4"/><path class="l" d="M7 12.500V18"/><circle class="b" cx="7" cy="10" r="2.500"/><path class="n" stroke-width="2.200" d="M11.500 10H20M16.500 6.500L20 10l-3.500 3.500"/>', "ana"),
    "l_moment": ('<path class="n" stroke-width="2" d="M19 12a7 7 0 1 1-2.300-5.200"/><path class="n" stroke-width="2" d="M19.500 3.500v4h-4"/>', "ana"),
    "l_wind": ('<path class="n" stroke-width="2" d="M3 9h11a3 3 0 1 0-3-3M3 14h15a3 3 0 1 1-3 3M3 19h8"/>', "ana"),
    "l_snow": ('<path class="n" stroke-width="1.800" d="M12 3v18M4.200 7.500l15.600 9M4.200 16.500l15.600-9"/><circle class="d" cx="12" cy="12" r="1.800"/>', "ana"),
    "l_pinned": ('<path class="b" d="M12 5l6 10H6z"/><path class="l" d="M3 15h18M5 21l3-6M10 21l3-6M15 21l3-6"/><circle class="d" cx="12" cy="5.500" r="1.700"/>', "ana"),
    "l_pinned_joint": ('<circle class="p" cx="12" cy="12" r="7"/><circle class="d" cx="12" cy="12" r="1.700"/>', "ana"),
    "l_rigid_joint": ('<circle class="a" cx="12" cy="12" r="7"/>', "ana"),

    # ---- one for any run button
    "run": ('<path class="a" d="M7 4l13 8-13 8z"/>', "dat"),
}
