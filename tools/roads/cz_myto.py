"""Czechia's tolled stretches from the toll operator's map (myto.gov.cz).

The law (vyhláška č. 470/2012 Sb., annexes 1 and 2; tools/roads/
cz-network.json) names each tolled section by its ends and length, but
not where a class I road's town passages and the other stretches it
leaves out lie; and some roads it lists by their class I number,
OpenStreetMap already has as class II, the motorway beside them open.
The operator's map draws the tolled roads by their toll class: its WMS
has the motorways (layer entc:v_entc_road_d, "mw") and the class I
roads (entc:v_entc_road_a, "nat"). The geometry is only published as
images, so the map is read at points of OpenStreetMap's main roads:

1. The Roads data workflow writes cz-samples.json.gz (build.py, with
   the CZ extract): every motorway, trunk, primary and secondary way,
   with a point every STEP_M along it.
2. In a browser tab on https://myto.gov.cz/cs/vymezene-useky-silnic/mapy
   (Claude in Chrome), cz_myto.js reads both layers at each point, and
   lists the places where a layer is drawn away from the points (a
   tolled road the samples miss).
3. Its answer goes in tools/tables/browser/cz-myto-wms.json with the
   URL and date, and the samples file in tools/roads/cz-samples.json.gz;
   build.py then keeps the tolled parts of each way, in the class of the
   layer drawn there.

A way takes the map's reading at its points where they still lie on it
(within MATCH_M; OpenStreetMap may have split or moved it since), and,
where they cover too little of it (a way added since: another id), the
reading at other ways' points beside it (within NEAR_M). Ways with no
points are tolled when they and the other such ways joined to them reach
tolled ways of one class at every end, else not; build.py reports their
km, and the tolled km of each class against the law's.
"""
import gzip, hashlib, json, math, os
from collections import Counter

STEP_M = 100
MATCH_M, NEAR_M, COVER = 25, 15, 0.7
HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLES = os.path.join(HERE, "cz-samples.json.gz")
CAPTURE = os.path.join(HERE, "..", "tables", "browser", "cz-myto-wms.json")
LAYERS = {"mw": "entc:v_entc_road_d", "nat": "entc:v_entc_road_a"}
OTHER = {"mw": "nat", "nat": "mw"}


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
    """ways: (id, class, ref, shapely line). Ordered by ref and then along
    the road (the long side of its box), so that a road's tolled ways
    come together; points delta-coded, 1e5 degrees."""
    box = {}
    for _, _, ref, ls in ways:
        x0, y0, x1, y1 = ls.bounds
        b = box.get(ref, (x0, y0, x1, y1))
        box[ref] = (min(b[0], x0), min(b[1], y0), max(b[2], x1), max(b[3], y1))

    def key(w):
        wid, _, ref, ls = w
        x0, y0, x1, y1 = box[ref]
        p = ls.interpolate(0.5, normalized=True)
        return (ref, p.x if (x1 - x0) * 0.65 > (y1 - y0) else p.y, wid)

    out = []
    for wid, c, ref, ls in sorted(ways, key=key):
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


def parts_at(fl, c, half):
    """A way's toll class and tolled parts, as (from, to) fractions of its
    length, from the map's points on it: fl, (fraction along the way,
    layer drawn or None), in order; half, half the points' spacing as a
    fraction of the way. A part ends halfway between a tolled point and
    the next, or half a spacing past its last point (the way's end if that
    is nearer); c, the way's own class, where no layer is drawn."""
    layers = [l for _, l in fl]
    got = runs([l is not None for l in layers])
    votes = Counter(layers[i] for a, b in got for i in range(a, b))
    out = []
    for a, b in got:
        lo = (fl[a - 1][0] + fl[a][0]) / 2 if a else (0.0 if fl[0][0] <= 1.5 * half else fl[0][0] - half)
        hi = (fl[b - 1][0] + fl[b][0]) / 2 if b < len(fl) else (1.0 if fl[-1][0] >= 1 - 1.5 * half else fl[-1][0] + half)
        if hi > lo:
            out.append((lo, hi))
    return (votes.most_common(1)[0][0] if votes else c), out


def unrun(text):
    """Runs of false and true values, false first: "0,9,6" is 9 true then
    6 false."""
    return [i % 2 == 1 for i, n in enumerate(int(x) for x in text.split(",")) for _ in range(n)]


