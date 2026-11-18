"""Sheets (dev_addons/sheets): engineering standards as cell formulas - AISI S100-16 connections (screws J4, bolts J3, welds J2): hand-calculated values, the
Ω/φ methods, warnings, argument checks, the registry (tree, search, hooks), a standard offered by another add-on.  Equations and section numbers only."""
import faulthandler
import os
import sys
import tempfile

faulthandler.dump_traceback_later(170, exit=True)
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp(prefix="opara_ud_")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "dev_addons", "sheets"), os.path.join(HERE, "shared"), HERE]
import ext
import sh_book as B
import sh_engine as E
import sh_std as S
import std_aisi16

std_aisi16.register()
wb = B.Workbook()
P = "AISI16."


def call(text):
    w = []
    return wb.evaluate("=" + text, warnings=w), w


def close(a, b, tol=1e-9):
    return isinstance(a, float) and abs(a - b) <= tol * max(1.0, abs(b))


# ---- hand calculations (inch, psi, lbf)
v, w = call(P + "J4_4_1(0.0747,0.1875,58000)")                              # Pnot = 0.85 tc d Fu2  (the 690.5 lbf of the Mare Motel workbook)
assert close(v, 0.85 * 0.0747 * 0.1875 * 58000) and close(v, 690.508125) and not w
assert close(call(P + 'J4_4_1(0.0747,0.1875,58000,"nominal")')[0], 690.508125)
assert close(call(P + 'J4_4_1(0.0747,0.1875,58000,"ASD")')[0], 690.508125 / 3.0)             # Ω = 3.0
assert close(call(P + 'J4_4_1(0.0747,0.1875,58000,"LRFD")')[0], 0.50 * 690.508125)            # φ = 0.50
assert close(call(P + 'J4_4_1(0.0747,0.1875,58000,"LSD")')[0], 0.40 * 690.508125)             # φ = 0.40
assert close(call(P + "J4_4_2(0.058,0.4,70000)")[0], 1.5 * 0.058 * 0.4 * 70000)             # Pnov = 1.5 t1 dh Fu1
assert close(call(P + "J4_1(0.19)")[0], 3 * 0.19) and close(call(P + "J4_2(0.19)")[0], 1.5 * 0.19)
assert close(call(P + "J3_1(0.5)")[0], 3 * 0.5) and close(call(P + "J3_2(0.5)")[0], 1.5 * 0.5)
assert close(call(P + "J3_4_1(0.196,54000)")[0], 0.196 * 54000)                             # Pn = Ab Fn
assert close(call(P + "J3_4_2(90000,54000,10000)")[0], 83666.66666666666)                   # F'nt = 1.3 Fnt - (Fnt/(phi Fnv)) fv, capped at Fnt (hand-worked)
assert close(call(P + "J2_1_1(6,0.075,50000)")[0], 6 * 0.075 * 50000)                       # Pn = L te Fy
assert close(call(P + "J2_1_2(6,0.075,50000,70000)")[0], min(0.6 * 70000 * 6 * 0.075, 6 * 0.075 * 50000 / 3 ** 0.5))
assert close(call(P + "J4_3_1(0.0345,0.0747,0.19,45000,58000)")[0], 2.7 * 0.0345 * 0.19 * 45000)    # bearing on the thinner sheet governs
# interaction checks: ratio at or under 1 passes (ASD is the default method for checks)
t, d, dw, fu = 0.036, 0.216, 0.5, 55000
pnv, pnov = 2.7 * t * d * fu, 1.5 * t * dw * fu
assert close(call(P + "J4_5_1(150,80,0.036,0.216,0.5,55000)")[0], (150 / pnv + 0.71 * 80 / pnov) / (1.10 / 2.35))
assert close(call(P + "J4_5_1(150,80,0.036,0.216,0.5,55000)")[0], 0.3592273653104181, 1e-12)
assert close(call(P + "J4_5_3(150,80,3313,2200)")[0], (150 / 3313 + 80 / 2200) / (1.3 / 3.0))
assert call(P + "J4_5_1(300,80,0.036,0.216,0.5,55000)")[0] > call(P + "J4_5_1(150,80,0.036,0.216,0.5,55000)")[0]       # more load, higher ratio

# ---- the worked examples of the Standards window equal the hand-worked numbers and every function has one
anchors = {"J4_4_1": 690.508125, "J4_4_2": 2436.0, "J4_5_1": 0.3592273653104181, "J2_2_2_1": 5080.8725, "J3_4_1": 10584.0, "J4_3_1": 796.4325}
funcs = S.all_funcs()
assert len(funcs) == 27, len(funcs)
for f in funcs:
    assert f.example is not None and f.example["result"] is not None and not isinstance(f.example["result"], E.Err), f.full_name
    assert isinstance(f.example["result"], float) and f.example["result"] > 0, (f.full_name, f.example)
    if f.name in anchors:
        assert close(f.example["result"], anchors[f.name], 1e-9), (f.name, f.example["result"])
    text = f.formula_text(f.example["values"])
    assert text.startswith("=" + f.full_name + "(")
    assert f.title and f.brief and f.formula and f.section and all(a.name and a.meaning for a in f.args), f.full_name
    # the example, typed into a cell as a formula, gives the same number
    vals = [x for x in f.example["values"]]
    while vals and vals[-1] is None:
        vals.pop()
    args = ",".join('""' if x is None else (f'"{x}"' if isinstance(x, str) else repr(x)) for x in vals)
    assert close(call(f"{f.full_name}({args})")[0], f.example["result"], 1e-9), f.full_name

