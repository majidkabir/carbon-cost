"""Finds the sections of a toll network listed in a law (pl-network.json,
from tools/roads/pl_network.py) in an OpenStreetMap extract.

Each section is a road (its OpenStreetMap ref: A1, S7, or 92 for a
national road) between two points. A point is found on the road's ways:
- a junction ("węzeł X"): the motorway_junction nodes named X on the
  road, or the road's nodes nearest to those on another road (a national
  road's section ending at an expressway junction);
- the state border by a place: the road's dead ends near the place;
- a city's border: where the road leaves the city's administrative
  boundary (the lowest admin_level with the city's name);
- a crossing with, or joining of, another road near a place: the road's
  nodes shared with that road's ways (by its ref) nearest the place,
  else the road's nodes nearest the place.
Between the two, the shortest path along the road's ways is the
section; per connected part of the road (a dual carriageway's two
carriageways), and the road's other nodes within TWIN_M of it (the other
carriageway where both join up) belong to it too.
"""
import heapq, math, re, unicodedata
from collections import defaultdict
from difflib import SequenceMatcher

import osmium
from shapely import wkb
from shapely.prepared import prep
from shapely.geometry import Point

ROADS = ("motorway", "trunk", "primary", "secondary", "tertiary")
PLACES = ("city", "town", "village", "hamlet", "suburb", "quarter", "neighbourhood", "isolated_dwelling", "locality")
TWIN_M = 60
NEAR_PLACE_M = 15000
NEAR_JUNCTION_M = 3000
FAR_JUNCTION_M = 10000
GAP_M = 1500
ALIAS_COST = 1.5
OTHER_COST = 4.0
SNAP_M = 300


