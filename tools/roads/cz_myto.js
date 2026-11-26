// Reads the toll operator's map at the points of tools/roads/cz-samples.json.gz
// (see cz_myto.py). Run in a browser tab on
// https://myto.gov.cz/cs/vymezene-useky-silnic/mapy, whose map draws the
// layers from /geoserver/entc/wms: czMyto(url of the samples file) starts
// it; window.czMytoState gives its progress and, when done, the result
// for tools/tables/browser/cz-myto-wms.json; czMytoShow() then writes it
// in the page, whose text the browser tool reads whole.
//
// A layer is drawn at a point when a pixel (alpha over 64) at it or next to
// it is, in maps of SIZE pixels at M_PER_PX: the lines are about 9 pixels
// wide, so up to about 40 m from OpenStreetMap's line. A point is tolled
// when its class's layer is drawn there, or else the other's ("other").
// "unmatched": the places where a layer is drawn more than R_PX pixels from
// every point it was drawn at, over MIN_PX pixels of a map (a tolled road
// of some 0.8 km or more that no sampled way is on).
const M_PER_PX = 8, SIZE = 2048, WORKERS = 3, R_PX = 10, MIN_PX = 900;

async function czMyto(samplesUrl) {
  const st = window.czMytoState = {done: 0, tiles: 0, error: null, result: null};
  try {
    const raw = await (await fetch(samplesUrl)).arrayBuffer();
    const sha = [...new Uint8Array(await crypto.subtle.digest('SHA-256', raw))].map(b => b.toString(16).padStart(2, '0')).join('');
    const doc = JSON.parse(await new Response(new Blob([raw]).stream().pipeThrough(new DecompressionStream('gzip'))).text());
    const dlat = M_PER_PX * SIZE / 111320, dlon = dlat / Math.cos(49.8 * Math.PI / 180);
    const pts = [], tiles = new Map();
    for (const [, cls, n, xy] of doc.ways) {
      let x = 0, y = 0;
      for (let i = 0; i < n; i++) {
        x += xy[2 * i]; y += xy[2 * i + 1];
        const lon = x / 1e5, lat = y / 1e5, key = `${Math.floor(lon / dlon)}:${Math.floor(lat / dlat)}`;
        if (!tiles.has(key)) tiles.set(key, []);
        tiles.get(key).push(pts.length);
        pts.push([lon, lat, cls]);
      }
    }
    const tolled = new Uint8Array(pts.length), other = new Uint8Array(pts.length), unmatched = [];
    const keys = [...tiles.keys()];
    st.tiles = keys.length;
    async function layer(name, x0, y0, x1, y1) {
      const q = new URLSearchParams({SERVICE: 'WMS', VERSION: '1.1.1', REQUEST: 'GetMap', LAYERS: name, STYLES: '', SRS: 'EPSG:4326',
        BBOX: [x0, y0, x1, y1].join(','), WIDTH: SIZE, HEIGHT: SIZE, FORMAT: 'image/png', TRANSPARENT: 'true'});
      let r;
      for (let a = 0; a < 4; a++) {
        r = await fetch('/geoserver/entc/wms?' + q);
        if (r.ok && /image/.test(r.headers.get('content-type'))) break;
        await new Promise(s => setTimeout(s, 2000 * (a + 1)));
      }
      if (!r.ok || !/image/.test(r.headers.get('content-type'))) throw new Error(`map ${name} ${x0},${y0}: ${r.status}`);
      const c = new OffscreenCanvas(SIZE, SIZE), g = c.getContext('2d');
      g.drawImage(await createImageBitmap(await r.blob()), 0, 0);
      return g.getImageData(0, 0, SIZE, SIZE).data;
    }
    async function tile(key) {
      const [tx, ty] = key.split(':').map(Number), x0 = tx * dlon, y0 = ty * dlat, x1 = x0 + dlon, y1 = y0 + dlat;
      const maps = {mw: await layer(doc.layers.mw, x0, y0, x1, y1), nat: await layer(doc.layers.nat, x0, y0, x1, y1)};
      const px = i => [Math.floor((pts[i][0] - x0) / dlon * SIZE), Math.floor((y1 - pts[i][1]) / dlat * SIZE)];
      const drawn = (d, [X, Y]) => {
        for (let u = -1; u <= 1; u++) for (let v = -1; v <= 1; v++) {
          const a = X + u, b = Y + v;
          if (a >= 0 && b >= 0 && a < SIZE && b < SIZE && d[(b * SIZE + a) * 4 + 3] > 64) return true;
        }
        return false;
      };
      const at = {mw: [], nat: []};
      for (const i of tiles.get(key)) {
        const own = pts[i][2], oth = own === 'mw' ? 'nat' : 'mw', p = px(i);
        if (drawn(maps[own], p)) { tolled[i] = 1; at[own].push(p); }
        else if (drawn(maps[oth], p)) { tolled[i] = 1; other[i] = 1; at[oth].push(p); }
      }
      for (const cls of ['mw', 'nat']) {
        const near = new Uint8Array(SIZE * SIZE);
        for (const [X, Y] of at[cls]) for (let v = -R_PX; v <= R_PX; v++) for (let u = -R_PX; u <= R_PX; u++) {
          const a = X + u, b = Y + v;
          if (u * u + v * v <= R_PX * R_PX && a >= 0 && b >= 0 && a < SIZE && b < SIZE) near[b * SIZE + a] = 1;
        }
        let n = 0, sx = 0, sy = 0;
        const d = maps[cls];
        for (let j = 0; j < SIZE * SIZE; j++) if (d[j * 4 + 3] > 64 && !near[j]) { n++; sx += j % SIZE; sy += Math.floor(j / SIZE); }
        if (n >= MIN_PX) unmatched.push([cls, +(x0 + sx / n / SIZE * dlon).toFixed(4), +(y1 - sy / n / SIZE * dlat).toFixed(4), n]);
      }
      st.done++;
    }
    let next = 0;
    await Promise.all(Array.from({length: WORKERS}, async () => { while (next < keys.length) await tile(keys[next++]); }));
    // Runs of false and true values, false first.
    const runs = a => {
      const out = [];
      let cur = 0, len = 0;
      for (const v of a) { if (v === cur) len++; else { out.push(len); cur = v; len = 1; } }
      out.push(len);
      return out.join(',');
    };
    st.result = {osm_extract: doc.osm_extract, samples_sha256: sha, layers: doc.layers, m_per_px: M_PER_PX, points: pts.length,
      tolled: tolled.reduce((a, b) => a + b, 0), other_points: other.reduce((a, b) => a + b, 0), maps: 2 * keys.length,
      unmatched: unmatched.sort((a, b) => b[3] - a[3]), runs: runs(tolled), other: runs(other)};
  } catch (e) {
    st.error = String(e);
  }
}

function czMytoShow() {
  const pre = document.createElement('pre');
  pre.textContent = JSON.stringify(window.czMytoState.result);
  document.body.replaceChildren(pre);
}
