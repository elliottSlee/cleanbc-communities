#!/usr/bin/env python3
"""Step 4 - attach a 2021 population to every Geonames.csv row.

Two census layers are queried for each geoname's representative point, because
neither answers the question alone:

  census subdivision (CSD)   the municipality, district municipality, village
                             or Indian reserve the point falls in. When the
                             geoname names that CSD, its count is the
                             population *of the named place*.
  dissemination area (DA)    the smallest census unit, 400-700 people. DAs
                             tile the province, so every land point lands in
                             exactly one, but a DA is emphatically *not* the
                             named place: the DA holding Vancouver's label
                             point has a few hundred people, not 662,000.

A third source overrides the census for the places it covers. BC Stats'
sub-provincial estimates are the province's own figures for its 162
incorporated municipalities, adjusted for census net undercoverage, so when a
geoname resolves to one of them its estimate is used instead of the census
count - Vancouver is 696,031 on July 1 2021, not the census's 662,248.

`place_population_basis` says which of the three the number came from:

  municipal   BC Stats' estimate for the incorporated municipality the geoname
              names. The best figure available, and the one to trust.
  csd         the census count for the subdivision the geoname names - an
              Indian reserve, Nisga'a village or other non-municipal CSD.
  da          the surrounding dissemination area, describing the small area
              around the point and nothing more.

`place_population_source` spells the same thing out in words. The three are
never collapsed into one unlabelled number.

Because the sheet lists places at several levels at once - Coquitlam and
Essondale inside it, Vancouver and Kitsilano inside that - adding the
populations up would count people repeatedly. `is_nested` and `is_primary`
say which rows overlap which; see `mark_nesting` for how they are derived and
how to sum the sheet safely.

Geometry decides; names only corroborate. BC reuses names freely - "Mill Bay",
"Bear Lake" and "Pine Valley" each have a same-named census place 318-820 km
away - so a name is never allowed to select a polygon, only to interpret the
one containment already chose.

    python3 04_join.py [--tolerance 2000] [--estimate-year 2021]
                       [--out out/geoname_population.csv]

To total the province without double counting, keep the rows where
`is_primary` is TRUE and ignore the rest.
"""

import argparse
import csv
import json
import math
import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.proj_lcc import statcan_lambert                       # noqa: E402
from lib.shapefile_lite import read_polygons_from_zip          # noqa: E402
from lib.spatial import PolygonIndex                           # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
POINTS = os.path.join(HERE, "data", "geoname_points.jsonl")
CENSUS = os.path.join(HERE, "data", "census_population.csv")
ESTIMATES = os.path.join(HERE, "data", "municipal_estimates.csv")
DA_ZIP = os.path.join(HERE, "data", "lda_000b21a_e.zip")
CSD_ZIP = os.path.join(HERE, "data", "lcsd000b21a_e.zip")
OUT = os.path.join(HERE, "out", "geoname_population.csv")
UNCLAIMED = os.path.join(HERE, "out", "unclaimed_csds.csv")

BC_PRUID = "59"

# The census is 2021, so the estimate defaults to the same vintage: every
# figure in the output then describes the same year, and the improvement over
# the census count is purely one of method. --estimate-year takes any year the
# workbook carries (2011-2025); `muni_population_latest` always holds the
# newest regardless, so the current figure is never more than a column away.
DEFAULT_ESTIMATE_YEAR = "2021"

COLUMNS = [
    "geoname_id", "bc_geographic_name", "geoname_type",
    "lon", "lat", "bcgn_name", "bcgn_feature_type",
    "da_uid", "da_population", "da_match", "da_distance_m",
    "csd_uid", "csd_name", "csd_type", "csd_population",
    "csd_match", "csd_distance_m", "name_agrees_with_csd",
    "muni_name", "muni_type",
    "muni_population", "muni_population_year",
    "muni_population_latest", "muni_latest_year",
    "place_population", "place_population_basis", "place_population_source",
    "place_population_confidence",
    "geo_level", "geo_uid", "geo_shared_with",
    "parent_geoname_id", "parent_name", "is_nested", "is_primary",
    "note",
]

