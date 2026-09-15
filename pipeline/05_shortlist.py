#!/usr/bin/env python3
"""Step 5 - the shortlist: primary rows worth carrying forward.

`out/geoname_population.csv` has a row for every geoname, including ones whose
people are already counted on another row. This reduces it to places that can
be added up and are individually meaningful:

    is_primary AND population != 0
               AND (population > 1000 OR a municipality
                    OR an Indigenous community)

Municipalities and Indigenous communities are kept whatever their size,
because a small incorporated municipality and a small Indigenous community
are still distinct communities with their own governments. The threshold then
picks up everywhere else that is substantial: unincorporated communities and
localities.

A row with population exactly 0 is dropped regardless of category: a
reserve or land unit with no recorded population adds nothing to the map and
only crowds it, so being Indigenous or a municipality no longer exempts a
literal zero the way it exempts a small-but-nonzero count. A *suppressed*
count (blank in the source, -1 here) is not the same thing and is not
affected by this rule.

`selected_because` records which clause admitted each row, so the shortlist
can be re-cut without rerunning the join.

    python3 05_shortlist.py [--min-population 1000]
                            [--out out/geoname_shortlist.csv]
"""

import argparse
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(HERE, "out", "geoname_population.csv")
DEFAULT_OUT = os.path.join(HERE, "out", "geoname_shortlist.csv")
DEFAULT_MIN = 1000


def is_municipality(row):
    """One of BC Stats' 162 incorporated municipalities.

    The basis is the test, not the geoname's own type label: it is set only
    when the point resolved to a subdivision present in the province's
    municipal estimates, so it cannot admit a place that merely calls itself
    a city.
    """
    return row["place_population_basis"] == "municipal"


# Every census subdivision type that is an Indigenous government's land.
# "Indian reserve" alone is not the category: the Nisga'a, Tsawwassen,
# Tla'amin and shishalh nations left the reserve system through treaty or
# self-government, so filtering on reserves drops them precisely *because*
# they concluded treaties. NVL has no BC subdivision in 2021 and is listed
# for when one appears.
INDIGENOUS_CSD_TYPES = {"IRI", "NL", "NVL", "TWL", "TAL", "IGD", "S-É"}

# Geonames that name an Indigenous community directly, whatever subdivision
# they fall in. The five "First Nation Village" sites matter most: Hitacu,
# Anaqtl'a, Houpsitas, Hi'tatis and Ak:tiis are the *only* row naming their
# reserve, because no geoname carries the reserve's own name.
INDIGENOUS_GEONAME_TYPES = {"Indian Reserve", "First Nation Village",
                            "Indian Government District"}

# A land unit is a parcel *within* a government district, not a community, and
# the district itself is listed separately - so the 25 shishalh land units are
# excluded even though they sit in an IGD subdivision. 04_join.py's
# `_representative` is what makes this safe: it prefers the district over its
# own land units, so excluding the parcels does not lose the government.
PART_OF_A_LARGER_GOVERNMENT = "Indian Government District : Land Unit"


def is_indigenous(row, csd_types):
    """An Indigenous community, by the geoname or the subdivision it lies in.

    Both tests are needed. Most reserves carry the geoname type, but four are
    named by a Community or Locality geoname instead - Mount Currie, Telegraph
    Creek, Shuswap and Kanaka Bar - and the subdivision is what settles those.

    The subdivision test deliberately does *not* require the row to name its
    subdivision. Gingolx, Laxgalts'ap and New Aiyansh are Nisga'a villages
    inside the single Nisga'a Lands subdivision and name none of it, so a
    naming requirement would drop the Nisga'a communities entirely. The cost
    is that a geoname merely sitting inside Indigenous land is admitted too -
    twelve rows, among them Mill Bay and Glenemma. `place_population_basis`
    and `csd_name` still say which is which on every row.
    """
    if row["geoname_type"] == PART_OF_A_LARGER_GOVERNMENT:
        return False
    return (row["geoname_type"] in INDIGENOUS_GEONAME_TYPES
            or csd_types.get(row["csd_type"]) in INDIGENOUS_CSD_TYPES)


def population(row):
    """-1 for a suppressed count, so it never passes a threshold by accident."""
    return int(row["place_population"]) if row["place_population"] else -1


def csd_type_codes():
    """{human label: code}, inverted from the join's own table.

    The delivered CSV carries the readable label, not the code, so the two
    must agree; taking the mapping from 04_join.py rather than restating it
    means a renamed label cannot silently empty this filter. A test asserts
    every code in INDIGENOUS_CSD_TYPES is present.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "join", os.path.join(HERE, "04_join.py"))
    join = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(join)
    return {label: code for code, label in join.CSD_TYPES.items()}


def select(rows, minimum=DEFAULT_MIN, csd_types=None):
    """Yield (row, reasons) for each shortlisted row, in source order."""
    if csd_types is None:
        csd_types = csd_type_codes()
    for row in rows:
        if row["is_primary"] != "TRUE":
            continue
        if population(row) == 0:
            continue
        reasons = []
        if is_municipality(row):
            reasons.append("municipality")
        if is_indigenous(row, csd_types):
            reasons.append("indigenous")
        if population(row) > minimum:
            reasons.append(f"population>{minimum}")
        if reasons:
            yield row, reasons


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--min-population", type=int, default=DEFAULT_MIN,
                    help=f"threshold for the size clause (default {DEFAULT_MIN}, exclusive)")
    ap.add_argument("--source", default=SOURCE)
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args()

    if not os.path.exists(args.source):
        raise SystemExit(f"missing {args.source}; run 04_join.py first")

    with open(args.source, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        columns = reader.fieldnames
        rows = list(reader)

    if "is_primary" not in columns:
        raise SystemExit(f"{args.source} has no is_primary column; it predates "
                         f"the nesting pass - rerun 04_join.py")

    # selected_because sits beside the other provenance columns rather than at
    # the end, so it is not mistaken for part of the note.
    out_columns = columns[:columns.index("note")] + ["selected_because", "note"]

    picked = list(select(rows, args.min_population))
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=out_columns)
        w.writeheader()
        for row, reasons in picked:
            w.writerow({**row, "selected_because": " + ".join(reasons)})

    primary = sum(1 for r in rows if r["is_primary"] == "TRUE")
    counts = {}
    for _, reasons in picked:
        for r in reasons:
            counts[r] = counts.get(r, 0) + 1
    print(f"{len(picked)} of {primary} primary rows "
          f"({len(rows)} geonames in all)", file=sys.stderr)
    for key in sorted(counts):
        print(f"  {key:<18} {counts[key]:5}", file=sys.stderr)
    only_size = sum(1 for _, rs in picked if rs == [f"population>{args.min_population}"])
    print(f"  {'(size alone)':<18} {only_size:5}", file=sys.stderr)
    total = sum(population(r) for r, _ in picked if population(r) > 0)
    print(f"\n  population represented: {total:,}", file=sys.stderr)
    print(f"\n-> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
