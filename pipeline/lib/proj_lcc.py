"""Lambert Conformal Conic <-> geographic, pure stdlib.

Exists so the spatial join can read Statistics Canada boundary files in their
native projection (EPSG:3347, "NAD83 / Statistics Canada Lambert") without
pulling in pyproj/GDAL. Formulas: Snyder, *Map Projections - A Working Manual*,
USGS PP 1395, pp. 107-109 (ellipsoidal LCC, two standard parallels).
"""

import math

# GRS80 / NAD83
GRS80_A = 6378137.0
GRS80_F = 1.0 / 298.257222101
GRS80_E2 = 2 * GRS80_F - GRS80_F ** 2
GRS80_E = math.sqrt(GRS80_E2)


class LambertConformalConic:
    """Two-standard-parallel ellipsoidal LCC."""

    def __init__(self, lat_1, lat_2, lat_0, lon_0, x_0=0.0, y_0=0.0,
                 a=GRS80_A, e=GRS80_E):
        self.a, self.e = a, e
        self.lon_0 = math.radians(lon_0)
        self.x_0, self.y_0 = x_0, y_0

        p1, p2, p0 = map(math.radians, (lat_1, lat_2, lat_0))
        t1, t2, t0 = self._t(p1), self._t(p2), self._t(p0)
        m1, m2 = self._m(p1), self._m(p2)

        if abs(p1 - p2) < 1e-12:            # tangent case
            self.n = math.sin(p1)
        else:
            self.n = (math.log(m1) - math.log(m2)) / (math.log(t1) - math.log(t2))
        self.F = m1 / (self.n * t1 ** self.n)
        self.rho_0 = a * self.F * t0 ** self.n

    def _t(self, phi):
        es = self.e * math.sin(phi)
        return (math.tan(math.pi / 4 - phi / 2)
                / ((1 - es) / (1 + es)) ** (self.e / 2))

    def _m(self, phi):
        return math.cos(phi) / math.sqrt(1 - (self.e * math.sin(phi)) ** 2)

    def forward(self, lon, lat):
        """(lon, lat) in degrees -> (x, y) in metres."""
        phi, lam = math.radians(lat), math.radians(lon)
        if abs(abs(phi) - math.pi / 2) < 1e-12 and phi * self.n > 0:
            rho = 0.0                        # pole on the positive side
        else:
            rho = self.a * self.F * self._t(phi) ** self.n
        theta = self.n * self._wrap(lam - self.lon_0)
        return (self.x_0 + rho * math.sin(theta),
                self.y_0 + self.rho_0 - rho * math.cos(theta))

    def inverse(self, x, y):
        """(x, y) in metres -> (lon, lat) in degrees."""
        dx, dy = x - self.x_0, self.rho_0 - (y - self.y_0)
        sign = 1.0 if self.n >= 0 else -1.0
        rho = sign * math.hypot(dx, dy)
        theta = math.atan2(sign * dx, sign * dy)
        lam = theta / self.n + self.lon_0

        if rho == 0.0:
            phi = math.copysign(math.pi / 2, self.n)
        else:
            t = (rho / (self.a * self.F)) ** (1.0 / self.n)
            phi = math.pi / 2 - 2 * math.atan(t)
            for _ in range(30):              # Snyder eq. 3-4, iterative
                es = self.e * math.sin(phi)
                nxt = math.pi / 2 - 2 * math.atan(
                    t * ((1 - es) / (1 + es)) ** (self.e / 2))
                if abs(nxt - phi) < 1e-13:
                    phi = nxt
                    break
                phi = nxt
        return math.degrees(self._wrap(lam)), math.degrees(phi)

    @staticmethod
    def _wrap(rad):
        return (rad + math.pi) % (2 * math.pi) - math.pi


def statcan_lambert():
    """EPSG:3347 - the CRS of StatCan census boundary files."""
    return LambertConformalConic(lat_1=49.0, lat_2=77.0, lat_0=63.390675,
                                 lon_0=-91.86666666666666,
                                 x_0=6200000.0, y_0=3000000.0)


# EPSG:4326 passthrough, so callers can treat CRS uniformly.
class Identity:
    def forward(self, lon, lat):
        return lon, lat

    def inverse(self, x, y):
        return x, y


def get_projection(name):
    key = (name or "").strip().lower()
    if key in ("3347", "epsg:3347", "lambert", "statcan"):
        return statcan_lambert()
    if key in ("4326", "epsg:4326", "wgs84", "", "none"):
        return Identity()
    raise ValueError(f"unsupported CRS {name!r}; use 3347 or 4326")
