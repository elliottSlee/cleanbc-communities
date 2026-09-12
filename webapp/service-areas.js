/* Service-area selector.

   Reads pipeline/out/service_areas.json - the output of pipeline/06_basins.py -
   and lets a contractor describe where they will travel to work by taking
   commute basins rather than municipalities.

   The one idea the whole file turns on: the selection is not a list of places.
   It is a small set of decisions - which basins you took, which sub-locales you
   unticked inside them, and which strays you added - and the list of places is
   recomputed from those. That is why unticking Merville and then re-taking the
   Comox Valley does not quietly forget it, and why a selection fits in a
   shareable URL.

   Nothing here is gated. Every area in the province can be ticked, because a
   contractor on Haida Gwaii does not "take a ferry" to work - they live there,
   and a page that made them switch ferries on first would be telling them
   something false about their own commute. Instead the page watches what the
   selection commits to: the first pick is free, and a later pick that adds a
   ferry, a mountain pass or a fly-in route says so once and waits for an
   answer. Cancel leaves the box unticked. */

(function () {
  'use strict';

  const DATA_URL = '../pipeline/out/service_areas.json';
  const STYLE = {
    light: 'https://tiles.openfreemap.org/styles/positron',
    dark: 'https://tiles.openfreemap.org/styles/dark',
  };

  /* The travel a contractor can be asked about, in the order anything lists
     them. `road` is absent because nobody opts into a road.

     `line` finishes the sentence "Getting to <name> ...", so each one has to
     read as a fact about the trip rather than a warning about the contractor.
     `chip` is what the summary calls it once it is in the selection. */
  const TRAVEL = [
    { key: 'ferry',
      title: 'This one needs a ferry',
      line: 'means a sailing. There is a schedule and a fare, and a day’s work can turn into an overnight.',
      chip: 'reached by ferry' },
    { key: 'pass',
      title: 'This one is over a mountain pass',
      line: 'means a mountain pass — winter tyres from October to April, and it closes after a storm.',
      chip: 'over a pass' },
    { key: 'remote',
      title: 'This one is resource road or fly-in',
      line: 'means a resource road, a winter road or a float plane. There is no ordinary highway route in.',
      chip: 'resource road or fly-in' },
  ];
  const TRAVEL_BY = Object.fromEntries(TRAVEL.map((t) => [t.key, t]));
  const ACCESS_COLOR = {
    road: 'var(--c-road)', ferry: 'var(--c-ferry)',
    pass: 'var(--c-pass)', remote: 'var(--c-remote)',
  };
  const ACCESS_LABEL = {
    road: 'Road', ferry: 'Ferry', pass: 'Pass', remote: 'Remote',
  };

  const $ = (id) => document.getElementById(id);
  // One pane at a time below this width, which changes what a tap on a row
  // should do: there is no map beside the tree to point at.
  const narrow = window.matchMedia('(max-width: 760px)');
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
    // Travel the contractor has already agreed to, either by confirming it or
    // by opening with it. Not a filter: nothing is ever hidden or disabled
    // because of what is in here. It only decides whether to ask again.
    accepted: { ferry: false, pass: false, remote: false },
    taken: new Set(),     // basin keys the contractor took whole
    excluded: new Set(),  // place ids unticked inside a taken basin
    included: new Set(),  // place ids taken without their basin
    query: '',
    focus: null,          // basin key in the detail card
  };

  /** The selected place ids, recomputed from the decisions above. */
  function selection() {
    const out = new Set();
    for (const key of state.taken) {
      const b = state.basins.get(key);
      if (!b) continue;
      for (const p of b.members) if (!state.excluded.has(p.id)) out.add(p.id);
    }
    for (const id of state.included) if (state.places.has(id)) out.add(id);
    return out;
  }

  /** none | some | all, over every place in the basin. */
  function basinFill(b, sel) {
    let on = 0;
    for (const p of b.members) if (sel.has(p.id)) on++;
    if (!on) return 'none';
    return on === b.members.length ? 'all' : 'some';
  }

  function takeBasin(key, on) {
    const b = state.basins.get(key);
    if (!b) return;
    for (const p of b.members) { state.excluded.delete(p.id); state.included.delete(p.id); }
    if (on) state.taken.add(key); else state.taken.delete(key);
  }

  function takePlace(id, on) {
    const p = state.places.get(id);
    if (!p) return;
    const taken = state.taken.has(p.basin);
    if (on) {
      if (taken) state.excluded.delete(id); else state.included.add(id);
    } else {
      if (taken) state.excluded.add(id); else state.included.delete(id);
    }
  }

  /* ---------- Asking about travel ---------- */

  /** Every kind of travel a basin carries: its own, and its sub-locales'. */
  function travelOfBasin(b) {
    const out = new Set();
    if (b.access !== 'road') out.add(b.access);
    for (const p of b.members) if (p.access !== 'road') out.add(p.access);
    return out;
  }

  function travelOfPlace(p) {
    const out = new Set();
    const b = state.basins.get(p.basin);
    if (b && b.access !== 'road') out.add(b.access);
    if (p.access !== 'road') out.add(p.access);
    return out;
  }

  /** Of a set of travel kinds, the ones not yet agreed to, in TRAVEL order. */
  const unagreed = (kinds) =>
    TRAVEL.filter((t) => kinds.has(t.key) && !state.accepted[t.key]);

  const nothingPicked = () => !state.taken.size && !state.included.size;

  /** Ask before committing to travel, unless there is nothing to ask about.

      The exception is the whole point of this design: the very first pick
      never asks. Somebody whose service area starts at Alert Bay or Bella
      Bella is not opting into a boat, they are describing where they live,
      and being made to tick "I take ferries" first would be the page telling
      them they are unusual. */
  function withTravel(kinds, what, go) {
    const asking = unagreed(kinds);
    if (!asking.length) { go(); return; }
    if (nothingPicked()) { agree(asking); go(); return; }
    ask(asking, what).then((yes) => {
      if (yes) { agree(asking); go(); } else commit();   // snap the box back
    });
  }

  const agree = (list) => { for (const t of list) state.accepted[t.key] = true; };

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
    const t = TRAVEL.filter((x) => state.accepted[x.key]).map((x) => x.key[0]).join('');
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
    for (const b of TRAVEL) state.accepted[b.key] = t.includes(b.key[0]);
    const nums = (s) => (s ? s.split(',').map(Number).filter((n) => state.places.has(n)) : []);
    state.taken = new Set((q.get('b') || '').split(',').filter((k) => state.basins.has(k)));
    state.excluded = new Set(nums(q.get('x')));
    state.included = new Set(nums(q.get('i')));
    return true;
  }

  /** Whatever the restored selection already travels, the contractor has
      agreed to by arriving with it. This also carries over links made when
      `t` meant "ferries allowed" rather than "ferries agreed to": a shared
      area that crosses water does not interrogate whoever opens it. */
  function agreeToWhatIsAlreadyIn() {
    for (const id of selection()) {
      const p = state.places.get(id);
      if (p) agree(unagreed(travelOfPlace(p)));
    }
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

  /* The map is a second view of the selection, not what makes the selection
     work, so it is optional from here down. MapLibre needs WebGL and a 900 KB
     download; an old phone, a blocked CDN or a browser with WebGL turned off
     used to throw here and take the whole page with it, leaving a contractor
     staring at "Loading..." forever. Now the tree still builds and the Map tab
     goes away. */
  let map = null;
  try {
    map = new maplibregl.Map({
      container: 'map', style: STYLE[currentTheme()],
      bounds: BC_BOUNDS, fitBoundsOptions: { padding: 24 },
      minZoom: 3, maxZoom: 14,
      attributionControl: false, dragRotate: false,
      pitchWithRotate: false, touchPitch: false,
    });
    map.touchZoomRotate.disableRotation();
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-left');
    map.addControl(new maplibregl.AttributionControl({ compact: false }), 'bottom-left');
  } catch (err) {
    console.warn('No map on this browser; the selector works without it.', err);
    map = null;
  }
  const onMap = (...args) => { if (map) map.on(...args); };

  const popup = map ? new maplibregl.Popup({
    closeButton: false, closeOnClick: false, className: 'place-tip',
    anchor: 'bottom', maxWidth: 'none',
  }) : { setLngLat() { return this; }, setOffset() { return this; },
         setHTML() { return this; }, addTo() { return this; }, remove() {} };

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
  onMap('style.load', addLayers);

  function syncMap() {
    if (!layersReady) return;
    const sel = selection();
    const picked = [...sel].map((id) => state.places.get(id)).filter(Boolean);
    map.getSource('sa-picked').setData(geo(picked));
    for (const b of state.basins.values()) {
      map.setFeatureState({ source: 'sa-hubs', id: b.hubId }, { taken: state.taken.has(b.key) });
    }
  }

  onMap('mousemove', ['sa-picked', 'sa-all', 'sa-hubs'], (e) => {
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
  onMap('mouseleave', ['sa-picked', 'sa-all', 'sa-hubs'], () => {
    popup.remove();
    map.getCanvas().style.cursor = '';
  });
  onMap('click', (e) => {
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
      // The row says "Cariboo"; the tooltip says "Cariboo Regional District",
      // which is the name on the tax notice and the one to search for.
      head.innerHTML =
        `<button class="sa-disclose" type="button" aria-expanded="false" aria-label="Expand ${esc(r.label)}">${CHEVRON}</button>` +
        `<input class="sa-box" type="checkbox" aria-label="Select every area in ${esc(r.official || r.label)}" />` +
        `<span class="sa-label" title="${esc(r.official || r.label)}">` +
        `<span class="sa-name">${esc(r.label)}</span></span>` +
        `<span class="sa-meta">${fmt(r.places)}</span>`;
      sec.appendChild(head);

      const body = document.createElement('div');
      body.className = 'sa-basins';
      body.hidden = true;
      sec.appendChild(body);

      const disclose = head.querySelector('.sa-disclose');
      const box = head.querySelector('.sa-box');
      const flip = () => {
        const open = disclose.getAttribute('aria-expanded') === 'true';
        disclose.setAttribute('aria-expanded', String(!open));
        body.hidden = open;
      };
      disclose.addEventListener('click', flip);
      head.querySelector('.sa-label').addEventListener('click', flip);
      box.addEventListener('change', () => {
        const on = box.checked;
        const take = () => {
          for (const key of r.basins) takeBasin(key, on);
          commit();
        };
        if (!on) { take(); return; }
        const kinds = new Set();
        for (const key of r.basins) {
          for (const k of travelOfBasin(state.basins.get(key))) kinds.add(k);
        }
        withTravel(kinds, r.official || r.label, take);
      });

      for (const key of r.basins) body.appendChild(buildBasin(state.basins.get(key)));
      nodes.regions.set(r.key, {
        sec, head, box, body, disclose, region: r,
        meta: head.querySelector('.sa-meta'),
      });
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
    const flip = () => {
      const open = disclose.getAttribute('aria-expanded') === 'true';
      disclose.setAttribute('aria-expanded', String(!open));
      note.hidden = open;
      list.hidden = open;
      if (!open) { fillPlaces(b, list); syncBasin(b, selection()); }
    };
    disclose.addEventListener('click', flip);
    box.addEventListener('change', () => {
      const on = box.checked;
      const take = () => { takeBasin(b.key, on); commit(); };
      if (!on) { take(); return; }
      withTravel(travelOfBasin(b), b.label, take);
    });
    // On a phone the detail card lives on a view you cannot see from here, so
    // the name opens what is under it instead.
    head.querySelector('.sa-name').addEventListener('click', () => {
      if (narrow.matches) flip(); else showBasin(b.key);
    });

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
      box.addEventListener('change', () => {
        const on = box.checked;
        const take = () => { takePlace(p.id, on); commit(); };
        if (!on) { take(); return; }
        withTravel(travelOfPlace(p), p.name, take);
      });
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
    n.box.checked = fill === 'all';
    n.box.indeterminate = fill === 'some';
    let on = 0;
    for (const p of b.members) if (sel.has(p.id)) on++;
    n.head.querySelector('.sa-meta').textContent =
      on ? `${fmt(on)} / ${fmt(b.places)}` : fmt(b.places);
    if (!n.filled) return;
    for (const { box, place } of n.rows.values()) box.checked = sel.has(place.id);
  }

  function syncTree(sel) {
    for (const b of state.basins.values()) syncBasin(b, sel);
    for (const { box, meta, region } of nodes.regions.values()) {
      const fills = region.basins.map((k) => basinFill(state.basins.get(k), sel));
      const all = fills.length && fills.every((f) => f === 'all');
      const none = !fills.length || fills.every((f) => f === 'none');
      box.checked = all;
      box.indeterminate = !all && !none;
      let on = 0;
      for (const k of region.basins) {
        for (const p of state.basins.get(k).members) if (sel.has(p.id)) on++;
      }
      meta.textContent = on ? `${fmt(on)} / ${fmt(region.places)}` : fmt(region.places);
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

    // The only thing that can be missing now is a sub-locale the contractor
    // unticked themselves, so say so plainly rather than listing reasons.
    const dropped = [...state.excluded].filter((id) => {
      const p = state.places.get(id);
      return p && state.taken.has(p.basin);
    }).length;
    $('sum-hint').textContent = !sel.size
      ? 'Nothing selected yet. Open a regional district below and tick an area.'
      : (dropped
        ? `Everything in the areas you took, less ${fmt(dropped)} you removed by hand.`
        : 'Everything in the areas you took is included.');
    syncTravel(sel);

    $('clear').disabled = !sel.size && !state.taken.size;
    $('download').disabled = !sel.size;
    $('copy-link').disabled = !sel.size;
  }

  /** What the selection involves, counted from the places actually in it.
      This replaced three switches, and the difference matters: it reports the
      area a contractor described instead of deciding what they may describe. */
  function syncTravel(sel) {
    const strip = $('sum-travel');
    const counts = {};
    for (const id of sel) {
      for (const t of travelOfPlace(state.places.get(id))) {
        counts[t] = (counts[t] || 0) + 1;
      }
    }
    const chips = TRAVEL.filter((t) => counts[t.key]);
    strip.hidden = !chips.length;
    strip.replaceChildren();
    for (const t of chips) {
      const chip = document.createElement('span');
      chip.className = 'sa-travel__chip';
      chip.innerHTML =
        `<span class="sa-travel__dot" style="background:${ACCESS_COLOR[t.key]}"></span>` +
        `<span class="sa-travel__n">${fmt(counts[t.key])}</span> ${esc(t.chip)}`;
      strip.appendChild(chip);
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
    const taken = state.taken.has(b.key);
    take.textContent = taken ? 'Remove this area' : 'Add this area';
    take.onclick = () => {
      const go = () => { takeBasin(b.key, !taken); commit(); };
      if (taken) { go(); return; }
      withTravel(travelOfBasin(b), b.label, go);
    };
    $('detail').hidden = false;

    if (!quiet) {
      if (map) map.flyTo({ center: [b.lon, b.lat], zoom: Math.max(map.getZoom(), 7.2), duration: 600, essential: true });
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
      // A district matches by either name, and takes all its basins with it:
      // somebody typing "Kootenay Boundary" wants the district, not the two
      // basins whose labels happen to contain the word.
      const hitRegion = !!q && (r.label.toLowerCase().includes(q)
        || (r.official || '').toLowerCase().includes(q));
      let anyRegion = !q || hitRegion;
      for (const key of r.basins) {
        const b = state.basins.get(key);
        const n = nodes.basins.get(key);
        if (!q) { n.wrap.hidden = false; continue; }
        if (hitRegion) { n.wrap.hidden = false; continue; }
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
    'regional_district', 'place_access'];

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
        b.key, b.label, b.hub, region ? region.official : '', p.access].map(q).join(','));
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
  /* ---------- The dialog ---------- */
  /* A native <dialog> so the browser handles the backdrop, the focus trap and
     Escape. Escape closes with an empty returnValue, which is a Cancel, which
     is what Escape should mean when the question is "shall I add this?".
     Anything without showModal falls back to the browser's own confirm(). */
  const dlg = $('ask');
  let answer = null;

  function ask(list, what) {
    const many = list.length > 1;
    $('ask-title').textContent = many
      ? 'This one takes some getting to' : list[0].title;
    $('ask-body').textContent = many
      ? `Getting to ${what} is not a straight drive:`
      : `Getting to ${what} ${list[0].line}`;
    const ul = $('ask-list');
    ul.replaceChildren();
    if (many) {
      for (const t of list) {
        const li = document.createElement('li');
        li.innerHTML =
          `<span class="sa-travel__dot" style="background:${ACCESS_COLOR[t.key]}"></span>` +
          `<span><strong>${esc(ACCESS_LABEL[t.key])}</strong> — ${esc(detail(t))}</span>`;
        ul.appendChild(li);
      }
    }
    if (typeof dlg.showModal !== 'function') {
      // No <dialog> here. The browser's own confirm is uglier and every bit
      // as answerable, which is the only thing that matters.
      const lines = many ? '\n' + list.map((t) => '- ' + detail(t)).join('\n') : '';
      return Promise.resolve(window.confirm(
        `${$('ask-body').textContent}${lines}\n\nAdd it?`));
    }
    dlg.showModal();
    return new Promise((resolve) => { answer = resolve; });
  }

  // "means a sailing. ..." reads as a sentence after the name and as a phrase
  // after a bullet; this is the phrase.
  const detail = (t) => t.line.replace(/^means /, '');

  $('ask-ok').addEventListener('click', () => dlg.close('ok'));
  $('ask-cancel').addEventListener('click', () => dlg.close('cancel'));
  dlg.addEventListener('close', () => {
    const resolve = answer;
    answer = null;
    if (resolve) resolve(dlg.returnValue === 'ok');
  });

  /* The map is a second view of the selection, not the way into it. Switching
     is a phone concern; on a desktop both panes are on screen and `data-view`
     changes nothing. */
  const app = document.querySelector('.app');
  if (!map) {
    app.dataset.map = 'off';
    $('map').textContent = 'The map needs WebGL, which this browser is not giving it. Everything else works.';
  }
  function setView(view) {
    app.dataset.view = view;
    $('view-areas').setAttribute('aria-pressed', String(view === 'areas'));
    $('view-map').setAttribute('aria-pressed', String(view === 'map'));
    // The pane keeps its size in both views, so this is only insurance against
    // a switch that coincided with a rotation or a browser chrome change.
    if (view === 'map' && map) requestAnimationFrame(() => map.resize());
  }
  $('view-areas').addEventListener('click', () => setView('areas'));
  $('view-map').addEventListener('click', () => setView('map'));

  narrow.addEventListener('change', (e) => {
    if (!e.matches) setView('areas');
    else if (map) requestAnimationFrame(() => map.resize());
  });

  $('search').addEventListener('input', (e) => { state.query = e.target.value; applySearch(); });
  $('detail-close').addEventListener('click', closeDetail);
  $('clear').addEventListener('click', () => {
    state.taken.clear(); state.excluded.clear(); state.included.clear();
    // Starting over means the next pick is a first pick again, and a first
    // pick is never questioned.
    for (const t of TRAVEL) state.accepted[t.key] = false;
    commit();
  });
  $('download').addEventListener('click', download);
  $('copy-link').addEventListener('click', copyLink);

  document.addEventListener('keydown', (e) => {
    if (dlg.open) return;   // the dialog answers its own Escape
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
    if (map) map.setStyle(STYLE[currentTheme()]);
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
      agreeToWhatIsAlreadyIn();
      buildTree();
      buildLegend();
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
