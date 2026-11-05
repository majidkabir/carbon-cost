"""Builds the Turkish motorway and bridge toll table from the General
Directorate of Highways' (Karayolları Genel Müdürlüğü, KGM) 2026 tariffs
(fetch.py's tr-*.pdf: the bridges as pdftotext -layout text, the
motorways' station matrices as pdftotext -bbox word boxes) and
OpenStreetMap (the workflow's tr-osm.geojsonseq, the bridges' ways, and
tr-osm-booths.geojsonseq, toll booths, gantries and motorway junctions,
from Geofabrik's Turkey extract; its date in tr-osm-timestamp.txt).

Usage: python3 tr.py fetched/ out-dir -> out-dir/tr-<date>.json

KGM classes vehicles by axles: 1 two axles under 3.20 m wheelbase, 2 two
axles of 3.20 m or more, 3 three axles, 4 four and five axles, 5 six or
more ("4 VE 5 AKSLI HER TÜRLÜ ARAÇLAR"). Each tariff gives TL "KDV dahil"
(including VAT); prices are divided by 1.20, Turkey's general VAT rate
(KDV Kanunu 28. madde, 20% since 2023-07-10). A two-axle truck is taken
as class 2.

Bridges: the price per passage by class. The 15 Temmuz Şehitler and
Fatih Sultan Mehmet bridges have one tariff, its first price column
("KÖPRÜ GEÇİŞ ÜCRETİ"). The bridges charge both ways (the tariffs say so
for 15 Temmuz, FSM and Yavuz Sultan Selim since 2022; Osmangazi charges
at a toll station for either direction). Each is placed at the middle of
its longest OSM way (the main span) named after it, one point per
carriageway.

Motorways: tr_matrix.py reads each tariff's matrix, a station's six
class rows against a column per station. KGM's own motorways print a
lower triangle, a row's last price (the longest trip's, charged when the
entry is unknown) in its own column; the concessions a full square,
rows the entry and columns the exit, the diagonal that longest price.
The diagonal isn't a trip and isn't kept. A station is placed at the OSM
toll booths named after it ("<name> Gişeleri"; names compared without
case, accents or word order; the part in brackets, a trailing ALIN
(main-line plaza), SGS or booth number dropped; abbreviations expanded by
ALIAS), else the motorway junction of its name; where a name matches
several places, the one that makes the stations' chain along the motorway
shortest, each booth serving one motorway (KGM's first, as SYSTEMS lists
them). A station with no match whose neighbours are placed takes the one
plaza of unnamed booths between them, if there is exactly one (see
between()). A station further than 60 km from the others, or still with
no match, isn't placed, nor are its prices. The 1915 Çanakkale bridge is a station
of Malkara–Çanakkale; its own tariff is checked to equal the Gelibolu
Güney – bridge price. Gebze–Orhangazi–İzmir prints two matrices side by
side (Gebze–Bursa and Bursa–İzmir, read as two systems); its Osmangazi
bridge stations are folded into one priced without the bridge (see
osmangazi()), the bridge charged by its own toll point. The Yavuz Sultan
Selim bridge's toll point is "within" the Kuzey Çevre motorway, whose
tickets include it. Karacabey – Mustafakemalpaşa 1 and 2 aren't placed
(DROP).

The table is valid from the latest date the bridge tariffs give
("01/07/2026 saat 00:00'dan itibaren geçerlidir").
"""
import json, math, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tr_matrix  # noqa: E402

BRIDGES = [("tr-1-15temmuz-fsm", ["15 Temmuz Şehitler Köprüsü", "Fatih Sultan Mehmet Köprüsü"]),
           ("tr-2-osmangazi", ["Osmangazi Köprüsü"]),
           ("tr-3-ysskoprusu", ["Yavuz Sultan Selim Köprüsü"])]
