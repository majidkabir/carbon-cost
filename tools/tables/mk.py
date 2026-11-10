"""Builds the North Macedonian toll station table from the transcribed
toll table (tools/tables/transcribed/mk-2025.json: Службен весник
88/2025, the tolls in euro per toll station) and the toll booths in
OpenStreetMap (the workflow's mk-osm.geojsonseq, from Geofabrik's North
Macedonia extract).

Usage: python3 mk.py transcribed/mk-2025.json fetched/ out-dir -> out-dir/mk-<date>.json

Categories (Службен весник 118/2019, art. 2, by axles and the height at
the front axle): a truck (1.8 m or more at the front axle) with two or
three axles is category III, with four or more category IV. The euro
table is the price paid in cash in euro (the denar table is the price in
denars, which the ECB publishes no rate for).

Each station's booths are the OSM toll booths named "Патарина <station>".
A booth on a one-way carriageway charges that direction (its heading
from the way's geometry at the booth); the others charge both directions
and make one point at their centre.
"""
import json, math, os, sys


def heading(a, b):
    dy = (b[1] - a[1]) * 111.2
    dx = (b[0] - a[0]) * 111.2 * math.cos(math.radians(a[1]))
    return round(math.degrees(math.atan2(dx, dy)) % 360, 1)


def main(transcribed, fetched, out):
    tr = json.load(open(transcribed, encoding="utf-8"))
    cols = tr["columns"]
    booths, ways = {}, []
    for line in open(os.path.join(fetched, "mk-osm.geojsonseq"), encoding="utf-8"):
        f = json.loads(line.strip("\x1e"))
        p, g = f["properties"], f["geometry"]
        if p.get("barrier") == "toll_booth" and g["type"] == "Point" and p.get("name", "").startswith("Патарина "):
            booths.setdefault(p["name"][len("Патарина "):], []).append(tuple(g["coordinates"]))
        elif p.get("highway") and g["type"] == "LineString":
            ways.append((p.get("oneway") == "yes", [tuple(c) for c in g["coordinates"]]))
    points = []
    for st in tr["stations"]:
        bs = booths.get(st["station"])
        if not bs:
            sys.exit(f"{st['station']}: no toll booth named Патарина {st['station']} in OpenStreetMap")
        price = dict(zip(cols, st["eur"]))
        classes = [{"min_kg": 3501, "max_axles": 3, "rate": price["III"]}, {"min_kg": 3501, "min_axles": 4, "rate": price["IV"]}]
        headed, both = [], []
        for b in bs:
            h = None
            for oneway, cs in ways:
                if oneway and b in cs:
                    i = cs.index(b)
                    a, c = (cs[i - 1], cs[i]) if i > 0 else (cs[i], cs[i + 1])
                    h = heading(a, c)
                    break
            (both if h is None else headed).append((b, h))
        # Booths charging both ways make one point (the route passes them all).
        if both:
            headed.append(((sum(b[0] for b, _ in both) / len(both), sum(b[1] for b, _ in both) / len(both)), None))
        for b, h in headed:
            tp = {"name": st["station"], "lat": round(b[1], 6), "lon": round(b[0], 6)}
            if h is not None:
                tp["heading"] = h
            tp.update(rate=0, classes=classes)
            points.append(tp)
        print(st["station"], len(bs), "booths ->", [(p.get("heading")) for p in points[-len(headed):]])
    tb = {
        "country": "MK", "currency": "EUR", "valid_from": tr["valid_from"],
        "osm_extract": open(os.path.join(fetched, "mk-osm-timestamp.txt")).read().strip()[:10],
        "name": "North Macedonian road tolls (патарина)",
        "law": "Закон за јавните патишта, член 58; Одлука за висината и начинот на наплата на надоместокот за употреба на пат (Службен весник 118/2019), art. 5 as replaced by Службен весник 88/2025 (in force 1 May 2025): a toll per toll station, by category (trucks: III with two or three axles, IV with four or more). The price in euro paid in cash; electronic payment by card or tag earns a discount on top-ups. Stations placed with OpenStreetMap's toll booths, a booth on a one-way carriageway charging that direction.",
        "sources": [{"title": "Службен весник 88/2025: Одлука за изменување на Одлуката за патарина (PESR)", "url": tr["source"]["url"]},
                    {"title": "Службен весник 118/2019: Одлука за патарина (PESR)", "url": "https://roads.org.mk/wp-content/uploads/2023/01/odluka-za-patarina-2019-1.pdf"},
                    {"title": "OpenStreetMap (Geofabrik extract), toll booths", "url": "https://download.geofabrik.de/europe/macedonia.html"}],
        "vehicles": "Trucks over 3.5 t (categories III and IV)",
        "min_kg": 3501,
        "tolled_roads": "The motorway sections of the toll stations: " + "; ".join(f"{s['station']} ({s['section']})" for s in tr["stations"]) + ".",
        "point_match_km": 0.1,
        "toll_points": points,
        "rows": [],
    }
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"mk-{tr['valid_from']}.json")
    json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, len(points), "booths")


if __name__ == "__main__":
    main(*sys.argv[1:])
