"""The workbench project (dev add-on workbench), no window: the kinds and the names of the cells, nodes and links and what a link may be, the status of every cell
(incomplete / refresh / update / ok / failed) as things change upstream, the plan of Update Project, the .opara file (readable JSON, zipped on request, written safely,
refused when it is not a project or comes from a newer program, unknown kinds kept), files and folders stored in a node, links to big files, the report and the
checks.   python test_wb_project.py"""
import faulthandler
faulthandler.dump_traceback_later(120, exit=True)
import json
import os
import shutil
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "dev_addons", "workbench")]
import wb_project as wp

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


def raises(fn, text, part=""):
    try:
        fn()
    except wp.ProjectError as ex:
        ok(part.lower() in str(ex).lower(), f"{text}: {ex}")
        return
    ok(False, f"{text}: nothing was raised")


T = tempfile.mkdtemp(prefix="opara_wbp_")

# ----------------------------------------------------------------------------------------------------------------------------------------- kinds and names
ok(wp.EXT == ".opara" and wp.FORMAT == "openpara-project", "the file type is .opara")
ok(wp.letter_of(0) == "A" and wp.letter_of(25) == "Z" and wp.letter_of(26) == "AA" and wp.letter_of(27) == "AB" and wp.letter_of(701) == "ZZ" and wp.letter_of(702) == "AAA",
   "system letters run A..Z, AA, AB ... ZZ, AAA")
for k in ("part", "assembly", "solid", "thermal3d", "fea", "thermal", "cfd", "beam", "sheets", "pdf", "controls", "circuits", "visualize", "motor", "trainer",
          "annotator", "truss", "study"):
    ok(wp.spec_of(k) is not None, f"the kind '{k}' is registered")
ok([c.key for c in wp.spec_of("solid").cells] == ["geometry", "setup", "solution", "results"], "an analysis has Geometry, Setup, Solution, Results")
ok([c.role for c in wp.spec_of("solid").cells] == ["import", "data", "compute", "view"], "the roles of an analysis: import, data, compute, view")
ok(wp.spec_of("part").standalone == ".gpd" and wp.spec_of("assembly").standalone == ".gpa" and wp.spec_of("solid").standalone == "folder",
   "a part saves out as .gpd, an assembly as .gpa, an analysis as a project folder")
try:
    wp.CellSpec("x", "X", "bogus")
    ok(False, "a cell role that does not exist is refused")
except ValueError:
    ok(True, "a cell role that does not exist is refused")
try:
    wp.register("zzz", "Z", "No such group", [])
    ok(False, "a toolbox group that does not exist is refused")
except ValueError:
    ok(True, "a toolbox group that does not exist is refused")

# ----------------------------------------------------------------------------------------------------------------------------------------- nodes
p = wp.Project("Bracket")
a = p.add_node("part", "Bracket part")
b = p.add_node("solid", "Stress")
c = p.add_node("thermal3d")
ok([n.label for n in p.nodes.values()] == ["A", "B", "C"], "the first nodes are A, B, C")
ok(a.title == "Bracket part" and c.title == "3D Thermal", "a node has the title given, or its kind's name")
ok(b.cell_name("geometry") == "B2" and b.cell_name("setup") == "B3" and b.cell_name("results") == "B5" and a.cell_name("geometry") == "A2",
   "cells are named like ANSYS: the letter, then row 2 for the first cell (row 1 is the name of the system)")
