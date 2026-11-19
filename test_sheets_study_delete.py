"""Sheets (dev_addons/sheets): taking an imported study off the sheet - Delete study (cells go, or the numbers stay as plain cells), Select study, and
Refresh from study following the cursor so it cannot silently refill a cleared area."""
import faulthandler
import json
import os
import sys
import tempfile

faulthandler.dump_traceback_later(170, exit=True)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp(prefix="opara_ud_")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "dev_addons", "sheets"), os.path.join(HERE, "shared"), HERE]
from PyQt6.QtWidgets import QApplication, QInputDialog, QMessageBox

app = QApplication([])
import sh_study as ST
import sh_tab as TAB

T = tempfile.mkdtemp(prefix="opara_sd_")
YES, NO = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No
ans = {"question": YES, "item": None, "delete": "cells"}
asked = []
QMessageBox.question = staticmethod(lambda *a, **k: (asked.append(a[2]), ans["question"])[1])
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
QInputDialog.getItem = staticmethod(lambda parent, title, label, items, *a, **k: (items[ans["item"]], True))


def write_study(project, n):
    root = os.path.join(project, "study")
    os.makedirs(root, exist_ok=True)
    outs = [["smax", "Max stress (psi)"], ["d", "Defl (in)"]]
    cases = [{"label": i + 1, "values": {"t": f"{0.05 + 0.01 * i:.12g}"}, "status": "ok", "outputs": {"smax": 1000.0 + 12.5 * i, "d": 0.1 * i}} for i in range(n)]
    json.dump({"format": "openpara-study", "version": 1, "checked": ["t"], "rows": [{}], "outputs": [o[0] for o in outs], "exit_conds": [], "cases": cases,
               "run_meta": {"params": [["t", "Thickness (in)"]], "outputs": outs, "unit": None}}, open(os.path.join(root, "study.json"), "w"))


def fresh():
    t = TAB.make_tab()
    t.resize(1100, 720)
    t._ask_study_delete = lambda ln: ans["delete"]
    return t


p1, p2 = os.path.join(T, "a"), os.path.join(T, "b")
write_study(p1, 4)
write_study(p2, 3)
t = fresh()
g = t.grid
assert not t.act["study_delete"].isEnabled() and not t.act["study_select"].isEnabled()
t.study_import((p1, "", True))
sh = g.sheet
s = g.sheet_obj()
ln = s.links[0]
assert ST.block_rect(ln) == (1, 1, 5, 5) and t.act["study_delete"].isEnabled() and t.act["study_select"].isEnabled()
t.wb.set_input(sh, 1, 6, "Ratio")
for r in range(2, 6):
    t.wb.set_input(sh, r, 6, f"=D{r}/5000")

# ---- select study: the whole block, from any cell of it
g.select(3, 3)
assert t.study_select() is ln and g.sel() == (1, 1, 5, 5)

# ---- delete, keeping the numbers: the link goes, the cells stay, Refresh no longer applies
g.select(3, 3)
ans["delete"] = "keep"
assert t.study_delete() is ln and s.links == [] and t.wb.value(sh, 3, 2) == 0.06 and t.wb.value(sh, 1, 2) == "Thickness (in)"
assert not t.act["study_refresh"].isEnabled() and t.study_refresh() is None and "no imported study" in t.status.text()
t.act["undo"].click()                                                                   # one undo step brings the link back
s = g.sheet_obj()
assert len(s.links) == 1 and s.links[0]["rows"] == 4

# ---- delete with the cells: the block is cleared, formulas beside it stay, undo restores everything
ans["delete"] = None
assert t.study_delete() is None and len(s.links) == 1 and t.wb.value(sh, 3, 2) == 0.06   # cancel changes nothing
ans["delete"] = "cells"
g.select(2, 2)
t.study_delete()
assert s.links == [] and t.wb.cell(sh, 3, 2) is None and t.wb.cell(sh, 1, 1) is None and t.wb.cell(sh, 3, 6).raw == "=D3/5000"
write_study(p1, 6)
os.utime(os.path.join(p1, "study", "study.json"), (os.path.getmtime(os.path.join(p1, "study", "study.json")) + 9,) * 2)
t.study_refresh()                                                                       # nothing to refill
assert t.wb.cell(sh, 3, 2) is None
t.act["undo"].click()
s = g.sheet_obj()
assert len(s.links) == 1 and t.wb.value(sh, 3, 2) == 0.06 and t.wb.value(sh, 1, 2) == "Thickness (in)"

# ---- refresh follows the cursor
asked.clear()
g.select(3, 3)
assert t.study_refresh() is not None and asked == []                                    # on the study: straight away
g.select(1, 7)
asked.clear()
assert t.study_refresh() is not None and asked == []                                    # next to it (the formula column): straight away
g.select(30, 30)
asked.clear()
ans["question"] = NO
assert t.study_refresh() is None and len(asked) == 1 and "Study 1" in asked[0] and "A1" in asked[0]   # far away: asks, and a No refreshes nothing
ans["question"] = YES
assert t.study_refresh() is not None

# ---- several studies: the one under the cursor, else a choice
t.study_import((p2, "", False))
s2 = g.sheet_obj()
assert len(s2.links) == 2 or g.sheet != sh
if len(s2.links) == 2:
    l1, l2 = s2.links
else:                                                                                   # imported onto a sheet of its own: put a second one here
    g.sheet = sh
    s = g.sheet_obj()
    ST.import_study(t.wb, sh, p2, "", origin=(20, 1))
    l1, l2 = s.links
    s2 = s
o2 = l2["origin"]
g.select(o2[0] + 1, o2[1] + 1)
assert t.study_at_cursor("t", "x") is l2
g.select(2, 2)
assert t.study_at_cursor("t", "x") is l1
g.select(40, 40)
ans["item"] = 1
assert t.study_at_cursor("t", "x") is l2
g.select(40, 40)
ans["delete"] = "cells"
ans["item"] = 0
t.study_delete()
assert s2.links == [l2] and t.wb.cell(g.sheet, o2[0] + 1, o2[1]) is not None and t.wb.cell(g.sheet, 2, 2) is None                        # only the chosen study went
print("ok")
