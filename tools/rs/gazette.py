"""Serbia's toll (putarina) tables from the decision itself: the Odluka o
visini posebne naknade za upotrebu javnog puta, njegovog dela i putnog
objekta (putarina), as each amendment printed its tables in the Official
Gazette (Službeni glasnik RS, served by pravno-informacioni-sistem.rs).
Each amendment replaces the decision's paragraph 1 whole: per
characteristic motorway section, the toll in RSD from each station to each
other, by vehicle category. The tables are scans; gazette_ocr.py reads
categories III and IV out of an issue (with the pairs it couldn't read for
certain, which are left out).

Stations are placed at Serbia's OpenStreetMap toll booths of the same name
(the tables workflow's rs-osm.geojsonseq); "Београд" is, by section, the
booths Putevi Srbije's price list calls Beograd: Šimanovci (A3), Stara
Pazova (A1 north), Beograd (A1 south).

Putevi Srbije's price list prints, besides its EUR column, the decision's
RSD amounts from six entry stations: check() holds a table to it, every
pair both have.

Used by tools/tables/rs.py (the amendment in force) and
tools/history/build_rs_gazette.py (the earlier ones).
"""
import datetime, difflib, importlib.util, json, os, re, sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("rs_build", os.path.join(HERE, "build.py"))
rs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rs)

ELI = "https://pravno-informacioni-sistem.rs/eli/rep/sgrs/drugeorganizacije/odluka/2019/40/1/reg"
MONTHS = {"јануара": 1, "фебруара": 2, "марта": 3, "априла": 4, "маја": 5, "јуна": 6, "јула": 7, "августа": 8,
          "септембра": 9, "октобра": 10, "новембра": 11, "децембра": 12}
# Each section by a station only it has: its system, and the booths its
# "Београд" is.
SECTIONS = [("шид", "A3 Beograd – Šid", "šimanovci"), ("суботиц", "A1 Beograd – Subotica", "stara pazova"),
            ("прешев", "A1, A4 Beograd – Niš – Preševo / Dimitrovgrad", "beograd"), ("обреновац", "A2 Beograd – Požega", None)]
# Gazette names -> the OpenStreetMap booths' (as tools/rs/build.py keys them).
FIX = {"адашевци/моровић": "adaševci", "прељина": "preljina konjevići", "прељина југ": "preljina konjevići",
       "ниш малча": "malča", "нови сад север": "novi sad - sever", "нови сад југ": "novi sad - jug"}
GROUPS = [{"name": "K3", "min_kg": 3501, "max_axles": 3}, {"name": "K4", "min_kg": 3501, "min_axles": 4}]


def booths(path):
    """Serbia's OpenStreetMap toll booths by name (as tools/rs/build.py keys them)."""
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


def clean(label):
    return re.sub(r"\s+", " ", re.sub(r"[^\w/ ]", " ", label)).strip()


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


def application(pdf):
    """The amendment's closing sentence: when it applies (the issue's text layer)."""
    import fitz
    doc = fitz.open(pdf)
    text = re.sub(r"-\s+", "", re.sub(r"\s+", " ", " ".join(p.get_text() for p in doc)))
    for m in re.finditer(r"Ова [оОo]длука[^.]{0,60}сагласности Владе.{0,400}?године(?:, (?:сем|изузев|осим).{0,300}?године)?", text):
        if "примењ" in m.group(0):
            return m.group(0)
    return ""


def datetime_of(sentence):
    m = re.search(r"примењује(?: се)? (?:од )?(\d{1,2})\. (\w+) (\d{4})", sentence)
    if not m or m.group(2) not in MONTHS:
        return None
    return f"{m.group(3)}-{MONTHS[m.group(2)]:02d}-{int(m.group(1)):02d}"


def periods(start, nxt, later):
    """(first day, last day or None, booths left out) of each table an
    amendment makes: until the next one (nxt; None while it is in force),
    split where some stations start later."""
    day = datetime.date.fromisoformat
    end = (day(nxt) - datetime.timedelta(days=1)).isoformat() if nxt else None
    if not later:
        return [(start, end, set())]
    then = min(later.values())
    return [(start, (day(then) - datetime.timedelta(days=1)).isoformat(), {rs.key(n.lower()) for n in later}), (then, end, set())]