def dist_m(a, b):
    la1, la2 = math.radians(a[1]), math.radians(b[1])
    dla, dlo = la2 - la1, math.radians(b[0] - a[0])
    h = math.sin(dla / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlo / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def norm(s):
    s = unicodedata.normalize("NFC", s or "").lower().strip()
    s = re.sub(r"^(węzeł|wezel|węzel)\s+", "", s)
    return re.sub(r"[\s\-–/]+", " ", s)


def street_of(name):
    """A street's name without "ul." or "ulica", lower case."""
    return re.sub(r"^(ul\.|ulica)\s+", "", (name or "").strip().lower())


def refs_of(tags):
    return [r.strip().replace(" ", "") for r in (tags.get("ref") or "").split(";") if r.strip()]


class Collect(osmium.SimpleHandler):
    def __init__(self, refs, cross, cities, streets):
        super().__init__()
        self.want, self.cross, self.cities, self.streets = refs, cross, cities, streets
        self.street_nodes = defaultdict(set)
        self.ways = defaultdict(list)  # ref -> [[node ids], [coords]]
        self.cross_nodes = defaultdict(set)
        self.coords = {}
        self.junctions = []  # (normalised name, name, node id, (lon, lat))
        self.places = defaultdict(list)
        self.city = {}  # name -> (admin_level, geometry)
        self.wkb = osmium.geom.WKBFactory()
        # The main roads and the listed roads' ways, with their refs and
        # whether motorway or trunk: the network a section's path may
        # take where its road's ways don't reach.
        self.major = []

    def node(self, n):
        t = n.tags
        if t.get("highway") == "motorway_junction" and t.get("name"):
            self.junctions.append((norm(t["name"]), t["name"], n.id, (n.location.lon, n.location.lat)))
        if t.get("place") in PLACES and t.get("name"):
            self.places[t["name"]].append((n.location.lon, n.location.lat))

    def way(self, w):
        t = w.tags
        refs = refs_of(t)
        if not refs and street_of(t.get("name")) not in self.streets:
            return
        hw = t.get("highway", "")
        try:
            ids = [n.ref for n in w.nodes]
            pts = [(n.lon, n.lat) for n in w.nodes]
        except osmium.InvalidLocationError:
            return
        keep = False
        for r in refs:
            if r in self.cross:
                self.cross_nodes[r].update(ids)
                keep = True
        street = street_of(t.get("name"))
        if street in self.streets:
            self.street_nodes[street].update(ids)
            keep = True
        if hw in ROADS:
            for r in refs:
                if r in self.want:
                    self.ways[r].append((ids, pts))
                    keep = True
            if hw in ("motorway", "trunk", "primary") or any(r in self.want for r in refs):
                self.major.append((ids, pts, frozenset(refs), hw in ("motorway", "trunk")))
                keep = True
        if keep:
            for i, p in zip(ids, pts):
                self.coords[i] = p

    def area(self, a):
        t = a.tags
        name = t.get("name")
        if t.get("boundary") != "administrative" or name not in self.cities:
            return
        try:
            level = int(t.get("admin_level", "99"))
        except ValueError:
            return
        old = self.city.get(name)
        if old and old[0] <= level:
            return
        try:
            self.city[name] = (level, wkb.loads(self.wkb.create_multipolygon(a), hex=True))
        except Exception:
            pass


def aliases(ref):
    """The refs a road's ways may carry in OpenStreetMap: an expressway is
    the national road of its number (S7 is national road 7), so where one
    has been built or reclassified OpenStreetMap may tag the other."""
    if ref.startswith("S"):
        return [ref, ref[1:]]
    if ref.isdigit():
        return [ref, "S" + ref]
    return [ref]


class Road:
    """A road's ways as an undirected graph: its own ref's, and at
    ALIAS_COST times their length its alias's. Its ways' gaps (a way
    without the ref, a carriageway broken in two) are bridged: each dead
    end joins the nearest dead end of another part of the road within
    GAP_M. The dead ends before the bridging are the road's ends."""

    def __init__(self, own, alias, coords):
        self.ways, self.coords = own + alias, coords
        self.adj = defaultdict(dict)
        for ways, k in ((own, 1.0), (alias, ALIAS_COST)):
            for ids, pts in ways:
                for i in range(len(ids) - 1):
                    a, b = ids[i], ids[i + 1]
                    d = dist_m(pts[i], pts[i + 1]) * k
                    if d < self.adj[a].get(b, math.inf):
                        self.adj[a][b] = self.adj[b][a] = d
        self.grid = defaultdict(list)
        for n in self.adj:
            p = coords[n]
            self.grid[(int(p[0] * 100), int(p[1] * 100))].append(n)
        self.ends = {n for n in self.adj if len(self.adj[n]) == 1}
        self._parts()
        part_of = {n: i for i, part in enumerate(self.parts) for n in part}
        for n in self.ends:
            best = None
            for m in self.near(coords[n], GAP_M):
                if m in self.ends and part_of[m] != part_of[n]:
                    d = dist_m(coords[n], coords[m])
                    if best is None or d < best[0]:
                        best = (d, m)
            if best:
                self.adj[n][best[1]] = self.adj[best[1]][n] = best[0]
        self._parts()

    def _parts(self):
        self.parts, seen = [], set()
        for n in self.adj:
            if n in seen:
                continue
            part, stack = set(), [n]
            while stack:
                x = stack.pop()
                if x in part:
                    continue
                part.add(x)
                stack.extend(y for y in self.adj[x] if y not in part)
            seen |= part
            self.parts.append(part)

    def near(self, p, within):
        """The road's nodes within metres of p."""
        k = (int(p[0] * 100), int(p[1] * 100))
        r = 1 + int(within // 700)
        out = []
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                out += [n for n in self.grid.get((k[0] + dx, k[1] + dy), ()) if dist_m(self.coords[n], p) <= within]
        return out

    def nearest(self, nodes, p, within, slack=500):
        """Of nodes, those nearest p: within metres, and at most slack
        further than the nearest."""
        best = sorted((dist_m(self.coords[n], p), n) for n in nodes)
        if not best or best[0][0] > within:
            return []
        return [n for d, n in best if d <= best[0][0] + slack][:8]

    def path(self, src, dst):
        """Shortest path from any of src to any of dst: (metres, nodes)."""
        dist, prev, h = {}, {}, []
        for s in src:
            dist[s] = 0.0
            heapq.heappush(h, (0.0, s))
        dst = set(dst)
        while h:
            d, x = heapq.heappop(h)
            if d > dist.get(x, math.inf):
                continue
            if x in dst:
                out = [x]
                while out[-1] in prev:
                    out.append(prev[out[-1]])
                return d, out[::-1]
            for y, w in self.adj[x].items():
                if d + w < dist.get(y, math.inf):
                    dist[y], prev[y] = d + w, x
                    heapq.heappush(h, (d + w, y))
        return None


class Net:
    """The main roads as one graph, for a section whose road's ways don't
    join its two points: the path costs a way of the section's road its
    length, of its alias ALIAS_COST times it, of another road OTHER_COST
    times it."""

    def __init__(self, ways, coords):
        self.ways, self.coords = ways, coords
        self.adj = defaultdict(dict)  # node -> node -> (metres, refs, motorway or trunk)
        for ids, pts, refs, fast in ways:
            for i in range(len(ids) - 1):
                a, b = ids[i], ids[i + 1]
                old = self.adj[a].get(b)
                e = (dist_m(pts[i], pts[i + 1]), refs | old[1] if old else refs, fast or bool(old and old[2]))
                self.adj[a][b] = self.adj[b][a] = e
        self.grid = defaultdict(list)
        for n in self.adj:
            p = coords[n]
            self.grid[(int(p[0] * 100), int(p[1] * 100))].append(n)

    near = Road.near

    def path(self, src, dst, ref):
        own, alias = {ref}, set(aliases(ref)[1:])
        dist, prev, h = {}, {}, []
        for s in src:
            if s in self.adj:
                dist[s] = 0.0
                heapq.heappush(h, (0.0, s))
        dst = set(dst)
        while h:
            d, x = heapq.heappop(h)
            if d > dist.get(x, math.inf):
                continue
            if x in dst:
                out = [x]
                while out[-1] in prev:
                    out.append(prev[out[-1]])
                out = out[::-1]
                metres = sum(self.adj[u][v][0] for u, v in zip(out, out[1:]))
                on = sum(self.adj[u][v][0] for u, v in zip(out, out[1:]) if self.adj[u][v][1] & (own | alias))
                return metres, out, on
            for y, (w, refs, _) in self.adj[x].items():
                k = 1.0 if refs & own else ALIAS_COST if refs & alias else OTHER_COST
                if d + w * k < dist.get(y, math.inf):
                    dist[y], prev[y] = d + w * k, x
                    heapq.heappush(h, (d + w * k, y))
        return None


def net_points(c, net, road, road_, pt, own):
    """The main roads' nodes at a point of a section, where the road's own
    ways didn't give it: within SNAP_M of the junction, of the crossing
    road's (or the street's) node nearest the place, or the road's own
    candidates."""
    at = []
    if "junction" in pt:
        want = norm(pt["junction"])
        at = [j[3] for j in c.junctions if j[0] == want]
        if not at:
            # A city junction named for its street: where the street comes
            # nearest the road.
            best = None
            for n in c.street_nodes.get(street_of(pt["junction"]), ()):
                for m in road_.near(c.coords[n], 1500):
                    d = dist_m(c.coords[n], c.coords[m])
                    if best is None or d < best[0]:
                        best = (d, c.coords[n])
            at = [best[1]] if best else []
    elif "crosses" in pt:
        places = c.places.get(pt["place"], [])
        nodes = {n for r in pt["crosses"] for n in c.cross_nodes.get(r, ())}
        if pt.get("street"):
            nodes = (nodes & c.street_nodes.get(street_of(pt["street"]), set())) or nodes
        if places and nodes:
            place = min(places, key=lambda p: min(dist_m(c.coords[n], p) for n in nodes))
            best = min(nodes, key=lambda n: dist_m(c.coords[n], place))
            if dist_m(c.coords[best], place) <= NEAR_PLACE_M:
                at = [c.coords[best]]
    out = []
    for p in at:
        near = net.near(p, SNAP_M)
        out += [n for n in near if any(e[1] & set(aliases(road)) for e in net.adj[n].values())] or near
    return out or [n for n in own if n in net.adj]


def junctions_named(road, want, junctions):
    """The junction nodes on or by the road (NEAR_JUNCTION_M) whose name is
    the law's: the same, one containing the other, or spelt a little
    differently ("Tomasz Lubelski")."""
    want = norm(want)
    by = [j for j in junctions if j[2] in road.adj or road.near(j[3], NEAR_JUNCTION_M)]
    for test in (lambda n: n == want, lambda n: want in n.split(" ") or n.endswith(" " + want) or n.startswith(want + " ") or want.endswith(" " + n),
                 lambda n: SequenceMatcher(None, want, n).ratio() >= 0.85):
        named = [j for j in by if test(j[0])]
        if named:
            return named, by
    return [], by


def candidates(c, road, pt, jx):
    """The road's nodes where a point of a section can be, and what was
    looked for when there are none."""
    if "junction" in pt:
        named, by = junctions_named(road, pt["junction"], jx)
        out = [j[2] for j in named if j[2] in road.adj]
        for j in named:
            if j[2] not in road.adj:
                out += road.nearest(road.near(j[3], NEAR_JUNCTION_M), j[3], NEAR_JUNCTION_M, 200)
        if out:
            return out, ""
        # A junction of that name further off (on the road it joins), or
        # the street of that name the road crosses (a city junction).
        far = [j for j in jx if j[0] == norm(pt["junction"])]
        for j in far:
            out += road.nearest(road.near(j[3], FAR_JUNCTION_M), j[3], FAR_JUNCTION_M, 200)
        out += [n for n in c.street_nodes.get(street_of(pt["junction"]), ()) if n in road.adj]
        if out:
            return out, ""
        close = sorted({j[1] for j in by}, key=lambda n: -SequenceMatcher(None, norm(pt["junction"]), norm(n)).ratio())[:6]
        return [], f"junction {pt['junction']!r} not on the road; its junctions most like it: {close}"
    if "border" in pt:
        places = c.places.get(pt["border"], [])
        if not places:
            return [], f"no place {pt['border']!r}"
        ends = [(min(dist_m(road.coords[n], p) for p in places), n) for n in road.ends]
        ends = [e for e in ends if e[0] <= NEAR_PLACE_M]
        if not ends:
            return [], f"no end of the road within {NEAR_PLACE_M} m of {pt['border']!r}"
        # The road's end nearest the place (both carriageways').
        first = min(ends)[0]
        return [n for d, n in ends if d <= first + 2000], ""
    if "city" in pt:
        city = c.city.get(pt["city"])
        if not city:
            return [], f"no boundary of {pt['city']!r}"
        shape = prep(city[1])
        ins = {n: shape.contains(Point(road.coords[n])) for n in road.adj}
        out = [n for n in road.adj if not ins[n] and any(ins[y] for y in road.adj[n])]
        if out:
            return out, ""
        # The road ends at the city: its nodes nearest the boundary.
        near = sorted((city[1].exterior.distance(Point(road.coords[n])) if city[1].geom_type == "Polygon"
                       else city[1].boundary.distance(Point(road.coords[n])), n) for n in road.adj)
        near = [(d * 111000, n) for d, n in near[:8] if d * 111000 <= 1500]
        return [n for d, n in near], "" if near else f"the road neither crosses nor ends at {pt['city']!r}"
    places = c.places.get(pt["place"], [])
    shared = {n for r in pt["crosses"] for n in c.cross_nodes.get(r, ()) if n in road.adj}
    # Where the other road meets or leaves this one, not along a stretch
    # they share.
    ends = [n for n in shared if any(y not in shared for y in road.adj[n])]
    if pt.get("street"):
        on = [n for n in ends if n in c.street_nodes.get(street_of(pt["street"]), ())]
        ends = on or ends
    if not places:
        return ends, "" if ends else f"no place {pt['place']!r} and no crossing with {pt['crosses']}"
    # Of the same-named places, the one nearest the road.
    place = min(places, key=lambda p: dist_m(road.coords[road.nearest(road.adj, p, math.inf, 0)[0]], p) if road.adj else 0)
    out = road.nearest(ends, place, NEAR_PLACE_M, 300)
    if out:
        return out, ""
    out = road.nearest(road.adj, place, 5000, 300)
    return out, "" if out else f"no crossing with {pt['crosses']} by {pt['place']!r}, nor the road within 5 km of it"


def build(src, sections):
    """The sections' lines by class ("mw", "nat"), [lon, lat] each, and a
    report of each section's km (the longest carriageway) or why it
    wasn't found."""
    refs = {a for s in sections for a in aliases(s["ref"])}
    cross = {r for s in sections for pt in (s["from"], s["to"]) for r in pt.get("crosses", [])}
    cities = {pt["city"] for s in sections for pt in (s["from"], s["to"]) if "city" in pt}
    streets = {street_of(pt["street"]) for s in sections for pt in (s["from"], s["to"]) if pt.get("street")}
    streets |= {street_of(pt["junction"]) for s in sections for pt in (s["from"], s["to"]) if "junction" in pt}
    c = Collect(refs, cross, cities, streets)
    c.apply_file(src, locations=True)
    roads = {r: Road(c.ways[r], [w for a in aliases(r)[1:] for w in c.ways[a]], c.coords) for r in {s["ref"] for s in sections}}
    net = Net(c.major, c.coords)
    lines = {"mw": [], "nat": []}
    report = []
    for s in sections:
        road = roads[s["ref"]]
        a, wa = candidates(c, road, s["from"], c.junctions)
        b, wb = candidates(c, road, s["to"], c.junctions)
        picked, km, paths = set(), 0.0, []
        why = [w for w in (wa, wb) if w]
        for part in road.parts:
            pa, pb = [n for n in a if n in part], [n for n in b if n in part]
            if not pa or not pb:
                continue
            found = road.path(pa, pb)
            if not found:
                continue
            d, nodes = found
            straight = dist_m(road.coords[nodes[0]], road.coords[nodes[-1]])
            if d > 3 * straight + 5000:
                why.append(f"path {d / 1000:.1f} km for {straight / 1000:.1f} km straight")
                continue
            picked.update(nodes)
            paths.append((road, nodes))
            km = max(km, d / 1000)
        if km < 0.2:
            # The road's ways don't join the points (a gap, a stretch tagged
            # by another road, or the points resolved to one): the path on
            # the main roads, from the points found again on them.
            one = bool(set(a) & set(b)) or bool(picked)
            na = net_points(c, net, s["ref"], road, s["from"], [] if one and "crosses" in s["from"] else a)
            nb = net_points(c, net, s["ref"], road, s["to"], [] if one and "crosses" in s["to"] else b)
            found = net.path(na, nb, s["ref"]) if na and nb and not set(na) & set(nb) else None
            picked, paths = set(), []
            if not found:
                why.append(f"main roads: {len(na)} and {len(nb)} points, {len(set(na) & set(nb))} in both, "
                           f"{'no path' if na and nb else 'not tried'}; {len(net.adj)} nodes")
            if found:
                d, nodes, on = found
                straight = dist_m(c.coords[nodes[0]], c.coords[nodes[-1]])
                if d >= 200 and d <= 3 * straight + 5000 and on >= 0.5 * d:
                    picked.update(nodes)
                    paths.append((net, nodes))
                    km = d / 1000
                    why = [f"on the main roads: {on / 1000:.1f} of {d / 1000:.1f} km on the road"]
                else:
                    why.append(f"main roads' path {d / 1000:.1f} km for {straight / 1000:.1f} km straight, {on / 1000:.1f} km on the road")
        if km < 0.2:
            if not why:
                why.append("the points are one" if picked else f"no part of the road has both points ({len(a)} and {len(b)} found)")
            report.append((s["text"], None, "; ".join(why)))
            continue
        # The other carriageway: the road's nodes (on the main roads, those
        # of the road, its alias or a motorway or trunk) within TWIN_M of the
        # paths' points every 20 m.
        for g, nodes in paths:
            pgrid, cells = defaultdict(list), set()
            for x, y in zip(nodes, nodes[1:]):
                p, q = c.coords[x], c.coords[y]
                steps = max(1, int(dist_m(p, q) // 20))
                for i in range(steps + 1):
                    m = (p[0] + (q[0] - p[0]) * i / steps, p[1] + (q[1] - p[1]) * i / steps)
                    pgrid[(int(m[0] * 500), int(m[1] * 500))].append(m)
                    cells.add((int(m[0] * 100), int(m[1] * 100)))
            near = {n for k in cells for dx in (-1, 0, 1) for dy in (-1, 0, 1) for n in g.grid.get((k[0] + dx, k[1] + dy), ())}
            for n in near - picked:
                p = c.coords[n]
                k = (int(p[0] * 500), int(p[1] * 500))
                if not any(dist_m(p, q) <= TWIN_M for dx in (-1, 0, 1) for dy in (-1, 0, 1) for q in pgrid.get((k[0] + dx, k[1] + dy), ())):
                    continue
                if g is road or any(e[2] or e[1] & set(aliases(s["ref"])) for e in net.adj[n].values()):
                    picked.add(n)
        ways = road.ways if all(g is road for g, _ in paths) else [(ids, pts) for ids, pts, _, _ in net.ways]
        for ids, wpts in ways:
            run = []
            for i, p in zip(ids, wpts):
                if i in picked:
                    run.append(p)
                    continue
                if len(run) >= 2:
                    lines[s["class"]].append(run)
                run = []
            if len(run) >= 2:
                lines[s["class"]].append(run)
        report.append((s["text"], km, "; ".join(why)))
    return lines, report
