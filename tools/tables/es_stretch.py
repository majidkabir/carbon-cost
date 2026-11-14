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


def lines(osm, refs):
    """The one-way carriageway chains of the ways whose ref includes one of refs."""
    ways = []
    for e in osm["elements"]:
        t = e.get("tags", {})
        if e["type"] == "way" and t.get("highway") in ("motorway", "trunk") and set(r.strip() for r in t.get("ref", "").split(";")) & set(refs):
            g = tuple((p["lon"], p["lat"]) for p in e["geometry"])
            ways.append(g[::-1] if t.get("oneway") == "-1" else g)
    return [l for l in m6toll.chains(ways) if m6toll.along(l)[-1] > 1]


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


def booths(osm):
    return [((e["lon"], e["lat"]), plain(e.get("tags", {}).get("name", ""))) for e in osm["elements"]
            if e["type"] == "node" and e.get("tags", {}).get("barrier") == "toll_booth"]


def assign(order, match, line, cum, juncs, near=0.06):
    """{station: km along line}: the stations in the tariff's order (or its
    reverse, whichever matches more) at junctions on the line whose words
    match the station (match(station, words)), keeping the order: the
    longest such matching (a station at most one junction)."""
    js = sorted((x, w) for x, w in ((m6toll.project(line, cum, p)[0], w) for p, w, _ in juncs if m6toll.project(line, cum, p)[1] < near))
    best = {}
    for seq in (order, order[::-1]):
        n, m = len(seq), len(js)
        f = [[0] * (m + 1) for _ in range(n + 1)]
        for i in range(1, n + 1):
            for j in range(1, m + 1):
                f[i][j] = max(f[i - 1][j], f[i][j - 1], f[i - 1][j - 1] + 1 if match(seq[i - 1], js[j - 1][1]) else 0)
        got, i, j = {}, n, m
        while i and j:
            if f[i][j] == f[i - 1][j]:
                i -= 1
            elif f[i][j] == f[i][j - 1]:
                j -= 1
            else:
                got[seq[i - 1]] = js[j - 1][0]
                i, j = i - 1, j - 1
        if len(got) > len(best):
            best = got
    return best


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
