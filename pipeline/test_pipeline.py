#!/usr/bin/env python3
"""Self-contained checks for the geometry and projection code.

The projection and shapefile parsing are hand-rolled to avoid a GDAL/pyproj
dependency, so they are checked against invariants that hold independently of
this implementation. Run with: python3 test_pipeline.py
"""

import math
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.proj_lcc import statcan_lambert, GRS80_A, GRS80_E2   # noqa: E402
from lib.spatial import PolygonIndex, point_in_rings          # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DA_ZIP = os.path.join(HERE, "data", "lda_000b21a_e.zip")
CSD_ZIP = os.path.join(HERE, "data", "lcsd000b21a_e.zip")
CENSUS = os.path.join(HERE, "data", "census_population.csv")
OUTPUT = os.path.join(HERE, "out", "geoname_population.csv")
SHORTLIST = os.path.join(HERE, "out", "geoname_shortlist.csv")
BASINS_CSV = os.path.join(HERE, "out", "geoname_basins.csv")
SERVICE_JSON = os.path.join(HERE, "out", "service_areas.json")
XLSX = os.path.join(os.path.dirname(HERE), "pop_municipal_subprov_areas.xlsx")
ESTIMATES = os.path.join(HERE, "data", "municipal_estimates.csv")


def _load(filename, modname):
    """Import a numbered step module, whose name is not a valid identifier."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        modname, os.path.join(HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestProjection(unittest.TestCase):
    def setUp(self):
        self.p = statcan_lambert()

    def test_origin_maps_to_false_easting_northing(self):
        x, y = self.p.forward(-91.86666666666666, 63.390675)
        self.assertAlmostEqual(x, 6200000.0, places=4)
        self.assertAlmostEqual(y, 3000000.0, places=4)

    def test_round_trip_over_bc(self):
        for lon in (-139.0, -130.0, -125.0, -120.0, -114.0):
            for lat in (48.3, 52.0, 56.0, 60.0):
                X, Y = self.p.forward(lon, lat)
                lo, la = self.p.inverse(X, Y)
                self.assertAlmostEqual(lo, lon, places=9)
                self.assertAlmostEqual(la, lat, places=9)

    def _scale_factor(self, lat):
        d = 1e-4
        x1, y1 = self.p.forward(-120.0, lat)
        x2, y2 = self.p.forward(-120.0 + d, lat)
        phi = math.radians(lat)
        ground = (math.radians(d) * GRS80_A * math.cos(phi)
                  / math.sqrt(1 - GRS80_E2 * math.sin(phi) ** 2))
        return math.hypot(x2 - x1, y2 - y1) / ground

    def test_scale_factor_unity_on_standard_parallels(self):
        # Defining property of a two-parallel LCC: k == 1 at 49N and 77N.
        self.assertAlmostEqual(self._scale_factor(49.0), 1.0, places=7)
        self.assertAlmostEqual(self._scale_factor(77.0), 1.0, places=7)

    def test_scale_factor_shrinks_between_and_grows_outside(self):
        self.assertLess(self._scale_factor(63.0), 1.0)
        self.assertGreater(self._scale_factor(85.0), 1.0)
        self.assertGreater(self._scale_factor(40.0), 1.0)


class TestPointInPolygon(unittest.TestCase):
    def setUp(self):
        outer = [(0, 0), (0, 10), (10, 10), (10, 0), (0, 0)]
        hole = [(4, 4), (6, 4), (6, 6), (4, 6), (4, 4)]
        self.donut = [outer, hole]

    def test_hole_is_not_inside(self):
        self.assertFalse(point_in_rings(5, 5, self.donut))

    def test_ring_between_outer_and_hole_is_inside(self):
        for pt in ((1, 1), (9, 9), (5, 1), (5, 9), (1, 5), (9, 5)):
            self.assertTrue(point_in_rings(*pt, self.donut), pt)

    def test_outside_is_outside(self):
        for pt in ((-1, 5), (11, 5), (5, -1), (5, 11)):
            self.assertFalse(point_in_rings(*pt, self.donut), pt)

    def test_hole_edge(self):
        self.assertTrue(point_in_rings(3.99, 5, self.donut))
        self.assertFalse(point_in_rings(4.01, 5, self.donut))


class TestPolygonIndex(unittest.TestCase):
    def test_index_agrees_with_brute_force(self):
        random.seed(7)
        polys = []
        for i in range(200):
            cx, cy = random.uniform(0, 1000), random.uniform(0, 1000)
            r = random.uniform(5, 40)
            ring = [(cx - r, cy - r), (cx - r, cy + r),
                    (cx + r, cy + r), (cx + r, cy - r), (cx - r, cy - r)]
            polys.append({"attrs": {"id": i},
                          "bbox": (cx - r, cy - r, cx + r, cy + r),
                          "rings": [ring]})
        idx = PolygonIndex(polys)
        for _ in range(3000):
            x, y = random.uniform(-50, 1050), random.uniform(-50, 1050)
            fast = sorted(p["attrs"]["id"] for p in idx.query(x, y))
            slow = sorted(
                p["attrs"]["id"] for p in polys
                if p["bbox"][0] <= x <= p["bbox"][2]
                and p["bbox"][1] <= y <= p["bbox"][3]
                and point_in_rings(x, y, p["rings"]))
            self.assertEqual(fast, slow, (x, y))


def _join():
    return _load("04_join.py", "join_mod")


def _norm():
    return _join().norm


class TestNameNormalisation(unittest.TestCase):
    def setUp(self):
        self.norm = _norm()

    def test_descriptor_stripped_either_side(self):
        # Geonames.csv carries both orders.
        self.assertEqual(self.norm("Queen Charlotte, Village of"),
                         self.norm("Queen Charlotte"))
        self.assertEqual(self.norm("West Kelowna, City of"),
                         self.norm("West Kelowna"))
        self.assertEqual(self.norm("City of Vancouver"), "vancouver")
        self.assertEqual(self.norm("The District of Sooke"), "sooke")

    def test_punctuation_and_accents_folded(self):
        self.assertEqual(self.norm("Grand Haven/Clairmont"),
                         "grand haven clairmont")
        self.assertEqual(self.norm("Laxgalts'ap"), "laxgaltsap")

    def test_apostrophe_variants_agree(self):
        """Typographic and ASCII apostrophes must normalise identically, or a
        name spelled differently in two sources would never join."""
        for pair in (("Nisga\u2019a Village", "Nisga'a Village"),
                     ("Laxgalts\u2019ap", "Laxgalts'ap"),
                     ("T\u2019Sou-ke", "T'Sou-ke")):
            self.assertEqual(self.norm(pair[0]), self.norm(pair[1]), pair)
        self.assertEqual(self.norm("Nisga'a Village"), "nisgaa village")
        self.assertEqual(self.norm("T'Sou-ke"), "tsou ke")

    def test_does_not_eat_real_name_parts(self):
        # "Trust Area" and numbered reserves must survive intact.
        self.assertEqual(self.norm("Saltspring Island Trust Area"),
                         "saltspring island trust area")
        self.assertEqual(self.norm("Telegraph Creek 6A"), "telegraph creek 6a")
        self.assertNotEqual(self.norm("Telegraph Creek 6"),
                            self.norm("Telegraph Creek 6A"))


class TestCsdNameNormalisation(unittest.TestCase):
    """norm_csd() additionally drops the parenthesised type code StatCan
    appends to disambiguate repeated CSD names."""

    def setUp(self):
        self.j = _join()

    def test_type_code_suffix_stripped(self):
        self.assertEqual(self.j.norm_csd("Langley (CY)"), "langley")
        self.assertEqual(self.j.norm_csd("Langley (DM)"), "langley")
        self.assertEqual(self.j.norm_csd("Kent (S-E)"), "kent")

    def test_real_trailing_parentheses_are_not_a_type_code(self):
        # A long parenthetical is part of the name, not a 2-5 char code.
        self.assertEqual(self.j.norm_csd("Squamish (Vancouver)"),
                         "squamish vancouver")

    def test_agrees_with_plain_norm_when_no_suffix(self):
        for name in ("Tofino", "Queen Charlotte", "Telegraph Creek 6A"):
            self.assertEqual(self.j.norm_csd(name), self.j.norm(name), name)


class TestCensusNameSplit(unittest.TestCase):
    """02 must only strip a trailing geography-type descriptor, never an
    ordinary comma that happens to sit in a name."""

    def setUp(self):
        self.split = _load("02_census_pop.py", "census_mod").split_kind

    def test_type_descriptor_stripped(self):
        self.assertEqual(self.split("Hagensborg part A, Designated place (DPL)"),
                         ("Hagensborg part A", "Designated place (DPL)"))

    def test_plain_name_untouched(self):
        # The hierarchical BC product carries bare names; splitting on the
        # last comma regardless would have mangled every one of them.
        for name in ("Elkford", "Greater Vancouver A", "Powell River"):
            self.assertEqual(self.split(name), (name, ""))

    def test_comma_in_name_survives(self):
        self.assertEqual(self.split("Queen Charlotte, Village of"),
                         ("Queen Charlotte, Village of", ""))


class TestSuppressionParsing(unittest.TestCase):
    """A suppressed count and a genuine zero must stay distinguishable: some
    reserves really do have a population of 0."""

    def setUp(self):
        self.parse = _load("02_census_pop.py", "census_mod").parse_count

    def test_zero_is_not_unknown(self):
        self.assertEqual(self.parse("0"), 0)
        self.assertIsNotNone(self.parse("0"))

    def test_suppression_symbols_are_unknown(self):
        for raw in ("x", "F", "..", "...", "", "   "):
            self.assertIsNone(self.parse(raw), raw)

    def test_ordinary_counts(self):
        self.assertEqual(self.parse("662248"), 662248)
        self.assertEqual(self.parse(" 1794 "), 1794)


class TestNearestPolygon(unittest.TestCase):
    """The bbox-bounded search must return exactly what brute force does; its
    early exit is the only thing making the water-point fallback affordable."""

    def setUp(self):
        self.j = _join()

    def test_matches_brute_force(self):
        random.seed(11)
        polys = []
        for i in range(120):
            cx, cy = random.uniform(0, 1000), random.uniform(0, 1000)
            r = random.uniform(5, 40)
            ring = [(cx - r, cy - r), (cx - r, cy + r),
                    (cx + r, cy + r), (cx + r, cy - r), (cx - r, cy - r)]
            polys.append({"attrs": {"id": i},
                          "bbox": (cx - r, cy - r, cx + r, cy + r),
                          "rings": [ring]})
        for _ in range(300):
            x, y = random.uniform(-200, 1200), random.uniform(-200, 1200)
            d, p = self.j.nearest_polygon(x, y, polys)
            best = min(self.j.ring_distance(x, y, q) for q in polys)
            self.assertAlmostEqual(d, best, places=6, msg=(x, y))
            self.assertIsNotNone(p)


def _synthetic_shapefile(n_fields=6):
    """Build a tiny valid .shp/.dbf pair in memory."""
    import struct

    squares, shp_records = [], []
    for i in range(4):
        x0, y0 = i * 10.0, 0.0
        x1, y1 = x0 + 5.0, 5.0
        ring = [(x0, y0), (x0, y1), (x1, y1), (x1, y0), (x0, y0)]
        squares.append((x0, y0, x1, y1))
        body = struct.pack("<i4dii", 5, x0, y0, x1, y1, 1, len(ring))
        body += struct.pack("<i", 0)
        for px, py in ring:
            body += struct.pack("<2d", px, py)
        shp_records.append(body)

    out = bytearray(100)
    struct.pack_into(">i", out, 0, 9994)
    struct.pack_into("<i", out, 28, 1000)
    struct.pack_into("<i", out, 32, 5)
    for k, rec in enumerate(shp_records, start=1):
        out += struct.pack(">ii", k, len(rec) // 2) + rec
    struct.pack_into(">i", out, 24, len(out) // 2)

    names = [f"FIELD{i}" for i in range(n_fields)]
    flen = 8
    record_len = 1 + flen * n_fields
    header_len = 32 + 32 * n_fields + 1          # ... + a ONE byte terminator
    dbf = bytearray(32)
    dbf[0] = 0x03
    struct.pack_into("<iHH", dbf, 4, len(shp_records), header_len, record_len)
    for name in names:
        fd = bytearray(32)
        fd[0:len(name)] = name.encode("ascii")
        fd[11] = ord("C")
        fd[16] = flen
        dbf += fd
    dbf += b"\x0d"
    for i in range(len(shp_records)):
        dbf += b" " + b"".join(f"r{i}f{k}".ljust(flen).encode("ascii")
                               for k in range(n_fields))
    dbf += b"\x1a"
    return bytes(out), bytes(dbf), squares


class TestShapefileReader(unittest.TestCase):
    """Regression guards for the streaming reader.

    The .dbf field-descriptor array ends with a single 0x0D byte. Consuming a
    full 32-byte chunk to detect it over-reads 31 bytes into the first record,
    and a forward-only stream cannot seek back - so every record decodes at
    the wrong offset, the last one runs short and is silently dropped. That
    failure is quiet: it returns *almost* the right answer.
    """

    def test_reads_every_record_with_correct_attributes(self):
        from lib.shapefile_lite import read_polygons
        shp, dbf, squares = _synthetic_shapefile()
        polys = read_polygons(shp, dbf)
        self.assertEqual(len(polys), len(squares))
        for i, p in enumerate(polys):
            self.assertEqual(p["attrs"]["FIELD0"], f"r{i}f0")
            self.assertEqual(p["attrs"]["FIELD5"], f"r{i}f5")
            self.assertEqual(tuple(round(v, 6) for v in p["bbox"]), squares[i])

    def test_header_length_independent_of_field_count(self):
        from lib.shapefile_lite import read_polygons
        for n in (1, 2, 6, 11):
            shp, dbf, squares = _synthetic_shapefile(n_fields=n)
            polys = read_polygons(shp, dbf)
            self.assertEqual(len(polys), len(squares), f"{n} fields")
            self.assertEqual(polys[-1]["attrs"][f"FIELD{n-1}"],
                             f"r{len(squares)-1}f{n-1}", f"{n} fields")

    def test_where_filters_without_changing_geometry(self):
        from lib.shapefile_lite import read_polygons
        shp, dbf, _ = _synthetic_shapefile()
        everything = read_polygons(shp, dbf)
        kept = read_polygons(shp, dbf, where=lambda a: a["FIELD0"] in
                             ("r1f0", "r3f0"))
        self.assertEqual([p["attrs"]["FIELD0"] for p in kept], ["r1f0", "r3f0"])
        # where= must only skip records, never alter the ones it keeps.
        for p in kept:
            match = next(q for q in everything
                         if q["attrs"]["FIELD0"] == p["attrs"]["FIELD0"])
            self.assertEqual(p["rings"], match["rings"])


@unittest.skipUnless(os.path.exists(DA_ZIP) and os.path.exists(CSD_ZIP),
                     "boundary files absent; run 03_fetch_boundaries.py")
class TestBoundaryFiles(unittest.TestCase):
    """The polygon counts are cross-checked against the census file's own
    geography counts. Two independently produced products agreeing is what
    established the reader was neither dropping nor duplicating records."""

    BC = staticmethod(lambda a: str(a.get("PRUID")) == "59")

    def _bc(self, path):
        from lib.shapefile_lite import read_polygons_from_zip
        return read_polygons_from_zip(path, where=self.BC)

    def test_bc_dissemination_area_count(self):
        self.assertEqual(len(self._bc(DA_ZIP)), 7848)

    def test_bc_census_subdivision_count(self):
        self.assertEqual(len(self._bc(CSD_ZIP)), 751)

    @unittest.skipUnless(os.path.exists(CENSUS),
                         "census extract absent; run 02_census_pop.py")
    def test_counts_agree_with_the_census_extract(self):
        import csv as _csv
        levels = {}
        with open(CENSUS, encoding="utf-8", newline="") as f:
            for row in _csv.DictReader(f):
                levels[row["geo_level"]] = levels.get(row["geo_level"], 0) + 1
        self.assertEqual(len(self._bc(DA_ZIP)), levels["Dissemination area"])
        self.assertEqual(len(self._bc(CSD_ZIP)), levels["Census subdivision"])

    def test_identifiers_are_unique(self):
        # One record per geography: multi-part geographies are encoded as
        # several rings inside a single record, not as repeated records, so
        # no population is split across rows the way designated places were.
        for path, key in ((DA_ZIP, "DAUID"), (CSD_ZIP, "CSDUID")):
            uids = [p["attrs"].get(key) for p in self._bc(path)]
            self.assertEqual(len(set(uids)), len(uids), key)

    def test_attributes_are_populated(self):
        for path, keys in ((DA_ZIP, ("DAUID", "DGUID", "PRUID", "LANDAREA")),
                           (CSD_ZIP, ("CSDUID", "DGUID", "CSDNAME", "CSDTYPE",
                                      "PRUID", "LANDAREA"))):
            for p in self._bc(path):
                for key in keys:
                    self.assertNotIn(p["attrs"].get(key), (None, ""), key)

    def test_polygon_centroids_project_back_inside_bc(self):
        """Guards the projection against the real boundary data: every BC
        subdivision must invert to a plausible BC latitude/longitude."""
        proj = statcan_lambert()
        for p in self._bc(CSD_ZIP):
            x0, y0, x1, y1 = p["bbox"]
            lon, lat = proj.inverse((x0 + x1) / 2, (y0 + y1) / 2)
            self.assertTrue(-141.0 <= lon <= -114.0,
                            f"{p['attrs']['CSDNAME']} lon={lon}")
            self.assertTrue(48.0 <= lat <= 60.5,
                            f"{p['attrs']['CSDNAME']} lat={lat}")

    def test_every_csd_type_code_has_a_label(self):
        j = _join()
        codes = {p["attrs"].get("CSDTYPE") for p in self._bc(CSD_ZIP)}
        self.assertEqual(codes - set(j.CSD_TYPES), set())


class TestBasisRule(unittest.TestCase):
    """The municipal-type corroboration must never reach the types that
    describe the countryside around a place rather than the place itself."""

    def setUp(self):
        self.j = _join()

    def test_excludes_regional_districts_and_reserves(self):
        for code in ("RDA", "IRI", "S-\u00c9", "NL", "TAL", "TWL", "IGD"):
            self.assertNotIn(code, self.j.MUNICIPAL_CSD_TYPES, code)

    def test_municipal_types_are_all_labelled(self):
        self.assertEqual(self.j.MUNICIPAL_CSD_TYPES - set(self.j.CSD_TYPES),
                         set())


@unittest.skipUnless(os.path.exists(OUTPUT), "no output; run 04_join.py")
class TestJoinOutput(unittest.TestCase):
    """Invariants on the delivered CSV. The central one is that a population
    is never reported without saying what it is the population *of*."""

    @classmethod
    def setUpClass(cls):
        import csv as _csv
        with open(OUTPUT, encoding="utf-8", newline="") as f:
            cls.rows = list(_csv.DictReader(f))

    def test_one_row_per_geoname(self):
        self.assertEqual(len(self.rows), 3216)
        ids = [r["geoname_id"] for r in self.rows]
        self.assertEqual(len(set(ids)), len(ids))

    def test_every_population_is_labelled(self):
        """The whole point of the two-column design: an unlabelled number
        would be read as the population of the named place, and for 83% of
        rows it is the population of a surrounding dissemination area."""
        for r in self.rows:
            self.assertIn(r["place_population_basis"],
                          ("municipal", "csd", "da", "none"))
            if r["place_population"]:
                self.assertIn(r["place_population_basis"],
                              ("municipal", "csd", "da"),
                              r["bc_geographic_name"])
                self.assertTrue(r["place_population_source"],
                                r["bc_geographic_name"])
                self.assertTrue(r["place_population_confidence"],
                                r["bc_geographic_name"])
            else:
                self.assertEqual(r["place_population_basis"], "none",
                                 r["bc_geographic_name"])

    def test_place_population_is_copied_from_its_stated_basis(self):
        for r in self.rows:
            if r["place_population_basis"] == "municipal":
                self.assertEqual(r["place_population"], r["muni_population"],
                                 r["bc_geographic_name"])
            elif r["place_population_basis"] == "csd":
                self.assertEqual(r["place_population"], r["csd_population"],
                                 r["bc_geographic_name"])
            elif r["place_population_basis"] == "da":
                self.assertEqual(r["place_population"], r["da_population"],
                                 r["bc_geographic_name"])

    def test_incorporated_municipalities_report_the_municipality(self):
        """A city must never be reported on a dissemination-area basis - that
        is the Vancouver-is-632-people failure this design exists to avoid."""
        municipal = {"City", "District Municipality", "Village", "Town",
                     "Resort Municipality"}
        for r in self.rows:
            if r["geoname_type"] in municipal:
                self.assertEqual(r["place_population_basis"], "municipal",
                                 r["bc_geographic_name"])

    def test_vancouver_is_not_its_dissemination_area(self):
        van = next(r for r in self.rows
                   if r["bc_geographic_name"] == "Vancouver")
        self.assertEqual(van["place_population_basis"], "municipal")
        self.assertGreater(int(van["place_population"]), 600000)
        self.assertLess(int(van["da_population"]), 5000)
        # BC Stats' estimate corrects the census for net undercoverage, so it
        # must be the larger of the two and must be the one reported.
        self.assertGreater(int(van["muni_population"]),
                           int(van["csd_population"]))

    def test_homonyms_resolve_to_distinct_places(self):
        """Mill Bay, Bear Lake and Pine Valley each have a same-named census
        place 318-820 km away. Geometry must give each its own answer rather
        than both claiming one number."""
        for name in ("Mill Bay", "Bear Lake", "Pine Valley"):
            pair = [r for r in self.rows if r["bc_geographic_name"] == name]
            self.assertEqual(len(pair), 2, name)
            self.assertNotEqual(pair[0]["da_uid"], pair[1]["da_uid"], name)
            self.assertNotEqual(pair[0]["csd_uid"], pair[1]["csd_uid"], name)

    def test_name_corroborated_matches_stay_local(self):
        """The name-gated tier is what keeps a name from selecting a polygon
        far away; every acceptance must be within the tolerance."""
        for r in self.rows:
            if r["csd_match"] == "nearest-name":
                self.assertLessEqual(float(r["csd_distance_m"]), 2000.0,
                                     r["bc_geographic_name"])
                self.assertEqual(r["name_agrees_with_csd"], "yes",
                                 r["bc_geographic_name"])

    def test_municipal_rows_carry_the_estimate_and_its_year(self):
        seen = set()
        for r in self.rows:
            if r["place_population_basis"] != "municipal":
                continue
            seen.add(r["csd_uid"])
            self.assertTrue(r["muni_name"], r["bc_geographic_name"])
            self.assertEqual(r["muni_population_year"], "2021",
                             r["bc_geographic_name"])
            self.assertIn("BC Stats", r["place_population_source"])
        # 159 of BC's 162 are named by a geoname. Sun Peaks Mountain is
        # absent from the sheet entirely, and the two shíshálh Nation
        # government districts are named only by their constituent land
        # units, which are parcels within the district rather than the
        # district itself - so those stay on a dissemination-area basis.
        self.assertEqual(len(seen), 159)

    def test_places_inside_a_municipality_still_name_it(self):
        """A neighbourhood is not its municipality, but the reader should be
        able to see which one holds it."""
        inside = [r for r in self.rows
                  if r["muni_name"] and r["place_population_basis"] == "da"]
        self.assertGreater(len(inside), 300)
        for r in inside[:50]:
            self.assertIn(r["muni_name"], r["note"], r["bc_geographic_name"])

    def test_census_count_is_still_published_beside_the_estimate(self):
        """Replacing the census figure must not mean hiding it."""
        for r in self.rows:
            if r["place_population_basis"] == "municipal" and r["csd_population"]:
                self.assertNotEqual(r["place_population"], "")
                self.assertTrue(r["csd_population"])

    def test_da_basis_rows_say_so_in_the_note(self):
        for r in self.rows:
            if r["place_population_basis"] == "da":
                self.assertIn("NOT of the named place", r["note"],
                              r["bc_geographic_name"])


class TestNesting(unittest.TestCase):
    """The sheet lists places at several levels at once, so the same people
    appear on more than one row. These are the invariants that let the rows be
    added up anyway."""

    @classmethod
    def setUpClass(cls):
        import csv as _csv
        with open(OUTPUT, encoding="utf-8", newline="") as f:
            cls.rows = list(_csv.DictReader(f))
        cls.primary = [r for r in cls.rows if r["is_primary"] == "TRUE"]

    def test_flags_are_true_or_false(self):
        for r in self.rows:
            self.assertIn(r["is_nested"], ("TRUE", "FALSE"))
            self.assertIn(r["is_primary"], ("TRUE", "FALSE"))

    def test_geography_matches_the_stated_basis(self):
        """`geo_uid` must point at the geography the population came from, or
        a total built on it would be deduplicating the wrong thing."""
        for r in self.rows:
            basis = r["place_population_basis"]
            if basis in ("municipal", "csd"):
                self.assertEqual(r["geo_level"], "csd")
                self.assertEqual(r["geo_uid"], r["csd_uid"])
            elif basis == "da":
                self.assertEqual(r["geo_level"], "da")
                self.assertEqual(r["geo_uid"], r["da_uid"])
            else:
                self.assertEqual(r["geo_uid"], "")
                self.assertEqual(r["is_primary"], "FALSE")

    def test_one_primary_row_per_geography(self):
        """The property the whole column exists for."""
        uids = [r["geo_uid"] for r in self.primary]
        self.assertEqual(len(set(uids)), len(uids))
        self.assertTrue(all(uids))

    def test_nested_rows_are_never_primary(self):
        for r in self.rows:
            if r["is_nested"] == "TRUE":
                self.assertEqual(r["is_primary"], "FALSE",
                                 r["bc_geographic_name"])

    def test_every_geography_with_a_population_keeps_one_row(self):
        """Deduplicating must not drop a geography entirely: every geography
        that is not inside a named place still has exactly one row standing."""
        standing = {r["geo_uid"] for r in self.primary}
        for r in self.rows:
            if r["geo_uid"] and r["is_nested"] == "FALSE":
                self.assertIn(r["geo_uid"], standing, r["bc_geographic_name"])

    def test_essondale_is_nested_inside_coquitlam(self):
        """The reported case: a community listed separately from the city
        whose population already includes it."""
        essondale = self._by_id("10643")
        coquitlam = self._by_name("Coquitlam")
        self.assertEqual(essondale["is_nested"], "TRUE")
        self.assertEqual(essondale["is_primary"], "FALSE")
        self.assertEqual(essondale["parent_geoname_id"], coquitlam["geoname_id"])
        self.assertEqual(essondale["parent_name"], "Coquitlam")
        self.assertEqual(coquitlam["is_primary"], "TRUE")
        self.assertEqual(coquitlam["is_nested"], "FALSE")

    def test_a_named_subdivision_is_never_nested(self):
        """Subdivisions are siblings, never one inside another - an Indian
        reserve is not part of the municipality it adjoins. Only
        dissemination-area rows can sit inside something."""
        for r in self.rows:
            if r["place_population_basis"] in ("municipal", "csd"):
                self.assertEqual(r["is_nested"], "FALSE",
                                 r["bc_geographic_name"])

    def test_every_nested_row_names_a_parent_that_is_itself_primary(self):
        by_id = {r["geoname_id"]: r for r in self.rows}
        for r in self.rows:
            if r["is_nested"] == "TRUE":
                self.assertTrue(r["parent_name"], r["bc_geographic_name"])
                parent = by_id[r["parent_geoname_id"]]
                self.assertEqual(parent["is_primary"], "TRUE")
                self.assertEqual(parent["csd_uid"], r["csd_uid"])

    def test_duplicate_geonames_for_one_place_keep_exactly_one(self):
        """Abbotsford is listed twice, as a City and as a Community. They are
        the same place and carry the same number; only one may count."""
        abbotsford = [r for r in self.rows
                      if r["bc_geographic_name"] == "Abbotsford"]
        self.assertEqual(len(abbotsford), 2)
        self.assertEqual({r["csd_uid"] for r in abbotsford}, {"5909052"})
        self.assertEqual(sum(r["is_primary"] == "TRUE" for r in abbotsford), 1)
        self.assertEqual([r["is_nested"] for r in abbotsford], ["FALSE"] * 2)

    def test_shared_count_matches_the_rows_on_that_geography(self):
        counts = {}
        for r in self.rows:
            if r["geo_uid"]:
                counts[r["geo_uid"]] = counts.get(r["geo_uid"], 0) + 1
        for r in self.rows:
            if r["geo_uid"]:
                self.assertEqual(int(r["geo_shared_with"]),
                                 counts[r["geo_uid"]] - 1,
                                 r["bc_geographic_name"])

    def test_primary_total_is_plausible_for_bc(self):
        """The end-to-end check. Adding every row up gives 6.33 million people
        in a province of 5.2 million; adding the primary rows lands just past
        the census count, which is what it should do - municipalities carry
        BC Stats' higher estimate, while the geonames reach only 523 of BC's
        7,848 dissemination areas, so the rural remainder is missing."""
        total = sum(int(r["place_population"] or 0) for r in self.primary)
        naive = sum(int(r["place_population"] or 0) for r in self.rows)
        self.assertGreater(naive, 6_000_000)
        self.assertGreater(total, 4_800_000)
        self.assertLess(total, 5_214_805)

    def _by_id(self, gid):
        return next(r for r in self.rows if r["geoname_id"] == gid)

    def _by_name(self, name):
        return next(r for r in self.rows
                    if r["bc_geographic_name"] == name
                    and r["place_population_basis"] in ("municipal", "csd"))


class TestShortlist(unittest.TestCase):
    """The shortlist is a filter, not a new calculation: it may drop rows but
    must never alter one, and must not lose a category to a size threshold."""

    @classmethod
    def setUpClass(cls):
        import csv as _csv
        cls.mod = _load("05_shortlist.py", "shortlist")
        cls.types = cls.mod.csd_type_codes()
        with open(OUTPUT, encoding="utf-8", newline="") as f:
            cls.source = list(_csv.DictReader(f))
        with open(SHORTLIST, encoding="utf-8", newline="") as f:
            cls.rows = list(_csv.DictReader(f))

    def test_every_row_is_primary(self):
        """Inherited from the join - a shortlist of overlapping rows would be
        worse than useless, because it looks summable."""
        for r in self.rows:
            self.assertEqual(r["is_primary"], "TRUE", r["bc_geographic_name"])
        uids = [r["geo_uid"] for r in self.rows]
        self.assertEqual(len(set(uids)), len(uids))

    def test_rows_are_copied_unaltered(self):
        by_id = {r["geoname_id"]: r for r in self.source}
        for r in self.rows:
            original = by_id[r["geoname_id"]]
            for column, value in r.items():
                if column != "selected_because":
                    self.assertEqual(value, original[column],
                                     f"{r['bc_geographic_name']}.{column}")

    def test_selection_matches_the_stated_rule(self):
        """Recomputed from the source rather than trusted, in both directions:
        nothing qualifying may be missing and nothing present may fail."""
        expected = {r["geoname_id"]
                    for r, _ in self.mod.select(self.source, 1000, self.types)}
        self.assertEqual({r["geoname_id"] for r in self.rows}, expected)

    def test_every_municipality_survives_whatever_its_size(self):
        munis = [r for r in self.source
                 if r["is_primary"] == "TRUE"
                 and r["place_population_basis"] == "municipal"]
        self.assertEqual(len(munis), 159)
        kept = {r["geoname_id"] for r in self.rows}
        for m in munis:
            self.assertIn(m["geoname_id"], kept, m["bc_geographic_name"])

    def test_every_indigenous_community_survives_whatever_its_size(self):
        """Indigenous communities are small by construction - many count zero
        - so a bare population threshold would delete most of them in BC."""
        indigenous = [r for r in self.source if r["is_primary"] == "TRUE"
                      and self.mod.is_indigenous(r, self.types)]
        kept = {r["geoname_id"] for r in self.rows}
        for r in indigenous:
            self.assertIn(r["geoname_id"], kept, r["bc_geographic_name"])
        self.assertTrue(any(r["place_population"] == "0" for r in indigenous))

    def test_reserves_named_by_another_feature_type_are_caught(self):
        """Three reserves are named by a Community or Locality geoname, so the
        geoname type alone would miss them. Shuswap was a fourth until the
        join learned to rank localities last: the reserve is named by both a
        Locality and an Indian Reserve geoname, and the latter now wins."""
        names = {r["bc_geographic_name"] for r in self.rows
                 if r["csd_type"] == "Indian reserve"
                 and r["place_population_basis"] == "csd"
                 and r["geoname_type"] != "Indian Reserve"}
        self.assertEqual(names, {"Mount Currie", "Telegraph Creek",
                                 "Kanaka Bar"})

    def test_the_category_is_not_just_reserves(self):
        """The point of the widening. Nations that concluded treaties or
        self-government agreements no longer have reserves, so a reserve-only
        filter drops them precisely *because* they settled."""
        present = {r["csd_type"] for r in self.rows
                   if "indigenous" in r["selected_because"]}
        for kind in ("Nisga'a land", "Tsawwassen Lands", "Tla'amin Lands",
                     "Indian government district", "Indian settlement"):
            self.assertIn(kind, present, kind)

    def test_named_nisgaa_villages_are_present(self):
        """Three of the four. Gitwinksihlkw shares its dissemination area with
        Nass Camp, a logging settlement, and loses `is_primary` to it on the
        geoname id - see test_is_primary_is_a_summing_gate_not_a_roster."""
        names = {r["bc_geographic_name"] for r in self.rows}
        for village in ("Gingolx", "Laxgalts'ap", "New Aiyansh"):
            self.assertIn(village, names, village)

    def test_is_primary_is_a_summing_gate_not_a_roster(self):
        """The shortlist's central limitation, asserted so it cannot be
        forgotten. `is_primary` keeps one row per geography so populations can
        be added up; it was never a claim that the other rows are not real
        places. Most Indigenous geonames share a dissemination area with
        another, so the shortlist is a population set, not a roster of
        communities. Removing the gate for this category is a deliberate
        decision, not a bug fix."""
        matching = [r for r in self.source
                    if self.mod.is_indigenous(r, self.types)]
        kept = [r for r in matching if r["is_primary"] == "TRUE"]
        self.assertGreater(len(matching), 1500)
        self.assertLess(len(kept), len(matching) / 2)
        lost_to_a_shared_geography = [
            r for r in matching
            if r["is_primary"] == "FALSE" and r["is_nested"] == "FALSE"]
        self.assertGreater(len(lost_to_a_shared_geography), 900)

    def test_village_sites_are_kept_because_nothing_else_names_the_reserve(self):
        """Hitacu is the only row naming Ittatsoo 1; no geoname carries the
        reserve's own name, so dropping the village site loses the place."""
        names = {r["bc_geographic_name"] for r in self.rows}
        for site in ("Hitacu", "Anaqtl'a", "Houpsitas", "Hi'tatis", "Ak:tiis"):
            self.assertIn(site, names, site)
        self.assertNotIn("Ittatsoo 1",
                         {r["bc_geographic_name"] for r in self.source})

    def test_land_units_are_excluded_but_their_district_is_not(self):
        """A land unit is a parcel inside the shishalh government district,
        not a community. Excluding them is only safe because the join prefers
        the district over its own parcels when they share a geography."""
        self.assertEqual(
            [r for r in self.rows if "Land Unit" in r["geoname_type"]], [])
        self.assertIn("Sechelt Indian Government District",
                      {r["bc_geographic_name"] for r in self.rows})

    def test_every_indigenous_type_code_exists_in_the_join(self):
        """The CSV carries readable labels, not codes. If a label were renamed
        in 04_join.py this filter would silently match nothing."""
        for code in self.mod.INDIGENOUS_CSD_TYPES:
            self.assertIn(code, set(self.types.values()), code)

    def test_suppressed_population_never_passes_the_threshold(self):
        blank = dict(self.source[0], place_population="",
                     place_population_basis="da", geoname_type="Locality",
                     csd_type="", is_primary="TRUE")
        self.assertEqual(self.mod.population(blank), -1)
        self.assertEqual(list(self.mod.select([blank], 1000, self.types)), [])

    def test_threshold_is_exclusive_and_adjustable(self):
        exactly = dict(self.source[0], place_population="1000",
                       place_population_basis="da", geoname_type="Locality",
                       csd_type="", is_primary="TRUE")
        self.assertEqual(list(self.mod.select([exactly], 1000, self.types)), [])
        self.assertEqual(len(list(self.mod.select([exactly], 999, self.types))), 1)

    def test_selected_because_names_every_clause_that_applied(self):
        for r in self.rows:
            reasons = r["selected_because"].split(" + ")
            self.assertTrue(reasons and all(reasons))
            self.assertEqual("municipality" in reasons,
                             self.mod.is_municipality(r))
            self.assertEqual("indigenous" in reasons,
                             self.mod.is_indigenous(r, self.types))
            self.assertEqual("population>1000" in reasons,
                             self.mod.population(r) > 1000)


