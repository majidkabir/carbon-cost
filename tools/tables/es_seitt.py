"""Builds the Spanish SEITT toll motorway table (AP-36, AP-41, AP-7
Cartagena–Vera) from SEITT's 2026 tariff PDFs
(fetch.py's es-seitt-*.pdf, read as pdftotext -bbox word boxes) and the
toll booths in OpenStreetMap (the workflow's es-osm.geojsonseq, from
Geofabrik's Madrid, Castilla-La Mancha, Murcia and Andalucía extracts;
its date in es-osm-timestamp.txt).

Usage: python3 es_seitt.py fetched/ out-dir -> out-dir/es-seitt-<year>-01-01.json

Each PDF prints, for Ligeros, Pesados 1 and Pesados 2, a square matrix:
a row and a column per station (in the same order), each column split
into Telepeaje (toll tag) and Efectivo/Tarjeta (cash or card). A price
on the diagonal is an open plaza's (R-2's Aeropuerto, M-12's Barajas); a
"-" or blank is no trip; "0,00 (*)" is free. Pesados 1: trucks of two or
three axles (with a one-axle trailer); Pesados 2: four axles or more
(each PDF's notes). Rows are the entry, columns the exit: priced per
direction ("directed"). Prices include 21% IVA, divided out. Cash prices are
the toll, tag prices the ETC prices; from 00:00 to 06:00 the motorways
are free (each PDF's heading).

OSM's Spanish toll booths and junctions carry no names, so a station is
placed at the toll booths whose nearby links are signposted to it (see
place()); stations that can't be told apart aren't placed, nor their
prices (a trip from or to one is priced from the next placed station).
"""
import json, math, os, re, sys, unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tr_matrix  # noqa: E402  (pdftotext -bbox words and lines)

MOTORWAYS = [("ap36", "AP-36 Ocaña – La Roda"), ("ap41", "AP-41 Madrid – Toledo"), ("ap7cv", "AP-7 Cartagena – Vera")]
# The Madrid radials (R-2, R-3, R-4, R-5) and M-12 aren't read: their
# stations are named after the roads they meet ("M-45", "Conexión A-3"),
# which the signage of OSM's links names all along them, so most can't
# be placed.
IVA = 1.21
# Each year's tariffs: the acts behind them.
ACUERDO = {"2025": "Acuerdo del Consejo de Ministros de 3 de diciembre de 2024 (BOE 18/12/2024), SEITT's tariff regime for 2025-2032",
           "2026": "Acuerdo del Consejo de Ministros de 9 de diciembre de 2025 (BOE 18/12/2025) and the Secretaría General de Transporte Terrestre's resolution of 10 December 2025"}
GROUPS = [{"name": "Pesados 1", "min_kg": 3501, "max_axles": 3}, {"name": "Pesados 2", "min_kg": 3501, "min_axles": 4}]
PRICE = re.compile(r"^\d+,\d\d$")


def km(a, b):
    return math.hypot((a[0] - b[0]) * 111.2 * math.cos(math.radians(a[1])), (a[1] - b[1]) * 111.2)


def plain(s):
    s = unicodedata.normalize("NFD", s.lower())
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in s if unicodedata.category(c) != "Mn"))


def road_of(name):
    return re.match(r"([A-Z]+-\d+)", name).group(1)


