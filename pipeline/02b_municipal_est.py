#!/usr/bin/env python3
"""Step 2b - extract BC Stats municipal population estimates from the workbook.

`pop_municipal_subprov_areas.xlsx` is BC Stats' sub-provincial estimates
series, July 1st of each year 2011-2025, and it is the province's own figure
for its 162 incorporated municipalities. It is preferred over the census count
for those places: an estimate is adjusted for census net undercoverage and for
boundary changes since census day, so it is both larger and more current -
Vancouver is 696,031 on July 1 2021 against the census's 662,248.

Only municipalities are taken. The workbook's regional-district rows (`RD`),
their unincorporated remainders (`RDR`) and the Stikine census division (`R`)
describe the countryside *around* named places rather than the places
themselves, which is the distinction the whole pipeline turns on.

The join key is the workbook's `SGC` column, the last five digits of the
Statistics Canada census subdivision UID: SGC 15022 is CSDUID 5915022. All 162
join, so no name matching is involved anywhere in this step.

    python3 02b_municipal_est.py [--xlsx ...] [--out data/municipal_estimates.csv]
"""

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.xlsx_lite import read_sheet                          # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_XLSX = os.path.join(ROOT, "pop_municipal_subprov_areas.xlsx")
OUT = os.path.join(HERE, "data", "municipal_estimates.csv")

SHEET = "Mun-RD"
BC_PRUID = "59"

# Incorporated municipalities and the two Indian government districts, which
# are municipal in status. RD / RDR / R are deliberately absent; see above.
MUNICIPAL_TYPES = {"CY", "DM", "VL", "T", "IM", "RGM", "IGD"}

COLUMNS = ["csd_uid", "sgc", "name", "area_type", "year", "population"]


def extract(path, sheet=SHEET):
    """[(csd_uid, sgc, name, area_type, {year: population})] in sheet order."""
    rows = read_sheet(path, sheet)

    header = next((r for r in rows if r[:3] == ["SGC", "Name", "Area Type"]), None)
    if header is None:
        raise SystemExit(f"{path}: no 'SGC / Name / Area Type' header row in "
                         f"sheet {sheet!r}; is this the BC Stats workbook?")
    # Year columns are found by their headings rather than by position: the
    # sheet also carries a block of "2011-12 Changes" columns further right,
    # and gains a year every release.
    years = {h: i for i, h in enumerate(header) if h.isdigit() and len(h) == 4}
    if not years:
        raise SystemExit(f"{path}: header row carries no year columns")

    out = []
    for row in rows[rows.index(header) + 1:]:
        if len(row) < 3 or row[2] not in MUNICIPAL_TYPES:
            continue
        sgc = row[0].strip()
        if not sgc.isdigit():
            continue
        # The sheet indents municipality names beneath their regional district.
        name = row[1].strip()
        counts = {}
        for year, col in years.items():
            raw = row[col].strip() if col < len(row) else ""
            if raw.isdigit():
                counts[year] = int(raw)
        out.append((BC_PRUID + sgc.zfill(5), sgc.zfill(5), name, row[2], counts))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", default=DEFAULT_XLSX)
    ap.add_argument("--sheet", default=SHEET)
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()

    if not os.path.exists(args.xlsx):
        raise SystemExit(f"missing {args.xlsx}")

    places = extract(args.xlsx, args.sheet)
    if not places:
        raise SystemExit(f"{args.xlsx}: no municipal rows found")

    uids = [p[0] for p in places]
    if len(set(uids)) != len(uids):
        raise SystemExit("duplicate CSDUID in the workbook; the SGC key is "
                         "not unique, which the join relies on")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    n = 0
    with open(args.out, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        for uid, sgc, name, kind, counts in places:
            for year in sorted(counts):
                w.writerow([uid, sgc, name, kind, year, counts[year]])
                n += 1

    by_type = {}
    for _, _, _, kind, _ in places:
        by_type[kind] = by_type.get(kind, 0) + 1
    years = sorted({y for *_, c in places for y in c})
    print(f"{len(places)} municipalities x {len(years)} years "
          f"({years[0]}-{years[-1]}) = {n} rows", file=sys.stderr)
    print("  " + "  ".join(f"{k}={by_type[k]}" for k in sorted(by_type)),
          file=sys.stderr)
    print(f"-> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
