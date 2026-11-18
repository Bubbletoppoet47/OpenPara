"""Sheets (dev_addons/sheets): the formula engine - operators, precedence, text, lookup, statistics, arrays, errors, parsing, reference shifting."""
import faulthandler
import os
import sys
import tempfile

faulthandler.dump_traceback_later(170, exit=True)
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp(prefix="opara_ud_")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "dev_addons", "sheets"), os.path.join(HERE, "shared"), HERE]
import sh_book as B
import sh_engine as E

wb = B.Workbook()
bad = []


def same(a, b):
    if isinstance(b, float) and isinstance(a, float):
        return abs(a - b) <= 1e-9 * max(1.0, abs(b))
    return a == b and type(a) == type(b)


def check(formula, want):
    got = wb.evaluate(formula)
    if isinstance(want, str) and want.startswith("#"):
        ok = str(got) == want
    else:
        ok = same(got, want)
    if not ok:
        bad.append(f"{formula}: got {got!r}, want {want!r}")


# ---- operators and precedence (Excel's own rules: unary minus binds tighter than ^)
for f, w in [("=1+2*3", 7.0), ("=(1+2)*3", 9.0), ("=-2^2", 4.0), ("=2^3^2", 64.0), ("=10%", 0.1), ("=200*5%", 10.0), ("=2*-3", -6.0), ("=7/2", 3.5),
             ('="a"&1', "a1"), ('="a"&"b"&"c"', "abc"), ("=1<2", True), ("=2<=1", False), ('="a"="A"', True), ("=1<>2", True), ("=1E3+1", 1001.0),
             ('="5"+1', 6.0), ("=TRUE+1", 2.0), ("=--TRUE", 1.0)]:
    check(f, w)

# ---- errors
for f, w in [("=1/0", "#DIV/0!"), ("=SQRT(-1)", "#NUM!"), ("=NOSUCH(1)", "#NAME?"), ('="a"+1', "#VALUE!"), ("=NA()", "#N/A"), ("=IFERROR(1/0,7)", 7.0),
             ("=IFNA(NA(),3)", 3.0), ("=ISERROR(1/0)", True), ("=ISNA(NA())", True), ("=ISERR(NA())", False), ("=1+1/0", "#DIV/0!"),
             ("=LN(0)", "#NUM!"), ("=MOD(5,0)", "#DIV/0!"), ("=ACOS(2)", "#NUM!")]:
    check(f, w)

# ---- logic
for f, w in [("=IF(1>2,1,2)", 2.0), ("=IF(1<2,\"y\")", "y"), ("=IF(1>2,1)", False), ("=AND(1,1,0)", False), ("=OR(0,0,1)", True), ("=NOT(0)", True), ("=XOR(1,1)", False),
             ("=IFS(1>2,\"a\",2>1,\"b\")", "b"), ("=CHOOSE(2,\"a\",\"b\",\"c\")", "b"), ("=ISNUMBER(1)", True), ("=ISTEXT(\"a\")", True),
             ("=ISBLANK(Z99)", True), ("=ISEVEN(4)", True), ("=ISODD(4)", False), ("=ISLOGICAL(TRUE)", True)]:
    check(f, w)

# ---- numbers
for f, w in [("=ROUND(2.5,0)", 3.0), ("=ROUND(-2.5,0)", -3.0), ("=ROUND(1.005,2)", 1.01), ("=ROUND(1234.5678,-2)", 1200.0), ("=ROUNDUP(1.21,1)", 1.3), ("=ROUNDDOWN(-1.29,1)", -1.2),
             ("=INT(-1.5)", -2.0), ("=TRUNC(-1.5)", -1.0), ("=MOD(-3,2)", 1.0), ("=MOD(3,-2)", -1.0), ("=ABS(-3)", 3.0), ("=SIGN(-4)", -1.0), ("=SQRT(16)", 4.0),
             ("=POWER(2,10)", 1024.0), ("=EXP(0)", 1.0), ("=LN(EXP(2))", 2.0), ("=LOG10(1000)", 3.0), ("=LOG(8,2)", 3.0), ("=FACT(5)", 120.0),
             ("=CEILING(2.1,1)", 3.0), ("=FLOOR(2.9,1)", 2.0), ("=MROUND(10,3)", 9.0), ("=PI()", 3.141592653589793), ("=DEGREES(PI())", 180.0),
             ("=RADIANS(180)", 3.141592653589793), ("=ATAN2(1,1)", 0.7853981633974483), ("=SIN(0)", 0.0), ("=COS(0)", 1.0)]:
    check(f, w)