def load_plazas(path):
    """Toll booth clusters (within 400 m), each with the words of the
    motorway and link ways within 400 m (destination, destination:ref,
    exit_to, name, ref), the refs of the motorways within 800 m, and
    whether it stands on a motorway (a main-line plaza) or a link."""
    booths, ways = [], []
    for line in open(path, encoding="utf-8"):
        f = json.loads(line.strip("\x1e"))
        p, g = f["properties"], f["geometry"]
        c = g["coordinates"]
        if p.get("barrier") == "toll_booth" or p.get("highway") == "toll_gantry":
            while isinstance(c[0], list):
                c = c[0]
            booths.append(tuple(c))
        elif p.get("highway") in ("motorway", "motorway_link") and g["type"] == "LineString":
            txt = " ".join(plain_words(str(p.get(k, ""))) for k in ("destination", "destination:ref", "exit_to", "name", "ref"))
            refs = {re.sub(r"\s", "", x).upper() for k in ("ref", "destination:ref") for x in str(p.get(k, "")).split(";") if x}
            own = {re.sub(r"\s", "", x).upper() for x in str(p.get("ref", "")).split(";") if x} if p["highway"] == "motorway" else set()
            ways.append(([tuple(q) for q in c], txt, refs, p["highway"], own))
    grid = {}
    for i, w in enumerate(ways):
        for q in w[0]:
            grid.setdefault((round(q[0] * 50), round(q[1] * 50)), set()).add(i)

    def near(pt, r):
        gx, gy, out = round(pt[0] * 50), round(pt[1] * 50), set()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for i in grid.get((gx + dx, gy + dy), ()):
                    if any(km(q, pt) < r for q in ways[i][0]):
                        out.add(i)
        return out
    cl = []
    for b in sorted(booths):
        for c in cl:
            if km(b, c[0]) < 0.4:
                c.append(b)
                break
        else:
            cl.append([b])
    out = []
    for c in cl:
        ctr = (sum(x[0] for x in c) / len(c), sum(x[1] for x in c) / len(c))
        n4, n8 = sorted(near(ctr, 0.4)), near(ctr, 0.8)
        out.append({"booths": c, "at": ctr, "words": " ".join(ways[i][1] for i in n4),
                    "refs": set().union(*[ways[i][2] for i in n4]), "roads": set().union(*[ways[i][4] for i in n8]),
                    "main": any(ways[i][3] == "motorway" and any(km(q, ctr) < 0.08 for q in ways[i][0]) for i in n4)})
    return out


def plain_words(s):
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


STOP = {"troncal", "lateral", "peaje", "conexion", "de", "la", "del", "el", "sagra", "cm"}


def matches(station, pl):
    """A plaza matches a station when the words and road refs of one of
    the station's names ("Madrid / M-40" is two) all appear on the ways
    by it."""
    for alt in [a.strip() for a in station.split("/") if a.strip()]:
        toks = [t for t in re.findall(r"[a-z0-9\-]+", plain_words(alt)) if t not in STOP]
        refs = [t.upper().replace("-", "") for t in toks if re.match(r"^[a-z]{1,2}-?\d+$", t)]
        words = [t for t in toks if t.upper().replace("-", "") not in refs and len(t) >= 3]
        if (refs or words) and all(any(r == q.replace("-", "") for q in pl["refs"]) for r in refs) and all(w in pl["words"] for w in words):
            return True
    return False


def place(rows, road, plazas):
    """Stations (in order along the motorway) to their plaza: of the plazas
    by the motorway (its ref on a motorway within 800 m), those matching
    the station's name (a "Troncal" station's on the motorway, a
    "Lateral" one's on a link); a station with one candidate takes it and
    it is taken from the others, until none is left with exactly one
    (candidates within 1 km count as one place). A placed station must
    lie on the way between its placed neighbours (at most 30% and 3 km
    longer than the straight line), else it is dropped. A "Lateral"
    station with a "Troncal" one of the same name is left out."""
    on = [p for p in plazas if road in p["roads"]]
    # A lateral (ramp) plaza within 1 km of its main-line one can't be told
    # apart from it along a route: only the main line's is kept.
    rows = [r for r in rows if not (r.startswith("Lateral ") and "Troncal " + r[8:] in rows)]
    cand = {}
    for r in rows:
        cs = [p for p in on if matches(r, p) and (not r.startswith("Troncal") or p["main"]) and (not r.startswith("Lateral") or not p["main"])]
        cand[r] = cs
    placed, taken = {}, set()

    def places(cs):
        groups = []
        for p in cs:
            for g in groups:
                if km(p["at"], g[0]["at"]) < 1:
                    g.append(p)
                    break
            else:
                groups.append([p])
        return groups
    changed = True
    while changed:
        changed = False
        for r in rows:
            if r in placed:
                continue
            gs = places([p for p in cand[r] if id(p) not in taken])
            if len(gs) == 1:
                placed[r] = gs[0]
                taken |= {id(p) for p in gs[0]}
                changed = True
    while True:
        order = [r for r in rows if r in placed]
        bad = None
        for i in range(1, len(order) - 1):
            a, x, b = (placed[order[j]][0]["at"] for j in (i - 1, i, i + 1))
            if km(a, x) + km(x, b) > km(a, b) * 1.3 + 3:
                bad = order[i]
                break
        if not bad:
            break
        del placed[bad]
    return {r: [q for p in g for q in p["booths"]] for r, g in placed.items()}


