#!/usr/bin/env python3
"""Step 3b - download BC's regional districts from the BC Data Catalogue.

The service-area selector needs a top level: something a contractor already
knows the name of, that covers the province without gaps or overlaps, and that
nobody in this repository invented. That is the regional district, and the
province publishes it.

Two DataBC layers are needed, because one alone does not cover BC:

  ABMS_REGIONAL_DISTRICTS_SP   27 regional districts + the Stikine Region,
                               the unincorporated northwest that belongs to no
                               district but is administered as if it were one.
  ABMS_MUNICIPALITIES_SP       the Northern Rockies Regional Municipality,
                               which absorbed its own regional district in 2009
                               and so is a municipality that does a district's
                               job. Without it there is an 86,000 km2 hole
                               around Fort Nelson.

29 areas, which is exactly Statistics Canada's 29 BC census divisions - the
correspondence step 6 relies on and checks.

Both come from the same WFS endpoint as GeoJSON in EPSG:4326, and the whole
province is one request of about 19 MB, so there is no paging and no
shapefile to unzip.

    python3 03b_fetch_districts.py [--out data/regional_districts.geojson]

`--check` re-reads whatever is already on disk and prints it instead of
fetching, which is the quick way to see what the pipeline is working from.
"""

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request

from lib.tls import make_context

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = os.path.join(HERE, "data", "regional_districts.geojson")

WFS = "https://openmaps.gov.bc.ca/geo/pub/{layer}/ows"

DISTRICTS = "WHSE_LEGAL_ADMIN_BOUNDARIES.ABMS_REGIONAL_DISTRICTS_SP"
MUNICIPALITIES = "WHSE_LEGAL_ADMIN_BOUNDARIES.ABMS_MUNICIPALITIES_SP"

# Only what the pipeline reads. Asking for the full attribute set would carry
# order-in-council numbers and image URLs through every rebuild.
PROPS = ("LGL_ADMIN_AREA_ID,ADMIN_AREA_NAME,ADMIN_AREA_ABBREVIATION,"
         "ADMIN_AREA_GROUP_NAME,FEATURE_AREA_SQM,SHAPE")

# One municipality, by the abbreviation DataBC gives it.
NORTHERN_ROCKIES = "NRRM"

EXPECTED = 29

USER_AGENT = "CleanBC-geoname-population/1.0"


def wfs_geojson(layer, cql=None, timeout=600):
    """One GetFeature call, returned as a parsed FeatureCollection.

    srsName is passed explicitly: the server's default for EPSG:4326 is the
    urn form, which some clients read as latitude-first. Naming it gets
    longitude-first coordinates, which is what GeoJSON means.
    """
    params = {
        "service": "WFS", "version": "2.0.0", "request": "GetFeature",
        "typeName": "pub:" + layer,
        "outputFormat": "application/json",
        "srsName": "EPSG:4326",
        "propertyName": PROPS,
    }
    if cql:
        params["CQL_FILTER"] = cql
    url = WFS.format(layer=layer) + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    print(f"  GET {layer}" + (f"  [{cql}]" if cql else ""), file=sys.stderr)
    with urllib.request.urlopen(req, timeout=timeout,
                                context=make_context()) as r:
        raw = r.read()
    doc = json.loads(raw.decode("utf-8"))
    if doc.get("type") != "FeatureCollection":
        raise SystemExit(f"{layer}: expected a FeatureCollection, got "
                         f"{doc.get('type')!r} - {raw[:300]!r}")
    print(f"    {len(doc['features'])} features, {len(raw)/1e6:.1f} MB",
          file=sys.stderr)
    return doc


def short_name(official):
    """The half of the official name a person says out loud.

    "Regional District of Bulkley-Nechako" and "Cariboo Regional District" are
    the same kind of thing named two ways, and a picker that lists both in full
    sorts every "Regional District of ..." under R. Stripping the boilerplate
    is what makes an alphabetical list usable.
    """
    s = official.strip()
    for prefix in ("Regional District of ",):
        if s.startswith(prefix):
            s = s[len(prefix):]
    for suffix in (" Regional District", " Regional Municipality",
                   " (Unincorporated)"):
        if s.endswith(suffix):
            s = s[:-len(suffix)]
    return s.strip()


