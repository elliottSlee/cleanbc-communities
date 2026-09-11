"""Minimal ESRI Shapefile (.shp + .dbf) polygon reader, pure stdlib.

Enough of the spec to read Statistics Canada boundary files without
GDAL/fiona. Reference: ESRI Shapefile Technical Description (July 1998).
Only the polygon shape types are supported - that is all the boundary
files contain.

Two things keep the national files tractable. Records can be filtered on their
.dbf attributes with `where=`, and geometry is parsed only for the ones that
pass - the national dissemination-area layer holds 57,936 polygons and would
cost roughly a gigabyte of Python tuples if fully materialised. And the .shp is
streamed straight out of the zip: the format is read strictly front-to-back, so
nothing is ever extracted to disk, which matters on a nearly full volume.
"""

import io
import struct
import zipfile

NULL = 0
POLYGON, POLYGON_Z, POLYGON_M = 5, 15, 25
_POLYGONS = (POLYGON, POLYGON_Z, POLYGON_M)


class ShapefileError(Exception):
    pass


def _readexactly(fh, n):
    """Streamed zip members may hand back short reads; insist on n bytes."""
    chunks, got = [], 0
    while got < n:
        b = fh.read(n - got)
        if not b:
            break
        chunks.append(b)
        got += len(b)
    return b"".join(chunks)


def _iter_shp_records(fh):
    """Yield (bbox, content) per record, forward-only, geometry unparsed."""
    head = _readexactly(fh, 100)
    if len(head) < 100 or struct.unpack(">i", head[:4])[0] != 9994:
        raise ShapefileError("not a shapefile (bad magic)")
    file_len = struct.unpack(">i", head[24:28])[0] * 2
    shp_type = struct.unpack("<i", head[32:36])[0]
    if shp_type not in _POLYGONS + (NULL,):
        raise ShapefileError(f"shape type {shp_type} is not a polygon type")

    pos = 100
    while pos < file_len:
        hdr = _readexactly(fh, 8)
        if len(hdr) < 8:
            break
        _, content_words = struct.unpack(">ii", hdr)
        content = _readexactly(fh, content_words * 2)
        pos += 8 + content_words * 2
        if len(content) < 4:
            break
        rec_type = struct.unpack("<i", content[:4])[0]
        if rec_type == NULL:
            yield None, None
            continue
        if rec_type not in _POLYGONS:
            raise ShapefileError(f"unexpected record shape type {rec_type}")
        yield struct.unpack("<4d", content[4:36]), content


def _rings(content):
    n_parts, n_points = struct.unpack("<ii", content[36:44])
    off = 44
    parts = struct.unpack(f"<{n_parts}i", content[off:off + 4 * n_parts])
    off += 4 * n_parts
    flat = struct.unpack(f"<{2 * n_points}d", content[off:off + 16 * n_points])
    bounds = list(parts) + [n_points]
    out = []
    for i in range(n_parts):
        s, e = bounds[i], bounds[i + 1]
        out.append([(flat[2 * j], flat[2 * j + 1]) for j in range(s, e)])
    return out


def _read_dbf(fh):
    """Yield dicts of attribute values, in record order."""
    head = _readexactly(fh, 32)
    n_records, header_len, record_len = struct.unpack("<iHH", head[4:12])

    # The field-descriptor array ends with a lone 0x0D byte, not a 32-byte
    # descriptor, so the terminator is peeked one byte at a time. Reading a
    # full 32 bytes to spot it would run 31 bytes into the first record, and
    # a forward-only stream cannot seek back: every record would then be
    # decoded at the wrong offset and the last would run short and vanish.
    fields, consumed = [], 32
    while consumed < header_len:
        first = _readexactly(fh, 1)
        consumed += 1
        if not first or first[0] in (0x0D, 0x00):
            break
        desc = first + _readexactly(fh, 31)
        consumed += 31
        if len(desc) < 32:
            break
        name = desc[:11].split(b"\x00")[0].decode("latin-1").strip()
        fields.append((name, chr(desc[11]), desc[16]))

    if consumed < header_len:                  # driver-specific header tail
        _readexactly(fh, header_len - consumed)

    for _ in range(n_records):
        rec = _readexactly(fh, record_len)
        if len(rec) < record_len or rec[:1] == b"\x1a":
            break
        if rec[:1] == b"*":                    # deleted
            yield None
            continue
        row, pos = {}, 1
        for name, ftype, flen in fields:
            raw = rec[pos:pos + flen].decode("latin-1").strip()
            pos += flen
            if ftype in ("N", "F"):
                row[name] = _num(raw)
            elif ftype == "L":
                row[name] = raw.upper() in ("Y", "T")
            else:
                row[name] = raw
        yield row


def _num(raw):
    if raw in ("", "-"):
        return None
    try:
        return int(raw) if ("." not in raw and "e" not in raw.lower()) else float(raw)
    except ValueError:
        try:
            return float(raw)
        except ValueError:
            return raw


def _collect(shp_fh, dbf_fh, where):
    # strict=True replaces the length check the materialising version could do
    # up front: streaming cannot count the .shp ahead of time, but a .shp and
    # .dbf that run out at different points still means the parse desynced.
    out = []
    for (bbox, content), attrs in zip(_iter_shp_records(shp_fh),
                                      _read_dbf(dbf_fh), strict=True):
        if attrs is None or bbox is None or content is None:
            continue
        if where is not None and not where(attrs):
            continue                           # skip geometry parsing entirely
        rings = _rings(content)
        if rings:
            out.append({"attrs": attrs, "bbox": bbox, "rings": rings})
    return out


def read_polygons(shp_bytes, dbf_bytes, where=None):
    """Read from in-memory bytes; see read_polygons_from_zip for normal use."""
    return _collect(io.BytesIO(shp_bytes), io.BytesIO(dbf_bytes), where)


def read_polygons_from_zip(path, stem=None, where=None):
    """Read the first (or named) polygon layer inside a zipped shapefile.

    `where(attrs) -> bool` filters on .dbf attributes before any geometry is
    parsed. The .shp is streamed, never extracted.
    """
    with zipfile.ZipFile(path) as z:
        shps = [n for n in z.namelist() if n.lower().endswith(".shp")]
        if stem:
            shps = [n for n in shps if stem.lower() in n.lower()]
        if not shps:
            raise ShapefileError(f"no .shp found in {path}")
        shp = sorted(shps, key=len)[0]
        names = {n.lower(): n for n in z.namelist()}
        dbf_key = (shp[:-4] + ".dbf").lower()
        if dbf_key not in names:
            raise ShapefileError(f"{shp} has no matching .dbf")
        # The .dbf is small and is consumed in lockstep with the .shp, so it is
        # read up front; the .shp is the one that must not be materialised.
        dbf_bytes = z.read(names[dbf_key])
        with z.open(shp) as shp_fh:
            return _collect(shp_fh, io.BytesIO(dbf_bytes), where)