# Census subdivision type codes, for a readable column alongside the code.
CSD_TYPES = {
    "CY": "City", "DM": "District municipality", "VL": "Village", "T": "Town",
    "IRI": "Indian reserve", "RDA": "Regional district electoral area",
    "IGD": "Indian government district", "IM": "Island municipality",
    "NL": "Nisga'a land", "NVL": "Nisga'a village", "RGM": "Regional municipality",
    # TAL is Tla'amin Lands - BC's only TAL subdivision is Sliammon 1, the
    # Tla'amin Nation's treaty settlement land near Powell River. It is not
    # Teslin, which is in Yukon; the census names it "Tla'amin Lands (TAL)".
    "S-É": "Indian settlement", "TAL": "Tla'amin Lands", "TWL": "Tsawwassen Lands",
}

# An incorporated municipality's label point lies inside its own census
# subdivision by construction, so for these types containment alone settles
# the basis and the spelling need not agree. That matters because a few do
# not: "100 Mile House" is the CSD "One Hundred Mile House", and "Northern
# Rockies Regional Municipality" is the CSD "Northern Rockies". Across the
# 159 municipal geonames in the sheet this rule and name agreement give the
# same answer 157 times, and the two they differ on are both these.
# Deliberately excludes RDA and IRI: a regional district electoral area is
# the countryside *around* named places, not one of them.
MUNICIPAL_GEONAME_TYPES = {
    "city", "district municipality", "village", "town",
    "resort municipality", "regional municipality", "island municipality",
}
MUNICIPAL_CSD_TYPES = {"CY", "DM", "VL", "T", "RGM", "IM"}

# Municipal descriptors appear on either side in this sheet: "City of Foo"
# but also "Queen Charlotte, Village of" / "West Kelowna, City of".
_DESCRIPTOR = r"(?:city|village|town|district|district municipality|" \
              r"resort municipality|municipality)"

# Statistics Canada disambiguates repeated CSD names with a parenthesised type
# code - "Langley (CY)" beside "Langley (DM)". Strip it before comparing, or a
# geoname that simply says "Langley" would agree with neither.
_CSD_SUFFIX = re.compile(r"\s*\([A-Z0-9\-É]{1,5}\)\s*$")

# Apostrophes are deleted rather than folded to a space, so that every
# spelling of a name collapses together: a typographic apostrophe would
# otherwise vanish in the ASCII fold ("Nisga’a" -> "nisgaa") while an
# ASCII one became a space ("Nisga'a" -> "nisga a"), and the two would never
# match. All three sources happen to use ASCII apostrophes today; this keeps
# the join correct if any of them changes.
_APOSTROPHES = dict.fromkeys(map(ord, "'’‘ʼ՚`´"), None)


def norm(s):
    """Casefold, strip accents and punctuation, drop municipal descriptors."""
    s = unicodedata.normalize("NFKC", s or "").translate(_APOSTROPHES)
    s = unicodedata.normalize("NFKD", s)
    s = s.encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()
    s = re.sub(rf"^(?:the\s+)?{_DESCRIPTOR}\s+of\s+", "", s)
    s = re.sub(rf"\s+{_DESCRIPTOR}\s+of$", "", s)
    return re.sub(r"^the\s+", "", s).strip()


def norm_csd(s):
    """As norm(), minus the parenthesised type code StatCan appends."""
    return norm(_CSD_SUFFIX.sub("", s or ""))


def read_geonames(path):
    with open(path, encoding="utf-8-sig", errors="replace", newline="") as f:
        for row in csv.DictReader(f):
            gid = (row.get("GeoName ID") or "").strip()
            if not gid.isdigit():
                continue
            yield {"geoname_id": gid,
                   "bc_geographic_name": (row.get("BC Geographic Name") or "").strip(),
                   "geoname_type": (row.get("Type") or "").strip()}


def read_points(path):
    if not os.path.exists(path):
        raise SystemExit(f"missing {path}; run 01_fetch_points.py first")
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            out[str(rec["geoname_id"])] = rec       # later lines win
    return out


def read_census(path):
    if not os.path.exists(path):
        raise SystemExit(f"missing {path}; run 02_census_pop.py first")
    by_dguid = {}
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            by_dguid[row["dguid"]] = row
    return by_dguid


