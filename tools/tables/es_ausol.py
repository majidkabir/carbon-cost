"""Builds the tables of Spain's AP-7 Málaga–Estepona and Estepona–Guadiaro
(Autopista del Sol, Ausol), an open system charged at toll barriers.

Usage: python3 es_ausol.py fetched/ out-dir -> out-dir/es-ausol-<date>.json

Prices: Ausol's tariff page (fetch.py's es-op-ausol.html), approved by
Orden Ministerial of 18 December 2025: per barrier (troncal on the main
road, lateral on the ramps), for Pesados 1 (two or three axles) and
Pesados 2 (four or more), in the normal and the special season, 21% IVA
included (divided out here). The special season (RD 436/1996 and RD
1099/1999, as the page quotes them) is June to September and the 17 days
from the Friday before Holy Week to the Sunday after Easter: one table
per stretch of dates.

Positions: OpenStreetMap's toll booths (es-conc-osm.json, an Overpass
query). Only the main-road (troncal) barriers are priced: Calahonda and
San Pedro at their booths on the AP-7 itself, and Manilva at the only
cluster of booths on that stretch (mapped on the plaza's links). The lateral barriers on the ramps
aren't: San Pedro's stand within 100 m of the main road, so they couldn't
be told apart from it, and Calahonda's and Manilva's aren't mapped. A trip
joining or leaving at a lateral barrier is priced as through traffic.
"""
import datetime, html, json, math, os, re, sys

IVA = 1.21
BARRIERS = ["Calahonda troncal", "Calahonda lateral", "San Pedro troncal", "San Pedro lateral", "Manilva troncal", "Manilva lateral"]
# Where each troncal barrier's booths stand, roughly (to pick its cluster).
NEAR = {"Calahonda troncal": (36.506, -4.718), "San Pedro troncal": (36.499, -5.009), "Manilva troncal": (36.380, -5.265)}


def text(path):
    t = open(path, encoding="utf-8", errors="replace").read()
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", t, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t)))


def km(a, b):
    return math.hypot((a[1] - b[1]) * 111.2 * math.cos(math.radians(a[0])), (a[0] - b[0]) * 111.2)


def easter(y):
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    return datetime.date(y, month, (h + l - 7 * m + 114) % 31 + 1)


def seasons(y):
    """(from, to, special) stretches covering the year."""
    e = easter(y)
    special = [(e - datetime.timedelta(days=9), e + datetime.timedelta(days=7)), (datetime.date(y, 6, 1), datetime.date(y, 9, 30))]
    out, day = [], datetime.date(y, 1, 1)
    for a, b in special:
        out.append((day, a - datetime.timedelta(days=1), False))
        out.append((a, b, True))
        day = b + datetime.timedelta(days=1)
    out.append((day, datetime.date(y, 12, 31), False))
    return out


def main(fetched, out):
    t = text(os.path.join(fetched, "es-op-ausol.html"))
    if "O.M. del Ministerio de Transporte y Movilidad Sostenible de fecha 18 de diciembre de 2025" not in t:
        sys.exit("Ausol: the tariffs' Orden Ministerial changed; check the page")
    year = 2026
    prices = {}
    for season in ("normal", "especial"):
        i = t.find(f"Tarifas temporada {season} {year}")
        if i < 0:
            sys.exit(f"Ausol: {season} season {year} not found")
        seg = t[i:i + 3000]
        heads = re.findall(r"(CALAHONDA|SAN PEDRO|MANILVA) (TRONCAL|LATERAL)", seg)[:6]
        if [f"{a.title()} {b.lower()}" for a, b in heads] != BARRIERS:
            sys.exit(f"Ausol: {season} columns {heads}")
        for cls in ("Pesado1", "Pesado 2"):
            m = re.search(r"((?:\d+[.,]\d\d €\s*){6})", seg[seg.find(cls + " "):])
            prices[(season, cls)] = [float(v.replace(",", ".")) for v in re.findall(r"(\d+[.,]\d\d) €", m.group(1))]
    d = json.load(open(os.path.join(fetched, "es-conc-osm.json")))
    stamp = d.get("osm3s", {}).get("timestamp_osm_base", "")[:10]
    booths = [e for e in d["elements"] if e["type"] == "node"]
    pos = {}
    on_ap7 = {(round(p["lat"], 7), round(p["lon"], 7)) for e in d["elements"] if e["type"] == "way" and e.get("tags", {}).get("ref") == "AP-7" for p in e["geometry"]}
    for b, near in NEAR.items():
        c = [n for n in booths if km((n["lat"], n["lon"]), near) < 0.3]
        # Where some booths stand on the AP-7 itself, those are the
        # barrier's (the others are the ramps' lateral ones).
        c = [n for n in c if (round(n["lat"], 7), round(n["lon"], 7)) in on_ap7] or c
        if not c:
            sys.exit(f"Ausol: no booths at {b}")
        lat, lon = sum(n["lat"] for n in c) / len(c), sum(n["lon"] for n in c) / len(c)
        if max(km((lat, lon), (n["lat"], n["lon"])) for n in c) > 0.15:
            sys.exit(f"Ausol: {b}'s booths spread over more than 150 m")
        pos[b] = (round(lat, 6), round(lon, 6))
    for a, b, special in seasons(year):
        s = "especial" if special else "normal"
        pts = []
        for name in NEAR:
            k = BARRIERS.index(name)
            p1, p2 = prices[(s, "Pesado1")][k], prices[(s, "Pesado 2")][k]
            pts.append({"name": "AP-7 " + name.replace(" troncal", ""), "lat": pos[name][0], "lon": pos[name][1], "rate": 0, "classes": [
                {"min_kg": 3501, "max_axles": 3, "rate": round(p1 / IVA, 4)},
                {"min_kg": 3501, "min_axles": 4, "rate": round(p2 / IVA, 4)}]})
        tb = {"country": "ES", "currency": "EUR", "valid_from": a.isoformat(), "valid_to": b.isoformat(), "crossings": True, "osm_extract": stamp,
              "name": f"AP-7 Málaga–Estepona–Guadiaro toll (Ausol), {'special' if special else 'normal'} season",
              "law": f"Tariffs of Autopista del Sol, Concesionaria Española, approved by Orden Ministerial of 18 December 2025, {year}: per troncal barrier (Calahonda, San Pedro, Manilva), Pesados 1 (two or three axles) and Pesados 2 (four or more), excluding 21% IVA; the {'special season (RD 436/1996, RD 1099/1999: June to September and the 17 days from the Friday before Holy Week to the Sunday after Easter)' if special else 'normal season'}. The lateral barriers on the ramps aren't priced: a trip joining or leaving at one is priced as through traffic.",
              "sources": [{"title": "Ausol: tarifas", "url": "https://www.ausol.es/es/tarifas-y-descuentos/tarifas"}],
              "vehicles": "Pesados 1 (two or three axles) and Pesados 2 (four or more)", "min_kg": 3501,
              "tolled_roads": "AP-7 Málaga–Estepona (Calahonda, San Pedro) and Estepona–Guadiaro (Manilva), at the main-road barriers.",
              "point_match_km": 0.1, "toll_points": pts, "rows": []}
        os.makedirs(out, exist_ok=True)
        path = os.path.join(out, f"es-ausol-{a.isoformat()}.json")
        json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
        print(path, s)


if __name__ == "__main__":
    main(*sys.argv[1:])