ok(a.pos[0] < b.pos[0] < c.pos[0] and all(abs(n.pos[0] / 20 - round(n.pos[0] / 20)) < 1e-9 for n in p.nodes.values()), "new blocks go side by side, on the 20-unit grid")
p.remove_node(c.id)
d = p.add_node("part")
ok(d.label == "C", "the letter of a removed node is used again")
ok(sorted(p.nodes) == sorted(["n1", "n2", "n4"]) or len(p.nodes) == 3, "node ids are never used twice in one session")
raises(lambda: p.add_node("nonsense"), "an unknown kind cannot be added", "does not know")
raises(lambda: p.node("zz"), "an unknown node id is an error", "no node")
raises(lambda: p.remove_node("zz"), "removing an unknown node is an error", "no node")
p.rename_node(d.id, "  ")
ok(d.title == "Part", "an empty title falls back to the kind's name")
p.rename_node(d.id, "Lid")
p.move_node(d.id, 400, 80)
ok(d.title == "Lid" and d.pos == [400.0, 80.0], "renaming and moving work")
rev = p.rev
p.move_node(d.id, 400, 80)
ok(p.rev == rev, "moving a node to where it is changes nothing (not dirty)")
p.remove_node(d.id)

# ----------------------------------------------------------------------------------------------------------------------------------------- links
asm = p.add_node("assembly", "Frame")
fea = p.add_node("fea", "Plate")
ok(p.why_not_link(a.id, "geometry", b.id, "geometry") is None, "a part can feed the geometry of a 3D analysis")
ok(p.why_not_link(a.id, "geometry", fea.id, "geometry") is None, "a part can feed the sketch of a 2D analysis")
ok("takes sketch" in p.why_not_link(asm.id, "geometry", fea.id, "geometry"), "an assembly gives no sketch: the 2D analysis refuses it, naming both ends")
ok("does not take" in p.why_not_link(a.id, "geometry", a.id, "geometry") or "itself" in p.why_not_link(a.id, "geometry", a.id, "geometry"), "a node cannot feed itself")
ok("does not give" in p.why_not_link(b.id, "setup", a.id, "geometry"), "a setup cell gives nothing to another node")
ok("does not take" in p.why_not_link(a.id, "geometry", b.id, "setup"), "a setup cell takes nothing from another node")
ok("not in the project" in p.why_not_link("zz", "geometry", b.id, "geometry"), "a link needs both ends in the project")
k1 = p.link(a.id, "geometry", b.id, "geometry")
ok(p.link_type(k1) == "geometry", "a part -> 3D analysis link carries geometry")
k2 = p.link(a.id, "geometry", fea.id, "geometry")
ok(p.link_type(k2) == "sketch", "a part -> 2D analysis link carries a sketch")
ok(len(p.outgoing(a.id)) == 2 and p.incoming(b.id, "geometry") is k1, "one part can feed several analyses")
raises(lambda: p.link(asm.id, "geometry", b.id, "geometry"), "a second source for a cell is refused", "already has a source")
p.unlink(k1)
ok(p.incoming(b.id, "geometry") is None, "a link can be removed")
k1 = p.link(asm.id, "geometry", b.id, "geometry")
ok(p.link_type(k1) == "geometry", "an assembly can feed a 3D analysis")
p.remove_node(asm.id)
ok(p.incoming(b.id, "geometry") is None and len(p.links) == 1, "removing a node removes its links")
# a loop: a node that takes and gives (a test kind)
wp.register("relay", "Relay", "Geometry", [("geometry", "Relay", "import", ("geometry",), ("geometry",))])
r1, r2, r3 = p.add_node("relay"), p.add_node("relay"), p.add_node("relay")
p.link(r1.id, "geometry", r2.id, "geometry")
p.link(r2.id, "geometry", r3.id, "geometry")
ok("loop" in p.why_not_link(r3.id, "geometry", r1.id, "geometry"), "a link that would close a loop is refused")
ok(p.reaches(r1.id, r3.id) and not p.reaches(r3.id, r1.id), "reaches follows links downstream only")
ok(p.order().index(r1.id) < p.order().index(r2.id) < p.order().index(r3.id), "the order puts every source before what takes from it")
for n in (r1, r2, r3):
    p.remove_node(n.id)

