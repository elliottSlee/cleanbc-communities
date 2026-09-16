#!/usr/bin/env python3
"""Step 3d - download BC's incorporated municipalities from the BC Data
Catalogue: "Municipalities - Legally Defined Administrative Areas of BC".

The join (`04_join.py`) already knows which of the 162 municipalities a
geoname sits inside, but it works out from the *census subdivision*
boundary - close to the legal one, not the same file. `07_exclude_nested.py`
needs the province's own legal boundary to decide whether a shortlisted
place - James Bay, say - lies inside a municipality it is not itself, so
this fetches that boundary directly rather than reusing the census proxy.

Same WFS endpoint and layer `03b_fetch_districts.py` already uses to pick out
the Northern Rockies Regional Municipality; this asks for all of it.

    python3 03d_fetch_municipalities.py [--out data/municipalities.geojson]

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
DEFAULT_OUT = os.path.join(HERE, "data", "municipalities.geojson")

WFS = "https://openmaps.gov.bc.ca/geo/pub/{layer}/ows"

MUNICIPALITIES = "WHSE_LEGAL_ADMIN_BOUNDARIES.ABMS_MUNICIPALITIES_SP"

# Only what the pipeline reads. Asking for the full attribute set would carry
# order-in-council numbers and image URLs through every rebuild.
PROPS = ("LGL_ADMIN_AREA_ID,ADMIN_AREA_NAME,ADMIN_AREA_ABBREVIATION,"
         "ADMIN_AREA_GROUP_NAME,FEATURE_AREA_SQM,SHAPE")

# 160, not the 162 BC Stats reports estimates for: this layer is strictly
# municipalities incorporated under the Local Government Act, and the two
# shishalh Nation government districts are Indian government districts, not
# municipalities, so they never appear here. See pipeline/README.md.
EXPECTED = 160

USER_AGENT = "CleanBC-geoname-population/1.0"


def wfs_geojson(layer, timeout=600):
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
    url = WFS.format(layer=layer) + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    print(f"  GET {layer}", file=sys.stderr)
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
    doc = wfs_geojson(MUNICIPALITIES, timeout=timeout)

    feats = []
    for f in doc["features"]:
        p = f["properties"]
        official = p["ADMIN_AREA_NAME"]
        feats.append({
            "type": "Feature",
            "properties": {
                "key": slug(p["ADMIN_AREA_ABBREVIATION"] or official),
                "official": official,
                "abbr": p["ADMIN_AREA_ABBREVIATION"],
                "regional_district": p.get("ADMIN_AREA_GROUP_NAME") or "",
                "admin_area_id": p["LGL_ADMIN_AREA_ID"],
                "area_km2": round((p.get("FEATURE_AREA_SQM") or 0) / 1e6),
                "bbox": bbox_of(f["geometry"]),
            },
            "geometry": f["geometry"],
        })

    feats.sort(key=lambda f: f["properties"]["official"].lower())
    keys = [f["properties"]["key"] for f in feats]
    if len(set(keys)) != len(keys):
        raise SystemExit("two municipalities slugged to the same key: "
                         + str(keys))
    if len(feats) != EXPECTED:
        raise SystemExit(f"expected {EXPECTED} municipalities, got "
                         f"{len(feats)} - update EXPECTED if the province "
                         f"incorporated or dissolved one")
    return {
        "type": "FeatureCollection",
        "crs": {"type": "name",
                "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "source": "BC Data Catalogue (DataBC), openmaps.gov.bc.ca WFS",
        "layers": [MUNICIPALITIES],
        "licence": "Open Government Licence - British Columbia",
        "features": feats,
    }


def describe(doc):
    fs = doc["features"]
    print(f"{len(fs)} municipalities from {', '.join(doc.get('layers', []))}")
    for f in fs:
        p = f["properties"]
        print(f"  {p['key']:26s} {p['official']:42s} "
              f"{p['area_km2']:>6,} km2  {f['geometry']['type']}")


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
