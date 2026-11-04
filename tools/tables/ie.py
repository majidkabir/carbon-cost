"""Builds the Irish toll plaza table from TII's "Toll Locations and
Charges" pages (fetch.py's ie-<scheme>.html) and the toll booths in
OpenStreetMap (the workflow's ie-osm.geojsonseq: toll booths and toll
gantries, and the motorway, trunk and primary roads, from Geofabrik's
Ireland and Northern Ireland extract; its date in ie-osm-timestamp.txt).

Usage: python3 ie.py fetched/ out-dir -> out-dir/ie-<year>-01-01.json

Prices: each page's "APPLICABLE TOLLS <year>" table. On the eight PPP
roads goods vehicles over 3,500 kg pay by axles (2 or 3, 4 or more); the
prices include 23% VAT (the M3 page says so, TII's 2025 toll release for
all eight) and are divided by 1.23 here. The M3 page's first heavy line
reads "2 or more axles" before "four or more": taken as 2 or 3. The M50
(no VAT) charges goods vehicles of 2,000 to 10,000 kg and over 10,000 kg,
by tag, video account or unregistered: unregistered here, the tag price
for trucks paying by tag. Heavy goods vehicles pass the Dublin Port
Tunnel free (its page), so it isn't included.

Places: TII places each toll on a road between junctions. The road is
given below for each page (SCHEMES); the plaza is where OpenStreetMap's
toll booths or gantries on that road's main carriageway (the nearest
motorway, trunk or primary road within 40 m, with that ref) lie, the
booths within 1.5 km of each other making one plaza. The M3 has two
plazas: the northern page is the one further north. The M50's toll is
its westernmost booths (the others with the M50 ref are the Dublin Port
Tunnel's).
"""
import html, json, math, os, re, sys

SCHEMES = [("m1", "M1", None), ("m3", "M3", "north"), ("m3-blackbull", "M3", "south"), ("m4", "M4", None),
           ("n6", "M6", None), ("m7m8", "M7", None), ("n8", "M8", None), ("limerick", "N18", None),
           ("n25", "N25", None), ("m50", "M50", "west")]
VAT = 1.23
MAIN = {"motorway", "trunk", "primary"}


def km(a, b):
    return math.hypot((a[0] - b[0]) * 111.2 * math.cos(math.radians(a[1])), (a[1] - b[1]) * 111.2)


def seg_km(p, a, b):
    cos = math.cos(math.radians(p[1]))
    ax, ay, bx, by = (a[0] - p[0]) * cos * 111.2, (a[1] - p[1]) * 111.2, (b[0] - p[0]) * cos * 111.2, (b[1] - p[1]) * 111.2
    dx, dy = bx - ax, by - ay
    l = dx * dx + dy * dy
    t = 0 if l == 0 else max(0, min(1, -(ax * dx + ay * dy) / l))
    return math.hypot(ax + t * dx, ay + t * dy)


def page(path):
    t = open(path, encoding="utf-8").read()
    t = re.sub(r"<script.*?</script>", "", t, flags=re.S)
    t = re.sub(r"<(td|th|tr|p|h\d|li|div|br)[^>]*>", "\n", t)
    t = html.unescape(re.sub(r"<[^>]+>", "", t))
    return [re.sub(r"\s+", " ", x).strip() for x in t.split("\n") if x.strip()]


def euros(s):
    return float(re.fullmatch(r"€(\d+\.\d\d)", s).group(1))


def classes(c, sid):
    i = next(k for k, x in enumerate(c) if re.fullmatch(r"APPLICABLE TOLLS \d{4}\*?", x))
    year = re.search(r"\d{4}", c[i]).group(0)
    if sid == "m50":
        assert c[i + 1:i + 5] == ["Vehicle Category", "Tag", "Video", "Unreg"], c[i + 1:i + 5]
        out = []
        for label, mass in (("Goods vehicles between 2,000kg and 10,000kg", {"min_kg": 2001, "max_kg": 10000}),
                            ("Goods vehicles exceeding 10,000kg", {"min_kg": 10001})):
            k = c.index(label, i)
            tag, _, unreg = (euros(x) for x in c[k + 1:k + 4])
            out.append({**mass, "rate": unreg, "etc_rate": tag})
        return year, out
    heavy = [k for k in range(i, i + 20) if c[k].startswith("Goods Vehicles with a design gross vehicle weight exceeding 3,500")]
    assert len(heavy) == 2, c[i:i + 20]
    assert re.search(r"(2 or 3|2 or more) axles", c[heavy[0]]) and re.search(r"(4|four) or more", c[heavy[1]]), (c[heavy[0]], c[heavy[1]])
    return year, [{"min_kg": 3501, "max_axles": 3, "rate": round(euros(c[heavy[0] + 1]) / VAT, 4)},
                  {"min_kg": 3501, "min_axles": 4, "rate": round(euros(c[heavy[1] + 1]) / VAT, 4)}]


