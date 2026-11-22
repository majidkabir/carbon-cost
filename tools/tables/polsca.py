"""Builds POLSCA Baltic Ferries' ferries for trucks (Polferries and Unity
Line under one tariff since 30 March 2026): Świnoujście–Ystad,
Świnoujście–Trelleborg, Gdańsk–Nynäshamn and, from 6 July 2026,
Gdańsk–Karlshamn (polsca-<date>.json, one per tariff edition or BES
announcement), from

- the freight tariffs (polsca-tariff-*.pdf, as text: the edition the
  tariff page on unityline.eu links, its date on the page and in the
  file's name, and the 30 March 2026 edition, polsca-tariff-2026-03-30):
  one way, EUR net, the same both ways; per unit for trucks up to 7 m
  and over 7 to 9 m (1.2, 1.3), per commenced metre for heavy goods
  vehicles over 9 m (1.4), the freight including one driver, a cabin
  place and two meals;
- the bunker-environmental surcharge announcements (polsca-bes-*.pdf, as
  text): per commenced metre of the vehicle's length, by route, from a
  date until further notice (the first one for 30 and 31 March only);
- OpenStreetMap (polsca-osm.json, Overpass): the ferry lines and terminals.

carbon-cost prices a trip with cargo, accompanied, by the truck's length
(truck.length_m) in whole metres up: the freight plus the BES per metre.
The ETS surcharge (polsca-ets-*) isn't added: carbon-cost prices the EU
ETS on a crossing itself, from the ships' MRV data (eua_eur_per_t). The
weight and width surcharges are for general cargo and over-standard
vehicles and aren't applied. TT-Line sails Świnoujście–Trelleborg too;
its freight rates aren't published, so a trip there is priced at
POLSCA's. A route is priced from the first day both its tariff column
and its BES are in force.

Usage: python3 polsca.py <fetched dir> <out dir>
"""
import datetime, glob, html, json, os, re, sys

from ferry_osm import MATCH_KM, lines_of, port_places, systems as place_systems

NAMES = {"SY": "Świnoujście–Ystad and Świnoujście–Trelleborg", "GN": "Gdańsk–Nynäshamn", "GK": "Gdańsk–Karlshamn"}
PORTS = {"Świnoujście": ("terminal", "Terminal Promowy Świnoujście"), "Ystad": ("terminal", "Ystad"), "Trelleborg": ("terminal", "Terminal C"),
         "Gdańsk": ("terminal", "Polferries Terminal Promowy Westerplatte"), "Nynäshamn": ("terminal", "Nynäshamn"),
         "Karlshamn": ("terminal", "Stillerydshamnen")}
ROUTES = {"Świnoujście–Ystad": [("Świnoujście", "Ystad")], "Świnoujście–Trelleborg": [("Świnoujście", "Trelleborg")],
          "Gdańsk–Nynäshamn": [("Gdańsk", "Nynäshamn")], "Gdańsk–Karlshamn": [("Gdańsk", "Karlshamn")]}
PAIRS = {"Świnoujście|Ystad": "SY", "Świnoujście|Trelleborg": "SY", "Gdańsk|Nynäshamn": "GN", "Gdańsk|Karlshamn": "GK"}
LENGTHS = list(range(4, 27))  # groups: up to 4 m, then each metre to 26 m (the tariff's maximum length)
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
EUR = r"€\s*(\d{1,3}(?: \d{3})*,\d\d)"
TARIFF_URL = "https://www.unityline.eu/cargo/documents-polsca/freight-tariff"
BES_URL = "https://www.unityline.eu/cargo/documents-polsca/bs-bunker-surcharge-announcement"


def read(path):
    return open(path, encoding="utf-8").read()


def flat(t):
    return re.sub(r"\s+", " ", t)


def eur(s):
    return float(s.replace(" ", "").replace(",", "."))


def iso(y, m, d):
    return datetime.date(int(y), int(m), int(d)).isoformat()