def tables(g, pdf, sid, issue, url, start, nxt, later, bs):
    """The tables an amendment makes (gazette_ocr.py's reading g of the
    issue pdf), each with its first day."""
    applies = application(pdf)
    d = datetime_of(applies)
    if d != start:
        sys.exit(f"{sid}: the amendment applies from {d} ({applies[:200]!r}), not {start}")
    for name in later:
        if name not in applies:
            sys.exit(f"{sid}: the amendment doesn't say {name} applies later")
    systems, unread, mapping = [], 0, {}
    for s in g["sections"]:
        reads = s.get("readings") or [[x] for x in s["stations"]]
        low = " ".join(x for r in reads for x in r).lower()
        sec = next(((n, b) for k, n, b in SECTIONS if k in low), None)
        if sec is None:
            sys.exit(f"{sid}: a section the builder doesn't know: {s['section']!r}")
        system, beograd = sec
        names, points = [], []
        for label, r in zip(s["stations"], reads):
            k = booth(r, bs, beograd)
            if k is None:
                sys.exit(f"{sid}: {system}: no OpenStreetMap booth for {r!r}")
            names.append(k.upper())
            points.append(bs[k])
            mapping[label] = k
        if len(set(names)) != len(names):
            sys.exit(f"{sid}: {system}: two stations read alike: {names}")
        systems.append({"system": system, "names": names, "points": points, "III": s["III"], "IV": s["IV"]})
        unread += len(s["unread"])
    have = sorted(sy["system"] for sy in systems)
    if have != sorted(n for _, n, _ in SECTIONS):
        sys.exit(f"{sid}: the sections read are {have}, not the decision's four")
    print(sid, "names:", {k: v for k, v in mapping.items() if rs.key(clean(k).lower()) != v})
    out = []
    for first, last, excl in periods(start, nxt, later):
        cs = []
        for sy in systems:
            prices = {}
            for pair in sorted(set(sy["III"]) | set(sy["IV"])):
                i, j = map(int, pair.split("|"))
                if any(sy["names"][x].lower() in excl for x in (i, j)):
                    continue
                # A category read for certain is kept even where the other wasn't.
                prices[f"{sy['names'][i]}|{sy['names'][j]}"] = {gr: sy[c][pair] for gr, c in (("K3", "III"), ("K4", "IV")) if pair in sy[c]}
            used = sorted({n for k in prices for n in k.split("|")})
            cs.append({"name": sy["system"],
                       "law": f"Odluka o visini posebne naknade za upotrebu javnog puta, njegovog dela i putnog objekta (putarina), as amended in Službeni glasnik RS {issue}: RSD from entry to exit station; vehicle categories III (2-3 axles over 3.5 t) and IV (4 or more axles)",
                       "groups": GROUPS,
                       "stations": [{"name": n, "points": sy["points"][sy["names"].index(n)]} for n in used],
                       "prices": prices})
        tb = {"country": "RS", "currency": "RSD", "valid_from": first}
        if last:
            tb["valid_to"] = last
        tb.update({
            "name": "Serbian motorway toll (putarina)",
            "law": (f"JP Putevi Srbije's Odluka o visini posebne naknade za upotrebu javnog puta, njegovog dela i putnog objekta (putarina), "
                    f"with the Government's consent, as amended in Službeni glasnik RS {issue} (applying from {start}" +
                    (", " + " and ".join(rs.lat(n) for n in later) + f" from {list(later.values())[0]}" if later else "") +
                    "): the toll in RSD from entry to exit station on each characteristic section, by vehicle category" +
                    (f"; in force until {last}" if last else "") + ". "
                    "The decision's tables are scans: read by OCR (tools/rs/gazette_ocr.py), each price checked against its mirror cell "
                    "and category IV against III" + (f"; {unread} pairs where a category couldn't be read for certain have no price for it" if unread else "") +
                    ". Stations placed at OpenStreetMap's toll booths of their name. The Belgrade bypass (category IV per section) is its own table."),
            "sources": [{"title": f"Službeni glasnik RS {issue}: Odluka o izmeni i dopuni Odluke o visini posebne naknade za upotrebu javnog puta, njegovog dela i putnog objekta (putarina)",
                         "url": url},
                        {"title": "Pravno-informacioni sistem RS: Odluka o visini posebne naknade ... (putarina), its amendments", "url": ELI},
                        {"title": "OpenStreetMap (Geofabrik extract), toll booths", "url": "https://download.geofabrik.de/europe/serbia.html"}],
            "vehicles": "Vehicles over 3.5 t (categories III and IV)", "min_kg": 3501,
            "tolled_roads": "Motorways A1 (Subotica–Beograd–Preševo), A2 (Obrenovac–Požega), A3 (Šid–Beograd), A4 (Niš–Dimitrovgrad) and the Morava corridor, as the decision's sections.",
            "closed_systems": cs})
        print(f"rs-{first}", first, last, sum(len(c["prices"]) for c in cs), "prices,", unread, "unread")
        out.append((first, tb))
    return out


def check(tb, list_txt, what, known=()):
    """Holds a table to a price list's RSD amounts (pdftotext -layout text):
    every pair both have must be the same, but for known differences
    ((entry, exit, category) where the list isn't the decision's amount,
    looked at in the scan); most of the list's pairs must be in the table."""
    listed = {}
    for sys_name, prs in rs.prices(list_txt, rsd=True).items():
        for k, v in prs.items():
            a, b = (rs.keys_of(x) for x in k.split("|"))
            if len(a) == 1 and len(b) == 1:
                listed[(a[0].upper(), b[0].upper())] = v
    have = {}
    for c in tb["closed_systems"]:
        for k, v in c["prices"].items():
            a, b = k.split("|")
            have[(a, b)] = have[(b, a)] = v
    same, bad, missing = 0, [], []
    for k, v in listed.items():
        if k not in have:
            missing.append(k)
            continue
        for g in ("K3", "K4"):
            if g in have[k]:
                if have[k][g] == v[g]:
                    same += 1
                elif (k[0], k[1], g) in known or (k[1], k[0], g) in known:
                    print(f"{what}: {k} {g}: the decision {have[k][g]}, the price list {v[g]} (known)")
                else:
                    bad.append((k, g, have[k][g], v[g]))
    print(f"{what}: {same} amounts the same as the price list's, {len(bad)} not, {len(missing)} of its {len(listed)} pairs not in the table")
    if bad or len(missing) > 0.1 * len(listed):
        sys.exit(f"{what}: the decision's table and the price list differ: {bad[:10]} missing {missing[:10]}")
