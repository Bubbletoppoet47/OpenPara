"""
sh_csv.py - bringing a CSV (or tab-separated, or semicolon-separated) file onto a sheet.  No Qt in here, so it can be tested on its own.

    load(path)                      -> CsvFile(path, name, text, encoding, delimiter)   the file read (UTF-8, with or without a BOM, UTF-16 or Windows-1252) and its separator guessed
    parse(text, delimiter)          -> Parsed(rows, cut_rows, cut_cols)                  the fields: quotes, separators and line breaks inside quotes, rows of different lengths
    looks_decimal_comma(rows)       -> True when the numbers are written 3,14 (a semicolon file from a computer set to German, French ...)
    looks_like_header(rows)         -> True when the first row is words and the next one has numbers
    entry(text, decimal_comma)      -> (raw, format hint)                                one field as a cell would get it: numbers and percentages become numbers, TRUE / FALSE
                                                                                         become booleans, everything else stays text - also text that starts with "=", and
                                                                                         codes with leading zeros such as 007
    put(wb, sheet, r0, c0, rows, decimal_comma, header) -> (rows, columns)               writes the block as ONE undo step; `header` makes the first row bold
    existing_cells(wb, sheet, r0, c0, nrows, ncols)     -> how many cells in that block hold something now

Dates stay text: Sheets has no date type yet (typing or pasting 2026-11-19 gives text as well).
"""
import codecs
import csv
import io
import os
import re
from collections import Counter, namedtuple

import sh_book as B
import sh_engine as E

MAX_BYTES = 200_000_000                     # a bigger file is refused
MAX_CELLS = 1_000_000                       # rows beyond this many cells are left out (about 0.5 GB of memory per million cells, and seconds of work)
SAMPLE_BYTES = 65536                        # how much of the start of a file is looked at to guess the separator
PREVIEW_ROWS = 12
DELIMITERS = [("Comma", ","), ("Semicolon", ";"), ("Tab", "\t"), ("Pipe", "|")]
_PRIORITY = ["\t", ";", "|", ","]           # when two separators fit equally well, the earlier one is taken (3,14;2,5 is a semicolon file with decimal commas)
FILE_FILTER = "CSV and text files (*.csv *.tsv *.txt);;All files (*)"

CsvFile = namedtuple("CsvFile", "path name text encoding delimiter")
Parsed = namedtuple("Parsed", "rows cut_rows cut_cols capped")          # capped: rows were left out because of MAX_CELLS (else because of the sheet's size)


class CsvError(Exception):
    """A file that cannot be brought in; the text says why, in words for the person."""


def read_text(raw):
    """The bytes of a file -> (text, encoding name)."""
    if b"\x00" in raw and not raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        raise CsvError("This does not look like a text file (it holds binary data).")
    if raw.startswith(codecs.BOM_UTF8):
        return raw[3:].decode("utf-8", "replace"), "UTF-8"
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        try:
            return raw.decode("utf-16"), "UTF-16"
        except UnicodeDecodeError:
            raise CsvError("This UTF-16 file could not be read.")
    try:
        return raw.decode("utf-8"), "UTF-8"
    except UnicodeDecodeError:
        return raw.decode("cp1252", "replace"), "Windows-1252"          # (an Excel export in Western Europe / the US)


def guess_delimiter(text):
    """The separator that splits the first lines into the same number (2 or more) of fields; "," when none does."""
    cut = text[:SAMPLE_BYTES]
    if len(text) > SAMPLE_BYTES and "\n" in cut:
        cut = cut[:cut.rindex("\n")]
    best, best_key = ",", None
    for d in _PRIORITY:
        try:
            rows = [r for r in list(csv.reader(io.StringIO(cut, newline=""), delimiter=d))[:60] if r]
        except csv.Error:
            continue
        if not rows:
            continue
        n, freq = Counter(len(r) for r in rows).most_common(1)[0]
        if n < 2:
            continue
        key = (round(freq / len(rows), 2), -_PRIORITY.index(d))
        if best_key is None or key > best_key:
            best, best_key = d, key
    return best


def load(path):
    """Reads a file: its text and the separator it most likely uses.  Raises CsvError."""
    try:
        with open(path, "rb") as fh:
            raw = fh.read(MAX_BYTES + 1)
    except OSError as ex:
        raise CsvError(f"The file could not be read: {ex.strerror or ex}")
    if len(raw) > MAX_BYTES:
        raise CsvError(f"This file is too big ({MAX_BYTES // 1_000_000} MB is the limit).")
    if not raw.strip():
        raise CsvError("This file is empty.")
    text, enc = read_text(raw)
    return CsvFile(path, os.path.splitext(os.path.basename(path))[0], text, enc, "\t" if path.lower().endswith(".tsv") else guess_delimiter(text))


