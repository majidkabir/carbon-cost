"""Builds Spanish toll motorways from the Ministry of Transport's tables of
the tolls in force (peajes vigentes), one closed system per motorway.

Usage: python3 es_ministry.py fetched/ out-dir -> out-dir/es-<motorway>-<date>.json

Prices: the Ministry's PDF for the motorway and year (fetch.py's
es-min-<motorway>-<year>.txt, pdftotext -layout): its first table,
"RECORRIDOS DIRECTOS E INVERSOS", one line per pair of stations with the
Ligeros, Pesados 1 and Pesados 2 tolls in euros, the same both ways.
The tolls are what's charged (with the heavy-vehicle reductions the
table states, if any), 21% IVA included; the tables here exclude it.
Pesados 1: two or three axles (or two with a one-axle trailer); Pesados
2: four axles or more.

Stations: placed at the concessionaire's own map (its interactive map's
Google My Maps, as KML: es-map-<operator>.html), at the toll plazas and
accesses MOTORWAYS (below) maps each of the table's stations to.
"""
import html, json, os, re, sys, unicodedata
import xml.etree.ElementTree as ET

IVA = 1.21
GROUPS = [{"name": "Pesados 1", "min_kg": 3501, "max_axles": 3}, {"name": "Pesados 2", "min_kg": 3501, "min_axles": 4}]
MOTORWAYS = {
    # AP-66: the table's Oblanca is the Villablino–Barrios de Luna toll (the
    # exit by the Oblanca tunnel); La Magdalena has a mainline and a ramp toll.
    "ap66": {"name": "AP-66 Campomanes–León (Aucalsa)", "map": "es-map-aucalsa",
             "tolled": "AP-66 Campomanes–León.",
             "stations": {"CAMPOMANES": ["ACCESO CAMPOMANES"], "OBLANCA": ["PEAJE VILLABLINO - BARRIOS DE LUNA"],
                          "LA MAGDALENA": ["PEAJE TRONCAL DE LA MAGDALENA", "PEAJE RAMAL DE LA MAGDALENA"],
                          "LEON": ["ACCESO LEÓN - ASTORGA"]}},
}


def norm(s):
    s = unicodedata.normalize("NFD", s.upper())
    return re.sub(r"\s+", " ", "".join(c for c in s if unicodedata.category(c) != "Mn")).strip()


def placemarks(path):
    """{name: (lat, lon)} of the map's points."""
    t = open(path, encoding="utf-8", errors="replace").read()
    t = re.sub(r'\sxmlns(:\w+)?="[^"]*"', "", t, count=0)
    root = ET.fromstring(t)
    out = {}
    for p in root.iter("Placemark"):
        n, c = p.find("name"), p.find("Point/coordinates")
        if n is not None and c is not None:
            lon, lat = map(float, c.text.strip().split(",")[:2])
            out[norm(n.text)] = (round(lat, 6), round(lon, 6))
    return out


PAIR = re.compile(r"^\s*(\S.*?)\s*-\s*(\S.*?)\s+(\d+,\d\d)\s+(\d+,\d\d)\s+(\d+,\d\d)\s*$")


def table(t):
    """The first table's {(a, b): (ligeros, pesados 1, pesados 2)}, and its date."""
    m = re.search(r"PEAJES VIGENTES (?:EN EUROS )?DESDE EL D[IÍ]A (\d\d)/(\d\d)/(\d{4})", t)
    if not m:
        sys.exit("no 'peajes vigentes desde' date")
    start = t.index("RECORRIDOS DIRECTOS E INVERSOS")
    pairs = {}
    for line in t[start:].splitlines()[1:]:
        if re.search(r"PEAJES VEH[IÍ]CULOS|Descripci[oó]n de veh|PEAJES VIGENTES", line):
            break
        p = PAIR.match(line)
        if p:
            pairs[(norm(p.group(1)), norm(p.group(2)))] = tuple(float(v.replace(",", ".")) for v in p.groups()[2:])
    return pairs, f"{m.group(3)}-{m.group(2)}-{m.group(1)}"


def main(fetched, out):
    srcs = {s["id"]: s for s in json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources.json")))["sources"]}
    for key, mw in MOTORWAYS.items():
        mp = os.path.join(fetched, mw["map"] + ".html")
        if not os.path.exists(mp):
            print(f"{key}: the concessionaire's map wasn't fetched; not built")
            continue
        pts = placemarks(mp)
        stations = []
        for st, names in mw["stations"].items():
            missing = [n for n in names if norm(n) not in pts]
            if missing:
                sys.exit(f"{key}: {missing} not on the concessionaire's map")
            stations.append({"name": st, "points": [{"name": n, "lat": pts[norm(n)][0], "lon": pts[norm(n)][1]} for n in names]})
        for year in ("2025", "2026"):
            sid = f"es-min-{key}-{year}"
            p = os.path.join(fetched, sid + ".txt")
            if not os.path.exists(p):
                print(f"{sid}: not fetched")
                continue
            t = open(p, encoding="utf-8", errors="replace").read()
            pairs, vf = table(t)
            if vf[:4] != year:
                sys.exit(f"{sid}: in force from {vf}, not {year}")
            unknown = {s for ab in pairs for s in ab} - set(mw["stations"])
            if unknown:
                sys.exit(f"{sid}: stations not placed: {sorted(unknown)}")
            prices = {f"{a}|{b}": {"Pesados 1": round(v[1] / IVA, 4), "Pesados 2": round(v[2] / IVA, 4)} for (a, b), v in pairs.items() if a != b}
            reductions = re.findall(r"BONIFICACIONES A PESADOS DEL (RD \d+/\d{4})", t)
            law = (f"The Ministry of Transport's tolls in force from {vf} on the {mw['name']}, by pair of stations either way: Pesados 1 (two or three axles) and Pesados 2 (four axles or more), excluding 21% IVA"
                   + (f", with the heavy-vehicle reductions of {', '.join(sorted(set(reductions)))} the table applies" if reductions else "")
                   + ". Stations placed at the concessionaire's own map of its toll plazas and accesses.")
            tb = {"country": "ES", "currency": "EUR", "valid_from": vf, "valid_to": f"{year}-12-31", "crossings": True,
                  "name": mw["name"], "law": law,
                  "sources": [{"title": srcs[sid]["what"], "url": srcs[sid]["url"]},
                              {"title": srcs[mw["map"]]["what"], "url": srcs[mw["map"]]["page"]}],
                  "vehicles": "Trucks over 3.5 t (Pesados 1 and 2)", "min_kg": 3501, "tolled_roads": mw["tolled"],
                  "closed_systems": [{"name": mw["name"], "law": law, "groups": GROUPS, "stations": stations, "prices": prices}],
                  "rows": []}
            os.makedirs(out, exist_ok=True)
            path = os.path.join(out, f"es-{key}-{vf}.json")
            json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
            print(path, len(stations), "stations,", len(prices), "prices")


if __name__ == "__main__":
    main(*sys.argv[1:])