def tariff(name, t):
    """An edition: (from, {route: (up to 7 m, over 7 to 9 m, per commenced metre over 9 m)})."""
    m = re.search(r"(\d\d)\.(\d\d)\.(\d{4})\.pdf$", name.replace(".txt", ".pdf")) or re.search(r"(\d{4})-(\d\d)-(\d\d)", name)
    if not m:
        sys.exit(f"POLSCA: {name}: no date in the file's name")
    d = iso(*m.groups()[::-1]) if len(m.group(1)) == 2 else iso(*m.groups())
    f = flat(t)
    if "FREIGHT TARIFF POLSCA Baltic Ferries" not in f or "Rates are expressed in EUR (euro) net" not in f or "Rates are for a one-way journey" not in f:
        sys.exit(f"POLSCA: {name}: not a POLSCA freight tariff in EUR net, one way")
    for label in ("Trucks up to 7 meters long per", "Trucks over 7 to 9 meters in", "Heavy goods vehicles over 9", "commenced meter of the vehicle"):
        if label not in f:
            sys.exit(f"POLSCA: {name}: {label!r} not found")
    head = f[:f.find("GENERAL PROVISIONS")]
    cols = ["SY", "GN"] + (["GK"] if "Gdańsk – Karlshamn and Karlshamn – Gdańsk" in head else [])
    if "Świnoujście – Ystad and Ystad – Świnoujście" not in head or "Gdańsk – Nynäshamn and Nynäshamn – Gdańsk" not in head:
        sys.exit(f"POLSCA: {name}: the connections aren't Świnoujście–Ystad/Trelleborg and Gdańsk–Nynäshamn")
    rows = {}
    for item in ("1.2", "1.3", "1.4"):
        line = next((ln for ln in t.splitlines() if re.match(r"\s*" + re.escape(item) + r"\.\s", ln)), None)
        vals = [eur(x) for x in re.findall(EUR, line or "")]
        if len(vals) != len(cols):
            sys.exit(f"POLSCA: {name}: item {item}: {vals} for columns {cols}")
        rows[item] = vals
    return d, {c: tuple(rows[i][k] for i in ("1.2", "1.3", "1.4")) for k, c in enumerate(cols)}


def bes(name, t):
    """An announcement: (from, to or None, {route: EUR per commenced metre})."""
    f = flat(t).replace("ś", "s").replace("Ś", "S").replace("–", "-")
    month = "(" + "|".join(MONTHS) + ")"
    to = None
    m = re.search(r"effective from " + month + r" (\d{1,2}), (\d{4})", f)
    if m:
        d = iso(m.group(3), MONTHS.index(m.group(1)) + 1, m.group(2))
    elif re.search(r"effective (\d{1,2}) " + month + r" (\d{4})", f):
        m = re.search(r"effective (\d{1,2}) " + month + r" (\d{4})", f)
        d = iso(m.group(3), MONTHS.index(m.group(2)) + 1, m.group(1))
    elif re.search(r"effective from (\d\d)\.(\d\d)\.(\d{4})", f):
        d = iso(*re.search(r"effective from (\d\d)\.(\d\d)\.(\d{4})", f).groups()[::-1])
    elif re.search(r"on " + month + r" (\d{1,2}) and (\d{1,2}), the fuel surcharge", f):
        m = re.search(r"on " + month + r" (\d{1,2}) and (\d{1,2}), the fuel surcharge", f)
        y = re.search(r"Swinoujscie, \d\d\.\d\d\.(\d{4})", f).group(1)
        d, to = iso(y, MONTHS.index(m.group(1)) + 1, m.group(2)), iso(y, MONTHS.index(m.group(1)) + 1, m.group(3))
    else:
        sys.exit(f"POLSCA: {name}: no date found")
    per = {}
    for r, label in (("SY", r"on Swinoujscie-Ystad & Swinoujscie-Trelleborg link - "), ("GK", r"on Gdansk-Karlshamn link - "),
                     ("GN", r"on Gdansk-Nynashamn link - "), ("GK", r"on the newly launched Gdansk-Karlshamn route will be ")):
        v = re.search(label + r"(\d+,\d\d) EUR per each commenced (?:linear|lane) meter", f)
        if v:
            per[r] = eur(v.group(1))
    if not per:
        sys.exit(f"POLSCA: {name}: no rates found")
    return d, to, per


def group_name(m):
    return "up to 4 m" if m == 4 else f"{m - 1}-{m} m"


