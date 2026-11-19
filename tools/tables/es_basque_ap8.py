"""Builds the Basque AP-8/AP-1 tolls (Interbiak and Bidegi) from Bidegi's
2026 tariff sheet (fetch.py's es-bidegi-ap8-2026.bbox.html, pdftotext
-bbox words) and OSM (es-basque-osm.json with es-basque-links-osm.json):
two closed systems by entry and exit.

Usage: python3 es_basque_ap8.py fetched/ out-dir -> out-dir/es-basque-ap8-2026-01-01.json

The sheet's first matrix ("AP-1 / AP-8"): the AP-8 from Bilbao's western
access to Zarautz's main plaza (towards Donostia, Astigarraga and Hernani)
and the AP-1 from its AP-8 junction to Etxabarri-Ibiña (Vitoria-Gasteiz);
a station per row with three sub-rows (Arinak/Ligeros, Astun.1/Pes.1,
Astun.2/Pes.2), the columns in the same order. Its second matrix: the AP-8
from Donostia's eastern plaza (Donostia SS E, Hernani, Astigarraga,
Lasarte) to Behobia, by entry row and exit column. Prices include 21% VAT
(BEZa/IVA barne), divided out; either way where only one way is printed.
Pesados 1 and 2 as the Spanish motorways' classes (the sheet's Astun.1
and Astun.2). The AP-636's sections: toll points (see ap636). Not built:
the sheet's single prices to Donostia's exits from Zarautz E and Orio,
Oñaurre (a tag-only price).

Stations: placed at the junctions whose exits are signposted to them, in
the matrix's order along each carriageway (es_stretch.assign), the
plazas without an exit of their own (Bilbao's western access, Zarautz's
main plaza, Donostia's eastern plaza) at the toll booths on the
carriageway, the roads' ends (Etxabarri-Ibiña, Behobia) at the
carriageways' ends; a station not found is left out, a trip from or to it
priced from the next one. The systems' stations are each carriageway's
stretches between consecutive entries/exits (es_stretch.stretches).
"""
import json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import es_stretch, m6toll, tr_matrix  # noqa: E402

VAT = 1.21
PRICE = re.compile(r"^\d+,\d\d$")
MAIN = ["Acceso Oeste (Bilbao)", "Amorebieta-Etxano", "Iurreta", "Abadiño", "Ermua", "Eibar", "Bergara I/N", "Bergara H/S",
        "Arrasate-Mondragon", "Eskoriatza", "Luko", "Etxabarri-Ibiña (Vitoria-Gasteiz)", "Elgoibar", "Itziar", "Zestoa-Zumaia",
        "Zarautz M/O", "Zarautz nagusia (Donostia, Astigarraga, Hernani)"]
# The words each name has in the sheet's row labels (to check the order).
LABEL = ["Acceso Oeste", "Amorebieta", "Iurreta", "Abadiño", "Ermua", "Eibar", "Bergara I/N", "Bergara H/S", "Arrasate", "Eskoriatza",
         "Luko", "Etxabarri", "Elgoibar", "Itziar", "Zestoa-Zumaia", "Zarautz M/O", "Zarautz nagusia"]
EAST_ROWS = ["Donostia - SS. E", "Oiartzun", "Irun Ventas"]
EAST_COLS = ["Oiartzun", "Irun M/O", "Oñaurre", "Behobia"]
EAST = ["Donostia SS E (Hernani, Astigarraga, Lasarte)", "Oiartzun", "Irun M/O", "Irun Ventas", "Oñaurre", "Behobia"]
# Signposted words per station (lower case, accents dropped).
SIGN = {"Amorebieta-Etxano": ["amorebieta"], "Iurreta": ["iurreta"], "Abadiño": ["abadino"], "Ermua": ["ermua"], "Eibar": ["eibar soraluze"],
        "Bergara I/N": ["elgeta"], "Bergara H/S": ["bergara hegoa", "hegoa"], "Arrasate-Mondragon": ["arrasate"], "Eskoriatza": ["eskoriatza"],
        "Luko": ["luko"], "Elgoibar": ["elgoibar"], "Itziar": ["itziar"], "Zestoa-Zumaia": ["zestoa", "zumaia"], "Zarautz M/O": ["zarautz"],
        "Oiartzun": ["oiartzun"], "Irun M/O": ["hondarribia"], "Irun Ventas": ["irun"], "Oñaurre": ["onaurre"]}


def clusters(xs, gap=12):
    xs = sorted(xs)
    out = [[xs[0]]]
    for x in xs[1:]:
        if x - out[-1][-1] > gap:
            out.append([x])
        else:
            out[-1].append(x)
    return [sum(c) / len(c) for c in out]


