"""Ferry routes as closed systems placed on OpenStreetMap's ferry lines,
for the ferry fare builders (gb_calmac.py, hr_jadrolinija.py).

A route is a set of port pairs with a fare each. A port is a station whose
points lie out on the water, on each car ferry line (route=ferry, a motor
vehicle may take it) between two of its route's ports: the first point at
least POINT_KM along the line (a quarter of a short crossing) that is more
than CLEAR_KM from every line of another system, so that a trip on another
route doesn't pass it. Routes that share a line (a ship calling on the
way), or whose lines run together from a port so that no such point can be
found (ships taking the same sound or harbour mouth), are one system,
priced from the first port passed to the last. Where no one line goes
between two ports (lines mapped leg by leg), the shortest way along lines
that meet (ends within JOIN_KM) is taken, if it isn't more than DETOUR
times the distance between the ports. A ferry line of no route
priced here that blocks a system's points the same way (another operator's,
a passenger line, a line mapped twice) is taken as the system's own.
"""
import heapq, math

POINT_KM, CLEAR_KM, MATCH_KM, QUAY_KM = 0.5, 0.3, 0.15, 0.8
JOIN_KM, DETOUR = 0.05, 2.5


def km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(h))


def along(line, d):
    """The point d km along a line of (lat, lon) points, or None past its end."""
    for a, b in zip(line, line[1:]):
        s = km(a, b)
        if s >= d and s > 0:
            f = d / s
            return round(a[0] + f * (b[0] - a[0]), 6), round(a[1] + f * (b[1] - a[1]), 6)
        d -= s
    return None


def off(p, line):
    """The distance in km from p to a line of (lat, lon) points."""
    cos = math.cos(math.radians(p[0]))
    best = math.inf
    for a, b in zip(line, line[1:]):
        ax, ay, bx, by = (a[1] - p[1]) * cos * 111.2, (a[0] - p[0]) * 111.2, (b[1] - p[1]) * cos * 111.2, (b[0] - p[0]) * 111.2
        dx, dy = bx - ax, by - ay
        u = max(0.0, min(1.0, -(ax * dx + ay * dy) / (dx * dx + dy * dy))) if dx or dy else 0.0
        best = min(best, math.hypot(ax + u * dx, ay + u * dy))
    return best


def nearest(line, p):
    """The index of the line's point nearest p, and its distance in km."""
    return min(((km(q, p), i) for i, q in enumerate(line)), key=lambda t: t[0])[::-1]


def lines_of(osm):
    """OpenStreetMap's ferry lines: (those a motor vehicle may take, those it may only with a permit)."""
    free, permit = [], []
    for w in osm.get("elements", []):
        t = w.get("tags", {})
        if w["type"] != "way" or t.get("route") != "ferry" or len(w.get("geometry", [])) < 2 or t.get("motor_vehicle") == "no":
            continue
        ln = (w["id"], [(g["lat"], g["lon"]) for g in w["geometry"]])
        (permit if t.get("motor_vehicle") in ("private", "permit", "destination") else free).append(ln)
    return free, permit


def features(osm):
    """Each element's tags and place (a node's, or the middle of its bounds)."""
    out = []
    for e in osm.get("elements", []):
        if e["type"] == "node":
            p = (e["lat"], e["lon"])
        elif e.get("bounds"):
            b = e["bounds"]
            p = ((b["minlat"] + b["maxlat"]) / 2, (b["minlon"] + b["maxlon"]) / 2)
        else:
            continue
        out.append((e.get("tags", {}), p))
    return out


