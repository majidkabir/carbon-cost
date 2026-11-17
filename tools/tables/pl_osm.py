"""Shared helper for Poland's concession motorways: places a toll system's
stations at the OpenStreetMap motorway junctions and toll booths of their
names along the motorway (pl-concessions-osm.json, fetch.py's copy of an
Overpass answer: the junctions and toll booths in each corridor's box).
"""
import math
import re
import sys
import unicodedata


def key(s):
    s = unicodedata.normalize("NFKD", s.replace("ł", "l").replace("Ł", "L"))
    return re.sub(r"[^a-z0-9]+", " ", "".join(ch for ch in s if not unicodedata.combining(ch)).lower()).strip()


def km(a, b):
    return math.hypot((a[0] - b[0]) * 111.2, (a[1] - b[1]) * 111.2 * math.cos(math.radians(a[0])))


def nodes(d, box):
    """The junctions and toll booths in box (south, west, north, east)."""
    s, w, n, e = box
    return [x for x in d["elements"] if x.get("type") == "node" and s <= x["lat"] <= n and w <= x["lon"] <= e]


def place(what, d, box, names, aliases=None, spread_km=3.0, optional=()):
    """Stations named as in names, each at the motorway junctions of its name
    (or a name ending in it) and the toll booths whose name holds it;
    aliases: OpenStreetMap's other names for a station (as "Modła" for
    "Konin Modła"). Exits when a station has no point or its points lie more
    than spread_km apart; a station in optional with no point is left out.""" 
    pts = nodes(d, box)
    stations = []
    for n in names:
        wants = [key(w) for w in [n] + (aliases or {}).get(n, [])]
        jname = lambda p: key(p["tags"].get("name", ""))
        js = [p for p in pts if p.get("tags", {}).get("highway") == "motorway_junction"
              and any(jname(p) == w or jname(p).endswith(" " + w) for w in wants)]
        bs = [p for p in pts if p.get("tags", {}).get("barrier") == "toll_booth"
              and any(re.search(r"\b" + re.escape(w) + r"\b", jname(p)) for w in wants)]
        got = [(p["lat"], p["lon"], "booth" if p in bs else "junction") for p in bs + js]
        if not got and n in optional:
            print(f"{what}: {n} not in OpenStreetMap; left out (priced as its free neighbour)")
            continue
        if not got:
            sys.exit(f"{what}: no junction or toll booth named {n!r} in OpenStreetMap")
        if max(km(a, b) for a in got for b in got) > spread_km:
            sys.exit(f"{what}: {n!r}'s junctions and booths lie more than {spread_km} km apart: {got}")
        stations.append({"name": n, "points": [{"name": w, "lat": round(a, 5), "lon": round(b, 5)} for a, b, w in got]})
    return stations