# Motorways priced entry to exit (tr_matrix.py reads each tariff's matrix).
# The 1915 Çanakkale bridge is a station of Malkara–Çanakkale: its own
# tariff is that matrix's Gelibolu Güney – bridge price.
SYSTEMS = [("tr-5-anadoluotoyolucamlica-akinci", "O-4 Anadolu Otoyolu (Çamlıca – Akıncı)"),
           ("tr-6-izmir-cesme", "O-32 İzmir – Çeşme"),
           ("tr-7-izmir-aydin", "O-31 İzmir – Aydın (Işıkkent – Aydın Batı)"),
           ("tr-8-cukurovaotoyoluadana-gaziantep", "O-52/O-53 Çukurova (Adana Doğu – Gaziantep Batı)"),
           ("tr-9-cukurovaotoyolugaziantep-sanliurfa", "O-52 Çukurova (Gaziantep Doğu – Şanlıurfa)"),
           ("tr-10-cukurovaotoyolunigde-mersin-adana", "O-21/O-51 Çukurova (Niğde – Mersin – Adana Batı)"),
           ("tr-11-avrupaotoyolumahmutbey-edirne", "O-3 Avrupa Otoyolu (Mahmutbey – Edirne)"),
           ("tr-14-kmoavrupakinali-odayeri", "O-7 Kuzey Marmara Avrupa (Kınalı – Odayeri)"),
           ("tr-15-kmoanadolukurtkoy-akyazi", "O-7 Kuzey Marmara Anadolu (Kurtköy – Akyazı)"),
           ("tr-16-menemen-aliaga-candarli", "O-33 Menemen – Aliağa – Çandarlı"),
           ("tr-17-ankara-nigde", "O-21 Ankara – Niğde"),
           ("tr-18-malkara-canakkale", "O-6 Malkara – Çanakkale (1915 Çanakkale Köprüsü)"),
           ("tr-19-aydin-denizli", "O-31 Aydın – Denizli"),
           ("tr-20-cesmeli-kizkalesitr", "Çeşmeli – Erdemli – Kızkalesi"),
           ("tr-12-gebze-orhangazi-izmir", "O-5 Gebze – Orhangazi – Bursa (Osmangazi Köprüsü)"),
           ("tr-12-gebze-orhangazi-izmir", "O-5 Bursa – İzmir"),
           ("tr-13-ysskuzeycevreyolu", "O-7 Yavuz Sultan Selim Köprüsü ve Kuzey Çevre Otoyolu")]
# Gebze–Orhangazi–İzmir prints two matrices side by side (the Gebze–Bursa
# and Bursa–İzmir sections, each its own ticket).
PART = {"O-5 Gebze – Orhangazi – Bursa (Osmangazi Köprüsü)": 0, "O-5 Bursa – İzmir": 1}
# Row labels the word boxes cut short -> the names the header prints.
RENAME = {"O-5 Bursa – İzmir": {"- Mustafakemalpaşa - 1": "Karacabey - Mustafakemalpaşa - 1",
                                "- Mustafakemalpaşa - 2": "Karacabey - Mustafakemalpaşa - 2", "Kuzey": "Balıkesir Kuzey"}}
# The Yavuz Sultan Selim bridge lies inside the Kuzey Çevre motorway, whose
# tickets include it (Uskumruköy – Riva, the stations either side, class
# 4: 985 TL against the bridge's own 690): a route with such a ticket
# across the bridge doesn't pay the bridge again.
WITHIN = {"Yavuz Sultan Selim Köprüsü": "O-7 Yavuz Sultan Selim Köprüsü ve Kuzey Çevre Otoyolu"}
# Abbreviated tariff names -> the OpenStreetMap toll booths' names.
ALIAS = {"Ş.PINAR": "Şekerpınar", "K.BURGAZ": "Kumburgaz", "GEBZE ORG. SAN. BÖLGELERİ": "Gebze OSB",
         "MERMECİLER": "Mermerciler", "KÜÇÜKILIÇLI": "Küçükkılıçlı",
         "Osmangazi Köprüsü": "Osmangazi Köprüsü (Hersek)"}