def read_estimates(path):
    """{csduid: {"name", "area_type", "counts": {year: population}}}.

    Keyed on the census subdivision UID the workbook's SGC column maps to, so
    the municipal figures attach to whatever polygon containment already chose.
    No name is consulted.
    """
    if not os.path.exists(path):
        raise SystemExit(f"missing {path}; run 02b_municipal_est.py first "
                         f"(or pass --no-estimates for census figures only)")
    out = {}
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            rec = out.setdefault(row["csd_uid"], {"name": row["name"],
                                                  "area_type": row["area_type"],
                                                  "counts": {}})
            if row["population"]:
                rec["counts"][row["year"]] = int(row["population"])
    return out


def ring_distance(x, y, poly, cutoff=float("inf")):
    """Metres from (x, y) to the nearest polygon edge."""
    best = cutoff
    for ring in poly["rings"]:
        n = len(ring)
        for i in range(n):
            x1, y1 = ring[i - 1]
            x2, y2 = ring[i]
            dx, dy = x2 - x1, y2 - y1
            L = dx * dx + dy * dy
            t = 0.0 if L == 0 else max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / L))
            d = math.hypot(x - (x1 + t * dx), y - (y1 + t * dy))
            if d < best:
                best = d
    return best


def _bbox_distance(x, y, bbox):
    bx0, by0, bx1, by1 = bbox
    return math.hypot(max(bx0 - x, 0.0, x - bx1), max(by0 - y, 0.0, y - by1))


def nearest_polygon(x, y, polys):
    """Closest polygon by true edge distance, bounded by bbox distance first.

    A bbox can only be nearer than the polygon inside it, so once the best
    exact distance beats the next bbox distance no later candidate can win.
    That turns a 7,848-polygon scan into a handful of ring walks.
    """
    ranked = sorted(((_bbox_distance(x, y, p["bbox"]), i, p)
                     for i, p in enumerate(polys)), key=lambda t: t[0])
    best_d, best_p = float("inf"), None
    for bd, _, p in ranked:
        if bd >= best_d:
            break
        d = ring_distance(x, y, p, best_d)
        if d < best_d:
            best_d, best_p = d, p
    return best_d, best_p


def _representative(row):
    """Sort key choosing the row that best speaks for a shared geography.

    Status first, then how the point matched, then whether the geoname is a
    municipal one, then whether it agreed by name, then distance, then the
    geoname id so the choice never depends on row order.
    """
    level = row["geo_level"]
    match = row["csd_match"] if level == "csd" else row["da_match"]
    dist = row["csd_distance_m"] if level == "csd" else row["da_distance_m"]
    return (
        0 if row["place_population_basis"] == "municipal" else 1,
        0 if match == "contains" else 1,
        0 if row["geoname_type"].strip().lower() in MUNICIPAL_GEONAME_TYPES else 1,
        # A part loses to the whole. The shishalh Nation's government district
        # shares a dissemination area with "Sechelt SB 2", one of the land
        # units inside it; without this the parcel would speak for the DA and
        # the government itself would drop out.
        1 if "land unit" in row["geoname_type"].lower() else 0,
        # A locality is a named place, not necessarily an inhabited one, so it
        # is the weakest thing that can speak for a populated area. Without
        # this the Nisga'a village of Gitwinksihlkw loses its dissemination
        # area to the locality "Mill Bay" on nothing but a lower geoname id.
        1 if row["geoname_type"].strip().lower() == "locality" else 0,
        0 if row["name_agrees_with_csd"] == "yes" else 1,
        float(dist or 0),
        int(row["geoname_id"] or 0),
    )


