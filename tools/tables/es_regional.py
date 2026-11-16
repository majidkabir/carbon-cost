"""Builds the regional toll roads of Catalonia (Generalitat) and Navarra
(AP-15, Audenasa) charged at barriers: per passage, either way.

Usage: python3 es_regional.py fetched/ out-dir -> out-dir/es-<road>-<date>.json

- Catalonia: the Generalitat's "Tarifes de peatges 2026" page (fetch.py's
  es-gencat-peatges.html; yearly revision by Resolució under Decret
  465/2004): the C-16 Túnel del Cadí, the Túnels de Vallvidrera (off-peak
  price; peak hours priced off-peak with a note), and the C-16 barriers of
  les Fonts and Sant Vicenç de Castellet (weekday and weekend prices; les
  Fonts' weekday price only with Via-T/Satelise, so `etc`). Category 4
  (trucks with more than 4 wheels or three axles; trucks over 3.5 t are
  taken to be). The C-16 Manresa barrier and the C-32 barriers have no
  named OSM booths and aren't priced.
- Navarra: Audenasa's "Tarifas y Recorrido 2026" (es-audenasa-2026.txt):
  the AP-15 barriers Sarasa, Oriz-Tiebas, Marcilla tronco and Marcilla
  enlace, Pesados I (two or three axles) and II (four or more), where
  OpenStreetMap names their booths.
Prices include 21% IVA, divided out. Positions: OSM toll booths
(es-regional-osm.json) by name.
"""
import html, json, os, re, sys

VAT = 1.21


def text(path):
    t = open(path, encoding="utf-8", errors="replace").read()
    t = re.sub(r"<(script|style).*?</\1>", " ", t, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t)))


def num(s):
    return float(s.replace(".", "").replace(",", "."))


def centre(pts):
    return round(sum(p[0] for p in pts) / len(pts), 6), round(sum(p[1] for p in pts) / len(pts), 6)


def write(out, t, name):
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"{name}-{t['valid_from']}.json")
    json.dump(t, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, len(t["toll_points"]), "points")


