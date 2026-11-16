"""Builds Spain's AP-71 León–Astorga (Aulesa, Abertis): a closed system
priced by entry and exit, with a day and a night tariff.

Usage: python3 es_aulesa.py fetched/ out-dir -> out-dir/es-aulesa-<year>-01-01.json

Prices: the operator's tariff sheet (fetch.py's es-aulesa-<year>.bbox.html,
pdftotext -bbox words): "Tarifa Diurna de 7 a 23 h." and "Tarifa Nocturna
de 23 a 7 h.", each with Ligeros, Pesados 1 (two or three axles) and
Pesados 2 (four axles or more) side by side, a row and a column per
station; euros including 21% IVA (divided out).

Stations: the sheet's map numbers the exits Villadangos 10, Hospital de
Órbigo 24 and San Justo de la Vega 35; each is placed at OpenStreetMap's
junctions of that number on the AP-71 (es-castellana-osm.json, which also
holds the AP-71). León is the AP-71's eastern end (where its ways end in
OpenStreetMap). Astorga, the western end, is priced as San Justo de la
Vega, two km before it, at the same prices.
"""
import json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tr_matrix  # noqa: E402

IVA = 1.21
STATIONS = ["León", "Villadangos", "Hospital de Órbigo", "San Justo de la Vega", "Astorga"]
EXITS = {"Villadangos": "10", "Hospital de Órbigo": "24", "San Justo de la Vega": "35"}
GROUPS = [{"name": "Pesados 1", "min_kg": 3501, "max_axles": 3}, {"name": "Pesados 2", "min_kg": 3501, "min_axles": 4}]
PRICE = re.compile(r"^\d+,\d\d$")


def block(ls, head):
    """{group: {(row, col): price}} for the tariff headed head."""
    start = next(i for i, (_, l) in enumerate(ls) if " ".join(w[4] for w in l[:2]) == head)
    rows, cells = [], {}
    for y, l in ls[start + 1:]:
        label = " ".join(w[4] for w in l if w[0] < 90)
        if label not in STATIONS:
            continue
        if label in rows:
            break
        r = len(rows)
        rows.append(label)
        for w in l:
            if 90 <= w[0] < 660 and PRICE.match(w[4]):
                i = round((w[0] - 97) / 38)
                if not 0 <= i < 15:
                    sys.exit(f"{head}: price at x {w[0]} outside the columns")
                cells.setdefault(["Ligeros", "Pesados 1", "Pesados 2"][i // 5], {})[(r, i % 5)] = float(w[4].replace(",", "."))
        if len(rows) == len(STATIONS):
            break
    if rows != STATIONS:
        sys.exit(f"{head}: rows {rows}")
    return cells


def main(fetched, out):
    d = json.load(open(os.path.join(fetched, "es-castellana-osm.json")))
    stamp = d.get("osm3s", {}).get("timestamp_osm_base", "")[:10]
    on, ends = {}, []
    for e in d["elements"]:
        if e["type"] == "way" and e["tags"].get("ref") == "AP-71":
            for p in e["geometry"]:
                on[(round(p["lat"], 7), round(p["lon"], 7))] = True
            ends += [(e["geometry"][0]["lon"], e["geometry"][0]["lat"]), (e["geometry"][-1]["lon"], e["geometry"][-1]["lat"])]
    if not ends:
        sys.exit("AP-71: no ways in OpenStreetMap")
    east = max(ends)
    stations = [{"name": "León", "points": [{"name": "end of the AP-71", "lat": round(east[1], 6), "lon": round(east[0], 6)}]}]
    for s, ref in EXITS.items():
        pts = [(round(e["lat"], 6), round(e["lon"], 6)) for e in d["elements"] if e["type"] == "node" and e.get("tags", {}).get("ref") == ref
               and (round(e["lat"], 7), round(e["lon"], 7)) in on]
        if not pts:
            sys.exit(f"AP-71: no junction {ref} ({s}) in OpenStreetMap")
        stations.append({"name": s, "points": [{"name": "junction", "lat": a, "lon": b} for a, b in pts]})
    placed = {s["name"] for s in stations}
    urls = {s["id"]: s["url"] for s in json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources.json")))["sources"]}
    for year in ("2025", "2026"):
        path = os.path.join(fetched, f"es-aulesa-{year}.bbox.html")
        if not os.path.exists(path):
            print(f"Aulesa {year}: tariff sheet not fetched")
            continue
        ws = [w for page in tr_matrix.words(path) for w in page]
        txt = " ".join(w[4] for w in ws)
        if f"en vigor desde el 1 de enero de {year} (21% IVA incluido)" not in txt or "Tarifa Diurna de 7 a 23 h." not in txt or "Tarifa Nocturna de 23 a 7 h." not in txt:
            sys.exit(f"Aulesa {year}: the sheet's heading or hours changed")
        maps = {w[4] for w in ws if w[1] < 600}
        if not all(r in maps for r in EXITS.values()):
            sys.exit(f"Aulesa {year}: exit numbers not on the sheet's map")
        ls = tr_matrix.lines(ws)
        day, night = block(ls, "Tarifa Diurna"), block(ls, "Tarifa Nocturna")
        prices, nprices = {}, {}
        for src, dst in ((day, prices), (night, nprices)):
            for g in ("Pesados 1", "Pesados 2"):
                for (r, c), v in src[g].items():
                    a, b = STATIONS[r], STATIONS[c]
                    if a in placed and b in placed and a != b:
                        dst.setdefault(f"{a}|{b}", {})[g] = round(v / IVA, 4)
        tb = {"country": "ES", "currency": "EUR", "valid_from": f"{year}-01-01", "valid_to": f"{year}-12-31", "crossings": True, "osm_extract": stamp,
              "name": "AP-71 León–Astorga (Aulesa)",
              "law": f"The concessionaire's tariffs in force from 1 January {year}, as its tariff sheet gives them by entry and exit: Pesados 1 (two or three axles) and Pesados 2 (four axles or more), the day tariff (07:00 to 23:00) and the night tariff (23:00 to 07:00, by the time the trip enters), excluding 21% IVA. Stations placed at OpenStreetMap's junctions of the exit numbers the sheet's map gives them, and León at the motorway's eastern end; Astorga is priced as San Justo de la Vega (same prices).",
              "sources": [{"title": f"Abertis Autopistas: AP-71 León–Astorga tariffs {year}", "url": urls[f"es-aulesa-{year}"]},
                          {"title": "OpenStreetMap (Overpass API), motorway junctions", "url": "https://www.openstreetmap.org/copyright"}],
              "vehicles": "Trucks over 3.5 t (Pesados 1 and 2)", "min_kg": 3501,
              "tolled_roads": "AP-71 León–Astorga.",
              "closed_systems": [{"name": "AP-71", "law": f"Aulesa tariffs {year}, including 21% IVA, here excluding it; night tariff 23:00 to 07:00",
                                  "directed": True, "groups": GROUPS, "stations": stations, "prices": prices,
                                  "night_hours": ["23:00", "06:59"], "night_prices": nprices}],
              "rows": []}
        os.makedirs(out, exist_ok=True)
        p = os.path.join(out, f"es-aulesa-{year}-01-01.json")
        json.dump(tb, open(p, "w"), ensure_ascii=False, indent=1)
        print(p, len(stations), "stations,", len(prices), "prices")


if __name__ == "__main__":
    main(*sys.argv[1:])