def mark_nesting(results):
    """Say where each row sits in the census hierarchy, so the populations can
    be added up without counting anybody twice.

    Geonames are points, so one cannot be tested for containment in another
    directly - and comparing every pair would answer the wrong question
    anyway. The census geography already holds the answer: each row knows the
    subdivision its point falls in and the dissemination area within that, and
    those two levels nest by construction. A row that *names* its subdivision
    sits at the top of its nest; a row reporting a dissemination area sits
    inside whichever subdivision holds it.

    Three separate things make a population appear twice, and they are worth
    telling apart:

      nested      the row's dissemination area lies inside a subdivision some
                  other row names. Essondale's 1,021 people are already inside
                  Coquitlam's 155,554.
      duplicate   two geonames describe the same geography. Eight subdivisions
                  are named twice - "Abbotsford" the City and "Abbotsford" the
                  Community are one place listed under two feature types - and
                  294 dissemination areas contain several geonames apiece.
      neither     the row is alone on its geography and nothing contains it.

    `is_primary` is TRUE for exactly one row per distinct geography and never
    for a nested one, so totalling `place_population` across the primary rows
    counts each person once. Where rows tie, the representative is picked by
    `_representative` - stable across runs, but an arbitrary choice when 70
    reserves share one northern dissemination area and all report the same 373
    people. `geo_shared_with` exists to make that arbitrariness visible: a
    primary row with a non-zero count speaks for its geography, it does not
    own it.
    """
    for row in results:
        basis = row["place_population_basis"]
        if basis in ("municipal", "csd"):
            row["geo_level"], row["geo_uid"] = "csd", row["csd_uid"]
        elif basis == "da":
            row["geo_level"], row["geo_uid"] = "da", row["da_uid"]
        else:
            row["geo_level"], row["geo_uid"] = "", ""

    # The subdivisions some row actually names, and the row that names each
    # best - that row is the parent every geoname inside it reports to.
    namers = {}
    for row in results:
        if row["geo_level"] == "csd":
            namers.setdefault(row["geo_uid"], []).append(row)
    parents = {uid: min(g, key=_representative) for uid, g in namers.items()}

    for row in results:
        # Only dissemination-area rows can be nested. A subdivision is never
        # inside another subdivision: an Indian reserve is not part of the
        # municipality it adjoins, and the census treats the two as siblings.
        parent = parents.get(row["csd_uid"]) if row["geo_level"] == "da" else None
        row["is_nested"] = "TRUE" if parent is not None else "FALSE"
        row["parent_geoname_id"] = parent["geoname_id"] if parent else ""
        row["parent_name"] = parent["bc_geographic_name"] if parent else ""

    shared = {}
    for row in results:
        if row["geo_uid"]:
            shared[row["geo_uid"]] = shared.get(row["geo_uid"], 0) + 1

    groups = {}
    for row in results:
        if row["geo_uid"] and row["is_nested"] == "FALSE":
            groups.setdefault(row["geo_uid"], []).append(row)
    winners = {id(min(g, key=_representative)) for g in groups.values()}

    for row in results:
        row["is_primary"] = "TRUE" if id(row) in winners else "FALSE"
        row["geo_shared_with"] = (shared[row["geo_uid"]] - 1
                                  if row["geo_uid"] else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--geonames", default=os.path.join(ROOT, "Geonames.csv"))
    ap.add_argument("--tolerance", type=float, default=2000.0,
                    help="metres within which a point that lands in no polygon "
                         "(typically over water) still adopts the nearest one")
    ap.add_argument("--estimate-year", default=DEFAULT_ESTIMATE_YEAR,
                    help="year of the BC Stats municipal estimate to report "
                         "as place_population (default %(default)s)")
    ap.add_argument("--no-estimates", action="store_true",
                    help="ignore the BC Stats workbook and use census counts "
                         "for municipalities too")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()

    geonames = list(read_geonames(args.geonames))
    points = read_points(POINTS)
    census = read_census(CENSUS)
    estimates = {} if args.no_estimates else read_estimates(ESTIMATES)
    latest_year = max((y for r in estimates.values() for y in r["counts"]),
                      default="")
    if estimates and not any(args.estimate_year in r["counts"]
                             for r in estimates.values()):
        raise SystemExit(f"no municipal estimates for {args.estimate_year}; "
                         f"the workbook covers up to {latest_year}")

    def bc_only(attrs):
        return str(attrs.get("PRUID")) == BC_PRUID

    for path in (DA_ZIP, CSD_ZIP):
        if not os.path.exists(path):
            raise SystemExit(f"missing {path}; run 03_fetch_boundaries.py first")
    print("reading boundaries ...", file=sys.stderr)
    das = read_polygons_from_zip(DA_ZIP, where=bc_only)
    csds = read_polygons_from_zip(CSD_ZIP, where=bc_only)
    if not das or not csds:
        raise SystemExit("no BC polygons in a boundary file")
    print(f"  {len(das)} DAs, {len(csds)} CSDs", file=sys.stderr)

    proj = statcan_lambert()
    da_index, csd_index = PolygonIndex(das), PolygonIndex(csds)

    # Normalised CSD name -> polygons, for the name-corroborated tier below.
    # Several names repeat across the province, which is exactly why every
    # lookup through this index is still gated on distance.
    csd_by_name = {}
    for p_ in csds:
        csd_by_name.setdefault(norm_csd(p_["attrs"].get("CSDNAME")), []).append(p_)
    csd_by_name.pop("", None)

    def pop_of(dguid):
        row = census.get(dguid)
        if not row:
            return None, "not in the census extract"
        raw = row.get("population")
        if raw in (None, ""):
            return None, "population suppressed or unavailable"
        return int(raw), ""

    def locate(x, y, index, polys, area_key):
        """(polygon, method, distance) - containment, else nearest within
        tolerance. Both layers tile BC, so 'nearest' means the point sits in
        water just off the boundary."""
        hits = index.query(x, y)
        if hits:
            # Nesting should not occur in a tiling layer, but a point exactly
            # on a shared edge can register in both; prefer the smaller.
            poly = min(hits, key=lambda p: p["attrs"].get(area_key) or 0.0)
            return poly, "contains", 0.0, len(hits)
        d, poly = nearest_polygon(x, y, polys)
        if poly is not None and d <= args.tolerance:
            return poly, "nearest", d, 0
        return None, "none", (d if poly is not None else None), 0

    results = []
    stats = {"municipal_basis": 0, "csd_basis": 0, "da_basis": 0,
             "no_population": 0, "no_point": 0}
    methods = {"contains": 0, "nearest": 0, "none": 0}
    csd_methods = {"contains": 0, "nearest": 0, "nearest-name": 0, "none": 0}
    claimed_csds = set()
    claimed_munis = set()

    for g in geonames:
        out = {c: "" for c in COLUMNS}
        out.update(g)
        rec = points.get(g["geoname_id"]) or {}
        out["bcgn_name"] = rec.get("api_name") or ""
        out["bcgn_feature_type"] = rec.get("feature_type") or ""

        if rec.get("status") != "ok":
            out["place_population_basis"] = "none"
            out["note"] = (f"BCGNWS: {rec.get('status')}" if rec
                           else "no BCGNWS record fetched")
            stats["no_point"] += 1
            results.append(out)
            continue

        out["lon"], out["lat"] = rec["lon"], rec["lat"]
        x, y = proj.forward(rec["lon"], rec["lat"])
        notes = []

        da, da_method, da_dist, _ = locate(x, y, da_index, das, "LANDAREA")
        csd, csd_method, csd_dist, csd_hits = locate(x, y, csd_index, csds,
                                                     "LANDAREA")
        methods[da_method] += 1

        # BCGN publishes one representative point per name, and for a small
        # reserve or village it often sits just outside that place's own
        # boundary - and therefore inside the regional district wrapped around
        # it. Reporting the regional district's dissemination area there would
        # describe the countryside next door instead of the reserve. When a
        # same-named subdivision lies within tolerance, take it: the name only
        # corroborates a polygon geometry has already placed within metres of
        # the point, and that distance gate is what keeps the 318-820 km
        # homonyms from ever being considered.
        names = {norm(g["bc_geographic_name"]), norm(rec.get("api_name"))} - {""}
        if csd is None or norm_csd(csd["attrs"].get("CSDNAME")) not in names:
            best_d, best_p = float("inf"), None
            for cand in (p for n in names for p in csd_by_name.get(n, ())):
                d = ring_distance(x, y, cand, best_d)
                if d < best_d:
                    best_d, best_p = d, cand
            if best_p is not None and best_d <= args.tolerance:
                inside = csd["attrs"].get("CSDNAME") if csd is not None else None
                csd, csd_method, csd_dist, csd_hits = (
                    best_p, "nearest-name", best_d, 0)
                notes.append(
                    f"the point lies {best_d:.0f} m outside the same-named "
                    f"census subdivision"
                    + (f", inside {inside}" if inside else "")
                    + "; the same-named one was taken")
        if csd_hits > 1:
            notes.append(f"point lies on a boundary shared by {csd_hits} "
                         "census subdivisions; the smaller was taken")

        da_pop = csd_pop = None
        if da is not None:
            out["da_uid"] = da["attrs"].get("DAUID") or ""
            out["da_distance_m"] = round(da_dist, 1) if da_dist is not None else ""
            da_pop, note = pop_of(da["attrs"].get("DGUID"))
            out["da_population"] = "" if da_pop is None else da_pop
            if note:
                notes.append(f"dissemination area {note}")
        out["da_match"] = da_method

        if csd is not None:
            a = csd["attrs"]
            out["csd_uid"] = a.get("CSDUID") or ""
            out["csd_name"] = a.get("CSDNAME") or ""
            out["csd_type"] = CSD_TYPES.get(a.get("CSDTYPE"), a.get("CSDTYPE") or "")
            out["csd_distance_m"] = round(csd_dist, 1) if csd_dist is not None else ""
            csd_pop, note = pop_of(a.get("DGUID"))
            out["csd_population"] = "" if csd_pop is None else csd_pop
            if note:
                notes.append(f"census subdivision {note}")
            claimed_csds.add(a.get("CSDUID"))
        out["csd_match"] = csd_method
        csd_methods[csd_method] += 1

        # BC Stats' estimate is attached whenever the containing subdivision is
        # an incorporated municipality, even on rows that will report a
        # dissemination area: a neighbourhood inside Vancouver is not Vancouver,
        # but knowing which municipality holds it is worth a column.
        est = estimates.get(out["csd_uid"]) if out["csd_uid"] else None
        muni_pop = None
        if est is not None:
            muni_pop = est["counts"].get(args.estimate_year)
            out["muni_name"] = est["name"]
            out["muni_type"] = CSD_TYPES.get(est["area_type"], est["area_type"])
            out["muni_population"] = "" if muni_pop is None else muni_pop
            out["muni_population_year"] = ("" if muni_pop is None
                                            else args.estimate_year)
            if latest_year in est["counts"]:
                out["muni_population_latest"] = est["counts"][latest_year]
                out["muni_latest_year"] = latest_year

        # Names corroborate, never select. Either spelling of the geoname may
        # agree - the sheet and the BCGN API do not always use the same one.
        agrees = False
        if csd is not None:
            target = norm_csd(csd["attrs"].get("CSDNAME"))
            agrees = bool(target) and target in {
                norm(g["bc_geographic_name"]), norm(rec.get("api_name"))}
        out["name_agrees_with_csd"] = "yes" if agrees else "no"

        # An incorporated municipality is its census subdivision even when the
        # two spell the name differently, provided containment - not a name -
        # chose the polygon.
        by_type = (not agrees and csd is not None and csd_method == "contains"
                   and g["geoname_type"].strip().lower() in MUNICIPAL_GEONAME_TYPES
                   and csd["attrs"].get("CSDTYPE") in MUNICIPAL_CSD_TYPES)

        names_the_csd = agrees or by_type

        if names_the_csd and muni_pop is not None:
            # The geoname is an incorporated municipality, so the province's
            # own estimate for it replaces the census count entirely.
            out["place_population"] = muni_pop
            out["place_population_basis"] = "municipal"
            out["place_population_source"] = (
                f"BC Stats population estimate, July 1 {args.estimate_year}")
            out["place_population_confidence"] = (
                "high" if csd_method == "contains" else "medium")
            notes.append(
                f"this is the population of the municipality of "
                f"{est['name']} itself, as estimated by BC Stats for "
                f"{args.estimate_year}"
                + (f" (the 2021 census counted {csd_pop:,})"
                   if csd_pop is not None else ""))
            claimed_munis.add(out["csd_uid"])
            stats["municipal_basis"] += 1
        elif names_the_csd and csd_pop is not None:
            out["place_population"] = csd_pop
            out["place_population_basis"] = "csd"
            out["place_population_source"] = (
                "2021 Census, census subdivision")
            out["place_population_confidence"] = (
                "high" if csd_method == "contains" else "medium")
            if by_type:
                notes.append(
                    f"the geoname is an incorporated {g['geoname_type'].lower()} "
                    f"lying inside census subdivision {out['csd_name']}, so "
                    f"this is the population of the municipality itself "
                    f"(the two spell the name differently)")
            else:
                notes.append(f"the geoname names its containing census "
                             f"subdivision, so this is the population of "
                             f"{out['csd_name']} itself")
            stats["csd_basis"] += 1
        elif da_pop is not None:
            out["place_population"] = da_pop
            out["place_population_basis"] = "da"
            out["place_population_source"] = (
                "2021 Census, dissemination area")
            out["place_population_confidence"] = (
                "high" if da_method == "contains" else "medium")
            notes.append("no census subdivision carries this name, so this is "
                         "the population of the surrounding dissemination "
                         "area, NOT of the named place"
                         + (f" (it lies within the municipality of "
                            f"{est['name']})" if est is not None else ""))
            stats["da_basis"] += 1
        else:
            out["place_population_basis"] = "none"
            notes.append("no population available for this point")
            stats["no_population"] += 1

        if "nearest" in (da_method, csd_method):
            notes.append("point falls outside every boundary - typically over "
                         "water - and adopted the nearest within "
                         f"{args.tolerance:.0f} m")
        out["note"] = "; ".join(notes)
        results.append(out)

    # Needs every row in hand: whether a place is nested depends on whether
    # any *other* geoname names the subdivision around it.
    mark_nesting(results)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(results)

    # The coverage gap from the census side: subdivisions no geoname landed in.
    with open(UNCLAIMED, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["csd_uid", "csd_name", "csd_type", "population_2021"])
        for p in sorted(csds, key=lambda q: q["attrs"].get("CSDNAME") or ""):
            a = p["attrs"]
            if a.get("CSDUID") in claimed_csds:
                continue
            pop, _ = pop_of(a.get("DGUID"))
            w.writerow([a.get("CSDUID"), a.get("CSDNAME"),
                        CSD_TYPES.get(a.get("CSDTYPE"), a.get("CSDTYPE") or ""),
                        "" if pop is None else pop])

    total = len(results)
    print(f"\n{total} geoname rows", file=sys.stderr)
    print("  DA  match: " + "  ".join(
        f"{k}={methods[k]}" for k in ("contains", "nearest", "none")),
        file=sys.stderr)
    print("  CSD match: " + "  ".join(
        f"{k}={csd_methods[k]}"
        for k in ("contains", "nearest", "nearest-name", "none")),
        file=sys.stderr)
    for k in ("municipal_basis", "csd_basis", "da_basis",
              "no_population", "no_point"):
        print(f"  {k:14} {stats[k]:5}  ({stats[k]/total:5.1%})", file=sys.stderr)
    with_pop = sum(1 for r in results if r["place_population"] != "")
    print(f"\n  population attached: {with_pop} ({with_pop/total:.1%})",
          file=sys.stderr)
    print(f"  census subdivisions claimed: {len(claimed_csds)} of {len(csds)}",
          file=sys.stderr)
    if estimates:
        print(f"  incorporated municipalities reported: "
              f"{len(claimed_munis)} of {len(estimates)}", file=sys.stderr)

    primary = [r for r in results if r["is_primary"] == "TRUE"]
    nested = sum(1 for r in results if r["is_nested"] == "TRUE")
    placed = sum(1 for r in results if r["geo_uid"])
    print(f"\n  primary rows: {len(primary)}  (nested in another place: "
          f"{nested}, duplicate geography: {placed - len(primary) - nested})",
          file=sys.stderr)
    print("  sum over primary rows: "
          f"{sum(int(r['place_population'] or 0) for r in primary):,}"
          "  (BC 2021: census 5,000,879, BC Stats 5,214,805)",
          file=sys.stderr)
    print(f"\n-> {args.out}\n-> {UNCLAIMED}", file=sys.stderr)


if __name__ == "__main__":
    main()
