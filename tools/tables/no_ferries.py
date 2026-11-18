"""Builds Norway's national road ferries (riksvegferjer) as toll systems
(no-ferries-<date>.json): the fare per crossing by vehicle length, from

- the AutoPASS-regulativ for ferjetakster's price table (Statens vegvesen,
  no-ferje-autopass-pris.txt): the full price by zone and length group
  AP1-AP9, VAT (12%) included;
- the regulativ itself (no-ferje-autopass-reg.txt): the vehicle is priced
  by its total length with trailer and load; business customers with a
  prepaid AutoPASS ferry account get 40% off;
- the Minister of Transport's answer to the Storting of 11 December 2025
  (no-stortinget-699.txt, written question 699): each national road ferry
  route's zone, by stretch, and its full AP1 price then (2025), which must
  agree with the 2026 table less its 3.6% rise; stretches priced 0 there
  are free;
- the national road database NVDB (no-nvdb-770.json, Ferjesamband, and
  no-nvdb-64.json, Ferjekai): each route's quays and where they are;
- OpenStreetMap (no-ferry-ways.json): the car ferry lines between them.

A quay is a station whose points lie out on the water, on each car ferry
line from it to another quay of its route, so that a road passing the
quay doesn't match: the first point at least POINT_KM along the line that
is more than CLEAR_KM from every car ferry line not of its route. A route enters at
the first quay it passes and leaves at the last, so a crossing that calls
at a quay on the way is priced from end to end. Stretches with no car
ferry line in OpenStreetMap (a route can't take them) aren't priced.

Moss-Horten has a regulativ of its own: its price list (no-ferje-mh-pris.txt,
the operator's fares for the year) by length. Prices exclude the 12% VAT.
The toll (bompenger) charged on board Mortavika-Arsvågen isn't included.

Usage: python3 no_ferries.py <fetched dir> <out dir>
"""
import glob
import json
import os
import re
import math
import sys

POINT_KM, CLEAR_KM, MATCH_KM, QUAY_KM = 0.5, 0.3, 0.15, 0.8
VAT = 1.12
ZE = "zero-emission"  # the groups of zero-emission trucks (CO2 class 5), before the others


def krone(x):
    """Rounded to the nearest whole krone (half up), as the regulativ rounds the zero-emission price."""
    return int(x + 0.5 + 1e-9)


def ze_groups(groups):
    """The zero-emission groups (CO2 class 5) ahead of the others: the first group a truck matches is its group."""
    return [dict(g, name=f"{g['name']} {ZE}", co2_class=[5]) for g in groups] + groups
LENGTHS = [("AP1", None, 6.0), ("AP2", 6.0, 8.0), ("AP3", 8.0, 10.0), ("AP4", 10.0, 12.5), ("AP5", 12.5, 14.5),
           ("AP6", 14.5, 17.5), ("AP7", 17.5, 19.5), ("AP8", 19.5, 22.0), ("AP9", 22.0, None)]
HEADER = "<6m 6,01-8m 8,01-10m 10,01-12,5m 12,51-14,5m 14,51-17,5m 17,51-19,5m 19,51-22m >22m"
MONTHS = {m: i + 1 for i, m in enumerate(("januar", "februar", "mars", "april", "mai", "juni", "juli", "august", "september", "oktober", "november", "desember"))}
URLS = {"price": "https://www.vegvesen.no/globalassets/fag/trafikk/ferje/pris---autopass-regulativ---fullpris---01.01.2026.pdf",
        "rules": "https://www.vegvesen.no/globalassets/fag/trafikk/ferje/autopass-reg.-for-ferje-fra-01.01.2026.pdf",
        "mh": "https://cdn.sanity.io/files/ufla9djl/production/5620c5955d8c702afa5cb2b98fae987d75981e97.pdf",
        "answer": "https://www.stortinget.no/globalassets/pdf/dokumentserien/2025-2026/dok15-202526-0699-vedlegg.pdf"}


