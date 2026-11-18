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
priced from the first port passed to the last.
"""
import math

POINT_KM, CLEAR_KM, MATCH_KM, QUAY_KM = 0.5, 0.3, 0.15, 0.8


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


class Blocked(Exception):
    pass


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
            hit = [(i, ln) for i, ln in lines if nearest(ln, pos[a])[1] <= QUAY_KM and nearest(ln, pos[b])[1] <= QUAY_KM]
            if not hit:
                why = ("motor vehicles only with a permit there (OpenStreetMap)" if any(
                    nearest(ln, pos[a])[1] <= QUAY_KM and nearest(ln, pos[b])[1] <= QUAY_KM for _, ln in permit)
                    else "no car ferry line between them in OpenStreetMap")
                notes.append(f"{a}–{b}: {why}, not priced")
                continue
            pair_lines[(r, a, b)] = hit
    sysof = {r: frozenset([r]) for r in routes}

    def merge(rs):
        m = frozenset().union(*(sysof[r] for r in rs))
        for r in m:
            sysof[r] = m
    for (r1, _, _), h1 in pair_lines.items():
        for (r2, _, _), h2 in pair_lines.items():
            if r1 != r2 and {i for i, _ in h1} & {i for i, _ in h2}:
                merge([r1, r2])

    def place(rs):
        mine = {i for k, h in pair_lines.items() if k[0] in rs for i, _ in h}
        others = [(i, ln) for i, ln in lines + permit if i not in mine]
        stations = {}
        for (r, a, b), hit in pair_lines.items():
            if r not in rs:
                continue
            for i, ln in hit:
                ia, ib = nearest(ln, pos[a])[0], nearest(ln, pos[b])[0]
                for q, x, y, to in ((a, ia, ib, b), (b, ib, ia, a)):
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
        for rs in {sysof[r] for r in routes if any(k[0] == r for k in pair_lines)}:
            try:
                place(rs)
            except Blocked as e:
                with_ = {k[0] for k, h in pair_lines.items() for i, _ in h if i in e.args[0]} - set(rs)
                if not with_:
                    fail(f"{sorted(rs)}: no clear point on its lines (blocked by OpenStreetMap ways {sorted(e.args[0])}, of no route)")
                merge(set(rs) | with_)
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