def port_places(osm, lines, ports):
    """Each port's place: its ferry terminal (amenity=ferry_terminal) or
    place by name (or English name), at the nearest car ferry line's
    nearest point within 3 km; or, for a port whose terminal has no name,
    the end of a car ferry line (by its name) away from the other port.
    ports: {port: ("terminal"|"place", name) or ("end", line name, other port)}."""
    feats = features(osm)
    out = {}
    for port, (kind, name, *rest) in sorted(ports.items(), key=lambda x: x[1][0] == "end"):
        if kind == "end":
            other = out.get(rest[0])
            ids = {i for i, _ in lines}
            ends = [(g[0]["lat"], g[0]["lon"]) for w in osm.get("elements", []) if w["type"] == "way" and w["id"] in ids
                    and w.get("tags", {}).get("name") == name for g in (w["geometry"], w["geometry"][::-1])]
            if other and ends:
                out[port] = max(ends, key=lambda q: km(q, other))
            continue
        if kind == "terminal":
            hit = [p for t, p in feats if t.get("amenity") == "ferry_terminal" and t.get("name") == name]
        else:
            hit = [p for t, p in feats if t.get("place") and name in (t.get("name"), t.get("name:en"))]
        best = None
        for p in hit:
            for _, ln in lines:
                for q in ln:
                    d = km(p, q)
                    if d <= 3 and (best is None or d < best[0]):
                        best = (d, q)
        if best:
            out[port] = best[1]
    return out


class Blocked(Exception):
    pass


def network_path(lines, a, b):
    """The shortest way from a to b along ferry lines that meet, joined to
    the lines within QUAY_KM of each: (way ids, points, way at a, way at b) or None."""
    nodes, adj = {}, {}

    def node(p):
        return nodes.setdefault((round(p[0], 6), round(p[1], 6)), len(nodes))

    def edge(u, v, w, way):
        adj.setdefault(u, []).append((v, w, way))
        adj.setdefault(v, []).append((u, w, way))
    ends = []
    for i, ln in lines:
        ids = [node(p) for p in ln]
        for (u, p), (v, q) in zip(zip(ids, ln), zip(ids[1:], ln[1:])):
            edge(u, v, km(p, q), i)
        ends += [(ids[0], ln[0]), (ids[-1], ln[-1])]
    for k, (u, p) in enumerate(ends):
        for v, q in ends[k + 1:]:
            if u != v and km(p, q) <= JOIN_KM:
                edge(u, v, km(p, q), None)
    pt = {v: k for k, v in nodes.items()}
    src, dst = -1, -2
    for s, p in ((src, a), (dst, b)):
        for i, ln in lines:
            j, d = nearest(ln, p)
            if d <= QUAY_KM:
                edge(s, node(ln[j]), d, i)
    pt[src], pt[dst] = a, b
    dist, prev, heap = {src: 0.0}, {}, [(0.0, src)]
    while heap:
        d, u = heapq.heappop(heap)
        if u == dst:
            break
        if d > dist.get(u, math.inf):
            continue
        for v, w, way in adj.get(u, []):
            if d + w < dist.get(v, math.inf):
                dist[v], prev[v] = d + w, (u, way)
                heapq.heappush(heap, (d + w, v))
    if dst not in dist or dist[dst] > DETOUR * km(a, b):
        return None
    seq, u = [], dst
    while u != src:
        u, way = prev[u]
        seq.append((u, way))
    seq.reverse()  # (node, way into the next node), from src's first hop
    ways = [w for _, w in seq if w is not None]
    points = [pt[u] for u, _ in seq[1:]]
    return frozenset(ways), points, ways[0], ways[-1]