# Stations left unplaced on purpose: Karacabey – Mustafakemalpaşa 1 and 2
# are one place, each charging the longest trip's price for all but one
# direction (one-way ramps); the route can't tell which it took.
DROP = {"Karacabey - Mustafakemalpaşa - 1", "Karacabey - Mustafakemalpaşa - 2"}
GROUPS = [{"name": "2", "max_axles": 2}, {"name": "3", "min_axles": 3, "max_axles": 3},
          {"name": "4", "min_axles": 4, "max_axles": 5}, {"name": "5", "min_axles": 6}]
KDV = 1.20
# KGM class -> axle bounds of the truck classes.
AXLES = {2: (2, 2), 3: (3, 3), 4: (4, 5), 5: (6, 0)}


def tl(s):
    return float(s.replace(".", "").replace(",", "."))


def tariff(path):
    t = open(path, encoding="utf-8").read().replace("​", "")
    m = re.search(r"\((\d\d)/(\d\d)/(\d{4}) [Ss]aat 00:00'dan itibaren geçerlidir\.\)", t)
    if not m:
        sys.exit(f"{path}: no date")
    date = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    prices = {}
    for line in t.split("\n"):
        m = re.match(r"^\s*([1-6])\s+(?:.*?\s)?(\d{1,3}(?:\.\d{3})*,\d\d)(?:\s*₺)?(?:\s+[\d,]+)?\s*$", line)
        if m and int(m.group(1)) not in prices:
            prices[int(m.group(1))] = tl(m.group(2))
    if sorted(prices) != [1, 2, 3, 4, 5, 6]:
        sys.exit(f"{path}: classes {prices}")
    return date, prices


def km(a, b):
    return math.hypot((a[0] - b[0]) * 111.2 * math.cos(math.radians(a[1])), (a[1] - b[1]) * 111.2)


def middle(coords):
    """The point halfway along a line, and the line's length in km."""
    total = sum(km(coords[i], coords[i + 1]) for i in range(len(coords) - 1))
    left = total / 2
    for i in range(len(coords) - 1):
        d = km(coords[i], coords[i + 1])
        if d >= left and d > 0:
            f = left / d
            return [coords[i][0] + f * (coords[i + 1][0] - coords[i][0]), coords[i][1] + f * (coords[i + 1][1] - coords[i][1])], total
        left -= d
    return coords[0], total


SUFFIX = re.compile(r"\s*(Gişeleri|Gişeler|Gişesi|Gişesiz Otomatik Geçiş Bölgesi|Otomatik Geçiş Sistemi)(\s+(giriş|çıkış))?\s*$", re.I)


def wkey(name):
    """A name's key with its words in any order ("DOĞU İZMİT" = "İzmit Doğu")."""
    return "".join(sorted(tr_matrix.key(w) for w in name.replace("ș", "s").split()))


def variants(name):
    """Keys a tariff name may match: as printed (without its booth number,
    "(G11)", "G-1"), without or only the part in brackets, without a
    trailing ALIN (main-line plaza), SGS, KMO or 2, and a double name's
    first part ("Kulu-Kırıkkale")."""
    n = ALIAS.get(name, name)
    n = re.sub(r"\s*\(G\d+\)|\s+G-\d+$", "", n)
    out = [n, re.sub(r"\s*\([^)]*\)", "", n).strip()] + re.findall(r"\(([^)]*)\)", n)
    out += [re.sub(r"^(KMO)\s+|\s+(ALIN|Alın|SGS|2)$", "", x) for x in out]
    out += [m.group(1) for x in out for m in [re.match(r"^(\w+)-\w{2,}$", x)] if m]  # "Kulu-Kırıkkale"
    return list(dict.fromkeys(k for x in out if x.strip() for k in (wkey(x), tr_matrix.key(x))))