def main(fetched, out):
    d = json.load(open(os.path.join(fetched, "es-regional-osm.json")))
    stamp = d.get("osm3s", {}).get("timestamp_osm_base", "")[:10]
    named = {}
    for e in d.get("elements", []):
        n = e.get("tags", {}).get("name")
        if e["type"] == "node" and e.get("tags", {}).get("barrier") == "toll_booth" and n:
            named.setdefault(n, []).append((e["lat"], e["lon"]))

    # Catalonia.
    t = text(os.path.join(fetched, "es-gencat-peatges.html"))
    year = re.search(r"Tarifes de peatges (\d{4})", t)
    eur = r"([\d,]+) €"
    cadi = re.search(r"C-16 Túnel del Cadí " + " ".join([eur] * 4), t)
    vall = re.search(r"C-16 Túnel de Vallvidrera Hora vall \(1\) " + " ".join([eur] * 4) + r" C-16 Túnel de Vallvidrera Hora punta \(1\) " + " ".join([eur] * 4), t)
    fonts = re.search(r"Barrera troncal de les Fonts Dilluns-divendres no festius \(2\) " + " ".join([eur] * 4) + r" C-16 Tram Sant Cugat-Terrassa Barrera troncal de les Fonts Dissabtes, diumenges i festius " + " ".join([eur] * 4), t)
    vicenc = re.search(r"Barrera troncal de Sant Vicenç de Castellet Dilluns-divendres no festius \(3\) " + " ".join([eur] * 4) + r" C-16 Tram Terrassa-Manresa Barrera troncal de Sant Vicenç de Castellet Dissabtes, diumenges i festius " + " ".join([eur] * 4), t)
    via_t = "La tarifa reduïda serà d'aplicació a totes les categories de vehicles sempre que s’utilitzi com a modalitat de pagament el sistema dinàmic Via-T o Satelise" in t
    if not (year and cadi and vall and fonts and vicenc and via_t):
        sys.exit(f"Catalonia: the tariff page changed ({bool(year)}, {bool(cadi)}, {bool(vall)}, {bool(fonts)}, {bool(vicenc)}, {via_t})")
    c4 = lambda m, i: round(num(m.group(i)) / VAT, 4)
    weekend = {"weekdays": [0, 6]}
    places = {"Túnel del Cadí": named.get("Peatge Túnel del Cadí"), "Túnels de Vallvidrera": named.get("Peatge Túnels de Vallvidrera"),
              "les Fonts": (named.get("Peatge de les Fonts") or []) + (named.get("Peatge de les Fonts (Via-T)") or []),
              "Sant Vicenç de Castellet": (named.get("Sant Vicenç") or []) + (named.get("Sant Vicenç (Via-T)") or [])}
    missing = [k for k, v in places.items() if not v]
    if missing:
        sys.exit(f"Catalonia: no OSM booths for {missing}")
    pt = lambda name, cls, **kw: dict({"name": f"C-16 {name}", "lat": centre(places[name])[0], "lon": centre(places[name])[1], "rate": 0, "classes": [dict({"min_kg": 3501}, **cls)]}, **kw)
    points = [
        pt("Túnel del Cadí", {"rate": c4(cadi, 4)}),
        pt("Túnels de Vallvidrera", {"rate": c4(vall, 4)}, peak_rate=c4(vall, 8)),
        pt("les Fonts", {"rate": c4(fonts, 8), "etc_rate": c4(fonts, 4), "high_rate": c4(fonts, 8), "high_etc_rate": c4(fonts, 8)}, high_season=weekend),
        pt("Sant Vicenç de Castellet", {"rate": c4(vicenc, 4), "high_rate": c4(vicenc, 8)}, high_season=weekend),
    ]
    y = year.group(1)
    write(out, {
        "country": "ES", "currency": "EUR", "valid_from": f"{y}-01-01", "valid_to": f"{y}-12-31", "crossings": True, "osm_extract": stamp,
        "name": "Catalonia: C-16 tolls (Túnel del Cadí, Túnels de Vallvidrera, les Fonts, Sant Vicenç de Castellet)",
        "law": (f"The Generalitat de Catalunya's toll rates for {y} (yearly revision by Resolució under Decret 465/2004), category 4 (trucks with more than four wheels, or three axles; trucks over 3.5 t are taken to be), "
                "per passage either way, excluding 21% IVA: the Túnel del Cadí; the Túnels de Vallvidrera at the off-peak price (weekdays 7:30-10:30 and 17:00-21:00 cost more, priced off-peak with a note); "
                "the C-16 barriers of les Fonts (the weekday price only with Via-T or Satelise, so `etc`; else and at weekends the full price) and Sant Vicenç de Castellet (weekday and weekend prices; public holidays aren't modelled). "
                "The C-16 Manresa barrier and the C-32 barriers have no named booths in OpenStreetMap and aren't priced."),
        "sources": [{"title": f"Generalitat de Catalunya: Tarifes de peatges {y}", "url": "https://territori.gencat.cat/ca/03_infraestructures_i_mobilitat/carreteres/peatges-tarifes-descomptes/tarifes-peatges/"},
                    {"title": "OpenStreetMap (Overpass API): toll booths", "url": "https://www.openstreetmap.org/"}],
        "vehicles": "Category 4 (here trucks over 3.5 t)", "min_kg": 3501,
        "tolled_roads": "C-16 Túnel del Cadí, Túnels de Vallvidrera, and the barriers of les Fonts (Sant Cugat-Terrassa) and Sant Vicenç de Castellet (Terrassa-Manresa).",
        "point_match_km": 0.2, "toll_points": points, "rows": []}, "es-catalonia-c16")

    # Navarra AP-15 (Audenasa).
    p = os.path.join(fetched, "es-audenasa-2026.txt")
    if not os.path.exists(p):
        print("AP-15: es-audenasa-2026.txt not fetched; not built")
        return
    a = re.sub(r"[ \t]+", " ", open(p, encoding="utf-8").read())
    year = re.search(r"Tarifas y Recorrido (\d{4})", a)
    bars = {m.group(1).strip(): (num(m.group(3)), num(m.group(4))) for m in re.finditer(r"^ ?(SARASA|ORIZ-TIEBAS|MARCILLA TRONCO|MARCILLA ENLACE) ([\d,]+) ([\d,]+) ([\d,]+)$", a, re.M)}
    if not year or len(bars) != 4:
        sys.exit(f"AP-15: the tariff sheet changed ({bool(year)}, {sorted(bars)})")
    osm = {"SARASA": "Sarasa", "ORIZ-TIEBAS": "Oriz-Tiebas", "MARCILLA TRONCO": "Marcilla", "MARCILLA ENLACE": "Marcilla enlace"}
    pts, missing = [], []
    for b, (p1, p2) in bars.items():
        loc = named.get(osm[b])
        if not loc:
            missing.append(b.title())
            continue
        lat, lon = centre(loc)
        pts.append({"name": f"AP-15 {b.title()}", "lat": lat, "lon": lon, "rate": 0,
                    "classes": [{"min_kg": 3501, "max_axles": 3, "rate": round(p1 / VAT, 4)}, {"min_kg": 3501, "min_axles": 4, "rate": round(p2 / VAT, 4)}]})
    if not pts:
        print(f"AP-15: no barrier has a named OSM booth ({missing}); not built")
        return
    y = year.group(1)
    write(out, {
        "country": "ES", "currency": "EUR", "valid_from": f"{y}-01-01", "valid_to": f"{y}-12-31", "crossings": True, "osm_extract": stamp,
        "name": "AP-15 Navarra (Audenasa) barriers",
        "law": (f"Audenasa's tariffs {y} (the Gobierno de Navarra's concession of the AP-15): per passage of each barrier, either way, Pesados I (two or three axles) and II (four or more), excluding 21% IVA. "
                + (f"Not placed (no named OSM booth), so not priced: {', '.join(missing)}." if missing else "")),
        "sources": [{"title": f"Audenasa: Tarifas y Recorrido {y}", "url": "https://www.audenasa.es/storage/Tarifas-2026-Recorrido.pdf"},
                    {"title": "OpenStreetMap (Overpass API): toll booths", "url": "https://www.openstreetmap.org/"}],
        "vehicles": "Pesados I and II (trucks over 3.5 t)", "min_kg": 3501,
        "tolled_roads": "AP-15 Irurzun–Tudela (Navarra): " + ", ".join(p["name"][6:] for p in pts) + ".",
        "point_match_km": 0.2, "toll_points": pts, "rows": []}, "es-ap15")


if __name__ == "__main__":
    main(*sys.argv[1:])
