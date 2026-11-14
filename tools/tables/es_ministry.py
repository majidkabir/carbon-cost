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


# Motorways with a single mainline toll barrier and a high season.
BARRIERS = {
    "ap46": {"name": "AP-46 Alto de las Pedrizas–Málaga", "osm": "es-min-ap46-osm",
             "tolled": "AP-46 Alto de las Pedrizas–Málaga (one toll barrier, Casabermeja).",
             # Mayo-octubre, weekends, and the 17 days from Viernes de Dolores
             # (Easter - 9) to the Sunday after Easter (+7).
             "barriers": ["TRONCAL DE CASABERMEJA"], "heading": "NIVEL TARIFARIO TEMPORADA",
             "season_text": "Se aplicará los meses de mayo a octubre, todos los sábados y domingos del año, y 17 días desde el Viernes Dolores hasta el domingo siguiente al Domingo de Resurrección",
             "season": {"months": [5, 6, 7, 8, 9, 10], "weekdays": [0, 6], "easter_from": -9, "easter_to": 7},
             "season_en": "May to October, every Saturday and Sunday, and the 17 days from Viernes de Dolores to the Sunday after Easter",
             "names": ["Troncal de Casabermeja"],
             "free_text": "para los vehículos \"Pesados 1\" y \"Pesados 2\", entre las 22:00 y las 08:00 horas del día siguiente",
             "free_hours": ["22:00", "07:59"]},
    # AP-7 Alicante-Cartagena: three barriers, the table's order north to
    # south; booths between its exits 724 and 800 (the AP-7 Cartagena-Vera's
    # are west of them).
    "ap7ac": {"name": "AP-7 Alicante–Cartagena", "osm": "es-min-ap7ac-osm",
              "barriers": ["TRONCAL DE LOS MONTESINOS", "ACCESO DE LA ZENIA", "TRONCAL DE LA ZENIA"], "exits": (724, 800),
              "heading": "TARIFA TEMPORADA", "tolled": "AP-7 Alicante–Cartagena (toll barriers at Los Montesinos and La Zenia).",
              "season_text": "Temporada alta: Meses de junio, julio, agosto, septiembre y diecisiete días en Semana Santa (desde el viernes anterior a la Semana Santa, hasta el domingo siguiente a la misma, ambos inclusive).",
              "season": {"months": [6, 7, 8, 9], "easter_from": -9, "easter_to": 7},
              "season_en": "June to September and the 17 days of Semana Santa (from the Friday before it to the Sunday after it)",
              "names": ["Troncal de Los Montesinos", "Acceso de La Zenia", "Troncal de La Zenia"]},
}


