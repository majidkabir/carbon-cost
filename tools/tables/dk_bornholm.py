"""Builds Bornholmslinjen's ferries to Bornholm for trucks
(dk-bornholm-<year>-01-01.json, one per year the page prices), from

- the operator's freight page (dk-bornholm-freight.html): per single trip,
  excluding VAT, for each year it lists ("PRICES 2026 ... until December
  31st 2026"): a lorry (tractor unit) under or over 10 m, a semi-trailer
  to 17 m and a road train to 19 m with a price per metre over, empty or
  loaded, on Rønne-Køge and Rønne-Ystad; on Rønne-Sassnitz one price;
- OpenStreetMap (dk-bornholm-osm.json, Overpass): the ferry lines, the
  terminals and the ports' places.

carbon-cost prices a trip with cargo: the loaded prices. A truck's type is
read from its length by the maximums of Directive 96/53/EC: to 10 m and
to 12 m a lorry (under or over 10 m), to 17 m an articulated vehicle
(16.5 m at most), longer a road train (18.75 m), with the price per metre
(each started metre) over 19 m. Extra width (over 2.6 m, +100%) isn't
applied. Each route is a closed system on OpenStreetMap's car ferry lines
(ferry_osm.py); lines that run together are one.

Usage: python3 dk_bornholm.py <fetched dir> <out dir>
"""
import html, json, os, re, sys

from ferry_osm import MATCH_KM, lines_of, port_places, systems as place_systems

PORTS = {"Rønne": ("place", "Rønne"), "Ystad": ("place", "Ystad"), "Køge": ("place", "Køge"), "Sassnitz": ("place", "Mukran")}
ROUTES = {"Rønne–Køge": ("Køge", "Rønne"), "Rønne–Ystad": ("Ystad", "Rønne"), "Rønne–Sassnitz": ("Sassnitz", "Rønne")}
N = r"DKK ([\d.]+)"


