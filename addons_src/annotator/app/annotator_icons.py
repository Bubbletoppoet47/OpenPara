"""annotator_icons.py - the drawings of the annotator's ribbon and side-panel tabs, in the icon look of the rest of OpenPara (icon_kit).

Inside OpenPara the drawings are registered with icon_kit ("ann_..." names) and `icon(key, px)` returns a QIcon; on its own (no icon_kit around
it) `icon()` returns None and the ribbon shows text-only buttons, so nothing in the annotator depends on the icons being there.
"""
try:
    import icon_kit
except ImportError:
    icon_kit = None

# {name: (svg elements on a 24 x 24 grid, hue)}; element classes: b body, p paper, a accent, l ink line, n accent line, d dot, k solid ink
ICONS = {
    # ---- Annotate
    "ann_confirm": ('<circle class="a" cx="12" cy="12" r="9"/><path class="l" d="M7.5 12.5l3 3 6-7" stroke-width="2"/>', "asm"),
    "ann_prev": ('<circle class="b" cx="12" cy="12" r="9"/><path class="l" d="M13.8 7.5L9.3 12l4.5 4.5" stroke-width="2"/>', "feat"),
    "ann_next": ('<circle class="b" cx="12" cy="12" r="9"/><path class="l" d="M10.2 7.5l4.5 4.5-4.5 4.5" stroke-width="2"/>', "feat"),
    "ann_fit": ('<rect class="a" x="8.5" y="8.5" width="7" height="7"/><path class="l" d="M3 8.5V3h5.5M15.5 3H21v5.5M21 15.5V21h-5.5M8.5 21H3v-5.5"/>', "feat"),
    "ann_rotate": ('<path class="n" d="M19.5 12.5a7.5 7.5 0 1 1-2.4-5.5" stroke-width="2"/><path class="l" d="M19.8 3v5h-5"/>', "ref"),
    "ann_delete_frame": ('<path class="b" d="M6 8.5h12l-1 12H7z"/><path class="l" d="M4 8.5h16M9 8.5V5h6v3.5M10.2 11.5v6M13.8 11.5v6"/>', "cut"),
    "ann_lidar": ('<rect class="p" x="3" y="4" width="18" height="16"/><circle class="d" cx="7.5" cy="8.5" r="1.2"/><circle class="d" cx="12" cy="8.5" r="1.2"/>'
                  '<circle class="d" cx="16.5" cy="8.5" r="1.2"/><circle class="d" cx="9.5" cy="12.5" r="1.2"/><circle class="d" cx="14" cy="12.5" r="1.2"/>'
                  '<circle class="d" cx="7.5" cy="16.5" r="1.2"/><circle class="d" cx="12" cy="16.5" r="1.2"/><circle class="d" cx="16.5" cy="16.5" r="1.2"/>', "feat"),
    "ann_clear_dist": ('<path class="b" d="M3 9.5h18v6H3z"/><path class="l" d="M7 9.5v3M11 9.5v3M15 9.5v3"/><path class="n" d="M15.5 17.5l5 5M20.5 17.5l-5 5" stroke-width="2"/>', "cut"),
    "ann_delete_box": ('<rect class="p" x="3" y="5" width="14" height="12" style="opacity:.95" stroke-dasharray="2.5 1.8"/><path class="n" d="M14.5 14.5l6 6M20.5 14.5l-6 6" stroke-width="2.2"/>', "cut"),
    "ann_retry_ai": ('<path class="a" d="M10 3.5l1.9 5.1 5.1 1.9-5.1 1.9L10 17.5l-1.9-5.1L3 10.5l5.1-1.9z"/><path class="n" d="M21 14.5a5 5 0 1 1-1.6-3.7" stroke-width="1.8"/>'
                     '<path class="l" d="M21.3 8.3v3h-3"/>', "ai"),
    # ---- Data
    "ann_import_video": ('<rect class="b" x="3" y="4" width="18" height="12"/><path class="a" d="M10 7.5v5l4.2-2.5z"/><path class="l" d="M12 17.5v4.5M9.5 20l2.5 2.5 2.5-2.5"/>', "dat"),
    "ann_import_zip": ('<path class="b" d="M3 8l2-3h14l2 3v12H3z"/><path class="l" d="M3 8h18M12 10.5v6M9 14l3 3 3-3"/>', "dat"),
    "ann_export_zip": ('<path class="b" d="M3 8l2-3h14l2 3v12H3z"/><path class="l" d="M3 8h18M12 16.5v-6M9 13.5l3-3 3 3"/>', "dat"),
    "ann_tablet": ('<rect class="b" x="5" y="2.5" width="14" height="19" rx="1.5"/><rect class="p" x="7" y="5" width="10" height="12.5"/><circle class="d" cx="12" cy="19.5" r="1"/>', "dat"),
    "ann_sessions": ('<rect class="b" x="3" y="3.5" width="14" height="10"/><rect class="b" x="7" y="7.5" width="14" height="10"/><rect class="p" x="5" y="11.5" width="14" height="9"/>', "dat"),
    "ann_sync": ('<path class="n" d="M4.5 10a7.5 7.5 0 0 1 13-3.5M19.5 14a7.5 7.5 0 0 1-13 3.5" stroke-width="2"/><path class="l" d="M18 2.5v4.5h-4.5M6 21.5V17h4.5"/>', "dat"),
    "ann_gimble_import": ('<rect class="b" x="3" y="8" width="18" height="11" rx="1.5"/><circle class="p" cx="12" cy="13.5" r="3.4"/><path class="l" d="M9 8l1.2-2.5h3.6L15 8"/><path class="n" d="M12 1.5v3M10.5 3.5l1.5 1.8 1.5-1.8" stroke-width="1.8"/>', "dat"),
    "ann_gimble_dl": ('<rect class="b" x="3" y="12" width="18" height="8" rx="1.5"/><circle class="d" cx="17" cy="16" r="1"/><path class="l" d="M12 2.5v8M8.5 7.5l3.5 3.5 3.5-3.5"/>', "dat"),
    "ann_gimble_status": ('<rect class="b" x="3" y="4" width="18" height="16" rx="1.5"/><path class="n" d="M5.5 13h3l2-5 3 9 2-4h3" stroke-width="1.8"/>', "dat"),
    "ann_addon": ('<rect class="b" x="4" y="4" width="16" height="16" rx="2"/><path class="l" d="M12 8v8M8 12h8" stroke-width="2"/>', "cfg"),
    # ---- Models
    "ann_model_load": ('<path class="b" d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path class="l" d="M4 7.5l8 4.5 8-4.5M12 12v9"/><path class="a" d="M12 12l8-4.5v9L12 21z" style="opacity:.55"/>', "ai"),
    "ann_model_dl": ('<path class="b" d="M12 8l7 4v8l-7 3.5L5 20v-8z" transform="translate(0 -1.5)"/><path class="l" d="M12 1.5v7M8.8 5.8L12 9l3.2-3.2"/>', "ai"),
    "ann_conf": ('<path class="l" d="M3 12h18"/><path class="a" d="M3 12h11"/><circle class="b" cx="14" cy="12" r="3.2"/><path class="l" d="M3 6.5h4M3 17.5h4"/>', "ai"),
    "ann_gimble_send": ('<rect class="b" x="3" y="8" width="13" height="11" rx="1.5"/><circle class="p" cx="9.5" cy="13.5" r="3"/><path class="l" d="M7 8l1-2h3l1 2"/><path class="n" d="M17 4.5h5M19.7 2l2.8 2.5-2.8 2.5" stroke-width="1.8"/>', "ai"),
    # ---- Setup
    "ann_classes": ('<rect class="p" x="3" y="3.5" width="18" height="17"/><rect class="a" x="5.5" y="6.5" width="3" height="3"/><rect class="b" x="5.5" y="10.5" width="3" height="3"/><rect class="p" x="5.5" y="14.5" width="3" height="3"/><path class="l" d="M11 8h7M11 12h7M11 16h7"/>', "cfg"),
    "ann_hotkeys": ('<rect class="b" x="3" y="6" width="18" height="12" rx="2"/><rect class="p" x="5.5" y="8.5" width="13" height="7" rx="1"/><path class="l" d="M8 12h8" stroke-width="1.4"/>', "cfg"),
    "ann_name": ('<circle class="b" cx="12" cy="8" r="3.8"/><path class="b" d="M4.5 21c0-4.5 3.4-7.2 7.5-7.2s7.5 2.7 7.5 7.2z"/>', "cfg"),
    # ---- the three tabs of the side panel
    "ann_tab_frames": ('<rect class="p" x="3" y="4" width="18" height="16"/><path class="l" d="M3 9.3h18M3 14.7h18M9 4v16"/><rect class="a" x="10.5" y="10.4" width="9" height="3" style="opacity:.7"/>', "feat"),
    "ann_tab_box": ('<rect class="p" x="5" y="6.5" width="14" height="11" stroke-dasharray="2.5 1.8"/><rect class="k" x="3.3" y="4.8" width="3.4" height="3.4"/><rect class="k" x="17.3" y="4.8" width="3.4" height="3.4"/>'
                    '<rect class="k" x="3.3" y="15.8" width="3.4" height="3.4"/><rect class="k" x="17.3" y="15.8" width="3.4" height="3.4"/>', "feat"),
    "ann_tab_ai": ('<path class="a" d="M10.5 3l2.1 5.7 5.7 2.1-5.7 2.1-2.1 5.7-2.1-5.7L2.7 10.8l5.7-2.1z"/><path class="a" d="M18.5 14.5l.9 2.4 2.4.9-2.4.9-.9 2.4-.9-2.4-2.4-.9 2.4-.9z"/>', "ai"),
}

_done = False


def _register():
    global _done
    if _done or icon_kit is None:
        return icon_kit is not None
    icon_kit.register(ICONS)
    _done = True
    return True


def icon(key, px=36):
    """The QIcon of a drawing, or None when OpenPara's icon kit is not there (the button then shows its text alone)."""
    if not _register():
        return None
    try:
        return icon_kit.qicon(key, px)
    except Exception:  # noqa: BLE001  (a missing drawing must never take a window down)
        return None
