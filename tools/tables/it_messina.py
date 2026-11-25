"""Builds the Strait of Messina's ferry for trucks (it-messina-<date>.json):
Caronte & Tourist's commercial vehicle fares between Messina Tremestieri
and Villa San Giovanni, from

- the operator's commercial vehicle fares page (it-messina-cv.html): one
  way each direction by the vehicle's length in linear metres (up to 6 m,
  then 6.01-6.50, 6.51-7.50 ... 17.51-18.50, 18.51-20.50), the month they
  are valid for, and the 4.30 EUR per trip every commercial vehicle pays
  for the port company's services (added here); the fares include the
  fuel, ETS and FuelEU Maritime surcharges, which the operator updates
  monthly;
- OpenStreetMap (it-messina-osm.json, Overpass): the ferry line and its
  terminals.

A closed system, directed, placed on OpenStreetMap's car ferry line
(ferry_osm.py). The page doesn't say whether VAT is in the fares; they are
taken as published. Round trips and vouchers aren't used.

Usage: python3 it_messina.py <fetched dir> <out dir>
"""
import datetime, html, json, os, re, sys

from ferry_osm import MATCH_KM, lines_of, port_places, systems as place_systems

MONTHS = {m: i + 1 for i, m in enumerate(("january", "february", "march", "april", "may", "june", "july", "august",
                                          "september", "october", "november", "december"))}
PORTS = {"Messina Tremestieri": ("terminal", "Caronte & Tourists"),
         "Villa San Giovanni": ("terminal", "Villa San Giovanni invasatura automezzi")}
E = r"€\s*(\d+),(\d\d)"