# ----------------------------------------------------------------------------------------------------------------------------------------- status
p = wp.Project("Status")
A = p.add_node("part", "Part")
B = p.add_node("solid", "Stress")
p.link(A.id, "geometry", B.id, "geometry")
S = lambda n, k: p.status(n.id, k)                         # noqa: E731
ok(S(A, "geometry") == wp.INCOMPLETE, "a part with nothing in it is incomplete")
ok(S(B, "geometry") == wp.INCOMPLETE and S(B, "solution") == wp.INCOMPLETE and S(B, "results") == wp.INCOMPLETE, "an analysis whose source is not ready is incomplete all the way")
p.set_ready(A.id, "geometry")
ok(S(A, "geometry") == wp.OK, "a part that is ready is up to date")
ok(S(B, "geometry") == wp.REFRESH, "the geometry of the analysis says refresh: the part is ready but was never taken")
ok(S(B, "setup") == wp.INCOMPLETE and S(B, "solution") == wp.INCOMPLETE, "setup not made yet: solution incomplete")
p.set_ready(B.id, "setup")
ok(S(B, "setup") == wp.OK and S(B, "solution") == wp.UPDATE, "setup made: the solution needs an update (the geometry still to refresh)")
steps = p.plan_update()
ok([(s["action"], s["name"]) for s in steps] == [("refresh", "B2"), ("update", "B4")], f"Update Project: refresh B2, then update B4 ({steps})")
rev = p.rev
p.plan_update()
ok(p.rev == rev and S(B, "geometry") == wp.REFRESH, "working out the plan changes nothing")
p.mark_refreshed(B.id, "geometry")
ok(S(B, "geometry") == wp.OK and S(B, "solution") == wp.UPDATE, "refreshed: the geometry is ok, the solution still needs its update")
ok(S(B, "results") == wp.INCOMPLETE, "the results are not there before the solution is up to date")
p.mark_updated(B.id, "solution")
ok(S(B, "solution") == wp.OK and S(B, "results") == wp.OK, "updated: solution and results are up to date")
ok(p.plan_update() == [], "nothing to do now")
# something upstream changes
p.touch(A.id, "geometry")
ok(S(B, "geometry") == wp.REFRESH and S(B, "solution") == wp.UPDATE and S(B, "setup") == wp.OK, "the part changed: geometry refresh, solution update, setup untouched")
ok(S(B, "results") == wp.INCOMPLETE, "results wait for the solution")
ok([s["name"] for s in p.plan_update()] == ["B2", "B4"], "the plan is again refresh B2, update B4")
p.mark_refreshed(B.id, "geometry")
p.mark_updated(B.id, "solution")
ok(all(v == wp.OK for v in p.statuses(B.id).values()), "after both steps everything is up to date")
# the setup changes
p.touch(B.id, "setup")
ok(S(B, "geometry") == wp.OK and S(B, "solution") == wp.UPDATE, "the setup changed: only the solution needs an update")
p.mark_updated(B.id, "solution")
# a failure
p.touch(B.id, "setup")
p.mark_failed(B.id, "solution", "The mesh could not be made.")
ok(S(B, "solution") == wp.FAILED and S(B, "results") == wp.FAILED, "a failed update shows as failed, and so do the results after it")
ok("mesh could not" in "\n".join(p.report_lines()), "the report says why it failed")
p.touch(B.id, "setup")
ok(S(B, "solution") == wp.UPDATE, "a change of the setup clears the failure: update again")
p.mark_failed(B.id, "solution", "")
ok(S(B, "solution") == wp.FAILED, "a failure without a text still shows")
p.mark_updated(B.id, "solution")
ok(S(B, "solution") == wp.OK, "an update that works clears the failure")
# an analysis with no link: the geometry is imported inside its editor
C = p.add_node("thermal3d", "Heat")
ok(S(C, "geometry") == wp.INCOMPLETE, "an analysis with no link and no geometry is incomplete")
p.set_ready(C.id, "geometry")
ok(S(C, "geometry") == wp.OK, "geometry imported by hand in the analysis: ok (no link to refresh)")
p.set_ready(C.id, "setup")
ok(S(C, "solution") == wp.UPDATE and [s["name"] for s in p.plan_update(only={C.id})] == ["C4"], "it only needs its solution")
# one source for two analyses; the part changes: both ask for a refresh
D = p.add_node("thermal3d", "Heat 2")
p.link(A.id, "geometry", D.id, "geometry")
p.set_ready(D.id, "setup")
p.mark_refreshed(D.id, "geometry")
p.mark_updated(D.id, "solution")
p.touch(A.id, "geometry")
ok(S(B, "geometry") == wp.REFRESH and S(D, "geometry") == wp.REFRESH, "one part feeds two analyses: both must refresh when it changes")
only = [s["node"] for s in p.plan_update(only={D.id})]
ok(set(only) == {D.id}, "the plan can be limited to some nodes")
# the node status (worst cell)
ok(p.node_status(D.id) == wp.REFRESH, "the node's own summary is what it needs next: refresh")
p.remove_node(C.id)
# a part that stops being ready makes the analysis incomplete again
p.set_ready(A.id, "geometry", False)
ok(S(B, "geometry") == wp.INCOMPLETE and S(B, "solution") == wp.INCOMPLETE, "a source that is not ready makes what takes from it incomplete")
p.set_ready(A.id, "geometry")
# a source that failed
p.cell(A.id, "geometry")["failed"] = "x"
ok(S(A, "geometry") == wp.OK, "a data cell has no 'failed' (only cells that compute or import do)")
p.cell(A.id, "geometry")["failed"] = ""
# the blocked list
q = wp.Project()
q.add_node("solid")
bl = q.blocked()
ok(len(bl) == 3 and bl[0][0] == "A2" and "no source" in bl[0][1], f"blocked(): says what is missing and where ({bl})")
# unknown kind
p2 = wp.Project()
p2.add_node("part")
ok(p2.statuses("n1") != {}, "statuses of a node")

