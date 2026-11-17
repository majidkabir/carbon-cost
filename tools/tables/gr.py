"""Builds the Greek motorway toll table from the concession companies'
price pages (fetch.py's gr-olympia, gr-neaodos, gr-kentriki, gr-moreas,
gr-aegean, gr-gefyra .html) and the toll booths in OpenStreetMap (the workflow's
gr-osm.geojsonseq, from Geofabrik's Greece extract).

Usage: python3 gr.py fetched/ out-dir -> out-dir/gr-<year>-01-01.json

Every station is open: a front station (μετωπικός) on the main
carriageway, a side station (πλευρικός) on a junction's ramps, each
charging per passage, by category: 3 for vehicles over 2.20 m high with
two or three axles, 4 for four or more axles (each page's category
list). Each page's table is read as a station name followed by its four
category prices. Prices include 24% VAT (Aegean Motorway's list says so;
Greek motorway tolls carry VAT) and are divided by 1.24.

The Rio–Antirrio bridge (Gefyra) charges trucks over 2 m high by axles:
2, 3, 4, 5 and more ("Φορτηγά 3 άξονες € 40,10"), at its toll station
(the OSM booths "Διόδια Γέφυρας Ρίου Αντιρρίου"), either way.

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
         "Αγ. Μαρίνας": "Αγίας Μαρίνας", "Μ. Μοναστηρίου": "Μεγάλου Μοναστηρίου",
         # Moreas's 2024 page names its stations in the nominative.
         "Σπαθοβούνι": "Σπαθοβουνίου", "Νεστάνη": "Νεστάνης", "Γέφυρα Μάναρη": "Γέφυρας Μάναρη", "Βελιγοστή": "Βελιγοστής",
         "Καλαμάτα": "Καλαμάτας", "Πετρίνα": "Πετρίνας",
         # Egnatia Odos (Νέα Εγνατία Οδός's page) -> its OSM booths.
         "Τύρια": "Τύριας", "Παμβώτιδα": "Παμβώτιδας", "Μαλακάσι": "Μαλακασίου", "Ιεροπηγή": "Ιεροπηγής",
         "Σιάτιστα": "Σιάτιστας", "Πολύμυλος": "Πολυμύλου", "Μάλγαρα": "Μαλγάρων", "Εύζωνοι": "Ευζώνων",
         "Ίασμος": "Ιάσμου", "Ανατ. Σιάτιστας": "Σιατίστων", "Καλαμιάς": "Καλαμιά", "Γαληψού / Ορφανού": "Γαληψού-Ορφανίου",
         "Αγ. Ανδρέα": "Αγίου Ανδρέα", "Βαφέϊκα": "Βαφέικων", "Μεστής": "Μέστης", "ΒΙΠΕ Κομοτηνής/Φύλακα": "ΒΙ.ΠΕ. Κομοτηνής"}
# OSM booths named without "Μετωπικ..."/"Πλευρικ...": (front or side, stem).
BOOTHS = {"Εύζωνοι": ("front", "Ευζώνων"), "Σταθμός Διοδίων Προμαχώνα": ("front", "Προμαχώνα")}
BROWSER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "browser")
VAT = 1.24
PRICE = re.compile(r"^\d+([.,]\d+)?\s*€?$")  # 8,95 € (or 8.95 € on older pages)


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


ATTIKI_URL = "https://www.naodos.gr/2025/arthro/nea-attiki-odos-timarithmiki-prosarmogi-diodion-telon-2026/"


def egnatia_attiki(eg, at):
    s = ""
    if eg:
        s += " Egnatia Odos: Νέα Εγνατία Οδός's station list (front stations per direction, side stations by ramp), 'Φορτηγά – Λεωφορεία' as category 3 and '4+ Άξονες' as 4."
    else:
        s += " Egnatia Odos isn't included."
    if at:
        s += " Attiki Odos: one toll per entry (Νέα Αττική Οδός, under article 18.4.1 of its concession agreement), category 5 (over 2.70 m, two or three axles) and 6 (four or more), at each of its booths: as they lie by the main carriageway, a trip pays the first it passes and no other within the hour."
    else:
        s += " Attiki Odos isn't included."
    return s


def page(fetched, sid, year, absent):
    """The text of fetch.py's gr-<sid>.html, or, for the current year only,
    the copy read in Chrome (browser/gr-<sid>.txt) when that wasn't fetched
    or has no prices; with which source it is."""
    p = os.path.join(fetched, f"gr-{sid}.html")
    if os.path.exists(p) and f"gr-{sid}" not in absent:
        t = " ".join(cells(p))
        if re.search(r"\d,\d\d €|\d\.\d\d €", t):
            return t, "fetched"
    if os.path.exists(os.path.join(fetched, "year.txt")):
        print(f"gr-{sid}: no copy of that year's page")
        return None
    b = os.path.join(BROWSER, f"gr-{sid}.txt")
    if not os.path.exists(b):
        print(f"gr-{sid}: not fetched and no browser/gr-{sid}.txt")
        return None
    print(f"gr-{sid}: the copy read in Chrome")
    return re.sub(r"\s+", " ", " ".join(l for l in open(b, encoding="utf-8") if not l.startswith("# "))), "browser"


def heading(a, b):
    return round(math.degrees(math.atan2((b[0] - a[0]) * math.cos(math.radians(a[1])), b[1] - a[1])) % 360, 1)


def main(fetched, out):
    # A past year's pages (tools/history/build_archived.py writes year.txt,
    # and absent.txt for pages it has no copy of).
    year = open(os.path.join(fetched, "year.txt")).read().strip() if os.path.exists(os.path.join(fetched, "year.txt")) else "2026"
    absent = set(open(os.path.join(fetched, "absent.txt")).read().split()) if os.path.exists(os.path.join(fetched, "absent.txt")) else set()
    booths, ways, booths_named, attiki = {}, [], {}, []
    for line in open(os.path.join(fetched, "gr-osm.geojsonseq"), encoding="utf-8"):
        f = json.loads(line.strip("\x1e"))
        p, g = f["properties"], f["geometry"]
        if p.get("barrier") == "toll_booth" and g["type"] == "Point" and p.get("name"):
            booths_named.setdefault(p["name"], []).append(tuple(g["coordinates"]))
            m = re.match(r"^(Μετωπικ\w+|Πλευρικ\w+)( [Δδ]ιόδια| Σταθμός Διοδίων)? (.+?)( [\d,]+\s*€)?$", p["name"])
            if m:
                kind = "side" if m.group(1).startswith("Πλευρ") else "front"
                booths.setdefault((kind, plain(m.group(3))), []).append(tuple(g["coordinates"]))
            elif p["name"] in BOOTHS:
                kind, stem = BOOTHS[p["name"]]
                booths.setdefault((kind, plain(stem)), []).append(tuple(g["coordinates"]))
            if p.get("operator") == "Νέα Αττική Οδός":
                attiki.append((p["name"], tuple(g["coordinates"])))
        elif p.get("highway") and g["type"] == "LineString":
            ways.append((p.get("oneway") == "yes", [tuple(x) for x in g["coordinates"]]))
    on_oneway = {}
    for oneway, cs in ways:
        if oneway:
            for i, x in enumerate(cs):
                on_oneway[x] = heading(cs[i - 1], x) if i > 0 else heading(x, cs[i + 1])
    points, missing = [], []

    def add(name, c3, c4, operator):
        kind, stem = split(name)
        bs = booths.get((kind, plain(stem)))
        if not bs:
            missing.append(f"{operator}: {name}")
            return
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
    for sid, operator in PAGES:
        if f"gr-{sid}" in absent:
            print(f"gr-{sid}: no copy of that year's page")
            continue
        for name, c3, c4 in stations(os.path.join(fetched, f"gr-{sid}.html")):
            add(name, c3, c4, operator)
    # Egnatia Odos: each line "Μετωπικά|Πλευρικά Διόδια <name>" and four prices.
    eg = page(fetched, "egnatia", year, absent)
    used = []
    if eg:
        rows = re.findall(r"(Μετωπικά|Πλευρικά) Διόδια (.+?) ([\d,]+) € ([\d,]+) € ([\d,]+) € ([\d,]+) €", eg[0])
        if len(rows) < 30 or "4+ Άξονες" not in eg[0]:
            sys.exit(f"Egnatia Odos: {len(rows)} stations read")
        used.append(eg[1])
        for kind, name, _, _, c3, c4 in rows:
            add(("Μετωπικά" if kind == "Μετωπικά" else "Πλευρικά") + " Διόδια " + name, euros(c3), euros(c4), "Εγνατία Οδός")
    # Attiki Odos: one price per entry, at every booth of Νέα Αττική Οδός.
    at = page(fetched, "attiki", year, absent)
    if at:
        t = at[0]
        c5 = re.search(r"Κατ\. ?5: .*?συνολικού ύψους μεγαλύτερου των 2,70m με 2 ή 3 άξονες.*? (\d+[.,]\d\d) €", t)
        c6 = re.search(r"Κατ\. ?6: .*?συνολικού ύψους μεγαλύτερου των 2,70m με 4 άξονες ή περισσότερους (\d+[.,]\d\d) €", t)
        if not c5 or not c6 or f"το {year} " not in t:
            sys.exit(f"Attiki Odos: the {year} prices weren't read ({bool(c5)}, {bool(c6)})")
        if not attiki:
            missing.append("Αττική Οδός (no booths of Νέα Αττική Οδός)")
        used.append(at[1])
        classes = [{"min_kg": 3501, "max_axles": 3, "rate": round(euros(c5.group(1)) / VAT, 4)}, {"min_kg": 3501, "min_axles": 4, "rate": round(euros(c6.group(1)) / VAT, 4)}]
        for name, b in attiki:
            tp = {"name": "Αττική Οδός: " + name, "lat": round(b[1], 6), "lon": round(b[0], 6)}
            if b in on_oneway:
                tp["heading"] = on_oneway[b]
            # Its booths lie within metres of the main carriageway, so a
            # trip along it passes them all; it pays once (group, hour).
            tp.update(rate=0, classes=classes, group=1, group_minutes=60)
            points.append(tp)
        print("Attiki Odos:", len(attiki), "booths,", sum(1 for _, b in attiki if b not in on_oneway), "not on a one-way road")
    # The Rio–Antirrio bridge: trucks over 2 m high by axles (2, 3, 4, 5 and more).
    c = " ".join(cells(os.path.join(fetched, "gr-gefyra.html")))
    ax = {int(n): euros(v) for n, v in re.findall(r"(\d) άξονες(?: και άνω)? € ?(\d+,\d\d)", c)}
    if sorted(ax) != [2, 3, 4, 5]:
        sys.exit(f"Gefyra: axle prices {ax}")
    bs = booths_named.get("Διόδια Γέφυρας Ρίου Αντιρρίου")
    if not bs:
        missing.append("Γέφυρα Ρίου–Αντιρρίου")
    else:
        lon, lat = sum(b[0] for b in bs) / len(bs), sum(b[1] for b in bs) / len(bs)
        points.append({"name": "Γέφυρα: Ρίο–Αντίρριο", "lat": round(lat, 6), "lon": round(lon, 6), "rate": 0,
                       "classes": [{"min_kg": 3501, "max_axles": 2, "rate": round(ax[2] / VAT, 4)},
                                   {"min_kg": 3501, "min_axles": 3, "max_axles": 3, "rate": round(ax[3] / VAT, 4)},
                                   {"min_kg": 3501, "min_axles": 4, "max_axles": 4, "rate": round(ax[4] / VAT, 4)},
                                   {"min_kg": 3501, "min_axles": 5, "rate": round(ax[5] / VAT, 4)}]})
    if missing:
        print("not in OpenStreetMap:", "; ".join(missing))
    tb = {
        "country": "GR", "currency": "EUR", "valid_from": f"{year}-01-01", "valid_to": f"{year}-12-31",
        "osm_extract": open(os.path.join(fetched, "gr-osm-timestamp.txt")).read().strip()[:10],
        "name": "Greek motorway tolls (open toll stations)",
        "law": "The concession agreements ratified by law (e.g. ν. 3559/2007 for Moreas), prices for " + year + " as published by each concession company: Olympia Odos, Nea Odos, Kentriki Odos, Moreas and Aegean Motorway, and the Rio–Antirrio bridge (Gefyra, by axles). Per passage of a front or side station, category 3 (over 2.20 m, two or three axles) and 4 (four or more axles), excluding 24% VAT. Within a toll zone a trip pays one station only, as the stations are placed. Stations placed with OpenStreetMap's toll booths." + egnatia_attiki(eg, at),
        "sources": [{"title": "Olympia Odos: Τιμές διοδίων", "url": "https://www.olympiaodos.gr/Diodia-OLYMPIA-PASS/Times-diodion/"},
                    {"title": "Nea Odos: Διόδια Τέλη", "url": "https://www.neaodos.gr/highways/tolls/"},
                    {"title": "Kentriki Odos: Διόδια Τέλη", "url": "https://www.kentrikiodos.gr/highways/toll-fees/"},
                    {"title": "Moreas: Διόδια", "url": "https://www.moreas.com.gr/leitourgia/diodia"},
                    {"title": "Aegean Motorway: Τιμές Διοδίων 2026", "url": "https://www.aegeanmotorway.gr/travel-info/diodia/times-diodiwn-2/"},
                    {"title": "Gefyra: Τιμές Διοδίων (Rio–Antirrio bridge)", "url": "https://www.gefyra.gr/prices/Times-Diodion/"},
                    {"title": "OpenStreetMap (Geofabrik extract), toll booths", "url": "https://download.geofabrik.de/europe/greece.html"}]
                   + ([{"title": "Νέα Εγνατία Οδός: Σταθμοί Διοδίων" + (" (read in Chrome: tools/tables/browser/gr-egnatia.txt)" if eg[1] == "browser" else ""), "url": "https://neodos.gr/stathmoi-diodion/"}] if eg else [])
                   + ([{"title": f"Νέα Αττική Οδός: Τιμαριθμική προσαρμογή διοδίων τελών {year}" + (" (read in Chrome: tools/tables/browser/gr-attiki.txt)" if at[1] == "browser" else ""), "url": ATTIKI_URL}] if at else []),
        "vehicles": "Vehicles over 3,500 kg (categories 3 and 4)",
        "min_kg": 3501,
        "tolled_roads": "A1 (Metamorfosi–Kleidi), A8 (Elefsina–Patra–Pyrgos), A5 Ionia Odos, A7 (Korinthos–Kalamata, Lefktro–Sparti), E65" + (", A2 Egnatia Odos and its vertical axes" if eg else "") + (", Attiki Odos (A6, A62, A64)" if at else "") + ".",
        "point_match_km": 0.1,
        "toll_points": points,
        "rows": [],
    }
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"gr-{year}-01-01.json")
    json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, len(points), "booth points")


if __name__ == "__main__":
    main(*sys.argv[1:])
