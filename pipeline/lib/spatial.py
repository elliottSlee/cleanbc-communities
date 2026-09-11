"""Point-in-polygon containment with a bbox grid index, pure stdlib."""

import json


def point_in_rings(x, y, rings):
    """Even-odd ray casting across every ring.

    Shapefile polygons encode holes as opposite-wound interior rings; testing
    all rings with a single even-odd parity count handles them for free - a
    point inside a hole crosses both the outer ring and the hole ring.
    """
    inside = False
    for ring in rings:
        n = len(ring)
        if n < 3:
            continue
        x1, y1 = ring[-1]
        for i in range(n):
            x2, y2 = ring[i]
            if (y1 > y) != (y2 > y):
                # x of the edge at height y
                xi = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
                if x < xi:
                    inside = not inside
            x1, y1 = x2, y2
    return inside


class PolygonIndex:
    """Uniform-grid bbox index over polygons, for repeated point queries."""

    def __init__(self, polygons, cells=64):
        self.polygons = polygons
        self.cells = max(1, cells)
        xs0 = min(p["bbox"][0] for p in polygons)
        ys0 = min(p["bbox"][1] for p in polygons)
        xs1 = max(p["bbox"][2] for p in polygons)
        ys1 = max(p["bbox"][3] for p in polygons)
        self.x0, self.y0 = xs0, ys0
        self.dx = (xs1 - xs0) / self.cells or 1.0
        self.dy = (ys1 - ys0) / self.cells or 1.0

        self.grid = {}
        for idx, p in enumerate(polygons):
            bx0, by0, bx1, by1 = p["bbox"]
            for cx in range(self._cx(bx0), self._cx(bx1) + 1):
                for cy in range(self._cy(by0), self._cy(by1) + 1):
                    self.grid.setdefault((cx, cy), []).append(idx)

    def _cx(self, x):
        return min(self.cells, max(0, int((x - self.x0) / self.dx)))

    def _cy(self, y):
        return min(self.cells, max(0, int((y - self.y0) / self.dy)))

    def query(self, x, y):
        """Return every polygon whose interior contains (x, y)."""
        hits = []
        for idx in self.grid.get((self._cx(x), self._cy(y)), ()):
            p = self.polygons[idx]
            bx0, by0, bx1, by1 = p["bbox"]
            if not (bx0 <= x <= bx1 and by0 <= y <= by1):
                continue
            if point_in_rings(x, y, p["rings"]):
                hits.append(p)
        return hits


def load_geojson_polygons(path):
    """Read a GeoJSON FeatureCollection of (Multi)Polygons in the same shape
    as shapefile_lite.read_polygons, so either source feeds PolygonIndex."""
    with open(path, encoding="utf-8") as f:
        gj = json.load(f)
    feats = gj["features"] if gj.get("type") == "FeatureCollection" else [gj]
    out = []
    for feat in feats:
        geom = feat.get("geometry") or {}
        gtype = geom.get("type")
        if gtype == "Polygon":
            groups = [geom["coordinates"]]
        elif gtype == "MultiPolygon":
            groups = geom["coordinates"]
        else:
            continue
        rings = [[(pt[0], pt[1]) for pt in ring]
                 for poly in groups for ring in poly]
        if not rings:
            continue
        xs = [p[0] for r in rings for p in r]
        ys = [p[1] for r in rings for p in r]
        out.append({"attrs": feat.get("properties") or {},
                    "bbox": (min(xs), min(ys), max(xs), max(ys)),
                    "rings": rings})
    return out