def main(fetched, out):
    eds = [tariff(os.path.basename(p), read(p)) for p in sorted(glob.glob(os.path.join(fetched, "polsca-tariff-*.txt")))]
    notes_bes = [bes(os.path.basename(p), read(p)) for p in sorted(glob.glob(os.path.join(fetched, "polsca-bes-*.txt")))]
    try:
        osm = json.load(open(os.path.join(fetched, "polsca-osm.json"), encoding="utf-8"))
        page = flat(re.sub(r"<[^>]+>", " ", html.unescape(read(os.path.join(fetched, "polsca-tariff.html")))))
    except (OSError, ValueError) as e:
        print(f"POLSCA: not built ({e})")
        return
    if not eds or not notes_bes:
        print(f"POLSCA: {len(eds)} tariffs, {len(notes_bes)} BES announcements; not built")
        return
    m = re.search(r"Valid from (\d{1,2}) (\w+) (\d{4}) until further notice", page)
    if not m or iso(m.group(3), MONTHS.index(m.group(2)) + 1, m.group(1)) not in [d for d, _ in eds]:
        sys.exit("POLSCA: the tariff page's edition isn't one read here")
    eds.sort()
    notes_bes.sort()
    for (d1, to, _), (d2, _, _) in zip(notes_bes, notes_bes[1:]):
        if to and (datetime.date.fromisoformat(to) + datetime.timedelta(days=1)).isoformat() != d2:
            sys.exit(f"POLSCA: the BES from {d1} ends {to}, the next is from {d2}")
    lines, permit = lines_of(osm)
    pos = port_places(osm, lines, PORTS)
    missing = [p for p in PORTS if p not in pos]
    if missing:
        sys.exit(f"POLSCA: ports not placed: {missing}")
    placed, notes = place_systems(ROUTES, pos, lines, permit, lambda msg: sys.exit(f"POLSCA: {msg}"))
    groups = [{"name": group_name(m), "min_kg": 3501, "max_length_m": m, **({"min_length_m": m - 1} if m > 4 else {})} for m in LENGTHS]
    days = sorted({d for d, _ in eds} | {d for d, _, _ in notes_bes if d >= eds[0][0]})
    for k, day in enumerate(days):
        until = (datetime.date.fromisoformat(days[k + 1]) - datetime.timedelta(days=1)).isoformat() if k + 1 < len(days) else None
        ed_from, rates = [e for e in eds if e[0] <= day][-1]
        per, since = {}, {}
        for d, _, p in notes_bes:
            if d <= day:
                for r, v in p.items():
                    per[r], since[r] = v, d
        routes = [r for r in ("SY", "GN", "GK") if r in rates and r in per]
        fare = lambda r, m: rates[r][0] if m <= 7 else rates[r][1] if m <= 9 else rates[r][2] * m
        systems = []
        for names, stations, _ in placed:
            prices = {p: {group_name(m): round(fare(r, m) + m * per[r], 2) for m in LENGTHS}
                      for p, r in PAIRS.items() if r in routes and all(x in stations for x in p.split("|"))}
            if prices:
                systems.append({"name": "POLSCA Baltic Ferries: " + " / ".join(names), "law": "POLSCA Baltic Ferries' freight tariff and BES, accompanied",
                                "groups": groups, "stations": [{"name": n, "points": pts} for n, pts in sorted(stations.items())],
                                "station_match_km": MATCH_KM, "prices": prices})
        law = (f"POLSCA Baltic Ferries' (Polferries and Unity Line) freight tariff valid from {ed_from}, one way, EUR net, the same both ways: "
               + "; ".join(f"{NAMES[r]}: trucks up to 7 m EUR {rates[r][0]:g} and over 7 to 9 m EUR {rates[r][1]:g} per unit, heavy goods vehicles "
                           f"over 9 m EUR {rates[r][2]:g} per commenced metre" for r in routes)
               + ", including one driver, a cabin place and two meals; by the truck's length in whole metres up. With the bunker-environmental surcharge "
               "(BES) per commenced metre: " + ", ".join(f"{NAMES[r]} EUR {per[r]:g} (from {since[r]})" for r in routes)
               + ". The ETS surcharge isn't added: carbon-cost prices the EU ETS on a crossing from the ships' MRV data. The weight and width "
               "surcharges (general cargo, over-standard vehicles) aren't applied. TT-Line sails Świnoujście–Trelleborg too; its freight rates "
               "aren't published, so that crossing is priced at POLSCA's. Ports at OpenStreetMap's ferry terminals, priced where the line goes out "
               "on its car ferry line." + "".join(f" {x}." for x in notes))
        crossings = [n for r in routes for n in ({"SY": ["Świnoujście–Ystad", "Świnoujście–Trelleborg"], "GN": ["Gdańsk–Nynäshamn"], "GK": ["Gdańsk–Karlshamn"]}[r])]
        d = {"country": "PL", "currency": "EUR", "valid_from": day, **({"valid_to": until} if until else {}), "crossings": True, "ferry": True,
             "name": "POLSCA Baltic Ferries' (Polferries, Unity Line) ferries " + ", ".join(crossings[:-1]) + " and " + crossings[-1] + ", trucks",
             "law": law,
             "sources": [{"title": "POLSCA Baltic Ferries (Unity Line): freight tariff", "url": TARIFF_URL},
                         {"title": "POLSCA Baltic Ferries (Unity Line): BES announcements", "url": BES_URL},
                         {"title": "OpenStreetMap (Overpass API): ferry lines and terminals", "url": "https://www.openstreetmap.org/"}],
             "vehicles": "Trucks over 3.5 t, by length (truck.length_m)", "min_kg": 3501,
             "tolled_roads": "The ferries " + ", ".join(crossings[:-1]) + " and " + crossings[-1] + ".",
             "closed_systems": systems, "rows": []}
        os.makedirs(out, exist_ok=True)
        path = os.path.join(out, f"polsca-{day}.json")
        json.dump(d, open(path, "w"), ensure_ascii=False, indent=1)
        print(path, ed_from, per, [(s["name"], {p: v["16-17 m"] for p, v in s["prices"].items()}) for s in systems], notes)


if __name__ == "__main__":
    main(*sys.argv[1:])