def barrier(key, mw, fetched, out, srcs):
    try:
        d = json.load(open(os.path.join(fetched, mw["osm"] + ".json")))
    except (OSError, ValueError):
        print(f"{key}: OpenStreetMap booths not fetched; not built")
        return
    bs = [(e["lat"], e["lon"]) for e in d["elements"] if e.get("tags", {}).get("barrier") == "toll_booth"]
    if "exits" in mw:
        lo_, hi_ = mw["exits"]
        js = [(e["lat"], e["lon"]) for e in d["elements"] if e.get("tags", {}).get("highway") == "motorway_junction"
              and re.fullmatch(r"\d+", e["tags"].get("ref", "")) and lo_ <= int(e["tags"]["ref"]) <= hi_]
        if not js:
            sys.exit(f"{key}: no junctions {lo_}-{hi_} in OpenStreetMap")
        box = (min(j[0] for j in js) - 0.02, max(j[0] for j in js) + 0.02, min(j[1] for j in js) - 0.02, max(j[1] for j in js) + 0.02)
        bs = [b for b in bs if box[0] <= b[0] <= box[1] and box[2] <= b[1] <= box[3]]
    clusters = []  # booths within 150 m of a cluster's first booth
    for b in sorted(bs, key=lambda b: -b[0]):
        for c in clusters:
            if abs(c[0][0] - b[0]) * 111 + abs(c[0][1] - b[1]) * 89 < 0.15:
                c.append(b)
                break
        else:
            clusters.append([b])
    if len(clusters) != len(mw["barriers"]):
        sys.exit(f"{key}: {len(clusters)} toll plazas in OpenStreetMap, the table has {len(mw['barriers'])} barriers")
    plazas = [(round(sum(b[0] for b in c) / len(c), 6), round(sum(b[1] for b in c) / len(c), 6)) for c in clusters]
    stamp = d.get("osm3s", {}).get("timestamp_osm_base", "")[:10]
    for year in ("2025", "2026"):
        sid = f"es-min-{key}-{year}"
        p = os.path.join(fetched, sid + ".txt")
        if not os.path.exists(p):
            print(f"{sid}: not fetched")
            continue
        t = open(p, encoding="utf-8", errors="replace").read()
        flat = re.sub(r"\s+", " ", t)
        _, vf = table_date(t)
        if vf[:4] != year:
            sys.exit(f"{sid}: in force from {vf}, not {year}")
        if mw["season_text"] not in flat or (mw.get("free_text") and mw["free_text"] not in flat):
            sys.exit(f"{sid}: the season or free hours changed")
        lvl = {}
        for m in re.finditer(mw["heading"] + r" (BAJA|ALTA) (?:(?!" + mw["heading"] + r").)*?BARRERAS DE PEAJE LIGEROS PESADOS 1 PESADOS 2 (.*?)(?= [A-Z]* ?TARIFA| MINISTERIO| Nivel| Temporada| RECORRIDOS|$)", flat):
            got = {n: [float(v.replace(",", ".")) / IVA for v in re.search(re.escape(n) + r" (\d+,\d\d) (\d+,\d\d) (\d+,\d\d)", m.group(2)).groups()]
                   for n in mw["barriers"] if re.search(re.escape(n) + r" \d", m.group(2))}
            if len(got) == len(mw["barriers"]):
                lvl.setdefault(m.group(1), got)
        if set(lvl) != {"BAJA", "ALTA"}:
            sys.exit(f"{sid}: low and high season tolls not found")
        names = ", ".join(mw["names"])
        ex = lvl["BAJA"][mw["barriers"][0]]
        hx = lvl["ALTA"][mw["barriers"][0]]
        law = (f"The Ministry of Transport's tolls in force from {vf} on the {mw['name']}, per barrier ({names}): Pesados 1 (two or three axles) EUR {ex[1]:.4f} "
               f"and Pesados 2 (four axles or more) {ex[2]:.4f} in the low season, {hx[1]:.4f} and {hx[2]:.4f} in the high season, excluding 21% IVA"
               + ("; free for trucks from 22:00 to 08:00" if mw.get("free_hours") else "")
               + f". High season: {mw['season_en']}"
               + ("; regular users pay the low season's tolls all year (not modelled)" if "habituales" in flat else "")
               + ". Barriers placed at OpenStreetMap's toll plazas on the motorway, " + ("in the table's order from north to south." if len(plazas) > 1 else "its only plaza."))
        points = []
        for n, label, (lat, lon) in zip(mw["barriers"], mw["names"], plazas):
            lo, hi = lvl["BAJA"][n], lvl["ALTA"][n]
            pt = {"name": label, "lat": lat, "lon": lon, "rate": 0,
                  "classes": [{"min_kg": 3501, "max_axles": 3, "rate": round(lo[1], 4), "high_rate": round(hi[1], 4)},
                              {"min_kg": 3501, "min_axles": 4, "rate": round(lo[2], 4), "high_rate": round(hi[2], 4)}],
                  "high_season": mw["season"]}
            if mw.get("free_hours"):
                pt["free_hours"] = mw["free_hours"]
            points.append(pt)
        tb = {"country": "ES", "currency": "EUR", "valid_from": vf, "valid_to": f"{year}-12-31", "crossings": True, "osm_extract": stamp,
              "name": mw["name"], "law": law,
              "sources": [{"title": srcs[sid]["what"], "url": srcs[sid]["url"]}, {"title": "OpenStreetMap (Overpass API), toll booths", "url": "https://www.openstreetmap.org/copyright"}],
              "vehicles": "Trucks over 3.5 t (Pesados 1 and 2)", "min_kg": 3501, "tolled_roads": mw["tolled"], "point_match_km": 0.15,
              "toll_points": points,
              "rows": []}
        os.makedirs(out, exist_ok=True)
        path = os.path.join(out, f"es-{key}-{vf}.json")
        json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
        print(path, "barriers at", plazas)


def table_date(t):
    m = re.search(r"PEAJES VIGENTES (?:EN EUROS )?DESDE EL D[IÍ]A (\d\d)/(\d\d)/(\d{4})", t)
    if not m:
        sys.exit("no 'peajes vigentes desde' date")
    return None, f"{m.group(3)}-{m.group(2)}-{m.group(1)}"


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
    for key, mw in BARRIERS.items():
        barrier(key, mw, fetched, out, srcs)


if __name__ == "__main__":
    main(*sys.argv[1:])
