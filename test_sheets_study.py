"""Sheets (dev_addons/sheets): importing a finished parametric study - the table, several studies in a project, the link, Refresh from study (formulas next
to the block fill down / trim / move over), not covering other cells, stale marks, broken studies, the link surviving insert / save / load."""
import faulthandler
import json
import os
import sys
import tempfile
import time

faulthandler.dump_traceback_later(170, exit=True)
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp(prefix="opara_ud_")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "dev_addons", "sheets"), os.path.join(HERE, "shared"), HERE]
import sh_book as B
import sh_study as ST

T = tempfile.mkdtemp(prefix="opara_ss_")
S = "Sheet1"


def write_study(project, sub, n, extra_output=False, thickness0=0.05, early_at=None):
    """A study file as the parametric add-on saves it: n cases of one changed input (t) and two outputs (three with extra_output)."""
    root = os.path.join(project, "study", "studies", sub) if sub else os.path.join(project, "study")
    os.makedirs(root, exist_ok=True)
    outs = [["smax", "Max stress (psi)"], ["d", "Defl (in)"]] + ([["w", "Weight (lb)"]] if extra_output else [])
    cases = []
    for i in range(n):
        t = thickness0 + 0.01 * i
        o = {"smax": 1000.0 + 12.5 * i, "d": 0.1 * i}
        if extra_output:
            o["w"] = 5.0 + i
        c = {"label": i + 1, "values": {"t": f"{t:.12g}"}, "status": "ok", "outputs": o}
        if early_at == i:
            c["status"], c["early_exit"] = "stopped", "stress over limit"
        cases.append(c)
    j = {"format": "openpara-study", "version": 1, "checked": ["t"], "rows": [{}], "outputs": [o[0] for o in outs], "exit_conds": [], "cases": cases,
         "run_meta": {"params": [["t", "Thickness (in)"]], "outputs": outs, "unit": None}}
    with open(os.path.join(root, "study.json"), "w", encoding="utf-8") as f:
        json.dump(j, f)


def bump(project, sub=""):
    """Makes the study file look saved again (a later modified time)."""
    f = ST._file(project, sub)
    t = os.path.getmtime(f) + 5
    os.utime(f, (t, t))


# ---- the studies of a project and their table
proj = os.path.join(T, "truss")
write_study(proj, "", 4)
assert ST.studies(proj) == [{"name": "Study 1", "sub": ""}]
write_study(proj, "mesh2", 3, extra_output=True)
with open(os.path.join(proj, "study", "index.json"), "w", encoding="utf-8") as f:
    json.dump({"studies": [{"name": "Study 1", "sub": ""}, {"name": "Finer mesh", "sub": "mesh2"}, {"name": "Gone", "sub": "nothere"}]}, f)
assert ST.studies(proj) == [{"name": "Study 1", "sub": ""}, {"name": "Finer mesh", "sub": "mesh2"}]
assert ST.studies(os.path.join(T, "empty")) == []
heads, rows = ST.table(proj, "")
assert heads == ["#", "Thickness (in)", "Status", "Max stress (psi)", "Defl (in)"] and len(rows) == 4
assert rows[1] == [2.0, 0.06, "ok", 1012.5, 0.1] and all(isinstance(x, float) for x in rows[2][:2] + rows[2][3:])
h2, r2 = ST.table(proj, "mesh2")
assert h2[-1] == "Weight (lb)" and len(r2) == 3 and ST.title_of(proj, "mesh2") == "truss - Finer mesh"
write_study(proj, "early", 3, early_at=1)
assert "EARLY EXIT: stress over limit" in ST.table(proj, "early")[1][1][2]

