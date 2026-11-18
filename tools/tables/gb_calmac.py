"""Builds CalMac's commercial vehicle fares (Caledonian MacBrayne, the Clyde
and Hebrides ferry services run for the Scottish Government) as toll
systems (gb-calmac-<date>.json), from

- the commercial vehicle single rates table (gb-calmac-cv.pdf, linked from
  CalMac's commercial vehicle rates page, gb-calmac-cv-page.html): for each
  route a fixed base rate (on some), the price per 0.5 m of the vehicle's
  length, and the fares from 6 to 17 m worked out. The table is an image:
  read by OCR (Tesseract), and each route's base and price per 0.5 m must
  give its 23 printed fares (most of them read alike: an OCR slip in a cell
  is outvoted);
- a route's fare page (gb-calmac-uig-tarbert.pdf): commercial vehicles are
  charged by length in 0.5 m increments, and the fares exclude VAT;
- OpenStreetMap (gb-calmac-osm.json, Overpass): the ferry lines and the
  terminals of the ports.

A fare is the base plus the price per 0.5 m for each started 0.5 m of the
vehicle's length (6 m at least), one way. Each route (or routes that share a
ferry line: a ship that calls on the way) is a closed system whose ports
are stations with points out on the water, on each car ferry line between
two of its ports, clear of every other system's lines (as for Norway's
ferries, no_ferries.py). A route whose ports OpenStreetMap has no line
between, or whose line motor vehicles may take only with a permit (the
Small Isles, Iona), isn't priced.

Usage: python3 gb_calmac.py <fetched dir> <out dir>
"""
import json, os, re, sys

from ferry_osm import MATCH_KM, QUAY_KM, features, km, lines_of, systems as place_systems

LONGEST_M = 25.5  # length groups to this length, in 0.5 m
MONTHS = {m: i + 1 for i, m in enumerate(("january", "february", "march", "april", "may", "june", "july", "august",
                                          "september", "october", "november", "december"))}
