#!/usr/bin/env python3
"""Step 2 - pull population out of a Statistics Canada Census Profile CSV.

The bundled product is 98-401-X2021006 for British Columbia. Unlike the
designated-place product it is *hierarchical*: one file carries the province,
its census divisions, every census subdivision and every dissemination area,
8,630 geographies in all. That matters because designated places are
unincorporated by definition and so exclude every city, village, district
municipality and nearly all Indian reserves - a hard ceiling near 10% of the
sheet. DAs tile the province completely and CSDs cover the municipalities.

The file is already BC-only (plus Canada and BC summary rows), so no province
filter is applied; every geographic level is kept and GEO_LEVEL is recorded
per row so the join can decide which one to use.

At 3.6 GB with 2,631 characteristics per geography this streams the file and
keeps only the characteristic of interest (ID 1 = "Population, 2021"),
reducing ~22.7 M data lines to 8,630.

    python3 02_census_pop.py [--data PATH] [--characteristic 1] [--pr '']
"""

import argparse
import csv
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_DATA = os.path.join(
    ROOT, "98-401-X2021006_BC_CB_eng_CSV",
    "98-401-X2021006_English_CSV_data_BritishColumbia.csv")
OUT = os.path.join(HERE, "data", "census_population.csv")

# Column positions in the Census Profile layout. The header repeats the name
# "SYMBOL" five times, so DictReader would collapse them - index by position.
C_DGUID, C_ALT_GEO, C_GEO_LEVEL, C_GEO_NAME = 1, 2, 3, 4
C_CHAR_ID, C_CHAR_NAME, C_COUNT = 8, 9, 11

# Some products suffix the geography type onto the name - "Hagensborg part A,
# Designated place (DPL)". Others, this one included, do not. Splitting on the
# last comma unconditionally would maul any name that simply contains one, so
# the suffix is only stripped when it actually looks like a type descriptor.
_KIND_RE = re.compile(r"^(?P<name>.+),\s*(?P<kind>[A-Za-z][A-Za-z .'-]*"
                      r"(?:\s*\([A-Z0-9]{1,5}\))?)$")
_KIND_TAIL = re.compile(r"\((?:[A-Z0-9]{1,5})\)$")


def parse_count(raw):
    """Census counts are integers, but may be blank or a suppression symbol."""
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        try:
            return int(round(float(raw)))
        except ValueError:
            return None                       # x / F / .. / ...


def split_kind(geo_name):
    """('Hagensborg part A, Designated place (DPL)') -> (name, kind)."""
    m = _KIND_RE.match(geo_name)
    if m and _KIND_TAIL.search(m.group("kind")):
        return m.group("name").strip(), m.group("kind").strip()
    return geo_name, ""


def extract(data_path, characteristic_id="1", pr_prefix=None):
    rows = []
    with open(data_path, encoding="latin-1", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        if header[C_CHAR_ID] != "CHARACTERISTIC_ID":
            raise SystemExit(
                f"unexpected layout: column {C_CHAR_ID} is {header[C_CHAR_ID]!r}, "
                "expected CHARACTERISTIC_ID")
        for rec in reader:
            if len(rec) <= C_COUNT or rec[C_CHAR_ID] != characteristic_id:
                continue
            alt = rec[C_ALT_GEO].strip()
            if pr_prefix and not alt.startswith(pr_prefix):
                continue
            geo_name = rec[C_GEO_NAME].strip()
            name, kind = split_kind(geo_name)
            rows.append({
                "dguid": rec[C_DGUID].strip(),
                "alt_geo_code": alt,
                "geo_level": rec[C_GEO_LEVEL].strip(),
                "geo_name_full": geo_name,
                "geo_name": name,
                "geo_kind": kind,
                "characteristic": rec[C_CHAR_NAME].strip(),
                "population": parse_count(rec[C_COUNT]),
            })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=DEFAULT_DATA)
    ap.add_argument("--characteristic", default="1",
                    help="CHARACTERISTIC_ID (1 = Population, 2021)")
    ap.add_argument("--pr", default="",
                    help="keep only this province prefix of ALT_GEO_CODE; "
                         "the default file is already BC-only, so empty")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()

    if not os.path.exists(args.data):
        raise SystemExit(f"census data not found: {args.data}")

    print(f"streaming {os.path.getsize(args.data)/1e9:.1f} GB ...", file=sys.stderr)
    rows = extract(args.data, args.characteristic, args.pr or None)
    if not rows:
        raise SystemExit("no rows matched - check --characteristic / --pr")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    cols = ["dguid", "alt_geo_code", "geo_level", "geo_name_full", "geo_name",
            "geo_kind", "characteristic", "population"]
    with open(args.out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    known = [r for r in rows if r["population"] is not None]
    by_level = {}
    for r in rows:
        by_level[r["geo_level"]] = by_level.get(r["geo_level"], 0) + 1
    print(f"{len(rows)} geographies ({rows[0]['characteristic']!r})", file=sys.stderr)
    print(f"  population present: {len(known)}   suppressed/blank: "
          f"{len(rows)-len(known)}", file=sys.stderr)
    for lvl, n in sorted(by_level.items(), key=lambda kv: -kv[1]):
        print(f"    {lvl:<24} {n:>6}", file=sys.stderr)
    print(f"-> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
