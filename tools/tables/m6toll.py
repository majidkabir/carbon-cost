"""Builds the M6 Toll's table: a closed system priced by the number of
zones a trip passes through.

Usage: python3 m6toll.py fetched/ out-dir -> out-dir/gb-m6toll-<date>.json

Sources:
- fetch.py's gb-m6toll-tables.html (https://www.m6toll.co.uk/pricing-tables/):
  the same standard prices, "all prices inclusive of VAT" (checked).
- fetch.py's gb-m6toll.html (https://www.m6toll.co.uk/pricing/): the
  journey planner's price table (data-price-table: per vehicle class,
  [standard, breeze] for a trip within zone 2 only ("only2"), spanning two
  zones ("span2") and all three ("all"), VAT included) and "Vehicle
  classifications explained" (class 4: 2 axles, class 5: 3 to 6, class 6:
  more than 6, all 1.3 m or over at the first axle).
- browser/gb-m6toll-zones.txt: the zone of each junction (T1, T2 and the
  M6/M42 end in zone 1; T3 to T6 in zone 2; T7, T8 and the M6 J11/11A end
  in zone 3), from the planner's map, which only its script draws, read in
  Chrome.
- fetch.py's gb-m6toll-osm.json (Overpass): the M6 Toll's two carriageways
  and its junction nodes T1 to T8.

Each carriageway is cut at its junctions (every junction node projected
onto it) into sections; a station is the middle of a section, passed in
its carriageway's direction (within 0.1 km). A trip's first section gives
the zone it entered in (the section's start in its direction), its last the
zone it left in (the section's end). Zones 1 and 3 have no toll plaza of
their own, so a trip within one of them is free; within zone 2 it pays
"only2"; across two zones "span2"; from zone 1 to zone 3 "all". Prices
exclude 20% VAT; `etc` the breeze account price.
"""
import html, json, math, os, re, sys

BROWSER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "browser")
VAT = 1.2


def km(a, b):
    return math.hypot((a[0] - b[0]) * math.cos(math.radians(a[1])) * 111.32, (a[1] - b[1]) * 110.57)


def bearing(a, b):
    return round(math.degrees(math.atan2((b[0] - a[0]) * math.cos(math.radians(a[1])), b[1] - a[1])) % 360, 1)


def chains(ways):
    """The one-way ways joined end to start into carriageways (lists of
    (lon, lat))."""
    by_start = {}
    for w in ways:
        by_start.setdefault(w[0], []).append(w)
    ends = {w[-1] for w in ways}
    out = []
    for w in ways:
        if w[0] in ends:
            continue
        line = list(w)
        while line[-1] in by_start and len(by_start[line[-1]]) == 1 and len(line) < 100000:
            nxt = by_start[line[-1]][0]
            if nxt is w:
                break
            line += nxt[1:]
        out.append(line)
    return out


def along(line):
    cum = [0.0]
    for a, b in zip(line, line[1:]):
        cum.append(cum[-1] + km(a, b))
    return cum


def project(line, cum, p):
    """(km along, distance) of p's nearest point on the line."""
    best = (math.inf, 0.0)
    for i, (a, b) in enumerate(zip(line, line[1:])):
        k = math.cos(math.radians(p[1]))
        ax, ay = (a[0] - p[0]) * k * 111.32, (a[1] - p[1]) * 110.57
        bx, by = (b[0] - p[0]) * k * 111.32, (b[1] - p[1]) * 110.57
        dx, dy = bx - ax, by - ay
        L = dx * dx + dy * dy
        u = 0 if L == 0 else max(0, min(1, -(ax * dx + ay * dy) / L))
        d = math.hypot(ax + u * dx, ay + u * dy)
        if d < best[0]:
            best = (d, cum[i] + u * (cum[i + 1] - cum[i]))
    return best[1], best[0]


def at(line, cum, s):
    """The point and bearing s km along the line."""
    for i in range(len(line) - 1):
        if cum[i + 1] >= s:
            seg = cum[i + 1] - cum[i]
            u = 0 if seg == 0 else (s - cum[i]) / seg
            a, b = line[i], line[i + 1]
            return (a[0] + u * (b[0] - a[0]), a[1] + u * (b[1] - a[1])), bearing(a, b)
    return line[-1], bearing(line[-2], line[-1])


