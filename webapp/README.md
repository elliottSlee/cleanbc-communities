# Two pages

`index.html` maps the shortlist; `service-areas.html` picks a contractor's
service area out of it. Both are static, share `styles.css`, and need no build
step.

## Map of the shortlist

A static page that puts every row of
`../pipeline/out/geoname_shortlist_deduped.csv` on a map. Hover a dot for the
place's name, type and population; click it (or a row in the sidebar) for the
whole record, including which geography the number describes.

No build step and no dependencies to install — MapLibre GL and the Inter font load
from CDNs, the basemap is OpenFreeMap. None of them needs an API key. The CSV is
fetched live, so re-running `make shortlist exclude-nested` in `../pipeline`
updates the map on the next reload.

Both pages also draw the province's own outline, from
`../pipeline/out/bc_boundary.geojson` (`make province` in `../pipeline`) — a
single DataBC polygon, drawn under the points so it reads as a boundary rather
than a shape competing with them.

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

It reads `../pipeline/out/service_areas.json` — BC's 29 regional districts, 76
commute basins, and every geoname in one of them. See
[Commute basins](../pipeline/README.md#commute-basins) for how the geography is
built; this file is about the page.

**The top level is the province's own.** The districts come from the BC Data
Catalogue, so the first thing a contractor reads is the boundary they already
pay taxes to — Cariboo, qathet, Kitimat-Stikine — listed alphabetically by the
short name, with the official one on the tooltip and in the exported CSV. It is
a way in, not an answer: nobody's service area is the Peace River Regional
District, but everybody knows whether they are in it.

**Take a basin, not a list.** Open a regional district, tick a basin, and its hub
and every unincorporated hamlet around it come with it. Ticking *Comox Valley*
takes Courtenay, Comox, Cumberland, Royston, Merville and Black Creek — three
of which are in no municipality and would otherwise have to be hunted down by
name. A disclosure arrow expands the basin into its sub-locales so any one of
them can be unticked; the basin checkbox then shows indeterminate rather than
silently lying about what is in.

**Nothing is gated; the page asks instead.** Every area in the province can be
ticked at any time. There used to be three switches — ferries, passes,
resource roads — that decided what a contractor was *allowed* to pick, and they
were wrong about the people they most affected: somebody whose whole business
is on Haida Gwaii does not take a ferry to work, they live there, and being
made to turn ferries on first is the page telling them they are unusual.

So the first pick is free, whatever it costs to reach. After that, a pick that
commits to travel not already in the selection says so once — *"Getting to
Southern Gulf Islands means a sailing. There is a schedule and a fare, and a
day's work can turn into an overnight."* — and waits. **Yes, add it** ticks the
box; **Cancel** leaves it unticked. An area carrying two kinds of travel asks
once and lists both. Removing an area never asks, and once a kind of travel is
in, it is never asked about again until *Clear*. The summary then reports what
the selection involves rather than gating it: *12 reached by ferry, 3 resource
road or fly-in*.

The distance rules underneath are unchanged, and they are the reason this is
safe: from Victoria, neither Salt Spring nor Duncan is dragged in because the
straight line looks short.

**The selection is decisions, not places.** What the page stores is which
basins you took, which sub-locales you unticked, which strays you added, and
which travel you have agreed to — and it recomputes the place list from those.
Unticking Merville and re-taking the Comox Valley does not quietly forget it,
and the whole selection fits in the URL. *Copy link* hands over a working link;
*Download CSV* writes one row per selected place with its basin, hub, regional
district and access. Opening somebody else's link never interrogates you about
travel their area already does.

Selections also persist in `localStorage`, so a reload keeps your work. A link
in the URL wins over the stored one.

**On a phone it is a list, not a map.** Below 760px the two panes stop sharing
the screen: the page opens on the selector and the map becomes the second of
two tabs. A map is the wrong first screen here — it shows you the province but
gives you nothing to answer with — so it is somewhere to check your work rather
than the way in. Rows, checkboxes and buttons all grow to thumb size, and the
question above becomes a sheet off the bottom edge, clear of the home bar.
Tapping a district or a basin name opens it; on a desktop, where the card has a
map to sit beside, a basin name still opens the card instead.

Both panes keep the same grid cell and the same size at every width — the one
you are not looking at is only made `visibility: hidden`. Giving the map
`display: none` would leave MapLibre measuring a zero-sized box and fitting the
whole province into it.

Keyboard: `/` focuses search, `Esc` clears it or closes the card. Searching a
place name opens the basins that contain it, which is how you find out that
Errington is in Parksville–Qualicum; searching a district name — either the
short one or the official one — narrows the tree to that district.

## Deployed

- Map — <https://elliottslee.github.io/cleanbc-communities/webapp/>
- Service areas — <https://elliottslee.github.io/cleanbc-communities/webapp/service-areas.html>

GitHub Pages serves the repository root of `main`, which is why the page's
`../pipeline/out/geoname_shortlist_deduped.csv` resolves there exactly as it
does under `http.server`. Two files at the root support this: `.nojekyll`, so
Pages copies every file through verbatim instead of running Jekyll, and
`index.html`, which forwards the bare URL here and carries the fragment across.

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
