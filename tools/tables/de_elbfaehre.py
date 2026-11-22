"""Builds the Elbe ferry Glückstadt–Wischhafen (FRS Elbfähre) for trucks
(de-elbfaehre-<date>.json, one per fare edition or fuel surcharge), from

- FRS Elbfähre's fares for trucks and cargo (frs-elbe-trucks*.html, the
  German page, "LKW und Fracht"): a truck, unloaded and without its
  driver, by its length over all (up to 5.00, 6.00 ... 17.00, 18.35 m, then
  each further metre, overhanging ones too; at most 23 m), net and gross,
  and the load by weight per started 1,000 kg, each "valid from 1 January
  to 31 December" of a year. The page changed its 2026 fares in November
  2026 without changing their dates: the earlier ones are the Internet
  Archive's copy of 8 November 2026 (frs-elbe-trucks-2026-01), the later
  ones are taken from the day they were first read (FIRST_READ), and the
  builder stops if the page gives others again. 2025's are the Internet
  Archive's copy of 10 November 2025;
- the fuel surcharge page (frs-elbe-fuel*.html; earlier states from the
  Internet Archive's copies): a surcharge per truck, with the date of each
  state ("Stand"); the first applies to tickets bought from 23 March 2026,
  and a state that leaves the trucks' surcharge unchanged isn't a version;
- OpenStreetMap (frs-elbe-osm.json, Overpass): the ferry line and its
  terminals.

carbon-cost prices a trip with cargo: the truck by its length
(truck.length_m) at the net fare plus the fuel surcharge (the page gives
one amount, taken as published), and the load (cargo_kg) per started
1,000 kg at the net rate: ORCT unit t on the vehicle parameter load_kg in
steps of 1,000 kg. The driver's own fare isn't added (the passengers' page
gives adults only a "from" price), nor the surcharges for width, dangerous
goods or the frequent travellers' discounts.

Usage: python3 de_elbfaehre.py <fetched dir> <out dir>
"""
import datetime, html, json, os, re, sys

from ferry_osm import MATCH_KM, lines_of, port_places, systems as place_systems

# The fares the live page gave when first read, and from when they're taken.
FIRST_READ = {"2026": "2026-11-19"}
# The editions: the fetched page for each, the earliest first within a year.
EDITIONS = [("2025", "frs-elbe-trucks-2025"), ("2026", "frs-elbe-trucks-2026-01"), ("2026", "frs-elbe-trucks")]
FUEL = ["frs-elbe-fuel-2026-03", "frs-elbe-fuel-2026-05", "frs-elbe-fuel-2026-09", "frs-elbe-fuel"]
PORTS = {"Glückstadt": ("terminal", "Glückstadt"), "Wischhafen": ("terminal", "Wischhafen")}
ROUTES = {"Glückstadt–Wischhafen": [("Glückstadt", "Wischhafen")]}
MONTHS_DE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"]
EUR = r"(\d+,\d\d) €"
PAGE = "https://www.frs-elbfaehre.de/fahrpreise/lkw-und-fracht"
FUEL_PAGE = "https://www.frs-elbfaehre.de/treibstoffzuschlag"


def text(path):
    t = open(path, encoding="utf-8", errors="replace").read()
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", t, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", html.unescape(t))


def eur(s):
    return float(s.replace(".", "").replace(",", "."))


def fares(name, t):
    """(year, [(up to m, net EUR)], per further metre net, max m, load per started 1,000 kg net)."""
    m = re.search(r"Lkw \(unbeladen und unbesetzt\)\* Gültig vom 01\. Januar bis 31\. Dezember (\d{4}) netto brutto (.*?) je weiterer Meter "
                  r"\(auch bei überhängenden Metern\) " + EUR + " " + EUR, t)
    if not m:
        sys.exit(f"Elbfähre: {name}: the trucks' fares not found")
    year, body = m.group(1), m.group(2)
    rows = [(float(a.replace(",", ".")), eur(n), eur(g)) for a, n, g in re.findall(r"Länge bis (\d+,\d\d) m " + EUR + " " + EUR, body)]
    if [r[0] for r in rows] != [5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18.35]:
        sys.exit(f"Elbfähre: {name}: the length bands read: {[r[0] for r in rows]}")
    for _, n, g in rows + [(0, eur(m.group(3)), eur(m.group(4)))]:
        if abs(n * 1.19 - g) > 0.02:  # gross is net plus 19% VAT
            sys.exit(f"Elbfähre: {name}: net {n} and gross {g} don't differ by 19% VAT")
    mx = re.search(r"Maximale Länge: (\d+,\d\d) m", t)
    load = re.search(r"Ladungen Gültig vom 01\. Januar bis 31\. Dezember (\d{4}) netto brutto nach Gewicht, je angefangene 1\.000 kg " + EUR + " " + EUR, t)
    if not mx or not load or load.group(1) != year:
        sys.exit(f"Elbfähre: {name}: the maximum length or the load's rate for {year} not found")
    return year, [(a, n) for a, n, _ in rows], eur(m.group(3)), float(mx.group(1).replace(",", ".")), eur(load.group(2))


