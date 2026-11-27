"""Bulgaria's toll segments of class I and II roads in OpenStreetMap.

Each segment of the list (bg_network.py: Решение № 680/2022, both
directions, settlements left out) is found as the shortest way along its
road from its start to its end: from the nearest point of a way with the
road's ref (within SNAP_M; the nearest pair of ways a path joins: a dual
road's carriageways) to the nearest such point of its end, along ways
with the ref, roundabouts and, where the way allows it, in its direction
of travel (oneway). A path more than LONGER times the segment's length (and
EXTRA_M) is the wrong road: the segment isn't placed. Where the ref's ways
give no path, any of the main roads may (a ring road OpenStreetMap
doesn't tag). The parts of ways the paths cover are the tolled class I
and II roads; a motorway's other ways are tolled as motorway.
"""
import heapq, math
from collections import defaultdict

SNAP_M, LONGER, EXTRA_M = 150, 1.3, 300
CELL = 0.005  # degrees, the snapping grid


def metres(x1, y1, x2, y2):
    k = math.cos(math.radians((y1 + y2) / 2))
    return math.hypot((x2 - x1) * 111_320 * k, (y2 - y1) * 111_320)


class Network:
    def __init__(self):
        # Ways: (refs, roundabout, oneway (1, -1, 0), node ids, [lon, lat],
        # edge lengths in metres, tags).
        self.ways = []
        self.at = defaultdict(list)   # node id -> [(way, edge, +1 from it / -1 to it)]
        self.grid = defaultdict(list)  # cell -> [(way, edge)]
        self.cover = defaultdict(list)  # (way, edge) -> [(t0, t1)]

    def add(self, refs, roundabout, oneway, nodes, coords, tags):
        w = len(self.ways)
        lens = [metres(*coords[i], *coords[i + 1]) for i in range(len(coords) - 1)]
        self.ways.append((refs, roundabout, oneway, nodes, coords, lens, tags))
        for e in range(len(coords) - 1):
            self.at[nodes[e]].append((w, e, 1))
            self.at[nodes[e + 1]].append((w, e, -1))
            (x1, y1), (x2, y2) = coords[e], coords[e + 1]
            for cx in range(int(min(x1, x2) // CELL), int(max(x1, x2) // CELL) + 1):
                for cy in range(int(min(y1, y2) // CELL), int(max(y1, y2) // CELL) + 1):
                    self.grid[(cx, cy)].append((w, e))

    def allowed(self, w, ref):
        refs, roundabout = self.ways[w][0], self.ways[w][1]
        return ref is None or ref in refs or roundabout

    def snap(self, lon, lat, ref):
        """The nearest points of ways with the ref: [(metres, way, edge, t)]."""
        out = []
        cx, cy = int(lon // CELL), int(lat // CELL)
        seen = set()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for w, e in self.grid.get((cx + dx, cy + dy), ()):
                    if (w, e) in seen or (ref is not None and ref not in self.ways[w][0]):
                        continue
                    seen.add((w, e))
                    (x1, y1), (x2, y2) = self.ways[w][4][e], self.ways[w][4][e + 1]
                    k = math.cos(math.radians(lat))
                    ax, ay, bx, by, px, py = x1 * k, y1, x2 * k, y2, lon * k, lat
                    dd = (bx - ax) ** 2 + (by - ay) ** 2
                    t = 0.0 if dd == 0 else max(0.0, min(1.0, ((px - ax) * (bx - ax) + (py - ay) * (by - ay)) / dd))
                    d = metres(lon, lat, x1 + t * (x2 - x1), y1 + t * (y2 - y1))
                    if d <= SNAP_M:
                        out.append((d, w, e, t))
        # The nearest point of each way.
        best = {}
        for c in sorted(out):
            best.setdefault(c[1], c)
        return sorted(best.values())[:4]

    def place(self, a, b, length, ref):
        """Covers the path of a segment from a to b ((lon, lat)) of about
        length metres along the road's ways (ref; None: any). Returns the
        path's length, or None."""
        # The nearest ends that a path joins.
        best = None
        pairs = sorted((sd + td, (sw, se, st), (tw, te, tt)) for sd, sw, se, st in self.snap(*a, ref) for td, tw, te, tt in self.snap(*b, ref))
        for _, s, t in pairs:
            best = self.path(s, t, length * LONGER + EXTRA_M, ref)
            if best:
                break
        if best is None:
            return None
        for (w, e), (t0, t1) in best[1]:
            self.cover[(w, e)].append((min(t0, t1), max(t0, t1)))
        return best[0]

    def path(self, src, dst, limit, ref):
        """Shortest path from a point on an edge to another (way, edge, t),
        within limit metres: (length, [((way, edge), (t0, t1))])."""
        sw, se, st = src
        tw, te, tt = dst
        oneway = lambda w: self.ways[w][2]
        L = lambda w, e: self.ways[w][5][e]
        nodes = lambda w: self.ways[w][3]
        # Both on one edge, in a direction it allows.
        if (sw, se) == (tw, te) and ((tt >= st and oneway(sw) != -1) or (tt <= st and oneway(sw) != 1)):
            return abs(tt - st) * L(sw, se), [((sw, se), (st, tt))]
        best, pred, heap = {}, {}, []

        def reach(n, c, how):
            if c <= limit and c < best.get(n, math.inf):
                best[n], pred[n] = c, how
                heapq.heappush(heap, (c, n))

        if oneway(sw) != -1:
            reach(nodes(sw)[se + 1], (1 - st) * L(sw, se), ("S", ((sw, se), (st, 1.0))))
        if oneway(sw) != 1:
            reach(nodes(sw)[se], st * L(sw, se), ("S", ((sw, se), (0.0, st))))
        ends = {}
        if oneway(tw) != -1:
            ends[nodes(tw)[te]] = (tt * L(tw, te), ((tw, te), (0.0, tt)))
        if oneway(tw) != 1:
            c = (1 - tt) * L(tw, te)
            n = nodes(tw)[te + 1]
            if n not in ends or c < ends[n][0]:
                ends[n] = (c, ((tw, te), (tt, 1.0)))
        found = None
        while heap:
            c, n = heapq.heappop(heap)
            if c > best[n]:
                continue
            if found is not None and c >= found[0]:
                break
            if n in ends and (found is None or c + ends[n][0] < found[0]):
                found = (c + ends[n][0], n)
            for w, e, d in self.at.get(n, ()):
                if not self.allowed(w, ref) or (d == 1 and oneway(w) == -1) or (d == -1 and oneway(w) == 1):
                    continue
                reach(nodes(w)[e + 1] if d == 1 else nodes(w)[e], c + L(w, e), ("N", n, w, e))
        if found is None or found[0] > limit:
            return None
        total, n = found
        parts = [ends[n][1]]
        while pred[n][0] == "N":
            _, pn, w, e = pred[n]
            parts.append(((w, e), (0.0, 1.0)))
            n = pn
        parts.append(pred[n][1])
        return total, parts

    def covered(self, w):
        """The covered stretches of way w: lists of [lon, lat] points."""
        refs, _, _, _, coords, lens, _ = self.ways[w]
        runs, cur = [], []
        for e in range(len(coords) - 1):
            iv = merge(self.cover.get((w, e), []))
            (x1, y1), (x2, y2) = coords[e], coords[e + 1]
            pt = lambda t: (x1 + t * (x2 - x1), y1 + t * (y2 - y1))
            if not iv:
                if cur:
                    runs.append(cur)
                    cur = []
                continue
            for t0, t1 in iv:
                if t0 > 1e-9 and cur:
                    runs.append(cur)
                    cur = []
                if not cur:
                    cur = [pt(t0)]
                cur.append(pt(t1))
                if t1 < 1 - 1e-9:
                    runs.append(cur)
                    cur = []
        if cur:
            runs.append(cur)
        return [r for r in runs if len(r) >= 2]

    def uncovered(self, w):
        """The stretches of way w no path covers."""
        coords = self.ways[w][4]
        runs, cur = [], []
        for e in range(len(coords) - 1):
            (x1, y1), (x2, y2) = coords[e], coords[e + 1]
            pt = lambda t: (x1 + t * (x2 - x1), y1 + t * (y2 - y1))
            gaps, t = [], 0.0
            for t0, t1 in merge(self.cover.get((w, e), [])):
                if t0 > t + 1e-9:
                    gaps.append((t, t0))
                t = max(t, t1)
            if t < 1 - 1e-9:
                gaps.append((t, 1.0))
            for g0, g1 in gaps:
                if g0 > 1e-9 and cur:
                    runs.append(cur)
                    cur = []
                if not cur:
                    cur = [pt(g0)]
                cur.append(pt(g1))
                if g1 < 1 - 1e-9:
                    runs.append(cur)
                    cur = []
            if not gaps and cur:
                runs.append(cur)
                cur = []
        if cur:
            runs.append(cur)
        return [r for r in runs if len(r) >= 2]


def merge(iv):
    out = []
    for a, b in sorted(iv):
        if out and a <= out[-1][1] + 1e-6:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out
