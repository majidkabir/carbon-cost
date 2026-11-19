"""Builds Albania's A1 (Rruga e Kombit, Milot–Morinë) toll: one toll
plaza by the Thirrë/Kalimash tunnel, charged per passage either way.

Usage: python3 al.py fetched/ out-dir -> out-dir/al-<date>.json

Prices: ATRAKO, the state concessions agency (fetch.py's al-atrako.html,
or browser/al-atrako.txt read in Chrome when that isn't fetched): the
concession contract's toll (clauses 11.4.3 and 11.4.4), EUR 5 with VAT
times each class's coefficient: class 4 (G: three axles, or commercial
vehicles over 2.70 m) 16.25, class 5 (H: four axles or more) 22.50.
Trucks over 3.5 t with two or three axles are taken to be over 2.70 m
(class 4). 20% VAT is divided out.

Position: OSM toll booths (al-osm.json) within 0.3 km of the A1 motorway,
east of Milot; they must lie together (within 2 km).
"""
import html, json, math, os, re, sys

BROWSER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "browser")
VAT = 1.2
START = "2026-11-13"  # the day the ATRAKO page was first read; it gives no date


def km(a, b):
    return math.hypot((a[1] - b[1]) * math.cos(math.radians(a[0])) * 111.32, (a[0] - b[0]) * 110.57)


def seg(p, a, b):
    k = math.cos(math.radians(p[0]))
    ax, ay = (a[1] - p[1]) * k * 111.32, (a[0] - p[0]) * 110.57
    bx, by = (b[1] - p[1]) * k * 111.32, (b[0] - p[0]) * 110.57
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    u = 0 if L == 0 else max(0, min(1, -(ax * dx + ay * dy) / L))
    return math.hypot(ax + u * dx, ay + u * dy)


def text(fetched):
    p = os.path.join(fetched, "al-atrako.html")
    if os.path.exists(p):
        t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<(script|style).*?</\1>", " ", open(p, encoding="utf-8", errors="replace").read(), flags=re.S))))
        if "Kamion të rëndë" in t:
            return t, "fetched"
    b = os.path.join(BROWSER, "al-atrako.txt")
    print("al-atrako: the copy read in Chrome")
    return re.sub(r"\s+", " ", " ".join(l for l in open(b, encoding="utf-8") if not l.startswith("# "))), "browser"


def main(fetched, out):
    t, how = text(fetched)
    base = re.search(r"(\d+) Euro me TVSH", t)
    c4 = re.search(r"4 G Kamione të mesëm dhe autobusë të rëndë \(3 akse\), duke përfshirë automjete komerciale me lartësi mbi 2,70m ([\d.]+) ([\d.]+)", t)
    c5 = re.search(r"5 H Kamion të rëndë \(4 akse dhe me shume\) ([\d.]+) ([\d.]+)", t)
    if not base or not c4 or not c5 or "11.4.3" not in t:
        sys.exit(f"Albania: the ATRAKO page changed ({bool(base)}, {bool(c4)}, {bool(c5)})")
    b = float(base.group(1))
    for c in (c4, c5):
        if abs(float(c.group(1)) * b - float(c.group(2))) > 0.005:
            sys.exit(f"Albania: {c.group(0)} isn't the coefficient times EUR {b}")

    d = json.load(open(os.path.join(fetched, "al-osm.json")))
    ways = [[(g["lat"], g["lon"]) for g in e["geometry"]] for e in d["elements"] if e["type"] == "way" and len(e.get("geometry", [])) > 1]
    booths = [(e["lat"], e["lon"]) for e in d["elements"] if e["type"] == "node" and e.get("tags", {}).get("barrier") == "toll_booth"
              and e["lon"] > 19.75 and any(seg((e["lat"], e["lon"]), w[i], w[i + 1]) < 0.3 for w in ways for i in range(len(w) - 1))]
    if not booths or max(km(a, b2) for a in booths for b2 in booths) > 2:
        sys.exit(f"Albania: toll booths on the A1 {booths}")
    lat, lon = sum(x[0] for x in booths) / len(booths), sum(x[1] for x in booths) / len(booths)
    src = {"title": "ATRAKO (Agjencia e Trajtimit të Koncesioneve): Rruga e Kombit" + (" (read in Chrome: tools/tables/browser/al-atrako.txt)" if how == "browser" else ""), "url": "https://atrako.gov.al/?p=1076"}
    tb = {
        "country": "AL", "currency": "EUR", "valid_from": START, "crossings": True,
        "osm_extract": d.get("osm3s", {}).get("timestamp_osm_base", "")[:10],
        "name": "A1 Rruga e Kombit toll (Milot–Morinë)",
        "law": (f"The Milot–Morinë motorway concession contract (clauses 11.4.3 and 11.4.4), as ATRAKO, the state concessions agency, publishes it: EUR {b:g} with VAT per passage times the class's coefficient, "
                f"class 4 (G: three axles, or commercial vehicles over 2.70 m) EUR {c4.group(2)}, class 5 (H: four axles or more) EUR {c5.group(2)}; trucks over 3.5 t with two or three axles are taken to be over 2.70 m. "
                "Excluding 20% VAT. Charged at the toll plaza by the Thirrë tunnel, either way. The page gives no date: valid_from is the day it was first read."),
        "sources": [src, {"title": "OpenStreetMap (Overpass API): toll booths on the A1", "url": "https://www.openstreetmap.org/"}],
        "vehicles": "Classes 4 and 5 (here trucks over 3.5 t)", "min_kg": 3501,
        "tolled_roads": "A1 Rruga e Kombit, Milot–Morinë (one plaza, by the Thirrë/Kalimash tunnel).",
        "point_match_km": 0.2,
        "toll_points": [{"name": "Rruga e Kombit: Kalimash toll plaza", "lat": round(lat, 6), "lon": round(lon, 6), "rate": 0,
                         "classes": [{"min_kg": 3501, "max_axles": 3, "rate": round(float(c4.group(2)) / VAT, 4)},
                                     {"min_kg": 3501, "min_axles": 4, "rate": round(float(c5.group(2)) / VAT, 4)}]}],
        "rows": [],
    }
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"al-{START}.json")
    json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, len(booths), "booths")


if __name__ == "__main__":
    main(*sys.argv[1:])