def systems(routes, pos, lines, permit, fail):
    """routes: {route: [(port, port), ...]} in order; pos: {port: (lat, lon)}.
    -> (systems as [(routes, {port: points}, [(route, a, b), ...])], notes).
    fail(message) is called when no system can be placed."""
    notes, pair_lines = [], {}
    for r, pairs in routes.items():
        for a, b in pairs:
            if a not in pos or b not in pos:
                notes.append(f"{a}–{b}: {'/'.join(x for x in (a, b) if x not in pos)} not found in OpenStreetMap, not priced")
                continue
            hit = [(frozenset([i]), ln, i, i) for i, ln in lines if nearest(ln, pos[a])[1] <= QUAY_KM and nearest(ln, pos[b])[1] <= QUAY_KM]
            if not hit and any(nearest(ln, pos[a])[1] <= QUAY_KM and nearest(ln, pos[b])[1] <= QUAY_KM for _, ln in permit):
                notes.append(f"{a}–{b}: motor vehicles only with a permit there (OpenStreetMap), not priced")
                continue
            if not hit:
                path = network_path(lines, pos[a], pos[b])
                if path and len(path[1]) > 1:
                    hit = [path]
            if not hit:
                notes.append(f"{a}–{b}: no car ferry line between them in OpenStreetMap, not priced")
                continue
            pair_lines[(r, a, b)] = hit
    sysof = {r: frozenset([r]) for r in routes}
    absorbed = {}  # lines of no route that run with a system's: taken as its own

    def merge(rs):
        parts = {sysof[r] for r in rs}
        m = frozenset().union(*parts)
        for r in m:
            sysof[r] = m
        got = set().union(*(absorbed.get(p, set()) for p in parts)) if parts else set()
        if got:
            absorbed[m] = got
    for (r1, _, _), h1 in pair_lines.items():
        for (r2, _, _), h2 in pair_lines.items():
            if r1 != r2 and frozenset().union(*(x[0] for x in h1)) & frozenset().union(*(x[0] for x in h2)):
                merge([r1, r2])

    def place(rs):
        mine = {i for k, h in pair_lines.items() if k[0] in rs for ids, *_ in h for i in ids} | absorbed.get(rs, set())
        others = [(i, ln) for i, ln in lines + permit if i not in mine]
        stations = {}
        for (r, a, b), hit in pair_lines.items():
            if r not in rs:
                continue
            for _, ln, wa, wb in hit:
                ia, ib = nearest(ln, pos[a])[0], nearest(ln, pos[b])[0]
                for q, x, y, to, i in ((a, ia, ib, b, wa), (b, ib, ia, a, wb)):
                    part = ln[x:y + 1] if x < y else ln[y:x + 1][::-1]
                    length = sum(km(u, w) for u, w in zip(part, part[1:]))
                    d, blocking = min(POINT_KM, length / 4), set()
                    while True:
                        pt = along(part, d)
                        if pt is None or d > length / 2:
                            raise Blocked(blocking)
                        near = {j for j, l in others if off(pt, l) <= CLEAR_KM}
                        if not near:
                            break
                        blocking |= near
                        d += 0.1
                    pts = stations.setdefault(q, [])
                    if all(km(pt, (o["lat"], o["lon"])) > 0.05 for o in pts):
                        pts.append({"name": f"{q} port, {round(d, 1)} km out on the line to {to} (OSM way {i})", "lat": pt[0], "lon": pt[1]})
        return stations
    while True:
        changed = False
        # In the routes' order: a set of systems would be walked in an order
        # Python's string hashing changes from run to run, and which system
        # meets a blocking line first decides what merges, so the same data
        # gave different systems on different nights.
        order = list(routes)
        for rs in sorted({sysof[r] for r in routes if any(k[0] == r for k in pair_lines)}, key=lambda x: min(order.index(r) for r in x)):
            try:
                place(rs)
            except Blocked as e:
                with_ = {k[0] for k, h in pair_lines.items() for ids, *_ in h if ids & e.args[0]} - set(rs)
                if with_:
                    merge(set(rs) | with_)
                else:
                    # Ferry lines of no route priced here (another operator's, a
                    # passenger line, a line mapped twice) along the same water.
                    stray = set(e.args[0]) - absorbed.get(rs, set())
                    if not stray:
                        fail(f"{sorted(rs)}: no clear point on its lines")
                    absorbed[rs] = absorbed.get(rs, set()) | stray
                changed = True
                break
        if not changed:
            break
    out = []
    for r in routes:
        s = sorted(sysof[r], key=list(routes).index)
        if s not in [o[0] for o in out] and any(k[0] in s for k in pair_lines):
            out.append((s, place(frozenset(s)), [k for k in pair_lines if k[0] in s]))
    return out, notes
