"""Builds the Montenegrin toll table from Monteput's price pages (fetch.py's
me-autoput.html: the motorway Bar–Boljare, section Smokovac–Mateševo, and
me-sozina.html: the Sozina tunnel) and the toll booths in OpenStreetMap
(the workflow's me-osm.geojsonseq, from Geofabrik's Montenegro extract).

Usage: python3 me.py fetched/ out-dir -> out-dir/me-<date>.json

The motorway is a closed system: the page's toll calculator holds the
price for each entry–exit pair ("var items = [{ from, to, tip1 .. tip5
}]"); TIP 4 is a vehicle over 3,500 kg with two or three axles, TIP 5 one
with four or more (the page's category list). The Sozina tunnel has one
price per category ("Četvrta kategorija ... 10€", "Peta kategorija ...
18€"), at its toll station, either direction. Prices as Monteput
publishes them (the pages don't say whether VAT is in them).

Stations: the OSM toll booths named "Naplatna stanica <name>", else the
toll booths within 1 km of the motorway junction of that name.

When Monteput answers the workflow with a bot check instead of the page,
the copy read in Chrome is used (browser/me-autoput.txt: the calculator's
pairs and the category lines; browser/me-sozina.txt), and the sources say
so.
"""
import html, json, math, os, re, sys

BROWSER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "browser")
ITEMS = r"\{\s*from:\s*'(\w+)',\s*to:\s*'(\w+)',\s*tip1:\s*([\d.]+),\s*tip2:\s*([\d.]+),\s*tip3:\s*([\d.]+),\s*tip4:\s*([\d.]+),\s*tip5:\s*([\d.]+)\s*\}"
NAMES = {"smokovac": "Smokovac", "pelevbrijeg": "Pelev Brijeg", "verusa": "Veruša", "matesevo": "Mateševo"}


def km(a, b):
    return math.hypot((a[0] - b[0]) * 111.2 * math.cos(math.radians(a[1])), (a[1] - b[1]) * 111.2)


def text(path):
    t = open(path, encoding="utf-8").read()
    t = re.sub(r"<script.*?</script>", "", t, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t)))


def page(fetched, sid, ok):
    """fetch.py's <sid>.html when it is the page (ok), else the copy read in
    Chrome (browser/<sid>.txt, without its "# " lines): its text, raw, and
    which it is."""
    p = os.path.join(fetched, f"{sid}.html")
    if os.path.exists(p) and ok(open(p, encoding="utf-8").read()):
        return text(p), open(p, encoding="utf-8").read(), "fetched"
    b = os.path.join(BROWSER, f"{sid}.txt")
    if not os.path.exists(b):
        sys.exit(f"{sid}: not fetched (a bot check?) and no browser/{sid}.txt")
    print(f"{sid}: the copy read in Chrome")
    raw = "".join(l for l in open(b, encoding="utf-8") if not l.startswith("# "))
    return re.sub(r"\s+", " ", raw), raw, "browser"