def sub_rows(ls):
    """[(y, words, class)] of the lines labelled Ligeros / Pes.1 / Pes.2."""
    out = []
    for y, l in ls:
        lab = [w[4] for w in l if 130 < w[0] < 200]
        cls = "L" if "Ligeros" in lab else "P1" if "Pes.1" in lab else "P2" if "Pes.2" in lab else None
        if cls:
            out.append((y, l, cls))
    return out


def matrices(path):
    ws = tr_matrix.words(path)[0]
    ls = tr_matrix.lines(ws)
    hdr = [y for y, l in ls if any(w[4] == "AP-1" and w[0] < 120 for w in l)]
    if len(hdr) != 2:
        sys.exit(f"AP-8: {len(hdr)} 'AP-1 / AP-8' headings, not 2")
    main = sub_rows([(y, l) for y, l in ls if hdr[0] < y < hdr[1]])
    if [c for _, _, c in main] != ["L", "P1", "P2"] * len(MAIN):
        sys.exit(f"AP-8: the first matrix has {len(main)} sub-rows, not 3 x {len(MAIN)}")
    cols = clusters([w[2] for _, l, _ in main for w in l if PRICE.match(w[4])])
    if len(cols) != len(MAIN):
        sys.exit(f"AP-8: {len(cols)} price columns, not {len(MAIN)}")
    # The row labels: the words left of the class labels, from each row's first to its last sub-row.
    text = " ".join(w[4] for y, l in ls if hdr[0] < y < hdr[1] for w in l if w[0] < 130)
    pos = [text.find(n) for n in LABEL]
    if -1 in pos or pos != sorted(pos):
        sys.exit(f"AP-8: the first matrix's rows aren't {LABEL}: {text}")
    m = {}
    for i, (y, l, cls) in enumerate(main):
        r = i // 3
        for w in l:
            if PRICE.match(w[4]):
                c = min(range(len(cols)), key=lambda k: abs(cols[k] - w[2]))
                m.setdefault((MAIN[r], MAIN[c]), {})[cls] = float(w[4].replace(",", "."))
    # The second matrix: rows Donostia SS E, Oiartzun, Irun Ventas; columns Oiartzun, Irun M/O, Oñaurre, Behobia.
    east = sub_rows([(y, l) for y, l in ls if y > hdr[1]])
    east = [(y, [w for w in l if w[0] < 400], c) for y, l, c in east]
    if [c for _, _, c in east] != ["L", "P1", "P2"] * 3:
        sys.exit(f"AP-8: the second matrix has {len(east)} sub-rows, not 9")
    ecols = clusters([w[2] for _, l, _ in east for w in l if PRICE.match(w[4])])
    if len(ecols) != 4:
        sys.exit(f"AP-8: the second matrix has {len(ecols)} columns, not 4")
    etext = " ".join(w[4] for y, l in ls if y > hdr[1] for w in l if w[0] < 130)
    if not all(n.split()[0] in etext for n in EAST_ROWS):
        sys.exit(f"AP-8: the second matrix's rows aren't {EAST_ROWS}")
    rows = {0: EAST[0], 1: "Oiartzun", 2: "Irun Ventas"}
    cmap = {0: "Oiartzun", 1: "Irun M/O", 2: "Oñaurre", 3: "Behobia"}
    e = {}
    for i, (y, l, cls) in enumerate(east):
        for w in l:
            if PRICE.match(w[4]):
                c = min(range(4), key=lambda k: abs(ecols[k] - w[2]))
                e.setdefault((rows[i // 3], cmap[c]), {})[cls] = float(w[4].replace(",", "."))
    return m, e


AP8 = ["Amorebieta-Etxano", "Iurreta", "Abadiño", "Ermua", "Eibar", "Elgoibar", "Itziar", "Zestoa-Zumaia", "Zarautz M/O"]
AP1 = ["Bergara I/N", "Bergara H/S", "Arrasate-Mondragon", "Eskoriatza", "Luko"]
AP8E = ["Oiartzun", "Irun M/O", "Irun Ventas", "Oñaurre"]


def plazas(line, cum, booths):
    """[km along line]: the toll plazas on the carriageway, clusters (within
    0.5 km) of three or more toll booths within 200 m of it."""
    on = sorted(x for p, _ in booths for x, d in [m6toll.project(line, cum, p)] if d < 0.2)
    out, cl = [], []
    for x in on + [None]:
        if x is not None and (not cl or x - cl[-1] < 0.5):
            cl.append(x)
            continue
        if len(cl) >= 3:
            out.append(sum(cl) / len(cl))
        cl = [x] if x is not None else []
    return out


def plaza(line, cum, booths, anchor, ahead, window):
    """The plaza nearest after (ahead=True) or before the anchor km within
    the window (km); else, where the carriageway's piece starts (ends)
    within the window, its start (end): OSM's carriageway may stop short."""
    lo, hi = window
    xs = [x for x in plazas(line, cum, booths) if lo < ((x - anchor) if ahead else (anchor - x)) < hi]
    if xs:
        return min(xs, key=lambda x: abs(x - anchor))
    edge = cum[-1] if ahead else 0.0
    return edge if lo < abs(edge - anchor) < hi else None


def place(ls, juncs, booths):
    """{station: [(lon, lat)]} on the AP-8/AP-1 carriageways."""
    match = lambda s, w: s in SIGN and any(re.search(r"\b" + k + r"\b", w) for k in SIGN[s])
    pts = {}
    for line in ls:
        cum = m6toll.along(line)
        got = {}
        for order in (AP8, AP1, AP8E):
            g, seq = es_stretch.assign(order, match, line, cum, juncs)
            if len(g) >= 2:
                fwd = seq[0] == order[0]
                got.update(g)
                h0, h1 = m6toll.at(line, cum, 0)[1], m6toll.at(line, cum, cum[-1])[1]
                if order is AP8:
                    # Bilbao's western access: the AP-8's western end; Zarautz's main plaza: the booths east of Zarautz.
                    west_end = 0.0 if fwd else cum[-1]
                    if es_stretch.open_end(line[0] if fwd else line[-1], h0 if fwd else h1, ls, line):
                        got[MAIN[0]] = west_end
                    z = g.get("Zarautz M/O")
                    if z is not None:
                        x = plaza(line, cum, booths, z, fwd, (0.5, 6.0))
                        if x is not None:
                            got[MAIN[-1]] = x
                if order is AP1:
                    south = cum[-1] if fwd else 0.0
                    if es_stretch.open_end(line[-1] if fwd else line[0], h1 if fwd else h0, ls, line):
                        got[MAIN[11]] = south
                if order is AP8E:
                    o = g.get("Oiartzun")
                    if o is not None:  # Donostia's eastern plaza: before Oiartzun going east
                        x = plaza(line, cum, booths, o, not fwd, (0.1, 4.0))
                        if x is not None:
                            got[EAST[0]] = x
                    end = cum[-1] if fwd else 0.0
                    if es_stretch.open_end(line[-1] if fwd else line[0], h1 if fwd else h0, ls, line):
                        got["Behobia"] = end
        for s, x in got.items():
            pts.setdefault(s, []).append(m6toll.at(line, cum, x)[0])
    return pts


# The AP-636's sections (the sheet's names) and the Bidegi gantry pair in
# OpenStreetMap that is the first on each, going from Beasain to Bergara.
AP636 = [("Beasain - Ormaiztegi", "Beasain"), ("Ormaiztegi - Zumarraga", "Ezkio"), ("Legazpi/Urretxu - Bergara", "Deskarga")]


def ap636(text, osm):
    """[toll point]: each AP-636 section's price at its gantry pair's middle, either way."""
    out = []
    gantries = [e for e in osm["elements"] if e["type"] == "node" and e.get("tags", {}).get("highway") == "toll_gantry" and e["tags"].get("operator") == "Bidegi"]
    for section, gantry in AP636:
        m = re.search(re.escape(section) + r"\s+(\d+,\d\d)\s+(\d+,\d\d)\s+(\d+,\d\d)", text)
        if not m:
            sys.exit(f"AP-636: no prices for {section}")
        g = [e for e in gantries if e["tags"].get("name") == gantry]
        if not 1 <= len(g) <= 2:
            sys.exit(f"AP-636: {len(g)} OSM gantries named {gantry}")
        p1, p2 = (float(m.group(i).replace(",", ".")) for i in (2, 3))
        out.append({"name": f"AP-636 {section} ({gantry} gantry)", "lat": round(sum(e["lat"] for e in g) / len(g), 6), "lon": round(sum(e["lon"] for e in g) / len(g), 6),
                    "rate": 0, "classes": [{"min_kg": 3501, "min_axles": 4, "rate": round(p2 / VAT, 4)}, {"min_kg": 3501, "rate": round(p1 / VAT, 4)}]})
    return out


def main(fetched, out):
    m, e = matrices(os.path.join(fetched, "es-bidegi-ap8-2026.bbox.html"))
    flat = re.sub(r"\s+", " ", open(os.path.join(fetched, "es-bidegi-ap8-2026.txt"), encoding="utf-8").read())
    if "Tarifas vigentes en € a partir de 01.01.2026" not in flat:
        sys.exit("AP-8: the sheet's heading changed")
    if any(m.get((b, a)) != v for (a, b), v in m.items()):
        sys.exit("AP-8: the first matrix isn't symmetric")
    osm = json.load(open(os.path.join(fetched, "es-basque-osm.json")))
    links = json.load(open(os.path.join(fetched, "es-basque-links-osm.json")))
    stamp = osm.get("osm3s", {}).get("timestamp_osm_base", "")[:10]
    allosm = {"elements": osm["elements"] + links["elements"]}
    ls = es_stretch.lines(allosm, ["AP-8", "AP-1"])
    pts = place(ls, es_stretch.signs(allosm), es_stretch.booths(allosm))
    groups = [{"name": "Pesados 2", "min_kg": 3501, "min_axles": 4}, {"name": "Pesados 1", "min_kg": 3501}]
    systems, missing = [], []
    for name, stations, table in (("AP-8/AP-1 Bilbao – Zarautz – Vitoria-Gasteiz", MAIN, m), ("AP-8 Donostia – Behobia", EAST, e)):
        p = {k: v for k, v in pts.items() if k in stations}
        miss = [s for s in stations if s not in p]
        missing += miss
        secs = es_stretch.stretches(ls, p)

        def price(a, b, table=table):
            v = table.get((a, b)) or table.get((b, a))
            return v and {"Pesados 1": round(v["P1"] / VAT, 4), "Pesados 2": round(v["P2"] / VAT, 4)}

        cs = es_stretch.system(name, "Bidegi's 2026 tariff sheet: by entry and exit, either way, excluding 21% VAT"
                               + (f"; stations not placed (priced from the next one): {', '.join(miss)}" if miss else ""), secs, price, groups)
        print(f"{name}: {len(stations) - len(miss)}/{len(stations)} placed, {len(secs)} stretches, {len(cs['prices'])} pairs" + (f"; unplaced {miss}" if miss else ""))
        systems.append(cs)
    points = ap636(open(os.path.join(fetched, "es-bidegi-ap8-2026.txt"), encoding="utf-8").read(), osm)
    p2 = m[(MAIN[0], MAIN[-1])]["P2"]
    tb = {
        "country": "ES", "currency": "EUR", "valid_from": "2026-01-01", "valid_to": "2026-12-31", "crossings": True, "osm_extract": stamp,
        "name": "AP-8, AP-1 and AP-636, Basque Country (Interbiak, Bidegi)",
        "law": ("Bidegi's tariff sheet in force from 1 January 2026 (Interbiak's and Bidegi's AP-8 and AP-1, Pesados 1 and 2, VAT included; "
                f"Pesados 2 from Bilbao's western access to Zarautz's main plaza towards Donostia EUR {p2:.2f}): by entry and exit, either way, excluding 21% VAT. "
                "Stations: each carriageway's stretch between two consecutive entries/exits, placed at the OpenStreetMap junctions whose exits are signposted to them, "
                "Bilbao's western access and Etxabarri-Ibiña at the motorways' ends, Zarautz's main plaza and Donostia's eastern plaza at the toll booths on the carriageway"
                + (f"; not placed (a trip from or to one priced from the next station): {', '.join(missing)}" if missing else "")
                + ". AP-636: each section's price (either way) at the first Bidegi gantry on it going from Beasain (OpenStreetMap's gantries named "
                + ", ".join(g for _, g in AP636) + "); the sheet's Legazpi/Urretxu – Antzuola price by tag isn't modelled (a trip from Legazpi to Antzuola is charged Legazpi – Bergara, one from Antzuola to Bergara nothing). "
                "Not built: the sheet's prices from Zarautz E and Orio to Donostia's exits."),
        "sources": [{"title": "Bidegi: AP-8, AP-1 and AP-636 tariffs 2026", "url": "https://www.bidegi.eus/documents/42696171/0/2026__AP-8_AP-1_AP-636_tarifak.pdf/0c9dbcf3-f3e7-e6f6-709b-8cbb7d9da9d5"},
                    {"title": "OpenStreetMap (Overpass API): the Basque motorways, junctions, signposted links and toll booths", "url": "https://www.openstreetmap.org/"}],
        "vehicles": "Pesados 1: trucks of two or three axles; Pesados 2: four axles or more", "min_kg": 3501,
        "tolled_roads": "AP-8 from Bilbao (western access) to Behobia, AP-1 from Eibar to Vitoria-Gasteiz, AP-636 from Beasain to Bergara.",
        "point_match_km": 0.1, "toll_points": points,
        "closed_systems": systems, "rows": [],
    }
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, "es-basque-ap8-2026-01-01.json")
    json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
    print(path)


if __name__ == "__main__":
    main(*sys.argv[1:])
