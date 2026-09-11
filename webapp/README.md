# Map of the shortlist

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

## Deployed

<https://elliottslee.github.io/cleanbc-communities/webapp/>

GitHub Pages serves the repository root of `main`, which is why the page's
`../pipeline/out/geoname_shortlist.csv` resolves there exactly as it does under
`http.server`. Two files at the root support this: `.nojekyll`, so Pages copies
every file through verbatim instead of running Jekyll, and `index.html`, which
forwards the bare URL here and carries the fragment across.

One difference from local use: the deployed map reads the **committed** CSV, so
re-running `make shortlist` only changes it once you commit and push the result.

A place can be linked to directly: `#` plus its `geoname_id`, e.g. `/webapp/#40540` opens Dawson Creek.

Keyboard: `/` focuses search, `Esc` clears the search or closes the detail card.
The theme follows the OS and can be toggled with the button in the top right.

Colours group `geoname_type` into three sets — Indigenous communities (Indian
Reserve, First Nation Village, Indian Government District), municipalities
(City, District Municipality, Town, Village, Resort Municipality) and everything
else (Community, Locality). Dot area scales with `place_population`.