# ---- warnings (a limit of the section is passed) are notes on the cell, not errors
v, w = call(P + "J4_4_2(0.058,0.2,70000)")
assert close(v, 1.5 * 0.058 * 0.2 * 70000) and w and "5/16" in w[0], (v, w)
assert call(P + "J4_4_2(0.058,0.4,70000)")[1] == []

# ---- argument errors say which argument and why
for text, want, part in [(P + "J4_4_1(0.0747,0.1875)", "#VALUE!", None), (P + 'J4_4_1(0.0747,0.1875,"")', "#VALUE!", "Fu2"),
                         (P + "J4_4_1(-1,0.1875,58000)", "#NUM!", "above 0"), (P + 'J4_4_1("a",0.1875,58000)', "#VALUE!", "not a number"),
                         (P + 'J4_4_1(0.0747,0.1875,58000,"foo")', "#VALUE!", "method"), (P + 'J2_6(0.0747,2,58000,"flare")', "#VALUE!", "bevel")]:
    v, w = call(text)
    assert str(v) == want, (text, v)
    if part:
        assert any(part in x for x in w), (text, w)
assert str(call(P + "J4_1(1,2,3)")[0]) == "#VALUE!"                                         # too many arguments

# ---- as cell formulas: cell references, ranges of cells, names, other sheets, copied down
wb2 = B.Workbook()
for i, d in enumerate([0.1, 0.1875, 0.25], 1):
    wb2.set_input("Sheet1", i, 1, str(d))
    wb2.set_input("Sheet1", i, 2, f"=AISI16.J4_4_1($E$1,A{i},$E$2)")
wb2.set_input("Sheet1", 1, 5, "0.0747")
wb2.set_input("Sheet1", 2, 5, "58000")
assert close(wb2.value("Sheet1", 2, 2), 690.508125)
assert not wb2.set_name("Fu2", "=Sheet1!$E$2", sheet="Sheet1")                             # Fu2 is a cell address (column FU), so it cannot be a name
assert wb2.set_name("BaseFu", "=Sheet1!$E$2", sheet="Sheet1")
wb2.set_input("Sheet1", 4, 2, "=AISI16.J4_4_1(E1,A2,BaseFu)")
assert close(wb2.value("Sheet1", 4, 2), 690.508125)
wb2.set_input("Sheet1", 1, 5, "0.1")                                                        # change an input: every result follows
assert close(wb2.value("Sheet1", 2, 2), 0.85 * 0.1 * 0.1875 * 58000)
wb2.copy_cells("Sheet1", (1, 2, 1, 2), "Sheet1", 5, 2)
assert wb2.cell("Sheet1", 5, 2).raw == "=AISI16.J4_4_1($E$1,A5,$E$2)"
j = wb2.to_json()
assert close(B.Workbook.from_json(j).value("Sheet1", 2, 2), wb2.value("Sheet1", 2, 2))      # the formula survives save and load

# ---- the registry: tree, search, signature help, completion
p = S.pack("aisi-s100-16")
assert (p.prefix, p.short, p.edition, p.publisher, p.root) == ("AISI16", "AISI S100-16", "2016 edition", "AISI", "Connections")
tree = p.tree()
assert list(tree) == ["Connections"] and list(tree["Connections"]) == ["Screws", "Bolts", "Welds"]
assert len(tree["Connections"]["Screws"]) == 10 and len(tree["Connections"]["Bolts"]) == 7
assert sum(len(v) if isinstance(v, list) else sum(len(x) for x in v.values()) for v in [tree["Connections"]["Welds"]]) == 10
assert [f.full_name for f in S.search("pull-out")] == ["AISI16.J4_4_1", "AISI16.J4_5_2"]
assert {f.name for f in S.search("weld")} >= {"J2_1_1", "J2_2_2_1", "J2_5", "J2_7"} and len(S.search("J4.4")) == 3
assert S.search("zzzzzz") == [] and len(S.search("")) == 27
import sh_edit
name, names, idx, hint = sh_edit.signature("=AISI16.J4_4_1(0.0747,", 22)
assert name == "AISI16.J4_4_1" and names[:3] == ["tc", "d", "Fu2"] and idx == 1 and "diameter" in hint.lower()
assert "AISI16.J4_4_1" in sh_edit.matches("AISI16.J4_4") and sh_edit.matches("") == []

# ---- another add-on can offer a standard through the hook
calls = []
pack = S.Pack("demo-std", "DEMO", "Demo 1", "A demo standard", "1st edition", "Nobody", [
    S.StdFunc("D1", "1.1", "Double", "Twice the number", "y = 2x", [S.Arg("x", "The number", "in", example=3.0)], lambda a: a.x * 2, ["Maths", "Basics"], eq="1-1")])
ext.add_hook("sheets_standard", lambda: (calls.append(1), pack)[1])
S.load_hooks()
assert "demo-std" in S.PACKS and calls and close(call("DEMO.D1(4)")[0], 8.0) and S.func("DEMO.D1").example["result"] == 6.0
S.load_hooks()
assert len(S.packs()) == 2                                                                  # loading twice adds nothing twice

print("OK test_sheets_std")