def fuel(name, t):
    """(from, EUR per truck) of a fuel surcharge page."""
    m = re.search(r"Zuschlag LKW " + EUR, t) or re.search(r"Truck surcharge " + EUR, t)
    s = re.search(r"Stand: (\d\d)\.(\d\d)\.(\d{4})", t) or re.search(r"Status: (\d\d)/(\d\d)/(\d{4})", t)
    if not m or not s:
        sys.exit(f"Elbfähre: {name}: the trucks' fuel surcharge or its date not found")
    d = f"{s.group(3)}-{s.group(2)}-{s.group(1)}"
    # The first state: not for tickets bought or reserved before 23 March 2026.
    f = re.search(r"nicht für Tickets, die vor dem (\d{1,2})\. (\w+) (\d{4}) gekauft", t) or re.search(r"before (\w+) (\d{1,2}), (\d{4})", t)
    if f:
        g = f.groups()
        nb = (f"{g[2]}-{MONTHS_DE.index(g[1]) + 1:02d}-{int(g[0]):02d}" if g[1] in MONTHS_DE
              else datetime.datetime.strptime(f"{g[0]} {g[1]} {g[2]}", "%B %d %Y").date().isoformat())
        d = max(d, nb)
    return d, eur(m.group(1))


def main(fetched, out):
    try:
        pages = {sid: text(os.path.join(fetched, sid + ".html")) for _, sid in EDITIONS}
        states = sorted(fuel(sid, text(os.path.join(fetched, sid + ".html"))) for sid in FUEL)
        # A new state that leaves the trucks' surcharge as it was isn't a change for them.
        fuels = [s for k, s in enumerate(states) if k == 0 or s[1] != states[k - 1][1]]
        osm = json.load(open(os.path.join(fetched, "frs-elbe-osm.json"), encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"Elbfähre: not built ({e})")
        return
    # Editions: (from, to, fares) with the fares' year.
    eds = []
    for y, sid in EDITIONS:
        f = fares(sid, pages[sid])
        if f[0] != y:
            sys.exit(f"Elbfähre: {sid}: fares for {f[0]}, not {y}")
        if eds and eds[-1][2][0] == y:
            if f[1:] == eds[-1][2][1:]:
                continue  # the live page still gives the earlier fares
            if y not in FIRST_READ:
                sys.exit(f"Elbfähre: the {y} fares changed: add the day they were first read to FIRST_READ")
            eds.append((FIRST_READ[y], f"{y}-12-31", f))
        else:
            eds.append((f"{y}-01-01", f"{y}-12-31", f))
    # The live page's fares for a year with FIRST_READ must still be those first read.
    days = sorted({a for a, _, _ in eds} | {d for d, _ in fuels})
    lines, permit = lines_of(osm)
    pos = port_places(osm, lines, PORTS)
    if set(pos) != set(PORTS):
        sys.exit(f"Elbfähre: ports not placed: {set(PORTS) - set(pos)}")
    placed, notes = place_systems(ROUTES, pos, lines, permit, lambda msg: sys.exit(f"Elbfähre: {msg}"))
    (_, stations, _), = placed
    st = [{"name": n, "points": pts} for n, pts in sorted(stations.items())]
    for k, day in enumerate(days):
        ed = [e for e in eds if e[0] <= day <= e[1]]
        if not ed:
            continue
        a, b, (year, bands, per, mx, load) = ed[-1]
        nxt = next((d for d in days[k + 1:]), None)
        until = min(b, (datetime.date.fromisoformat(nxt) - datetime.timedelta(days=1)).isoformat()) if nxt else b
        sur = ([s for d, s in fuels if d <= day] or [0])[-1]
        since = ([d for d, s in fuels if d <= day] or [None])[-1]
        groups, prices, lo = [], {}, 0
        for hi, net in bands:
            g = f"up to {hi:g} m" if lo == 0 else f"{lo:g}-{hi:g} m"
            groups.append({"name": g, "min_kg": 3501, "max_length_m": hi, **({"min_length_m": lo} if lo else {})})
            prices[g] = round(net + sur, 2)
            lo = hi
        n = 1
        while lo < mx:  # each further metre, to the maximum length
            hi = min(round(18.35 + n, 2), mx)
            g = f"{lo:g}-{hi:g} m"
            groups.append({"name": g, "min_kg": 3501, "max_length_m": hi, "min_length_m": lo})
            prices[g] = round(bands[-1][1] + per * n + sur, 2)
            lo, n = hi, n + 1
        vehicle = {"name": "Elbfähre Glückstadt–Wischhafen: the truck", "law": "FRS Elbfähre's fares for trucks (unloaded, without the driver), net, by length",
                   "groups": groups, "stations": st, "station_match_km": MATCH_KM, "prices": {"Glückstadt|Wischhafen": prices}}
        cargo = {"name": "Elbfähre Glückstadt–Wischhafen: the load", "law": "FRS Elbfähre's fare for loads by weight, net, per started 1,000 kg",
                 "groups": [{"name": "per started 1,000 kg of load", "min_kg": 3501}], "stations": st, "station_match_km": MATCH_KM,
                 "prices": {"Glückstadt|Wischhafen": {"per started 1,000 kg of load": load}},
                 "unit": "t", "mass_basis": "load_kg", "mass_step_kg": 1000}
        src = ("the Internet Archive's copy of 8 November 2026" if a == f"{year}-01-01" and year in FIRST_READ
               else "the page as read on " + a if year in FIRST_READ else "the Internet Archive's copy of 10 November 2025" if year == "2025" else "the page")
        law = (f"FRS Elbfähre's fares for trucks and cargo, valid 1 January to 31 December {year} ({src}): a truck, unloaded and without its driver, "
               "net of 19% VAT, by its length over all: " + ", ".join(f"to {hi:g} m EUR {net:.2f}" for hi, net in bands)
               + f", each further metre (overhanging ones too) EUR {per:.2f}, at most {mx:g} m; the load by weight, EUR {load:.2f} per started 1,000 kg. "
               + (f"Plus the fuel surcharge per truck of EUR {sur:.2f} (as of {since}; the page gives one amount, taken as published). " if sur else "")
               + "The driver's own fare (adults \"from\" EUR 3.40) isn't added, nor the surcharges for over 2.50 m wide (30%) or dangerous goods, "
                 "nor the frequent travellers' discounts. Ports at OpenStreetMap's ferry terminals, priced where the line goes out on its car ferry line."
               + "".join(f" {x}." for x in notes))
        t = {"country": "DE", "currency": "EUR", "valid_from": day, "valid_to": until, "crossings": True, "ferry": True,
             "name": "Elbe ferry Glückstadt–Wischhafen (FRS Elbfähre), trucks and their load", "law": law,
             "sources": [{"title": "FRS Elbfähre: LKW und Fracht (fares for trucks and cargo)", "url": PAGE},
                         {"title": "FRS Elbfähre: Treibstoffzuschlag (fuel surcharge)", "url": FUEL_PAGE},
                         {"title": "OpenStreetMap (Overpass API): the ferry line and its terminals", "url": "https://www.openstreetmap.org/"}],
             "vehicles": "Trucks over 3.5 t, by length (truck.length_m), and their load (cargo_kg)", "min_kg": 3501,
             "tolled_roads": "The Elbe ferry Glückstadt–Wischhafen.", "closed_systems": [vehicle, cargo], "rows": []}
        os.makedirs(out, exist_ok=True)
        path = os.path.join(out, f"de-elbfaehre-{day}.json")
        json.dump(t, open(path, "w"), ensure_ascii=False, indent=1)
        print(path, until, prices.get("16-17 m"), prices.get("18.35-19.35 m"), load, sur)


if __name__ == "__main__":
    main(*sys.argv[1:])
