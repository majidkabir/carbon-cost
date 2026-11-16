"""Builds the Consorzio per le Autostrade Siciliane's toll table (A18
Messina-Catania and A20 Messina-Palermo) from its tolls in force by entry
and exit station (fetch.py's it-cas-a18.txt and it-cas-a20.txt, the PDFs
as text) and OSM (it-cas-a18-links-osm.json, it-cas-a20-links-osm.json):
two closed systems by entry and exit.

Usage: python3 it_cas.py fetched/ out-dir -> out-dir/it-cas-<date>.json

Prices: the tables' tolls by entry and exit station and class (A, B, 3,
4, 5), VAT included (as the main Italian table's rates), either way.

Stations, in the tables' order along the motorway: the others at the
junctions whose exits are signposted to them; the terminal barriers (A18
Messina Sud and Catania Nord, A20 Messina Nord and Buonfornello) at the
toll plaza in OSM (a cluster of toll booths) nearest the end station
among those over 2 km beyond it. A stretch of carriageway between two consecutive
stations is a station of the system (es_stretch). The A20's Villafranca
barrier ("Sistema Aperto", a fixed toll for the Villafranca exit) isn't
modelled.
"""
import json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import es_stretch, m6toll  # noqa: E402

CLASSES = ["A", "B", "3", "4", "5"]
ROADS = {
    "A18": {
        "title": "A18 Messina-Catania", "min_lat": 37.4,
        "order": ["Messina Sud", "Roccalumera", "Taormina", "Giardini Naxos", "Fiumefreddo", "Giarre", "Acireale", "Catania Nord"],
        "keys": {"Roccalumera": "roccalumera", "Taormina": "taormina", "Giardini Naxos": "giardini naxos", "Fiumefreddo": "fiumefreddo",
                 "Giarre": "giarre", "Acireale": "acireale"},
    },
    "A20": {
        "title": "A20 Messina-Palermo", "min_lat": 37.5,
        "order": ["Messina Nord", "Rometta", "Milazzo", "Barcellona", "Falcone", "Patti", "Brolo", "Rocca di Caprileone",
                  "S.Agata di Militello", "S.Stefano di Camastra", "Tusa", "Castelbuono", "Cefalu'", "Buonfornello"],
        "keys": {"Rometta": "rometta", "Milazzo": "milazzo", "Barcellona": "barcellona", "Falcone": "falcone", "Patti": "patti",
                 "Brolo": "brolo", "Rocca di Caprileone": "capri ?leone", "S.Agata di Militello": "sant agata", "S.Stefano di Camastra": "santo stefano",
                 "Tusa": "tusa", "Castelbuono": "castelbuono", "Cefalu'": "cefalu"},
    },
}
ROW = re.compile(r"^(?:(\S.*?)\s+(\d{3})\s+)?\s*(\S.*?)\s+(\d{3})\s+" + r"\s+".join([r"(\d+,\d\d)"] * 5) + r"\s*$")


def pairs(text, order):
    """{(entry, exit): {class: euros}} from the table; the date it's in force from."""
    m = re.search(r"TARIFFE IN VIGORE DAL\b.{0,200}?\b1\s+gennaio\s+(\d{4})", text, re.I | re.S)
    if not m:
        sys.exit("CAS: the table's date isn't stated as 1 January <year>")
    out, entry = {}, None
    for line in text.splitlines():
        r = ROW.match(line.strip())
        if not r:
            continue
        if r.group(1):
            entry = r.group(1).strip()
        out[(entry, r.group(3).strip())] = {c: float(v.replace(",", ".")) for c, v in zip(CLASSES, r.groups()[4:])}
    names = {x for k in out for x in k}
    n = len(order)
    if names != set(order) or len(out) != n * (n - 1) // 2:
        sys.exit(f"CAS: {len(out)} pairs; stations not in the order: {sorted(names ^ set(order))}")
    return out, m.group(1)


def plazas(osm):
    """Centres of the clusters of two or more toll booths within 200 m."""
    cl = []
    for p, _ in es_stretch.booths(osm):
        for c in cl:
            if m6toll.km(p, c[0]) < 0.2:
                c.append(p)
                break
        else:
            cl.append([p])
    return [(sum(q[0] for q in c) / len(c), sum(q[1] for q in c) / len(c)) for c in cl if len(c) >= 2]


def join(ls):
    """The pieces joined where one runs on into another: each other's
    nearest (the one's end to the other's start, within 1.2 km, heading
    within 60 degrees). OSM breaks carriageways at junctions and bridges,
    and leaves the ref off some ways (the A18's northbound carriageway near
    Messina)."""
    ls = list(ls)

    def head(l, end):
        cum = m6toll.along(l)
        return m6toll.at(l, cum, cum[-1] if end else 0)[1]

    def gap(a, b):
        d = m6toll.km(a[-1], b[0])
        return d if d < 1.2 and abs((head(a, True) - head(b, False) + 540) % 360 - 180) < 60 else None

    while True:
        for i, a in enumerate(ls):
            nxt = [(gap(a, b), j) for j, b in enumerate(ls) if j != i and gap(a, b) is not None]
            if not nxt:
                continue
            j = min(nxt)[1]
            prv = [(gap(c, ls[j]), k) for k, c in enumerate(ls) if k != j and gap(c, ls[j]) is not None]
            if min(prv)[1] == i:
                ls = [l for k, l in enumerate(ls) if k not in (i, j)] + [a + ls[j]]
                break
        else:
            return ls


