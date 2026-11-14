"""Builds Gipuzkoa's canon for heavy vehicles on the N-I and A-15 (Bidegi)
as a closed system priced by entry and exit.

Usage: python3 es_basque.py fetched/ out-dir -> out-dir/es-basque-<date>.json

Law: Norma Foral 5/2021, de 3 de diciembre (Gipuzkoa), consolidated from
27 December 2022 (fetch.py's es-gipuzkoa-nf-5-2021): the canon is charged
on the N-I and A-15 along their whole length in Gipuzkoa by free-flow
gantries (article 6), to heavy goods vehicles over 3.5 t: "Pesados 1"
under 12 t and "Pesados 2" from 12 t (article 7), VAT included, at a
percentage of the amounts by EURO class (article 8: 80% EURO 6, 85% EURO 5,
for trucks registered with Bidegi with a TAG; 75% for electric, hybrid and
gas trucks, not modelled), with frequency discounts from the 21st trip in
a month (article 8 bis, not modelled).

Prices: Bidegi's 2026 tariff matrix (fetch.py's es-bidegi-n1-a15-2026,
pdftotext -bbox words): page 1 Pesados 1, page 2 Pesados 2; rows are
entries ("Sarrera"), columns exits ("Irteera"), numbered 1 to 32 with
their road and PK. Prices exclude the 21% VAT here.

Stations: fetch.py's es-basque-osm.json (Overpass): the N-I and A-15
carriageways and their junction nodes, matched to the matrix's stations
by exit number (the PK rounded); see place().
"""
import json, math, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tr_matrix  # noqa: E402  (pdftotext -bbox words)
import m6toll  # noqa: E402  (carriageway chains)

VAT = 1.21
PRICE = re.compile(r"^\d+,\d\d$")


def matrix(path):
    """{group: {(entry, exit): euros with VAT}}, {station: (road, pk)}."""
    out, roads = {}, {}
    for ws in tr_matrix.words(path):
        title = " ".join(w[4] for w in ws if w[1] < 100)
        m = re.search(r"Pesados (\d)", title)
        hdr = [w for w in ws if w[4] == "Zk"]
        if not m or not hdr:
            continue
        y0 = (hdr[0][1] + hdr[0][3]) / 2
        cols = {int(w[4]): (w[0] + w[2]) / 2 for w in ws if abs((w[1] + w[3]) / 2 - y0) < 2 and w[4].isdigit() and w[0] > hdr[0][2]}
        rows = {}
        for w in ws:
            y = (w[1] + w[3]) / 2
            if y > y0 + 5 and hdr[0][0] - 5 < w[0] < hdr[0][2] + 10 and w[4].isdigit() and int(w[4]) <= max(cols):
                rows.setdefault(int(w[4]), y)
        for r, y in rows.items():
            line = sorted((w for w in ws if abs((w[1] + w[3]) / 2 - y) < 2 and w[2] < hdr[0][0]), key=lambda w: w[0])
            road = next((w[4] for w in line if re.fullmatch(r"N-I|A-15", w[4])), None)
            pk = next((float(w[4].replace(",", ".")) for w in line if re.fullmatch(r"\d{3},\d\d", w[4])), None)
            if road and pk:
                roads[r] = (road, pk)
        g = out.setdefault(f"P{m.group(1)}", {})
        for w in ws:
            if not PRICE.match(w[4]) or w[0] < hdr[0][2] or w[1] < y0 + 5:
                continue
            y, x = (w[1] + w[3]) / 2, (w[0] + w[2]) / 2
            r = [k for k, v in rows.items() if abs(v - y) < 2]
            c = min(cols, key=lambda k: abs(cols[k] - x))
            if not r or abs(cols[c] - x) > 12:
                sys.exit(f"N-I/A-15: price {w[4]} at ({x:.0f}, {y:.0f}) is in no row or column")
            g[(r[0], c)] = float(w[4].replace(",", "."))
    if sorted(out) != ["P1", "P2"] or len(roads) != 32:
        sys.exit(f"N-I/A-15: groups {sorted(out)}, {len(roads)} stations")
    if set(out["P1"]) != set(out["P2"]):
        sys.exit("N-I/A-15: Pesados 1 and 2 price different pairs")
    for (a, b), v in out["P1"].items():
        if out["P2"][a, b] < v:
            sys.exit(f"N-I/A-15: {a}-{b} is cheaper for Pesados 2")
    return out, roads