def slug(s):
    out = []
    for ch in s.lower():
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != "-":
            out.append("-")
    return "".join(out).strip("-")


def bbox_of(geom):
    coords = geom["coordinates"]
    groups = [coords] if geom["type"] == "Polygon" else coords
    xs, ys = [], []
    for poly in groups:
        for ring in poly:
            for pt in ring:
                xs.append(pt[0])
                ys.append(pt[1])
    return [round(min(xs), 6), round(min(ys), 6),
            round(max(xs), 6), round(max(ys), 6)]


def build(timeout=600):
    rds = wfs_geojson(DISTRICTS, timeout=timeout)
    nr = wfs_geojson(MUNICIPALITIES,
                     cql=f"ADMIN_AREA_ABBREVIATION='{NORTHERN_ROCKIES}'",
                     timeout=timeout)
    if len(nr["features"]) != 1:
        raise SystemExit(f"expected one {NORTHERN_ROCKIES}, got "
                         f"{len(nr['features'])}")

    feats = []
    for f in rds["features"] + nr["features"]:
        p = f["properties"]
        official = p["ADMIN_AREA_NAME"]
        label = short_name(official)
        feats.append({
            "type": "Feature",
            "properties": {
                "key": slug(label),
                "label": label,
                "official": official,
                "abbr": p["ADMIN_AREA_ABBREVIATION"],
                "admin_area_id": p["LGL_ADMIN_AREA_ID"],
                "area_km2": round((p.get("FEATURE_AREA_SQM") or 0) / 1e6),
                "source_layer": (MUNICIPALITIES if f in nr["features"]
                                 else DISTRICTS),
                "bbox": bbox_of(f["geometry"]),
            },
            "geometry": f["geometry"],
        })

    feats.sort(key=lambda f: f["properties"]["label"].lower())
    keys = [f["properties"]["key"] for f in feats]
    if len(set(keys)) != len(keys):
        raise SystemExit("two districts slugged to the same key: " + str(keys))
    if len(feats) != EXPECTED:
        raise SystemExit(f"expected {EXPECTED} areas, got {len(feats)}")
    return {
        "type": "FeatureCollection",
        "crs": {"type": "name",
                "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "source": "BC Data Catalogue (DataBC), openmaps.gov.bc.ca WFS",
        "layers": [DISTRICTS, MUNICIPALITIES],
        "licence": "Open Government Licence - British Columbia",
        "features": feats,
    }


def describe(doc):
    fs = doc["features"]
    print(f"{len(fs)} areas from {', '.join(doc.get('layers', []))}")
    for f in fs:
        p = f["properties"]
        print(f"  {p['key']:26s} {p['label']:26s} {p['abbr']:15s} "
              f"{p['area_km2']:>7,} km2  {f['geometry']['type']}")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--force", action="store_true",
                    help="re-download even if the file is already there")
    ap.add_argument("--check", action="store_true",
                    help="describe the file on disk; fetch nothing")
    ap.add_argument("--timeout", type=int, default=600)
    args = ap.parse_args(argv)

    if args.check:
        if not os.path.exists(args.out):
            raise SystemExit(f"{args.out} not found - run without --check first")
        with open(args.out, encoding="utf-8") as f:
            describe(json.load(f))
        return 0

    if os.path.exists(args.out) and not args.force:
        print(f"already present: {args.out} "
              f"({os.path.getsize(args.out)/1e6:.1f} MB)", file=sys.stderr)
        with open(args.out, encoding="utf-8") as f:
            describe(json.load(f))
        return 0

    doc = build(timeout=args.timeout)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    tmp = args.out + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, args.out)
    print(f"-> {args.out} ({os.path.getsize(args.out)/1e6:.1f} MB)",
          file=sys.stderr)
    describe(doc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