def main(fetched, out):
    cats, raw, autoput = page(fetched, "me-autoput", lambda t: len(re.findall(ITEMS, t)) == 12)
    items = re.findall(ITEMS, raw)
    if len(items) != 12:
        sys.exit(f"{len(items)} entry-exit pairs, want 12")
    prices = {f"{NAMES[a]}|{NAMES[b]}": {"IV": float(t4), "V": float(t5)} for a, b, _, _, _, t4, t5 in items}
    assert "dvije ili tri osovine" in cats and "četiri ili više osovina" in cats
    soz, _, sozina = page(fetched, "me-sozina", lambda t: "Četvrta kategorija" in t and "Peta kategorija" in t)
    s4 = float(re.search(r"Četvrta kategorija Cijena .*? prelazi 3\.500 ?kg ([\d.]+)€", soz).group(1))
    s5 = float(re.search(r"Peta kategorija Cijena .*? prelazi 3500kg\. ([\d.]+)€", soz).group(1))

    booths, junctions = [], {}
    for line in open(os.path.join(fetched, "me-osm.geojsonseq"), encoding="utf-8"):
        f = json.loads(line.strip("\x1e"))
        p, g = f["properties"], f["geometry"]
        if g["type"] != "Point":
            continue
        if p.get("barrier") == "toll_booth":
            booths.append((tuple(g["coordinates"]), p.get("name", "")))
        elif p.get("highway") == "motorway_junction" and p.get("name"):
            junctions.setdefault(p["name"], []).append(g["coordinates"])

    def place(name):
        named = [c for c, n in booths if n == f"Naplatna stanica {name}"]
        if named:
            return named
        near = [c for c, n in booths if not n and any(km(c, j) < 1 for j in junctions.get(name, []))]
        if not near:
            sys.exit(f"{name}: no toll booth in OpenStreetMap")
        return near

    stations = [{"name": n, "points": [{"name": "booth", "lat": round(c[1], 6), "lon": round(c[0], 6)} for c in place(n)]} for n in NAMES.values()]
    soz_pts = place("Sozina")
    lon, lat = sum(c[0] for c in soz_pts) / len(soz_pts), sum(c[1] for c in soz_pts) / len(soz_pts)
    tb = {
        "country": "ME", "currency": "EUR", "valid_from": "2022-07-21",
        "osm_extract": open(os.path.join(fetched, "me-osm-timestamp.txt")).read().strip()[:10],
        "name": "Montenegrin road tolls (putarina): motorway Smokovac–Mateševo and the Sozina tunnel",
        "law": "Zakon o putevima; prices published by Monteput d.o.o.: on the motorway Bar–Boljare (Smokovac–Mateševo), from entry to exit station, category IV (over 3,500 kg, two or three axles) and V (four or more axles); in the Sozina tunnel per passage. The pages carry no date: the table runs from the start of toll collection on the motorway (21 July 2022). Stations placed with OpenStreetMap's toll booths.",
        "sources": [{"title": "Monteput: Cjenovnik Autoput Bar-Boljare" + (" (read in Chrome: tools/tables/browser/me-autoput.txt)" if autoput == "browser" else ""), "url": "https://monteput.me/cjenovnik-autoput-bar-boljare/"},
                    {"title": "Monteput: Cjenovnik Tunel Sozina" + (" (read in Chrome: tools/tables/browser/me-sozina.txt)" if sozina == "browser" else ""), "url": "https://monteput.me/cjenovnik-tunel-sozina/"},
                    {"title": "OpenStreetMap (Geofabrik extract), toll booths", "url": "https://download.geofabrik.de/europe/montenegro.html"}],
        "vehicles": "Vehicles over 3,500 kg (categories IV and V)",
        "min_kg": 3501,
        "tolled_roads": "The motorway Smokovac–Mateševo (stations Smokovac, Pelev Brijeg, Veruša, Mateševo) and the Sozina tunnel.",
        "closed_systems": [{
            "name": "Autoput Bar–Boljare (Smokovac–Mateševo)",
            "law": "Monteput price list: from entry to exit station, categories IV and V.",
            "groups": [{"name": "IV", "min_kg": 3501, "max_axles": 3}, {"name": "V", "min_kg": 3501, "min_axles": 4}],
            "stations": stations,
            "prices": prices,
        }],
        "point_match_km": 0.15,
        "toll_points": [{"name": "Tunel Sozina", "lat": round(lat, 6), "lon": round(lon, 6), "rate": 0,
                         "classes": [{"min_kg": 3501, "max_axles": 3, "rate": s4}, {"min_kg": 3501, "min_axles": 4, "rate": s5}]}],
        "rows": [],
    }
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, "me-2022-07-21.json")
    json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, len(prices), "pairs; Sozina", s4, s5, "; stations", {s["name"]: len(s["points"]) for s in stations})


if __name__ == "__main__":
    main(*sys.argv[1:])
