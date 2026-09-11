# Handoff: population per row of `Geonames.csv` — **COMPLETE**

`pipeline/README.md` is the reference; this file records only what changed and
what to watch out for.

## Result

**3,192 of 3,216 rows (99.3%)** carry a 2021 population. The remaining 24 sit
in geographies Statistics Canada suppressed.

Every row says which geography *and which source* its number comes from:

| `place_population_basis` | Rows | Meaning |
|---|---:|---|
| `municipal` | 166 | BC Stats' estimate **for the incorporated municipality** named. |
| `csd` | 368 | 2021 census count for the **census subdivision** named (reserves, Nisga'a villages). |
| `da` | 2,658 | 2021 census count for the **surrounding dissemination area**, not of the named place. |
| `none` | 24 | Suppressed. |

`place_population_source` spells it out in words on every row, and
`da_population`, `csd_population` and `muni_population` are all kept alongside,
so nothing is hidden by the choice.

Rows overlap - Essondale is inside Coquitlam - so `is_primary` marks the
1,049 that can be added up. See "Nested places" below.

`python3 pipeline/test_pipeline.py` — **81 tests, all passing**.

## Two source switches, in order

### 1. Designated places → the hierarchical census product

`98-401-X2021011` covers only 332 BC geographies — a hard ceiling near 10% of
the sheet. `98-401-X2021006_BC_*` is hierarchical: 7,848 dissemination areas,
751 census subdivisions, 29 census divisions, plus BC and Canada, 8,630 in one
3.6 GB file streamed in ~80 s. DAs tile the province and the CSDs include all
423 BC Indian reserves and every municipality, so coverage went from a ceiling
of 10% to an actual 99.3%.

### 2. Census counts → BC Stats estimates, for municipalities only

`pop_municipal_subprov_areas.xlsx` is the province's own annual estimate series
(July 1st, 2011–2025) for its 162 incorporated municipalities, and it is the
better figure: a census *count* is not adjusted for net undercoverage, and a
2021 boundary is not a 2025 one. Across the 162, estimates total 4,670,523
against the census's 4,464,434.

- `lib/xlsx_lite.py` — minimal stdlib `.xlsx` reader. Shared strings and
  **sparse cells**: an absent `<c>` means an empty cell, so cells are placed by
  their A1 reference and gaps padded, never taken in document order. Getting
  that wrong shifts every column after the first blank.
- `02b_municipal_est.py` — reduces the `Mun-RD` sheet to
  `data/municipal_estimates.csv` (162 × 15 years). It keeps only the municipal
  area types; `RD`, `RDR` and the Stikine `R` row describe the countryside
  *around* named places, which is the distinction the whole pipeline turns on.
- The join key is the sheet's `SGC` column — the last five digits of the CSDUID
  (SGC 15022 = CSDUID 5915022). **All 162 join, so no name matching is
  involved**; the estimate attaches to whatever polygon containment chose. A
  test asserts every key exists in the census extract, because a wrong mapping
  would silently attach estimates to the wrong municipality.

**Vintage.** `--estimate-year` defaults to **2021** so every figure in the
output describes the same year and the improvement over the census is purely
one of method. `muni_population_latest` carries 2025 regardless, and
`04_join.py --estimate-year 2025` makes the current estimate the headline.

**Only for geonames that name a municipality.** 644 rows land inside one of the
162, but 478 of them are neighbourhoods and localities and still report their
dissemination area — Kitsilano is 689, not Vancouver's 696,031. `muni_name`
records the containing municipality on all of them.

**3 of 162 are never reported**: Sun Peaks Mountain is absent from
`Geonames.csv` entirely, and the two shíshálh Nation government districts are
named only by their constituent land units, which are parcels within the
district rather than the district itself.

## Nested places (the sheet cannot simply be summed)

`Geonames.csv` lists Coquitlam *and* Essondale inside it, Vancouver *and*
Kitsilano. Adding every `place_population` gives 6,329,562 people in a
province of 5.2 million.

Not solved by pairwise geoname containment - geonames are points, and the
question is not really geometric. Each row already knows its subdivision and
its dissemination area, and those nest by construction, so `mark_nesting()`
in `04_join.py` reads the answer straight off the census hierarchy in a
second pass over the finished rows.

Seven columns: `geo_level`, `geo_uid` (the dedupe key), `geo_shared_with`,
`parent_geoname_id`, `parent_name`, `is_nested`, `is_primary`.

**Filter `is_primary == TRUE`.** 1,049 rows totalling **5,004,154**, against
BC's 2021 census count of 5,000,879 - the right side of both that and BC
Stats' 5,214,805, for the reason in the README. That total is the end-to-end
check on the whole pipeline and a test asserts the band.

Three distinct causes of duplication, deliberately kept apart:

- **nested** 538 rows inside a subdivision another row names.
- **duplicate subdivision** 8 places named twice under different feature
  types (Abbotsford the City / the Community).
- **shared DA** 294 DAs holding 1,951 rows; one Omineca DA holds 70 reserves
  all reporting the same 373.

The third is why `is_primary` is a *representative*, not a claim of ownership.
The tie-break is deterministic (status, match quality, geoname id) but
arbitrary, and `geo_shared_with` exists to keep that visible. Do not quietly
turn it into an attribution.

Only one level deep, and that is correct: subdivisions are siblings, so a
reserve is never nested in the municipality beside it.

## The shortlist (`05_shortlist.py`)

`is_primary AND (population > 1000 OR municipality OR Indigenous community)`
-> `out/geoname_shortlist.csv`, **638 rows**, 4,796,915 people. 467
Indigenous, 159 municipalities, 164 over the threshold, 12 by size alone.

**"Indian reserve" is not the category.** Nisga'a, Tsawwassen, Tla'amin and
shishalh left the reserve system by treaty or self-government, so a
reserve-only filter drops them *because* they settled. The filter takes CSD
types IRI, NL, NVL, TWL, TAL, IGD, S-É plus the `First Nation Village` and
`Indian Government District` geoname types. Type codes are read back out of
04_join.py's CSD_TYPES rather than restated, because the CSV carries labels.

Three things that are load-bearing:

- The CSD-type test does **not** require the row to name its subdivision, or
  the Nisga'a villages (inside one `Nisga'a` CSD, naming none of it) vanish.
  Costs 12 rows that merely sit inside Indigenous land.
- The five `First Nation Village` sites are the *only* row naming their
  reserve; no geoname carries the reserve's name.
- Land units are excluded, which forced `_representative` to rank a whole
  government above its own land units - the shishalh district had lost its DA
  to "Sechelt SB 2", one of its own parcels. Localities now rank last too.

**`is_primary` is a summing gate, not a roster.** 1,648 geonames match the
category; 467 survive. ~1,040 lose an arbitrary tie-break for a shared DA
(Gitwinksihlkw loses to Nass Camp on geoname id). 1,552 reserve geonames
occupy ~1,000 DAs and the census publishes nothing below the DA, so no
per-place figure exists at any price. For a roster rather than a population
set, drop the `is_primary` clause for this category. A test asserts the size
of the gap.

## A mislabelled census type code - fixed

`CSD_TYPES` had `TAL` as "Teslin land", a Yukon geography. BC's only TAL
subdivision is Sliammon 1, and the census names it "Tla'amin Lands (TAL)" -
so every output row mislabelled the Tla'amin Nation. Also corrected TWL to
"Tsawwassen Lands" to match the census's own wording.

## The staged `shapefile_lite.py` had a bug — do not restore the old copy

It returned **1,684 of 1,685** records and corrupted every attribute. The
`.dbf` field-descriptor array ends with a **single `0x0D` byte**, but
`_read_dbf` consumed a full 32-byte chunk to detect it, over-reading 31 bytes
into the first record. The materialising version was immune because it did an
absolute `buf.seek(header_len)`; a forward-only stream cannot seek back, so
every record decoded at the wrong offset and the last ran short and vanished.

Fixed by peeking the terminator one byte at a time, plus `zip(..., strict=True)`
in `_collect` so a desynced parse is a loud error rather than a silently short
result. `TestShapefileReader` builds a synthetic `.shp`/`.dbf` pair in memory
and fails if the bug is reintroduced. The copy at the repo root is synced with
the fix, so re-copying it is harmless.

## Two judgement calls worth reviewing

**`nearest-name` tier (180 rows).** A BCGN representative point for a small
reserve often sits just outside its own boundary and therefore inside the
regional district around it — containment alone reported the countryside next
door. `Iskut 6`'s point is 600 m outside Iskut 6, in a DA of 74 people, while
the reserve has 478. When a same-named CSD lies within `--tolerance`, it is
taken. 177 of the 180 are Indian reserves. Accepted distances run 5 m–1,893 m
against the 318–820 km separating the genuine homonyms, so the distance gate
still does the work; `Mill Bay`, `Bear Lake` and `Pine Valley` each still
resolve to two distinct places.

**Municipal-type corroboration (2 rows).** An incorporated municipality's label
point is inside its own CSD by construction, so for municipal geoname types
containment settles the basis even when the spelling differs: `100 Mile House`
is the CSD `One Hundred Mile House` and `Northern Rockies Regional
Municipality` is `Northern Rockies`. Across all 159 municipal geonames this
rule and name agreement agree 157 times, and the two they differ on are both
these. Excludes CSD types `RDA` and `IRI` deliberately.

## Still true, still do not redo

- `pipeline/data/geoname_points.jsonl` — 3,216 records, status `ok`, zero
  failures. **Do not refetch.**
- `lib/proj_lcc.py`, `lib/spatial.py`, `lib/tls.py` — all verified; see the
  README. Certificate verification stays **on**.
- No third-party packages — no pandas, no GDAL, no openpyxl. Pure stdlib by
  necessity; keep it that way.
- Disk is tight (~11 GB free). Nothing is extracted; the 3.6 GB CSV is
  streamed, never copied.

## Gotchas that did not carry over

- **Multi-part geographies.** Unlike designated places, no CSD is split into
  lettered parts and every `CSDUID`/`DAUID` appears exactly once — multi-part
  geometry is several rings inside one record. A test asserts the uniqueness
  this relies on. The one apparent exception is cosmetic: the shíshálh Nation
  government district appears as two rows, but they carry different SGC codes
  and are distinct CSDs in the census too, so nothing needs summing.
- **The `name`-only tier** is gone. Both layers tile BC, so containment never
  fails outright and a name is never allowed to select a polygon.