def section(ws):
    """One vehicle class's matrix: (rows, {(row, col): (tag, cash)})."""
    ls = tr_matrix.lines(ws)
    tag = sorted(w for w in ws if w[4] == "Telepeaje")
    cash = sorted(w for w in ws if w[4] == "Efectivo/")
    if not tag or len(tag) != len(cash):
        sys.exit(f"{len(tag)} Telepeaje and {len(cash)} Efectivo columns")
    sub = []  # (x centre, column, kind)
    for i, (t, c) in enumerate(zip(tag, cash)):
        sub += [((t[0] + t[2]) / 2, i, 0), ((c[0] + c[2]) / 2, i, 1)]
    top = max(w[3] for w in ws if w[4] == "Tarjeta")
    left = min(w[0] for w in tag) - 5
    rows, cells = [], {}
    for y, l in ls:
        if y <= top + 1:
            continue
        label = " ".join(w[4] for w in l if w[2] < left)
        vals = [w for w in l if w[0] >= left]
        if not label:
            continue
        if not any(PRICE.match(w[4]) or w[4] == "-" for w in vals):
            if rows:
                break  # the notes under the matrix
            continue
        r = len(rows)
        rows.append(label)
        for i, w in enumerate(vals):
            if not PRICE.match(w[4]):
                continue
            x = (w[0] + w[2]) / 2
            _, col, kind = min(sub, key=lambda s: abs(s[0] - x))
            cells.setdefault((r, col), [None, None])[kind] = float(w[4].replace(",", "."))
    if len(rows) != len(tag):
        sys.exit(f"{len(rows)} rows for {len(tag)} columns: {rows}")
    return rows, cells


def read(path):
    """{class: (rows, cells)} for Ligeros, Pesados 1, Pesados 2."""
    out = {}
    for ws in tr_matrix.words(path):
        heads = []
        for y, l in tr_matrix.lines(ws):
            if l[0][4] == "Vehículos":
                n = []
                for x in l[1:]:
                    if x[4] not in ("Ligeros", "Pesados", "1", "2"):
                        break
                    n.append(x[4])
                if " ".join(n) in ("Ligeros", "Pesados 1", "Pesados 2"):
                    heads.append((l[0][1], " ".join(n)))
        heads.sort()
        for i, (y, name) in enumerate(heads):
            notes = [l[0][1] for _, l in tr_matrix.lines(ws) if l[0][1] > y + 20 and (l[0][4] == "Ligeros:" or [w[4] for w in l[:2]] == ["Las", "presentes"])]
            y2 = heads[i + 1][0] if i + 1 < len(heads) else min(notes + [1e9])
            part = [w for w in ws if y - 2 <= w[1] < y2 - 2 and not (w[4] == "(*)")]
            cls = name
            out[cls] = section(part)
    return out