def clusters(points, within=3):
    """Groups same-name points less than `within` km apart."""
    out = []
    for c in points:
        for cl in out:
            if km(c, cl[0]) < within:
                cl.append(c)
                break
        else:
            out.append([c])
    return [(cl, [sum(x[0] for x in cl) / len(cl), sum(x[1] for x in cl) / len(cl)]) for cl in out]


def place(names, booths, junctions, used):
    """Picks for each station (in order along the motorway) one of the
    OSM booth clusters its name matches (else junctions), the choice that
    makes the stations' chain shortest; stations far from the others stay
    unplaced. A cluster serves one motorway: those in `used` (placed for
    an earlier one) are skipped, and the ones picked are added."""
    cands = []
    for n in names:
        vs = variants(n)
        c = [(cl, ctr, "booth") for v in vs for cl, ctr in clusters(booths.get(v, []))]
        if not c:
            c = [(cl, ctr, "junction") for v in vs for cl, ctr in clusters(junctions.get(v, []))]
        seen, c2 = set(), []
        for x in c:
            k = (round(x[1][0], 4), round(x[1][1], 4))
            if k not in used and k not in seen:
                seen.add(k)
                c2.append(x)
        cands.append(c2)
    idx = [i for i, c in enumerate(cands) if c]
    # Shortest chain through one candidate per placed station.
    best = {k: (0.0, [k]) for k in range(len(cands[idx[0]]))} if idx else {}
    for a, b in zip(idx, idx[1:]):
        nb = {}
        for k, cb in enumerate(cands[b]):
            nb[k] = min(((d + km(cands[a][j][1], cb[1]), path + [k]) for j, (d, path) in best.items()), key=lambda x: x[0])
        best = nb
    out = [None] * len(names)
    if best:
        for i, k in zip(idx, min(best.values(), key=lambda x: x[0])[1]):
            out[i] = cands[i][k]
    # A station more than 60 km from every other placed one is a namesake.
    for i in idx:
        if out[i] and all(km(out[i][1], out[j][1]) > 60 for j in idx if j != i and out[j]):
            print(f"  {names[i]}: {out[i][1]} far from the others, unplaced")
            out[i] = None
    for o in out:
        if o:
            used.add((round(o[1][0], 4), round(o[1][1], 4)))
    return out


def osmangazi(rows, cols, cells, bridge):
    """Gebze–Bursa's matrix has the bridge as two stations: "İzmir Yönü"
    (entering southbound, its row) and "İstanbul Yönü" (leaving
    northbound, a column). Southbound the bridge is paid at its plaza and
    the row prices are the motorway alone; the northbound column is the
    row price plus the bridge. Checked, then folded into one station
    "Osmangazi Köprüsü" priced without the bridge, which its own toll
    point charges either way."""
    iz, ist = 0, 1
    if not (rows[0].endswith("(İzmir Yönü)") and cols[ist].endswith("(İstanbul Yönü)")):
        sys.exit(f"Gebze–Bursa: unexpected stations {rows[0]}, {cols[ist]}")
    for c in AXLES:
        if round(cells[(0, iz)][c], 2) != bridge[c]:
            sys.exit(f"Gebze–Bursa: the bridge price {cells[(0, iz)][c]} isn't the Osmangazi tariff {bridge[c]}")
    out = {(0, 0): cells[(0, 0)]}
    for r in range(1, len(rows)):
        for c in AXLES:
            if round(cells[(r, ist)][c] - cells[(0, r + 1)][c], 2) != bridge[c]:
                sys.exit(f"Gebze–Bursa: {rows[r]} northbound isn't the southbound price plus the bridge")
        out[(r, 0)] = {c: cells[(r, ist)][c] - bridge[c] for c in cells[(r, ist)]}
        out[(0, r)] = cells[(0, r + 1)]
        for c2 in range(1, len(rows)):
            out[(r, c2)] = cells[(r, c2 + 1)]
    names = ["Osmangazi Köprüsü"] + rows[1:]
    return names, names, out


