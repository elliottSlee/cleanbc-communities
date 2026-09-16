# Geoname → population

Attaches a 2021 population to each of the 3,216 rows of `../Geonames.csv`, and
says which geography each number describes. BC Stats' estimate is used for the
162 incorporated municipalities; the 2021 Census for everywhere else.

Pure standard-library Python 3.10+. No `pip install`, no GDAL, no pyproj, no
openpyxl — none of those are present on this machine, so the projection, the
shapefile reader, the spreadsheet reader and the point-in-polygon test are
implemented here and covered by `test_pipeline.py`.

```bash
make all      # points -> census -> municipal -> boundaries -> districts ->
              # province -> municipalities -> join -> shortlist ->
              # exclude-nested -> basins
make test     # checks on the hand-rolled geometry, parsing and output
```

Current result: **3,192 of 3,216 rows (99.3%)** carry a population, and all
159 municipalities named in the sheet carry the province's own estimate. The
remaining 24 rows sit in geographies Statistics Canada suppressed.

The rows overlap, because the sheet names places inside other places. Filter
`is_primary == "TRUE"` for the 1,049 that can be added up — see
[Nested places](#nested-places-and-how-to-sum-the-sheet).

## Getting the inputs

The bulk StatCan downloads are **not in the repository** — each is over
GitHub's 100 MB per-file limit, 4.8 GB together. A fresh clone has everything
else, including the fetched coordinate cache and the pipeline's own outputs,
so `make shortlist` runs straight off the tracked `out/geoname_population.csv`.
`make census` needs the Census Profile table back, and `make join` needs the
boundary zips that `make boundaries` fetches.

`make boundaries` re-downloads all three of its zips from StatCan, so only
the Census Profile table is a manual step:

| Missing file | Where it comes from |
|---|---|
| `98-401-X2021006_BC_CB_eng_CSV/98-401-X2021006_English_CSV_data_BritishColumbia.csv` | StatCan product **98-401-X2021006**, Census Profile 2021, *British Columbia* CSV. 3.6 GB; the one table `02_census_pop.py` reads. |
| `pipeline/data/lda_000b21a_e.zip`, `lcsd000b21a_e.zip`, `ldpl000b21a_e.zip` | `make boundaries` (`03_fetch_boundaries.py`) fetches these. |
| `pipeline/data/regional_districts.geojson` | `make districts` (`03b_fetch_districts.py`) fetches this from the BC Data Catalogue. 20 MB, so it is not committed either. |
| `pipeline/data/municipalities.geojson` | `make municipalities` (`03d_fetch_municipalities.py`) fetches this from the BC Data Catalogue - the same layer `make districts` already uses for one row (Northern Rockies), unfiltered. 4 MB, not committed. |

The `98-401-X2021011` and `98-401-X2021025` directories are leftovers from the
earlier designated-place approach described below; nothing reads them. Their
`*_meta.txt` and `*_Geo_starting_row*.CSV` files are still tracked, which is
enough to identify each product, but their data tables are excluded too.

## The one thing to understand before using the output

**A dissemination area is not the named place.** A DA holds 400–700 people.
The DA containing Vancouver's label point has 632 of them. Reporting that as
"Vancouver's population" would be wrong by three orders of magnitude.

So every row carries every figure that applies to it, and a label saying which
one `place_population` was taken from:

| `place_population_basis` | Rows | What the number is |
|---|---:|---|
| `municipal` | 166 | BC Stats' **estimate for the incorporated municipality** the geoname names. The best figure available for the 162 municipalities, and the one to trust. |
| `csd` | 368 | The 2021 census count for the **census subdivision** the geoname names — an Indian reserve, Nisga'a village or other non-municipal subdivision. |
| `da` | 2,658 | The 2021 census count for the **surrounding dissemination area**, *not* of the named place. For communities, localities and anything with no official boundary, this is the closest thing that exists. |
| `none` | 24 | Every figure suppressed by Statistics Canada. |

`place_population_source` says the same thing in words, on every row.
`da_population`, `csd_population` and `muni_population` are all present
whenever they are known — replacing the census figure for a municipality does
not mean hiding it — so a consumer can ignore `place_population` and apply its
own rule. Never present `place_population` without its basis.

### Why municipalities use BC Stats rather than the census

For the 162 incorporated municipalities the province publishes its own annual
estimate, and it is the better number: a census *count* is not adjusted for net
undercoverage, and a 2021 boundary is not a 2025 one. Across the 162 the
estimates total 4,670,523 against the census's 4,464,434 — Vancouver alone is
696,031 rather than 662,248.

Estimates default to **2021**, matching the census vintage, so every figure in
the output describes the same year and the improvement is purely one of method.
`muni_population_latest` always carries the newest year in the workbook (2025)
alongside it, and `04_join.py --estimate-year 2025` makes the current estimate
the headline instead.

This only ever applies to a geoname that *names* a municipality. A
neighbourhood inside one still reports its dissemination area — Kitsilano is
689 people, not Vancouver's 696,031 — with `muni_name` recording which
municipality holds it.

## What the sources actually are

Worth knowing before reading the code, because two of them differ from what
their filenames suggest.

| Source | What it is |
|---|---|
| `Geonames.csv` | 3,216 BC names. `GeoName ID` is the join key. |
| `bcgnws.json` | **An OpenAPI specification, not data.** It documents the BC Geographical Names web service but contains no names or coordinates. |
| `98-401-X2021006_BC_*` | Census Profile for BC, **hierarchical**: 7,848 dissemination areas, 751 census subdivisions, 29 census divisions, plus BC and Canada — 8,630 geographies in one 3.6 GB file. |
| `pop_municipal_subprov_areas.xlsx` | BC Stats' sub-provincial population **estimates**, July 1st 2011–2025, for the 162 incorporated municipalities (and regional districts, which this pipeline ignores). |

Because `bcgnws.json` holds no data, coordinates are fetched from the live
service it describes. The `GeoName ID` column is that API's `nameId`:

```
GET https://apps.gov.bc.ca/pub/bcgnws/names/{nameId}.json?outputSRS=4326
```

Neither bundled source carries a polygon — the census CSV has no geometry and
the API returns one representative *point* per name — so the containment join
also needs StatCan's boundary files, which `03` downloads: `lda_000b21a_e.zip`
(dissemination areas) and `lcsd000b21a_e.zip` (census subdivisions), both
EPSG:3347, `PRUID == "59"` for BC.

### Why this product and not the designated-place one

The pipeline previously used `98-401-X2021011`, **designated places**, which
covers only 332 BC geographies — a hard ceiling near 10% of the sheet no
matter how good the join is. Designated places are *unincorporated* by
definition, so every city, village and district municipality, and nearly
every Indian reserve, is definitionally absent.

The hierarchical product fixes this from both directions at once: DAs tile
the entire province, so every land point falls in exactly one, and the 751
CSDs include all 423 BC Indian reserves and every municipality. Coverage went
from a ceiling of 10% to an actual 99.3%.

## How the join decides

Geometry decides; names only corroborate. BC reuses names freely — `Mill Bay`,
`Bear Lake` and `Pine Valley` each have a same-named census place **318–820 km**
away — so a name is never allowed to *select* a polygon, only to interpret the
one containment already chose. Each of those three pairs resolves to two
different places, as it should.

Each point gets a DA and a CSD, by these tiers:

| `csd_match` / `da_match` | Rows (CSD) | Meaning |
|---|---:|---|
| `contains` | 2,854 | The point falls inside the polygon. Authoritative. |
| `nearest-name` | 180 | The point lies outside a **same-named** subdivision but within `--tolerance` of it. See below. |
| `nearest` | 182 | The point falls in no polygon at all — almost always just offshore — and adopts the nearest within tolerance. |
| `none` | 0 | No polygon within tolerance. |

### Why `nearest-name` exists

BCGN publishes one representative point per name, and for a small reserve it
often sits just outside that reserve's own boundary — and therefore *inside*
the regional district wrapped around it. Containment alone would then report
the surrounding countryside: `Iskut 6`'s point is 600 m outside Iskut 6 and
lands in Kitimat-Stikine D, whose DA has 74 people, while the reserve itself
has 478. 180 rows are recovered this way, 177 of them Indian reserves.

This is the tier where a name is consulted, so it is gated hard on distance:
accepted matches run 5 m to 1,893 m, against the 318–820 km that separates the
genuine homonyms. The 2 km default sits in that wide empty gap.

### Incorporated municipalities

The BC Stats workbook joins on its `SGC` column, the last five digits of the
census subdivision UID — SGC 15022 is CSDUID 5915022. All 162 join, so no name
matching is involved: the estimate attaches to whatever polygon containment
already chose. 159 of the 162 are named by a geoname and report their estimate.
Sun Peaks Mountain is absent from `Geonames.csv` altogether, and the two
shíshálh Nation government districts are named only by their constituent land
units, which are parcels within the district rather than the district itself.

An incorporated municipality's label point lies inside its own census
subdivision by construction, so for the geoname types `City`,
`District Municipality`, `Village`, `Town` and `Resort Municipality`,
containment settles the basis and the spelling need not agree. Two rows need
this: `100 Mile House` is the CSD `One Hundred Mile House`, and
`Northern Rockies Regional Municipality` is the CSD `Northern Rockies`.
Across all 159 municipal geonames this rule and name agreement give the same
answer 157 times, and the two they differ on are both these. All 159 now
report the municipality rather than a dissemination area.

The rule deliberately excludes CSD types `RDA` and `IRI`: a regional district
electoral area is the countryside *around* named places, not one of them.

## Nested places, and how to sum the sheet

`Geonames.csv` lists places at several levels at once. Coquitlam is a row;
so is Essondale, a community inside it. Vancouver is a row; so is Kitsilano.
Add every `place_population` up and you get **6,329,562** people in a province
of 5.2 million, because the same people are counted on several rows.

Geonames are *points*, so one cannot be tested for containment in another —
and pairwise containment would be the wrong question anyway. The census
geography already carries the answer: every row knows the subdivision its
point falls in and the dissemination area within it, and those two levels nest
by construction. That gives four columns:

| Column | Meaning |
|---|---|
| `geo_level` | `csd` if the row reports a whole subdivision, `da` if it reports a dissemination area. |
| `geo_uid` | The identifier of that geography — **the deduplication key**. |
| `geo_shared_with` | How many *other* rows report the same geography. |
| `is_nested` | `TRUE` if the row's area lies inside a subdivision that another row names. |
| `parent_geoname_id`, `parent_name` | Which row that is. Essondale's parent is Coquitlam. |
| `is_primary` | `TRUE` for exactly one row per geography, never for a nested one. |

**To use the sheet: keep the rows where `is_primary` is TRUE.** That is 1,049
rows, and they total **5,004,154** — against a 2021 census count for BC of
5,000,879. It should land slightly above the census and well below BC Stats'
5,214,805: municipalities carry the higher estimate, while the geonames reach
only 523 of BC's 7,848 dissemination areas, so the rural remainder is absent.

Three different things cause the duplication, and they need telling apart:

- **Nested** (538 rows) — a dissemination area inside a subdivision some other
  row names. Essondale's 1,021 are already inside Coquitlam's 155,554.
- **Duplicate subdivision** (8 places) — two geonames for one place, listed
  under different feature types: "Abbotsford" the City and "Abbotsford" the
  Community, "Wells" the District Municipality and "Wells" the Community.
- **Shared dissemination area** (294 DAs, 1,951 rows) — several geonames in
  one DA, each reporting the same figure. One DA in the Omineca holds **70**
  reserves, all showing 373.

That last case is why `is_primary` is a representative and not a claim. Where
rows tie, one is chosen by status, then match quality, then geoname id — stable
across runs, but arbitrary. `geo_shared_with` is there to show it: a primary
row with a non-zero count *speaks for* its geography, it does not own it. If
you need per-place figures for those 70 reserves, this sheet cannot give them;
the census does not publish below the DA.

Nesting only ever runs one level deep, because subdivisions are siblings — an
Indian reserve is not part of the municipality it adjoins, and the census
treats the two as separate. So a row with `is_nested` FALSE is either the top
of its nest or stands alone, which is the same thing for summing.

## The shortlist

`05_shortlist.py` cuts the sheet down to the places worth carrying forward:

    is_primary AND (population > 1000 OR a municipality
                    OR an Indigenous community)

**638 rows**, representing 4,796,915 people.

| Admitted because | Rows |
|---|---:|
| Indigenous community | 467 |
| Incorporated municipality | 159 |
| Population > 1,000 | 164 |
| *(size alone — neither category)* | *12* |

The two named categories are kept **whatever their size**, because a small
municipality and a small Indigenous community are each distinct communities
with their own governments. Many count zero people, so a bare population
threshold would quietly delete most of them.

### Why "Indigenous community" and not "Indian reserve"

Reserves are 423 of BC's 751 subdivisions, but they are not the category.
The Nisga'a, Tsawwassen, Tla'amin and shíshálh nations left the reserve
system through treaty or self-government, so a reserve-only filter drops them
**precisely because they concluded treaties**. The filter therefore takes any
subdivision of type `IRI`, `NL`, `NVL`, `TWL`, `TAL`, `IGD` or `S-É`, plus the
`First Nation Village` and `Indian Government District` geoname types.

Three details that decide real rows:

- **The subdivision test does not require the row to *name* its
  subdivision.** Gingolx, Laxgalts'ap and New Aiyansh are Nisga'a villages
  inside the single `Nisga'a` subdivision and name none of it, so a naming
  requirement would drop the Nisga'a communities entirely. The cost is twelve
  rows that merely lie inside Indigenous land — Mill Bay, Glenemma, Tzouhalem
  among them. `place_population_basis` and `csd_name` still say which is which.
- **Five reserves exist in the sheet only as a village site.** Hitacu,
  Anaqtl'a, Houpsitas, Hi'tatis and Ak:tiis are typed `First Nation Village`;
  no geoname carries their reserve's own name, so dropping the type loses the
  place outright.
- **Land units are excluded, and that required a fix in the join.** A land
  unit is a parcel inside the shíshálh government district, not a community.
  But the district itself had lost its dissemination area to "Sechelt SB 2",
  one of its own parcels, so excluding parcels would have deleted the shíshálh
  Nation. `_representative` now ranks a whole government above its own land
  units, and a locality — a named place, not necessarily an inhabited one —
  last of all.

### The limitation to know before using this as a roster

**`is_primary` is a deduplication gate, not a census of communities.** 1,648
geonames match the Indigenous category; 467 survive. 144 are nested inside a
subdivision another row names, and about 1,040 share a dissemination area with
another geoname and lose an arbitrary tie-break. Gitwinksihlkw, a Nisga'a
village, is absent for exactly this reason — it shares a DA with Nass Camp, a
logging settlement with a lower geoname id.

This is not a defect in the filter. Most reserves are small parcels and BC's
dissemination areas are coarse in the north, so 1,552 reserve geonames occupy
roughly 1,000 DAs; no per-place population exists for them at any price,
because the census does not publish below the DA. If you need a **roster** of
Indigenous communities rather than a **summable population set**, drop the
`is_primary` clause for this category and use the column to filter when
totalling instead. A test asserts the size of this gap so it cannot be
forgotten.

`selected_because` names every clause that admitted each row, so the cut can
be re-examined without rerunning the join. `--min-population` changes the
threshold, which is exclusive.

## Dropping places nested inside a municipality (`05b_exclude_nested_municipalities.py`)

The shortlist still has one kind of duplicate `is_primary` cannot see: two
places whose *census* geography sits side by side, even though one's real
boundary is entirely inside the other's. Every Indian reserve is its own
census subdivision, a sibling of the city around it, not something nested
inside it - so a reserve surrounded by a municipality (Tsawwassen by Delta,
Musqueam by Vancouver, 66 others) survives the join's nesting pass and lands
on the shortlist twice over: once as the reserve, once as the city holding it.

This step catches that case the way `04_join.py` cannot: geometrically,
against the municipality's actual legal boundary rather than the census
proxy for it. `03d_fetch_municipalities.py` downloads that boundary -
DataBC's "Municipalities - Legally Defined Administrative Areas of BC"
(`WHSE_LEGAL_ADMIN_BOUNDARIES.ABMS_MUNICIPALITIES_SP`), the same layer
`03b_fetch_districts.py` already draws one row from - and every shortlisted
place whose point falls inside one of its 160 polygons is dropped, unless
`place_population_basis == "municipal"`, i.e. the place *is* that
municipality.

**This drops Indian reserves inside city limits on purpose.** A reserve
enclosed by a municipality is still federal land under a separate government,
not a neighbourhood of the city around it - the same reasoning that keeps
Indigenous communities on the shortlist "whatever their size" would argue for
keeping these too. The choice made here is the opposite: for this map, a
place entirely inside a municipality's boundary reads as part of that
municipality regardless of jurisdiction, so all 68 are cut. Reverting this
call means skipping rows where `"indigenous" in selected_because`.

Two things worth knowing:

- **It cannot see the case it was named for.** A plain neighbourhood -
  James Bay inside Victoria - is already gone by this point: its
  dissemination area sits inside Victoria's census subdivision, so
  `04_join.py` already marked it `is_nested` and it never became
  `is_primary`, let alone reached the shortlist. This step exists for the one
  case that pass structurally cannot catch: two subdivisions that are
  siblings in the census hierarchy no matter how their real boundaries nest.
- **It reads the shortlist without rewriting it.** `out/geoname_shortlist.csv`
  still means exactly what `05_shortlist.py`'s own rule says; the further cut
  lands in `out/geoname_shortlist_deduped.csv`, which is what the webapp and
  everything downstream of "the shortlist" should read instead.
  `out/excluded_within_municipality.csv` lists what was dropped and why, for
  review without rerunning anything.

## Commute basins

`06_basins.py` answers a different question from the rest of the pipeline:
not *how many people live here* but *would a contractor drive to it*.

BC's official boundaries are the wrong shape for that on their own. Regional
districts are too big to *pick* — Peace River is larger than Austria — and
municipalities are too small, because most of the province's inhabited places
are unincorporated and belong to no municipality at all. A contractor asked to
tick municipalities cannot say "the Comox Valley"; asked to tick only regional
districts, they commit to a fifth of the province. Errington, Roberts Creek,
Merville and Royston are in none of the 162 municipalities and are exactly the
places the question is about.

So the step lays **76 commute basins** — driving corridors around one
commercial hub each — over the join's output, with every one of the 3,216
geonames in exactly one of them, and hangs those under the boundary a
contractor already knows: **BC's 29 regional districts**, downloaded from the
BC Data Catalogue. Too big to be the answer, exactly right as the way in.

    make districts       # downloads data/regional_districts.geojson (~20 MB)
    make basins          # writes out/geoname_basins.csv and out/service_areas.json
    make basin-report    # every basin's members, farthest from the hub first

### The top level comes from DataBC

`03b_fetch_districts.py` reads two layers off the province's WFS endpoint as
GeoJSON — one request each, no shapefile to unzip:

- `WHSE_LEGAL_ADMIN_BOUNDARIES.ABMS_REGIONAL_DISTRICTS_SP` — 27 regional
  districts plus the **Stikine Region**, the unincorporated northwest that
  belongs to no district but is administered as though it were one.
- `WHSE_LEGAL_ADMIN_BOUNDARIES.ABMS_MUNICIPALITIES_SP`, filtered to the
  **Northern Rockies Regional Municipality**, which absorbed its own regional
  district in 2009 and so is a municipality doing a district's job. Without it
  there is an 86,000 km² hole around Fort Nelson.

29 areas, which is exactly Statistics Canada's 29 BC census divisions — and
that correspondence is what the rest of the step needs, because every place
here is already labelled with a census division and nothing is labelled with a
regional district. Rather than typing 29 pairs and hoping, `district_crosswalk`
drops all 3,216 places into the DataBC polygons and lets each division take the
district holding most of them. The majority matters: the two boundaries are not
bit-identical, three divisions have a single place a few hundred metres over a
line, and about ten places on the 49th parallel fall just outside every polygon
because the border is a rounded coordinate. A division that landed nowhere at
all would stop the run.

The polygons are used once, here, and then dropped. `out/service_areas.json`
carries names and counts, not 20 MB of coastline for a phone to download.

Display names are derived, not typed: "Regional District of Bulkley-Nechako"
and "Cariboo Regional District" are the same kind of thing named two ways, and
a picker listing both in full files half the province under R. The boilerplate
is stripped for the row and kept as the tooltip and the CSV column.

### The three tables are the model

Everything else is derived, and the tables are meant to be edited.

- **`BASINS`** — one per hub. `hub` names a row of the source CSV and the
  coordinates come from that row, so no coordinate is typed by hand and a
  misspelled hub stops the run instead of putting a dot in the ocean. `access`
  is how the basin is reached from the rest of its district: the Malahat on
  Cowichan, a sailing on Salt Spring. `closed` keeps a basin out of the
  distance competition entirely. There is no `region` field — a basin belongs
  to the district its **hub** stands in, because a basin that draws across a
  divisional line still has one address, and it is the town the work is
  dispatched from.
- **`ZONES`** — the barriers: sets of places on the far side of water, a pass,
  or the end of the road, by exact name or by bounding box. A zone overrides
  distance when assigning its places, and stamps them with the access a
  contractor has to opt into.
- **`OVERRIDES`** — the handful of places no rule gets right, each with its
  reason. Castlegar is in Central Kootenay and works with Trail.

A place with no zone and no override joins the nearest hub **among the basins
that draw from its own census division**. The division does the work that a
road network would: without it, Ganges is 24 km from Sidney across Haro Strait
and the Saanich Peninsula leaves Victoria for Salt Spring.

### Four kinds of access, not two

`road`, `ferry`, `pass` and `remote`. The fourth is not in the original brief
and BC needs it anyway: a hundred-odd inhabited places are neither a sailing
nor a mountain highway but two hundred kilometres of resource road, a winter
road or a float plane — Tsay Keh Dene, Kwadacha, Takla Landing, the Sustut,
Gwaii Haanas. Filing them under either of the other two would tell a
contractor something false about the trip.

The coast is where this matters most. Ninety-odd Tsimshian, Gitga'at, Haisla,
Heiltsuk, Kitasoo, Wuikinuxv and Nuxalk communities sit on fjords and islands
with no road at all, and distance alone reads them as a long *drive* up a
channel — the one error here that would put somebody on a wharf with no boat.
Metlakatla, Hartley Bay, Kitkatla, Kemano, Klemtu, Ocean Falls and Oweekeno
are all water access, and a test asserts it.

### The backstop, and what it admits

There is no road network in this repository. A place the tables did not
classify is assumed to be an ordinary drive, and that assumption fails in one
direction only — on trapline localities and lake reserves nothing names. So
past **`DISTANT_KM` = 120 km** great-circle from its hub, an unclassified
place is marked `remote` rather than quietly offered as a drive. A 60-minute
drive is roughly 90 km of BC highway, well under 120 km straight-line, so
nothing inside a real basin is caught and nothing caught is inside one. It
currently fires on 13 places, visible as `nearest+beyond-range` in
`assigned_by`.

That is the honest limit of this step: **basins are hand-drawn geography
checked against distance, not isochrones.** Drive times would need a routing
engine and ferry schedules, neither of which is here.

### Why 76 and not 45

The brief this was built from asked for about 45 basins. Holding to its own
rule — a 45–60 minute corridor — produces 76, because south of Cache Creek a
basin is a valley and north of Prince George the next settlement is two hours
away. The number a contractor sees is basins *per region*, which is 2–7
throughout and asserted by a test; the total only shows if you expand
everything.

## Outputs

- `out/geoname_population.csv` — one row per geoname, 36 columns:
  `da_uid`, `da_population`, `da_match`, `da_distance_m`,
  `csd_uid`, `csd_name`, `csd_type`, `csd_population`, `csd_match`,
  `csd_distance_m`, `name_agrees_with_csd`,
  `muni_name`, `muni_type`, `muni_population`, `muni_population_year`,
  `muni_population_latest`, `muni_latest_year`, then `place_population`,
  `place_population_basis`, `place_population_source`,
  `place_population_confidence`, then the nesting columns `geo_level`,
  `geo_uid`, `geo_shared_with`, `parent_geoname_id`, `parent_name`,
  `is_nested`, `is_primary`, and a `note` spelling out in words what the
  number is.
  Filter on `place_population_basis in ("municipal", "csd")` for the strict
  set of "population of the named place", and on `is_primary == "TRUE"` for a
  set that can be added up.
- `data/municipal_estimates.csv` — the workbook reduced to
  `csd_uid, sgc, name, area_type, year, population`, 162 municipalities ×
  15 years.
- `out/geoname_shortlist.csv` — the shortlisted rows, same columns plus
  `selected_because`. See [The shortlist](#the-shortlist).
- `out/geoname_shortlist_deduped.csv` — the shortlist with places nested
  inside a municipality's legal boundary removed. See
  [Dropping places nested inside a municipality](#dropping-places-nested-inside-a-municipality-05b_exclude_nested_municipalitiespy).
  This is the file the webapp reads.
- `out/excluded_within_municipality.csv` — every row that step dropped, and
  which municipality's boundary caught it.
- `data/municipalities.geojson` — the 160 municipalities from DataBC with
  their official names and polygons. Not committed: `make municipalities`
  re-fetches it.
- `out/unclaimed_csds.csv` — the 16 census subdivisions no geoname landed in,
  i.e. the coverage gap seen from the census side.
- `data/regional_districts.geojson` — the 29 areas from DataBC with their
  official names, abbreviations and polygons. Not committed: 20 MB, and
  `make districts` re-fetches it.
- `out/geoname_basins.csv` — one row per geoname with its basin, hub,
  `basin_access`, `place_access`, `assigned_by` and `hub_distance_km`, plus
  two regional districts that are not the same question: `district` is where
  the *place* is, `basin_district` is where its basin is dispatched from.
  `assigned_by` says which table decided: `hub`, `zone:<key>`, `override`,
  `nearest`, or `nearest+beyond-range`.
- `out/service_areas.json` — the same thing shaped for
  [`webapp/service-areas.html`](../webapp/service-areas.html): the district
  and basin tables, then every place as a fixed-order array. 295 KB.
- `out/bc_boundary.geojson` — the province as a single DataBC polygon
  (`03c_fetch_province.py`), so both webapp maps can draw the outline of BC
  itself. Small enough (1.5 MB) to be committed, unlike the regional
  districts fetch above.

`place_population_confidence` is `high` for a containment match and `medium`
for either nearest tier. It describes how the *polygon* was chosen, not how
good the count is.

## Notes

- `01` is resumable. Results append to `data/geoname_points.jsonl`; a rerun
  only requests IDs the cache lacks, so an interrupted fetch costs nothing.
  ~3,200 requests at 6 workers takes roughly 10 minutes. All 3,216 currently
  resolve, with zero failures.
- `02` streams the 3.6 GB CSV in ~80 s, keeping only `CHARACTERISTIC_ID == 1`
  ("Population, 2021") and reducing ~22.7 M data lines to 8,630. The file is
  **latin-1**, and its header repeats the name `SYMBOL` five times, so
  `csv.DictReader` would silently collapse those columns — it is indexed
  positionally instead.
- `lib/xlsx_lite.py` reads the BC Stats workbook. Two details of the `.xlsx`
  format bite a casual reader: text cells hold an index into a shared string
  table rather than the text, and a row's cells are sparse — an empty cell is
  simply absent — so cells are placed by their A1 reference and gaps padded,
  never taken in document order. `02b` finds the year columns by their
  headings, because the sheet also carries a block of `2011-12 Changes`
  columns and gains a year with every release.
- `lib/shapefile_lite.py` filters on `.dbf` attributes via `where=` *before*
  parsing any geometry, and streams the `.shp` straight out of the zip. The
  national DA layer is 57,936 polygons; materialising it would cost about a
  gigabyte of Python tuples and extracting it ~700 MB of disk. Neither
  happens.
- Polygon counts are cross-checked against the census file's own geography
  counts (7,848 DAs, 751 CSDs) in `test_pipeline.py`. Two independently
  produced products agreeing is what establishes the hand-rolled reader is
  neither dropping nor duplicating records.
- Unlike designated places, no CSD is split into lettered parts and every
  `CSDUID`/`DAUID` appears exactly once; multi-part geographies are encoded
  as several rings inside a single record. So the part-summing the old
  pipeline needed has no counterpart here.
- `lib/tls.py` exists because this python.org interpreter ships with no CA
  file configured (`ssl.get_default_verify_paths().cafile is None`). Behind a
  TLS-inspecting proxy every HTTPS call fails with
  `CERTIFICATE_VERIFY_FAILED` while `curl` succeeds, because curl reads the
  macOS keychain. It exports the keychain roots to a PEM bundle and verifies
  against that — certificate verification stays **on**.
- Census counts are randomly rounded to a multiple of 5 by Statistics Canada,
  and 51 of the 8,630 BC values are suppressed (28 DAs, 23 CSDs). A count of
  `0` is a real zero and is kept distinct from "unknown", which is blank —
  several reserves genuinely have no residents. Small-area figures are
  indicative.
