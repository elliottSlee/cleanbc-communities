# Map of the shortlist

A static page that puts every row of `../pipeline/out/geoname_shortlist.csv` on a
map. Hover a dot for the place's name, type and population; click it (or a row in
the sidebar) for the whole record, including which geography the number describes.

No build step and no dependencies to install — MapLibre GL and the Inter font load
from CDNs, the basemap is OpenFreeMap. None of them needs an API key. The CSV is fetched live, so re-running
`make shortlist` in `../pipeline` updates the map on the next reload.

Browsers block `fetch()` from `file://`, so serve the repository root over HTTP:

```bash
# from the repository root
python3 -m http.server 8000
# then open http://localhost:8000/webapp/
```

A place can be linked to directly: `#` plus its `geoname_id`, e.g. `/webapp/#40540` opens Dawson Creek.

Keyboard: `/` focuses search, `Esc` clears the search or closes the detail card.
The theme follows the OS and can be toggled with the button in the top right.

Colours group `geoname_type` into three sets — Indigenous communities (Indian
Reserve, First Nation Village, Indian Government District), municipalities
(City, District Municipality, Town, Village, Resort Municipality) and everything
else (Community, Locality). Dot area scales with `place_population`.
