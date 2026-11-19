"""Builds Scandlines' ferries Puttgarden–Rødby and Rostock–Gedser and
Øresundslinjen's Helsingør–Helsingborg for trucks, with Scandlines'
transit tickets over both (scandlines-<month>.json, one per month whose
surcharges Scandlines gives), from

- Scandlines' freight tariffs (the PDFs its tariffs page links, fetched as
  scl-tariffs-*.pdf, as text): the gross freight per single crossing,
  excluding VAT, by the unit's length: standard units 10–26 m by the
  metre on Puttgarden–Rødby and Rostock–Gedser, loaded or empty ("Germany
  – Denmark"); the transit tickets Puttgarden–Rødby plus Helsingør–
  Helsingborg and Rostock–Gedser plus Helsingør–Helsingborg, 10–26 m
  ("Transit Germany–Sweden North"); units up to 9 m on all of them ("small
  freight units"); each valid from a date until recall; and
  Øresundslinjen's own tariff for Helsingør–Helsingborg (trucks up to 8,
  13, 16 and 26 m, for a calendar year);
- each month's surcharges notice (scl-surcharges-<yyyy>-<mm>.pdf, as
  text; those the surcharges page no longer links, January to May 2026,
  from the Internet Archive's copies of the PDFs): per commencing metre, at least 7 m, the bunker surcharge (BAF),
  the ETS surcharge and the Green Investment Rate (GIR) on Scandlines'
  routes, and Øresundslinjen's energy and green surcharges;
- OpenStreetMap (scl-osm.json, Overpass): the ferry lines and terminals.

carbon-cost prices a trip with cargo: the loaded rates, by the truck's
length (truck.length_m) in whole metres up (a 16.5 m truck pays the 17 m
rate and 17 commencing metres of surcharges). The ETS surcharge isn't
added: carbon-cost prices the EU ETS on a crossing itself, from the ships'
MRV data (eua_eur_per_t). The routes are one closed system: a trip over
Puttgarden–Rødby (or Rostock–Gedser) and Helsingør–Helsingborg pays the
transit ticket, priced from the first station passed to the last.
Over-length (over 26 m), over-width and over-weight surcharges aren't
applied.

Usage: python3 scandlines.py <fetched dir> <out dir>
"""
import datetime, glob, json, os, re, sys

from ferry_osm import MATCH_KM, lines_of, port_places, systems as place_systems

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
PORTS = {"Puttgarden": ("terminal", "Puttgarden"), "Rødby": ("terminal", "Rødbyhavn"), "Rostock": ("terminal", "Rostock - Gedser"),
         "Gedser": ("terminal", "Gedser Leje 1"), "Helsingør": ("terminal", "Øresundslinjen"), "Helsingborg": ("terminal", "Helsingborg-Helsingør")}
ROUTES = {"Puttgarden–Rødby": [("Puttgarden", "Rødby")], "Rostock–Gedser": [("Rostock", "Gedser")], "Helsingør–Helsingborg": [("Helsingør", "Helsingborg")]}
LENGTHS = list(range(7, 27))  # groups: up to 7 m, then each metre to 26 m
E = r"(\d+,\d\d) EUR"
VV = r"v\s*\.\s*v\s*\."


def eur(s):
    return float(s.replace(".", "").replace(",", "."))


def read(path):
    return open(path, encoding="utf-8").read()


def edition(path, text):
    """An edition's validity: (from, to or None) as ISO dates."""
    m = re.search(r"valid (\d\d) (\w+) (\d{4}) until recall", text)
    if m:
        return f"{m.group(3)}-{MONTHS.index(m.group(2)) + 1:02d}-{m.group(1)}", None
    m = re.search(r"(\d\d)\.(\d\d)\.(\d{4}) - (\d\d)\.(\d\d)\.(\d{4})", text)
    if m:
        a, b = m.groups()[:3], m.groups()[3:]
        return f"{a[2]}-{a[1]}-{a[0]}", f"{b[2]}-{b[1]}-{b[0]}"
    sys.exit(f"Scandlines: {os.path.basename(path)}: its validity not read")


