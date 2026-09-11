#!/usr/bin/env python3
"""Step 3 - download 2021 census boundary files from Statistics Canada.

Needed because neither bundled source carries a polygon: the census CSV has no
geometry, and the BCGNWS API returns a single representative *point* per name.
A containment join needs the census geography's outline, which Statistics
Canada distributes separately as a zipped shapefile in EPSG:3347.

Two layers are downloaded by default, because one alone cannot answer the
question. Census subdivisions give the population *of* a named municipality or
Indian reserve; dissemination areas tile the whole province, so every point
lands in one, but each holds only 400-700 people. See README.md.

    python3 03_fetch_boundaries.py [--layer da csd] [--kind digital]
"""

import argparse
import os
import sys
import urllib.request

from lib.tls import make_context

HERE = os.path.dirname(os.path.abspath(__file__))
DEST_DIR = os.path.join(HERE, "data")

BASE = ("https://www12.statcan.gc.ca/census-recensement/2021/geo/sip-pis/"
        "boundary-limites/files-fichiers")

# Digital boundaries follow the true legal limits (into water); preferred for
# containment. Cartographic boundaries are clipped to the coastline, which
# would drop shoreline points into no polygon at all.
FILES = {
    "da":  {"digital": "lda_000b21a_e.zip",  "cartographic": "lda_000a21a_e.zip"},
    "csd": {"digital": "lcsd000b21a_e.zip", "cartographic": "lcsd000a21a_e.zip"},
    "dpl": {"digital": "ldpl000b21a_e.zip", "cartographic": "ldpl000a21a_e.zip"},
}
DEFAULT_LAYERS = ("da", "csd")

# The files are national; only BC is ever parsed. Filtering on this .dbf
# attribute before any geometry is decoded is what keeps the DA layer
# (57,936 polygons nationally) inside a sane memory budget.
BC_PRUID = "59"

USER_AGENT = "CleanBC-geoname-population/1.0"


def path_for(layer, kind="digital", dest_dir=DEST_DIR):
    return os.path.join(dest_dir, FILES[layer][kind])


def download(layer, kind="digital", dest_dir=DEST_DIR, force=False):
    dest = path_for(layer, kind, dest_dir)
    if os.path.exists(dest) and os.path.getsize(dest) > 0 and not force:
        print(f"already present: {dest} "
              f"({os.path.getsize(dest)/1e6:.1f} MB)", file=sys.stderr)
        return dest

    os.makedirs(dest_dir, exist_ok=True)
    url = f"{BASE}/{FILES[layer][kind]}"
    print(f"downloading {url}", file=sys.stderr)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    tmp = dest + ".part"
    with urllib.request.urlopen(req, timeout=300,
                                context=make_context()) as r, \
            open(tmp, "wb") as out:
        total = int(r.headers.get("Content-Length") or 0)
        got = 0
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            out.write(chunk)
            got += len(chunk)
            if total:
                pct = 100 * got / total
                print(f"\r  {got/1e6:6.1f} / {total/1e6:.1f} MB ({pct:4.1f}%)",
                      end="", file=sys.stderr)
        print("", file=sys.stderr)
    os.replace(tmp, dest)
    print(f"-> {dest} ({os.path.getsize(dest)/1e6:.1f} MB)", file=sys.stderr)
    return dest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--layer", nargs="+", choices=sorted(FILES),
                    default=list(DEFAULT_LAYERS))
    ap.add_argument("--kind", choices=("digital", "cartographic"),
                    default="digital")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-verify", action="store_true",
                    help="skip the parse-back check (saves a minute)")
    args = ap.parse_args()

    from lib.shapefile_lite import read_polygons_from_zip
    for layer in args.layer:
        path = download(layer, args.kind, force=args.force)
        if args.no_verify:
            continue
        # where= discards non-BC records before their geometry is parsed;
        # without it the national DA layer costs about a gigabyte of tuples.
        polys = read_polygons_from_zip(
            path, where=lambda a: str(a.get("PRUID")) == BC_PRUID)
        keys = sorted((polys[0]["attrs"] or {}).keys()) if polys else []
        print(f"readable: {len(polys)} BC polygons; attributes = {keys}",
              file=sys.stderr)


if __name__ == "__main__":
    main()
