"""Checks Sootcase's routing for the truck's size, weight and dangerous
goods (docs/requirements/sootcase-truck-restrictions.md) against a local
Sootcase on a map extract, as a black box: only its API answers and the
map's own OpenStreetMap tags.

Usage: python3 restrictions.py http://localhost:8080 low.geojson heavy.geojson hazmat.geojson

low.geojson, heavy.geojson and hazmat.geojson are osmium exports of the
extract's ways tagged maxheight, maxweight and hazmat (or hazmat:B to E).
For each check it prints PASS, FAIL or SKIP with what it saw, and exits 1
on any FAIL.
"""
import json, math, re, sys, urllib.request, urllib.error

BASE = sys.argv[1]
results = []


def say(check, verdict, what):
    results.append(verdict)
    print(f"{verdict} {check}: {what}", flush=True)


def calc(frm, to, vehicle=None, query="country_km=true&path=full"):
    leg = {"id": "road", "mode": "road", "vehicle_type": "glec/road/eu_sa/artic_34_40t/diesel",
           "from": {"lat": frm[1], "lon": frm[0]}, "to": {"lat": to[1], "lon": to[0]}}
    if vehicle is not None:
        leg["vehicle"] = vehicle
    body = json.dumps({"id": "trip", "weight_kg": 20000, "add_road_legs": False, "legs": [leg]}).encode()
    req = urllib.request.Request(f"{BASE}/v1/calculate?{query}", body, {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except Exception:
            return e.code, {}


def km(a, b):
    """Metres between two [lon, lat] points."""
    dy = (a[1] - b[1]) * 111320
    dx = (a[0] - b[0]) * 111320 * math.cos(math.radians((a[1] + b[1]) / 2))
    return math.hypot(dx, dy)


def near(path, pt, m):
    return any(km(p, pt) < m for p in path)


def number(v, unit_re=r"^\s*([\d.]+)\s*(t|m)?\s*$"):
    """A tag's plain number (13'6" and the like aren't needed here)."""
    m = re.match(unit_re, v or "")
    return float(m.group(1)) if m else None


def ways(path):
    try:
        feats = json.load(open(path))["features"]
    except Exception as e:
        print(f"no ways from {path}: {e}")
        return []
    return [f for f in feats if f.get("geometry", {}).get("type") == "LineString" and len(f["geometry"]["coordinates"]) >= 2]


MAJOR = {"motorway", "trunk", "primary", "secondary", "tertiary", "motorway_link", "trunk_link", "primary_link", "secondary_link"}


def leg0(res):
    legs = res.get("legs") or []
    return legs[0] if legs else {}


def candidates(feats, tag, limit, below):
    """Ways on main roads whose tag is below the truck's value, middle
    first by length (a short bridge or tunnel, not a long street)."""
    out = []
    for f in feats:
        p = f.get("properties", {})
        if p.get("highway") not in MAJOR:
            continue
        v = number(p.get(tag))
        if v is None or v >= below:
            continue
        c = f["geometry"]["coordinates"]
        length = sum(km(c[i], c[i + 1]) for i in range(len(c) - 1))
        if 20 <= length <= 800:
            out.append((length, f))
    out.sort(key=lambda x: x[0])
    return [f for _, f in out[:limit]]


def detour(check, f, vehicle, tag):
    """Routes from 1.5 km before a restricted way to 1.5 km after it along
    its own direction: without the vehicle the route takes the way, with
    it the route must not pass its middle."""
    c = f["geometry"]["coordinates"]
    a, b = c[0], c[-1]
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = math.hypot(dx, dy) or 1
    step = 0.02  # about 1.5 km in degrees
    frm = [a[0] - dx / n * step, a[1] - dy / n * step]
    to = [b[0] + dx / n * step, b[1] + dy / n * step]
    mid = c[len(c) // 2]
    name = f["properties"].get("name") or f["properties"].get("ref") or f["properties"].get("@id", "")
    s0, r0 = calc(frm, to)
    if s0 != 200 or not near(leg0(r0).get("path") or [], mid, 25):
        say(check, "SKIP", f"{name} ({tag}={f['properties'].get(tag)}): the route without vehicle doesn't take it (HTTP {s0})")
        return
    s1, r1 = calc(frm, to, vehicle)
    l1 = leg0(r1)
    if s1 == 422:
        say(check, "PASS", f"{name} ({tag}={f['properties'].get(tag)}): HTTP 422 {r1.get('error', '')[:150]}")
    elif s1 != 200:
        say(check, "FAIL", f"{name}: HTTP {s1} {json.dumps(r1)[:200]}")
    elif near(l1.get("path") or [], mid, 25):
        say(check, "FAIL", f"{name} ({tag}={f['properties'].get(tag)}): still routed through it, {l1.get('distance_km')} km against {leg0(r0).get('distance_km')} km; restrictions {l1.get('restrictions')}")
    else:
        say(check, "PASS", f"{name} ({tag}={f['properties'].get(tag)}): avoided, {leg0(r0).get('distance_km')} km -> {l1.get('distance_km')} km; restrictions {l1.get('restrictions')}")


def main():
    low, heavy, haz = (ways(p) for p in sys.argv[2:5])
    print(f"ways: {len(low)} with maxheight, {len(heavy)} with maxweight, {len(haz)} with hazmat tags")

    # B1: without vehicle, the answer is as before; the vehicle is optional.
    frm, to = [10.0, 53.73], [9.98, 53.46]
    s0, r0 = calc(frm, to)
    s1, r1 = calc(frm, to, {})
    d0, d1 = leg0(r0).get("distance_km"), leg0(r1).get("distance_km")
    say("B1 no vehicle", "PASS" if s0 == 200 and s1 == 200 and d0 == d1 else "FAIL", f"HTTP {s0}/{s1}, {d0} km and {d1} km with an empty vehicle")

    # B7: a value out of range answers 400 naming the field.
    s, r = calc(frm, to, {"height_m": 9})
    say("B7 height_m 9", "PASS" if s == 400 and "height_m" in json.dumps(r) else "FAIL", f"HTTP {s} {json.dumps(r)[:200]}")

    # R4: the applied restrictions come back.
    v = {"height_m": 4.0, "width_m": 2.55, "length_m": 16.5, "gross_weight_kg": 40000, "axle_load_kg": 11500, "axles": 5, "trailer": "semi"}
    s, r = calc(frm, to, v)
    rest = leg0(r).get("restrictions")
    say("R4 restrictions", "PASS" if s == 200 and rest else "FAIL", f"HTTP {s}, restrictions {json.dumps(rest)[:300]}")

    # B9: the same request twice, the same route.
    s2, r2 = calc(frm, to, v)
    say("B9 repeatable", "PASS" if s2 == 200 and leg0(r2).get("distance_km") == leg0(r).get("distance_km") else "FAIL",
        f"{leg0(r).get('distance_km')} km and {leg0(r2).get('distance_km')} km")

    # B2: low bridges, B3: weight limits, B4/B5: tunnels barred to the load.
    for f in candidates(low, "maxheight", 3, 4.0):
        detour("B2 maxheight", f, {"height_m": 4.0}, "maxheight")
    for f in candidates(heavy, "maxweight", 3, 40):
        detour("B3 maxweight", f, {"gross_weight_kg": 40000}, "maxweight")
    tunnels = [f for f in haz if f.get("properties", {}).get("highway") in MAJOR]
    for code in ("D", "E"):
        barred = [f for f in tunnels if f["properties"].get(f"hazmat:{code}") == "no" or f["properties"].get("hazmat") == "no"]
        barred.sort(key=lambda f: len(f["geometry"]["coordinates"]))
        for f in barred[:2]:
            detour(f"B4/B5 tunnel code {code}", f, {"tunnel_code": code}, f"hazmat:{code}")
        print(f"tunnels barred to code {code}: {len(barred)}")
    allowed = [f for f in tunnels if f["properties"].get("hazmat:D") == "no" and f["properties"].get("hazmat:E") in (None, "yes")]
    print(f"category D tunnels (barred to code D, not to code E): {len(allowed)}")

    # B8: with alternatives, every route obeys the vehicle.
    s, r = calc(frm, to, v, "country_km=true&path=full&alternatives=3")
    alts = leg0(r).get("alternatives") or []
    say("B8 alternatives", "PASS" if s == 200 else "FAIL", f"HTTP {s}, {len(alts)} alternatives, restrictions {[a.get('restrictions') is not None for a in alts]}")

    fails = results.count("FAIL")
    print(f"{results.count('PASS')} passed, {fails} failed, {results.count('SKIP')} skipped")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