NAMES = {  # the matrix's legend (Spanish half), checked against the PDF's words
    1: "Límite Navarra (Etzegarate)", 2: "Idiazabal sur", 3: "Segura", 4: "Idiazabal norte", 5: "Olaberria",
    6: "A-636", 7: "Lazkao y Beasain", 8: "Ordizia sur", 9: "Ordizia norte", 10: "Legorreta", 11: "Ikaztegieta",
    12: "Alegia", 13: "Tolosa sur", 14: "Tolosa centro", 15: "Tolosa norte", 16: "Irura sur", 17: "Irura norte",
    18: "Villabona sur", 19: "Villabona norte", 20: "Andoain sur", 21: "Andoain Cruz Roja", 22: "Andoain norte",
    23: "Lasarte-Oria sur", 24: "Lasarte-Oria centro y norte", 25: "Urmeneta (Andoain)", 26: "Urnieta",
    27: "Mandazubi (Hernani)", 28: "Zikuñaga (Hernani)", 29: "Martindegi (Hernani)", 30: "Astigarraga",
    31: "Berastegi", 32: "Límite Navarra (A-15)"}
# The legend words each name must find in the PDF (as printed, upper case).
LEGEND = {1: "NAVARRA (Etzegarate)", 3: "SEGURA", 5: "OLABERRIA", 6: "A-636", 10: "LEGORRETA", 11: "IKAZTEGIETA",
          12: "ALEGIA", 21: "Cruz Roja", 25: "URMENETA", 26: "URNIETA", 27: "MANDAZUBI", 28: "ZIKUÑAGA",
          29: "MARTINDEGI", 30: "ASTIGARRAGA", 31: "BERASTEGI"}

# Exit numbers (km) used to fit each road's PK to OSM distance: the N-I in
# Gipuzkoa; the A-15 south of Andoain; the A-15 east of it.
FIT = {"N-I": (400, 460), "A-15S": (100, 150), "A-15N": (155, 175)}


def group_of(station, roads):
    road, pk = roads[station]
    return "N-I" if road == "N-I" else ("A-15S" if pk < 150 else "A-15N")


def oneway_lines(osm, road):
    """The road's one-way carriageway chains (lists of (lon, lat)), ways
    whose ref includes it (a stretch two roads share carries both)."""
    ways = []
    for e in osm["elements"]:
        t = e.get("tags", {})
        if e["type"] == "way" and t.get("highway") in ("motorway", "trunk") and road in [r.strip() for r in t.get("ref", "").split(";")]:
            g = tuple((p["lon"], p["lat"]) for p in e["geometry"])
            ways.append(g[::-1] if t.get("oneway") == "-1" else g)
    return [l for l in m6toll.chains(ways) if m6toll.along(l)[-1] > 1]


def junctions(osm):
    """Junction nodes with a numeric exit ref: [((lon, lat), km)]."""
    out = []
    for e in osm["elements"]:
        t = e.get("tags", {})
        m = re.fullmatch(r"(\d{2,3}) ?[A-Z]?", t.get("ref", ""))
        if e["type"] == "node" and t.get("highway") == "motorway_junction" and m:
            out.append(((e["lon"], e["lat"]), int(m.group(1))))
    return out


