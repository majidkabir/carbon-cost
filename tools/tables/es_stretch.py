"""Shared helpers for Spanish toll motorways priced by entry and exit whose
stations OSM doesn't name: each station is placed at the junction whose
exit link is signposted to it, in the tariff's order along the motorway,
and the toll system's stations are the carriageways' stretches between
two consecutive entries/exits (as es_basque.py and m6toll.py).

Input: an Overpass JSON (out geom tags) with the motorway's carriageways,
their junction nodes, the links within 1.5 km (their destination,
destination:ref and exit_to tags) and toll booths.
"""
import re, unicodedata

import m6toll


def plain(s):
    s = unicodedata.normalize("NFD", s.lower())
    return re.sub(r"[^a-z0-9]+", " ", "".join(c for c in s if unicodedata.category(c) != "Mn")).strip()


def walk(ways):
    """The one-way ways joined end to start into carriageways (lists of
    (lon, lat)): from each way no other leads into, following at each
    fork the way that turns least (a toll plaza's parallel lanes, a split
    for a junction), each way used once."""
    by_start = {}
    for w in ways:
        by_start.setdefault(w[0], []).append(w)
    ends = {w[-1] for w in ways}
    used, out = set(), []

    def go(w):
        line = list(w)
        used.add(id(w))
        while True:
            nxt = [x for x in by_start.get(line[-1], []) if id(x) not in used]
            if not nxt:
                return line
            h = m6toll.bearing(line[-2], line[-1])
            w2 = min(nxt, key=lambda x: abs((m6toll.bearing(x[0], x[1]) - h + 540) % 360 - 180))
            used.add(id(w2))
            line += w2[1:]

    for w in ways:
        if w[0] not in ends:
            out.append(go(w))
    for w in ways:  # what's left: lanes beside the chosen one, or loops
        if id(w) not in used and len(w) > 1:
            out.append(go(w))
    return out


def lines(osm, refs):
    """The one-way carriageway chains of the ways whose ref includes one of
    refs, over 1 km."""
    ways = []
    for e in osm["elements"]:
        t = e.get("tags", {})
        if e["type"] == "way" and t.get("highway") in ("motorway", "trunk") and set(r.strip() for r in t.get("ref", "").split(";")) & set(refs):
            g = tuple((p["lon"], p["lat"]) for p in e["geometry"])
            ways.append(g[::-1] if t.get("oneway") == "-1" else g)
    return [l for l in walk(ways) if m6toll.along(l)[-1] > 1]


def signs(osm):
    """[(lon, lat), words]: each junction node with the signposted words of
    the links leaving the motorway there (their first node within 60 m):
    destination, destination:ref, exit_to, and the junction's own name and
    exit_to."""
    links = []
    for e in osm["elements"]:
        t = e.get("tags", {})
        if e["type"] == "way" and t.get("highway", "").endswith("_link"):
            g = e["geometry"]
            if t.get("oneway") == "-1":
                g = g[::-1]
            words = " ".join(t.get(k, "") for k in ("destination", "destination:ref", "exit_to", "destination:street", "name"))
            if words.strip():
                links.append(((g[0]["lon"], g[0]["lat"]), words))
    out = []
    for e in osm["elements"]:
        t = e.get("tags", {})
        if e["type"] == "node" and t.get("highway") == "motorway_junction":
            p = (e["lon"], e["lat"])
            words = [t.get("name", ""), t.get("exit_to", "")] + [w for q, w in links if m6toll.km(p, q) < 0.06]
            out.append((p, plain(" ".join(words)), t.get("ref", "")))
    return out


def open_end(p, h, ls, me):
    """Whether the carriageway ends (or begins) at p, heading h: no other
    line runs on from there (within 0.6 km and 60 degrees)."""
    for l in ls:
        if l is me:
            continue
        cum = m6toll.along(l)
        x, d = m6toll.project(l, cum, p)
        if d < 0.6 and abs((m6toll.at(l, cum, x)[1] - h + 540) % 360 - 180) < 60:
            return False
    return True


def booths(osm):
    return [((e["lon"], e["lat"]), plain(e.get("tags", {}).get("name", ""))) for e in osm["elements"]
            if e["type"] == "node" and e.get("tags", {}).get("barrier") == "toll_booth"]