# ----------------------------------------------------------------------------------------------------------------------------------------- the file
p = wp.Project("Plate with a hole")
A = p.add_node("part", "Plate", data={"doc": {"features": [1, 2, 3], "text": "ä ö ü"}})
B = p.add_node("solid", "Stress", data={"folder": {"simulation.json": {"text": "{\"a\": 1}\r\n"}}})
p.link(A.id, "geometry", B.id, "geometry")
p.set_ready(A.id, "geometry")
p.set_ready(B.id, "setup")
p.mark_refreshed(B.id, "geometry")
p.mark_updated(B.id, "solution")
A.notes = "the first part"
p.view = {"x": 12.5, "y": -3.0, "zoom": 1.5}
f = os.path.join(T, "plate")
path = p.write(f)
ok(path.endswith(".opara") and os.path.isfile(path) and p.path == path, "writing adds .opara to the name and notes the path")
ok(not p.is_dirty(), "saved: not dirty")
p.touch(A.id, "geometry")
ok(p.is_dirty(), "a change makes it dirty")
p.write()
ok(not p.is_dirty(), "saved again: not dirty")
txt = open(path, encoding="utf-8").read()
d = json.loads(txt)
ok(d["format"] == "openpara-project" and d["version"] == 1 and d["name"] == "Plate with a hole" and len(d["nodes"]) == 2 and len(d["links"]) == 1, "the file is plain JSON with the format, the version, the nodes and the links")
ok("\n" in txt and txt.startswith("{\n"), "the file is indented text you can read")
ok(d["nodes"][0]["data"]["doc"]["text"] == "ä ö ü" and "ä ö ü" in txt, "non-ASCII text is written as it is (UTF-8), not escaped")
ok(d["saved_with"] != "" and "T" in d["saved"], "the file says which program saved it and when")
p3 = wp.Project.read(path)
ok(p3.name == "Plate with a hole" and list(p3.nodes) == [A.id, B.id] and len(p3.links) == 1 and p3.path == path and not p3.is_dirty(), "reading gives the project back, not dirty")
n3 = p3.nodes[A.id]
ok(n3.title == "Plate" and n3.label == "A" and n3.pos == A.pos and n3.notes == "the first part" and n3.data["doc"]["features"] == [1, 2, 3], "title, letter, place, notes and data come back")
ok(p3.nodes[B.id].data["folder"]["simulation.json"]["text"] == "{\"a\": 1}\r\n", "text with CR LF comes back exactly")
ok(p3.view == {"x": 12.5, "y": -3.0, "zoom": 1.5}, "the place of the view comes back")
# the part was touched after B took it (stamp 1 vs seen 0): after the reload B.geometry must still ask for a refresh
ok(p3.status(B.id, "geometry") == wp.REFRESH, "the refresh that was pending when it was saved is still pending")
ok(p3.status(B.id, "solution") == wp.UPDATE and p3.status(B.id, "results") == wp.INCOMPLETE, "results are not saved: the solution says update after opening")
p.mark_refreshed(B.id, "geometry")
p.mark_updated(B.id, "solution")
p.write()
p4 = wp.Project.read(path)
ok(p4.status(B.id, "geometry") == wp.OK and p4.status(B.id, "solution") == wp.UPDATE, "even when it was all up to date: opening says update for the solution, ok for the geometry it already took")
ok([s["action"] for s in p4.plan_update()] == ["update"], "Update Project after opening has one step: update (nothing is recomputed on its own)")
ok(p4.counter >= 2, "the id counter is kept")
n5 = p4.add_node("part")
ok(n5.id not in (A.id, B.id), "a node added after opening gets a new id")
# zipped
zp = p.write(os.path.join(T, "zipped.opara"), zipped=True)
ok(open(zp, "rb").read(2) == b"PK" and zipfile.is_zipfile(zp), "a zipped project is a zip")
pz = wp.Project.read(zp)
ok(pz.name == p.name and list(pz.nodes) == list(p.nodes), "a zipped project reads like the plain one")
p.write(path)                                              # the plain form again
# writing is safe
good = open(path, "rb").read()
import wb_project as wbp
real_replace = os.replace


