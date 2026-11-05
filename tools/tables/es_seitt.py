"""Builds the Spanish SEITT toll motorway table (AP-36, AP-41, AP-7
Cartagena–Vera, R-2, R-3, R-4, R-5, M-12) from SEITT's 2026 tariff PDFs
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
(each PDF's notes). Prices include 21% IVA, divided out. Cash prices are
the toll, tag prices the ETC prices; from 00:00 to 06:00 the motorways
are free (each PDF's heading).

A station is placed at the OSM toll booths named after it (names compared
without case, accents, "Peaje de", or the road numbers the tariff adds),
where a name matches several places the cluster nearest the motorway's
other stations; stations with no booth of their name aren't placed, nor
their prices.
"""
import json, math, os, re, sys, unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tr_matrix  # noqa: E402  (pdftotext -bbox words and lines)

MOTORWAYS = [("ap36", "AP-36 Ocaña – La Roda"), ("ap41", "AP-41 Madrid – Toledo"), ("ap7cv", "AP-7 Cartagena – Vera"),
             ("r2", "R-2 Madrid – Guadalajara"), ("r3", "R-3 Madrid – Arganda"), ("r4", "R-4 Madrid – Ocaña"),
             ("r5", "R-5 Madrid – Navalcarnero"), ("m12", "M-12 Eje Aeropuerto")]
IVA = 1.21
GROUPS = [{"name": "Pesados 1", "min_kg": 3501, "max_axles": 3}, {"name": "Pesados 2", "min_kg": 3501, "min_axles": 4}]
PRICE = re.compile(r"^\d+,\d\d$")


def km(a, b):
    return math.hypot((a[0] - b[0]) * 111.2 * math.cos(math.radians(a[1])), (a[1] - b[1]) * 111.2)


def plain(s):
    s = unicodedata.normalize("NFD", s.lower())
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in s if unicodedata.category(c) != "Mn"))


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
    booths = []
    for line in open(os.path.join(fetched, "es-osm.geojsonseq"), encoding="utf-8"):
        f = json.loads(line.strip("\x1e"))
        p, c = f["properties"], f["geometry"]["coordinates"]
        while isinstance(c[0], list):
            c = c[0]
        if (p.get("barrier") == "toll_booth" or p.get("highway") == "toll_gantry") and p.get("name"):
            booths.append((re.sub(r"^(peaje|peaxe|estaci[oó]n de peaje|barrera de peaje)( de| del)?\s+", "", p["name"], flags=re.I), c))
    systems, year, missing = [], None, []
    for sid, name in MOTORWAYS:
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
        # Place the stations.
        cands = {}
        for r in rows:
            keys = {plain(r)} | {plain(x) for x in re.split(r"\s*/\s*|\s*\(|\)", r) if x.strip()}
            keys |= {plain(re.sub(r"\b(Troncal|Lateral|Peaje|Conexión|Madrid|Mad\.)\b|[A-Z]{1,2}-\d+", "", r))}
            keys.discard("")
            cands[r] = [c for n, c in booths if plain(n) in keys]
        placed = {}
        anchor = [c[0] for c in cands.values() if c]
        for r, cs in cands.items():
            if not cs:
                continue
            # Same-named booths elsewhere: keep those near the motorway's others.
            ctr = (sum(a[0] for a in anchor) / len(anchor), sum(a[1] for a in anchor) / len(anchor))
            best = min(cs, key=lambda c: km(c, ctr))
            near = [c for c in cs if km(c, best) < 2]
            if km(best, ctr) > 80:
                continue
            placed[r] = near
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
        if stations:
            systems.append({"name": name, "law": f"SEITT tariff {y} ({sid}), cash and tag prices including 21% IVA, here excluding it; free 00:00–06:00",
                            "free_hours": ["00:00", "05:59"], "groups": GROUPS, "stations": stations, "prices": prices, "etc_prices": etc})
    osm = open(os.path.join(fetched, "es-osm-timestamp.txt")).read().strip()[:10]
    tb = {
        "country": "ES", "currency": "EUR", "valid_from": f"{year}-01-01", "valid_to": f"{year}-12-31",
        "name": "Spanish state toll motorways (SEITT)",
        "law": f"Acuerdo del Consejo de Ministros de 9 de diciembre de 2025 (BOE 18/12/2025) and the Secretaría General de Transporte Terrestre's resolution of 10 December 2025: SEITT's {year} tariffs by entry and exit, Pesados 1 (two or three axles) and Pesados 2 (four or more), cash prices, tag prices for trucks paying by Vía-T (etc), excluding 21% IVA; free from 00:00 to 06:00. Stations placed at OpenStreetMap's toll booths of their name (extract of {osm}); {len(missing)} stations without one aren't priced. Only SEITT's motorways; the concessions (AP-6, AP-9, AP-46, AP-51, AP-53, AP-61, AP-66, AP-68, AP-71, AP-7 Málaga–Guadiaro and Alicante–Cartagena) aren't included.",
        "sources": []
                   + [{"title": s["what"], "url": s["url"]} for s in json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources.json")))["sources"] if s["id"].startswith("es-seitt-")]
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
