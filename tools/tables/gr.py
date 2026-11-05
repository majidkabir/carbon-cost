"""Builds the Greek motorway toll table from the concession companies'
price pages (fetch.py's gr-olympia, gr-neaodos, gr-kentriki, gr-moreas,
gr-aegean .html) and the toll booths in OpenStreetMap (the workflow's
gr-osm.geojsonseq, from Geofabrik's Greece extract).

Usage: python3 gr.py fetched/ out-dir -> out-dir/gr-<year>-01-01.json

Every station is open: a front station (μετωπικός) on the main
carriageway, a side station (πλευρικός) on a junction's ramps, each
charging per passage, by category: 3 for vehicles over 2.20 m high with
two or three axles, 4 for four or more axles (each page's category
list). Each page's table is read as a station name followed by its four
category prices. Prices include 24% VAT (Aegean Motorway's list says so;
Greek motorway tolls carry VAT) and are divided by 1.24.

Stations are matched to the OSM toll booths named "Μετωπικά Διόδια
<name>" / "Πλευρικά Διόδια <name>" (front / side; names compared without
accents), the pages' names put in the genitive OSM uses where they differ
(NAMES). A booth on a one-way road (a ramp, or one carriageway) charges
that direction; booths on two-way roads charge both ways and are merged.
"""
import html, json, math, os, re, sys, unicodedata

PAGES = [("olympia", "Ολυμπία Οδός"), ("neaodos", "Νέα Οδός"), ("kentriki", "Κεντρική Οδός"),
         ("moreas", "Μορέας"), ("aegean", "Αυτοκινητόδρομος Αιγαίου")]
# Page names (nominative or abbreviated) -> the genitive the OSM booths use.
NAMES = {"Ελευσίνα": "Ελευσίνας", "Ισθμός": "Ισθμού", "Κιάτο": "Κιάτου", "Ελαιώνας": "Ελαιώνα", "Ρίο": "Ρίου",
         "Πάτρα": "Πάτρας", "Πύργος": "Πύργου", "Νέα Πέραμος": "Νέας Περάμου", "Πάχη": "Πάχης",
         "Αγ. Θεόδωροι": "Αγίων Θεοδώρων", "Ζευγολατιό": "Ζευγολατιού", "Δερβένι": "Δερβενίου", "Ακράτα": "Ακράτας",
         "Καλάβρυτα": "Καλαβρύτων", "Δρέπανο": "Δρεπάνου", "Κάτω Αχαΐα": "Κάτω Αχαΐας", "Αμαλιάδα": "Αμαλιάδας",
         "Αγ. Μαρίνας": "Αγίας Μαρίνας", "Μ. Μοναστηρίου": "Μεγάλου Μοναστηρίου"}
VAT = 1.24
PRICE = re.compile(r"^\d+(,\d+)?\s*€?$")


