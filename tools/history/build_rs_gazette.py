"""Builds Serbia's toll (putarina) tables for the periods no archived price
list covers, from the decision itself: the Odluka o visini posebne
naknade za upotrebu javnog puta, njegovog dela i putnog objekta
(putarina) of JP Putevi Srbije, with the Government's consent, as each
amendment was published in the Official Gazette (Službeni glasnik RS,
served by the state's legal information system,
pravno-informacioni-sistem.rs). Each amendment replaces the decision's
tables whole: per characteristic motorway section, the toll in RSD from
each station to each other, by vehicle category.

The tables are scans; rs_gazette.py reads categories III and IV out of
each issue (fetched/rs-sg-<n>-<year>.json, with the pairs it couldn't read
for certain, which are left out). Each table runs from the day the
amendment says it applies to the day before the next one (an archived
price list, tools/history/build_rs.py, or the next amendment).

Stations are placed at Serbia's OpenStreetMap toll booths (the tables
workflow's rs-osm.geojsonseq) of the same name; "Београд" is, by
section, the booths the current price list calls Beograd: Šimanovci
(A3), Stara Pazova (A1 north), Beograd (A1 south).

Usage: python3 build_rs_gazette.py fetched/ out-dir
"""
import difflib, importlib.util, json, os, re, sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCES = {s["id"]: s["url"] for s in json.load(open(os.path.join(HERE, "sources.json"), encoding="utf-8"))["sources"]}
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location("rs_build", os.path.join(ROOT, "rs", "build.py"))
rs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rs)

MONTHS = {"јануара": 1, "фебруара": 2, "марта": 3, "априла": 4, "маја": 5, "јуна": 6, "јула": 7, "августа": 8,
          "септембра": 9, "октобра": 10, "новембра": 11, "децембра": 12}
# Each amendment: its source, the issue, the day it applies from, the
# day the next table starts, and stations that start later (that day).
ISSUES = [
    ("rs-sg-119-2023", "119/2023", "2024-01-01", "2024-07-10", {}),
    ("rs-sg-107-2024", "107/2024", "2025-01-10", "2025-07-04", {}),
    ("rs-sg-58-2025", "58/2025", "2025-07-04", "2026-01-01", {"Лучани": "2025-07-10", "Прилипац": "2025-07-10"}),
]
# Each section by a station only it has: its system in the current table,
# and the booths its "Београд" is.
SECTIONS = [("шид", "A3 Beograd – Šid", "šimanovci"), ("суботиц", "A1 Beograd – Subotica", "stara pazova"),
            ("прешев", "A1, A4 Beograd – Niš – Preševo / Dimitrovgrad", "beograd"), ("обреновац", "A2 Beograd – Požega", None)]
# Gazette names -> the OpenStreetMap booths' (as tools/rs/build.py keys them).
FIX = {"адашевци/моровић": "adaševci", "прељина": "preljina konjevići", "ниш малча": "malča", "нови сад север": "novi sad - sever",
       "нови сад југ": "novi sad - jug"}


def booths(path):
    out = defaultdict(list)
    for line in open(path, encoding="utf-8"):
        f = json.loads(line.lstrip("\x1e"))
        p = f["properties"]
        if p.get("barrier") != "toll_booth":
            continue
        lon, la = f["geometry"]["coordinates"]
        for n in {p.get("name", ""), p.get("name:sr-Latn", "")}:
            if n:
                pt = {"name": "booth", "lat": round(la, 5), "lon": round(lon, 5)}
                if pt not in out[rs.key(n)]:
                    out[rs.key(n)].append(pt)
    return out


def booth(reads, bs, beograd):
    """The booths a station is: its readings' best match among the booths'
    names (a reading that is a booth's name wins; else the closest, if
    close enough). "Београд" is the section's Beograd booths."""
    best = (0, None)
    for label in reads:
        c = clean(label).lower()
        if c == "београд" and beograd:
            return beograd
        fix = difflib.get_close_matches(c, list(FIX), n=1, cutoff=0.8)
        k = FIX[fix[0]] if fix else rs.key(c)
        if k in bs:
            return k
        for m in difflib.get_close_matches(k, list(bs), n=1, cutoff=0.75):
            r = difflib.SequenceMatcher(None, k, m).ratio()
            if r > best[0]:
                best = (r, m)
    return beograd if best[1] == "beograd" and beograd else best[1]


def clean(label):
    return re.sub(r"\s+", " ", re.sub(r"[^\w/ ]", " ", label)).strip()


