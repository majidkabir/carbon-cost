"""Builds Polferries' (Polska Żegluga Bałtycka, POLSCA Baltic Ferries)
ferries for trucks: Świnoujście–Ystad, Świnoujście–Trelleborg,
Gdańsk–Nynäshamn and Gdańsk–Karlshamn (polferries-<date>.json), from

- the freight tariff (pol-tariff.html): one way, EUR net, the same both
  ways; per unit for trucks up to 7 m and over 7 to 9 m (1.2, 1.3), per
  commenced metre for heavy goods vehicles over 9 m (1.4), the freight
  including one driver, a cabin place and two meals; the page gives no
  date, and the carrier may change it without notice;
- the bunker-environmental surcharge (pol-bes.html): per commenced metre
  of the vehicle's length, by route, with the date each set applies from
  ("until further notice");
- OpenStreetMap (pol-osm.json, Overpass): the ferry lines and terminals.

carbon-cost prices a trip with cargo, accompanied, by the truck's length
(truck.length_m) in whole metres up: the freight plus the BES per metre.
The ETS surcharge (pol-ets.html) isn't added: carbon-cost prices the EU
ETS on a crossing itself, from the ships' MRV data (eua_eur_per_t). The
weight and width surcharges are for general cargo and over-standard
vehicles and aren't applied. Unity Line and TT-Line sail Świnoujście–
Ystad and Świnoujście–Trelleborg too; their freight rates aren't
published, so a trip there is priced at Polferries'.

The tariff page has no date: its rates are taken from the day they were
first read (START), and the builder stops if the page no longer gives
them (a new edition is then added from the day it was seen). A version
per BES set from then on.

Usage: python3 polferries.py <fetched dir> <out dir>
"""
import datetime, html, json, os, re, sys

from ferry_osm import MATCH_KM, lines_of, port_places, systems as place_systems

START = "2026-11-19"  # the day the undated tariff was first read
# The tariff as read on START: (up to 7 m, over 7 to 9 m, per commenced metre over 9 m), EUR.
READ = {"SY": (125.0, 150.0, 25.0), "GN": (250.0, 300.0, 39.0), "GK": (150.0, 180.0, 30.0)}
NAMES = {"SY": "Świnoujście–Ystad and Świnoujście–Trelleborg", "GN": "Gdańsk–Nynäshamn", "GK": "Gdańsk–Karlshamn"}
PORTS = {"Świnoujście": ("terminal", "Terminal Promowy Świnoujście"), "Ystad": ("terminal", "Ystad"), "Trelleborg": ("terminal", "Terminal C"),
         "Gdańsk": ("terminal", "Polferries Terminal Promowy Westerplatte"), "Nynäshamn": ("terminal", "Nynäshamn"),
         "Karlshamn": ("terminal", "Stillerydshamnen")}
ROUTES = {"Świnoujście–Ystad": [("Świnoujście", "Ystad")], "Świnoujście–Trelleborg": [("Świnoujście", "Trelleborg")],
          "Gdańsk–Nynäshamn": [("Gdańsk", "Nynäshamn")], "Gdańsk–Karlshamn": [("Gdańsk", "Karlshamn")]}
PAIRS = {"Świnoujście|Ystad": "SY", "Świnoujście|Trelleborg": "SY", "Gdańsk|Nynäshamn": "GN", "Gdańsk|Karlshamn": "GK"}
LENGTHS = list(range(4, 27))  # groups: up to 4 m, then each metre to 26 m (the tariff's maximum length)
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
E = r"€\s*([\d ]+,\d\d)"


def text(path):
    t = open(path, encoding="utf-8").read()
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", t, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", html.unescape(t))


def eur(s):
    return float(s.replace(" ", "").replace(",", "."))


def tariff(t):
    """{route: (up to 7 m, over 7 to 9 m, per commenced metre over 9 m)} in the tariff's columns
    (Świnoujście–Ystad/Trelleborg, Gdańsk–Nynäshamn, Gdańsk–Karlshamn)."""
    if not re.search(r"Świnoujście – Ystad and Ystad – Świnoujście Świnoujście – Trelleborg and Trelleborg – Świnoujście "
                     r"Gdańsk – Nynäshamn and Nynäshamn – Gdańsk Gdańsk – Karlshamn and Karlshamn – Gdańsk 1\.1\.", t):
        sys.exit("Polferries: the tariff's columns aren't Świnoujście–Ystad/Trelleborg, Gdańsk–Nynäshamn, Gdańsk–Karlshamn")
    if "Rates are expressed in EUR (euro) net" not in t or "Rates are for a one-way journey" not in t:
        sys.exit("Polferries: the tariff no longer says its rates are EUR net, one way")
    rows = {}
    for item, label in (("1.2", r"Trucks up to 7 meters long per unit"), ("1.3", r"Trucks over 7 to 9 meters in length per unit"),
                        ("1.4", r"Heavy goods vehicles over 9 meters in length for each commenced meter of the vehicle")):
        m = re.search(re.escape(item) + r"\. " + label + rf" {E} {E} {E}", t)
        if not m:
            sys.exit(f"Polferries: tariff item {item} not found")
        rows[item] = [eur(x) for x in m.groups()]
    return {r: tuple(rows[i][k] for i in ("1.2", "1.3", "1.4")) for k, r in enumerate(("SY", "GN", "GK"))}


