"""Builds the A1 Rusocin-Toruń concession toll (pl-a1-<date>.json) from
AmberOne's (Gdańsk Transport Company's) toll page (pl-a1-tolls.html): a
closed system of twelve toll stations, priced from the station of entry to
the station of exit, the same for categories 2, 3 and 4 (vehicles with
twin wheels: two, three, or more than three axles), VAT included.

The stations are placed at the motorway junctions of their names on the A1
and at their toll booths in OpenStreetMap (pl-concessions-osm.json).

Usage: python3 pl_a1.py <fetched dir> <out dir>
"""
import html
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pl_osm  # noqa: E402

MONTHS = {m: i + 1 for i, m in enumerate(("stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca", "sierpnia",
                                          "września", "października", "listopada", "grudnia"))}
URL = "https://a1.com.pl/kalkulator-oplat-i-planowanie-podrozy/"
STATIONS = ["Rusocin", "Stanisławie", "Swarożyn", "Pelplin", "Kopytkowo", "Warlubie", "Nowe Marzy", "Grudziądz", "Lisewo", "Turzno",
            "Lubicz", "Nowa Wieś"]
BOX = (52.9, 18.3, 54.4, 19.0)  # south, west, north, east


def cells(row):
    return [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", c))).strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, flags=re.S)]


def main(fetched, out):
    try:
        page = open(os.path.join(fetched, "pl-a1-tolls.html"), encoding="utf-8", errors="replace").read()
        d = json.load(open(os.path.join(fetched, "pl-concessions-osm.json")))
    except (OSError, ValueError):
        print("A1 Rusocin-Toruń: toll page or OpenStreetMap not fetched; not built")
        return
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page)))
    head = re.search(r"Stawki opłat za przejazd zawierające podatek VAT \(obowiązujące od dnia (\d+) (\w+) (\d{4}) r\.\)", text)
    sys_ = re.search(r"Pobór opłat odbywa się w systemie zamkniętym\.", text)
    cats = re.search(r"2 Pojazdy o dwóch osiach, z których przynajmniej na jednej zamocowano podwójne koła .{0,120}?"
                     r"3 Pojazdy o trzech osiach, z których przynajmniej na jednej zamocowano podwójne koła "
                     r"4 Pojazdy o więcej niż trzech osiach, z których przynajmniej na jednej zamocowano podwójne koła", text)
    # The price tables, in the page's order: category 1, categories 2-4, category 5.
    at = page.find("KATEGORIE 2-4")
    tb = re.search(r"<table.*?</table>", page[at:], flags=re.S) if at >= 0 else None
    if not (head and sys_ and cats and tb) or head.group(2) not in MONTHS:
        sys.exit("A1 Rusocin-Toruń: toll page not read (the date, the closed system, the categories or the table for categories 2-4)")
    start = f"{head.group(3)}-{MONTHS[head.group(2)]:02d}-{int(head.group(1)):02d}"
    rows = [cells(r) for r in re.findall(r"<tr[^>]*>(.*?)</tr>", tb.group(0), flags=re.S)]
    if [c for c in rows[0] if c] != STATIONS or [r[0] for r in rows[1:]] != STATIONS:
        sys.exit(f"A1 Rusocin-Toruń: the table's stations are not {STATIONS}: {rows[0]}")
    prices = {}
    for r in rows[1:]:
        for b, v in zip(STATIONS, r[1:]):
            if b == r[0]:
                continue
            prices[f"{r[0]}|{b}"] = {"2-4": float(v.replace(",", "."))}
    for k, v in prices.items():
        a, b = k.split("|")
        if prices[f"{b}|{a}"] != v:
            sys.exit(f"A1 Rusocin-Toruń: {a}-{b} differs by direction")
    stations = pl_osm.place("A1 Rusocin-Toruń", d, BOX, STATIONS)
    full = prices["Rusocin|Nowa Wieś"]["2-4"]
    t = {"country": "PL", "currency": "PLN", "valid_from": start, "crossings": True, "osm_extract": d.get("osm3s", {}).get("timestamp_osm_base", "")[:10],
         "name": "A1 Rusocin-Toruń (AmberOne, Gdańsk Transport Company)",
         "law": (f"AmberOne's tolls including VAT, in force from {start} (the per-km rates set by the Minister of Infrastructure): a closed system of twelve toll stations, "
                 f"priced from the station of entry to that of exit, the same for categories 2, 3 and 4 (two, three, or more than three axles, at least one with twin wheels): "
                 f"PLN {full:g} Rusocin-Nowa Wieś. The e-TOLL doesn't charge this stretch. The stations are placed at the motorway junctions of their names and their toll booths in OpenStreetMap. "
                 "AmberGO automatic payment changes nothing in the price."),
         "sources": [{"title": "AmberOne Autostrada A1: Kalkulator opłat i planowanie podróży (tabela opłat, system poboru, klasyfikacja pojazdów)", "url": URL},
                     {"title": "OpenStreetMap (Overpass API): A1 junctions and toll booths", "url": "https://www.openstreetmap.org/"}],
         "vehicles": "Vehicles over 3.5 t (categories 2-4)", "min_kg": 3501,
         "tolled_roads": "A1 Rusocin (Gdańsk) - Nowa Wieś (Toruń), 152 km.",
         "closed_systems": [{"name": "A1 Rusocin-Toruń (AmberOne)", "law": "AmberOne's tabela opłat, categories 2-4, PLN including VAT",
                             "groups": [{"name": "2-4", "min_kg": 3501}], "stations": stations, "prices": prices}],
         "rows": []}
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"pl-a1-{start}.json")
    json.dump(t, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, len(stations), "stations", len(prices), "prices", full)


if __name__ == "__main__":
    main(*sys.argv[1:])