# Each row of the table: its ports, pair by pair.
ROUTES = {
    "Ardmhor (Barra)-Eriskay": [("Ardmhor", "Eriskay")],
    "Ardrossan/Troon-Brodick": [("Ardrossan", "Brodick"), ("Troon", "Brodick")],
    "Berneray-Leverburgh": [("Berneray", "Leverburgh")],
    "Castlebay-Lochboisdale": [("Castlebay", "Lochboisdale")],
    "Claonaig/Tarbert(*)-Lochranza": [("Claonaig", "Lochranza"), ("Tarbert (Loch Fyne)", "Lochranza")],
    "Colintraive-Rhubodach": [("Colintraive", "Rhubodach")],
    "Coll-Tiree": [("Coll", "Tiree")],
    "Fionnphort-Iona": [("Fionnphort", "Iona")],
    "Kennacraig-Port Ellen/Port Askaig": [("Kennacraig", "Port Ellen"), ("Kennacraig", "Port Askaig")],
    "Largs-Cumbrae Slip": [("Largs", "Cumbrae Slip")],
    "Lochaline-Fishnish": [("Lochaline", "Fishnish")],
    "Lochmaddy-Tarbert": [("Lochmaddy", "Tarbert (Harris)")],
    "Mallaig-Armadale": [("Mallaig", "Armadale")],
    "Mallaig-Canna": [("Mallaig", "Canna")],
    "Mallaig-Eigg": [("Mallaig", "Eigg")],
    "Mallaig-Lochboisdale": [("Mallaig", "Lochboisdale")],
    "Mallaig-Muck": [("Mallaig", "Muck")],
    "Mallaig-Rum": [("Mallaig", "Rum")],
    "Oban-Castlebay/Lochboisdale": [("Oban", "Castlebay"), ("Oban", "Lochboisdale")],
    "Oban-Coll/Tiree": [("Oban", "Coll"), ("Oban", "Tiree")],
    "Oban-Craignure": [("Oban", "Craignure")],
    "Oban-Lismore": [("Oban", "Lismore")],
    "Oban/Kennacraig-Colonsay": [("Oban", "Colonsay"), ("Kennacraig", "Colonsay")],
    "Oban-Port Askaig": [("Oban", "Port Askaig")],
    "Port Askaig-Colonsay": [("Port Askaig", "Colonsay")],
    "Sconser-Raasay": [("Sconser", "Raasay")],
    "Tarbert-Portavadie": [("Tarbert (Loch Fyne)", "Portavadie")],
    "Tayinloan-Gigha": [("Tayinloan", "Gigha")],
    "Tiree-Castlebay": [("Tiree", "Castlebay")],
    "Tobermory-Kilchoan": [("Tobermory", "Kilchoan")],
    "Uig-Lochmaddy": [("Uig", "Lochmaddy")],
    "Uig-Tarbert": [("Uig", "Tarbert (Harris)")],
    "Ullapool-Stornoway": [("Ullapool", "Stornoway")],
    "Wemyss Bay-Rothesay": [("Wemyss Bay", "Rothesay")],
}
# Each port: its terminal in OpenStreetMap (amenity=ferry_terminal) by name,
# else a place by name, else the far end of the one car ferry line from
# another port.
PORTS = {
    "Ardmhor": ("terminal", "Àird Mhòr"), "Eriskay": ("terminal", "Ceann a' Ghàraidh"),
    "Ardrossan": ("terminal", "Ardrossan Ferry Terminal"), "Troon": ("terminal", "Troon Ferry Terminal"),
    "Brodick": ("terminal", "Brodick Ferry Terminal"), "Berneray": ("terminal", "Ionad Aiseig' Bheàrnaraigh"),
    "Leverburgh": ("terminal", "Ionad Aiseig' an t-Òib"), "Castlebay": ("terminal", "Castlebay Ferry Terminal"),
    "Lochboisdale": ("terminal", "Ionad Aiseig' Loch Baghasdail"), "Claonaig": ("place", "Claonaig"),
    "Tarbert (Loch Fyne)": ("terminal", "Tarbert"), "Lochranza": ("terminal", "Lochranza Ferry Terminal"),
    "Colintraive": ("terminal", "Colintraive"), "Rhubodach": ("terminal", "Rhubodach"),
    "Coll": ("terminal", "Coll Ferry Terminal"), "Tiree": ("terminal", "Scarinish Ferry Terminal"),
    "Fionnphort": ("terminal", "Fionnphort Ferry Terminal"), "Iona": ("terminal", "Iona Ferry Terminal"),
    "Kennacraig": ("terminal", "Kennacraig"), "Port Ellen": ("terminal", "Port Ellen Ferry Terminal"),
    "Port Askaig": ("terminal", "Port Askaig Ferry Terminal"), "Largs": ("terminal", "Largs Ferry Terminal"),
    "Cumbrae Slip": ("terminal", "Cumbrae Ferry Terminal"), "Lochaline": ("terminal", "Lochaline Ferry Terminal"),
    "Fishnish": ("terminal", "Fishnish Ferry Terminal"), "Lochmaddy": ("place", "Lochmaddy"),
    "Tarbert (Harris)": ("terminal", "Ionad Aiseig' an Tairbeart"), "Mallaig": ("terminal", "Mallaig Ferry Terminal"),
    "Armadale": ("terminal", "Armadale Ferry Terminal"), "Canna": ("terminal", "Canna Pier"), "Eigg": ("terminal", "Eigg"),
    "Muck": ("place", "Muck"), "Rum": ("place", "Kinloch"), "Oban": ("terminal", "Oban Ferry Terminal"),
    "Craignure": ("terminal", "Craignure Ferry Terminal"), "Lismore": ("terminal", "Lismore Ferry Terminal"),
    "Colonsay": ("terminal", "Colonsay Ferry Terminal"), "Sconser": ("place", "Sconser"), "Raasay": ("end", "Sconser"),
    "Portavadie": ("place", "Portavadie"), "Tayinloan": ("terminal", "Tayinloan - Gigha Ferry Terminal"),
    "Gigha": ("terminal", "Gigha"), "Tobermory": ("terminal", "Tobermory Ferry Terminal"),
    "Kilchoan": ("terminal", "Kilchoan Ferry Terminal"), "Uig": ("terminal", "Uig Ferry Terminal"),
    "Ullapool": ("terminal", "Ullapool Ferry Terminal"), "Stornoway": ("terminal", "Stornoway Ferry Terminal"),
    "Wemyss Bay": ("terminal", "Wemyss Bay"), "Rothesay": ("terminal", "Rothesay Ferry Terminal"),
}
PAGE = "https://www.calmac.co.uk/faqs/commercial-vehicles/commercial-vehicle-rates"