def bad_replace(*a, **k):
    raise OSError("disk full (test)")


wbp.os.replace = bad_replace
try:
    p.write(path)
    ok(False, "a failing replace raises")
except OSError:
    ok(True, "a failing write raises")
finally:
    wbp.os.replace = real_replace
ok(open(path, "rb").read() == good, "the old file is whole after a failed save")
ok(not [x for x in os.listdir(T) if x.endswith(".tmp")], "no temporary file is left behind")
raises(lambda: wp.Project("x").write(), "saving without a name is an error", "no file name")
# refusals
bad = os.path.join(T, "bad.opara")
open(bad, "w").write("this is not json")
raises(lambda: wp.Project.read(bad), "text that is not JSON", "not readable")
open(bad, "w").write("[1, 2]")
raises(lambda: wp.Project.read(bad), "JSON that is not a project", "not an openpara project")
open(bad, "w").write(json.dumps({"format": "something-else", "version": 1}))
raises(lambda: wp.Project.read(bad), "another format", "not an openpara project")
open(bad, "w").write(json.dumps({"format": wp.FORMAT, "version": 99, "nodes": []}))
raises(lambda: wp.Project.read(bad), "a newer version", "newer")
open(bad, "w").write(json.dumps({"format": wp.FORMAT, "version": "x", "nodes": []}))
raises(lambda: wp.Project.read(bad), "a version that is not a number", "version")
open(bad, "w").write(json.dumps({"format": wp.FORMAT, "version": 1, "nodes": [{"id": "n1"}]}))
raises(lambda: wp.Project.read(bad), "a node without a kind", "without an id or a kind")
open(bad, "w").write(json.dumps({"format": wp.FORMAT, "version": 1, "nodes": [{"id": "n1", "kind": "part"}, {"id": "n1", "kind": "part"}]}))
raises(lambda: wp.Project.read(bad), "the same node id twice", "twice")
open(bad, "w").write(json.dumps({"format": wp.FORMAT, "version": 1, "nodes": [], "links": [{"from": "x"}]}))
raises(lambda: wp.Project.read(bad), "a link that is not complete", "not complete")
open(bad, "wb").write(b"\xff\xfe\x00bad")
raises(lambda: wp.Project.read(bad), "bytes that are not text", "not text")
open(bad, "wb").write(b"PK\x03\x04junk")
raises(lambda: wp.Project.read(bad), "a broken zip", "zipped")
raises(lambda: wp.Project.read(os.path.join(T, "missing.opara")), "a file that is not there", "cannot be read")
# an older/other program's extras and unknown kinds survive
j = {"format": wp.FORMAT, "version": 1, "name": "Future", "future_key": {"a": [1, 2]}, "counter": 5,
     "nodes": [{"id": "n1", "kind": "part", "title": "P", "label": "A", "pos": [20, 20], "cells": {"geometry": {"stamp": 3, "seen": {}, "ready": True, "failed": ""}}, "data": {}},
               {"id": "n2", "kind": "hologram", "title": "H", "label": "B", "pos": [300, 20], "weird": [1, 2, 3], "data": {"x": 1}}],
     "links": []}