def standard(text):
    """{m: (P-R loaded, R-G loaded)} for 10–26 m, and the GIR per metre (P-R, R-G)."""
    rows = {int(m): (eur(a), eur(c)) for m, a, b, c, d in re.findall(rf"^\s*(\d\d)m\s+{E}\s+{E}\s+{E}\s+{E}\s*$", text, re.M)}
    if sorted(rows) != list(range(10, 27)):
        sys.exit(f"Scandlines: Germany–Denmark rows read: {sorted(rows)}")
    g = re.search(rf"Green Investment Rate \(GIR\) per c/m\s+(?:\d\s+)?{E}\s+{E}", text)
    if not g:
        sys.exit("Scandlines: Germany–Denmark: the GIR not read")
    return rows, (eur(g.group(1)), eur(g.group(2)))


def transit(text):
    rows = {int(m): (eur(a), eur(b)) for m, a, b in re.findall(rf"^\s*(\d\d)m\s+{E}\s+{E}\s*$", text, re.M)}
    if sorted(rows) != list(range(10, 27)):
        sys.exit(f"Scandlines: transit rows read: {sorted(rows)}")
    return rows


def small(text):
    m = re.search(r"small freight units up to 9m\s+" + r"\s+".join([r"(\d+,\d\d)"] * 6), text)
    if not m:
        sys.exit("Scandlines: the small units' rates not read")
    return [eur(x) for x in m.groups()]  # P-R, R-G, P-R + H-H, R-G + H-H, P-R + bridge, R-G + bridge


def oresund(text):
    if "TARIFF I EUR EXCL. VAT (ONE WAY TICKET)" not in text:
        sys.exit("Øresundslinjen: the tariff's heading changed")
    rows = [(int(m), eur(p)) for m, p in re.findall(r"TRUCK UP TO (\d+) M\s+(\d+,\d\d)", text)]
    if [m for m, _ in rows] != [8, 13, 16, 26]:
        sys.exit(f"Øresundslinjen: bands read: {rows}")
    return rows


def surcharges(text):
    """The month a notice starts (yyyy-mm-01) and its surcharges per commencing metre."""
    m = re.search(r"as from 01 (\w+) (\d{4})", text)
    if not m:
        sys.exit("Scandlines: a surcharges notice's month not read")
    month = f"{m.group(2)}-{MONTHS.index(m.group(1)) + 1:02d}-01"
    out = {}
    for key, route in (("PR", "Puttgarden - Rødby"), ("RG", "Rostock - Gedser")):
        r = re.search(rf"{route} {VV}\s+{E}\s+{E}\s+{E}\s+{E}", text)
        if not r:
            sys.exit(f"Scandlines {month}: {route} not read")
        baf, ets, gir, tot = map(eur, r.groups())
        if abs(baf + ets + gir - tot) > 0.005:
            sys.exit(f"Scandlines {month}: {route}: {baf} + {ets} + {gir} isn't {tot}")
        out[key] = {"BAF": baf, "ETS": ets, "GIR": gir}
    r = re.search(rf"Helsingør - Helsingborg {VV}\s+5?\s*{E}\s+---\s+{E}\s+{E}", text)
    if not r:
        sys.exit(f"Scandlines {month}: Helsingør - Helsingborg not read")
    energy, green, tot = map(eur, r.groups())
    if abs(energy + green - tot) > 0.005:
        sys.exit(f"Scandlines {month}: Helsingør - Helsingborg: {energy} + {green} isn't {tot}")
    out["HH"] = {"energy": energy, "green": green}
    for key, route in (("PR", "Puttgarden - Helsingborg"), ("RG", "Rostock - Helsingborg")):
        r = re.search(rf"{route} {VV}\s+{E}\s+{E}\s+{E}\s+{E}\s+{E}\s+{E}", text)
        if not r:
            sys.exit(f"Scandlines {month}: {route} not read")
        v = list(map(eur, r.groups()))
        if v[:3] != [out[key]["BAF"], out[key]["ETS"], out[key]["GIR"]] or v[3:5] != [energy, green] or abs(sum(v[:5]) - v[5]) > 0.005:
            sys.exit(f"Scandlines {month}: {route}: {v} doesn't add up from the single routes")
    return month, out