def between(order, pts, unnamed, named, used):
    """Places an unplaced station whose neighbours along the motorway are
    placed at the one plaza of unnamed OSM toll booths (two or more) on
    the way between them: going through it adds at most 1 km to the
    straight line, it is more than 1.5 km from every named booth and
    every place a station was given (any motorway so far), and no
    other unplaced station of the motorway could take it."""
    cand = {}
    for i, p in enumerate(pts):
        if p or not order[i] or order[i] in DROP:
            continue
        a = next((pts[j][1] for j in range(i - 1, -1, -1) if pts[j]), None)
        b = next((pts[j][1] for j in range(i + 1, len(pts)) if pts[j]), None)
        if not (a and b):
            continue
        cand[i] = [(cl, ctr) for cl, ctr in unnamed
                   if len(cl) >= 2 and (round(ctr[0], 4), round(ctr[1], 4)) not in used
                   and km(a, ctr) + km(ctr, b) <= km(a, b) + 1 and all(km(ctr, n) > 1.5 for n in named)
                   and all(km(ctr, u) > 1.5 for u in used)]
    for i, c in cand.items():
        if len(c) == 1 and sum(c[0][1] == x[1] for cs in cand.values() for x in cs) == 1:
            pts[i] = (c[0][0], c[0][1], "booth")
            used.add((round(c[0][1][0], 4), round(c[0][1][1], 4)))
            print(f"  {order[i]}: the unnamed toll booths at {c[0][1][1]:.5f},{c[0][1][0]:.5f}")


def system(m, name, booths, junctions, used, sid, unnamed, named):
    rows, cols, cells = m
    square = len(rows) == len(cols) and all((r, c) in cells for r in range(len(rows)) for c in range(len(cols)))
    if square:
        owner = {c: c for c in range(len(cols))}  # column c is row c's station
    else:
        # Lower triangle: each row's last price (the longest trip's,
        # charged without an entry) stands in its own column, if it has one.
        owner = {}
        for r in range(len(rows)):
            d = max(c for (r2, c) in cells if r2 == r)
            if d not in owner or tr_matrix.key(cols[d]) == tr_matrix.key(rows[r]):
                owner[d] = r
    colst = {c: (rows[owner[c]] if c in owner else cols[c]) for c in range(len(cols))}
    # Stations in order along the road: the columns, a row-only station
    # just before the column of its last price.
    pos = {colst[c]: c for c in range(len(cols))}
    for r in range(len(rows)):
        pos.setdefault(rows[r], max(c for (r2, c) in cells if r2 == r) - 0.5)
    order = sorted(pos, key=lambda n: pos[n])
    pts = place([n if n not in DROP else "" for n in order], booths, junctions, used)
    between(order, pts, unnamed, named, used)
    placed = {n: p for n, p in zip(order, pts) if p}
    prices = {}
    for (r, c), p in cells.items():
        a, b = rows[r], colst[c]
        if a == b or a not in placed or b not in placed or (not square and c in owner and owner[c] > r):
            continue
        prices[f"{a}|{b}"] = {g["name"]: round(p[int(g["name"])] / KDV, 4) for g in GROUPS}
    stations = [{"name": n, "points": [{"name": placed[n][2], "lat": round(x[1], 6), "lon": round(x[0], 6)} for x in placed[n][0]]} for n in order if n in placed]
    missing = [n for n in order if n not in placed]
    print(f"{name}: {len(stations)}/{len(order)} stations placed, {len(prices)} prices" + (f"; unplaced {missing}" if missing else ""))
    return {"name": name, "law": "KGM 2026 tariff (" + sid + "), TL including 20% KDV, here excluding it; KGM classes 2 (two axles), 3, 4 (four and five axles), 5 (six or more)",
            "groups": GROUPS, "stations": stations, "prices": prices}, missing, order