def fit(line, cum, juncs, lo, hi):
    """(sign, offset): PK = offset + sign * km along the line, from the
    junctions within 60 m whose exit number is in [lo, hi] (an exit is
    numbered by its PK's km, so + 0.5 on average); None if under 3."""
    pts = []
    for p, k in juncs:
        if lo <= k <= hi:
            s, d = m6toll.project(line, cum, p)
            if d < 0.06:
                pts.append((s, k + 0.5))
    if len(pts) < 3:
        return None
    pts.sort()
    sign = 1 if pts[-1][1] > pts[0][1] else -1
    off = sorted(k - sign * s for s, k in pts)
    o = off[len(off) // 2]
    worst = max(abs(k - sign * s - o) for s, k in pts)
    if worst > 1.6:
        sys.exit(f"N-I/A-15: exit numbers {lo}-{hi} fit the carriageway only within {worst:.2f} km")
    return sign, o



def station_points(lines, stations, roads, juncs):
    """{station: [(lon, lat)]}: each station's place on every carriageway
    whose exit numbers fit its road (see fit): at the junction nodes
    numbered with the station's PK's km, projected within 100 m and 1.2 km
    of its PK, where only that station has the number on its road; else at
    its PK by the fitted origin."""
    pts = {}
    for line in lines:
        cum = m6toll.along(line)
        for g, (lo, hi) in FIT.items():
            f = fit(line, cum, juncs, lo, hi)
            if not f:
                continue
            sign, off = f
            mine = [s for s in stations if group_of(s, roads) == g]
            for s in mine:
                pk = roads[s][1]
                at = (pk - off) * sign
                if not -2 < at < cum[-1] + 2:
                    continue
                snap = []
                if [int(roads[t][1]) for t in mine].count(int(pk)) == 1:
                    for p, k in juncs:
                        if k == int(pk):
                            x, d = m6toll.project(line, cum, p)
                            if d < 0.1 and abs(x - at) < 1.2:
                                snap.append(x)
                if snap:
                    at = sum(snap) / len(snap)
                pts.setdefault(s, []).append(m6toll.at(line, cum, min(max(at, 0.0), cum[-1]))[0])
    return pts


def cuts(line, cum, pts, road, roads):
    """[(km along, station)] where the stations cut the line, in order: a
    station of the line's road at the mean of its places within 150 m; any
    other station placed on the line itself (a shared stretch)."""
    out = []
    for s, ps in pts.items():
        on = [m6toll.project(line, cum, p) for p in ps]
        near = [x for x, d in on if d < (0.15 if roads[s][0] == road else 0.02)]
        if near:
            out.append((sum(near) / len(near), s))
    return sorted(out)


def sections(osm, roads):
    """The carriageways cut at the stations: [(entry, exit, (lon, lat),
    heading)], each stretch between two consecutive stations, at its
    middle and in its direction. OSM breaks a carriageway into pieces where
    roads join or part; a piece's stretch before its first station starts
    at the last station passed on the piece it leaves (within 0.6 km, the
    same way within 100 degrees), one after its last station ends at the
    first station on the piece it joins."""
    juncs = junctions(osm)
    lines = {road: oneway_lines(osm, road) for road in ("N-I", "A-15")}
    pts = station_points(lines["N-I"] + lines["A-15"], list(roads), roads, juncs)
    missing = sorted(set(roads) - set(pts))
    if missing:
        sys.exit(f"N-I/A-15: stations {missing} not placed")
    pieces = []
    for road, ls in lines.items():
        for line in ls:
            cum = m6toll.along(line)
            pieces.append((line, cum, cuts(line, cum, pts, road, roads)))

    def onto(p, h, me):
        """(piece, km along) of the other piece p lies on, going h."""
        best = None
        for q in pieces:
            if q is me:
                continue
            x, d = m6toll.project(q[0], q[1], p)
            if d < 0.6 and abs((m6toll.at(q[0], q[1], x)[1] - h + 540) % 360 - 180) < 100 and (best is None or d < best[0]):
                best = (d, q, x)
        return best and best[1:]

    out = {}

    def add(a, b, line, cum, xa, xb):
        if a != b and xb - xa > 0.05:
            p, h = m6toll.at(line, cum, (xa + xb) / 2)
            out.setdefault((a, b), (p, h))

    for piece in pieces:
        line, cum, c = piece
        for (xa, a), (xb, b) in zip(c, c[1:]):
            add(a, b, line, cum, xa, xb)
        if not c:
            continue
        if c[0][0] > 0.1:
            o = onto(line[0], m6toll.at(line, cum, 0)[1], piece)
            before = [s for x, s in o[0][2] if x <= o[1] + 0.05] if o else []
            if o and before:
                add(before[-1], c[0][1], line, cum, 0, c[0][0])
        if c[-1][0] < cum[-1] - 0.1:
            o = onto(line[-1], m6toll.at(line, cum, cum[-1])[1], piece)
            after = [s for x, s in o[0][2] if x >= o[1] - 0.05 and s != c[-1][1]] if o else []
            if o and after:
                add(c[-1][1], after[0], line, cum, c[-1][0], cum[-1])
    return [(a, b, p, h) for (a, b), (p, h) in out.items()]


def main(fetched, out):
    prices, roads = matrix(os.path.join(fetched, "es-bidegi-n1-a15-2026.bbox.html"))
    text = " ".join(w[4] for ws in tr_matrix.words(os.path.join(fetched, "es-bidegi-n1-a15-2026.bbox.html")) for w in ws)
    for n, words in LEGEND.items():
        if words not in text:
            sys.exit(f"N-I/A-15: the legend no longer names {n} {words!r}")
    law = re.sub(r"\s+", " ", open(os.path.join(fetched, "es-gipuzkoa-nf-5-2021.txt"), encoding="utf-8").read())
    for needle in ("Pesados 1: masa máxima autorizada superior a 3,5 toneladas e inferior a 12 toneladas",
                   "Pesados 2: masa máxima autorizada igual o superior a 12 toneladas",
                   "Vehículos pesados EURO 6 (Reglamento 595/2009)", "anexos II y III (IVA incluido)"):
        if needle not in law:
            sys.exit(f"N-I/A-15: Norma Foral 5/2021 no longer says {needle!r}")
    if not re.search(r"Grupo 2 Vehículos pesados EURO 6 \(Reglamento 595/2009\) EURO 5 .*? 85 Grupo 3", law) or " 80 Grupo 2 " not in law:
        sys.exit("N-I/A-15: the EURO percentages changed")

    osm = json.load(open(os.path.join(fetched, "es-basque-osm.json")))
    secs = sections(osm, roads)
    name = lambda a, b: f"{NAMES[a]} > {NAMES[b]}"
    # Sections follow each other where one ends at the station the next starts at.
    nxt = {}
    for a, b, _, _ in secs:
        nxt.setdefault(a, set()).add(b)
    tb_prices = {}
    for a, b, _, _ in secs:
        seen, todo = {(a, b)}, [(a, b)]
        while todo:
            x, y = todo.pop()
            if (a, y) in prices["P1"]:
                tb_prices[f"{name(a, b)}|{name(x, y)}"] = {g: round(prices[g][a, y] / VAT, 4) for g in ("P1", "P2")}
            for z in nxt.get(y, ()):
                if (y, z) not in seen and z != x:
                    seen.add((y, z))
                    todo.append((y, z))
    priced = {tuple(k.split("|")) for k in tb_prices}
    lost = [(a, b) for (a, b) in prices["P1"] if not any(k[0].startswith(NAMES[a] + " >") and k[1].endswith("> " + NAMES[b]) for k in priced)]
    if len(lost) > 40:
        sys.exit(f"N-I/A-15: {len(lost)} entry-exit pairs no route of sections gives: {lost[:20]}")
    stamp = osm.get("osm3s", {}).get("timestamp_osm_base", "")[:10]
    p2 = prices["P2"][1, 24]
    tb = {
        "country": "ES", "currency": "EUR", "valid_from": "2026-01-01", "valid_to": "2026-12-31", "crossings": True,
        "osm_extract": stamp,
        "name": "N-I and A-15 heavy vehicle canon (Gipuzkoa, Bidegi)",
        "law": ("Norma Foral 5/2021, de 3 de diciembre (Gipuzkoa), as amended by Norma Foral 6/2022: a canon on the N-I and A-15 along their whole length in Gipuzkoa, charged by free-flow gantries "
                "to goods vehicles over 3.5 t, Pesados 1 under 12 t and Pesados 2 from 12 t (article 7), by entry and exit, at Bidegi's 2026 tariffs "
                f"(Pesados 2 from the Navarra border at Etzegarate to Lasarte-Oria EUR {p2:.2f} with IVA), excluding 21% IVA here; "
                "80% for EURO 6 and 85% for EURO 5 trucks registered with Bidegi with a TAG (article 8; 75% for electric, hybrid and gas trucks and the frequency discounts of article 8 bis are not modelled). "
                "Stations: each carriageway's stretch between two of the tariff's entries and exits, at its middle and in its direction; the entries and exits placed at their PK along the OpenStreetMap carriageways, "
                "the PK fitted to the junctions' exit numbers, or at the junction itself where its exit number is the station's alone."
                + (f" Entry-exit pairs no run of stretches gives: {len(lost)}." if lost else "")),
        "sources": [{"title": "Bidegi: N-I and A-15 tariffs 2026 (2026__N-I-A-15_tarifak.pdf)", "url": "https://www.bidegi.eus/documents/42696171/0/2026__N-I-A-15_tarifak.pdf/f1728e98-d55a-b934-c3ff-276649650617"},
                    {"title": "Norma Foral 5/2021 de Gipuzkoa (consolidated text from 27/12/2022)", "url": "https://egoitza.gipuzkoa.eus/ogasuna/normativa/docs/0001239c.pdf"},
                    {"title": "Bidegi: vehicle categories", "url": "https://www.bidegi.eus/documents/42696171/0/Categoria+de+veh%C3%ADculos_CAS.pdf/07c6468b-5045-2d19-4a59-1f16a5062528"},
                    {"title": "OpenStreetMap (Overpass API): the N-I and A-15 carriageways and junctions", "url": "https://www.openstreetmap.org/"}],
        "vehicles": "Goods vehicles over 3.5 t: Pesados 1 under 12 t, Pesados 2 from 12 t", "min_kg": 3501,
        "tolled_roads": "N-I from the Navarra border (Etzegarate) to Lasarte-Oria; A-15 from the Navarra border to Andoain and from Andoain to Astigarraga.",
        "closed_systems": [{
            "name": "N-I/A-15 Gipuzkoa", "law": "Norma Foral 5/2021 (Gipuzkoa): by entry and exit, per direction.",
            "directed": True, "station_match_km": 0.1,
            "groups": [{"name": "P2", "min_kg": 12000}, {"name": "P1", "min_kg": 3501}],
            "stations": [{"name": name(a, b), "points": [{"name": f"between {NAMES[a]} and {NAMES[b]}", "lat": round(p[1], 6), "lon": round(p[0], 6), "heading": h}]}
                         for a, b, p, h in sorted(secs)],
            "prices": dict(sorted(tb_prices.items())),
            "discounts": [{"name": "EURO 6 (80%)", "etc": True, "euro": [6], "percent": 20}, {"name": "EURO 5 (85%)", "etc": True, "euro": [5], "percent": 15}]}],
        "rows": [],
    }
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, "es-basque-2026-01-01.json")
    json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, len(secs), "stretches,", len(tb_prices), "pairs,", len(lost), "pairs not reached")


if __name__ == "__main__":
    main(*sys.argv[1:])