def bes(t):
    """[(from, {route: EUR per commenced metre})], by date."""
    out = []
    for m in re.finditer(r"Rates valid from (\d{1,2}) (\w+) (\d{4}): (.*?)(?=Rates valid from|Contact - for cargo|$)", t):
        d = f"{m.group(3)}-{MONTHS.index(m.group(2)) + 1:02d}-{int(m.group(1)):02d}"
        body, per = m.group(4), {}
        for r, label in (("SY", r"Świnoujście – Ystad and vice versa, and Świnoujście – Trelleborg and vice versa:"),
                         ("GK", r"Gdańsk – Karlshamn and vice versa:"), ("GN", r"Gdańsk – Nynäshamn and vice versa:")):
            v = re.search(label + r" BES for each commenced metre of vehicle length (\d+\.\d+) EUR", body)
            if not v:
                sys.exit(f"Polferries: BES from {d}: {r} not found")
            per[r] = float(v.group(1))
        out.append((d, per))
    if not out:
        sys.exit("Polferries: no BES rates found")
    return sorted(out)


def group_name(m):
    return "up to 4 m" if m == 4 else f"{m - 1}-{m} m"


def main(fetched, out):
    try:
        t, b = text(os.path.join(fetched, "pol-tariff.html")), text(os.path.join(fetched, "pol-bes.html"))
        osm = json.load(open(os.path.join(fetched, "pol-osm.json"), encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"Polferries: not built ({e})")
        return
    rates = tariff(t)
    if rates != READ:
        sys.exit(f"Polferries: the tariff's rates {rates} aren't those read on {START} {READ}: add an edition from the day it changed")
    sets = bes(b)
    # The set in force on START, and each later one.
    first = [s for s in sets if s[0] <= START]
    if not first:
        sys.exit(f"Polferries: no BES set in force on {START}")
    versions = [(START, first[-1][0], first[-1][1])] + [(d, d, per) for d, per in sets if d > START]
    lines, permit = lines_of(osm)
    pos = port_places(osm, lines, PORTS)
    missing = [p for p in PORTS if p not in pos]
    if missing:
        sys.exit(f"Polferries: ports not placed: {missing}")
    placed, notes = place_systems(ROUTES, pos, lines, permit, lambda msg: sys.exit(f"Polferries: {msg}"))
    groups = [{"name": group_name(m), "min_kg": 3501, "max_length_m": m, **({"min_length_m": m - 1} if m > 4 else {})} for m in LENGTHS]

    def fare(r, m):
        small, mid, per = READ[r]
        return small if m <= 7 else mid if m <= 9 else per * m
    for k, (vf, bes_from, per) in enumerate(versions):
        until = (datetime.date.fromisoformat(versions[k + 1][0]) - datetime.timedelta(days=1)).isoformat() if k + 1 < len(versions) else None
        systems = []
        for routes, stations, _ in placed:
            prices = {p: {group_name(m): round(fare(r, m) + m * per[r], 2) for m in LENGTHS}
                      for p, r in PAIRS.items() if all(x in stations for x in p.split("|"))}
            if prices:
                systems.append({"name": "Polferries: " + " / ".join(routes), "law": "Polferries' freight tariff and BES, accompanied",
                                "groups": groups, "stations": [{"name": n, "points": pts} for n, pts in sorted(stations.items())],
                                "station_match_km": MATCH_KM, "prices": prices})
        law = ("Polferries' (POLSCA Baltic Ferries) freight tariff, one way, EUR net, the same both ways (as published, read on " + START + "): "
               + "; ".join(f"{NAMES[r]}: trucks up to 7 m EUR {READ[r][0]:g} and over 7 to 9 m EUR {READ[r][1]:g} per unit, heavy goods vehicles "
                           f"over 9 m EUR {READ[r][2]:g} per commenced metre" for r in ("SY", "GN", "GK"))
               + ", including one driver, a cabin place and two meals; by the truck's length in whole metres up. With the bunker-environmental surcharge "
               f"(BES) per commenced metre valid from {bes_from}: " + ", ".join(f"{NAMES[r]} EUR {per[r]:g}" for r in ("SY", "GN", "GK"))
               + ". The ETS surcharge isn't added: carbon-cost prices the EU ETS on a crossing from the ships' MRV data. The weight and width "
               "surcharges (general cargo, over-standard vehicles) aren't applied. Unity Line and TT-Line sail Świnoujście–Ystad and "
               "Świnoujście–Trelleborg too; their freight rates aren't published, so those crossings are priced at Polferries'. Ports at "
               "OpenStreetMap's ferry terminals, priced where the line goes out on its car ferry line." + "".join(f" {x}." for x in notes))
        d = {"country": "PL", "currency": "EUR", "valid_from": vf, **({"valid_to": until} if until else {}), "crossings": True,
             "name": "Polferries' ferries Świnoujście–Ystad, Świnoujście–Trelleborg, Gdańsk–Nynäshamn and Gdańsk–Karlshamn, trucks",
             "law": law,
             "sources": [{"title": "Polferries: freight tariff", "url": "https://polferries.com/cargo/freight-tariff.html"},
                         {"title": "Polferries: BES surcharge", "url": "https://polferries.com/cargo/bes-surcharge.html"},
                         {"title": "OpenStreetMap (Overpass API): ferry lines and terminals", "url": "https://www.openstreetmap.org/"}],
             "vehicles": "Trucks over 3.5 t, by length (truck.length_m)", "min_kg": 3501,
             "tolled_roads": "The ferries Świnoujście–Ystad, Świnoujście–Trelleborg, Gdańsk–Nynäshamn and Gdańsk–Karlshamn.",
             "closed_systems": systems, "rows": []}
        os.makedirs(out, exist_ok=True)
        path = os.path.join(out, f"polferries-{vf}.json")
        json.dump(d, open(path, "w"), ensure_ascii=False, indent=1)
        print(path, [(s["name"], {p: v["16-17 m"] for p, v in s["prices"].items()}) for s in systems], notes)


if __name__ == "__main__":
    main(*sys.argv[1:])
