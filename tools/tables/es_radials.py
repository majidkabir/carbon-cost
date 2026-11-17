"""Builds the Madrid radials' toll table (SEITT: R-2, R-3, R-4, R-5) from
SEITT's tariff PDFs (fetch.py's es-seitt-<r>.bbox.html, read by
es_seitt.read) and OSM (es-radials-links-osm.json).

Usage: python3 es_radials.py fetched/ out-dir -> out-dir/es-radials-<year>-01-01.json

Prices as es_seitt.py: rows are entries and columns exits (directed),
Pesados 1 and 2, cash prices (tag prices with `etc`), excluding 21% IVA,
free from 00:00 to 06:00. A price on the diagonal is an open plaza's
(R-2's Aeropuerto and Alcobendas, and M-12's): those aren't built here.

Stations are named after the places and roads their exits lead to
("M-45", "M-208 Mejorada/Velilla"), so each is placed at the junction whose
exit link is signposted to one of those words, keeping the tariff's order
along the motorway (es_stretch.assign); the first and last stations, where
no junction is signposted to them, at the carriageways' ends. A station no
junction can be found for is left out, a trip from or to it priced from
the next station placed (each such station named in the law). The system's
stations are the carriageways' stretches between consecutive placed
entries/exits (es_stretch.stretches).
"""
import json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import es_seitt, es_stretch, m6toll  # noqa: E402

IVA = 1.21
RADIALS = [("r2", "R-2", "R-2 Madrid – Guadalajara"), ("r3", "R-3", "R-3 Madrid – Arganda"), ("r4", "R-4", "R-4 Madrid – Ocaña"),
           ("r5", "R-5", "R-5 Madrid – Navalcarnero")]
GROUPS = es_seitt.GROUPS
# Signposted words beyond the station's own name.
EXTRA = {"NII-Taracena": ["n ii", "taracena", "a 2"], "Alcala": ["alcala"], "Conexión A-3": ["a 3"], "Conexión A-5": ["a 5"],
         "Ocaña / A-40": ["ocana", "a 40"], "AP-41 Madrid-Toledo": ["ap 41"], "Pinto-Parla": ["pinto", "parla"],
         "Villaseca Sagra (CM 4001)": ["villaseca", "cm 4001"]}


def words(station):
    """The words a junction signposted to the station shows: road refs
    ("m 45") and place names, from the station's name split at "/", "-"
    between names, and parentheses."""
    out = set(EXTRA.get(station, []))
    for part in re.split(r"/|\(|\)", station):
        p = es_stretch.plain(part)
        if not p or p in ("conexion", "madrid"):
            continue
        refs = re.findall(r"\b([a-z]{1,2}) (\d{2,4})\b", p)
        for a, n in refs:
            out.add(f"{a} {n}")
        rest = re.sub(r"\b[a-z]{1,2} \d{2,4}\b", " ", p).strip()
        for name in re.split(r"\s{2,}", rest):
            if len(name) > 3 and name not in ("norte", "sur", "conexion"):
                out.add(name)
    return sorted(out)