# ---- import: a bold header row, the rows under it, the link; the next import goes under the first
wb = B.Workbook()
link, notes = ST.import_study(wb, S, proj, "")
assert link["origin"] == [1, 1] and link["rows"] == 4 and link["cols"] == 5 and link["name"] == "truss - Study 1" and wb.get_sheet(S).links == [link]
assert wb.value(S, 1, 2) == "Thickness (in)" and wb.cell(S, 1, 2).st.bold and wb.value(S, 3, 4) == 1012.5 and wb.value(S, 5, 5) == 0.30000000000000004 or abs(wb.value(S, 5, 5) - 0.3) < 1e-12
assert notes == []
l2, _n = ST.import_study(wb, S, proj, "mesh2")
assert l2["origin"] == [7, 1] and wb.value(S, 7, 6) == "Weight (lb)" and wb.value(S, 10, 6) == 7.0
assert ST.link_at(wb, S, 3, 3) is link and ST.link_at(wb, S, 9, 2) is l2 and ST.link_at(wb, S, 6, 1) is None and ST.link_at(wb, S, 1, 9) is None
empty = os.path.join(T, "noresults")
write_study(empty, "", 0)
l3, n3 = ST.import_study(wb, "Sheet1", empty, "", origin=(20, 3))
assert l3["rows"] == 0 and l3["origin"] == [20, 3] and any("no results" in x for x in n3) and wb.value(S, 20, 4) == "Thickness (in)"

# ---- formulas written next to the block fill down for new rows and are trimmed for rows that are gone
wb = B.Workbook()
link, _n = ST.import_study(wb, S, proj, "")                                      # A1:E5 (header + 4 rows)
wb.set_input(S, 1, 6, "Utilisation")
wb.set_input(S, 1, 7, "Margin")
for r in range(2, 6):
    wb.set_input(S, r, 6, f"=D{r}/$J$1")
    wb.set_input(S, r, 7, f"=1-F{r}")
wb.set_input(S, 1, 10, "5000")
assert abs(wb.value(S, 5, 6) - (1000 + 37.5) / 5000) < 1e-12
write_study(proj, "", 7)
assert not ST.is_stale(link)
bump(proj)
assert ST.is_stale(link)
done, notes = ST.refresh(wb, S, link)
assert done and link["rows"] == 7 and not ST.is_stale(link)
assert wb.cell(S, 8, 6).raw == "=D8/$J$1" and wb.cell(S, 8, 7).raw == "=1-F8" and abs(wb.value(S, 8, 6) - (1000 + 75) / 5000) < 1e-12
assert any("6 formula" in x for x in notes), notes
assert wb.value(S, 8, 4) == 1075.0 and wb.value(S, 8, 3) == "ok"
write_study(proj, "", 2)
bump(proj)
done, notes = ST.refresh(wb, S, link)
assert done and link["rows"] == 2
for r in (4, 5, 6, 7, 8):
    assert wb.cell(S, r, 6) is None or wb.cell(S, r, 6).raw is None, r             # rows that are gone take their formulas with them
    assert wb.cell(S, r, 4) is None or wb.cell(S, r, 4).raw is None, r
assert wb.cell(S, 3, 6).raw == "=D3/$J$1" and wb.value(S, 1, 10) == 5000.0         # what is not part of the table stays
wb.undo()                                                                           # one step brings the table, its formulas and the link's numbers back
assert wb.get_sheet(S).links[0]["rows"] == 7 and wb.value(S, 8, 4) == 1075.0 and wb.cell(S, 8, 6).raw == "=D8/$J$1"
wb.undo()                                                                           # the next one is the first refresh (4 -> 7 rows)
assert wb.get_sheet(S).links[0]["rows"] == 4 and wb.cell(S, 8, 6) is None and wb.value(S, 5, 4) == 1037.5
wb.redo()
wb.redo()
assert wb.get_sheet(S).links[0]["rows"] == 2 and wb.cell(S, 3, 6).raw == "=D3/$J$1"

# ---- importing is one step too: undo takes the table AND the link away
wb = B.Workbook()
write_study(proj, "", 4)
ST.import_study(wb, S, proj, "")
assert wb.get_sheet(S).links and wb.value(S, 2, 4) == 1000.0
wb.undo()
assert wb.get_sheet(S).links == [] and wb.extent(S) == (0, 0) and not wb.can_undo()
wb.redo()
assert wb.get_sheet(S).links[0]["rows"] == 4 and wb.value(S, 5, 4) == 1037.5