class TestXlsxReader(unittest.TestCase):
    """The workbook reader is hand-rolled too, so it is checked against a
    sheet built here whose expected contents are known exactly."""

    @staticmethod
    def _workbook(rows):
        """A minimal .xlsx whose single sheet holds `rows` of strings."""
        import io as _io
        import zipfile as _zipfile

        strings, order = {}, []
        for row in rows:
            for cell in row:
                if cell and not cell.isdigit() and cell not in strings:
                    strings[cell] = len(order)
                    order.append(cell)

        def ref(c, r):
            name = ""
            c += 1
            while c:
                c, rem = divmod(c - 1, 26)
                name = chr(65 + rem) + name
            return f"{name}{r + 1}"

        body = []
        for ri, row in enumerate(rows):
            cells = []
            for ci, cell in enumerate(row):
                if cell == "":
                    continue               # sparse: empty cells are absent
                if cell.isdigit():
                    cells.append(f'<c r="{ref(ci, ri)}"><v>{cell}</v></c>')
                else:
                    cells.append(f'<c r="{ref(ci, ri)}" t="s">'
                                 f'<v>{strings[cell]}</v></c>')
            body.append(f'<row r="{ri + 1}">{"".join(cells)}</row>')

        ns = ("xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'")
        rns = ("xmlns:r='http://schemas.openxmlformats.org/officeDocument/"
               "2006/relationships'")
        buf = _io.BytesIO()
        with _zipfile.ZipFile(buf, "w") as z:
            z.writestr("xl/workbook.xml",
                       f"<workbook {ns} {rns}><sheets>"
                       f"<sheet name='Mun-RD' sheetId='1' r:id='rId1'/>"
                       f"</sheets></workbook>")
            z.writestr("xl/_rels/workbook.xml.rels",
                       "<Relationships xmlns='http://schemas.openxmlformats."
                       "org/package/2006/relationships'><Relationship "
                       "Id='rId1' Target='worksheets/sheet1.xml'/>"
                       "</Relationships>")
            z.writestr("xl/sharedStrings.xml",
                       f"<sst {ns}>"
                       + "".join(f"<si><t>{t}</t></si>" for t in order)
                       + "</sst>")
            z.writestr("xl/worksheets/sheet1.xml",
                       f"<worksheet {ns}><sheetData>{''.join(body)}"
                       f"</sheetData></worksheet>")
        return buf.getvalue()

    def _read(self, rows, **kw):
        import tempfile
        from lib.xlsx_lite import read_sheet
        with tempfile.NamedTemporaryFile(suffix=".xlsx") as fh:
            fh.write(self._workbook(rows))
            fh.flush()
            return read_sheet(fh.name, **kw)

    def test_values_and_shared_strings_round_trip(self):
        rows = [["SGC", "Name", "Area Type"], ["15022", "Vancouver", "CY"]]
        self.assertEqual(self._read(rows), rows)

    def test_gaps_do_not_shift_later_columns(self):
        """An absent cell must pad, not close up - otherwise every column
        after the first blank is read from the wrong field."""
        rows = [["a", "", "c", "", "e"]]
        self.assertEqual(self._read(rows), [["a", "", "c", "", "e"]])

    def test_columns_past_z(self):
        """The changes block in the real workbook starts around column T and
        runs past Z, where the reference is two letters."""
        rows = [[str(i) for i in range(30)]]
        self.assertEqual(self._read(rows)[0][29], "29")

    def test_sheet_selected_by_name(self):
        rows = [["SGC"]]
        self.assertEqual(self._read(rows, sheet="Mun-RD"), rows)
        from lib.xlsx_lite import XlsxError
        with self.assertRaises(XlsxError):
            self._read(rows, sheet="Nope")