def flat(path):
    return re.sub(r"\s+", " ", open(path, encoding="utf-8", errors="replace").read())


def key(name):
    return re.sub(r"\s+", "", name.lower().replace("–", "-"))


def objects(fetched, sid):
    """The NVDB objects of a fetched query, over its pages (<sid>.json, <sid>-2.json, ...)."""
    out = []
    for p in [os.path.join(fetched, f"{sid}.json")] + sorted(glob.glob(os.path.join(fetched, f"{sid}-[0-9]*.json")), key=lambda p: int(re.search(r"-(\d+)\.json$", p).group(1))):
        out += json.load(open(p)).get("objekter") or []
    return out


def prop(o, name):
    return next((e.get("verdi") for e in o.get("egenskaper", []) if e.get("navn") == name), None)


def where(o):
    """A quay's place: the middle of its NVDB geometry (WKT, latitude first in srid 4326)."""
    wkt = (o.get("geometri") or {}).get("wkt", "")
    pts = [(float(a), float(b)) for a, b in re.findall(r"(-?\d+\.\d+) (-?\d+\.\d+)", wkt)]
    if not pts:
        return None
    return round(sum(p[0] for p in pts) / len(pts), 6), round(sum(p[1] for p in pts) / len(pts), 6)


def km(a, b):
    """Distance in km between two (lat, lon) points."""
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(h))


def along(line, d):
    """The point d km along a line of (lat, lon) points, or None past its end."""
    for a, b in zip(line, line[1:]):
        s = km(a, b)
        if s >= d and s > 0:
            f = d / s
            return round(a[0] + f * (b[0] - a[0]), 6), round(a[1] + f * (b[1] - a[1]), 6)
        d -= s
    return None


def off(p, line):
    """The distance in km from p to a line of (lat, lon) points."""
    cos = math.cos(math.radians(p[0]))
    best = math.inf
    for a, b in zip(line, line[1:]):
        ax, ay, bx, by = (a[1] - p[1]) * cos * 111.2, (a[0] - p[0]) * 111.2, (b[1] - p[1]) * cos * 111.2, (b[0] - p[0]) * 111.2
        dx, dy = bx - ax, by - ay
        u = max(0.0, min(1.0, -(ax * dx + ay * dy) / (dx * dx + dy * dy))) if dx or dy else 0.0
        best = min(best, math.hypot(ax + u * dx, ay + u * dy))
    return best


def quays_of(route, quays):
    """A route's quays: name -> (lat, lon), from its NVDB Ferjekai children."""
    ids = [i for b in (route.get("relasjoner") or {}).get("barn", []) if b.get("type", {}).get("id") == 64 for i in b["vegobjekter"]]
    qs = {}
    for i in ids:
        q = quays.get(i)
        if q and where(q):
            qs[re.sub(r"\s+(ferjekai|kai)$", "", prop(q, "Navn") or "", flags=re.I)] = where(q)
    return qs


def quay_points(route, qs, lines):
    """Each quay's points out on the car ferry lines to the route's other quays."""
    joins = {}
    for wid, ln in lines:
        ends = []
        for end in (ln[0], ln[-1]):
            near = sorted((km(end, q), n) for n, q in qs.items())
            ends.append(near[0][1] if near and near[0][0] <= QUAY_KM else None)
        if None not in ends and ends[0] != ends[1]:
            joins.setdefault(frozenset(ends), []).append((wid, ln, ends))
    points = {}
    mine = {wid for ws in joins.values() for wid, _, _ in ws}
    others = [l for i, l in lines if i not in mine]
    for ws in joins.values():
        for wid, ln, ends in ws:
            for q, line in ((ends[0], ln), (ends[1], ln[::-1])):
                d = POINT_KM
                while True:
                    p = along(line, d)
                    if p is None or km(p, line[-1]) < POINT_KM:
                        sys.exit(f"Norwegian ferries: {route}: no clear point on the line {wid} from {q}")
                    if all(off(p, l) > CLEAR_KM for l in others):
                        break
                    d += 0.1
                points.setdefault(q, []).append({"name": f"{q} ferry quay, {round(d, 1)} km out on the line to {ends[1] if q == ends[0] else ends[0]} (OSM way {wid})", "lat": p[0], "lon": p[1]})
    return points