def build(road, text, osm):
    cfg = ROADS[road]
    order = cfg["order"]
    pr, year = pairs(text, order)
    ls = join(l for l in es_stretch.lines(osm, [road]) if sum(p[1] for p in l) / len(l) > cfg["min_lat"])
    juncs = es_stretch.signs(osm)
    inner = order[1:-1]
    match = lambda s, w: s in cfg["keys"] and re.search(r"\b" + cfg["keys"][s] + r"\b", w) is not None
    pts = {}
    for line in ls:
        cum = m6toll.along(line)
        got, _ = es_stretch.assign(inner, match, line, cum, juncs)
        for s, x in got.items():
            pts.setdefault(s, []).append(m6toll.at(line, cum, x)[0])
    missing = [s for s in inner if s not in pts]
    if missing:
        sys.exit(f"CAS {road}: {missing} not placed")
    pl = [p for p in plazas(osm) if any(m6toll.project(l, m6toll.along(l), p)[1] < 0.15 for l in ls)]
    mean = lambda ps: (sum(q[0] for q in ps) / len(ps), sum(q[1] for q in ps) / len(ps))
    ends = {}
    for term, near, far in ((order[0], inner[0], inner[-1]), (order[-1], inner[-1], inner[0])):
        a, b = mean(pts[near]), mean(pts[far])
        # Beyond the end station: over 2 km further from the other end than it is.
        cand = [p for p in pl if m6toll.km(p, b) > m6toll.km(a, b) + 2]
        if not cand:
            sys.exit(f"CAS {road}: no toll plaza beyond {near} for {term}")
        ends[term] = min(cand, key=lambda p: m6toll.km(p, a))
    for s, p in ends.items():
        for line in ls:
            cum = m6toll.along(line)
            x, d = m6toll.project(line, cum, p)
            if d < 0.15:
                pts.setdefault(s, []).append(m6toll.at(line, cum, x)[0])
    secs = es_stretch.stretches(ls, pts)
    if len(secs) != 2 * (len(order) - 1):
        sys.exit(f"CAS {road}: {len(secs)} stretches, not {2 * (len(order) - 1)}")

    def price(a, b):
        v = pr.get((a, b)) or pr.get((b, a))
        return v and {c: v[c] for c in ("B", "3", "4", "5")}

    g = pr[(order[0], order[-1])]
    cs = es_stretch.system(cfg["title"], f"Consorzio per le Autostrade Siciliane's tolls in force from 1 January {year}: by entry and exit, either way, VAT included.", secs, price,
                           [{"name": "5", "min_kg": 3501, "min_axles": 5}, {"name": "4", "min_kg": 3501, "min_axles": 4},
                            {"name": "3", "min_kg": 3501, "min_axles": 3}, {"name": "B", "min_kg": 3501}])
    return cs, year, g, len(secs)


def main(fetched, out):
    systems, years, notes, stamp = [], set(), [], ""
    for road in ROADS:
        text = open(os.path.join(fetched, f"it-cas-{road.lower()}.txt"), encoding="utf-8").read()
        osm = json.load(open(os.path.join(fetched, f"it-cas-{road.lower()}-links-osm.json")))
        stamp = max(stamp, osm.get("osm3s", {}).get("timestamp_osm_base", "")[:10])
        cs, year, g, n = build(road, text, osm)
        systems.append(cs)
        years.add(year)
        o = ROADS[road]["order"]
        notes.append(f"{ROADS[road]['title']} ({o[0]} - {o[-1]} class 5 EUR {g['5']:.2f})")
        print(road, n, "stretches,", len(cs["prices"]), "pairs")
    if len(years) != 1:
        sys.exit(f"CAS: tables of different years {sorted(years)}")
    year = years.pop()
    tb = {
        "country": "IT", "currency": "EUR", "valid_from": f"{year}-01-01", "valid_to": f"{year}-12-31", "crossings": True, "osm_extract": stamp,
        "name": "Sicilian motorways A18 and A20 (Consorzio per le Autostrade Siciliane)",
        "law": (f"The Consorzio per le Autostrade Siciliane's tolls in force from 1 January {year} by entry and exit station and class (A, B by height for two axles; 3, 4, 5 by axles), VAT included, either way: "
                + "; ".join(notes) + ". "
                "Stations: each carriageway's stretch between two consecutive entries/exits; the terminal barriers at OpenStreetMap's toll plazas (clusters of toll booths) beyond the end stations, the others at the junctions whose exits are signposted to them. "
                "The A20's Villafranca barrier (an open-system fixed toll for the Villafranca exit) isn't modelled."),
        "sources": [{"title": f"Consorzio per le Autostrade Siciliane: tariffe pedaggio in vigore dal 1 gennaio {year}, A18 Messina-Catania", "url": "https://www.autostradesiciliane.it/files/upload/PortaleNews/allegati/a18%20tariffe%201%20gen%202026.pdf"},
                    {"title": f"Consorzio per le Autostrade Siciliane: tariffe pedaggio in vigore dal 1 gennaio {year}, A20 Messina-Palermo", "url": "https://www.autostradesiciliane.it/files/upload/PortaleNews/allegati/a20%20tariffe%201%20gen%202026.pdf"},
                    {"title": "OpenStreetMap (Overpass API): A18 and A20 carriageways, junctions, signposted links and toll booths", "url": "https://www.openstreetmap.org/"}],
        "vehicles": "Classes B (two axles), 3, 4 and 5 (five axles or more)", "min_kg": 3501,
        "tolled_roads": "A18 Messina Sud - Catania Nord and A20 Messina Nord - Buonfornello.",
        "closed_systems": systems, "rows": [],
    }
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"it-cas-{year}-01-01.json")
    json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
    print(path)


if __name__ == "__main__":
    main(*sys.argv[1:])
