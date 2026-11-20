"""
sh_icons.py - the drawings of the Sheets icons (ribbon, chart panel, dialogs), registered with the program's icon kit (icon_kit.py).

Keys start with s_.  icon(key, px) -> QIcon / pixmap(key, px) -> QPixmap; the ribbon draws them at the size the person sets.
"""
import icon_kit
from PyQt6.QtCore import QSize

SHEETS = {
    "s_new": ('<path class="p" d="M5 3h9l5 5v13H5z"/><path class="l" d="M14 3v5h5"/>', "dat"),
    "s_open": ('<path class="b" d="M3 6h6l2 2h9v11H3z"/><path class="a" d="M3 19l3-8h16l-3 8z"/>', "ref"),
    "s_save": ('<path class="b" d="M4 3h13l3 3v15H4z"/><rect class="a" x="7" y="3" width="9" height="6"/><rect class="p" x="7" y="13" width="10" height="8"/>', "feat"),
    "s_save_as": ('<path class="b" d="M3 3h11l3 3v11H3z"/><rect class="a" x="5.500" y="3" width="7" height="5"/><rect class="p" x="5.500" y="11" width="8" height="6"/><path class="a" d="M14 21l1-3.500 5-5 2.500 2.500-5 5z"/>', "feat"),
    "s_paste": ('<rect class="b" x="4" y="4" width="14" height="17" rx="1.500"/><rect class="a" x="8" y="2.500" width="6" height="4" rx="1"/><path class="p" d="M10 10h11v11H10z"/>', "ref"),
    "s_paste_special": ('<rect class="b" x="4" y="4" width="14" height="17" rx="1.500"/><rect class="a" x="8" y="2.500" width="6" height="4" rx="1"/><path class="p" d="M10 10h11v11H10z"/><path class="n" stroke-width="2" d="M15.500 12.500v6M12.500 15.500h6"/>', "ref"),
    "s_cut": ('<path class="l" d="M8.500 14.500L17 3M15.500 14.500L7 3"/><circle class="p" cx="7" cy="18" r="3"/><circle class="p" cx="17" cy="18" r="3"/>', "cut"),
    "s_copy": ('<path class="p" d="M4 3h9l3 3v11H4z"/><path class="p" d="M9 8h9l3 3v11H9z"/><path class="l" d="M11.500 14h6M11.500 17.500h6"/>', "cfg"),
    "s_bold": ('<path class="k" fill-rule="evenodd" d="M7 4h6.500a4 4 0 0 1 2.600 7 4.300 4.300 0 0 1-1.600 8.500H7zM10.200 7v3.400h3a1.700 1.700 0 0 0 0-3.400zM10.200 13.300v3.500h3.600a1.750 1.750 0 0 0 0-3.500z"/>', "cfg"),
    "s_italic": ('<path class="k" d="M10.500 4h7l-.4 2.200h-2L12.400 17.800h2L14 20H7l.4-2.200h2L11.800 6.200h-2z"/>', "cfg"),
    "s_fg": ('<path class="k" fill-rule="evenodd" d="M12 3.500l6.500 14h-2.600l-1.200-2.800H9.300L8.100 17.500H5.500zM12 8.500l-2 4.700h4z"/><rect class="a" x="4" y="19.500" width="16" height="3"/>', "cut"),
    "s_bg": ('<path class="b" d="M3.500 13L11 5.500l7 7L10.500 20z"/><path class="l" d="M9 8l-1.500-4L11 3"/><path class="a" d="M20.500 14c1.300 1.800 2 2.900 2 3.900a2 2 0 0 1-4 0c0-1 .7-2.100 2-3.900z"/>', "ref"),
    "s_number": ('<ellipse class="l" stroke-width="2.200" cx="6" cy="11" rx="2.800" ry="4.200"/><rect class="k" x="10.200" y="14" width="2.600" height="2.600"/><ellipse class="l" stroke-width="2.200" cx="17" cy="11" rx="2.800" ry="4.200"/><path class="n" stroke-width="1.600" d="M3 20.500h18"/>', "cfg"),
    "s_dec_up": ('<circle class="k" cx="5" cy="15" r="1.200"/><ellipse class="l" stroke-width="1.800" cx="10.500" cy="12" rx="2.500" ry="3.800"/><path class="n" stroke-width="2.200" d="M18 8v8M14 12h8"/>', "dat"),
    "s_dec_dn": ('<circle class="k" cx="5" cy="15" r="1.200"/><ellipse class="l" stroke-width="1.800" cx="10.500" cy="12" rx="2.500" ry="3.800"/><path class="n" stroke-width="2.200" d="M14 12h8"/>', "cut"),
    "s_ins_row": ('<rect class="p" x="3" y="3" width="18" height="18" rx="1"/><path class="l" d="M3 9h18M3 15h18M9 3v18"/><rect class="a" x="3" y="9" width="18" height="6"/><circle class="a" cx="17.500" cy="17.500" r="4.600"/><path class="l" stroke-width="1.600" d="M17.500 15v5M15 17.500h5"/>', "dat"),
    "s_ins_col": ('<rect class="p" x="3" y="3" width="18" height="18" rx="1"/><path class="l" d="M3 9h18M9 3v18M15 3v18"/><rect class="a" x="9" y="3" width="6" height="18"/><circle class="a" cx="17.500" cy="17.500" r="4.600"/><path class="l" stroke-width="1.600" d="M17.500 15v5M15 17.500h5"/>', "dat"),
    "s_del_row": ('<rect class="p" x="3" y="3" width="18" height="18" rx="1"/><path class="l" d="M3 9h18M3 15h18M9 3v18"/><rect class="a" x="3" y="9" width="18" height="6"/><circle class="a" cx="17.500" cy="17.500" r="4.600"/><path class="l" stroke-width="1.600" d="M15 17.500h5"/>', "cut"),
    "s_del_col": ('<rect class="p" x="3" y="3" width="18" height="18" rx="1"/><path class="l" d="M3 9h18M9 3v18M15 3v18"/><rect class="a" x="9" y="3" width="6" height="18"/><circle class="a" cx="17.500" cy="17.500" r="4.600"/><path class="l" stroke-width="1.600" d="M15 17.500h5"/>', "cut"),
    "s_fill_down": ('<rect class="p" x="3" y="3" width="10" height="18"/><path class="l" d="M3 9h10M3 15h10"/><rect class="a" x="3" y="3" width="10" height="6"/><path class="n" stroke-width="2" d="M18 6v11M14.500 13.500L18 17l3.500-3.500"/>', "dat"),
    "s_fill_right": ('<rect class="p" x="3" y="3" width="18" height="10"/><path class="l" d="M9 3v10M15 3v10"/><rect class="a" x="3" y="3" width="6" height="10"/><path class="n" stroke-width="2" d="M6 18h11M13.500 14.500L17 18l-3.500 3.500"/>', "dat"),
    "s_clear": ('<path class="b" d="M8 5h13v14H8l-5-7z"/><path class="n" stroke-width="2" d="M12 9l6 6M18 9l-6 6"/>', "cut"),
    "s_fit": ('<rect class="p" x="6" y="4" width="12" height="16"/><path class="n" stroke-width="2" d="M2 12h20M2 12l3-3M2 12l3 3M22 12l-3-3M22 12l-3 3"/>', "cfg"),
    "s_undo": ('<path class="n" stroke-width="2.200" d="M9 5L4 9.500 9 14M4.500 9.500H14a5.500 5.500 0 0 1 0 11h-4"/>', "feat"),
    "s_redo": ('<path class="n" stroke-width="2.200" d="M15 5l5 4.500-5 4.500M19.500 9.500H10a5.500 5.500 0 0 0 0 11h4"/>', "feat"),
    "s_study_in": ('<rect class="p" x="3" y="12" width="18" height="9" rx="1"/><path class="l" d="M3 16.500h18M9 12v9M15 12v9"/><path class="n" stroke-width="2.200" d="M12 2v8M8.500 6.500L12 10l3.500-3.500"/>', "ana"),
    "s_study_sel": ('<rect class="p" x="4" y="6" width="16" height="12" rx="1"/><path class="l" d="M4 10h16M9.500 6v12M14.500 6v12"/><rect class="n" stroke-width="1.800" stroke-dasharray="3 2" fill="none" x="2" y="3.500" width="20" height="17" rx="1"/>', "ana"),
    "s_study_del": ('<rect class="p" x="2" y="4" width="15" height="11" rx="1"/><path class="l" d="M2 8h15M7 4v11M12 4v11"/><path class="n" stroke-width="2.200" d="M14.500 14.500l7 7M21.500 14.500l-7 7"/>', "ana"),
    "s_study_refresh": ('<path class="n" stroke-width="2.200" d="M19 12a7 7 0 1 1-2.300-5.200"/><path class="n" stroke-width="2.200" d="M19.500 3.500v4.500H15"/>', "ana"),
    "s_xl_in": ('<path class="p" d="M9 3h7l4 4v14H9z"/><path class="n" stroke-width="2.200" d="M11.500 11l5 6M16.500 11l-5 6"/><path class="n" stroke-width="2" d="M2 12h5.500M5 9l3 3-3 3"/>', "dat"),
    "s_xl_out": ('<path class="p" d="M4 3h7l4 4v14H4z"/><path class="n" stroke-width="2.200" d="M6.500 11l5 6M11.500 11l-5 6"/><path class="n" stroke-width="2" d="M16.500 12H22M19 9l3 3-3 3"/>', "dat"),
    "s_names": ('<path class="b" d="M3 12l9-9h9v9l-9 9z"/><circle class="p" cx="16.500" cy="7.500" r="1.900"/>', "ref"),
    "s_sh_add": ('<rect class="p" x="3" y="5" width="15" height="15" rx="1"/><path class="l" d="M3 10h15M8 5v15"/><circle class="a" cx="17.500" cy="6.500" r="4.600"/><path class="l" stroke-width="1.600" d="M17.500 4v5M15 6.500h5"/>', "dat"),
    "s_sh_dup": ('<rect class="p" x="3" y="3" width="13" height="13"/><path class="l" d="M3 8h13M8 3v13"/><rect class="p" x="8" y="8" width="13" height="13"/><path class="l" d="M8 13h13M13 8v13"/>', "dat"),
    "s_sh_del": ('<rect class="p" x="3" y="5" width="15" height="15" rx="1"/><path class="l" d="M3 10h15M8 5v15"/><circle class="a" cx="17.500" cy="6.500" r="4.600"/><path class="l" stroke-width="1.600" d="M15 6.500h5"/>', "cut"),
    "s_sh_paste": ('<rect class="p" x="3" y="3" width="8" height="8"/><rect class="p" x="3" y="13" width="8" height="8"/><path class="n" stroke-width="2" d="M13 7h8M18 4l3 3-3 3M13 17h8M18 14l3 3-3 3"/>', "dat"),
    "s_ch_new": ('<path class="l" d="M3.500 3v17.500H21"/><rect class="a" x="6.500" y="12" width="3.500" height="8.500"/><rect class="b" x="12" y="6.500" width="3.500" height="14"/><rect class="a" x="17.500" y="14" width="3" height="6.500"/><circle class="a" cx="18" cy="6" r="4.200"/><path class="l" stroke-width="1.600" d="M18 3.800v4.400M15.800 6h4.400"/>', "feat"),
    "s_ch_edit": ('<path class="l" d="M3.500 3v17.500H21"/><rect class="a" x="6.500" y="12" width="3.500" height="8.500"/><rect class="b" x="12" y="6.500" width="3.500" height="14"/><rect class="a" x="17.500" y="14" width="3" height="6.500"/><path class="a" d="M17 2.500l3.500 3.500-6 6-4 .5.5-4z"/>', "feat"),
    "s_ch_copy": ('<path class="p" d="M4 3h9l3 3v11H4z"/><path class="p" d="M9 8h9l3 3v11H9z"/><rect class="a" x="11" y="16" width="2.500" height="4"/><rect class="b" x="14.500" y="13" width="2.500" height="7"/><rect class="a" x="18" y="15" width="1.800" height="5"/>', "feat"),
    "s_ch_export": ('<path class="l" d="M3.500 3v17.500H21"/><rect class="a" x="6.500" y="12" width="3.500" height="8.500"/><rect class="b" x="12" y="6.500" width="3.500" height="14"/><rect class="a" x="17.500" y="14" width="3" height="6.500"/><path class="n" stroke-width="2.200" d="M13.500 10.500L21 3M16 3h5v5"/>', "feat"),
    "s_ch_del": ('<path class="l" d="M3.500 3v17.500H21"/><rect class="a" x="6.500" y="12" width="3.500" height="8.500"/><rect class="b" x="12" y="6.500" width="3.500" height="14"/><rect class="a" x="17.500" y="14" width="3" height="6.500"/><circle class="a" cx="18" cy="6" r="4.200"/><path class="l" stroke-width="1.600" d="M16 4l4 4M20 4l-4 4"/>', "cut"),
    "s_pic_new": ('<rect class="p" x="3" y="6" width="15" height="13" rx="1"/><circle class="a" cx="7.500" cy="10.500" r="1.600"/><path class="b" d="M3.500 18.500l4.500-4.500 3 3 2.500-2.500 4.500 4z"/><circle class="a" cx="18" cy="6" r="4.200"/><path class="l" stroke-width="1.600" d="M18 3.800v4.400M15.800 6h4.400"/>', "feat"),
    "s_pic_edit": ('<rect class="p" x="3" y="6" width="15" height="13" rx="1"/><circle class="a" cx="7.500" cy="10.500" r="1.600"/><path class="b" d="M3.500 18.500l4.500-4.500 3 3 2.500-2.500 4.500 4z"/><path class="a" d="M17 2.500l3.500 3.500-6 6-4 .5.5-4z"/>', "feat"),
    "s_pic_copy": ('<path class="p" d="M4 3h9l3 3v11H4z"/><path class="p" d="M9 8h9l3 3v11H9z"/><circle class="a" cx="13" cy="14.500" r="1.100"/><path class="b" d="M10.500 20.500l3-3 2 2 1.500-1.500 2.500 2.500z"/>', "feat"),
    "s_pic_export": ('<rect class="p" x="3" y="6" width="15" height="13" rx="1"/><circle class="a" cx="7.500" cy="10.500" r="1.600"/><path class="b" d="M3.500 18.500l4.500-4.500 3 3 2.500-2.500 4.500 4z"/><path class="n" stroke-width="2.200" d="M13.500 10.500L21 3M16 3h5v5"/>', "feat"),
    "s_pic_del": ('<rect class="p" x="3" y="6" width="15" height="13" rx="1"/><circle class="a" cx="7.500" cy="10.500" r="1.600"/><path class="b" d="M3.500 18.500l4.500-4.500 3 3 2.500-2.500 4.500 4z"/><circle class="a" cx="18" cy="6" r="4.200"/><path class="l" stroke-width="1.600" d="M16 4l4 4M20 4l-4 4"/>', "cut"),
    "s_csv_in": ('<path class="p" d="M9 3h7l4 4v14H9z"/><path class="l" d="M11.500 11.500h6M11.500 14.500h6M11.500 17.500h6M14.500 10v9"/><path class="n" stroke-width="2" d="M2 12h5.500M5 9l3 3-3 3"/>', "dat"),
    "s_fx": ('<path class="l" stroke-width="2.200" d="M14.500 3.500c-3 0-4 1.500-4.500 4L8 18.500c-.5 2-1.500 2.800-3.500 3M5.500 11.500h8"/><path class="n" stroke-width="2.200" d="M14.500 12.500l6 8M20.500 12.500l-6 8"/>', "ana"),
    "s_std": ('<rect class="b" x="5" y="3" width="14" height="18" rx="1.500"/><path class="l" d="M9 3v18"/><path class="n" stroke-width="1.800" d="M12 8h4M12 11.500h4"/>', "ref"),
    "s_std_select": ('<rect class="b" x="3" y="6" width="5" height="14"/><rect class="a" x="9.500" y="3" width="5" height="17"/><rect class="b" x="16" y="7" width="5" height="13"/><path class="l" stroke-width="1.800" d="M2 21h20"/>', "ref"),
    "s_ribbon_size": ('<path class="k" fill-rule="evenodd" d="M8 3.500l6 14h-2.400l-1.100-2.700H5.500L4.400 17.500H2zM8 8.500l-1.800 4.400h3.600z"/><circle class="l" stroke-width="1.800" cx="17.500" cy="15" r="3"/><path class="l" stroke-width="1.800" d="M20.500 12v6.500"/>', "cfg"),
    "s_pick_range": ('<rect class="p" x="3" y="3" width="18" height="18"/><path class="l" d="M3 9h18M3 15h18M9 3v18M15 3v18"/><rect class="n" stroke-width="2" stroke-dasharray="3 2" x="9" y="9" width="12" height="12"/>', "feat"),
    "s_remove": ('<path class="n" stroke-width="2.600" d="M6 6l12 12M18 6L6 18"/>', "cut"),
    "s_more": ('<circle class="d" cx="5" cy="12" r="2.200"/><circle class="d" cx="12" cy="12" r="2.200"/><circle class="d" cx="19" cy="12" r="2.200"/>', "cfg"),
}
icon_kit.register(SHEETS)


def icon(key, px=24):
    return icon_kit.qicon(key, px)


def pixmap(key, px=24, ratio=2, enabled=True):
    return icon_kit.pixmap(key, px, ratio, enabled)


def decorate(button, key, px=16):
    """An icon-only button: the drawing instead of a text character (the button's tooltip says what it does)."""
    button.setText("")
    button.setIcon(icon(key, px))
    button.setIconSize(QSize(px, px))
