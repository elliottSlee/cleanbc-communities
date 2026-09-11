/* Service-area selector.

   Reads pipeline/out/service_areas.json - the output of pipeline/06_basins.py -
   and lets a contractor describe where they will travel to work by taking
   commute basins rather than municipalities.

   The one idea the whole file turns on: the selection is not a list of places.
   It is a small set of decisions - which basins you took, which sub-locales you
   unticked inside them, which strays you added, and which kinds of travel you
   are willing to do - and the list of places is recomputed from those. That is
   why turning "ferries" off drops Hornby Island without forgetting that you had
   also unticked Merville, and why a selection fits in a shareable URL. */

(function () {
  'use strict';

  const DATA_URL = '../pipeline/out/service_areas.json';
  const STYLE = {
    light: 'https://tiles.openfreemap.org/styles/positron',
    dark: 'https://tiles.openfreemap.org/styles/dark',
  };

  // The three kinds of travel a contractor opts into, in the order the
  // sidebar lists them. `road` is not here because it is never optional.
  const BARRIERS = [
    { key: 'ferry', label: 'Ferry or water access', toggle: 't-ferry', count: 'n-ferry' },
    { key: 'pass', label: 'Mountain pass', toggle: 't-pass', count: 'n-pass' },
    { key: 'remote', label: 'Resource road or fly-in', toggle: 't-remote', count: 'n-remote' },
  ];
  const ACCESS_COLOR = {
    road: 'var(--c-road)', ferry: 'var(--c-ferry)',
    pass: 'var(--c-pass)', remote: 'var(--c-remote)',
  };
  const ACCESS_LABEL = {
    road: 'Road', ferry: 'Ferry', pass: 'Pass', remote: 'Remote',
  };

  const $ = (id) => document.getElementById(id);
  const fmt = (n) => (n == null || Number.isNaN(n)) ? '—' : n.toLocaleString('en-CA');
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  const CHEVRON =
    '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
    'stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<path d="m9 6 6 6-6 6"/></svg>';

  /* ---------- State ---------- */
  const state = {
    regions: [], basins: new Map(), places: new Map(),
    allow: { ferry: false, pass: false, remote: false },
    taken: new Set(),     // basin keys the contractor took whole
    excluded: new Set(),  // place ids unticked inside a taken basin
    included: new Set(),  // place ids taken without their basin
    query: '',
    focus: null,          // basin key in the detail card
  };

  const barrierOK = (access) => access === 'road' || state.allow[access] === true;
  const basinOK = (b) => barrierOK(b.access);
  // A place is reachable only if both its basin and its own access clear: the
  // Gulf Islands are a sailing to get to, and Gwaii Haanas is a boat once you
  // are there.
  const placeOK = (p) => basinOK(state.basins.get(p.basin)) && barrierOK(p.access);

  /** The selected place ids, recomputed from the decisions above. */
  function selection() {
    const out = new Set();
    for (const key of state.taken) {
      const b = state.basins.get(key);
      if (!b || !basinOK(b)) continue;
      for (const p of b.members) {
        if (barrierOK(p.access) && !state.excluded.has(p.id)) out.add(p.id);
      }
    }
    for (const id of state.included) {
      const p = state.places.get(id);
      if (p && placeOK(p)) out.add(id);
    }
    return out;
  }

  /** none | some | all, over the places in `b` that the toggles currently allow. */
  function basinFill(b, sel) {
    if (!basinOK(b)) return 'none';
    let n = 0, on = 0;
    for (const p of b.members) {
      if (!barrierOK(p.access)) continue;
      n++;
      if (sel.has(p.id)) on++;
    }
    if (!n || !on) return 'none';
    return on === n ? 'all' : 'some';
  }

  function takeBasin(key, on) {
    const b = state.basins.get(key);
    if (!b || !basinOK(b)) return;
    for (const p of b.members) { state.excluded.delete(p.id); state.included.delete(p.id); }
    if (on) state.taken.add(key); else state.taken.delete(key);
  }

  function takePlace(id, on) {
    const p = state.places.get(id);
    if (!p || !placeOK(p)) return;
    const taken = state.taken.has(p.basin);
    if (on) {
      if (taken) state.excluded.delete(id); else state.included.add(id);
    } else {
      if (taken) state.excluded.add(id); else state.included.delete(id);
    }
  }

  /* ---------- Data ---------- */
  function ingest(doc) {
    const f = Object.fromEntries(doc.fields.map((k, i) => [k, i]));
    state.regions = doc.regions;
    for (const b of doc.basins) state.basins.set(b.key, { ...b, members: [] });
    for (const row of doc.places) {
      const p = {
        id: row[f.id], name: row[f.name], type: row[f.type],
        lat: row[f.lat], lon: row[f.lon], pop: row[f.pop],
        basin: row[f.basin], access: row[f.access], isHub: !!row[f.isHub],
      };
      state.places.set(p.id, p);
      const b = state.basins.get(p.basin);
      if (b) b.members.push(p);
    }
  }

  /* ---------- URL and storage ---------- */
  const KEY = 'cbc-service-area';

  function encodeState() {
    const t = BARRIERS.filter((x) => state.allow[x.key]).map((x) => x.key[0]).join('');
    const parts = [];
    if (state.taken.size) parts.push('b=' + [...state.taken].join(','));
    if (state.excluded.size) parts.push('x=' + [...state.excluded].join(','));
    if (state.included.size) parts.push('i=' + [...state.included].join(','));
    if (t) parts.push('t=' + t);
    return parts.join('&');
  }

  function decodeState(hash) {
    const q = new URLSearchParams(hash.replace(/^#/, ''));
    if (![...q.keys()].length) return false;
    const t = q.get('t') || '';
    for (const b of BARRIERS) state.allow[b.key] = t.includes(b.key[0]);
    const nums = (s) => (s ? s.split(',').map(Number).filter((n) => state.places.has(n)) : []);
    state.taken = new Set((q.get('b') || '').split(',').filter((k) => state.basins.has(k)));
    state.excluded = new Set(nums(q.get('x')));
    state.included = new Set(nums(q.get('i')));
    return true;
  }

  function persist() {
    const s = encodeState();
    try { history.replaceState(null, '', s ? '#' + s : location.pathname); } catch (_) {}
    try { localStorage.setItem(KEY, s); } catch (_) {}
  }

  /* ---------- Map ---------- */
  const BC_BOUNDS = [[-139.5, 48.0], [-113.8, 60.2]];
  const mql = window.matchMedia('(prefers-color-scheme: dark)');
  const currentTheme = () => {
    const t = document.documentElement.dataset.theme;
    return (t === 'dark' || t === 'light') ? t : (mql.matches ? 'dark' : 'light');
  };

  const map = new maplibregl.Map({
    container: 'map', style: STYLE[currentTheme()],
    bounds: BC_BOUNDS, fitBoundsOptions: { padding: 24 },
    minZoom: 3, maxZoom: 14,
    attributionControl: false, dragRotate: false,
    pitchWithRotate: false, touchPitch: false,
  });
  map.touchZoomRotate.disableRotation();
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-left');
  map.addControl(new maplibregl.AttributionControl({ compact: false }), 'bottom-left');

  const popup = new maplibregl.Popup({
    closeButton: false, closeOnClick: false, className: 'place-tip',
    anchor: 'bottom', maxWidth: 'none',
  });

  // Read the palette out of the stylesheet so the two files cannot drift, and
  // so a theme change picks up the dark variants.
  function colors() {
    const cs = getComputedStyle(document.documentElement);
    const out = {};
    for (const k of Object.keys(ACCESS_COLOR)) {
      out[k] = cs.getPropertyValue('--c-' + k).trim() || '#888';
    }
    out.muted = cs.getPropertyValue('--text-3').trim() || '#999';
    out.ring = cs.getPropertyValue('--ring').trim() || '#fff';
    return out;
  }

  const RADIUS = ['min', 22, ['+', 2.5, ['/', ['sqrt', ['max', 0, ['coalesce', ['get', 'pop'], 0]]], 34]]];
  const accessColorExpr = (c) => ['match', ['get', 'access'],
    'ferry', c.ferry, 'pass', c.pass, 'remote', c.remote, c.road];

  const geo = (places, extra) => ({
    type: 'FeatureCollection',
    features: places.map((p) => ({
      type: 'Feature', id: p.id,
      geometry: { type: 'Point', coordinates: [p.lon, p.lat] },
      properties: {
        id: p.id, name: p.name, pop: p.pop || 0, access: p.access,
        basin: p.basin, ...(extra ? extra(p) : null),
      },
    })),
  });

  let layersReady = false;

  /** The two layers that do not depend on the selection. Kept separate
      because `style.load` can fire before the fetch resolves - and does, on a
      warm cache - which would otherwise build both from an empty state and
      leave the basemap with no dots and no hub labels for the whole session. */
  function refreshBaseData() {
    const all = map.getSource('sa-all');
    const hubsSrc = map.getSource('sa-hubs');
    if (all) all.setData(geo([...state.places.values()]));
    if (hubsSrc) {
      hubsSrc.setData(geo(
        [...state.basins.values()].map((b) => ({
          id: b.hubId, name: b.hub, lat: b.lat, lon: b.lon, pop: 0,
          access: b.access, basin: b.key,
        })),
        (h) => ({ label: state.basins.get(h.basin).label })));
    }
  }

  function addLayers() {
    const c = colors();

    if (!map.getSource('sa-all')) map.addSource('sa-all', { type: 'geojson', data: geo([]) });
    if (!map.getSource('sa-picked')) map.addSource('sa-picked', { type: 'geojson', data: geo([]) });
    if (!map.getSource('sa-hubs')) map.addSource('sa-hubs', { type: 'geojson', data: geo([]) });
    refreshBaseData();

    if (!map.getLayer('sa-all')) {
      map.addLayer({
        id: 'sa-all', type: 'circle', source: 'sa-all',
        paint: {
          'circle-radius': RADIUS, 'circle-color': c.muted,
          'circle-opacity': 0.22, 'circle-stroke-width': 0,
        },
      });
    }
    if (!map.getLayer('sa-picked')) {
      map.addLayer({
        id: 'sa-picked', type: 'circle', source: 'sa-picked',
        layout: { 'circle-sort-key': ['*', -1, ['coalesce', ['get', 'pop'], 0]] },
        paint: {
          'circle-radius': RADIUS,
          'circle-color': accessColorExpr(c),
          'circle-opacity': 0.6,
          'circle-stroke-width': 1.2,
          'circle-stroke-color': accessColorExpr(c),
          'circle-stroke-opacity': 0.95,
        },
      });
    }
    if (!map.getLayer('sa-hubs')) {
      map.addLayer({
        id: 'sa-hubs', type: 'circle', source: 'sa-hubs',
        paint: {
          'circle-radius': ['case', ['boolean', ['feature-state', 'taken'], false], 6, 3.5],
          'circle-color': ['case', ['boolean', ['feature-state', 'taken'], false],
            accessColorExpr(c), 'rgba(0,0,0,0)'],
          'circle-stroke-width': 1.5,
          'circle-stroke-color': ['case', ['boolean', ['feature-state', 'taken'], false],
            c.ring, c.muted],
        },
      });
      map.addLayer({
        id: 'sa-hub-labels', type: 'symbol', source: 'sa-hubs',
        minzoom: 5.2,
        layout: {
          'text-field': ['get', 'label'],
          'text-size': 11,
          'text-offset': [0, 1.1],
          'text-anchor': 'top',
          'text-allow-overlap': false,
          'text-font': ['Noto Sans Regular'],
        },
        paint: {
          'text-color': c.muted,
          'text-halo-color': c.ring,
          'text-halo-width': 1.4,
        },
      });
    }
    layersReady = true;
    syncMap();
  }
  map.on('style.load', addLayers);

  function syncMap() {
    if (!layersReady) return;
    const sel = selection();
    const picked = [...sel].map((id) => state.places.get(id)).filter(Boolean);
    map.getSource('sa-picked').setData(geo(picked));
    for (const b of state.basins.values()) {
      map.setFeatureState({ source: 'sa-hubs', id: b.hubId }, { taken: state.taken.has(b.key) });
    }
  }

  map.on('mousemove', ['sa-picked', 'sa-all', 'sa-hubs'], (e) => {
    const f = e.features && e.features[0];
    if (!f) return;
    const p = state.places.get(Number(f.id));
    const b = state.basins.get(f.properties.basin);
    map.getCanvas().style.cursor = 'pointer';
    popup.setLngLat(e.lngLat).setOffset([0, -10]).setHTML(
      `<div class="tip__name">${esc(p ? p.name : f.properties.name)}</div>` +
      `<div class="tip__meta"><span>${esc(b ? b.label : '')}</span>` +
      (p && p.pop != null ? `<span class="tip__sep">·</span><span class="tip__pop">${fmt(p.pop)}</span><span>people</span>` : '') +
      `</div>`
    ).addTo(map);
  });
  map.on('mouseleave', ['sa-picked', 'sa-all', 'sa-hubs'], () => {
    popup.remove();
    map.getCanvas().style.cursor = '';
  });
  map.on('click', (e) => {
    const hits = map.queryRenderedFeatures(e.point, {
      layers: ['sa-hubs', 'sa-picked', 'sa-all'].filter((l) => map.getLayer(l)),
    });
    if (!hits.length) { closeDetail(); return; }
    showBasin(hits[0].properties.basin);
  });

  /* ---------- Tree ---------- */
  const nodes = { regions: new Map(), basins: new Map() };

  function tag(access) {
    if (access === 'road') return '';
    return `<span class="sa-tag sa-tag--${access}">${esc(ACCESS_LABEL[access])}</span>`;
  }

  function buildTree() {
    const tree = $('tree');
    tree.replaceChildren();
    for (const r of state.regions) {
      const sec = document.createElement('section');
      sec.className = 'sa-region';

      const head = document.createElement('div');
      head.className = 'sa-row';
      head.innerHTML =
        `<button class="sa-disclose" type="button" aria-expanded="false" aria-label="Expand ${esc(r.label)}">${CHEVRON}</button>` +
        `<input class="sa-box" type="checkbox" aria-label="Select every basin in ${esc(r.label)}" />` +
        `<span class="sa-label"><span class="sa-name">${esc(r.label)}</span></span>` +
        `<span class="sa-meta">${r.basins.length} basins</span>`;
      sec.appendChild(head);

      const body = document.createElement('div');
      body.className = 'sa-basins';
      body.hidden = true;
      sec.appendChild(body);

      const disclose = head.querySelector('.sa-disclose');
      const box = head.querySelector('.sa-box');
      disclose.addEventListener('click', () => {
        const open = disclose.getAttribute('aria-expanded') === 'true';
        disclose.setAttribute('aria-expanded', String(!open));
        body.hidden = open;
      });
      box.addEventListener('change', () => {
        for (const key of r.basins) takeBasin(key, box.checked);
        commit();
      });

      for (const key of r.basins) body.appendChild(buildBasin(state.basins.get(key)));
      nodes.regions.set(r.key, { sec, head, box, body, disclose, region: r });
      tree.appendChild(sec);
    }
  }

  function buildBasin(b) {
    const wrap = document.createElement('div');
    wrap.className = 'sa-basin';

    const head = document.createElement('div');
    head.className = 'sa-row';
    head.innerHTML =
      `<button class="sa-disclose" type="button" aria-expanded="false" aria-label="Show the places in ${esc(b.label)}">${CHEVRON}</button>` +
      `<input class="sa-box" type="checkbox" aria-label="Take ${esc(b.label)}" />` +
      `<span class="sa-label"><span class="sa-name">${esc(b.label)}</span>${tag(b.access)}</span>` +
      `<span class="sa-meta">${fmt(b.places)}</span>`;
    wrap.appendChild(head);

    const note = document.createElement('p');
    note.className = 'sa-basin__note';
    note.textContent = b.note;
    note.hidden = true;
    wrap.appendChild(note);

    const list = document.createElement('div');
    list.className = 'sa-places';
    list.hidden = true;
    wrap.appendChild(list);

    const disclose = head.querySelector('.sa-disclose');
    const box = head.querySelector('.sa-box');
    disclose.addEventListener('click', () => {
      const open = disclose.getAttribute('aria-expanded') === 'true';
      disclose.setAttribute('aria-expanded', String(!open));
      note.hidden = open;
      list.hidden = open;
      if (!open) { fillPlaces(b, list); syncBasin(b, selection()); }
    });
    box.addEventListener('change', () => { takeBasin(b.key, box.checked); commit(); });
    head.querySelector('.sa-name').addEventListener('click', () => showBasin(b.key));

    const node = { wrap, head, box, note, list, disclose, filled: false, rows: new Map() };
    nodes.basins.set(b.key, node);
    return wrap;
  }

  function fillPlaces(b, list) {
    const node = nodes.basins.get(b.key);
    if (node.filled) return;
    const frag = document.createDocumentFragment();
    for (const p of b.members) {
      const row = document.createElement('div');
      row.className = 'sa-place' + (p.isHub ? ' sa-place--hub' : '');
      row.innerHTML =
        `<input class="sa-box" type="checkbox" aria-label="${esc(p.name)}" />` +
        `<span class="sa-label"><span class="sa-name">${esc(p.name)}</span>` +
        (p.isHub ? '<span class="sa-sub">hub</span>' : '') + tag(p.access) + `</span>` +
        `<span class="sa-meta">${p.pop == null ? '—' : fmt(p.pop)}</span>`;
      const box = row.querySelector('.sa-box');
      box.addEventListener('change', () => { takePlace(p.id, box.checked); commit(); });
      node.rows.set(p.id, { row, box, place: p });
      frag.appendChild(row);
    }
    list.replaceChildren(frag);
    node.filled = true;
  }

  /* ---------- Sync ---------- */
  function syncBasin(b, sel) {
    const n = nodes.basins.get(b.key);
    const fill = basinFill(b, sel);
    const ok = basinOK(b);
    n.box.disabled = !ok;
    n.box.checked = fill === 'all';
    n.box.indeterminate = fill === 'some';
    n.head.querySelector('.sa-label').classList.toggle('sa-label--off', !ok);
    let on = 0;
    for (const p of b.members) if (sel.has(p.id)) on++;
    n.head.querySelector('.sa-meta').textContent =
      on ? `${fmt(on)} / ${fmt(b.places)}` : fmt(b.places);
    if (!n.filled) return;
    for (const { box, place } of n.rows.values()) {
      const reachable = placeOK(place);
      box.disabled = !reachable;
      box.checked = sel.has(place.id);
      box.parentElement.querySelector('.sa-label')
        .classList.toggle('sa-label--off', !reachable);
    }
  }

  function syncTree(sel) {
    for (const b of state.basins.values()) syncBasin(b, sel);
    for (const { box, region } of nodes.regions.values()) {
      const usable = region.basins.map((k) => state.basins.get(k)).filter(basinOK);
      const fills = usable.map((b) => basinFill(b, sel));
      const all = fills.length && fills.every((f) => f === 'all');
      const none = !fills.length || fills.every((f) => f === 'none');
      box.disabled = !usable.length;
      box.checked = all;
      box.indeterminate = !all && !none;
    }
  }

  function syncSummary(sel) {
    let pop = 0;
    for (const id of sel) pop += state.places.get(id).pop || 0;
    const basins = [...state.basins.values()]
      .filter((b) => basinFill(b, sel) !== 'none').length;
    $('sum-basins').textContent = fmt(basins);
    $('sum-places').textContent = fmt(sel.size);
    $('sum-pop').textContent = fmt(pop);

    const blocked = [];
    for (const bar of BARRIERS) {
      if (state.allow[bar.key]) continue;
      let n = 0;
      for (const b of state.basins.values()) {
        if (!state.taken.has(b.key)) continue;
        if (b.access === bar.key) { n += b.members.length; continue; }
        if (!basinOK(b)) continue;
        for (const p of b.members) if (p.access === bar.key) n++;
      }
      if (n) blocked.push(`${fmt(n)} behind ${bar.label.toLowerCase()}`);
    }
    // Two different reasons a place is missing, and a contractor needs to be
    // able to tell them apart: a barrier they have not opted into, or a
    // sub-locale they unticked themselves.
    const dropped = [...state.excluded].filter((id) => {
      const p = state.places.get(id);
      return p && state.taken.has(p.basin) && barrierOK(p.access);
    }).length;
    if (dropped) blocked.push(`${fmt(dropped)} you removed by hand`);
    $('sum-hint').textContent = !sel.size
      ? 'Nothing selected yet. Open a region and take a basin.'
      : (blocked.length ? 'Not included: ' + blocked.join(', ') + '.'
        : 'Every place in the basins you took is included.');

    $('clear').disabled = !sel.size && !state.taken.size;
    $('download').disabled = !sel.size;
    $('copy-link').disabled = !sel.size;
  }

  function syncBarrierCounts() {
    for (const bar of BARRIERS) {
      let n = 0;
      for (const b of state.basins.values()) {
        if (b.access === bar.key) { n += b.members.length; continue; }
        for (const p of b.members) if (p.access === bar.key) n++;
      }
      $(bar.count).textContent = fmt(n);
    }
  }

  function commit() {
    const sel = selection();
    syncTree(sel);
    syncSummary(sel);
    syncMap();
    if (state.focus) showBasin(state.focus, { quiet: true });
    persist();
  }

  /* ---------- Detail card ---------- */
  function showBasin(key, { quiet = false } = {}) {
    const b = state.basins.get(key);
    if (!b) return;
    state.focus = key;
    const sel = selection();
    let on = 0, pop = 0;
    const byAccess = {};
    for (const p of b.members) {
      byAccess[p.access] = (byAccess[p.access] || 0) + 1;
      if (sel.has(p.id)) { on++; pop += p.pop || 0; }
    }
    const region = state.regions.find((r) => r.key === b.region);
    $('d-region').textContent = region ? region.label : '';
    $('d-name').textContent = b.label;
    $('d-pop').textContent = fmt(on ? pop : b.population);
    const pill = $('d-access');
    pill.textContent = b.access === 'road' ? 'Road access' : ACCESS_LABEL[b.access] + ' access';
    $('d-note').textContent = b.note;

    const rows = [
      ['Hub', b.hub],
      ['Places', `${fmt(on)} of ${fmt(b.places)} selected`],
      ['Ferry-dependent', byAccess.ferry ? fmt(byAccess.ferry) : ''],
      ['Resource road or fly-in', byAccess.remote ? fmt(byAccess.remote) : ''],
    ].filter(([, v]) => v);
    const grid = $('d-grid');
    grid.replaceChildren();
    for (const [k, v] of rows) {
      const dt = document.createElement('dt'); dt.textContent = k;
      const dd = document.createElement('dd'); dd.textContent = v;
      grid.append(dt, dd);
    }

    const take = $('d-take');
    const ok = basinOK(b);
    const taken = state.taken.has(b.key);
    take.disabled = !ok;
    take.textContent = !ok
      ? `Turn on ${ACCESS_LABEL[b.access].toLowerCase()} travel to take this`
      : (taken ? 'Remove this basin' : 'Add this basin');
    take.onclick = () => { takeBasin(b.key, !taken); commit(); };
    $('detail').hidden = false;

    if (!quiet) {
      map.flyTo({ center: [b.lon, b.lat], zoom: Math.max(map.getZoom(), 7.2), duration: 600, essential: true });
      const n = nodes.basins.get(key);
      const r = nodes.regions.get(b.region);
      if (r && r.body.hidden) { r.body.hidden = false; r.disclose.setAttribute('aria-expanded', 'true'); }
      if (n) n.head.scrollIntoView({ block: 'nearest' });
    }
  }

  function closeDetail() { state.focus = null; $('detail').hidden = true; }

  /* ---------- Search ---------- */
  function applySearch() {
    const q = state.query.trim().toLowerCase();
    const sel = selection();
    for (const r of state.regions) {
      const rn = nodes.regions.get(r.key);
      let anyRegion = !q;
      for (const key of r.basins) {
        const b = state.basins.get(key);
        const n = nodes.basins.get(key);
        if (!q) { n.wrap.hidden = false; continue; }
        const hitBasin = b.label.toLowerCase().includes(q) || b.hub.toLowerCase().includes(q);
        const hitPlace = !hitBasin && b.members.some((p) => p.name.toLowerCase().includes(q));
        const hit = hitBasin || hitPlace;
        n.wrap.hidden = !hit;
        if (hit) {
          anyRegion = true;
          if (hitPlace) {
            // Open straight to the matching sub-locales: the point of the
            // search is to find a hamlet without knowing its basin.
            fillPlaces(b, n.list);
            syncBasin(b, sel);   // rows built just now have never been synced
            n.list.hidden = false;
            n.note.hidden = false;
            n.disclose.setAttribute('aria-expanded', 'true');
            for (const { row, place } of n.rows.values()) {
              row.hidden = !place.name.toLowerCase().includes(q);
            }
          } else if (n.filled) {
            for (const { row } of n.rows.values()) row.hidden = false;
          }
        }
      }
      rn.sec.hidden = !anyRegion;
      if (q && anyRegion) { rn.body.hidden = false; rn.disclose.setAttribute('aria-expanded', 'true'); }
    }
    if (!q) {
      for (const n of nodes.basins.values()) {
        if (n.filled) for (const { row } of n.rows.values()) row.hidden = false;
      }
    }
  }

  /* ---------- Export ---------- */
  const CSV_COLS = ['geoname_id', 'bc_geographic_name', 'geoname_type',
    'lat', 'lon', 'place_population', 'basin', 'basin_label', 'basin_hub',
    'macro_region', 'place_access'];

  function toCSV(sel) {
    const q = (v) => {
      const s = v == null ? '' : String(v);
      return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
    };
    const lines = [CSV_COLS.join(',')];
    const ordered = [...state.basins.values()].flatMap((b) =>
      b.members.filter((p) => sel.has(p.id)).map((p) => [p, b]));
    for (const [p, b] of ordered) {
      const region = state.regions.find((r) => r.key === b.region);
      lines.push([p.id, p.name, p.type, p.lat, p.lon, p.pop,
        b.key, b.label, b.hub, region ? region.label : '', p.access].map(q).join(','));
    }
    return lines.join('\n') + '\n';
  }

  function download() {
    const sel = selection();
    const blob = new Blob([toCSV(sel)], { type: 'text/csv;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'service-area.csv';
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  async function copyLink() {
    const q = encodeState();
    const url = location.origin + location.pathname + (q ? '#' + q : '');
    const btn = $('copy-link');
    const said = btn.textContent;
    try {
      await navigator.clipboard.writeText(url);
      btn.textContent = 'Copied';
    } catch (_) {
      // Clipboard access can be refused; the URL bar already holds the link.
      btn.textContent = 'In the URL bar';
    }
    setTimeout(() => { btn.textContent = said; }, 1600);
  }

  /* ---------- Legend ---------- */
  function buildLegend() {
    const legend = $('legend');
    legend.replaceChildren();
    for (const k of ['road', 'ferry', 'pass', 'remote']) {
      const div = document.createElement('div');
      div.className = 'legend__item';
      div.innerHTML = `<span class="legend__swatch" style="background:${ACCESS_COLOR[k]}"></span>` +
        `<strong>${esc(ACCESS_LABEL[k])}</strong>`;
      legend.appendChild(div);
    }
    const hint = document.createElement('div');
    hint.className = 'legend__hint';
    hint.textContent = 'Selected places only; dot area scales with population';
    legend.appendChild(hint);
  }

  /* ---------- Events ---------- */
  for (const bar of BARRIERS) {
    $(bar.toggle).addEventListener('change', (e) => {
      state.allow[bar.key] = e.target.checked;
      commit();
    });
  }
  $('search').addEventListener('input', (e) => { state.query = e.target.value; applySearch(); });
  $('detail-close').addEventListener('click', closeDetail);
  $('clear').addEventListener('click', () => {
    state.taken.clear(); state.excluded.clear(); state.included.clear();
    commit();
  });
  $('download').addEventListener('click', download);
  $('copy-link').addEventListener('click', copyLink);

  document.addEventListener('keydown', (e) => {
    const typing = e.target instanceof HTMLInputElement && e.target.type !== 'checkbox';
    if (e.key === '/' && !typing) { e.preventDefault(); $('search').focus(); $('search').select(); }
    if (e.key === 'Escape') {
      if (typing && $('search').value) { $('search').value = ''; state.query = ''; applySearch(); }
      else closeDetail();
    }
  });

  function applyTheme() {
    layersReady = false;
    popup.remove();
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
  fetch(DATA_URL)
    .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
    .then((doc) => {
      ingest(doc);
      let restored = decodeState(location.hash);
      if (!restored) {
        try { restored = decodeState('#' + (localStorage.getItem(KEY) || '')); } catch (_) {}
      }
      buildTree();
      buildLegend();
      for (const bar of BARRIERS) $(bar.toggle).checked = state.allow[bar.key];
      syncBarrierCounts();
      if (layersReady) syncMap();
      commit();
      if (restored && state.taken.size) {
        const first = state.basins.get([...state.taken][0]);
        if (first) showBasin(first.key);
      }
    })
    .catch((err) => {
      console.error(err);
      $('tree').innerHTML =
        '<div class="list__state">Couldn’t load <code>service_areas.json</code>.' +
        '<br>Build it with <code>make basins</code> in <code>pipeline/</code>,' +
        '<br>then serve the repository root:<br><code>python3 -m http.server 8000</code>' +
        '<br>and open <code>localhost:8000/webapp/service-areas.html</code></div>';
      $('sum-hint').textContent = 'No data loaded.';
    });

  // Console handle: sa.state, sa.selection(), sa.showBasin('comox-valley').
  window.sa = { map, state, selection, showBasin };
})();