def plain(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").lower()


def cells(path):
    t = open(path, encoding="utf-8").read()
    t = re.sub(r"<(script|style).*?</\1>", "", t, flags=re.S)
    t = re.sub(r"<(td|th|tr|p|h\d|li|div|br|span)[^>]*>", "\n", t)
    t = html.unescape(re.sub(r"<[^>]+>", "", t)).replace("​", "").replace("\xa0", " ")
    return [re.sub(r"\s+", " ", x).strip() for x in t.split("\n") if x.strip()]


def euros(s):
    return float(s.replace("€", "").strip().replace(",", "."))


def stations(path):
    c = cells(path)
    out = []
    for i in range(len(c) - 4):
        m = re.match(r"^(\D+?) (\d+,\d+) (\d+,\d+) (\d+,\d+) (\d+,\d+)$", c[i])
        if m:
            out.append((m.group(1), euros(m.group(4)), euros(m.group(5))))
        elif not PRICE.match(c[i]) and all(PRICE.match(x) for x in c[i + 1:i + 5]):
            out.append((c[i], euros(c[i + 3]), euros(c[i + 4])))
    return out


def split(name):
    """(front or side, stem) from a page's station name."""
    side = bool(re.match(r"Πλευρικ", name)) or bool(re.search(r"\((Π|Α)\)", name))
    stem = re.sub(r"^(Μετωπικ\w+|Πλευρικ\w+)( Διόδια)? ", "", name)
    stem = re.sub(r"\s*\(.*?\)\s*$", "", stem).strip()
    return ("side" if side else "front"), NAMES.get(stem, stem)


def heading(a, b):
    return round(math.degrees(math.atan2((b[0] - a[0]) * math.cos(math.radians(a[1])), b[1] - a[1])) % 360, 1)


def main(fetched, out):
    booths, ways = {}, []
    for line in open(os.path.join(fetched, "gr-osm.geojsonseq"), encoding="utf-8"):
        f = json.loads(line.strip("\x1e"))
        p, g = f["properties"], f["geometry"]
        if p.get("barrier") == "toll_booth" and g["type"] == "Point" and p.get("name"):
            m = re.match(r"^(Μετωπικ\w+|Πλευρικ\w+)( Διόδια| Σταθμός Διοδίων)? (.+?)( [\d,]+\s*€)?$", p["name"])
            if m:
                kind = "side" if m.group(1).startswith("Πλευρ") else "front"
                booths.setdefault((kind, plain(m.group(3))), []).append(tuple(g["coordinates"]))
        elif p.get("highway") and g["type"] == "LineString":
            ways.append((p.get("oneway") == "yes", [tuple(x) for x in g["coordinates"]]))
    on_oneway = {}
    for oneway, cs in ways:
        if oneway:
            for i, x in enumerate(cs):
                on_oneway[x] = heading(cs[i - 1], x) if i > 0 else heading(x, cs[i + 1])
    points, missing = [], []
    for sid, operator in PAGES:
        for name, c3, c4 in stations(os.path.join(fetched, f"gr-{sid}.html")):
            kind, stem = split(name)
            bs = booths.get((kind, plain(stem)))
            if not bs:
                missing.append(f"{operator}: {name}")
                continue
            classes = [{"min_kg": 3501, "max_axles": 3, "rate": round(c3 / VAT, 4)}, {"min_kg": 3501, "min_axles": 4, "rate": round(c4 / VAT, 4)}]
            headed = [(b, on_oneway[b]) for b in bs if b in on_oneway]
            both = [b for b in bs if b not in on_oneway]
            if both:
                headed.append(((sum(b[0] for b in both) / len(both), sum(b[1] for b in both) / len(both)), None))
            label = f"{operator}: {'Μετωπικός' if kind == 'front' else 'Πλευρικός'} {stem}"
            for b, h in headed:
                tp = {"name": label, "lat": round(b[1], 6), "lon": round(b[0], 6)}
                if h is not None:
                    tp["heading"] = h
                tp.update(rate=0, classes=classes)
                points.append(tp)
    if missing:
        print("not in OpenStreetMap:", "; ".join(missing))
    tb = {
        "country": "GR", "currency": "EUR", "valid_from": "2026-01-01", "valid_to": "2026-12-31",
        "name": "Greek motorway tolls (open toll stations)",
        "law": "The concession agreements ratified by law (e.g. ν. 3559/2007 for Moreas), prices for 2026 as published by each concession company: Olympia Odos, Nea Odos, Kentriki Odos, Moreas and Aegean Motorway. Per passage of a front or side station, category 3 (over 2.20 m, two or three axles) and 4 (four or more axles), excluding 24% VAT. Within a toll zone a trip pays one station only, as the stations are placed. Stations placed with OpenStreetMap's toll booths; Egnatia Odos and Attiki Odos aren't included.",
        "sources": [{"title": "Olympia Odos: Τιμές διοδίων", "url": "https://www.olympiaodos.gr/Diodia-OLYMPIA-PASS/Times-diodion/"},
                    {"title": "Nea Odos: Διόδια Τέλη", "url": "https://www.neaodos.gr/highways/tolls/"},
                    {"title": "Kentriki Odos: Διόδια Τέλη", "url": "https://www.kentrikiodos.gr/highways/toll-fees/"},
                    {"title": "Moreas: Διόδια", "url": "https://www.moreas.com.gr/leitourgia/diodia"},
                    {"title": "Aegean Motorway: Τιμές Διοδίων 2026", "url": "https://www.aegeanmotorway.gr/travel-info/diodia/times-diodiwn-2/"},
                    {"title": "OpenStreetMap (Geofabrik extract), toll booths", "url": "https://download.geofabrik.de/europe/greece.html"}],
        "vehicles": "Vehicles over 3,500 kg (categories 3 and 4)",
        "min_kg": 3501,
        "tolled_roads": "A1 (Metamorfosi–Kleidi), A8 (Elefsina–Patra–Pyrgos), A5 Ionia Odos, A7 (Korinthos–Kalamata, Lefktro–Sparti), E65.",
        "point_match_km": 0.1,
        "toll_points": points,
        "rows": [],
    }
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, "gr-2026-01-01.json")
    json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, len(points), "booth points")


if __name__ == "__main__":
    main(*sys.argv[1:])
