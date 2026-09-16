#!/usr/bin/env python3
"""Step 3c - download BC's provincial boundary from the BC Data Catalogue.

Both webapp maps put every point on top of a generic basemap, with nothing
marking where the province itself ends. This fetches that outline: one
DataBC layer, one polygon, the whole province in a single request - small
enough that, unlike the regional districts fetch, the result travels with
the repo and the webapp reads it directly.

    python3 03c_fetch_province.py [--out out/bc_boundary.geojson]

`--check` re-reads whatever is already on disk and prints it instead of
fetching, which is the quick way to see what the webapp is working from.
"""

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request

from lib.tls import make_context

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = os.path.join(HERE, "out", "bc_boundary.geojson")

WFS = "https://openmaps.gov.bc.ca/geo/pub/{layer}/ows"

PROVINCE = "WHSE_LEGAL_ADMIN_BOUNDARIES.ABMS_PROVINCE_SP"

PROPS = "ADMIN_AREA_NAME,SHAPE"

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
    print(f"    {len(doc['features'])} feature(s), {len(raw)/1e6:.1f} MB",
          file=sys.stderr)
    return doc


def build(timeout=600):
    doc = wfs_geojson(PROVINCE, timeout=timeout)
    if len(doc["features"]) != 1:
        raise SystemExit(f"expected one province polygon, got "
                         f"{len(doc['features'])}")
    f = doc["features"][0]
    return {
        "type": "FeatureCollection",
        "crs": {"type": "name",
                "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "source": "BC Data Catalogue (DataBC), openmaps.gov.bc.ca WFS",
        "layers": [PROVINCE],
        "licence": "Open Government Licence - British Columbia",
        "features": [{
            "type": "Feature",
            "properties": {"name": f["properties"]["ADMIN_AREA_NAME"]},
            "geometry": f["geometry"],
        }],
    }


def describe(doc):
    fs = doc["features"]
    print(f"{len(fs)} feature(s) from {', '.join(doc.get('layers', []))}")
    for f in fs:
        print(f"  {f['properties'].get('name')}  {f['geometry']['type']}")


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
