"""Builds the A2 Świecko-Konin concession toll (pl-a2-<date>.json) from
Autostrada Wielkopolska's price list: its page (pl-a2-tolls.html: the date
the price list holds from and the links to the tables) and the tables of
categories 2, 3 and 4 (pl-a2-cat2.txt, pl-a2-cat3.txt, pl-a2-cat4.txt,
pdftotext -layout of the PDFs): the price from each of the sixteen
stations to each other, standard (manual) prices.

Categories: 2, two axles (at least one with twin wheels) or two axles with
trailers; 3, three axles or two axles (twin wheels) with trailers; 4, more
than three axles or three axles with trailers. The table counts the motor
vehicle's axles (motor_axles); a semi-trailer counts as a trailer.

The stations are placed at the motorway junctions of their names on the
A2 and at their toll booths in OpenStreetMap (pl-concessions-osm.json);
Świecko is the toll plaza by the German border.

Usage: python3 pl_a2.py <fetched dir> <out dir>
"""
import html
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pl_osm  # noqa: E402

URL = "https://www.autostrada-a2.pl/oplaty/"
# A price list's tables, by its first day: uploads/<year>/<month>/AW-tabele-oplat-<month>.<year>_0<category>.pdf
PDF = "https://www.autostrada-a2.pl/wp-content/uploads/{y}/{m}/AW-tabele-oplat-{m}.{y}_0{n}.pdf"
STATIONS = ["Konin Modła", "Sługocin", "Słupca", "Września", "Poznań Wschód", "Poznań Krzesiny", "Poznań Luboń", "Poznań Komorniki",
            "Poznań Zachód", "Buk", "Nowy Tomyśl", "Trzciel", "Jordanowo", "Torzym", "Rzepin", "Świecko"]
# OpenStreetMap's names where they differ: the junction names without the town, the plazas' booths.
OSM = {"Konin Modła": ["Modła"], "Świecko": ["PPO Świecko", "Świecko"]}
BOX = (52.1, 14.5, 52.55, 18.4)  # south, west, north, east
GROUPS = [  # (group, category, bounds on the motor vehicle's axles and the trailer)
    ("4", "4", {"min_axles": 4}),
    ("4 (3 axles with trailer)", "4", {"min_axles": 3, "max_axles": 3, "trailer": True}),
    ("3", "3", {"min_axles": 3, "max_axles": 3, "trailer": False}),
    ("3 (2 axles with trailer)", "3", {"max_axles": 2, "trailer": True}),
    ("2", "2", {"max_axles": 2, "trailer": False}),
]


def matrix(path):
    """The sixteen rows of a category's table: on each, sixteen prices with
    a dash where the row meets its own column."""
    rows = []
    for line in open(path, encoding="utf-8", errors="replace"):
        toks = re.findall(r"(?<![\d,.])(\d+(?:[,.]\d+)?|[–—-])(?![\d,.])", line)
        if len(toks) == 16 and sum(t in "–—-" for t in toks) == 1:
            rows.append(toks)
    if len(rows) != 16 or any(r[i] not in "–—-" for i, r in enumerate(rows)):
        sys.exit(f"A2 Świecko-Konin: {path} has no 16 x 16 table ({len(rows)} rows)")
    return [[None if t in "–—-" else float(t.replace(",", ".")) for t in r] for r in rows]