fp = os.path.join(T, "future.opara")
open(fp, "w").write(json.dumps(j))
pf = wp.Project.read(fp)
ok(pf.nodes["n2"].spec is None and pf.nodes["n1"].cells["geometry"]["stamp"] == 3, "a node of an unknown kind loads (and a known one keeps its stamp)")
ok(pf.status("n2", "x") == wp.INCOMPLETE and pf.statuses("n2") == {}, "an unknown node has no cells to show")
ok(any("hologram" in x for x in pf.check()), "the check names the unknown kind")
pf.write(fp)
back = json.load(open(fp))
ok(back["future_key"] == {"a": [1, 2]} and back["nodes"][1] == j["nodes"][1], "unknown top-level keys and unknown nodes are written back exactly as they were")
ok(wp.Project.read(fp).plan_update() == [], "an unknown node is skipped by Update Project")
ok(any("hologram" in w for _n, w in pf.blocked()), "and listed as something that cannot be done")

# ----------------------------------------------------------------------------------------------------------------------------------------- checks and the report
bp = wp.Project()
x = bp.add_node("part")
y = bp.add_node("solid")
bp.links.append(wp.Link(x.id, "geometry", "gone", "geometry"))
ok(any("not in the project" in s for s in bp.check()), "a link to a node that is gone is found")
bp.links = [wp.Link(x.id, "geometry", y.id, "setup")]
ok(any("carries nothing" in s or "does not exist" in s for s in bp.check()), "a link between cells that carry nothing is found")
bp.links = [wp.Link(x.id, "geometry", y.id, "geometry"), wp.Link(x.id, "geometry", y.id, "geometry")]
ok(any("more than one source" in s for s in bp.check()), "two sources for one cell are found")
y.label = "A"
ok(any("letter A" in s for s in bp.check()), "a letter used twice is found")
bp.links = []
ok(bp.check() != [], "problems stay listed")
good = wp.Project()
g1 = good.add_node("part")
g2 = good.add_node("solid")
good.link(g1.id, "geometry", g2.id, "geometry")
ok(good.check() == [], "a good project has no problems")
rep = "\n".join(good.report_lines())
ok("Project 'Project'" in rep and "A2 Part: incomplete" in rep and "link A2 (Part) -> B2" in rep and "Not stored in the file: results" in rep, "the report lists the nodes, the cells, the links and what is not stored")
ok("cannot yet: B3" in rep, "the report says what cannot be done yet and why")
good.set_ready(g1.id, "geometry")
good.set_ready(g2.id, "setup")
rep = "\n".join(good.report_lines())
ok("Update Project would do 2 steps: refresh B2, update B4" in rep, "the report says what Update Project would do")