def text(path):
    t = open(path, encoding="utf-8").read()
    t = re.sub(r"<script.*?</script>", " ", t, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", html.unescape(t))


def main(fetched, out):
    try:
        page = text(os.path.join(fetched, "it-messina-cv.html"))
        osm = json.load(open(os.path.join(fetched, "it-messina-osm.json")))
    except (OSError, ValueError):
        print("Strait of Messina: a source wasn't fetched; not built")
        return
    for needle in ("Fares include Fuel Surcharge, ETS, and FuelEU Maritime", "Messina - Villa S.G. One way Villa S.G. - Messina One way"):
        if needle not in page:
            sys.exit(f"Strait of Messina: the fares page no longer says {needle!r}")
    m = re.search(r"Rates valid from (\d{1,2}) to (\w+) (\d{1,2}), (\d{4})", page)
    if not m or m.group(2).lower() not in MONTHS:
        sys.exit("Strait of Messina: the fares' month not read")
    month, year = MONTHS[m.group(2).lower()], int(m.group(4))
    start = datetime.date(year, month, int(m.group(1))).isoformat()
    end = datetime.date(year, month, int(m.group(3))).isoformat()
    fee = re.search(r"all commercial vehicles must pay € (\d+)[.,](\d\d) per trip as payment for the port company services", page)
    if not fee:
        sys.exit("Strait of Messina: the port company's fee not read")
    fee = int(fee.group(1)) + int(fee.group(2)) / 100
    sur = re.search(r"ETS and Fuel EU Maritime for heavy vehicles (\d+),(\d\d)€ per trip", page)
    fuel = re.search(r"Fuel surcharge for heavy vehicles (\d+),(\d\d)€ per trip", page)
    table = page[page.index("Round Trip Voucher"):page.index("Please note all commercial vehicles")]
    rows = re.findall(r"(Vans/Trucks up to 6 metres \(4\.51 - 6\.00\)|\d+\.00 MTL \((\d+\.\d\d) - (\d+\.\d\d)\))\s+" + r"\s+".join([E] * 4), table)
    if len(rows) != 15:
        sys.exit(f"Strait of Messina: {len(rows)} length bands read, not 15")
    groups, out_, back = [], {}, {}
    lo = None
    for r in rows:
        label = r[0]
        hi = 6.0 if label.startswith("Vans/Trucks") else float(r[2])
        if lo is not None and float(r[1]) != round(lo + 0.01, 2):
            sys.exit(f"Strait of Messina: the bands don't follow on: {label}")
        name = f"up to {hi:g} m" if lo is None else f"{lo + 0.01:.2f}-{hi:.2f} m"
        g = {"name": name, "min_kg": 3501, "max_length_m": hi}
        if lo is not None:
            g["min_length_m"] = lo
        groups.append(g)
        ms, vs = int(r[3]) + int(r[4]) / 100, int(r[5]) + int(r[6]) / 100
        out_[name], back[name] = round(ms + fee, 2), round(vs + fee, 2)
        lo = hi
    lines, permit = lines_of(osm)
    pos = port_places(osm, lines, PORTS)
    placed, notes = place_systems({"Tremestieri-Villa San Giovanni": [("Messina Tremestieri", "Villa San Giovanni")]}, pos, lines, permit,
                                  lambda msg: sys.exit(f"Strait of Messina: {msg}"))
    if len(placed) != 1:
        sys.exit(f"Strait of Messina: the line not placed: {notes}")
    _, stations, _ = placed[0]
    surch = ""
    if sur and fuel:
        surch = (f" In {m.group(2).capitalize()} {year} the fares hold a fuel surcharge of {int(fuel.group(1))},{fuel.group(2)} EUR and "
                 f"ETS and FuelEU Maritime of {int(sur.group(1))},{sur.group(2)} EUR per trip for heavy vehicles.")
    law = (f"Caronte & Tourist's commercial vehicle fares, Messina Tremestieri–Villa San Giovanni, valid {start} to {end}: one way each direction "
           f"by the vehicle's length in linear metres (to 20.50 m), plus the {fee:.2f} EUR per trip every commercial vehicle pays for the port "
           f"company's services. The fares include the fuel, ETS and FuelEU Maritime surcharges, updated monthly; a newer month's fares replace "
           f"these when published.{surch} The page doesn't say whether VAT is in the fares; they are taken as published. "
           "Round trips and vouchers aren't used; longer vehicles are exceptional transport, not priced. The ports at OpenStreetMap's "
           "ferry terminals, priced where the line goes out on its car ferry line.")
    s = {"name": "Strait of Messina: Caronte & Tourist, Messina Tremestieri–Villa San Giovanni", "law": law, "groups": groups,
         "stations": [{"name": n, "points": pts} for n, pts in sorted(stations.items())], "station_match_km": MATCH_KM,
         "prices": {"Messina Tremestieri|Villa San Giovanni": out_, "Villa San Giovanni|Messina Tremestieri": back},
         "directed": True}
    # The fares hold the ETS surcharge (need above): no ETS line on top.
    t = {"country": "IT", "currency": "EUR", "valid_from": start, "crossings": True, "ferry": True, "ets_in_fare": True,
         "name": "Strait of Messina ferry (Caronte & Tourist), trucks",
         "law": law,
         "sources": [{"title": "Caronte & Tourist: Strait of Messina, commercial vehicle fares", "url": "https://www.carontetourist.it/en/strait-messina/freight/rates-commercial-vehicle"},
                     {"title": "OpenStreetMap (Overpass API): the Strait of Messina's ferry lines and terminals", "url": "https://www.openstreetmap.org/"}],
         "vehicles": "Trucks over 3.5 t, by length (truck.length_m)", "min_kg": 3501,
         "tolled_roads": "The Strait of Messina's ferry for commercial vehicles, Messina Tremestieri–Villa San Giovanni.",
         "closed_systems": [s], "rows": []}
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"it-messina-{start}.json")
    json.dump(t, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, {k: out_[k] for k in list(out_)[-2:]}, {k: back[k] for k in list(back)[-2:]}, {p: len(x) for p, x in stations.items()})


if __name__ == "__main__":
    main(*sys.argv[1:])