def text(path):
    t = open(path, encoding="utf-8").read()
    t = re.sub(r"<script.*?</script>", " ", t, flags=re.S)
    t = re.sub(r"<style.*?</style>", " ", t, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", html.unescape(t))


def dkk(s):
    return int(s.replace(".", ""))


def part(sec, head):
    i = sec.index(head)
    return sec[i:sec.index("A reservation can", i)]


def year_prices(sec):
    """{route: {"u10", "o10", "semi", "train", "metre"}} loaded, DKK."""
    lorry, semi, train = part(sec, "Lorry - O/U 10 m."), part(sec, "Semi-trailer - 17 m."), part(sec, "Road train - 19 m.")
    out = {}
    for route, key in (("Rønne–Køge", "Køge"), ("Rønne–Ystad", "Ystad")):
        m = re.search(rf"{key} {N} {N} {N} {N}", lorry)
        s = re.search(rf"{key} {N} {N} \+ 100% af enhedsprisen {N}", semi)
        t = re.search(rf"{key} {N} {N} \+ 100% af enhedsprisen {N}", train)
        if not (m and s and t):
            sys.exit(f"Bornholmslinjen: {route}: the prices not read")
        if s.group(3) != t.group(3):
            sys.exit(f"Bornholmslinjen: {route}: two prices per metre over ({s.group(3)}, {t.group(3)})")
        out[route] = {"u10": dkk(m.group(2)), "o10": dkk(m.group(4)), "semi": dkk(s.group(2)), "train": dkk(t.group(2)), "metre": dkk(t.group(3))}
    m = re.search(rf"Rønne-Sassnitz {N} {N} {N} Sassnitz-Rønne {N} {N} {N}", lorry)
    s = re.search(rf"Rønne-Sassnitz {N} {N} {N} Sassnitz-Rønne {N} {N} {N}", semi)
    t = re.search(rf"Rønne-Sassnitz {N} {N} {N} Sassnitz-Rønne {N} {N} {N}", train)
    if not (m and s and t) or m.group(1, 2) != m.group(4, 5) or s.group(1, 3) != s.group(4, 6) or t.group(1, 3) != t.group(4, 6):
        sys.exit("Bornholmslinjen: Rønne–Sassnitz: the prices not read, or they differ by direction")
    out["Rønne–Sassnitz"] = {"u10": dkk(m.group(1)), "o10": dkk(m.group(2)), "semi": dkk(s.group(1)), "train": dkk(t.group(1)), "metre": dkk(t.group(3))}
    return out


GROUPS = [("up to 10 m", None, 10, "u10", 0), ("10-12 m", 10, 12, "o10", 0), ("12-17 m", 12, 17, "semi", 0), ("17-19 m", 17, 19, "train", 0)] + [
    (f"{m - 1}-{m} m", m - 1, m, "train", m - 19) for m in range(20, 27)]


def main(fetched, out):
    try:
        page = text(os.path.join(fetched, "dk-bornholm-freight.html"))
        osm = json.load(open(os.path.join(fetched, "dk-bornholm-osm.json")))
    except (OSError, ValueError):
        print("Bornholmslinjen: a source wasn't fetched; not built")
        return
    if "all prices on the page and in the list are listed exclusive of VAT" not in page:
        sys.exit("Bornholmslinjen: the page no longer says its prices exclude VAT")
    years = re.findall(r"PRICES (\d{4}) BORNHOLMSLINJEN is offering the following prices until December 31st (\d{4})", page)
    if not years or any(a != b for a, b in years):
        sys.exit(f"Bornholmslinjen: the years not read: {years}")
    heads = [page.index(f"PRICES {y} BORNHOLMSLINJEN") for y, _ in years] + [len(page)]
    lines, permit = lines_of(osm)
    pos = port_places(osm, lines, PORTS)
    placed, notes = place_systems({r: [ends] for r, ends in ROUTES.items()}, pos, lines, permit, lambda msg: sys.exit(f"Bornholmslinjen: {msg}"))
    groups = [{"name": n, "min_kg": 3501, "max_length_m": hi, **({"min_length_m": lo} if lo else {})} for n, lo, hi, _, _ in GROUPS]
    for k, (y, _) in enumerate(years):
        pr = year_prices(page[heads[k]:heads[k + 1]])
        systems = []
        for rs, stations, pairs in placed:
            prices = {}
            for r, a, b in pairs:
                p = pr[r]
                prices[f"{a}|{b}"] = {n: p[key] + extra * p["metre"] for n, _, _, key, extra in GROUPS}
            systems.append({"name": f"Bornholmslinjen: {' / '.join(rs)}", "law": f"Bornholmslinjen's freight prices {y}, loaded: {' / '.join(rs)}",
                            "groups": groups, "stations": [{"name": n, "points": pts} for n, pts in sorted(stations.items())],
                            "station_match_km": MATCH_KM, "prices": prices})
        t = {"country": "DK", "currency": "DKK", "valid_from": f"{y}-01-01", "valid_to": f"{y}-12-31", "crossings": True, "ferry": True,
             "name": "Bornholmslinjen's ferries to Bornholm, trucks",
             "law": (f"Bornholmslinjen's freight prices for {y} (per single trip, excluding VAT), loaded: "
                     + "; ".join(f"{r} lorry under 10 m {p['u10']}, over 10 m {p['o10']}, semi-trailer to 17 m {p['semi']}, road train to 19 m {p['train']} DKK "
                                 f"and {p['metre']} DKK per metre over" for r, p in pr.items())
                     + ". A truck's type from its length by Directive 96/53/EC's maximums: to 10 m and to 12 m a lorry, to 17 m an articulated vehicle, "
                       "longer a road train (each started metre over 19 m at the price per metre). Empty trucks' prices and extra width (+100%) aren't used. "
                       "Ports at OpenStreetMap's places, priced where the line goes out on its car ferry line. " + " ".join(f"{x}." for x in notes)),
             "sources": [{"title": "Bornholmslinjen: freight prices", "url": "https://bornholmslinjen.com/practical-information/freight"},
                         {"title": "OpenStreetMap (Overpass API): ferry lines, terminals and places around Bornholm", "url": "https://www.openstreetmap.org/"}],
             "vehicles": "Trucks over 3.5 t, by length (truck.length_m)", "min_kg": 3501,
             "tolled_roads": "Bornholmslinjen's ferries Rønne–Køge, Rønne–Ystad and Rønne–Sassnitz.",
             "closed_systems": systems, "rows": []}
        os.makedirs(out, exist_ok=True)
        path = os.path.join(out, f"dk-bornholm-{y}-01-01.json")
        json.dump(t, open(path, "w"), ensure_ascii=False, indent=1)
        print(path, {r: p for r, p in pr.items()}, "; ".join(notes))


if __name__ == "__main__":
    main(*sys.argv[1:])