# The fares table, read by OCR.

def money(s):
    m = re.fullmatch(r"[£fFeE]?\s*(\d{1,4})[.,](\d\d)", s.strip().replace(" ", ""))
    return round(int(m.group(1)) + int(m.group(2)) / 100, 2) if m else None


def read_table(pdf):
    """(the title, rows of (route, base, price per 0.5 m)) from the table's
    one image, each row checked against its printed fares."""
    import cv2, fitz, numpy as np, pytesseract
    os.environ.setdefault("OMP_THREAD_LIMIT", "1")
    doc = fitz.open(pdf)
    imgs = doc[0].get_images(full=True)
    if len(doc) != 1 or len(imgs) != 1:
        sys.exit(f"CalMac: the fares table isn't one image on one page ({len(doc)} pages, {len(imgs)} images)")
    im = cv2.imdecode(np.frombuffer(doc.extract_image(imgs[0][0])["image"], np.uint8), cv2.IMREAD_GRAYSCALE)
    im = cv2.resize(im, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    bw = cv2.adaptiveThreshold(255 - im, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 15, -2)
    h = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (im.shape[1] // 6, 1)))
    v = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 40)))

    def groups(vals):
        out = []
        for x in vals:
            if out and x - out[-1][-1] <= 30:
                out[-1].append(x)
            else:
                out.append([x])
        return [(g[0], g[-1]) for g in out]
    ys = groups([y for y in range(h.shape[0]) if h[y].sum() > 255 * im.shape[1] * 0.5])
    xs = groups([x for x in range(v.shape[1]) if v[:, x].sum() > 255 * v.shape[0] * 0.3])
    bands = [(a[1], b[0]) for a, b in zip(ys, ys[1:])]
    cols = [(a[1], b[0]) for a, b in zip(xs, xs[1:])]
    if len(cols) != 26:
        sys.exit(f"CalMac: the fares table has {len(cols)} columns, not route, base, price per 0.5 m and 23 lengths")

    def ocr(a, b, c, cfg="--psm 7"):
        cell = cv2.copyMakeBorder(im[a + 3:b - 2, cols[c][0] + 3:cols[c][1] - 2], 15, 15, 15, 15, cv2.BORDER_CONSTANT, value=255)
        return re.sub(r"\s+", " ", pytesseract.image_to_string(cell, lang="eng", config=cfg)).strip()
    # Data rows are as tall as the most; the header's band may hold the
    # first row (its rule doesn't come out): that row is the band's bottom.
    tall = sorted(b - a for a, b in bands)[len(bands) // 2]
    rows = []
    for k, (a, b) in enumerate(bands):
        if b - a < 1.3 * tall:
            rows.append((a, b))
        elif k + 1 < len(bands) and bands[k + 1][1] - bands[k + 1][0] < 1.3 * tall:
            rows.append((b - tall, b))
    title = re.sub(r"\s+", " ", pytesseract.image_to_string(im[bands[0][0]:bands[0][1]], lang="eng", config="--psm 6")).strip()
    out = []
    for a, b in rows:
        name = ocr(a, b, 0)
        if route_of(name) is None:
            continue
        base, rate = money(ocr(a, b, 1)), money(ocr(a, b, 2))
        fares = [money(ocr(a, b, c)) for c in range(3, 26)]
        # The fare at 6 + k/2 m is the base and 12 + k half metres; most cells must agree.
        def fits(base, rate):
            return sum(1 for k, f in enumerate(fares) if f is not None and abs((base or 0) + rate * (12 + k) - f) < 0.005)
        cands = {(base, rate)}
        diffs = [round(y - x, 2) for x, y in zip(fares, fares[1:]) if x is not None and y is not None]
        if diffs:
            r2 = max(set(diffs), key=diffs.count)
            for k, f in enumerate(fares):
                if f is not None:
                    cands.add((round(f - r2 * (12 + k), 2) or None, r2))
        best = max((c for c in cands if c[1]), key=lambda c: fits(*c), default=None)
        if best is None or fits(*best) < 18:
            sys.exit(f"CalMac: {name!r}: no base and price per 0.5 m give its fares ({base}, {rate}: {fares})")
        if rate is not None and best[1] != rate:
            sys.exit(f"CalMac: {name!r}: the price per 0.5 m reads {rate}, the fares give {best[1]}")
        out.append((name, best[0], best[1], fits(*best)))
    return title, out


def route_of(name):
    """The table's route name as ROUTES has it (OCR reads a letter or a space amiss)."""
    import difflib
    key = lambda s: re.sub(r"[^a-z]", "", s.lower())
    m = difflib.get_close_matches(key(name), [key(r) for r in ROUTES], n=1, cutoff=0.85)
    return next((r for r in ROUTES if key(r) == m[0]), None) if m else None


# The ports and lines, from OpenStreetMap.

def places(osm):
    """Each port's place."""
    feats = features(osm)
    out = {}
    for port, (kind, name) in PORTS.items():
        if kind == "terminal":
            hit = [p for t, p in feats if t.get("amenity") == "ferry_terminal" and t.get("name") == name]
        elif kind == "place":
            hit = [p for t, p in feats if t.get("place") and t.get("name") == name]
        else:
            continue
        if hit:
            out[port] = hit[0]
    return out


def main(fetched, out):
    try:
        osm = json.load(open(os.path.join(fetched, "gb-calmac-osm.json")))
        page = open(os.path.join(fetched, "gb-calmac-cv-page.html"), encoding="utf-8", errors="replace").read()
        route_page = re.sub(r"\s+", " ", open(os.path.join(fetched, "gb-calmac-uig-tarbert.txt"), encoding="utf-8").read())
    except (OSError, ValueError):
        print("CalMac: a source wasn't fetched; not built")
        return
    src = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources.json")))["sources"]
    cv_url = next(s["url"] for s in src if s["id"] == "gb-calmac-cv")
    if cv_url.split("/media/")[-1] not in page:
        sys.exit(f"CalMac: the commercial vehicle rates page links another table than {cv_url}: a new table, for tools/tables/sources.json")
    for needle in ("Fares are exclusive of VAT", "in 0.5 metre increments", "Commercial Vehicle"):
        if needle not in route_page:
            sys.exit(f"CalMac: the route's fare page no longer says {needle!r}")
    title, rows = read_table(os.path.join(fetched, "gb-calmac-cv.pdf"))
    m = re.search(r"single rates from (\d{1,2})(?:st|nd|rd|th)? (\w+) (\d{4})", title, re.I)
    if not m or m.group(2).lower() not in MONTHS or "Commercial Vehicle" not in title:
        sys.exit(f"CalMac: the table's title not read: {title!r}")
    start = f"{m.group(3)}-{MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    fares = {}
    for name, base, rate, n in rows:
        r = route_of(name)
        if r is None:
            sys.exit(f"CalMac: a route ROUTES doesn't have: {name!r}")
        fares[r] = (base, rate)
    if sorted(fares) != sorted(ROUTES):
        sys.exit(f"CalMac: routes not in the table: {sorted(set(ROUTES) - set(fares))}")
    lines, permit = lines_of(osm)
    pos = places(osm)
    for port, (kind, other) in PORTS.items():
        if kind == "end" and other in pos:
            ends = [ln[-1] if km(ln[0], pos[other]) <= QUAY_KM else ln[0] for _, ln in lines
                    if min(km(ln[0], pos[other]), km(ln[-1], pos[other])) <= QUAY_KM]
            if len(ends) == 1:
                pos[port] = ends[0]
    groups = [{"name": "6 m", "min_kg": 3501, "max_length_m": 6.0}]
    halves = list(range(13, int(LONGEST_M * 2) + 1))
    for n in halves:
        groups.append({"name": f"{n / 2:g} m", "min_kg": 3501, "min_length_m": (n - 1) / 2, "max_length_m": n / 2})
    placed, notes = place_systems(ROUTES, pos, lines, permit, lambda m: sys.exit(f"CalMac: {m}"))
    systems = []
    for rs, stations, pairs in placed:
        prices = {}
        for r, a, b in pairs:
            base, rate = fares[r]
            p = {"6 m": round((base or 0) + rate * 12, 2)}
            for n in halves:
                p[f"{n / 2:g} m"] = round((base or 0) + rate * n, 2)
            prices[f"{a}|{b}"] = p
        name = " / ".join(rs)
        systems.append({"name": f"CalMac {name}", "law": f"CalMac commercial vehicle single rates from {start}: {'; '.join(f'{r}: ' + (f'£{fares[r][0]:.2f} plus ' if fares[r][0] else '') + f'£{fares[r][1]:.2f} per 0.5 m' for r in rs)}",
                        "groups": groups, "stations": [{"name": n, "points": p} for n, p in sorted(stations.items())],
                        "station_match_km": MATCH_KM, "prices": prices})
        print(name, {k: v["16.5 m"] for k, v in prices.items()}, {n: len(p) for n, p in stations.items()})
    t = {"country": "GB", "currency": "GBP", "valid_from": start, "crossings": True,
         "name": "CalMac ferries (Clyde and Hebrides), commercial vehicles",
         "law": (f"CalMac's commercial vehicle single rates from {start} (until further notice): per route, its fixed base rate (Coll–Tiree, Tiree–Castlebay, "
                 "Uig's and Ullapool's routes) plus its price per 0.5 m of the vehicle's length, for each started 0.5 m and 6 m at least, one way; vehicles over 3.5 t "
                 f"(the route fare pages: commercial vehicles are charged by length in 0.5 metre increments, and the fares exclude VAT, which is left out here too). "
                 f"Length groups to {LONGEST_M:g} m. The table is an image, read by OCR: each route's base and price per 0.5 m give its fares from 6 to 17 m as printed. "
                 "The ports are OpenStreetMap's ferry terminals, priced where a route goes out on OpenStreetMap's car ferry line from them; routes sharing a line "
                 "(a ship calling on the way) are one system, priced from the first port passed to the last. Wide loads (dearer) aren't priced. "
                 + " ".join(f"{n}." for n in notes)),
         "sources": [{"title": f"CalMac: commercial vehicle single rates from {start}", "url": cv_url},
                     {"title": "CalMac: commercial vehicle rates", "url": PAGE},
                     {"title": "CalMac: Uig – Tarbert fares (commercial vehicles by length in 0.5 m increments, excluding VAT)",
                      "url": next(s["url"] for s in src if s["id"] == "gb-calmac-uig-tarbert")},
                     {"title": "OpenStreetMap (Overpass API): ferry lines and terminals on Scotland's west coast", "url": "https://www.openstreetmap.org/"}],
         "vehicles": "Commercial vehicles over 3.5 t, by length (give truck.length_m; 16.5 m assumed)", "min_kg": 3501,
         "tolled_roads": "CalMac's ferry routes on the Clyde and to the Hebrides, from port to port.",
         "closed_systems": systems, "rows": []}
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"gb-calmac-{start}.json")
    json.dump(t, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, len(systems), "systems;", "; ".join(notes))


if __name__ == "__main__":
    main(*sys.argv[1:])