# ----------------------------------------------------------------------------------------------------------------------------------------- files and folders in a node
src = os.path.join(T, "src")
os.makedirs(os.path.join(src, "sub"))
open(os.path.join(src, "a.txt"), "wb").write(b"line1\r\nline2\r\n \xc3\xa4")
open(os.path.join(src, "sub", "b.bin"), "wb").write(bytes(range(256)))
open(os.path.join(src, "result.npz"), "wb").write(b"big result")
packed = wp.pack_folder(src, skip=lambda rel: rel.endswith(".npz"))
ok(sorted(packed) == ["a.txt", "sub/b.bin"], "pack_folder keeps relative paths with '/' and leaves out what skip says")
ok("text" in packed["a.txt"] and "b64" in packed["sub/b.bin"], "text goes in as text (readable), binary as base64")
dest = wp.unpack_folder(packed, os.path.join(T, "out"))
ok(open(os.path.join(dest, "a.txt"), "rb").read() == b"line1\r\nline2\r\n \xc3\xa4", "text comes back byte for byte (CR LF kept)")
ok(open(os.path.join(dest, "sub", "b.bin"), "rb").read() == bytes(range(256)), "binary comes back byte for byte")
for evil in ("../x.txt", "/abs.txt", "a/../../x", "C:/x.txt", "a//b", "./a", ""):
    raises(lambda e=evil: wp.unpack_folder({e: {"text": "x"}}, os.path.join(T, "evil")), f"a stored path '{evil}' is refused", "not allowed")
ok(not os.path.exists(os.path.join(T, "x.txt")) and not os.path.exists("/abs.txt"), "nothing was written outside the folder")
fb = wp.pack_file(os.path.join(src, "a.txt"))
ok(fb["name"] == "a.txt" and "text" in fb, "pack_file keeps the name")
one = wp.unpack_file(fb, os.path.join(T, "one"))
ok(os.path.basename(one) == "a.txt" and open(one, "rb").read().startswith(b"line1"), "unpack_file writes it back")
ok(os.path.basename(wp.unpack_file({"text": "x", "name": "../up.txt"}, os.path.join(T, "one"))) == "up.txt" and not os.path.exists(os.path.join(T, "up.txt")),
   "a stored name with '..' is cut to its last part")
raises(lambda: wp.unpack_file({"text": "x", "name": ".."}, os.path.join(T, "one")), "a name that is only '..' is refused", "not a usable")
raises(lambda: wp.unpack_bytes({}), "a stored file with no content", "neither")
ok(wp.payload_bytes({"a": "x" * 1000}) > 1000 and wp.size_text(500) == "500 bytes" and wp.size_text(3 << 20) == "3.0 MB" and wp.size_text(2048) == "2.0 KB", "sizes are shown in plain units")

# links to big files
big = os.path.join(T, "data", "big.csv")
os.makedirs(os.path.dirname(big))
open(big, "w").write("1,2,3")
pj = os.path.join(T, "proj", "p.opara")
lk = wp.rel_link(big, pj)
ok(lk["rel"] == "../data/big.csv" and lk["abs"] == big, "a link to a big file is relative to the project file (and keeps the full path as a hint)")
ok(wp.resolve_link(lk, pj) == os.path.normpath(big), "the link finds the file")
moved = os.path.join(T, "copy")
shutil.copytree(os.path.join(T, "data"), os.path.join(moved, "data"))
os.makedirs(os.path.join(moved, "proj"))
shutil.rmtree(os.path.join(T, "data"))
ok(wp.resolve_link(lk, os.path.join(moved, "proj", "p.opara")) == os.path.normpath(os.path.join(moved, "data", "big.csv")), "when the folders are moved together the relative link still finds the file")
ok(wp.resolve_link(lk, pj) is None, "a file that is not there is None, not an error")
ok(wp.resolve_link({"rel": "nope.csv"}, pj) is None and wp.resolve_link({}, None) is None, "an empty link is None")

shutil.rmtree(T, ignore_errors=True)
print()
print("FAILURES:" if FAILS else "all passed", len(FAILS) if FAILS else "")
for f in FAILS:
    print("  -", f)
sys.exit(1 if FAILS else 0)
