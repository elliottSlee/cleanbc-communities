"""Minimal .xlsx (SpreadsheetML) cell reader, pure stdlib.

Enough of ECMA-376 to read a published statistics workbook without openpyxl.
Values come back as strings exactly as stored; no type or date coercion, which
suits a sheet of counts whose blanks and footnotes must survive the trip.

Two details of the format bite anyone reading it casually. Text cells usually
hold an index into a shared string table rather than the text itself, and a
row's <c> elements are sparse - an empty cell is simply absent - so cells are
placed by their A1 reference and gaps padded, never taken in document order.
"""

import re
import zipfile
from xml.etree import ElementTree as ET

_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_COL = re.compile(r"([A-Z]+)")


class XlsxError(Exception):
    pass


def _text(el):
    """Concatenate a string item's runs, skipping phonetic guides."""
    parts = []
    for node in el.iter():
        if node.tag == _MAIN + "rPh":       # furigana; not part of the value
            continue
        if node.tag == _MAIN + "t":
            parts.append(node.text or "")
    return "".join(parts)


def _shared_strings(z):
    try:
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    return [_text(si) for si in root]


def sheet_names(z):
    """[(name, part path)] in workbook order."""
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = {r.get("Id"): r.get("Target")
            for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    out = []
    for s in wb.find(_MAIN + "sheets"):
        target = (rels.get(s.get(_REL + "id")) or "").lstrip("/")
        if not target:
            continue
        out.append((s.get("name"),
                    target if target.startswith("xl/") else "xl/" + target))
    return out


def _col_index(ref):
    """'C4' -> 2. Bijective base-26 over A-Z, so 'AA' is 26, not 0."""
    n = 0
    for ch in _COL.match(ref).group(1):
        n = n * 26 + ord(ch) - 64
    return n - 1


def _rows(z, path, strings):
    root = ET.fromstring(z.read(path))
    for row in root.iter(_MAIN + "row"):
        cells = {}
        for c in row.iter(_MAIN + "c"):
            kind, ref = c.get("t"), c.get("r")
            if kind == "inlineStr":
                value = _text(c)
            else:
                v = c.find(_MAIN + "v")
                if v is None:
                    continue
                value = (strings[int(v.text)] if kind == "s" else (v.text or ""))
            cells[_col_index(ref) if ref else len(cells)] = value
        if cells:
            yield [cells.get(i, "") for i in range(max(cells) + 1)]


def read_sheet(path, sheet=None):
    """Rows of a workbook sheet as lists of strings.

    `sheet` selects by name, else by zero-based position; the first sheet by
    default. Trailing empty cells are trimmed, so rows vary in length.
    """
    with zipfile.ZipFile(path) as z:
        sheets = sheet_names(z)
        if not sheets:
            raise XlsxError(f"no worksheets in {path}")
        if sheet is None:
            name, part = sheets[0]
        elif isinstance(sheet, int):
            name, part = sheets[sheet]
        else:
            match = [s for s in sheets if s[0] == sheet]
            if not match:
                raise XlsxError(
                    f"no sheet {sheet!r} in {path}; have "
                    + ", ".join(repr(n) for n, _ in sheets))
            name, part = match[0]
        return list(_rows(z, part, _shared_strings(z)))