@unittest.skipUnless(os.path.exists(XLSX), "workbook not present")
class TestMunicipalEstimates(unittest.TestCase):
    """BC Stats' workbook is the authority for incorporated municipalities,
    and it joins to the census on a numeric key, so both ends are checked."""

    @classmethod
    def setUpClass(cls):
        cls.m = _load("02b_municipal_est.py", "step02b")
        cls.places = cls.m.extract(XLSX)

    def test_all_162_municipalities(self):
        self.assertEqual(len(self.places), 162)

    def test_regional_districts_are_excluded(self):
        """RD, RDR and the Stikine census division describe the countryside
        around named places, which is precisely what this file is not for."""
        for code in ("RD", "RDR", "R"):
            self.assertNotIn(code, self.m.MUNICIPAL_TYPES)
        self.assertEqual({p[3] for p in self.places} - self.m.MUNICIPAL_TYPES,
                         set())

    def test_keys_are_unique_census_subdivision_uids(self):
        uids = [p[0] for p in self.places]
        self.assertEqual(len(set(uids)), 162)
        for uid in uids:
            self.assertTrue(uid.startswith("59") and len(uid) == 7, uid)

    @unittest.skipUnless(os.path.exists(CENSUS), "no census extract")
    def test_every_key_exists_in_the_census(self):
        """The SGC -> CSDUID mapping is asserted, not assumed: if it were
        wrong, estimates would silently attach to the wrong municipality."""
        import csv as _csv
        with open(CENSUS, encoding="utf-8", newline="") as f:
            known = {r["alt_geo_code"] for r in _csv.DictReader(f)}
        missing = [p[0] for p in self.places if p[0] not in known]
        self.assertEqual(missing, [])

    def test_full_series_is_present(self):
        years = {y for *_, counts in self.places for y in counts}
        self.assertEqual(min(years), "2011")
        self.assertGreaterEqual(max(years), "2025")
        for uid, _, name, _, counts in self.places:
            self.assertIn("2021", counts, name)