def parts_at(fl, c, half):
    """A way's toll class and tolled parts, as (from, to) fractions of its
    length, from the map's points on it: fl, (fraction along the way,
    layer drawn or None), in order; half, half the points' spacing as a
    fraction of the way. A part ends halfway between a tolled point and
    the next, or half a spacing past its last point (the way's end if that
    is nearer); c, the way's own class, where no layer is drawn."""
    layers = [l for _, l in fl]
    got = runs([l is not None for l in layers])
    votes = Counter(layers[i] for a, b in got for i in range(a, b))
    out = []
    for a, b in got:
        lo = (fl[a - 1][0] + fl[a][0]) / 2 if a else (0.0 if fl[0][0] <= 1.5 * half else fl[0][0] - half)
        hi = (fl[b - 1][0] + fl[b][0]) / 2 if b < len(fl) else (1.0 if fl[-1][0] >= 1 - 1.5 * half else fl[-1][0] + half)
        if hi > lo:
            out.append((lo, hi))
    return (votes.most_common(1)[0][0] if votes else c), out


def unrun(text):
    """Runs of false and true values, false first: "0,9,6" is 9 true then
    6 false."""
    return [i % 2 == 1 for i, n in enumerate(int(x) for x in text.split(",")) for _ in range(n)]


def parts(layers, c):
    """A way's toll class and tolled parts, as (from, to) fractions of its
    length, from the layer drawn at each of its points (None for none);
    c, the way's own class, where none is."""
    got = runs([l is not None for l in layers])
    votes = Counter(layers[i] for a, b in got for i in range(a, b))
    n = len(layers)
    return (votes.most_common(1)[0][0] if votes else c), [(a / n, b / n) for a, b in got]


def load():
    """Way id -> (its own class, the layer drawn at each of its points:
    "mw", "nat" or None, the points' [lon, lat]), or None without a
    capture."""
    if not os.path.exists(CAPTURE) or not os.path.exists(SAMPLES):
        return None
    cap = json.load(open(CAPTURE, encoding="utf-8"))
    raw = open(SAMPLES, "rb").read()
    if hashlib.sha256(raw).hexdigest() != cap["samples_sha256"]:
        raise SystemExit("CZ: tools/tables/browser/cz-myto-wms.json is for another cz-samples.json.gz")
    doc = json.loads(gzip.decompress(raw))
    # tolled: a layer is drawn at the point; other: only the other class's.
    tolled, other = unrun(cap["runs"]), unrun(cap["other"])
    total = sum(w[2] for w in doc["ways"])
    if not len(tolled) == len(other) == cap["points"] == total:
        raise SystemExit(f"CZ: the capture has {len(tolled)} and {len(other)} points, the samples {total}")
    out, k = {}, 0
    for wid, c, n, xy in doc["ways"]:
        layers = [(OTHER[c] if other[k + i] else c) if tolled[k + i] else None for i in range(n)]
        pts, x, y = [], 0, 0
        for i in range(n):
            x, y = x + xy[2 * i], y + xy[2 * i + 1]
            pts.append((x / 1e5, y / 1e5))
        out[wid] = (c, layers, pts)
        k += n
    return out


class Points:
    """The map's points of every way of the capture, in a grid, to find
    those on a way: (fraction along it, layer, [lon, lat])."""

    CELL = 0.0005  # degrees

    def __init__(self, myto):
        self.myto, self.grid = myto, {}
        for wid, (_, layers, pts) in myto.items():
            for l, p in zip(layers, pts):
                self.grid.setdefault((int(p[0] // self.CELL), int(p[1] // self.CELL)), []).append((l, p, wid))

    def on(self, wid, ls):
        """The points on line ls (shapely, degrees) of way wid: its own
        within MATCH_M, and, where those cover less than COVER of it, other
        ways' within NEAR_M. Sorted by fraction."""
        from shapely.geometry import Point
        n = count(list(ls.coords))
        out = []

        def add(l, p, within):
            q = Point(p)
            f = ls.project(q, normalized=True)
            r = ls.interpolate(f, normalized=True)
            if length_m([(p[0], p[1]), (r.x, r.y)]) <= within:
                out.append((f, l, tuple(p)))

        own = self.myto.get(wid)
        if own:
            for l, p in zip(own[1], own[2]):
                add(l, p, MATCH_M)
        if len(out) < COVER * n:
            x0, y0, x1, y1 = ls.bounds
            for cx in range(int(x0 // self.CELL) - 1, int(x1 // self.CELL) + 2):
                for cy in range(int(y0 // self.CELL) - 1, int(y1 // self.CELL) + 2):
                    for l, p, w in self.grid.get((cx, cy), ()):
                        if w != wid:
                            add(l, p, NEAR_M)
        return sorted(out)
