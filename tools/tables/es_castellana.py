"""Builds Spain's AP-6 Villalba–Adanero, AP-51 Villacastín–Ávila and AP-61
San Rafael–Segovia (Castellana de Autopistas and Iberpistas, Abertis):
one closed system, priced by entry and exit.

Usage: python3 es_castellana.py fetched/ out-dir -> out-dir/es-castellana-<year>-01-01.json

Prices: the operator's tariff sheet for the year (fetch.py's
es-castellana-<year>.bbox.html, pdftotext -bbox words): the Pesados 1
(two or three axles) and Pesados 2 (four axles or more) matrices, one
row and one column per station in the same order, "Tarifa Única" (the
peak and off-peak tariffs are for light vehicles on the AP-51 and AP-61
only), euros including 21% IVA (divided out). A "*" is no trip.

Stations: the sheet's map numbers each station's exit (Villalba 42, El
Escorial/Guadarrama 47, N VI/Alto del León 52, San Rafael 60 and 61,
Villacastín 81 and 82, Sanchidrián 102, Adanero 108, Otero de
Herreros 68, Ortigosa del Monte 74, Hontoria 86, Segovia 88AB,
Vicolozano 104, Ávila 105); each is placed at OpenStreetMap's motorway
junctions of that number on the AP-6, AP-51 or AP-61 themselves
(es-castellana-osm.json). Ávila (105, the AP-51's end) has no junction
there: a trip from or to it is priced from Vicolozano, whose prices are
the same.
"""
import json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tr_matrix  # noqa: E402

IVA = 1.21
STATIONS = ["Villalba", "El Escorial/Guadarrama", "N VI / Alto del León", "San Rafael", "Villacastín", "Sanchidrián", "Adanero",
            "Otero de Herreros", "Ortigosa del Monte", "Hontoria", "Segovia", "Vicolozano", "Ávila"]
EXITS = {"Villalba": [("AP-6", "42")], "El Escorial/Guadarrama": [("AP-6", "47")], "N VI / Alto del León": [("AP-6", "52")],
         "San Rafael": [("AP-6", "60"), ("AP-6", "61")], "Villacastín": [("AP-6", "81"), ("AP-51", "82")],
         "Sanchidrián": [("AP-6", "102")], "Adanero": [("AP-6", "108")],
         "Otero de Herreros": [("AP-61", "68")], "Ortigosa del Monte": [("AP-61", "74")], "Hontoria": [("AP-61", "86")],
         "Segovia": [("AP-61", "88AB")], "Vicolozano": [("AP-51", "104")], "Ávila": []}
GROUPS = [{"name": "Pesados 1", "min_kg": 3501, "max_axles": 3}, {"name": "Pesados 2", "min_kg": 3501, "min_axles": 4}]
PRICE = re.compile(r"^\d+,\d\d$")


def block(ls, head):
    """The matrix under the line starting with head: {(row, col): price}."""
    start = next(i for i, (_, l) in enumerate(ls) if " ".join(w[4] for w in l).startswith(head))
    rows, cells = [], {}
    first = None
    for y, l in ls[start + 1:]:
        label = " ".join(w[4] for w in l if w[0] < 100)
        vals = [w for w in l if 100 <= w[0] < 640]
        if label not in STATIONS:
            if rows and label.startswith(("PESADOS", "LIGEROS")):
                break
            continue
        if label in rows:
            break
        r = len(rows)
        rows.append(label)
        for w in vals:
            if PRICE.match(w[4]):
                if first is None and r == 0:
                    first = w[0]
                c = round((w[0] - 117) / 40)
                if not 0 <= c < len(STATIONS):
                    sys.exit(f"{head}: price at x {w[0]} outside the columns")
                cells[(r, c)] = float(w[4].replace(",", "."))
        if len(rows) == len(STATIONS):
            break
    if rows != STATIONS:
        sys.exit(f"{head}: rows {rows}")
    return cells


