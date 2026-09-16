/* CleanBC Communities map — reads pipeline/out/geoname_shortlist.csv and
   puts every row on a MapLibre map. Hover for name / type / population;
   click for the full row. No build step; MapLibre GL and the OpenFreeMap
   basemap are the only external pieces, and neither needs a key. */

(function () {
  'use strict';

  const CSV_URL = '../pipeline/out/geoname_shortlist.csv';
  const BOUNDARY_URL = '../pipeline/out/bc_boundary.geojson';
  const STYLE = {
    light: 'https://tiles.openfreemap.org/styles/positron',
    dark: 'https://tiles.openfreemap.org/styles/dark',
  };
  // Three groups by geoname_type. Colour slots 1-3 of the validated palette.
  const CATEGORY_OF_TYPE = {
    'Indian Reserve': 'indigenous',
    'First Nation Village': 'indigenous',
    'Indian Government District': 'indigenous',
    'City': 'municipality',
    'District Municipality': 'municipality',
    'Village': 'municipality',
    'Town': 'municipality',
    'Resort Municipality': 'municipality',
    'Community': 'other',
    'Locality': 'other',
  };
  const CATEGORIES = [
    { key: 'indigenous',   label: 'Indigenous community',  light: '#2a78d6', dark: '#3987e5' },
    { key: 'municipality', label: 'Municipality',          light: '#eb6834', dark: '#d95926' },
    { key: 'other',        label: 'Community or locality', light: '#1baf7a', dark: '#199e70' },
  ];
  const BASIS_LABEL = { municipal: 'BC Stats estimate', csd: 'Census subdivision', da: 'Dissemination area', none: 'Suppressed' };

  const $ = (id) => document.getElementById(id);
  const fmt = (n) => (n == null || Number.isNaN(n)) ? '—' : n.toLocaleString('en-CA');
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  /* ---------- Theme ---------- */
  const mql = window.matchMedia('(prefers-color-scheme: dark)');
  function currentTheme() {
    const t = document.documentElement.dataset.theme;
    if (t === 'dark' || t === 'light') return t;
    return mql.matches ? 'dark' : 'light';
  }

  /* ---------- CSV ---------- */
  function parseCSV(text) {
    const rows = [];
    let row = [], field = '', i = 0, quoted = false;
    while (i < text.length) {
      const c = text[i];
      if (quoted) {
        if (c === '"') {
          if (text[i + 1] === '"') { field += '"'; i += 2; continue; }
          quoted = false; i++; continue;
        }
        field += c; i++; continue;
      }
      if (c === '"') { quoted = true; i++; continue; }
      if (c === ',') { row.push(field); field = ''; i++; continue; }
      if (c === '\r') { i++; continue; }
      if (c === '\n') { row.push(field); rows.push(row); row = []; field = ''; i++; continue; }
      field += c; i++;
    }
    if (field.length || row.length) { row.push(field); rows.push(row); }
    return rows;
  }

  function toPlaces(table) {
    const header = table[0];
    const idx = Object.fromEntries(header.map((h, i) => [h, i]));
    const get = (r, k) => (idx[k] == null ? '' : (r[idx[k]] ?? '')).trim();
    const num = (s) => (s === '' ? null : Number(s));
    const out = [];
    for (const r of table.slice(1)) {
      if (r.length < 3 || !get(r, 'bc_geographic_name')) continue;
      const lat = num(get(r, 'lat')), lon = num(get(r, 'lon'));
      if (lat == null || lon == null || Number.isNaN(lat) || Number.isNaN(lon)) continue;
      const type = get(r, 'geoname_type');
      out.push({
        id: Number(get(r, 'geoname_id')),
        name: get(r, 'bc_geographic_name'),
        type,
        cat: CATEGORY_OF_TYPE[type] || 'other',
        lat, lon,
        pop: num(get(r, 'place_population')),
        basis: get(r, 'place_population_basis'),
        source: get(r, 'place_population_source'),
        confidence: get(r, 'place_population_confidence'),
        csd: get(r, 'csd_name'),
        csdType: get(r, 'csd_type'),
        muni: get(r, 'muni_name'),
        latest: num(get(r, 'muni_population_latest')),
        latestYear: get(r, 'muni_latest_year'),
        reason: get(r, 'selected_because'),
        note: get(r, 'note'),
      });
    }
    return out;
  }

  /* ---------- State ---------- */
  const state = {
    places: [],
    byId: new Map(),
    query: '',
    cats: new Set(CATEGORIES.map((c) => c.key)),
    selected: null,
    hovered: null,
  };

  /* ---------- Map ---------- */
  const BC_BOUNDS = [[-139.5, 48.0], [-113.8, 60.2]];
  const map = new maplibregl.Map({
    container: 'map',
    style: STYLE[currentTheme()],
    bounds: BC_BOUNDS,
    fitBoundsOptions: { padding: 24 },
    minZoom: 3,
    maxZoom: 14,
    attributionControl: false,
    dragRotate: false,
    pitchWithRotate: false,
    touchPitch: false,
  });
  map.touchZoomRotate.disableRotation();
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-left');
  map.addControl(new maplibregl.AttributionControl({ compact: false }), 'bottom-left');

  const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, className: 'place-tip', anchor: 'bottom', maxWidth: 'none' });

  const radius = (pop) => Math.min(28, 3 + Math.sqrt(Math.max(0, pop || 0)) / 30);
  const RADIUS_EXPR = ['min', 28, ['+', 3, ['/', ['sqrt', ['max', 0, ['coalesce', ['get', 'pop'], 0]]], 30]]];
  const colorExpr = () => {
    const dark = currentTheme() === 'dark';
    const m = ['match', ['get', 'cat']];
    for (const c of CATEGORIES) m.push(c.key, dark ? c.dark : c.light);
    m.push(dark ? CATEGORIES[2].dark : CATEGORIES[2].light);
    return m;
  };
  const ringColor = () => (currentTheme() === 'dark' ? '#0c0c0c' : '#ffffff');

  function toGeoJSON(places) {
    return {
      type: 'FeatureCollection',
      features: places.map((p) => ({
        type: 'Feature',
        id: p.id,
        geometry: { type: 'Point', coordinates: [p.lon, p.lat] },
        properties: { id: p.id, name: p.name, type: p.type, cat: p.cat, pop: p.pop },
      })),
    };
  }

  // Fetched once, independently of style reloads; `addLayers` re-adds it from
  // here whenever `style.load` fires, same as everything else in this file.
  let boundary = null;
  fetch(BOUNDARY_URL)
    .then((r) => (r.ok ? r.json() : null))
    .then((d) => { boundary = d; if (map.isStyleLoaded()) addBoundaryLayer(); })
    .catch(() => {});

  function addBoundaryLayer() {
    if (!boundary || map.getSource('bc-boundary')) return;
    map.addSource('bc-boundary', { type: 'geojson', data: boundary });
    map.addLayer({
      id: 'bc-boundary-line',
      type: 'line',
      source: 'bc-boundary',
      paint: {
        'line-color': getComputedStyle(document.documentElement).getPropertyValue('--border-strong').trim() || 'rgba(0,0,0,0.3)',
        'line-width': 1.25,
      },
    });
  }

  let layersReady = false;
  function addLayers() {
    // Called on every style load: setStyle() drops custom sources and layers.
    addBoundaryLayer(); // added first so points draw on top of it
    if (!map.getSource('places')) {
      map.addSource('places', { type: 'geojson', data: toGeoJSON(visiblePlaces()), promoteId: 'id' });
    }
    const color = colorExpr();
    if (!map.getLayer('places')) {
      map.addLayer({
        id: 'places',
        type: 'circle',
        source: 'places',
        layout: { 'circle-sort-key': ['*', -1, ['coalesce', ['get', 'pop'], 0]] },
        paint: {
          'circle-radius': RADIUS_EXPR,
          'circle-color': color,
          'circle-opacity': ['case', ['boolean', ['feature-state', 'hover'], false], 0.85, 0.5],
          'circle-stroke-width': 1.25,
          'circle-stroke-color': color,
          'circle-stroke-opacity': 0.9,
        },
      });
    }
    if (!map.getLayer('places-selected')) {
      map.addLayer({
        id: 'places-selected',
        type: 'circle',
        source: 'places',
        filter: ['==', ['get', 'id'], state.selected ?? -1],
        paint: {
          'circle-radius': RADIUS_EXPR,
          'circle-color': color,
          'circle-opacity': 0.95,
          'circle-stroke-width': 2.5,
          'circle-stroke-color': ringColor(),
        },
      });
    }
    layersReady = true;
  }
  map.on('style.load', addLayers);

  function syncMapData() {
    if (!layersReady) return;
    const src = map.getSource('places');
    if (src) src.setData(toGeoJSON(visiblePlaces()));
    map.setFilter('places-selected', ['==', ['get', 'id'], state.selected ?? -1]);
  }

  function tooltipHtml(p) {
    return `<div class="tip__name">${esc(p.name)}</div>` +
      `<div class="tip__meta"><span>${esc(p.type)}</span><span class="tip__sep">·</span>` +
      `<span class="tip__pop">${fmt(p.pop)}</span><span>people</span></div>`;
  }

  function setHover(id) {
    if (state.hovered === id) return;
    if (state.hovered != null) map.setFeatureState({ source: 'places', id: state.hovered }, { hover: false });
    state.hovered = id;
    if (id == null) { popup.remove(); map.getCanvas().style.cursor = ''; return; }
    map.setFeatureState({ source: 'places', id }, { hover: true });
    const p = state.byId.get(id);
    if (!p) return;
    map.getCanvas().style.cursor = 'pointer';
    popup.setLngLat([p.lon, p.lat]).setOffset([0, -(radius(p.pop) + 4)]).setHTML(tooltipHtml(p)).addTo(map);
  }

  map.on('mousemove', 'places', (e) => {
    const f = e.features && e.features[0];
    if (f) setHover(Number(f.id));
  });
  map.on('mouseleave', 'places', () => setHover(null));
  map.on('click', (e) => {
    const hits = map.queryRenderedFeatures(e.point, { layers: ['places'] });
    if (hits.length) select(Number(hits[0].id), { fly: false });
    else clearSelection();
  });

  /* ---------- Filtering ---------- */
  function visiblePlaces() {
    const q = state.query.trim().toLowerCase();
    return state.places.filter((p) =>
      state.cats.has(p.cat) && (!q || p.name.toLowerCase().includes(q) || p.type.toLowerCase().includes(q))
    );
  }

  function render() {
    const vis = visiblePlaces().sort((a, b) => (b.pop || 0) - (a.pop || 0) || a.name.localeCompare(b.name));

    syncMapData();

    // Stats
    $('stat-count').textContent = fmt(vis.length);
    $('stat-pop').textContent = fmt(vis.reduce((s, p) => s + (p.pop || 0), 0));

    // List
    const list = $('list');
    if (!vis.length) {
      list.innerHTML = '<div class="list__state">No places match.</div>';
      return;
    }
    const frag = document.createDocumentFragment();
    const groups = [
      { label: 'Over 10,000', test: (p) => (p.pop || 0) >= 10000 },
      { label: '1,000 – 10,000', test: (p) => (p.pop || 0) >= 1000 },
      { label: 'Under 1,000', test: () => true },
    ];
    let gi = 0, opened = null;
    for (const p of vis) {
      while (!groups[gi].test(p)) gi++;
      if (opened !== gi) {
        const h = document.createElement('div');
        h.className = 'list__group';
        h.textContent = groups[gi].label;
        frag.appendChild(h);
        opened = gi;
      }
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'row';
      b.setAttribute('role', 'option');
      b.setAttribute('aria-selected', String(state.selected === p.id));
      b.dataset.id = p.id;
      b.innerHTML =
        `<span class="dot dot--${p.cat}"></span>` +
        `<span class="row__name">${esc(p.name)}<span class="row__type">${esc(p.type)}</span></span>` +
        `<span class="row__pop">${fmt(p.pop)}</span>`;
      frag.appendChild(b);
    }
    list.replaceChildren(frag);
  }

  /* ---------- Selection ---------- */
  function select(id, { fly = true } = {}) {
    state.selected = id;
    const p = id != null ? state.byId.get(id) : null;
    if (layersReady) map.setFilter('places-selected', ['==', ['get', 'id'], p ? p.id : -1]);

    try { history.replaceState(null, '', p ? `#${p.id}` : location.pathname + location.search); } catch (_) {}
    if (!p) { $('detail').hidden = true; syncListSelection(); return; }
    if (fly) map.flyTo({ center: [p.lon, p.lat], zoom: Math.max(map.getZoom(), 8.5), duration: 700, essential: true });

    showDetail(p);
    syncListSelection();
  }

  function clearSelection() {
    if (state.selected == null) return;
    select(null);
  }

  function syncListSelection() {
    for (const el of document.querySelectorAll('.row')) {
      const on = Number(el.dataset.id) === state.selected;
      el.setAttribute('aria-selected', String(on));
      if (on) el.scrollIntoView({ block: 'nearest' });
    }
  }

  function showDetail(p) {
    $('d-dot').className = `dot dot--${p.cat}`;
    $('d-type').textContent = p.type;
    $('d-name').textContent = p.name;
    $('d-pop').textContent = fmt(p.pop);
    $('d-basis').textContent = BASIS_LABEL[p.basis] || p.basis || '—';

    const rows = [
      ['Source', p.source],
      ['Confidence', p.confidence ? p.confidence[0].toUpperCase() + p.confidence.slice(1) : ''],
      ['Subdivision', p.csd && p.csd !== p.name ? `${p.csd}${p.csdType ? ` · ${p.csdType}` : ''}` : (p.csd ? p.csdType : '')],
      ['Municipality', p.muni && p.muni !== p.name ? p.muni : ''],
      [p.latestYear ? `${p.latestYear} estimate` : '', p.latest != null ? fmt(p.latest) : ''],
      ['Shortlisted for', p.reason ? p.reason.replace(/\+/g, ' and ').replace(/>/g, ' > ') : ''],
      ['Coordinates', `${p.lat.toFixed(4)}, ${p.lon.toFixed(4)}`],
      ['Geoname ID', String(p.id)],
    ].filter(([k, v]) => k && v);

    const grid = $('d-grid');
    grid.replaceChildren();
    for (const [k, v] of rows) {
      const dt = document.createElement('dt'); dt.textContent = k;
      const dd = document.createElement('dd'); dd.textContent = v;
      grid.append(dt, dd);
    }
    $('d-note').textContent = p.note ? p.note[0].toUpperCase() + p.note.slice(1) + (/[.!?]$/.test(p.note) ? '' : '.') : '';
    $('detail').hidden = false;
  }

  /* ---------- Chips & legend ---------- */
  function buildChips() {
    const counts = {};
    for (const p of state.places) counts[p.cat] = (counts[p.cat] || 0) + 1;
    const chips = $('chips');
    chips.replaceChildren();
    for (const c of CATEGORIES) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'chip';
      b.setAttribute('aria-pressed', 'true');
      b.innerHTML = `<span class="dot dot--${c.key}"></span>${esc(c.label)}<span class="chip__count">${fmt(counts[c.key] || 0)}</span>`;
      b.addEventListener('click', () => {
        if (state.cats.has(c.key)) {
          // Never let the map go empty: the last active chip stays on.
          if (state.cats.size === 1) return;
          state.cats.delete(c.key);
        } else {
          state.cats.add(c.key);
        }
        b.setAttribute('aria-pressed', String(state.cats.has(c.key)));
        const sel = state.selected != null ? state.byId.get(state.selected) : null;
        if (sel && !state.cats.has(sel.cat)) clearSelection();
        render();
      });
      chips.appendChild(b);
    }

    const legend = $('legend');
    legend.replaceChildren();
    for (const c of CATEGORIES) {
      const div = document.createElement('div');
      div.className = 'legend__item';
      div.innerHTML = `<span class="dot dot--${c.key}"></span><strong>${esc(c.label)}</strong>`;
      legend.appendChild(div);
    }
    const hint = document.createElement('div');
    hint.className = 'legend__hint';
    hint.textContent = 'Dot area scales with population';
    legend.appendChild(hint);
  }

  /* ---------- Events ---------- */
  $('search').addEventListener('input', (e) => { state.query = e.target.value; render(); });
  $('list').addEventListener('click', (e) => {
    const row = e.target.closest('.row');
    if (row) select(Number(row.dataset.id), { fly: true });
  });
  $('detail-close').addEventListener('click', clearSelection);

  document.addEventListener('keydown', (e) => {
    const typing = e.target instanceof HTMLInputElement;
    if (e.key === '/' && !typing) { e.preventDefault(); $('search').focus(); $('search').select(); }
    if (e.key === 'Escape') {
      if (typing && $('search').value) { $('search').value = ''; state.query = ''; render(); }
      else clearSelection();
    }
  });

  function applyTheme() {
    // A new style drops our layers; 'style.load' puts them back with this theme's colours.
    layersReady = false;
    setHover(null);
    map.setStyle(STYLE[currentTheme()]);
  }
  $('theme').addEventListener('click', () => {
    const next = currentTheme() === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem('cbc-theme', next); } catch (_) {}
    applyTheme();
  });
  mql.addEventListener('change', applyTheme);

  /* ---------- Boot ---------- */
  fetch(CSV_URL)
    .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.text(); })
    .then((text) => {
      state.places = toPlaces(parseCSV(text));
      state.byId = new Map(state.places.map((p) => [p.id, p]));
      buildChips();
      render();
      if (state.places.length) {
        const b = new maplibregl.LngLatBounds();
        for (const p of state.places) b.extend([p.lon, p.lat]);
        map.fitBounds(b, { padding: 32, duration: 0 });
      }
      // Deep link: /webapp/#40540 opens that place.
      const linked = Number(location.hash.slice(1));
      if (linked && state.byId.has(linked)) {
        const p = state.byId.get(linked);
        map.jumpTo({ center: [p.lon, p.lat], zoom: 8.5 });
        select(linked, { fly: false });
      }
    })
    .catch((err) => {
      console.error(err);
      $('list').innerHTML =
        '<div class="list__state">Couldn’t load the shortlist CSV.<br>Serve the repo over HTTP from its root:' +
        '<br><code>python3 -m http.server 8000</code><br>then open <code>localhost:8000/webapp/</code></div>';
      $('stat-count').textContent = '0';
      $('stat-pop').textContent = '0';
    });

  // Console handle for poking at the map: cbc.select(40540), cbc.state, cbc.map.
  window.cbc = { map, state, select };
})();