def main(fetched, out):
    bs = booths(os.path.join(fetched, "osm", "rs-osm.geojsonseq"))
    os.makedirs(out, exist_ok=True)
    for sid, issue, start, nxt, later in ISSUES:
        path = os.path.join(fetched, sid + ".json")
        if not os.path.exists(path):
            print(f"{sid}: not read (no {sid}.json)")
            continue
        g = json.load(open(path, encoding="utf-8"))
        applies = application(os.path.join(fetched, sid + ".pdf"))
        d = datetime_of(applies)
        if d != start:
            sys.exit(f"{sid}: the amendment applies from {d} ({applies[:200]!r}), not {start}")
        for name, day in later.items():
            if name not in applies:
                sys.exit(f"{sid}: the amendment doesn't say {name} applies later")
        systems, unread, mapping = [], 0, {}
        for s in g["sections"]:
            low = " ".join(x for r in s.get("readings") or [s["stations"]] for x in r).lower()
            sec = next(((n, b) for k, n, b in SECTIONS if k in low), None)
            if sec is None:
                sys.exit(f"{sid}: a section the builder doesn't know: {s['section']!r}")
            system, beograd = sec
            names, points = [], []
            for label, reads in zip(s["stations"], s.get("readings") or [[x] for x in s["stations"]]):
                k = booth(reads, bs, beograd)
                if k is None:
                    sys.exit(f"{sid}: {system}: no OpenStreetMap booth for {reads!r}")
                names.append(k.upper())
                points.append(bs[k])
                mapping[label] = k
            if len(set(names)) != len(names):
                sys.exit(f"{sid}: {system}: two stations read alike: {names}")
            systems.append({"system": system, "names": names, "points": points, "III": s["III"], "IV": s["IV"],
                            "stations": s["stations"]})
            unread += len(s["unread"])
        for first, last, excl in periods(start, nxt, later):
            cs = []
            for sy in systems:
                prices = {}
                for pair in sorted(set(sy["III"]) | set(sy["IV"])):
                    i, j = map(int, pair.split("|"))
                    if any(sy["names"][x].lower() in excl for x in (i, j)):
                        continue
                    # A category read for certain is kept even where the other wasn't.
                    prices[f"{sy['names'][i]}|{sy['names'][j]}"] = {g: sy[c][pair] for g, c in (("K3", "III"), ("K4", "IV")) if pair in sy[c]}
                used = sorted({n for k in prices for n in k.split("|")})
                cs.append({"name": sy["system"],
                           "law": f"Odluka o visini posebne naknade za upotrebu javnog puta, njegovog dela i putnog objekta (putarina), as amended in Službeni glasnik RS {issue}: RSD from entry to exit station; vehicle categories III (2-3 axles over 3.5 t) and IV (4 or more axles)",
                           "groups": [{"name": "K3", "min_kg": 3501, "max_axles": 3}, {"name": "K4", "min_kg": 3501, "min_axles": 4}],
                           "stations": [{"name": n, "points": sy["points"][sy["names"].index(n)]} for n in used],
                           "prices": prices})
            tb = {"country": "RS", "currency": "RSD", "valid_from": first, "valid_to": last,
                  "name": "Serbian motorway toll (putarina)",
                  "law": (f"JP Putevi Srbije's Odluka o visini posebne naknade za upotrebu javnog puta, njegovog dela i putnog objekta (putarina), "
                          f"with the Government's consent, as amended in Službeni glasnik RS {issue} (applying from {start}" +
                          (", " + " and ".join(rs.lat(n) for n in later) + f" from {list(later.values())[0]}" if later else "") +
                          f"): the toll in RSD from entry to exit station on each characteristic section, by vehicle category; in force until {last}. "
                          "The decision's tables are scans: read by OCR (tools/history/rs_gazette.py), each price checked against its mirror cell "
                          "and category IV against III" + (f"; {unread} pairs where a category couldn't be read for certain have no price for it" if unread else "") +
                          ". Stations placed at OpenStreetMap's toll booths of their name."),
                  "sources": [{"title": f"Službeni glasnik RS {issue}: Odluka o izmeni i dopuni Odluke o visini posebne naknade za upotrebu javnog puta, njegovog dela i putnog objekta (putarina)",
                               "url": SOURCES[sid]},
                              {"title": "Pravno-informacioni sistem RS: Odluka o visini posebne naknade ... (putarina), its amendments",
                               "url": "https://pravno-informacioni-sistem.rs/eli/rep/sgrs/drugeorganizacije/odluka/2019/40/1/reg"},
                              {"title": "OpenStreetMap (Geofabrik extract), toll booths", "url": "https://download.geofabrik.de/europe/serbia.html"}],
                  "vehicles": "Vehicles over 3.5 t (categories III and IV)", "min_kg": 3501,
                  "tolled_roads": "Motorways A1 (Subotica–Beograd–Preševo), A2 (Obrenovac–Požega), A3 (Šid–Beograd), A4 (Niš–Dimitrovgrad) and the Morava corridor, as the decision's sections.",
                  "closed_systems": cs}
            p = os.path.join(out, f"rs-{first}.json")
            json.dump(tb, open(p, "w"), ensure_ascii=False, indent=1)
            print(p, first, last, sum(len(c["prices"]) for c in cs), "prices,", unread, "unread")
        print(sid, "names:", {k: v for k, v in mapping.items() if rs.key(clean(k).lower()) != v})


def application(pdf):
    """The amendment's closing sentence: when it applies (the issue's text layer)."""
    import fitz
    doc = fitz.open(pdf)
    text = re.sub(r"-\s+", "", re.sub(r"\s+", " ", " ".join(p.get_text() for p in doc)))
    for m in re.finditer(r"Ова [оo]длука[^.]{0,60}сагласности Владе.{0,400}?године(?:, (?:сем|изузев).{0,300}?године)?", text):
        if "примењ" in m.group(0):
            return m.group(0)
    return ""


def datetime_of(sentence):
    m = re.search(r"примењује(?: се)? (?:од )?(\d{1,2})\. (\w+) (\d{4})", sentence)
    if not m or m.group(2) not in MONTHS:
        return None
    return f"{m.group(3)}-{MONTHS[m.group(2)]:02d}-{int(m.group(1)):02d}"


def periods(start, nxt, later):
    """(first day, last day, stations left out) of each table an amendment makes."""
    import datetime
    day = lambda s: datetime.date.fromisoformat(s)
    end = (day(nxt) - datetime.timedelta(days=1)).isoformat()
    if not later:
        return [(start, end, set())]
    then = min(later.values())
    return [(start, (day(then) - datetime.timedelta(days=1)).isoformat(), {rs.key(n.lower()) for n in later}), (then, end, set())]


if __name__ == "__main__":
    main(*sys.argv[1:])