def junctions(path):
    d = json.load(open(path))
    on = {}
    for e in d["elements"]:
        if e["type"] == "way":
            for p in e["geometry"]:
                on.setdefault((round(p["lat"], 7), round(p["lon"], 7)), set()).add(e["tags"].get("ref"))
    out = {}
    for e in d["elements"]:
        if e["type"] == "node" and e.get("tags", {}).get("ref"):
            for road in on.get((round(e["lat"], 7), round(e["lon"], 7)), ()):
                out.setdefault((road, e["tags"]["ref"]), []).append((round(e["lat"], 6), round(e["lon"], 6)))
    return out, d.get("osm3s", {}).get("timestamp_osm_base", "")[:10]


def main(fetched, out):
    jn, stamp = junctions(os.path.join(fetched, "es-castellana-osm.json"))
    stations = []
    for s in STATIONS:
        pts = [p for road, ref in EXITS[s] for p in jn.get((road, ref), [])]
        if EXITS[s] and not pts:
            sys.exit(f"{s}: no junction {EXITS[s]} in OpenStreetMap")
        if pts:
            stations.append({"name": s, "points": [{"name": "junction", "lat": a, "lon": b} for a, b in pts]})
    placed = {s["name"] for s in stations}
    urls = {s["id"]: s["url"] for s in json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources.json")))["sources"]}
    for year in ("2025", "2026"):
        path = os.path.join(fetched, f"es-castellana-{year}.bbox.html")
        if not os.path.exists(path):
            print(f"Castellana {year}: tariff sheet not fetched")
            continue
        ws = [w for page in tr_matrix.words(path) for w in page]
        txt = " ".join(w[4] for w in ws)
        if f"en vigor desde el 1 de enero de {year} (21% IVA incluido)" not in txt:
            sys.exit(f"Castellana {year}: the sheet no longer says it's in force from 1 January {year}, 21% IVA included")
        maps = {w[4] for w in ws if w[1] < 650}
        for s, ex in EXITS.items():
            for _, ref in ex:
                if ref.rstrip("AB") not in maps:
                    sys.exit(f"Castellana {year}: exit {ref} ({s}) not on the sheet's map")
        ls = tr_matrix.lines(ws)
        prices = {}
        for g in ("Pesados 1", "Pesados 2"):
            for (r, c), v in block(ls, g.upper()).items():
                a, b = STATIONS[r], STATIONS[c]
                if a in placed and b in placed and a != b:
                    prices.setdefault(f"{a}|{b}", {})[g] = round(v / IVA, 4)
        tb = {"country": "ES", "currency": "EUR", "valid_from": f"{year}-01-01", "valid_to": f"{year}-12-31", "crossings": True, "osm_extract": stamp,
              "name": "AP-6, AP-51 and AP-61 (Castellana de Autopistas, Iberpistas)",
              "law": f"The concessionaire's tariffs in force from 1 January {year}, as its tariff sheet gives them by entry and exit: Pesados 1 (two or three axles) and Pesados 2 (four axles or more), the single tariff, excluding 21% IVA. Stations placed at OpenStreetMap's motorway junctions of the exit numbers the sheet's map gives them; Ávila (the AP-51's end) is priced as Vicolozano, at the same prices.",
              "sources": [{"title": f"Abertis Autopistas: AP-6, AP-51, AP-61 tariffs {year}", "url": urls[f"es-castellana-{year}"]},
                          {"title": "OpenStreetMap (Overpass API), motorway junctions", "url": "https://www.openstreetmap.org/copyright"}],
              "vehicles": "Trucks over 3.5 t (Pesados 1 and 2)", "min_kg": 3501,
              "tolled_roads": "AP-6 Villalba–Adanero, AP-51 Villacastín–Ávila, AP-61 San Rafael–Segovia.",
              "closed_systems": [{"name": "AP-6/AP-51/AP-61", "law": f"Castellana de Autopistas / Iberpistas tariffs {year}, including 21% IVA, here excluding it",
                                  "directed": True, "groups": GROUPS, "stations": stations, "prices": prices}],
              "rows": []}
        os.makedirs(out, exist_ok=True)
        p = os.path.join(out, f"es-castellana-{year}-01-01.json")
        json.dump(tb, open(p, "w"), ensure_ascii=False, indent=1)
        print(p, len(stations), "stations,", len(prices), "prices")


if __name__ == "__main__":
    main(*sys.argv[1:])