# ---- a table with more columns pushes the formulas next to it over, and their references follow
wb = B.Workbook()
write_study(proj, "", 4)
bump(proj)
link, _n = ST.import_study(wb, S, proj, "")
wb.set_input(S, 1, 6, "Ratio")
for r in range(2, 6):
    wb.set_input(S, r, 6, f"=D{r}/1000")
write_study(proj, "", 4, extra_output=True)
bump(proj)
done, notes = ST.refresh(wb, S, link)
assert done and link["cols"] == 6 and any("inserted" in x for x in notes), notes
assert wb.value(S, 1, 6) == "Weight (lb)" and wb.value(S, 1, 7) == "Ratio"
assert wb.cell(S, 3, 7).raw == "=D3/1000" and abs(wb.value(S, 3, 7) - 1.0125) < 1e-12 and wb.value(S, 3, 6) == 6.0
wb.undo()                                                                           # the inserted column and the new table go in ONE step
assert wb.get_sheet(S).links[0]["cols"] == 5 and wb.value(S, 1, 6) == "Ratio" and wb.cell(S, 3, 6).raw == "=D3/1000"

# ---- never quietly covers other cells: the refresh says no, and force=True does it
wb = B.Workbook()
write_study(proj, "", 2)
bump(proj)
link, _n = ST.import_study(wb, S, proj, "")
wb.set_input(S, 5, 2, "mine")
write_study(proj, "", 5)
bump(proj)
assert ST.overwrite_count(wb, S, link, 5) == 1
done, notes = ST.refresh(wb, S, link)
assert not done and "1 cell" in notes[0] and link["rows"] == 2 and wb.value(S, 5, 2) == "mine"
done, notes = ST.refresh(wb, S, link, force=True)
assert done and link["rows"] == 5 and wb.value(S, 5, 2) != "mine"

# ---- the link follows the block when rows or columns are inserted above or left of it; it survives save and load
wb = B.Workbook()
write_study(proj, "", 3)
link, _n = ST.import_study(wb, S, proj, "")
wb.insert(S, "r", 1, 2)
wb.insert(S, "c", 1, 1)
assert link["origin"] == [3, 2] and wb.value(S, 3, 3) == "Thickness (in)"
p = os.path.join(T, "w.opsheet")
wb.save(p)
w2 = B.Workbook.load(p)
l2 = w2.get_sheet(S).links[0]
assert l2["origin"] == [3, 2] and l2["project"] == proj
write_study(proj, "", 6)
bump(proj)
done, _n = ST.refresh(w2, S, l2)
assert done and w2.value(S, 9, 2) == 6.0 and w2.get_sheet(S).links[0]["rows"] == 6
ST.remove_link(w2, S, l2)
assert w2.get_sheet(S).links == [] and w2.value(S, 9, 2) == 6.0                      # forgetting the link leaves the numbers

# ---- broken or missing studies give a plain error and change nothing
wb = B.Workbook()
for bad_project, why in [(os.path.join(T, "nowhere"), "could not be read")]:
    try:
        ST.import_study(wb, S, bad_project, "")
        raise AssertionError("a missing study must raise")
    except ST.StudyError as ex:
        assert why in str(ex)
broken = os.path.join(T, "broken")
os.makedirs(os.path.join(broken, "study"))
open(os.path.join(broken, "study", "study.json"), "w").write('{"format": "something-else"}')
try:
    ST.table(broken, "")
    raise AssertionError("another kind of file must raise")
except ST.StudyError as ex:
    assert "not a parametric study" in str(ex)
open(os.path.join(broken, "study", "study.json"), "w").write("{oops")
try:
    ST.table(broken, "")
    raise AssertionError("a damaged file must raise")
except ST.StudyError:
    pass
assert wb.get_sheet(S).links == [] and wb.extent(S) == (0, 0)

print("OK test_sheets_study")