class TestCommuteBasins(unittest.TestCase):
    """The basin tables in 06_basins.py are hand-authored geography, so the
    checks here are the ones a reader cannot do by eye: that the tables refer
    only to things that exist, that every place lands somewhere, and that the
    barrier rules actually fire on the cases the design turns on."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load("06_basins.py", "step6")

    def test_tables_are_internally_consistent(self):
        m = self.mod
        regions = {k for k, _ in m.REGIONS}
        keys = [b["key"] for b in m.BASINS]
        self.assertEqual(len(keys), len(set(keys)), "duplicate basin key")
        for b in m.BASINS:
            self.assertIn(b["region"], regions, b["key"])
            self.assertIn(b["access"], m.ACCESS_LEVELS, b["key"])
            self.assertTrue(b["note"], f"{b['key']} has no note")
            for cd in b["cds"]:
                self.assertIn(cd, m.CD_NAMES, b["key"])
        for z in m.ZONES:
            self.assertIn(z["basin"], keys, z["key"])
            self.assertIn(z["access"], m.ACCESS_LEVELS, z["key"])
            self.assertTrue(z["names"] or z["boxes"], f"{z['key']} claims nothing")
        for name, (key, why) in m.OVERRIDES.items():
            self.assertIn(key, keys, name)
            self.assertTrue(why, f"override {name} has no reason")

    def test_every_region_offers_three_to_seven_basins(self):
        """The UI expands a region into a list a contractor reads at a glance.
        One basin makes the region pointless; more than seven is the list the
        design exists to avoid."""
        m = self.mod
        counts = {}
        for b in m.BASINS:
            counts[b["region"]] = counts.get(b["region"], 0) + 1
        for key, label in m.REGIONS:
            n = counts.get(key, 0)
            self.assertGreaterEqual(n, 2, f"{label} has {n} basins")
            self.assertLessEqual(n, 7, f"{label} has {n} basins")

    @unittest.skipUnless(os.path.exists(OUTPUT), "no join output")
    def test_every_hub_resolves_to_one_place(self):
        m = self.mod
        places = m.load_places(OUTPUT)
        hubs = m.resolve_hubs(places)          # raises on a typo
        self.assertEqual(len(hubs), len(m.BASINS))
        ids = [h["id"] for h in hubs.values()]
        self.assertEqual(len(ids), len(set(ids)), "two basins share a hub")

    @unittest.skipUnless(os.path.exists(OUTPUT), "no join output")
    def test_every_place_lands_in_exactly_one_basin(self):
        m = self.mod
        places = m.load_places(OUTPUT)
        rows = m.assign(places, m.resolve_hubs(places))
        self.assertEqual(len(rows), len(places))
        self.assertEqual(len({r["id"] for r in rows}), len(rows))
        keys = {b["key"] for b in m.BASINS}
        for r in rows:
            self.assertIn(r["basin"], keys, r["name"])

    @unittest.skipUnless(os.path.exists(OUTPUT), "no join output")
    def test_no_basin_is_empty(self):
        """A basin nothing lands in is a hub in the wrong census division."""
        m = self.mod
        places = m.load_places(OUTPUT)
        rows = m.assign(places, m.resolve_hubs(places))
        got = {r["basin"] for r in rows}
        self.assertEqual(sorted({b["key"] for b in m.BASINS} - got), [])

    @unittest.skipUnless(os.path.exists(OUTPUT), "no join output")
    def test_the_examples_the_design_is_built_on(self):
        """Straight from the brief. Each of these is a case where straight-line
        distance gives the wrong answer, so each is worth asserting."""
        m = self.mod
        places = m.load_places(OUTPUT)
        rows = m.assign(places, m.resolve_hubs(places))
        by_name = {}
        for r in rows:
            by_name.setdefault(r["name"], []).append(r)
        basin = {b["key"]: b for b in m.BASINS}

        def one(name, cd=None):
            cands = by_name[name]
            if cd:
                cands = [c for c in cands if c["cd"] == cd]
            self.assertEqual(len(cands), 1, name)
            return cands[0]

        # A basin auto-covers its hub and the unincorporated places round it,
        # including the ones no municipal list contains.
        for name in ("Courtenay", "Comox", "Cumberland", "Royston",
                     "Merville", "Black Creek"):
            self.assertEqual(one(name, "5926")["basin"], "comox-valley", name)
        for name in ("Kelowna", "West Kelowna, City of", "Lake Country",
                     "Peachland"):
            self.assertEqual(one(name)["basin"], "kelowna", name)

        # Unincorporated locales the municipal list drops entirely.
        self.assertEqual(one("Errington")["basin"], "oceanside")
        self.assertEqual(one("Roberts Creek")["basin"], "sechelt")

        # Ferry sub-locales sit inside their basin but carry the sailing, so a
        # contractor who takes the Comox Valley does not get Hornby with it.
        for name in ("Hornby Island", "Denman Island"):
            r = one(name)
            self.assertEqual(r["basin"], "comox-valley", name)
            self.assertEqual(r["access"], m.FERRY, name)
        r = one("Bowen Island")
        self.assertEqual((r["basin"], r["access"]), ("north-shore", m.FERRY))

        # The case the brief names: from Victoria, neither Salt Spring nor
        # Duncan comes along for the ride.
        self.assertEqual(one("Victoria")["basin"], "victoria")
        self.assertEqual(basin["victoria"]["access"], m.ROAD)
        self.assertEqual(one("Ganges")["basin"], "gulf-islands-south")
        self.assertEqual(basin["gulf-islands-south"]["access"], m.FERRY)
        self.assertEqual(one("Duncan")["basin"], "cowichan")
        self.assertEqual(basin["cowichan"]["access"], m.PASS)

        # Castlegar works with Trail across a regional district boundary.
        self.assertEqual(one("Castlegar")["basin"], "trail-castlegar")

    @unittest.skipUnless(os.path.exists(OUTPUT), "no join output")
    def test_nothing_is_offered_as_a_drive_that_cannot_be_one(self):
        """The invariant the whole design rests on. Great-circle km is not
        drive time, but nothing 120 km away in a straight line is a 45-60
        minute corridor whatever the road does, so every such place has to be
        tagged ferry, pass or remote - never left as an ordinary drive a
        contractor gets without asking for it."""
        m = self.mod
        places = m.load_places(OUTPUT)
        rows = m.assign(places, m.resolve_hubs(places))
        bad = [(r["name"], r["basin"], r["km"]) for r in rows
               if r["access"] == m.ROAD and r["km"] > m.DISTANT_KM]
        self.assertEqual(bad, [])

    @unittest.skipUnless(os.path.exists(OUTPUT), "no join output")
    def test_the_coast_is_not_mistaken_for_a_road(self):
        """Ninety-odd Tsimshian, Gitga'at, Haisla, Heiltsuk and Kitasoo
        communities sit on fjords and islands with no road to them. Distance
        alone reads them as a long drive up a channel, which is the one error
        in this file that would put a contractor on a wharf with no boat."""
        m = self.mod
        places = m.load_places(OUTPUT)
        rows = m.assign(places, m.resolve_hubs(places))
        by_name = {}
        for r in rows:
            by_name.setdefault(r["name"], []).append(r)
        boat_only = ["Metlakatla", "Lax Kw'alaams", "Kitkatla", "Hartley Bay",
                     "Dodge Cove", "Oona River", "Kemano", "Klemtu",
                     "Ocean Falls", "Shearwater", "Oweekeno", "Tallheo"]
        for name in boat_only:
            rows_ = by_name.get(name, [])
            self.assertTrue(rows_, f"{name} is missing from the source")
            for r in rows_:
                self.assertIn(r["access"], (m.FERRY, m.REMOTE),
                              f"{name} is offered as a drive")
        # And the road that is a road stays one.
        for name in ("Prince Rupert", "Port Edward", "Terrace", "Kitimat",
                     "Bella Coola", "Hagensborg"):
            self.assertEqual(by_name[name][0]["access"], m.ROAD, name)

    @unittest.skipUnless(os.path.exists(BASINS_CSV), "no basins output")
    def test_csv_and_json_agree(self):
        import csv as _csv
        import json as _json
        with open(BASINS_CSV, encoding="utf-8", newline="") as f:
            rows = list(_csv.DictReader(f))
        with open(SERVICE_JSON, encoding="utf-8") as f:
            doc = _json.load(f)
        self.assertEqual(len(rows), len(doc["places"]))
        idx = {k: i for i, k in enumerate(doc["fields"])}
        seen = {p[idx["id"]]: p for p in doc["places"]}
        for r in rows:
            p = seen[int(r["geoname_id"])]
            self.assertEqual(p[idx["basin"]], r["basin"], r["bc_geographic_name"])
            self.assertEqual(p[idx["access"]], r["place_access"])
        # Every basin the page can offer has somewhere to put its dot.
        for b in doc["basins"]:
            self.assertTrue(b["places"] >= 1, b["key"])
            self.assertIsInstance(b["lat"], float)
        listed = {k for r in doc["regions"] for k in r["basins"]}
        self.assertEqual(listed, {b["key"] for b in doc["basins"]})


if __name__ == "__main__":
    unittest.main(verbosity=2)