def main(fetched, out, browser=BROWSER):
    page = open(os.path.join(fetched, "gb-m6toll.html"), encoding="utf-8").read()
    m = re.search(r'data-price-table="([^"]+)"', page)
    if not m:
        sys.exit("M6 Toll: no price table on the pricing page")
    table = json.loads(html.unescape(m.group(1)))
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page)))
    cls = re.search(r"Class 4 4 or more 2 1\.3m or over Class 5 4 or more more than 2, up to 6 1\.3m or over Class 6 4 or more more than 6 1\.3m or over", text)
    if not cls:
        sys.exit("M6 Toll: the vehicle classes changed")
    # The pricing tables page: the same prices, "all prices inclusive of VAT".
    tt = open(os.path.join(fetched, "gb-m6toll-tables.html"), encoding="utf-8").read()
    tt = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", tt)))
    std = re.search(r"Standard pricing tariff, including zonal pricing \(all prices inclusive of VAT\) Class 1 Class 2 Class 3 Class 4 Class 5 3 zones (.*?) 2 zones (.*?) 1 zone (.*?) breeze", tt)
    if not std:
        sys.exit("M6 Toll: the pricing tables page changed")
    for row, key in zip(std.groups(), ("all", "span2", "only2")):
        got = re.findall(r"£(\d+\.\d\d)", row)
        if got[3:5] != [table["4"][key][0], table["5"][key][0]]:
            sys.exit(f"M6 Toll: the pricing tables ({key} {got}) and the planner disagree")
    for c in ("4", "5", "6"):
        if sorted(table.get(c, {})) != ["all", "only2", "span2"]:
            sys.exit(f"M6 Toll: class {c} prices {table.get(c)}")
    if table["5"] != table["6"]:
        sys.exit("M6 Toll: classes 5 and 6 now differ")

    z = open(os.path.join(browser, "gb-m6toll-zones.txt"), encoding="utf-8").read()
    zones = {}
    for name, zone in re.findall(r"^(M6\(N\) J11/11A|M6\(S\) / M42|T[1-8]) \| ([123]) \|", z, re.M):
        zones[{"M6(N) J11/11A": "M6N", "M6(S) / M42": "M6S"}.get(name, name)] = int(zone)
    order = ["M6S", "T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8", "M6N"]
    if sorted(zones) != sorted(order) or [zones[j] for j in order] != sorted(zones[j] for j in order):
        sys.exit(f"M6 Toll: zones {zones}")
    read = re.search(r"read on (\d{4}-\d\d-\d\d)", z).group(1)

    d = json.load(open(os.path.join(fetched, "gb-m6toll-osm.json")))
    ways = [tuple((g["lon"], g["lat"]) for g in e["geometry"]) for e in d["elements"]
            if e["type"] == "way" and e.get("tags", {}).get("oneway") == "yes" and len(e.get("geometry", [])) > 1]
    nodes = {}
    for e in d["elements"]:
        if e["type"] == "node" and re.fullmatch(r"T[1-8]", e.get("tags", {}).get("ref", "")):
            nodes.setdefault(e["tags"]["ref"], []).append((e["lon"], e["lat"]))
    if sorted(nodes) != order[1:-1]:
        sys.exit(f"M6 Toll: junction nodes {sorted(nodes)}")
    lines = sorted(chains(ways), key=lambda l: -len(l))
    lines = [l for l in lines if along(l)[-1] > 30]
    if len(lines) != 2:
        sys.exit(f"M6 Toll: {len(lines)} carriageways over 30 km ({[round(along(l)[-1], 1) for l in chains(ways)]})")
    stations, prices, etc = [], {}, {}
    for line in lines:
        cum = along(line)
        # Northbound runs from the M6/M42 end (south-east) to J11 (north-west).
        north = line[-1][0] < line[0][0]
        seq = ["M6S", "T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8", "M6N"] if north else ["M6N", "T8", "T7", "T6", "T5", "T4", "T3", "T2", "T1", "M6S"]
        pos = {seq[0]: 0.0, seq[-1]: cum[-1]}
        for j in seq[1:-1]:
            s, dist = min(project(line, cum, p) for p in nodes[j])
            if dist > 0.5:
                sys.exit(f"M6 Toll: {j} is {dist:.2f} km off the {'north' if north else 'south'}bound carriageway")
            pos[j] = s
        if [pos[j] for j in seq] != sorted(pos[j] for j in seq):
            sys.exit(f"M6 Toll: junctions out of order {pos}")
        way = "N" if north else "S"
        secs = []
        for a, b in zip(seq, seq[1:]):
            p, h = at(line, cum, (pos[a] + pos[b]) / 2)
            name = f"{way} {a}-{b}"
            secs.append((name, zones[a], zones[b]))
            stations.append({"name": name, "points": [{"name": f"{'north' if north else 'south'}bound, between {a} and {b}", "lat": round(p[1], 6), "lon": round(p[0], 6), "heading": h}]})
        for i, (sa, za, _) in enumerate(secs):
            for sb, _, zb in secs[i:]:
                n = abs(za - zb)
                key = "only2" if n == 0 else ("span2" if n == 1 else "all")
                if n == 0 and za != 2:
                    prices[f"{sa}|{sb}"] = {"Class 4": 0.0, "Class 5": 0.0}
                    etc[f"{sa}|{sb}"] = {"Class 4": 0.0, "Class 5": 0.0}
                    continue
                prices[f"{sa}|{sb}"] = {g: round(float(table[c][key][0]) / VAT, 4) for g, c in (("Class 4", "4"), ("Class 5", "5"))}
                etc[f"{sa}|{sb}"] = {g: round(float(table[c][key][1]) / VAT, 4) for g, c in (("Class 4", "4"), ("Class 5", "5"))}
    t5 = table["5"]
    tb = {
        "country": "GB", "currency": "GBP", "valid_from": read, "crossings": True,
        "osm_extract": d.get("osm3s", {}).get("timestamp_osm_base", "")[:10],
        "name": "M6 Toll",
        "law": ("The M6 Toll (Birmingham Northern Relief Road, operated by Midland Expressway Ltd under its concession): prices by the number of zones a trip passes through, as the operator's pricing page publishes them, "
                f"class 4 (two axles) and 5 (three or more; class 6 over six axles costs the same), 1.3 m or over at the first axle (trucks over 3.5 t are taken to be): class 5 GBP {t5['all'][0]} for all three zones, {t5['span2'][0]} for two, {t5['only2'][0]} within zone 2, "
                "VAT included on the page and excluded here (20%); `etc` the breeze account price. Zones by junction from the page's zone map (read in Chrome); a trip within zone 1 or zone 3 passes no plaza and pays nothing. "
                "Stations: the middle of each carriageway's stretch between junctions (OSM), passed in its direction."),
        "sources": [{"title": "M6toll: Pricing (journey planner price table and vehicle classes)", "url": "https://www.m6toll.co.uk/pricing/"},
                    {"title": "M6toll: Pricing tables", "url": "https://www.m6toll.co.uk/pricing-tables/"},
                    {"title": "M6toll: zones by junction (the pricing page's zone map, read in Chrome: tools/tables/browser/gb-m6toll-zones.txt)", "url": "https://www.m6toll.co.uk/pricing/"},
                    {"title": "OpenStreetMap (Overpass API): the M6 Toll's carriageways and junctions T1-T8", "url": "https://www.openstreetmap.org/"}],
        "vehicles": "Class 4 (two axles) and class 5 (three to six axles) at 1.3 m or over; here trucks over 3.5 t", "min_kg": 3501,
        "tolled_roads": "The M6 Toll, from the M6/M42 (Coleshill) to the M6 at J11/11A (Cannock).",
        "closed_systems": [{
            "name": "M6 Toll", "law": "Priced by the zones between where a trip joins and leaves the M6 Toll (see the table's law).",
            "groups": [{"name": "Class 4", "min_kg": 3501, "max_axles": 2}, {"name": "Class 5", "min_kg": 3501, "min_axles": 3}],
            "stations": stations, "station_match_km": 0.1, "prices": prices, "etc_prices": etc}],
        "rows": [],
    }
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"gb-m6toll-{read}.json")
    json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, len(stations), "stations")


if __name__ == "__main__":
    main(*sys.argv[1:])
