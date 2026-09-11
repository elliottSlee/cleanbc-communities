# Two pages

`index.html` maps the shortlist; `service-areas.html` picks a contractor's
service area out of it. Both are static, share `styles.css`, and need no build
step.

## Map of the shortlist

A static page that puts every row of `../pipeline/out/geoname_shortlist.csv` on a
map. Hover a dot for the place's name, type and population; click it (or a row in
the sidebar) for the whole record, including which geography the number describes.

No build step and no dependencies to install — MapLibre GL and the Inter font load
from CDNs, the basemap is OpenFreeMap. None of them needs an API key. The CSV is
fetched live, so re-running `make shortlist` in `../pipeline` updates the map on
the next reload.

Browsers block `fetch()` from `file://`, so serve the repository root over HTTP:

```bash
# from the repository root
python3 -m http.server 8000
# then open http://localhost:8000/webapp/
```


## Service areas

`service-areas.html` answers "where will you travel to work?" without asking a
contractor to read a list of 3,216 places or to pretend their business stops at
a municipal boundary.

It reads `../pipeline/out/service_areas.json` — 16 macro regions, 76 commute
basins, and every geoname in one of them. See
[Commute basins](../pipeline/README.md#commute-basins) for how the geography is
built; this file is about the page.

**Take a basin, not a list.** Open a macro region, tick a basin, and its hub
and every unincorporated hamlet around it come with it. Ticking *Comox Valley*
takes Courtenay, Comox, Cumberland, Royston, Merville and Black Creek — three
of which are in no municipality and would otherwise have to be hunted down by
name. A disclosure arrow expands the basin into its sub-locales so any one of
them can be unticked; the basin checkbox then shows indeterminate rather than
silently lying about what is in.

**Barriers are off by default.** Three toggles — ferries, mountain passes,
resource roads and fly-in — gate both whole basins and individual sub-locales.
With ferries off, taking the Comox Valley leaves Hornby and Denman out and says
so; the Southern Gulf Islands cannot be taken at all. This is the case the page
exists for: from Victoria, neither Salt Spring nor Duncan is dragged in because
the straight line looks short.

**The selection is decisions, not places.** What the page stores is which
basins you took, which sub-locales you unticked, which strays you added, and
which travel you allow — and it recomputes the place list from those. So
turning ferries off and on again drops and restores Hornby without forgetting
that you had also unticked Merville, and the whole selection fits in the URL.
*Copy link* hands over a working link; *Download CSV* writes one row per
selected place with its basin, hub and access.

Selections also persist in `localStorage`, so a reload keeps your work. A link
in the URL wins over the stored one.

Keyboard: `/` focuses search, `Esc` clears it or closes the card. Searching a
place name opens the basins that contain it, which is how you find out that
Errington is in Parksville–Qualicum.

## Deployed

- Map — <https://elliottslee.github.io/cleanbc-communities/webapp/>
- Service areas — <https://elliottslee.github.io/cleanbc-communities/webapp/service-areas.html>

GitHub Pages serves the repository root of `main`, which is why the page's
`../pipeline/out/geoname_shortlist.csv` resolves there exactly as it does under
`http.server`. Two files at the root support this: `.nojekyll`, so Pages copies
every file through verbatim instead of running Jekyll, and `index.html`, which
forwards the bare URL here and carries the fragment across.

One difference from local use: the deployed pages read the **committed** data,
so re-running `make shortlist` or `make basins` only changes them once you
commit and push the result.

A place can be linked to directly: `#` plus its `geoname_id`, e.g. `/webapp/#40540` opens Dawson Creek.

Keyboard: `/` focuses search, `Esc` clears the search or closes the detail card.
The theme follows the OS and can be toggled with the button in the top right.

Colours group `geoname_type` into three sets — Indigenous communities (Indian
Reserve, First Nation Village, Indian Government District), municipalities
(City, District Municipality, Town, Village, Resort Municipality) and everything
else (Community, Locality). Dot area scales with `place_population`.