def plazas(path):
    booths, roads, ramps = [], [], set()
    for line in open(path, encoding="utf-8"):
        f = json.loads(line.strip("\x1e"))
        p, g = f["properties"], f["geometry"]
        if p.get("barrier") == "toll_booth" or p.get("highway") == "toll_gantry":
            if g["type"] == "Point":
                booths.append(tuple(g["coordinates"]))
        elif p.get("highway") in MAIN and p.get("ref") and g["type"] == "LineString":
            roads.append((p["ref"], g["coordinates"]))
        elif p.get("highway", "").endswith("_link") and g["type"] == "LineString":
            ramps.update(tuple(x) for x in g["coordinates"])
    on = {}
    for b in booths:
        if b in ramps:
            continue  # a ramp toll at a junction, not the plaza on the main road
        best = (0.04, None)
        for ref, cs in roads:
            if abs(cs[0][1] - b[1]) > 0.5 or abs(cs[0][0] - b[0]) > 0.8:
                continue
            for a, c in zip(cs, cs[1:]):
                d = seg_km(b, a, c)
                if d < best[0]:
                    best = (d, ref)
        if best[1]:
            for ref in best[1].split(";"):
                on.setdefault(ref.strip(), []).append(b)
    clusters = {}
    for ref, bs in on.items():
        cl = []
        for b in bs:
            for c in cl:
                if any(km(b, x) < 1.5 for x in c):
                    c.append(b)
                    break
            else:
                cl.append([b])
        clusters[ref] = [(sum(x[0] for x in c) / len(c), sum(x[1] for x in c) / len(c), len(c)) for c in cl]
    return clusters


def main(fetched, out):
    cl = plazas(os.path.join(fetched, "ie-osm.geojsonseq"))
    osm_date = open(os.path.join(fetched, "ie-osm-timestamp.txt")).read().strip()
    points, years = [], set()
    for sid, ref, pick in SCHEMES:
        c = page(os.path.join(fetched, f"ie-{sid}.html"))
        name = c[c.index("Toll Locations and Charges") + 1] if "Toll Locations and Charges" in c else sid
        title = next(x for x in c if x.startswith("Location:"))
        year, cls = classes(c, sid)
        years.add(year)
        found = sorted(cl.get(ref, []), key=lambda x: -x[1])
        if pick == "north":
            found = found[:1]
        elif pick == "south":
            found = found[-1:]
        elif pick == "west":
            found = sorted(found)[:1]
        if len(found) != 1:
            sys.exit(f"{sid}: {len(found)} plazas on the {ref} in OpenStreetMap: {found}")
        lon, lat, n = found[0]
        points.append({"name": name, "lat": round(lat, 6), "lon": round(lon, 6),
                       "rate": 0, "classes": cls})
        print(f"{sid}: {ref} plaza at {lat:.5f},{lon:.5f} ({n} booths); {title[:90]}")
    assert len(years) == 1, years
    year = years.pop()
    tb = {
        "country": "IE", "currency": "EUR", "valid_from": f"{year}-01-01", "valid_to": f"{year}-12-31",
        "name": "Irish national road tolls (M50 and the PPP toll roads)",
        "law": f"Roads Act 1993 (Part V) and the toll bye-laws of each scheme, maximum tolls for {year} as published by Transport Infrastructure Ireland per toll road: goods vehicles over 3,500 kg by axles (2 or 3, 4 or more) on the PPP roads, excluding 23% VAT; on the M50 (no VAT) by weight, at the unregistered price, or the tag price for trucks paying by tag. Heavy goods vehicles use the Dublin Port Tunnel free. Each toll is charged at its plaza (M50: its gantry), placed with OpenStreetMap's toll booths ({osm_date}).",
        "sources": [{"title": "TII: Toll Locations and Charges", "url": "https://www.tii.ie/en/roads-tolling/tolling-information/toll-locations-and-charges/"},
                    {"title": "OpenStreetMap (Geofabrik extract), toll booths", "url": "https://download.geofabrik.de/europe/ireland-and-northern-ireland.html"}],
        "vehicles": "Goods vehicles over 3,500 kg (M50: over 2,000 kg)",
        "min_kg": 3501,
        "tolled_roads": "The M1, M3 (two plazas), M4, M6, M7, M8, N18 Limerick Tunnel and N25 Waterford toll plazas and the M50 toll between junctions 6 and 7.",
        "point_match_km": 0.15,
        "toll_points": points,
        "rows": [],
    }
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"ie-{year}-01-01.json")
    json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, len(points), "plazas")


if __name__ == "__main__":
    main(*sys.argv[1:])