def parse(text, delimiter=",", max_rows=E.MAXROW, max_cols=E.MAXCOL, max_cells=MAX_CELLS):
    """The fields of the text.  Rows are not made the same length.  A row or column beyond the sheet's size is dropped (and counted), and so are the rows
    that would take the import past `max_cells`."""
    csv.field_size_limit(1 << 24)
    rows, cut_rows, cut_cols, cells, capped = [], 0, 0, 0, False
    try:
        for row in csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, quotechar='"', doublequote=True):
            if len(row) > max_cols:
                cut_cols = max(cut_cols, len(row) - max_cols)
                row = row[:max_cols]
            if len(rows) >= max_rows or cells + len(row) > max_cells:
                capped = capped or len(rows) < max_rows
                cut_rows += 1
                continue
            cells += len(row)
            rows.append(row)
    except csv.Error as ex:
        raise CsvError(f"The file could not be split into fields: {ex}")
    while rows and not any(f.strip() for f in rows[-1]):             # (empty lines at the end)
        rows.pop()
    return Parsed(rows, cut_rows, cut_cols, capped)


_DEC = re.compile(r"^[+-]?\d{1,3}(\.\d{3})*,\d+%?$|^[+-]?\d+,\d+%?$")
_DOT = re.compile(r"^[+-]?\d+\.\d+%?$")


def looks_decimal_comma(rows):
    """True when the numbers in the first rows are written with a comma (3,14) and none with a point."""
    comma = dot = 0
    for row in rows[:200]:
        for f in row:
            f = f.strip()
            if _DEC.match(f):
                comma += 1
            elif _DOT.match(f):
                dot += 1
    return comma > 0 and dot == 0


def _is_number(text, decimal_comma):
    return isinstance(entry(text, decimal_comma)[0], float)


def looks_like_header(rows, decimal_comma=False):
    """True when the first row is all words and the next row holds a number: a row of column names."""
    if len(rows) < 2:
        return False
    first = [f for f in rows[0] if f.strip()]
    if not first or any(_is_number(f, decimal_comma) for f in first):
        return False
    return any(_is_number(f, decimal_comma) for f in rows[1] if f.strip())


def _decimal(text):
    t = text.strip()
    return t.replace(".", "").replace(",", ".") if _DEC.match(t) else text


def entry(text, decimal_comma=False):
    """One field -> (raw, format hint) for a cell.  Nothing becomes a formula: text that starts with = stays text (it is stored with the ' that marks text)."""
    if not text.strip():
        return None, None
    if decimal_comma:
        text = _decimal(text)
    if text.startswith(("=", "'")) or re.match(r"^[+-]?0\d+$", text.strip()):           # (007 and 01234 are codes, not numbers: they keep their zeros)
        return "'" + text, None
    return B.parse_entry(text)


def existing_cells(wb, sheet, r0, c0, nrows, ncols):
    """How many cells of the block hold something now (an import would replace them)."""
    s = wb.get_sheet(sheet)
    if s is None:
        return 0
    r1, c1 = r0 + nrows - 1, c0 + ncols - 1
    return sum(1 for (r, c), cell in s.cells.items() if r0 <= r <= r1 and c0 <= c <= c1 and cell.raw is not None)


def put(wb, sheet, r0, c0, rows, decimal_comma=False, header=False, label="Import CSV"):
    """Writes the rows with their first field at (r0, c0) as one undo step.  Cells the file leaves empty are emptied.  Returns (rows, columns) written."""
    ncols = max((len(r) for r in rows), default=0)
    bold = B.style_of(bold=True)
    wb.begin(label)
    try:
        for i, row in enumerate(rows):
            r = r0 + i
            if r > E.MAXROW:
                break
            for j in range(ncols):
                c = c0 + j
                if c > E.MAXCOL:
                    break
                raw, hint = entry(row[j], decimal_comma) if j < len(row) else (None, None)
                if header and i == 0 and raw is not None:
                    st = B.style_of(bold=True, fmt=hint) if hint else bold
                else:
                    st = B.style_of(fmt=hint) if hint else None
                wb.set_raw(sheet, r, c, raw, st)
    finally:
        wb.end()
    return min(len(rows), E.MAXROW - r0 + 1), min(ncols, E.MAXCOL - c0 + 1)