def assign(order, match, line, cum, juncs, booths=(), near=0.06):
    """{station: km along line}: the stations in the tariff's order (or its
    reverse, whichever places more) at junctions on the line: a junction
    matches a station where its signposted words do (match(station,
    words)); a station with a toll booth of its name within 1.5 km of the
    line matches only the junction nearest that booth. The longest
    matching that keeps the order (a station at one junction at most);
    returns the order it ran in too."""
    js = []
    for p, w, _ in juncs:
        x, d = m6toll.project(line, cum, p)
        if d < near:
            js.append((x, w))
    js.sort()
    pinned = {}
    for p, name in booths:
        x, d = m6toll.project(line, cum, p)
        if d < 1.5 and js:
            for s in order:
                if name and match(s, name):
                    pinned[s] = min(range(len(js)), key=lambda j: abs(js[j][0] - x))
    ok = lambda s, j: pinned[s] == j if s in pinned else match(s, js[j][1])
    best, how = {}, order
    for seq in (order, order[::-1]):
        n, m = len(seq), len(js)
        f = [[0] * (m + 1) for _ in range(n + 1)]
        for a in range(1, n + 1):
            for b in range(1, m + 1):
                f[a][b] = max(f[a - 1][b], f[a][b - 1], f[a - 1][b - 1] + 1 if ok(seq[a - 1], b - 1) else 0)
        got, a, b = {}, n, m
        while a and b:
            if f[a][b] == f[a - 1][b]:
                a -= 1
            elif f[a][b] == f[a][b - 1]:
                b -= 1
            else:
                got[seq[a - 1]] = js[b - 1][0]
                a, b = a - 1, b - 1
        if len(got) > len(best):
            best, how = got, seq
    return best, how


def stretches(ls, pts, tol=0.15):
    """[(entry, exit, (lon, lat), heading)]: each carriageway (ls, one-way
    lines) cut at the stations (pts: {station: [(lon, lat)]}, the mean of
    a station's places within tol km), a stretch per two consecutive
    stations, at its middle and in its direction. Where OSM breaks a
    carriageway into pieces, a piece's head joins the last station passed
    on the piece it leaves and its tail the first station on the piece it
    joins (within 0.6 km, heading within 100 degrees)."""
    pieces = []
    for line in ls:
        cum = m6toll.along(line)
        c = []
        for s, ps in pts.items():
            near = [x for x, d in (m6toll.project(line, cum, p) for p in ps) if d < tol]
            if near:
                c.append((sum(near) / len(near), s))
        pieces.append((line, cum, sorted(c)))

    def onto(p, h, me):
        best = None
        for q in pieces:
            if q is me:
                continue
            x, d = m6toll.project(q[0], q[1], p)
            if d < 0.6 and abs((m6toll.at(q[0], q[1], x)[1] - h + 540) % 360 - 180) < 100 and (best is None or d < best[0]):
                best = (d, q, x)
        return best and best[1:]

    out = {}

    def add(a, b, line, cum, xa, xb):
        if a != b and xb - xa > 0.05:
            p, h = m6toll.at(line, cum, (xa + xb) / 2)
            out.setdefault((a, b), (p, h))

    for piece in pieces:
        line, cum, c = piece
        for (xa, a), (xb, b) in zip(c, c[1:]):
            add(a, b, line, cum, xa, xb)
        if not c:
            continue
        if c[0][0] > 0.1:
            o = onto(line[0], m6toll.at(line, cum, 0)[1], piece)
            before = [s for x, s in o[0][2] if x <= o[1] + 0.05] if o else []
            if before:
                add(before[-1], c[0][1], line, cum, 0, c[0][0])
        if c[-1][0] < cum[-1] - 0.1:
            o = onto(line[-1], m6toll.at(line, cum, cum[-1])[1], piece)
            after = [s for x, s in o[0][2] if x >= o[1] - 0.05 and s != c[-1][1]] if o else []
            if after:
                add(c[-1][1], after[0], line, cum, c[-1][0], cum[-1])
    return [(a, b, p, h) for (a, b), (p, h) in out.items()]


def system(name, law, secs, price, groups, label=lambda s: s, directed=False):
    """A closed system of stretches: a trip's first stretch gives its
    entry, its last its exit; price(entry, exit) -> {group: euros} or None.
    Pairs of stretches are those a trip can run in order (one stretch
    ending where the next starts)."""
    nxt = {}
    for a, b, _, _ in secs:
        nxt.setdefault(a, set()).add(b)
    sname = lambda a, b: f"{label(a)} > {label(b)}"
    prices = {}
    for a, b, _, _ in secs:
        seen, todo = {(a, b)}, [(a, b)]
        while todo:
            x, y = todo.pop()
            p = price(a, y)
            if p:
                prices[f"{sname(a, b)}|{sname(x, y)}"] = p
            for z in nxt.get(y, ()):
                if (y, z) not in seen and z != x:
                    seen.add((y, z))
                    todo.append((y, z))
    return {"name": name, "law": law, "directed": True, "station_match_km": 0.1, "groups": groups,
            "stations": [{"name": sname(a, b), "points": [{"name": f"between {label(a)} and {label(b)}", "lat": round(p[1], 6), "lon": round(p[0], 6), "heading": h}]}
                         for a, b, p, h in sorted(secs)],
            "prices": dict(sorted(prices.items()))}