def main(fetched, out):
    try:
        page = open(os.path.join(fetched, "pl-a2-tolls.html"), encoding="utf-8", errors="replace").read()
        d = json.load(open(os.path.join(fetched, "pl-concessions-osm.json")))
    except (OSError, ValueError):
        print("A2 Świecko-Konin: price list page or OpenStreetMap not fetched; not built")
        return
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page)))
    head = re.search(r"cennik obowiązuje od (\d\d)\.(\d\d)\.(\d{4}) roku", text)
    cats = re.search(r"Pojazdy samochodowe o dwóch osiach, z których co najmniej jedna wyposażona jest w koła bliźniacze oraz pojazdy samochodowe o dwóch osiach z przyczepami .{0,60}?"
                     r"Pojazdy samochodowe o trzech osiach oraz pojazdy samochodowe o dwóch osiach, z których co najmniej jedna wyposażona jest w koła bliźniacze z przyczepami .{0,60}?"
                     r"Pojazdy samochodowe o więcej niż trzech osiach oraz pojazdy samochodowe o trzech osiach z przyczepami", text)
    if not (head and cats):
        sys.exit("A2 Świecko-Konin: the price list's date or categories not read")
    start = f"{head.group(3)}-{head.group(2)}-{head.group(1)}"
    pdf = lambda n: PDF.format(y=head.group(3), m=head.group(2), n=n)
    tables = {}
    for n in ("2", "3", "4"):
        sub = re.search(r'href="(/oplaty/cennik-kategoria-' + n + r'/|https://www\.autostrada-a2\.pl/oplaty/cennik-kategoria-' + n + r'/)"', page)
        if not sub:
            sys.exit(f"A2 Świecko-Konin: no link to category {n}'s price list")
        tables[n] = matrix(os.path.join(fetched, f"pl-a2-cat{n}.txt"))
    # The category pages' PDFs must be the ones fetched (a new price list has new files).
    for n in ("2", "3", "4"):
        p = os.path.join(fetched, f"pl-a2-cat{n}-page.html")
        if os.path.exists(p) and os.path.basename(pdf(n)) not in open(p, encoding="utf-8", errors="replace").read():
            sys.exit(f"A2 Świecko-Konin: category {n}'s page links to another PDF than {pdf(n)}")
    prices = {}
    for i, a in enumerate(STATIONS):
        for j, b in enumerate(STATIONS):
            if i == j:
                continue
            v = {n: tables[n][i][j] for n in tables}
            w = {n: tables[n][j][i] for n in tables}
            if v != w:
                sys.exit(f"A2 Świecko-Konin: {a}-{b} differs by direction")
            prices[f"{a}|{b}"] = v
    # A station free to and from a neighbour, with the same price as it to
    # every other station (the Poznań ring's junctions, Świecko by Rzepin),
    # may be left out where OpenStreetMap has no point of it: a trip through
    # it passes the neighbour, at the same price.
    twins = {a for a in STATIONS for b in STATIONS if a != b and all(tables[n][STATIONS.index(a)][STATIONS.index(b)] == 0 for n in tables)
             and all(tables[n][STATIONS.index(a)][k] == tables[n][STATIONS.index(b)][k] for n in tables for k in range(16) if STATIONS[k] not in (a, b))}
    stations = pl_osm.place("A2 Świecko-Konin", d, BOX, STATIONS, OSM, optional=twins)
    placed = {s["name"] for s in stations}
    prices = {k: v for k, v in prices.items() if set(k.split("|")) <= placed}
    groups = [{"name": g, "min_kg": 3501} | b for g, _, b in GROUPS]
    prices = {k: {g: v[cat] for g, cat, _ in GROUPS} for k, v in prices.items()}
    full = {n: tables[n][0][15] for n in tables}
    t = {"country": "PL", "currency": "PLN", "valid_from": start, "crossings": True, "motor_axles": True,
         "osm_extract": d.get("osm3s", {}).get("timestamp_osm_base", "")[:10],
         "name": "A2 Świecko-Konin (Autostrada Wielkopolska)",
         "law": (f"Autostrada Wielkopolska's price list (cennik przejazdów) from {start} for the A2 Świecko-Nowy Tomyśl-Konin (Autostrada Wielkopolska II and Autostrada Wielkopolska), "
                 f"the price from station to station paid at the plazas: category 2 (two axles with twin wheels, or two axles with trailers) PLN {full['2']:g} Konin Modła-Świecko, "
                 f"category 3 (three axles, or two axles with twin wheels with trailers) PLN {full['3']:g}, category 4 (more than three axles, or three axles with trailers) PLN {full['4']:g}. "
                 "A semi-trailer counts as a trailer (Prawo o ruchu drogowym art. 2 pkt 44). The category goes by the motor vehicle's own axles (give truck.motor_axles; without it all the "
                 "truck's axles count) and whether it tows a trailer. The Poznań ring between Poznań Zachód and Poznań Wschód is free. The e-TOLL doesn't charge this stretch. "
                 "The stations are placed at the motorway junctions of their names and their toll booths in OpenStreetMap. Videotolling prices (Poznań-Konin) aren't modelled."),
         "sources": [{"title": "Autostrada Wielkopolska: Cennik przejazdów", "url": URL}]
         + [{"title": f"Autostrada Wielkopolska: tabela opłat, kategoria {n}", "url": pdf(n)} for n in ("2", "3", "4")]
         + [{"title": "OpenStreetMap (Overpass API): A2 junctions and toll booths", "url": "https://www.openstreetmap.org/"}],
         "vehicles": "Vehicles over 3.5 t (categories 2-4)", "min_kg": 3501,
         "tolled_roads": "A2 Świecko (German border) - Konin (Modła), 255 km; free between Poznań Zachód and Poznań Wschód.",
         "closed_systems": [{"name": "A2 Świecko-Konin (Autostrada Wielkopolska)", "law": "Autostrada Wielkopolska's tabele opłat, categories 2-4, PLN",
                             "groups": groups, "stations": stations, "prices": prices}],
         "rows": []}
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"pl-a2-{start}.json")
    json.dump(t, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, len(stations), "stations", len(prices), "prices", full)


if __name__ == "__main__":
    main(*sys.argv[1:])