def main(fetched, out):
    ways = {}
    for line in open(os.path.join(fetched, "tr-osm.geojsonseq"), encoding="utf-8"):
        f = json.loads(line.strip("\x1e"))
        p, g = f["properties"], f["geometry"]
        if g["type"] != "LineString" or p.get("highway") not in ("motorway", "trunk", "primary"):
            continue
        for k in ("name", "bridge:name"):
            if p.get(k):
                ways.setdefault(p[k], []).append((p, g["coordinates"]))
    date, points = "", []
    for sid, names in BRIDGES:
        d, prices = tariff(os.path.join(fetched, sid + ".txt"))
        date = max(date, d)
        classes = [{"min_axles": lo, **({"max_axles": hi} if hi else {}), "rate": round(prices[c] / KDV, 4)} for c, (lo, hi) in AXLES.items()]
        for name in names:
            ws = ways.get(name, [])
            if not ws:
                sys.exit(f"{name}: no way in OpenStreetMap")
            mids = sorted((middle(c) for _, c in ws), key=lambda x: -x[1])
            longest = mids[0][1]
            # The main span of each carriageway: the longest ways (within 10%).
            keep = []
            for (lon, lat), length in mids:
                if length >= 0.9 * longest and all(km((lon, lat), k) > 0.01 for k in keep):
                    keep.append((lon, lat))
            if len(keep) > 2 or (len(keep) == 2 and km(keep[0], keep[1]) > 0.2):
                sys.exit(f"{name}: main spans {keep}")
            for lon, lat in keep:
                points.append({"name": name, "lat": round(lat, 6), "lon": round(lon, 6), "rate": 0, "classes": classes,
                               **({"within": WITHIN[name]} if name in WITHIN else {})})
            print(f"{name}: {len(ws)} ways, main span {longest:.2f} km, {len(keep)} points; class 2-5 TL {[prices[c] for c in AXLES]} ({d})")
    # Motorways: toll booths (else junctions) by name.
    booths, junctions, anon, named = {}, {}, [], []
    for line in open(os.path.join(fetched, "tr-osm-booths.geojsonseq"), encoding="utf-8"):
        f = json.loads(line.strip("\x1e"))
        p, c = f["properties"], f["geometry"]["coordinates"]
        while isinstance(c[0], list):
            c = c[0]
        if not p.get("name"):
            if p.get("highway") != "motorway_junction":
                anon.append(c)
            continue
        if p.get("highway") != "motorway_junction":
            named.append(c)
        n = SUFFIX.sub("", p["name"])
        for k in {wkey(n), tr_matrix.key(n)}:
            (junctions if p.get("highway") == "motorway_junction" else booths).setdefault(k, []).append(c)
    unnamed = clusters(anon, 1.0)
    used, systems, unplaced = set(), [], []
    _, osmangazi_tl = tariff(os.path.join(fetched, "tr-2-osmangazi.txt"))
    for sid, name in SYSTEMS:
        ms = tr_matrix.matrices(os.path.join(fetched, sid + ".bbox.html"))
        if len(ms) != (2 if name in PART else 1):
            sys.exit(f"{sid}: {len(ms)} matrices")
        rows, cols, cells = ms[PART.get(name, 0)]
        rows = [RENAME.get(name, {}).get(r, r) for r in rows]
        if name.startswith("O-5 Gebze"):
            rows, cols, cells = osmangazi(rows, cols, cells, osmangazi_tl)
        s, missing, _ = system((rows, cols, cells), name, booths, junctions, used, sid, unnamed, named)
        systems.append(s)
        unplaced += missing
    # The 1915 Çanakkale bridge's own tariff is Malkara–Çanakkale's
    # Gelibolu Güney – bridge price.
    d, bridge = tariff(os.path.join(fetched, "tr-4-1915canakkale.txt"))
    date = max(date, d)
    mc = systems[[n for _, n in SYSTEMS].index("O-6 Malkara – Çanakkale (1915 Çanakkale Köprüsü)")]["prices"]
    if [round(mc["GELİBOLU GÜNEY G-4|1915 ÇANAKKALE KÖPRÜSÜ G-5"][str(c)] * KDV, 2) for c in AXLES] != [bridge[c] for c in AXLES]:
        sys.exit(f"1915 Çanakkale bridge tariff {bridge} isn't the Gelibolu Güney – bridge price")
    osm = open(os.path.join(fetched, "tr-osm-timestamp.txt")).read().strip()[:10]
    kgm = "https://www.kgm.gov.tr/SiteCollectionDocuments/KGMdocuments/Otoyollar/OtoyolKopruUcret/2026Gecis_Ucret/"
    titles = {"tr-1-15temmuz-fsm": ("15 Temmuz Şehitler ve Fatih Sultan Mehmet Köprüleri", "1-15Temmuz-FSM"),
              "tr-2-osmangazi": ("Osmangazi Köprüsü", "2-Osmangazi"), "tr-3-ysskoprusu": ("Yavuz Sultan Selim Köprüsü", "3-YSSKoprusu"),
              "tr-4-1915canakkale": ("1915 Çanakkale Köprüsü", "4-1915Canakkale")}
    srcs = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources.json")))["sources"]
    url = {s["id"]: s["url"] for s in srcs}
    tb = {
        "country": "TR", "currency": "TRY", "valid_from": date,
        "name": "Turkish motorway and bridge tolls (KGM)",
        "law": "Karayollarında Geçiş Ücretlerinin Belirlenmesi ve Uygulanmasına Dair Yönetmelik; KGM's 2026 tariffs. Bridges (15 Temmuz Şehitler, Fatih Sultan Mehmet, Osmangazi, Yavuz Sultan Selim) per passage either way; motorways by entry and exit station. By KGM class: 2 (two axles of 3.20 m or more wheelbase), 3 (three axles), 4 (four and five axles), 5 (six or more), excluding 20% KDV (VAT). Trucks may not use 15 Temmuz Şehitler or FSM (UKOME decision) but pay their tariff if they do. Bridges placed at their main span, stations at their toll booths (else the motorway junction of their name) in OpenStreetMap (extract of " + osm + "); " + str(len(unplaced)) + " stations OSM doesn't name aren't placed, a trip from or to one priced from the next placed station. The Osmangazi bridge is charged at its own tariff, Gebze–Bursa's prices taken without it; Kuzey Çevre's tickets include the Yavuz Sultan Selim bridge, which isn't charged again on them.",
        "sources": [{"title": "KGM: Otoyol ve Köprü Geçiş Ücretleri", "url": url["tr-kgm-ucretler"]}]
                   + [{"title": f"KGM: {a} Geçiş Ücretleri Tarifesi", "url": kgm + b + ".pdf"} for a, b in titles.values()]
                   + [{"title": f"KGM: {n} geçiş ücretleri", "url": url[sid]} for sid, n in dict((sid, "O-5 Gebze – Orhangazi – İzmir" if sid in ("tr-12-gebze-orhangazi-izmir",) else n) for sid, n in SYSTEMS).items()]
                   + [{"title": "OpenStreetMap (Geofabrik extract), bridges and toll booths", "url": "https://download.geofabrik.de/europe/turkey.html"}],
        "vehicles": "Trucks of two or more axles (KGM classes 2 to 5)",
        "tolled_roads": "The 15 Temmuz Şehitler, Fatih Sultan Mehmet, Yavuz Sultan Selim and Osmangazi bridges; " + ", ".join(n for _, n in SYSTEMS) + ".",
        "point_match_km": 0.05,
        "toll_points": points,
        "closed_systems": systems,
        "rows": [],
    }
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"tr-{date}.json")
    json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
    print(path)


if __name__ == "__main__":
    main(*sys.argv[1:])