# ---- statistics on constants and arrays
for f, w in [("=SUM(1,2,3)", 6.0), ("=SUM({1,2;3,4})", 10.0), ("=AVERAGE(1,2,3,4)", 2.5), ("=MAX(1,2,3)", 3.0), ("=MIN({4,2,8})", 2.0), ("=MEDIAN(1,3,2,10)", 2.5),
             ("=COUNT(1,\"a\",2)", 2.0), ("=COUNTA(1,\"a\",2)", 3.0), ("=PRODUCT(2,3,4)", 24.0), ("=SUMSQ(3,4)", 25.0), ("=LARGE({5,1,9,3},2)", 5.0),
             ("=SMALL({5,1,9,3},2)", 3.0), ("=SUMPRODUCT({1,2,3},{4,5,6})", 32.0), ("=COUNTIF({1,2,3,4},\">2\")", 2.0), ("=SUMIF({1,2,3,4},\">2\")", 7.0),
             ("=AVERAGEIF({1,2,3,4},\"<=2\")", 1.5), ("=STDEV.S({2,4,4,4,5,5,7,9})", 2.138089935299395), ("=STDEV.P({2,4,4,4,5,5,7,9})", 2.0),
             ("=VAR.P({2,4,4,4,5,5,7,9})", 4.0), ("=SLOPE({2,4,6},{1,2,3})", 2.0), ("=INTERCEPT({2,4,6},{1,2,3})", 0.0), ("=RSQ({2,4,6},{1,2,3})", 1.0),
             ("=CORREL({1,2,3},{2,4,6})", 1.0), ("=FORECAST(4,{2,4,6},{1,2,3})", 8.0), ("=MAXIFS({1,2,3,4},{1,1,2,2},2)", 4.0), ("=MINIFS({1,2,3,4},{1,1,2,2},2)", 3.0)]:
    check(f, w)

# ---- text
for f, w in [('=LEFT("hello",2)', "he"), ('=RIGHT("hello",3)', "llo"), ('=MID("hello",2,3)', "ell"), ('=LEN("abc")', 3.0), ('=UPPER("ab")', "AB"), ('=LOWER("AB")', "ab"),
             ('=PROPER("hello world")', "Hello World"), ('=TRIM("  a  b ")', "a b"), ('=SUBSTITUTE("a-b-c","-","+")', "a+b+c"), ('=FIND("b","abc")', 2.0),
             ('=SEARCH("B","abc")', 2.0), ('=REPT("ab",3)', "ababab"), ('=CONCATENATE("a","b")', "ab"), ('=CONCAT("a",1)', "a1"), ('=TEXTJOIN(",",TRUE,"a","b")', "a,b"),
             ('=VALUE("12.5")', 12.5), ('=EXACT("a","A")', False), ('=TEXT(1234.5,"#,##0.00")', "1,234.50"), ('=TEXT(0.256,"0.0%")', "25.6%"), ('=TEXT(5,"0000")', "0005"),
             ('=TEXT(1234.5,"0.00E+00")', "1.23E+03")]:
    check(f, w)

# ---- lookup and arrays
for f, w in [('=VLOOKUP(2,{1,"a";2,"b"},2,FALSE)', "b"), ('=VLOOKUP(2.5,{1,"a";2,"b";3,"c"},2,TRUE)', "b"), ('=HLOOKUP(3,{1,2,3;"a","b","c"},2,FALSE)', "c"),
             ("=INDEX({1,2;3,4},2,1)", 3.0), ("=MATCH(3,{1,2,3},0)", 3.0), ("=MATCH(2.5,{1,2,3},1)", 2.0), ("=LOOKUP(2,{1,2,3},{\"a\",\"b\",\"c\"})", "b"),
             ("=ROWS({1;2;3})", 3.0), ("=COLUMNS({1,2,3})", 3.0), ("=SUM(TRANSPOSE({1,2,3}))", 6.0), ("=VLOOKUP(9,{1,\"a\"},2,FALSE)", "#N/A"),
             ("=CONVERT(1,\"in\",\"mm\")", 25.4)]:
    check(f, w)

# ---- the parser tells where a formula is wrong, and reads names, sheets and ranges
assert E.check("=1+") is not None and E.check("=(1+2") is not None and E.check("=SUM(1,)") is None
assert E.check("=1+2") is None and E.check("='My Sheet'!A1+Other!$B$2:C3") is None
assert E.function_at("=IF(A1,SUM(B1,", 15) == ("SUM", 1) and E.function_at("=IF(A1,SUM(B1,", 4) == ("IF", 0)
assert E.addr(5, 28) == "AB5" and E.col_letter(1) == "A" and E.col_letter(27) == "AA" and E.parse_addr("AB5") is not None and E.parse_addr("AB") is None
assert E.quote_sheet("Sheet1") == "Sheet1" and E.quote_sheet("My Data") == "'My Data'" and E.quote_sheet("it's") == "'it''s'"

# ---- shifting references (copy/fill): relative moves, $ stays, other sheets move too, off the grid is #REF!
assert E.shift_formula("=A1+B$2+$C3+$D$4", 1, 1) == "=B2+C$2+$C4+$D$4"
assert E.shift_formula("=SUM(A1:B2)", 2, 0) == "=SUM(A3:B4)"
assert E.shift_formula("=Data!A1*2", 1, 0) == "=Data!A2*2"
assert E.shift_formula("='My Data'!$A1", 3, 5) == "='My Data'!$A4"
assert "#REF!" in E.shift_formula("=A1", -1, 0)
assert E.shift_formula("=NumScrews*2", 4, 4) == "=NumScrews*2"
assert E.shift_formula('="A1"&B1', 1, 0) == '="A1"&B2'                    # text in quotes is not a reference

if bad:
    print("\n".join(bad))
    raise SystemExit(f"{len(bad)} engine check(s) failed")
print("OK test_sheets_engine")
