// Reads the toll operator's map at the points of tools/roads/cz-samples.json.gz
// (see cz_myto.py). Run in a browser tab on
// https://myto.gov.cz/cs/vymezene-useky-silnic/mapy, whose map draws the
// layers from /geoserver/entc/wms: czMyto(url of the samples file) starts
// it; window.czMytoState gives its progress and, when done, the result
// for tools/tables/browser/cz-myto-wms.json.
//
// A point is tolled where its class's layer is drawn (alpha over 64) at its
// pixel or a neighbour, in maps of SIZE pixels at M_PER_PX: the lines are
// about 9 pixels wide, so up to about 40 m from OpenStreetMap's line.
const M_PER_PX = 8, SIZE = 2048, WORKERS = 3;

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
        const lon = x / 1e5, lat = y / 1e5, key = `${cls}:${Math.floor(lon / dlon)}:${Math.floor(lat / dlat)}`;
        if (!tiles.has(key)) tiles.set(key, []);
        tiles.get(key).push(pts.length);
        pts.push([lon, lat]);
      }
    }
    const bits = new Uint8Array(Math.ceil(pts.length / 8));
    const keys = [...tiles.keys()];
    st.tiles = keys.length;
    async function tile(key) {
      const [cls, tx, ty] = key.split(':'), x0 = tx * dlon, y0 = ty * dlat, x1 = x0 + dlon, y1 = y0 + dlat;
      const q = new URLSearchParams({SERVICE: 'WMS', VERSION: '1.1.1', REQUEST: 'GetMap', LAYERS: doc.layers[cls], STYLES: '', SRS: 'EPSG:4326',
        BBOX: [x0, y0, x1, y1].join(','), WIDTH: SIZE, HEIGHT: SIZE, FORMAT: 'image/png', TRANSPARENT: 'true'});
      let r;
      for (let a = 0; a < 4; a++) {
        r = await fetch('/geoserver/entc/wms?' + q);
        if (r.ok && /image/.test(r.headers.get('content-type'))) break;
        await new Promise(s => setTimeout(s, 2000 * (a + 1)));
      }
      if (!r.ok || !/image/.test(r.headers.get('content-type'))) throw new Error(`tile ${key}: ${r.status}`);
      const c = new OffscreenCanvas(SIZE, SIZE), g = c.getContext('2d');
      g.drawImage(await createImageBitmap(await r.blob()), 0, 0);
      const d = g.getImageData(0, 0, SIZE, SIZE).data;
      for (const i of tiles.get(key)) {
        const px = Math.floor((pts[i][0] - x0) / dlon * SIZE), py = Math.floor((y1 - pts[i][1]) / dlat * SIZE);
        let on = false;
        for (let u = -1; u <= 1 && !on; u++) for (let v = -1; v <= 1 && !on; v++) {
          const X = px + u, Y = py + v;
          on = X >= 0 && Y >= 0 && X < SIZE && Y < SIZE && d[(Y * SIZE + X) * 4 + 3] > 64;
        }
        if (on) bits[i >> 3] |= 1 << (i & 7);
      }
      st.done++;
    }
    let next = 0;
    await Promise.all(Array.from({length: WORKERS}, async () => { while (next < keys.length) await tile(keys[next++]); }));
    const z = new Uint8Array(await new Response(new Blob([bits]).stream().pipeThrough(new CompressionStream('deflate-raw'))).arrayBuffer());
    let s = '';
    for (const b of z) s += String.fromCharCode(b);
    let on = 0;
    for (let i = 0; i < pts.length; i++) on += bits[i >> 3] >> (i & 7) & 1;
    st.result = {osm_extract: doc.osm_extract, samples_sha256: sha, layers: doc.layers, m_per_px: M_PER_PX, points: pts.length, tolled: on, maps: keys.length, bits: btoa(s)};
  } catch (e) {
    st.error = String(e);
  }
}