def in_force(eds, day):
    """The edition in force on a day, or None."""
    ok = [(f, t, d) for f, t, d in eds if f <= day and (t is None or day <= t)]
    return max(ok, key=lambda x: x[0]) if ok else None


def group_name(m):
    return "up to 7 m" if m == 7 else f"{m - 1}-{m} m"


def main(fetched, out):
    try:
        osm = json.load(open(os.path.join(fetched, "scl-osm.json")))
    except (OSError, ValueError):
        print("Scandlines: OpenStreetMap wasn't fetched; not built")
        return
    eds = {"std": [], "transit": [], "small": [], "oresund": []}
    for path in sorted(glob.glob(os.path.join(fetched, "scl-tariffs-*.txt"))):
        name, text = os.path.basename(path), read(path)
        kind = ("std" if "-germany-denmark-10m-" in name else "transit" if "-transit-sweden-" in name else "small" if "-small-freight-units-" in name
                else "oresund" if name.startswith("scl-tariffs-oresundslinjen-") else None)
        if kind is None:
            print(f"Scandlines: {name}: not a tariff read here")
            continue
        f, t = edition(path, text)
        eds[kind].append((f, t, {"std": standard, "transit": transit, "small": small, "oresund": oresund}[kind](text)))
    notices = [surcharges(read(p)) for p in sorted(glob.glob(os.path.join(fetched, "scl-surcharges-*.txt")))]
    if not all(eds.values()) or not notices:
        print(f"Scandlines: tariffs or surcharges missing ({ {k: len(v) for k, v in eds.items()} }, {len(notices)} notices); not built")
        return
    lines, permit = lines_of(osm)
    pos = port_places(osm, lines, PORTS)
    missing = [p for p in PORTS if p not in pos]
    if missing:
        sys.exit(f"Scandlines: ports not placed: {missing}")
    placed, notes = place_systems(ROUTES, pos, lines, permit, lambda msg: sys.exit(f"Scandlines: {msg}"))
    stations = {}
    for _, st, _ in placed:
        stations.update(st)
    groups = [{"name": group_name(m), "min_kg": 3501, "max_length_m": m, **({"min_length_m": m - 1} if m > 7 else {})} for m in LENGTHS]
    notices.sort()
    for k, (month, sur) in enumerate(notices):
        # Each month's surcharges hold "until further notification": to the next notice.
        until = (datetime.date.fromisoformat(notices[k + 1][0]) - datetime.timedelta(days=1)).isoformat() if k + 1 < len(notices) else None
        ed = {k_: in_force(v, month) for k_, v in eds.items()}
        if not ed["std"] or not ed["small"]:
            print(f"Scandlines {month}: no Germany–Denmark tariff in force; not built")
            continue
        (sf, _, (std, gir)), (mf, _, sm) = ed["std"], ed["small"]
        if abs(gir[0] - sur["PR"]["GIR"]) > 0.005 or abs(gir[1] - sur["RG"]["GIR"]) > 0.005:
            sys.exit(f"Scandlines {month}: the notice's GIR {sur['PR']['GIR']}, {sur['RG']['GIR']} isn't the tariff's {gir}")
        per = {"PR": sur["PR"]["BAF"] + sur["PR"]["GIR"], "RG": sur["RG"]["BAF"] + sur["RG"]["GIR"], "HH": sur["HH"]["energy"] + sur["HH"]["green"]}

        def base(route, m):
            if route in ("PR", "RG"):
                return (sm[0] if route == "PR" else sm[1]) if m <= 9 else std[m][0 if route == "PR" else 1]
            if route == "HH":
                return next(p for hi, p in ed["oresund"][2] if m <= hi)
            if m <= 9:
                return sm[2] if route == "PR+HH" else sm[3]
            return ed["transit"][2][m][0 if route == "PR+HH" else 1]

        pairs = {"Puttgarden|Rødby": ["PR"], "Rostock|Gedser": ["RG"]}
        if ed["oresund"]:
            pairs["Helsingør|Helsingborg"] = ["HH"]
        if ed["oresund"] and ed["transit"]:
            pairs["Puttgarden|Helsingborg"] = ["PR+HH", "PR", "HH"]
            pairs["Rostock|Helsingborg"] = ["RG+HH", "RG", "HH"]
        prices = {}
        for pair, keys in pairs.items():
            fare, surch = keys[0], keys[1:] or keys
            prices[pair] = {group_name(m): round(base(fare, m) + m * sum(per[k] for k in surch), 2) for m in LENGTHS}
        law = (f"Scandlines' gross freight tariffs per single crossing, excluding VAT, loaded (Germany–Denmark from 10 m, valid from {sf}; small units to 9 m, "
               f"valid from {mf}" + (f"; transit Germany–Sweden North, valid from {ed['transit'][0]}" if ed["transit"] else "")
               + (f"), and Øresundslinjen's freight tariff Helsingør–Helsingborg ({ed['oresund'][0]} to {ed['oresund'][1]}: trucks "
                  + ", ".join(f"to {hi} m EUR {p:g}" for hi, p in ed["oresund"][2]) + ")" if ed["oresund"] else ")")
               + f"; by the truck's length in whole metres up. With the surcharges per commencing metre (at least 7) as from {month}: "
               f"Puttgarden–Rødby BAF {sur['PR']['BAF']:g} and GIR {sur['PR']['GIR']:g}, Rostock–Gedser BAF {sur['RG']['BAF']:g} and GIR {sur['RG']['GIR']:g}, "
               f"Helsingør–Helsingborg energy {sur['HH']['energy']:g} and green {sur['HH']['green']:g} EUR. Scandlines' ETS surcharge "
               f"({sur['PR']['ETS']:g} and {sur['RG']['ETS']:g} EUR per metre) isn't added: carbon-cost prices the EU ETS on a crossing from the ships' MRV data. "
               "A trip over Puttgarden–Rødby or Rostock–Gedser and Helsingør–Helsingborg pays the transit ticket. Over-length (over 26 m), over-width and "
               "over-weight surcharges aren't applied. Ports at OpenStreetMap's ferry terminals, priced where the line goes out on its car ferry line."
               + "".join(f" {x}." for x in notes))
        system = {"name": "Scandlines and Øresundslinjen: " + " / ".join(ROUTES), "law": "Scandlines' and Øresundslinjen's freight tariffs and surcharges, loaded",
                  "groups": groups, "stations": [{"name": n, "points": pts} for n, pts in sorted(stations.items())], "station_match_km": MATCH_KM, "prices": prices}
        t = {"country": "DK", "currency": "EUR", "valid_from": month, **({"valid_to": until} if until else {}), "crossings": True,
             "name": "Scandlines' ferries Puttgarden–Rødby and Rostock–Gedser and Øresundslinjen's Helsingør–Helsingborg, trucks",
             "law": law,
             "sources": [{"title": "Scandlines Freight: freight tariffs", "url": "https://freight.scandlines.com/freight-conditions/freight-tariffs/"},
                         {"title": "Scandlines Freight: surcharges", "url": "https://freight.scandlines.com/freight-conditions/fuel-surcharges/"},
                         {"title": "OpenStreetMap (Overpass API): ferry lines and terminals", "url": "https://www.openstreetmap.org/"}],
             "vehicles": "Trucks over 3.5 t, by length (truck.length_m)", "min_kg": 3501,
             "tolled_roads": "The ferries Puttgarden–Rødby, Rostock–Gedser and Helsingør–Helsingborg.", "closed_systems": [system], "rows": []}
        os.makedirs(out, exist_ok=True)
        path = os.path.join(out, f"scandlines-{month}.json")
        json.dump(t, open(path, "w"), ensure_ascii=False, indent=1)
        print(path, {p: (v["16-17 m"], v["18-19 m"]) for p, v in prices.items()})


if __name__ == "__main__":
    main(*sys.argv[1:])
