#!/usr/bin/env python3
"""Step 5b - drop shortlisted places that lie inside a municipality they are
not themselves.

`05_shortlist.py` keeps every municipality and every substantial community,
but some of those communities are neighbourhoods of a municipality already
on the list - James Bay is a shortlisted locality entirely inside Victoria,
which is also shortlisted. Showing both makes Victoria look like two places.

This drops the neighbourhood, not the municipality: any shortlisted row whose
point falls inside a municipality's *legal* boundary
(`data/municipalities.geojson`, fetched by `03d_fetch_municipalities.py` from
the BC Data Catalogue) is excluded, unless the row **is** that municipality.
There is no carve-out for Indian reserves that happen to sit inside a city's
boundary (Tsawwassen in Delta, Musqueam in Vancouver, and 66 others) - this
was a deliberate call, not an oversight: see pipeline/README.md.

"Is that municipality" is read off `place_population_basis == "municipal"`,
the flag `04_join.py` already set from census-subdivision containment plus
its two name/type exceptions (100 Mile House, Northern Rockies) - not
recomputed here by comparing names against DataBC's own official-name
strings, which are inconsistently formatted ("The Corporation of the Village
of Hazelton") and would need the same exceptions duplicated to match.

Reads `05_shortlist.py`'s output but does not touch it - a plain neighbourhood
inside a municipality (James Bay, in Victoria) never reaches that file in the
first place, because it is too small and already dropped by `04_join.py`'s
census-hierarchy nesting. This step only ever catches the case that hierarchy
cannot see: two census subdivisions that are geometric siblings - a reserve
and the city around it - even though one's legal boundary sits entirely
inside the other's. Writes a new, further-reduced file instead, so
`out/geoname_shortlist.csv` still means exactly what `05_shortlist.py` says
it means.

    python3 05b_exclude_nested_municipalities.py
        [--shortlist out/geoname_shortlist.csv]
        [--municipalities data/municipalities.geojson]
        [--out out/geoname_shortlist_deduped.csv]
        [--excluded-out out/excluded_within_municipality.csv]
"""

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.spatial import PolygonIndex, load_geojson_polygons  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SHORTLIST = os.path.join(HERE, "out", "geoname_shortlist.csv")
DEFAULT_MUNICIPALITIES = os.path.join(HERE, "data", "municipalities.geojson")
DEFAULT_OUT = os.path.join(HERE, "out", "geoname_shortlist_deduped.csv")
DEFAULT_EXCLUDED_OUT = os.path.join(HERE, "out",
                                    "excluded_within_municipality.csv")


def is_the_municipality(row):
    return row["place_population_basis"] == "municipal"


def find_nested(rows, index):
    """Yield (row, containing_municipality_official_name) for every row that
    lies inside a municipality's legal boundary and is not that municipality.
    """
    for row in rows:
        if is_the_municipality(row):
            continue
        lon, lat = row.get("lon"), row.get("lat")
        if not lon or not lat:
            continue
        hits = index.query(float(lon), float(lat))
        if hits:
            yield row, hits[0]["attrs"]["official"]


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shortlist", default=DEFAULT_SHORTLIST)
    ap.add_argument("--municipalities", default=DEFAULT_MUNICIPALITIES)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--excluded-out", default=DEFAULT_EXCLUDED_OUT)
    args = ap.parse_args(argv)

    if not os.path.exists(args.shortlist):
        raise SystemExit(f"missing {args.shortlist}; run 05_shortlist.py first")
    if not os.path.exists(args.municipalities):
        raise SystemExit(f"missing {args.municipalities}; run "
                         f"03d_fetch_municipalities.py first")

    with open(args.shortlist, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        columns = reader.fieldnames
        rows = list(reader)

    polygons = load_geojson_polygons(args.municipalities)
    index = PolygonIndex(polygons)

    nested = list(find_nested(rows, index))
    nested_ids = {row["geoname_id"] for row, _ in nested}
    kept = [row for row in rows if row["geoname_id"] not in nested_ids]

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerows(kept)

    os.makedirs(os.path.dirname(os.path.abspath(args.excluded_out)),
               exist_ok=True)
    with open(args.excluded_out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["geoname_id", "bc_geographic_name",
                                          "within_municipality"])
        w.writeheader()
        for row, official in nested:
            w.writerow({"geoname_id": row["geoname_id"],
                       "bc_geographic_name": row["bc_geographic_name"],
                       "within_municipality": official})

    print(f"{len(nested)} of {len(rows)} shortlisted rows lie inside a "
          f"municipality they are not themselves; {len(kept)} remain",
          file=sys.stderr)
    for row, official in sorted(nested, key=lambda p: p[1]):
        print(f"  {row['bc_geographic_name']:<30} -> {official}",
              file=sys.stderr)
    print(f"\n-> {args.out}\n-> {args.excluded_out}", file=sys.stderr)


if __name__ == "__main__":
    main()
