"""Czechia's tolled stretches from the toll operator's map (myto.gov.cz).

The law (vyhláška č. 470/2012 Sb., annexes 1 and 2; tools/roads/
cz-network.json) names each tolled section by its ends and length, but
not where a class I road's town passages and the other stretches it
leaves out lie. The operator's map does: its WMS draws the tolled
motorways (layer entc:v_entc_road_d) and class I roads
(entc:v_entc_road_a). The geometry is only published as images, so the
map is read at points of OpenStreetMap's ways:

1. The Roads data workflow writes cz-samples.json.gz (build.py, with
   the CZ extract): every motorway and every way of a class I road the
   law tolls, with a point every STEP_M along it.
2. In a browser tab on https://myto.gov.cz/cs/vymezene-useky-silnic/mapy
   (Claude in Chrome), cz_myto.js reads the map at each point: tolled
   where the layer of its class is drawn there.
3. The answer, the points' bits, goes in tools/tables/browser/
   cz-myto-wms.json with the URL and date, and the samples file in
   tools/roads/cz-samples.json.gz; build.py then keeps only the tolled
   parts of each way.

Ways OpenStreetMap added since the samples were taken (other ids) are
tolled when both their ends meet tolled ways of their class, else not;
build.py reports their km, and each road's tolled km against the law's.
"""
import base64, gzip, hashlib, json, math, os, zlib

STEP_M = 100
HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLES = os.path.join(HERE, "cz-samples.json.gz")
CAPTURE = os.path.join(HERE, "..", "tables", "browser", "cz-myto-wms.json")
LAYERS = {"mw": "entc:v_entc_road_d", "nat": "entc:v_entc_road_a"}


def length_m(coords):
    return sum(math.hypot((x2 - x1) * 111_320 * math.cos(math.radians((y1 + y2) / 2)), (y2 - y1) * 111_320)
               for (x1, y1), (x2, y2) in zip(coords, coords[1:]))


def points(ls, n):
    """n points of a shapely line in degrees, each the middle of its
    n-th of the line (by the line's length in degrees: build.py cuts it
    the same way)."""
    return [ls.interpolate((i + 0.5) / n, normalized=True) for i in range(n)]


def count(coords):
    return max(1, round(length_m(coords) / STEP_M))


def write_samples(ways, path, osm_extract=None):
    """ways: (id, class, shapely line); points delta-coded, 1e5 degrees."""
    out = []
    for wid, c, ls in ways:
        n = count(list(ls.coords))
        xy, px, py = [], 0, 0
        for p in points(ls, n):
            x, y = round(p.x * 1e5), round(p.y * 1e5)
            xy += [x - px, y - py]
            px, py = x, y
        out.append([wid, c, n, xy])
    doc = {"osm_extract": osm_extract, "step_m": STEP_M, "layers": LAYERS, "ways": out}
    with gzip.GzipFile(path, "wb", mtime=0) as f:
        f.write(json.dumps(doc, separators=(",", ":")).encode())


def runs(bits):
    """The tolled runs (start, end) of a way's points: a single untolled
    point between tolled ones is filled (the map's line broken under a
    bridge), and a run of fewer than 3 points in a way of more is left
    out (a crossing or a fork with a tolled road)."""
    b = list(bits)
    for i in range(1, len(b) - 1):
        if not b[i] and b[i - 1] and b[i + 1]:
            b[i] = True
    out, i = [], 0
    while i < len(b):
        if b[i]:
            j = i
            while j < len(b) and b[j]:
                j += 1
            if j - i >= 3 or j - i == len(b) or (len(b) < 5 and 2 * (j - i) >= len(b)):
                out.append((i, j))
            i = j
        else:
            i += 1
    return out


def load():
    """Way id -> its tolled parts as (from, to) fractions of its length
    ([] for none), or None without a capture."""
    if not os.path.exists(CAPTURE) or not os.path.exists(SAMPLES):
        return None
    cap = json.load(open(CAPTURE, encoding="utf-8"))
    raw = open(SAMPLES, "rb").read()
    if hashlib.sha256(raw).hexdigest() != cap["samples_sha256"]:
        raise SystemExit("CZ: tools/tables/browser/cz-myto-wms.json is for another cz-samples.json.gz")
    doc = json.loads(gzip.decompress(raw))
    data = zlib.decompress(base64.b64decode(cap["bits"]), -15)
    out, k = {}, 0
    for wid, c, n, _ in doc["ways"]:
        bits = [bool(data[(k + i) >> 3] >> ((k + i) & 7) & 1) for i in range(n)]
        k += n
        out[wid] = [(a / n, b / n) for a, b in runs(bits)]
    if k != cap["points"]:
        raise SystemExit(f"CZ: the capture has {cap['points']} points, the samples {k}")
    return out