def build(fetched, sid, ref, name, osm, juncs):
    text = open(os.path.join(fetched, f"es-seitt-{sid}.txt"), encoding="utf-8").read()
    if "De 00:00 a 06:00 h gratuito" not in text or "21 % IVA incluido" not in text:
        sys.exit(f"{sid}: the heading no longer says free 00:00–06:00 or 21% IVA")
    year = re.search(r"Peajes? (\d{4})", text).group(1)
    m = es_seitt.read(os.path.join(fetched, f"es-seitt-{sid}.bbox.html"))
    rows = m["Pesados 1"][0]
    if m["Pesados 2"][0] != rows:
        sys.exit(f"{sid}: Pesados 1 and 2 list other stations")
    cells = {cls: m[cls][1] for cls in ("Pesados 1", "Pesados 2")}
    # Open plazas (a diagonal price and no other) are left out.
    opens = [r for i, r in enumerate(rows) if (i, i) in cells["Pesados 2"] and not any((i, j) in cells["Pesados 2"] for j in range(len(rows)) if j != i)]
    order = [r for r in rows if r not in opens]
    keys = {s: words(s) for s in order}
    match = lambda s, w: any(re.search(r"\b" + re.escape(k) + r"\b", w) for k in keys[s])
    ls = es_stretch.lines(osm, [ref])
    pts, placed = {}, set()
    for line in ls:
        cum = m6toll.along(line)
        if cum[-1] < 5:
            continue
        got, seq = es_stretch.assign(order, match, line, cum, juncs)
        if len(got) < 2:
            continue
        first, last = seq[0], seq[-1]
        # The motorway's ends: the line's ends, where they are the road's own
        # (no other piece runs on) and the first or last station isn't signposted.
        if first not in got and min(got.values()) > 0.5 and es_stretch.open_end(line[0], m6toll.at(line, cum, 0)[1], ls, line):
            got[first] = 0.0
        if last not in got and max(got.values()) < cum[-1] - 0.5 and es_stretch.open_end(line[-1], m6toll.at(line, cum, cum[-1])[1], ls, line):
            got[last] = cum[-1]
        for s, x in got.items():
            pts.setdefault(s, []).append(m6toll.at(line, cum, x)[0])
            placed.add(s)
    secs = es_stretch.stretches(ls, pts)
    miss = [r for r in order if r not in placed]
    pos = [r for r in order if r in placed]

    def price_of(table, a, b, cls):
        """Price from a to b; a station left out takes the next one placed's place."""
        i, j = rows.index(a), rows.index(b)
        v = table[cls].get((i, j))
        return v

    prices, etc = {}, {}

    def price(kind):
        def f(a, b):
            out = {}
            for cls in ("Pesados 1", "Pesados 2"):
                v = cells[cls].get((rows.index(a), rows.index(b)))
                if v and v[kind] is not None:
                    out[cls] = round(v[kind] / IVA, 4)
            return out or None
        return f

    cs = es_stretch.system(name, f"SEITT tariff {year} ({sid}), cash prices (tag prices with etc) including 21% IVA, here excluding it; free 00:00–06:00"
                           + (f"; stations not placed (priced from the next one placed): {', '.join(miss)}" if miss else "")
                           + (f"; open plazas not built: {', '.join(opens)}" if opens else ""),
                           secs, price(1), GROUPS)
    cs["etc_prices"] = es_stretch.system(name, "", secs, price(0), GROUPS)["prices"]
    cs["free_hours"] = ["00:00", "05:59"]
    print(f"{name}: {len(pos)}/{len(order)} stations placed, {len(secs)} stretches, {len(cs['prices'])} pairs" + (f"; unplaced {miss}" if miss else ""))
    return cs, year, miss, opens


def main(fetched, out):
    osm = json.load(open(os.path.join(fetched, "es-radials-links-osm.json")))
    stamp = osm.get("osm3s", {}).get("timestamp_osm_base", "")[:10]
    juncs = es_stretch.signs(osm)
    systems, years, missing, opens = [], set(), [], []
    for sid, ref, name in RADIALS:
        cs, y, miss, op = build(fetched, sid, ref, name, osm, juncs)
        systems.append(cs)
        years.add(y)
        missing += [f"{name}: {m}" for m in miss]
        opens += [f"{name}: {o}" for o in op]
    year = max(years)
    srcs = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources.json")))["sources"]
    tb = {
        "country": "ES", "currency": "EUR", "valid_from": f"{year}-01-01", "valid_to": f"{year}-12-31", "crossings": True, "osm_extract": stamp,
        "name": "Madrid radials R-2, R-3, R-4 and R-5 (SEITT)",
        "law": (f"{es_seitt.ACUERDO.get(year, es_seitt.ACUERDO['2026'])}: SEITT's {year} tariffs by entry and exit, Pesados 1 (two or three axles) and Pesados 2 (four or more), "
                "cash prices, tag prices for trucks paying by Vía-T (etc), excluding 21% IVA; free from 00:00 to 06:00. Stations: each carriageway's stretch between two consecutive entries/exits, "
                "the entries/exits placed at the OpenStreetMap junctions whose exits are signposted to the places and roads they're named after, in the tariff's order"
                + (f"; not placed (a trip from or to one priced from the next placed station): {'; '.join(missing)}" if missing else "")
                + (f"; open plazas not built: {'; '.join(opens)}" if opens else "") + "."),
        "sources": [{"title": s["what"], "url": s["url"]} for s in srcs if s["id"] in {f"es-seitt-{k}" for k, _, _ in RADIALS}]
                   + [{"title": "OpenStreetMap (Overpass API): the radials' carriageways, junctions and signposted links", "url": "https://www.openstreetmap.org/"}],
        "vehicles": "Trucks over 3.5 t (Pesados 1 and 2)", "min_kg": 3501,
        "tolled_roads": ", ".join(n for _, _, n in RADIALS) + ".",
        "closed_systems": systems, "rows": [],
    }
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"es-radials-{year}-01-01.json")
    json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
    print(path)


if __name__ == "__main__":
    main(*sys.argv[1:])