def main(fetched, out):
    try:
        price = open(os.path.join(fetched, "no-ferje-autopass-pris.txt"), encoding="utf-8").read()
        rules = flat(os.path.join(fetched, "no-ferje-autopass-reg.txt"))
        answer = open(os.path.join(fetched, "no-stortinget-699.txt"), encoding="utf-8").read()
        routes, quays = objects(fetched, "no-nvdb-770"), {o["id"]: o for o in objects(fetched, "no-nvdb-64")}
        osm = json.load(open(os.path.join(fetched, "no-ferry-ways.json")))
        mh = open(os.path.join(fetched, "no-ferje-mh-pris.txt"), encoding="utf-8").read()
    except (OSError, ValueError):
        print("Norwegian ferries: a source wasn't fetched; not built")
        return
    # The price table: the date, the length groups, a row per zone.
    day = re.search(r"Inkl\. 12 % mva, gjeldende f\.o\.m\. (\d{1,2})\. (\w+) (\d{4})", price)
    if not day or HEADER not in re.sub(r"\s+", " ", price) or day.group(2) not in MONTHS:
        sys.exit("Norwegian ferries: the price table's date or length groups not read")
    start = f"{day.group(3)}-{MONTHS[day.group(2)]:02d}-{int(day.group(1)):02d}"
    zones = {}
    for ln in price.splitlines():
        m = re.match(r"^\s*(\d+)\s+((?:\d+\s+){9})(\d+)\s*$", ln)
        if m:
            zones[int(m.group(1))] = [int(x) for x in m.group(2).split()]
    if sorted(zones)[:2] != [0, 1] or len(zones) < 100:
        sys.exit(f"Norwegian ferries: the price table's zones not read ({len(zones)})")
    # The rules: priced by total length with trailer and load; 40% off with a business account.
    for needle in ("Kjøretøy takstberegnes etter kjøretøyets målte totallengde", "Kjøretøy over 6 meter og med tilhenger takseres som ett kjøretøy",
                   "Bedriftskunder kan oppnå 40 % rabatt",
                   "drivstoffkode 6 (hydrogen), betaler en takst som er 70% (AP1) eller 50% (AP2-AP9 og MC) av prisen i den takstgruppe som kjøretøyet blir målt til å tilhøre, avrundet til nærmeste hele krone. Det ytes ordinære rabatter på denne taksten"):
        if needle not in rules:
            sys.exit(f"Norwegian ferries: the regulativ no longer says {needle!r}")
    # The Minister's answer: zone and 2025 AP1 full price by stretch.
    stretches = {}
    for ln in answer.splitlines():
        m = re.match(r"^\s*(\S.*?[a-zæøå])\s{2,}(\S.*?[a-zæøå])\s{2,}(\d+)\s+(\d+)(\*?)\s*$", ln)
        if m:
            stretches.setdefault(m.group(1), []).append((m.group(2), int(m.group(3)), int(m.group(4)), bool(m.group(5))))
    toll_note = re.search(r"\* Taksten er inklusive (\d+) kr i bompengar", answer)
    if len(stretches) < 14:
        sys.exit(f"Norwegian ferries: the Minister's table not read ({len(stretches)} routes)")
    # Car ferry lines: OSM route=ferry ways a motor vehicle may take.
    lines = [(w["id"], [(g["lat"], g["lon"]) for g in w["geometry"]]) for w in osm.get("elements", [])
             if w.get("type") == "way" and w.get("tags", {}).get("route") == "ferry" and w.get("tags", {}).get("motor_vehicle") != "no" and len(w.get("geometry", [])) > 1]
    if len(lines) < 20:
        sys.exit(f"Norwegian ferries: only {len(lines)} car ferry lines in OpenStreetMap")
    systems, notes = [], []
    by_name = {key(prop(o, "Navn") or ""): o for o in routes if "Riks" in str(prop(o, "Sambandstype"))}
    for route, rows in stretches.items():
        o = by_name.get(key(route.replace("–", "-")))
        if not o:
            # NVDB names a multi-stop route by its stops in another order.
            o = next((v for k, v in by_name.items() if sorted(k.split("-")) == sorted(key(route).split("-"))), None)
        if not o:
            sys.exit(f"Norwegian ferries: {route} isn't a national road ferry route in NVDB")
        qs = quays_of(o, quays)
        points = quay_points(route, qs, lines)
        stations, prices = {}, {}
        for stretch, zone, ap1_2025, toll in rows:
            ends = stretch.split("–")
            found = []
            for e in ends:
                hit = [n for n in qs if n.lower().startswith(e.strip().lower())]
                found.append(hit[0] if len(hit) == 1 else None)
            if found.count(None) == 1 and len(qs) == 2:
                found[found.index(None)] = next(n for n in qs if n not in found)
            if None in found:
                sys.exit(f"Norwegian ferries: {route}: {stretch}'s quays not found among {sorted(qs)}")
            if zone not in zones:
                sys.exit(f"Norwegian ferries: {route}: zone {zone} isn't in the price table")
            free = ap1_2025 == 0
            if not free:
                # The 2025 AP1 price (less the on-board toll) is the 2026 one less its 3.6% rise.
                ferry_2025 = ap1_2025 - (int(toll_note.group(1)) if toll and toll_note else 0)
                if abs(zones[zone][0] / 1.036 - ferry_2025) > 3:
                    sys.exit(f"Norwegian ferries: {route} {stretch}: zone {zone}'s AP1 {zones[zone][0]} doesn't follow from {ferry_2025} in 2025")
            if any(e not in points for e in found):
                notes.append(f"{stretch}: OpenStreetMap has no car ferry line from {' or '.join(e for e in found if e not in points)}, so it isn't priced")
                continue
            if toll:
                notes.append(f"{stretch}: the toll (bompenger) charged on board isn't included")
            for e in found:
                stations[e] = points[e]
            p = {}
            for k, (g, _, _) in enumerate(LENGTHS):
                p[g] = 0 if free else round(zones[zone][k] / VAT, 2)
                # Zero-emission: 70% (AP1) or 50% of the full price, to the krone; the discounts apply on it.
                p[f"{g} {ZE}"] = 0 if free else round(krone(zones[zone][k] * (0.7 if k == 0 else 0.5)) / VAT, 2)
            prices[f"{found[0]}|{found[1]}"] = p
            if free:
                notes.append(f"{stretch} is free (priced 0 in the Minister's table)")
        if not prices:
            sys.exit(f"Norwegian ferries: {route}: no stretch priced")
        groups = []
        for g, lo, hi in LENGTHS:
            gg = {"name": g}
            if lo:
                gg["min_length_m"] = lo
            if hi:
                gg["max_length_m"] = hi
            groups.append(gg)
        systems.append({"name": f"{route} ferry", "law": f"AutoPASS-regulativ for ferjetakster: {route}, by stretch (zone)", "groups": ze_groups(groups),
                        "stations": [{"name": n, "points": pts} for n, pts in sorted(stations.items())], "station_match_km": MATCH_KM,
                        "prices": prices, "discounts": [{"name": "AutoPASS ferry account, business, prepaid (40%)", "etc": True, "percent": 40}]})
        print(route, {k: v["AP6"] for k, v in prices.items()}, {n: len(p) for n, p in stations.items()})
    # Moss-Horten: its own price list (the operator's, under its own AutoPASS-regulativ), by length.
    head = re.search(r"Fares (\d\d)\.(\d\d)\.(\d{4}) - (\d\d)\.(\d\d)\.(\d{4})", mh)
    for needle in ("RV.19 Moss - Horten", "All fares are in Norwegian kroner and include 12% VAT.", "To obtain a 30% discount, you must have a valid AutoPASS-chip",
                   "Double fare for vehicles with a width of more than 2,6 meters", "has a trailer, the vehicle is assessed according to the total lenght including cargo"):
        if needle not in re.sub(r"\s+", " ", mh):
            sys.exit(f"Norwegian ferries: Moss-Horten's price list no longer says {needle!r}")
    if not head:
        sys.exit("Norwegian ferries: Moss-Horten's price list has no dates")
    mh_from, mh_to = f"{head.group(3)}-{head.group(2)}-{head.group(1)}", f"{head.group(6)}-{head.group(5)}-{head.group(4)}"
    mh_groups, mh_full, mh_etc = [], {}, {}
    if "Electric and Hydrogen vehicle" not in mh or "registered in the Norwegian Vehicle Register with fuel code 5 (electric) and fuel code 6 (hydrogen)" not in re.sub(r"\s+", " ", mh):
        sys.exit("Norwegian ferries: Moss-Horten's price list no longer has the electric and hydrogen columns")
    for m in re.finditer(r"^AP(\d) (Inntil [\d,]+|[\d,]+ - [\d,]+|Over [\d,]+) meters" + r"\s+(\d+),(\d\d)" * 6, mh, re.M):
        name, span = f"AP{m.group(1)}", m.group(2).replace(",", ".")
        full, tag, deal, ze_full, ze_tag, ze_deal = (int(m.group(k)) + int(m.group(k + 1)) / 100 for k in range(3, 15, 2))
        if abs(full * 0.9 - tag) > 0.01 or abs(full * 0.7 - deal) > 0.01:
            sys.exit(f"Norwegian ferries: Moss-Horten {name}: {tag} and {deal} aren't 10% and 30% off {full}")
        if ze_full != krone(full * (0.7 if name == "AP1" else 0.5)) or abs(ze_full * 0.9 - ze_tag) > 0.01 or abs(ze_full * 0.7 - ze_deal) > 0.01:
            sys.exit(f"Norwegian ferries: Moss-Horten {name}: the electric and hydrogen prices {ze_full}, {ze_tag}, {ze_deal} don't follow from {full}")
        g = {"name": name}
        if span.startswith("Inntil "):
            g["max_length_m"] = float(span.split()[1])
        elif span.startswith("Over "):
            g["min_length_m"] = float(span.split()[1])
        else:
            lo, hi = span.split(" - ")
            g["min_length_m"], g["max_length_m"] = round(float(lo) - 0.01, 2), float(hi)
        mh_groups.append(g)
        mh_full[name], mh_etc[name] = round(full / VAT, 2), round(deal / VAT, 2)
        mh_full[f"{name} {ZE}"], mh_etc[f"{name} {ZE}"] = round(ze_full / VAT, 2), round(ze_deal / VAT, 2)
    if [g["name"] for g in mh_groups] != [f"AP{k}" for k in range(1, 10)]:
        sys.exit(f"Norwegian ferries: Moss-Horten's length groups not read ({[g['name'] for g in mh_groups]})")
    o = by_name.get(key("Moss - Horten"))
    qs = quays_of(o, quays) if o else {}
    points = quay_points("Moss-Horten", qs, lines)
    if sorted(points) != ["Horten", "Moss"]:
        sys.exit(f"Norwegian ferries: Moss-Horten's quays or car ferry line not found ({sorted(qs)}, {sorted(points)})")
    systems.append({"name": "Moss–Horten ferry", "law": f"Rv. 19 Moss-Horten's price list {mh_from} to {mh_to} (its own AutoPASS-regulativ): the full price by length; `etc` with an AutoPASS tag and a prepaid Moss-Horten agreement (30% off)",
                    "groups": ze_groups(mh_groups), "stations": [{"name": n, "points": pts} for n, pts in sorted(points.items())], "station_match_km": MATCH_KM,
                    "prices": {"Moss|Horten": mh_full}, "etc_prices": {"Moss|Horten": mh_etc}})
    print("Moss–Horten", mh_full["AP6"], mh_etc["AP6"], {n: len(p) for n, p in points.items()})
    start = max(start, mh_from)
    t = {"country": "NO", "currency": "NOK", "valid_from": start, "crossings": True,
         "name": "Norwegian national road ferries (riksvegferjer)",
         "law": (f"AutoPASS-regulativ for ferjetakster from {start} (Statens vegvesen, set by the Ministry of Transport): the full price per crossing by zone and the vehicle's "
                 "total length with trailer and load (AP1 up to 6 m ... AP6 14.51-17.5 m, AP7 17.51-19.5 m, AP8 19.51-22 m, AP9 over 22 m); the table includes 12% VAT, "
                 "the prices here exclude it. Paying by AutoPASS tag with a prepaid business ferry account (`etc`) takes 40% off (a central AutoPASS agreement alone, 10%). "
                 "Zero-emission trucks (CO2 class 5; the regulativ: registered with fuel code 5, electric, or 6, hydrogen, in the Norwegian register, or for a foreign one in AutoPASS's own routine, else full price) "
                 "pay 70% (AP1) or 50% (AP2-AP9) of their group's price, to the krone, and the discounts apply on that. Each national road ferry route's zone by stretch from the Minister of Transport's answer to the Storting "
                 "of 11 December 2025 (written question 699), checked against the table; the quays from NVDB, matched where a route goes out on OpenStreetMap's car ferry line from them. "
                 f"Moss-Horten has a regulativ of its own: the operator's price list from {mh_from} to {mh_to}, by length (AP4 10.01-12 m, AP5 12.01-14 m, AP6 14.01-17.5 m), 30% off with a prepaid Moss-Horten agreement (`etc`), its electric and hydrogen prices for zero-emission trucks, "
                 "double for vehicles wider than 2.6 m (not applied). "
                 + " ".join(f"{n}." for n in notes)),
         "sources": [{"title": "Statens vegvesen: AutoPASS-regulativ for ferjetakster, takster (fullpris) fra 1. januar 2026", "url": URLS["price"]},
                     {"title": "Statens vegvesen: AutoPASS-regulativ for ferjetakster fra 1. januar 2026", "url": URLS["rules"]},
                     {"title": "Samferdselsministeren: svar på skriftleg spørsmål nr. 699 (2025-2026), billettpris og takstsone for riksvegferjesambanda", "url": URLS["answer"]},
                     {"title": "NVDB (Statens vegvesen): Ferjesamband (770) and Ferjekai (64)", "url": "https://nvdbapiles.atlas.vegvesen.no/vegobjekter/api/v4/vegobjekter/770"},
                     {"title": f"Rv. 19 Moss-Horten: fares {mh_from} to {mh_to} (Torghatten / Bastø Fosen)", "url": URLS["mh"]},
                     {"title": "OpenStreetMap (Overpass API): car ferry lines (route=ferry) by the quays", "url": "https://www.openstreetmap.org/"}],
         "vehicles": "Vehicles over 3.5 t, by total length with trailer and load (give truck.length_m; 16.5 m assumed)", "min_kg": 3501,
         "tolled_roads": "Norway's national road ferry routes (riksvegferjesamband), from quay to quay: those priced by the AutoPASS-regulativ and Moss-Horten.",
         "closed_systems": systems, "rows": []}
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"no-ferries-{start}.json")
    json.dump(t, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, len(systems), "routes")


if __name__ == "__main__":
    main(*sys.argv[1:])