def main(fetched, out):
    plazas = load_plazas(os.path.join(fetched, "es-osm.geojsonseq"))
    systems, year, missing = [], None, []
    # A past year's tariffs (tools/history/build_es.py lists the ones it
    # has none of in absent.txt).
    absent = set(open(os.path.join(fetched, "absent.txt")).read().split()) if os.path.exists(os.path.join(fetched, "absent.txt")) else set()
    for sid, name in MOTORWAYS:
        if f"es-seitt-{sid}" in absent:
            print(f"es-seitt-{sid}: no tariff of that year")
            continue
        path = os.path.join(fetched, f"es-seitt-{sid}.bbox.html")
        text = open(os.path.join(fetched, f"es-seitt-{sid}.txt"), encoding="utf-8").read()
        y = re.search(r"Peajes? (\d{4})", text).group(1)
        year = max(year or y, y)
        if "De 00:00 a 06:00 h gratuito" not in text or "21 % IVA incluido" not in text:
            sys.exit(f"{sid}: the heading no longer says free 00:00–06:00 or 21% IVA")
        m = read(path)
        if set(m) != {"Ligeros", "Pesados 1", "Pesados 2"}:
            sys.exit(f"{sid}: classes {list(m)}")
        rows = m["Pesados 1"][0]
        if m["Pesados 2"][0] != rows:
            sys.exit(f"{sid}: Pesados 1 and 2 list other stations")
        placed = place(rows, road_of(name), plazas)
        miss = [r for r in rows if r not in placed]
        missing += [f"{name}: {r}" for r in miss]
        prices, etc = {}, {}
        for cls in ("Pesados 1", "Pesados 2"):
            _, cells = m[cls]
            for (r, c), (tag, cash) in cells.items():
                a, b = rows[r], rows[c]
                if a not in placed or b not in placed:
                    continue
                if cash is not None:
                    prices.setdefault(f"{a}|{b}", {})[cls] = round(cash / IVA, 4)
                if tag is not None:
                    etc.setdefault(f"{a}|{b}", {})[cls] = round(tag / IVA, 4)
        stations = [{"name": r, "points": [{"name": "booth", "lat": round(c[1], 6), "lon": round(c[0], 6)} for c in placed[r]]} for r in rows if r in placed]
        print(f"{name}: {len(stations)}/{len(rows)} stations placed, {len(prices)} prices" + (f"; unplaced {miss}" if miss else ""))
        if len(stations) >= 3:
            systems.append({"name": name, "law": f"SEITT tariff {y} ({sid}), cash and tag prices including 21% IVA, here excluding it; free 00:00–06:00",
                            "free_hours": ["00:00", "05:59"], "directed": True, "groups": GROUPS, "stations": stations, "prices": prices, "etc_prices": etc})
    osm = open(os.path.join(fetched, "es-osm-timestamp.txt")).read().strip()[:10]
    tb = {
        "country": "ES", "currency": "EUR", "valid_from": f"{year}-01-01", "valid_to": f"{year}-12-31",
        "osm_extract": osm,
        "name": "Spanish state toll motorways (SEITT)",
        "law": f"{ACUERDO.get(year, ACUERDO['2026'])}: SEITT's {year} tariffs by entry and exit, Pesados 1 (two or three axles) and Pesados 2 (four or more), cash prices, tag prices for trucks paying by Vía-T (etc), excluding 21% IVA; free from 00:00 to 06:00. Stations placed at OpenStreetMap's toll booths of their name (extract of {osm}); {len(missing)} stations without one aren't priced. Only SEITT's AP-36, AP-41 and AP-7 Cartagena–Vera (not the Madrid radials or M-12); the concessions (AP-6, AP-9, AP-46, AP-51, AP-53, AP-61, AP-66, AP-68, AP-71, AP-7 Málaga–Guadiaro and Alicante–Cartagena) aren't included.",
        "sources": []
                   + [{"title": s["what"], "url": s["url"]} for s in json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources.json")))["sources"] if s["id"] in {f"es-seitt-{k}" for k, _ in MOTORWAYS}]
                   + [{"title": "OpenStreetMap (Geofabrik extracts), toll booths", "url": "https://download.geofabrik.de/europe/spain.html"}],
        "vehicles": "Trucks over 3.5 t (Pesados 1 and 2)",
        "min_kg": 3501,
        "tolled_roads": ", ".join(n for _, n in MOTORWAYS) + ".",
        "closed_systems": systems,
        "rows": [],
    }
    print(f"unplaced: {missing}")
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"es-seitt-{year}-01-01.json")
    json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
    print(path)


if __name__ == "__main__":
    main(*sys.argv[1:])
