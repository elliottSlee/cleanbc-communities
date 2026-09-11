#!/usr/bin/env python3
"""Step 1 - resolve each Geonames.csv row to a coordinate via the BCGNWS API.

bcgnws.json in the project root is an OpenAPI *specification*, not data: it
documents this service but contains no geographic names. The spatial
information has to be fetched from the live endpoint it describes, where the
`GeoName ID` column is the `nameId` path parameter.

    GET https://apps.gov.bc.ca/pub/bcgnws/names/{nameId}.json?outputSRS=4326

Results are appended to a JSONL cache so reruns are incremental and the API is
only asked for IDs it has not already answered. Safe to interrupt and restart.

    python3 01_fetch_points.py [--limit N] [--workers N] [--refresh]
"""

import argparse
import csv
import json
import os
import queue
import sys
import threading
import time
import urllib.error
import urllib.request

from lib.tls import make_context

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GEONAMES = os.path.join(ROOT, "Geonames.csv")
CACHE = os.path.join(HERE, "data", "geoname_points.jsonl")

BASE = "https://apps.gov.bc.ca/pub/bcgnws/names/{}.json?outputSRS=4326"
USER_AGENT = "CleanBC-geoname-population/1.0 (+stdlib urllib)"
TIMEOUT = 30
_CTX = None


def read_geonames(path=GEONAMES):
    """Geonames.csv is UTF-8 with a BOM and contains a few stray bytes."""
    with open(path, encoding="utf-8-sig", errors="replace", newline="") as f:
        for row in csv.DictReader(f):
            gid = (row.get("GeoName ID") or "").strip()
            if not gid.isdigit():
                continue
            yield {"geoname_id": gid,
                   "name": (row.get("BC Geographic Name") or "").strip(),
                   "type": (row.get("Type") or "").strip()}


def load_cache(path=CACHE):
    done = {}
    if not os.path.exists(path):
        return done
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue                      # tolerate a torn final line
            done[str(rec["geoname_id"])] = rec
    return done


def fetch_one(gid, retries=4):
    url = BASE.format(gid)
    ctx = _CTX
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "application/json"})
    delay = 1.0
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as r:
                return parse_feature(gid, json.loads(r.read().decode("utf-8")))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {"geoname_id": gid, "status": "not_found"}
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(delay); delay *= 2; continue
            return {"geoname_id": gid, "status": f"http_{e.code}"}
        except Exception as e:                # noqa: BLE001 - network is messy
            if attempt < retries - 1:
                time.sleep(delay); delay *= 2; continue
            return {"geoname_id": gid, "status": f"error:{type(e).__name__}"}
    return {"geoname_id": gid, "status": "error:exhausted"}


def parse_feature(gid, payload):
    feat = payload.get("feature") or {}
    props = feat.get("properties") or {}
    geom = feat.get("geometry") or {}
    coords = geom.get("coordinates") if geom.get("type") == "Point" else None
    if not coords or len(coords) < 2:
        return {"geoname_id": gid, "status": "no_geometry",
                "api_name": props.get("name")}
    return {
        "geoname_id": gid,
        "status": "ok",
        "lon": coords[0],
        "lat": coords[1],
        "api_name": props.get("name"),
        "is_official": props.get("isOfficial"),
        "feature_type": props.get("featureType"),
        "feature_category": props.get("featureCategoryDescription"),
        "relative_location": (props.get("feature") or {}).get("relativeLocation"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="only fetch N new IDs (smoke test)")
    ap.add_argument("--workers", type=int, default=4,
                    help="concurrent requests (default 4; keep it modest)")
    ap.add_argument("--refresh", action="store_true", help="ignore the cache")
    args = ap.parse_args()

    global _CTX
    _CTX = make_context(verbose=True)

    rows = list(read_geonames())
    cache = {} if args.refresh else load_cache()
    todo = [r["geoname_id"] for r in rows if r["geoname_id"] not in cache]
    # De-duplicate while preserving order; a name can repeat in the sheet.
    todo = list(dict.fromkeys(todo))
    if args.limit:
        todo = todo[:args.limit]

    print(f"{len(rows)} geoname rows | {len(cache)} cached | {len(todo)} to fetch",
          file=sys.stderr)
    if not todo:
        print("nothing to do", file=sys.stderr)
        return

    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    q = queue.Queue()
    for gid in todo:
        q.put(gid)
    lock = threading.Lock()
    counts = {"ok": 0, "fail": 0}

    mode = "w" if args.refresh else "a"
    with open(CACHE, mode, encoding="utf-8") as out:
        def worker():
            while True:
                try:
                    gid = q.get_nowait()
                except queue.Empty:
                    return
                rec = fetch_one(gid)
                with lock:
                    out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    out.flush()               # keep the cache resumable
                    counts["ok" if rec["status"] == "ok" else "fail"] += 1
                    n = counts["ok"] + counts["fail"]
                    if n % 50 == 0 or n == len(todo):
                        print(f"  {n}/{len(todo)}  ok={counts['ok']} "
                              f"fail={counts['fail']}", file=sys.stderr)
                time.sleep(0.05)              # be polite to a public service

        threads = [threading.Thread(target=worker, daemon=True)
                   for _ in range(max(1, args.workers))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    print(f"done: ok={counts['ok']} fail={counts['fail']} -> {CACHE}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
