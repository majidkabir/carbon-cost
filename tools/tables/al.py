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

Thumanë–Kashar (the motorway by Tirana airport, G2 Infra's concession):
G2 Infra's price list (fetch.py's al-g2infra.html, or browser/al-g2infra.txt
read in Chrome), a price per trip between Kashar, Rinas (the airport
junction) and Thumanë for 2 or 3 axles and for 4 or more (over 2.20 m;
here trucks over 3.5 t), in euro with 20% VAT, which is divided out. Its
plazas all lie at the Rinas junction: on each carriageway beyond it and on
its ramps, so a trip is priced by the stations it passes: Kashar and
Thumanë on the motorway's two carriageways south and north of the
junction's ramps, Rinas on its link to the airport road (STATIONS), each
checked against OSM (al-g2-osm.json): the motorway within 30 m of Kashar
and Thumanë, a link within 30 m of Rinas and G2 Infra's booths within
0.6 km of Rinas.
"""
import html, json, math, os, re, sys

BROWSER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "browser")
VAT = 1.2
START = "2026-11-13"  # the day the ATRAKO page was first read; it gives no date
# Thumanë–Kashar's stations (lat, lon): on the motorway 1.4 km south and
# 1.6 km north of the Rinas junction's plazas, and on the junction's link to
# the airport road, 0.4 km from the motorway.
STATIONS = {"Kashar": (41.40500, 19.69660), "Rinas": (41.41942, 19.70690), "Thumanë": (41.43500, 19.70505)}
G2_URL = "https://g2infra.al/en/sherbimet/"


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


def g2_text(fetched):
    p = os.path.join(fetched, "al-g2infra.html")
    if os.path.exists(p):
        t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<(script|style).*?</\1>", " ", open(p, encoding="utf-8", errors="replace").read(), flags=re.S))))
        if "4 or more axles" in t:
            return t, "fetched"
    b = os.path.join(BROWSER, "al-g2infra.txt")
    print("al-g2infra: the copy read in Chrome")
    return re.sub(r"\s+", " ", " ".join(l for l in open(b, encoding="utf-8") if not l.startswith("# "))), "browser"


def thumane(fetched):
    """Thumanë–Kashar's closed system: G2 Infra's prices between its three
    stations, placed at STATIONS and checked against OSM."""
    t, how = g2_text(fetched)
    prices = {}
    for cls, axles in (("III", "2 or 3 axles"), ("IV", "4 or more axles")):
        m = re.search(r"has " + axles + r" and a height over 2\.20 meters\. Kashar – Thumanë – Kashar: (\d+) ALL or ([\d.]+) € "
                      r"Rinas – Kashar – Rinas: (\d+) ALL or ([\d.]+) € Rinas – Thumanë – Rinas: (\d+) ALL or ?([\d.]+) €", t)
        if not m:
            sys.exit(f"Albania: G2 Infra's price list changed ({axles})")
        for pair, eur in (("Kashar|Thumanë", m.group(2)), ("Kashar|Rinas", m.group(4)), ("Rinas|Thumanë", m.group(6))):
            prices.setdefault(pair, {})[cls] = round(float(eur) / VAT, 4)
    d = json.load(open(os.path.join(fetched, "al-g2-osm.json")))
    ways = {e["id"]: (e["tags"].get("highway"), [(g["lat"], g["lon"]) for g in e["geometry"]]) for e in d["elements"] if e["type"] == "way" and len(e.get("geometry", [])) > 1}
    near = lambda p, kind: min((seg(p, w[i], w[i + 1]) for h, w in ways.values() if h == kind for i in range(len(w) - 1)), default=9)
    for name, p in STATIONS.items():
        kind = "motorway_link" if name == "Rinas" else "motorway"
        if near(p, kind) > 0.03:
            sys.exit(f"Albania: no {kind} within 30 m of Thumanë–Kashar's {name} station {p}")
    booths = [(e["lat"], e["lon"]) for e in d["elements"] if e["type"] == "node" and e.get("tags", {}).get("barrier") == "toll_booth"
              and e["tags"].get("operator") == "G2 Infra"]
    if not booths or max(km(b, STATIONS["Rinas"]) for b in booths) > 0.6:
        sys.exit(f"Albania: G2 Infra's toll booths {booths} aren't all at the Rinas junction")
    law = ("G2 Infra's price list for the Thumanë–Vorë–Kashar motorway (Ministria e Infrastrukturës dhe Energjisë's concession): a price per trip "
           "between Kashar, Rinas (the airport junction) and Thumanë, either way, for a vehicle with 2 or 3 axles and for one with 4 or more, over 2.20 m "
           "(here trucks over 3.5 t): Kashar–Thumanë EUR {}/{}, Kashar–Rinas EUR {}/{}, Rinas–Thumanë EUR {}/{}, with 20% VAT, which is divided out. "
           "Its plazas lie at the Rinas junction, on each carriageway beyond the junction and on its ramps, so the trip is priced by the stations it passes. "
           "The page gives no date.").format(*(m2 for pair in ("Kashar|Thumanë", "Kashar|Rinas", "Rinas|Thumanë") for m2 in
                                                (round(prices[pair]["III"] * VAT, 2), round(prices[pair]["IV"] * VAT, 2))))
    src = {"title": "G2 Infra: Services, vehicle class prices in the toll system (Thumanë–Vorë–Kashar)" + (" (read in Chrome: tools/tables/browser/al-g2infra.txt)" if how == "browser" else ""), "url": G2_URL}
    return {"name": "A1 Thumanë–Kashar", "law": law, "station_match_km": 0.1,
            "groups": [{"name": "III", "min_kg": 3501, "max_axles": 3}, {"name": "IV", "min_kg": 3501, "min_axles": 4}],
            "stations": [{"name": n, "points": [{"lat": p[0], "lon": p[1]}]} for n, p in STATIONS.items()],
            "prices": prices}, src, d.get("osm3s", {}).get("timestamp_osm_base", "")[:10]


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
    tk, tksrc, tkosm = thumane(fetched)
    tb = {
        "country": "AL", "currency": "EUR", "valid_from": START, "crossings": True,
        "osm_extract": d.get("osm3s", {}).get("timestamp_osm_base", "")[:10],
        "name": "A1 Rruga e Kombit toll (Milot–Morinë) and Thumanë–Kashar",
        "law": (f"The Milot–Morinë motorway concession contract (clauses 11.4.3 and 11.4.4), as ATRAKO, the state concessions agency, publishes it: EUR {b:g} with VAT per passage times the class's coefficient, "
                f"class 4 (G: three axles, or commercial vehicles over 2.70 m) EUR {c4.group(2)}, class 5 (H: four axles or more) EUR {c5.group(2)}; trucks over 3.5 t with two or three axles are taken to be over 2.70 m. "
                "Excluding 20% VAT. Charged at the toll plaza by the Thirrë tunnel, either way. The page gives no date: valid_from is the day it was first read. "
                + tk["law"]),
        "sources": [src, tksrc, {"title": "G2 Infra's base fare 'EUR 2.5 with VAT' (its statement to Monitor, as A2 CNN reports it)", "url": "https://a2news.com/shqiperia/ekonomi/thumane-kashar-nga-tarifa-te-garancia-e-buxhetit-dhe-mirembajt-i1137091"},
                    {"title": "OpenStreetMap (Overpass API): toll booths on the A1, and the motorway and G2 Infra's booths by Tirana airport", "url": "https://www.openstreetmap.org/"}],
        "vehicles": "Classes 4 and 5 (here trucks over 3.5 t)", "min_kg": 3501,
        "tolled_roads": "A1 Rruga e Kombit, Milot–Morinë (one plaza, by the Thirrë/Kalimash tunnel); Thumanë–Kashar (by its stations Kashar, Rinas and Thumanë).",
        "point_match_km": 0.2,
        "toll_points": [{"name": "Rruga e Kombit: Kalimash toll plaza", "lat": round(lat, 6), "lon": round(lon, 6), "rate": 0,
                         "classes": [{"min_kg": 3501, "max_axles": 3, "rate": round(float(c4.group(2)) / VAT, 4)},
                                     {"min_kg": 3501, "min_axles": 4, "rate": round(float(c5.group(2)) / VAT, 4)}]}],
        "closed_systems": [tk],
        "rows": [],
    }
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"al-{START}.json")
    json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, len(booths), "booths")


if __name__ == "__main__":
    main(*sys.argv[1:])
