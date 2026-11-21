"""Builds Jadrolinija's state ferry lines (Croatia) for goods vehicles as
toll systems (hr-jadrolinija-<date>.json), from

- each line's timetable and price list for the year (hr-jadro-<line>.pdf,
  linked from the line's page, hr-jadro-<line>-page.html): the fare by
  relation for goods vehicles and trailers (teretna vozila, priključna
  vozila) by load capacity (nosivost): up to 3 t, 3.01-4 t, 4.01-5 t, and
  from 5.01 t a fare per tonne of it, for each vehicle on its own, but for a
  tractor with semi-trailer per tonne of the semi-trailer's; off-season and
  season prices (or one price for the year), the season's days as the price
  list gives them; the prices include port dues and VAT;
- OpenStreetMap (hr-jadrolinija-osm.json, Overpass): the ferry lines, the
  ferry terminals and the places of the ports.

Each line (or lines that share a ferry line or a harbour mouth) is a closed
system placed on OpenStreetMap's car ferry lines (ferry_osm.py), twice: one
system with the fares up to 5 t of load capacity, one with the fare per
tonne over 5 t (the truck's capacity_kg: ORCT unit t on load_capacity_kg);
the one the truck isn't in is free. VAT is taken out at Croatia's standard
25%, the rate Jadrolinija's price lists named until 2024 (those of 2026 say
"VAT included"); the port dues stay in. The island residents' and public
services' prices aren't used.

Usage: python3 hr_jadrolinija.py <fetched dir> <out dir>
"""
import datetime, json, os, re, sys

from ferry_osm import MATCH_KM, lines_of, port_places, systems as place_systems

VAT = 1.25
E = r"(\d{1,4}),(\d\d) EUR"
# Each line: its source ids (the price list and the line's page).
LINES = ["332", "334", "335", "338", "401", "431", "432", "433", "434", "435", "532", "602", "604", "606", "631", "632",
         "633", "634", "635", "636", "638", "831", "832"]
# A price list's port name -> the port (as PORTS names it).
ALIAS = {"DRVENIK V.": "DRVENIK VELI", "DRVENIK M.": "DRVENIK MALI", "DRVENIK VELIKI": "DRVENIK VELI", "RAVA MALA": "MALA RAVA"}
# Each port: its ferry terminal in OpenStreetMap (amenity=ferry_terminal)
# by name, else a place by name; the nearest car ferry line within 3 km is
# where it is.
PORTS = {
    "BIOGRAD NA MORU": ("terminal", "Biograd na Moru"), "TKON": ("terminal", "Tkon"), "BRESTOVA": ("terminal", "Brestova"),
    "POROZINA": ("terminal", "Porozina"), "DRVENIK": ("terminal", "Drvenik"), "SUĆURAJ": ("place", "Sućuraj"),
    "DUBROVNIK": ("terminal", "Dubrovnik"), "SUĐURAĐ": ("terminal", "Suđurađ"), "KOLOČEP": ("terminal", "Koločep"),
    "OREBIĆ": ("place", "Orebić"), "DOMINČE": ("terminal", "Dominče (Korčula)"), "PRAPRATNO": ("terminal", "Prapratno"),
    "SOBRA": ("terminal", "Sobra"), "PRIZNA": ("terminal", "Prizna"), "ŽIGLJEN": ("terminal", "Žigljen"),
    "ŠIBENIK": ("terminal", "Šibenik"), "ZLARIN": ("terminal", "Zlarin"), "OBONJAN": ("place", "Obonjan"),
    "KAPRIJE": ("terminal", "Kaprije"), "ŽIRJE": ("terminal", "Žirje"), "SPLIT": ("place", "Split"),
    "ROGAČ": ("terminal", "Rogač"), "STARI GRAD": ("terminal", "Stari Grad"), "SUPETAR": ("terminal", "Supetar"),
    "VELA LUKA": ("terminal", "Vela luka"), "UBLI": ("terminal", "Uble"), "VIS": ("terminal", "Vis"),
    "SUMARTIN": ("place", "Sumartin"), "MAKARSKA": ("place", "Makarska"), "TROGIR": ("terminal", "Soline"),
    "DRVENIK VELI": ("terminal", "Drvenik Veli"), "DRVENIK MALI": ("terminal", "Drvenik Mali"), "LOPAR": ("terminal", "Lopar"),
    "VALBISKA": ("terminal", "Valbiska"), "MERAG": ("terminal", "Merag"), "BRBINJ": ("terminal", "Brbinj"),
    "ZADAR": ("terminal", "Gaženica"), "PREKO": ("terminal", "Preko"), "OŠLJAK": ("terminal", "Luka Ošljak"),
    "PREMUDA": ("terminal", "Premuda"), "SILBA": ("terminal", "Silba"), "OLIB": ("terminal", "Olib"),
    "IST": ("terminal", "Port of Ist"), "MALI LOŠINJ": ("terminal", "Mali Lošinj"), "RIVANJ": ("terminal", "Rivanj"),
    "SESTRUNJ": ("terminal", "Sestrunj"), "ZVERINAC": ("terminal", "Zverinac"), "MOLAT": ("terminal", "Molat"),
    "BRŠANJ": ("terminal", "Bršanj (Iž)"), "RAVA": ("terminal", "Rava"), "MALA RAVA": ("terminal", "Mala Rava"),
    "PLOČE": ("terminal", "Ploče"), "TRPANJ": ("terminal", "Trpanj"),
}
HEADER_WORDS = ("IZVANSEZONSK", "SEZONSK", "OTOČN", "CJENIK", "CJELOGODIŠNJ", "JAVNE", "SLUŽBE")


def eur(m):
    return round(int(m[0]) + int(m[1]) / 100, 2)


def day(d, m, y):
    return datetime.date(int(y), int(m), int(d))


def parse(text, line):
    """The line's relations with their goods vehicle fares, and its season."""
    flat = re.sub(r"\s+", " ", text)
    head = re.search(r"TRAJEKTNA LINIJA br\. *(\d+)", text)
    if not head or head.group(1) != line:
        sys.exit(f"Jadrolinija {line}: the price list is of line {head.group(1) if head else None}")
    for needle in ("U cijenu karte su uključene lučke pristojbe i PDV",
                   "Za teretna i priključna vozila iznad 5,01 tona nosivosti ukupan broj tona množi se sa cijenom po toni za svako vozilo posebno",
                   "osim kada tegljač koji vuče poluprikolicu (priključno vozilo) tada se naplaćuje po toni nosivosti poluprikolice (priključnog vozila)"):
        if needle not in flat:
            sys.exit(f"Jadrolinija {line}: the price list no longer says {needle!r}")
    season = re.search(r"Izvansezonski cjenik vrijedi za razdoblje od (\d\d)\.(\d\d)\.\s*[-–]\s*(\d\d)\.(\d\d)\.(\d{4})\.?,? i "
                       r"(\d\d)\.(\d\d)\.\s*[-–]\s*(\d\d)\.(\d\d)\.(\d{4})", flat)
    year = re.search(r"Cjenik vrijedi (?:za razdoblje )?od 01\.01\.\s*(?:-|do)\s*31\.12\.(\d{4})", flat)
    if season:
        a1, a2, b1, b2 = day(*season.group(1, 2, 5)), day(*season.group(3, 4, 5)), day(*season.group(6, 7, 10)), day(*season.group(8, 9, 10))
        if a1.month != 1 or a1.day != 1 or b2.month != 12 or b2.day != 31:
            sys.exit(f"Jadrolinija {line}: the off-season isn't from 1 January to 31 December's ends: {season.group(0)}")
        span = (a1.year, [(a2 + datetime.timedelta(days=1)).isoformat(), (b1 - datetime.timedelta(days=1)).isoformat()])
    elif year:
        span = (int(year.group(1)), None)
    else:
        sys.exit(f"Jadrolinija {line}: the price list's period not read")
    lines = text.splitlines()
    blocks, i = [], 0
    while i < len(lines):
        if re.match(r"\s*(CJENIK:|Relacije:)", lines[i]):
            rels, j = [], i
            while j < len(lines) and not re.match(r"\s*1\.\s", lines[j]) and j < i + 10:
                t = re.sub(r"^\s*(CJENIK:|Relacije:)", "", lines[j]).strip()
                t = re.sub(r"^_+\s*", "", re.split(r"\s{3,}", t)[0]).strip()
                t = re.sub(r"\s+i obratno$", "", t).strip()
                if not t or any(w in t for w in HEADER_WORDS):
                    pass
                elif " - " in t:
                    rels.append(t)
                elif rels and re.fullmatch(r"[A-ZČĆŠĐŽ ,./]+", t):
                    rels[-1] += " " + t
                j += 1
            blocks.append({"rels": rels, "rows": None})
            i = j
            continue
        if blocks and "TERETNA VOZILA" in lines[i] and blocks[-1]["rows"] is None:
            vals, k = [], i
            while k < len(lines) and len(vals) < 4 and k < i + 12:
                v = re.findall(E, lines[k])
                if v:
                    vals.append([eur(x) for x in v])
                k += 1
            labels = re.sub(r"\s+", " ", re.sub(E, " ", " ".join(lines[i:k + 1])))
            for want in ("do 3 t nosivosti", "od 3,01 t do 4,0 t nosivosti", "od 4,01 t do 5,0 t nosivosti", "od 5,01 t na više"):
                if want not in labels:
                    sys.exit(f"Jadrolinija {line}: the goods vehicle rows no longer say {want!r}")
            if len(vals) != 4 or len({len(v) for v in vals}) != 1 or len(vals[0]) not in (3, 4):
                sys.exit(f"Jadrolinija {line}: the goods vehicle rows not read: {vals}")
            if (len(vals[0]) == 4) != bool(season):
                sys.exit(f"Jadrolinija {line}: {len(vals[0])} price columns, but {'a season' if season else 'one price for the year'}")
            blocks[-1]["rows"] = vals
        i += 1
    out = []
    for b in blocks:
        if not b["rows"]:
            continue
        pairs = []
        for rel in b["rels"]:
            a, rest = rel.split(" - ", 1)
            for x in re.split(r",\s*|/", rest):
                x = x.strip().rstrip(",")
                if x:
                    pairs.append((ALIAS.get(a.strip(), a.strip()), ALIAS.get(x, x)))
        if not pairs:
            sys.exit(f"Jadrolinija {line}: a price block without its relations")
        out.append((pairs, b["rows"]))
    if not out:
        sys.exit(f"Jadrolinija {line}: no goods vehicle prices read")
    return span, out


def places(osm, lines):
    return port_places(osm, lines, PORTS)


def main(fetched, out):
    try:
        osm = json.load(open(os.path.join(fetched, "hr-jadrolinija-osm.json")))
        texts = {n: open(os.path.join(fetched, f"hr-jadro-{n}.txt"), encoding="utf-8").read() for n in LINES}
        pages = {n: open(os.path.join(fetched, f"hr-jadro-{n}-page.html"), encoding="utf-8", errors="replace").read() for n in LINES}
    except (OSError, ValueError):
        print("Jadrolinija: a source wasn't fetched; not built")
        return
    src = {s["id"]: s for s in json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources.json")))["sources"]}
    for n in LINES:
        url = src[f"hr-jadro-{n}"]["url"]
        if url.rsplit("/", 1)[-1] not in pages[n]:
            sys.exit(f"Jadrolinija {n}: the line's page links another price list than {url}: a new one, for tools/tables/sources.json")
    years, routes, fares, seasons = set(), {}, {}, {}
    for n in LINES:
        (year, season), blocks = parse(texts[n], n)
        years.add(year)
        for k, (pairs, rows) in enumerate(blocks):
            r = f"{n}" + (f" ({k + 1})" if len(blocks) > 1 else "")
            routes[r] = []
            for a, b in pairs:
                for x in (a, b):
                    if x not in PORTS:
                        sys.exit(f"Jadrolinija {n}: a port PORTS doesn't have: {x!r}")
                if (a, b) not in routes[r] and (b, a) not in routes[r]:
                    routes[r].append((a, b))
            fares[r], seasons[r] = rows, season
    if len(years) != 1:
        sys.exit(f"Jadrolinija: price lists of several years: {sorted(years)}")
    year = years.pop()
    lines, permit = lines_of(osm)
    pos = places(osm, lines)
    placed, notes = place_systems(routes, pos, lines, permit, lambda m: sys.exit(f"Jadrolinija: {m}"))
    small = [{"name": "load capacity up to 3 t", "min_kg": 3501, "max_capacity_kg": 3000},
             {"name": "load capacity 3.01-4 t", "min_kg": 3501, "min_capacity_kg": 3000, "max_capacity_kg": 4000},
             {"name": "load capacity 4.01-5 t", "min_kg": 3501, "min_capacity_kg": 4000, "max_capacity_kg": 5000}]
    big = [{"name": "per tonne of load capacity over 5 t", "min_kg": 3501, "min_capacity_kg": 5000}]
    systems = []
    for rs, stations, pairs in placed:
        # Lines with one price for the year keep it in the season.
        ss = {tuple(seasons[r]) for r in rs if seasons[r]}
        if len(ss) > 1:
            sys.exit(f"Jadrolinija: lines {rs} share a system but not their season ({ss})")
        season = ss.pop() if ss else None
        law = "; ".join(f"line {r}" for r in rs)
        for kind, groups, col in (("up to 5 t", small, (0, 1, 2)), ("per tonne over 5 t", big, (3,))):
            prices, season_prices = {}, {}
            for r, a, b in pairs:
                rows = fares[r]
                prices[f"{a}|{b}"] = {g["name"]: round(rows[i][0] / VAT, 2) for g, i in zip(groups, col)}
                if season:
                    s_col = 1 if seasons[r] else 0
                    season_prices[f"{a}|{b}"] = {g["name"]: round(rows[i][s_col] / VAT, 2) for g, i in zip(groups, col)}
            s = {"name": f"Jadrolinija {' / '.join(rs)}, goods vehicles {kind}",
                 "law": f"Jadrolinija's {year} price list, {law}: goods vehicles and trailers {kind} of load capacity" + (
                     f" (season {season[0]} to {season[1]})" if season else " (one price for the year)"),
                 "groups": groups, "stations": [{"name": p, "points": pts} for p, pts in sorted(stations.items())],
                 "station_match_km": MATCH_KM, "prices": prices, "unmatched": "free"}
            if season:
                s["season"], s["season_prices"] = [list(season)], season_prices
            if kind != "up to 5 t":
                s["unit"], s["mass_basis"] = "t", "load_capacity_kg"
            systems.append(s)
        print(" / ".join(rs), {k: v for k, v in list(systems[-1]["prices"].items())[:3]}, {p: len(x) for p, x in stations.items()})
    t = {"country": "HR", "currency": "EUR", "valid_from": f"{year}-01-01", "valid_to": f"{year}-12-31", "crossings": True, "ferry": True,
         "name": "Jadrolinija's state ferry lines, goods vehicles",
         "law": (f"Jadrolinija's price lists for {year}, line by line (state ferry lines, the fares the Agency for Coastal Line Traffic approves): "
                 "goods vehicles and trailers by load capacity (nosivost): up to 3 t, 3.01-4 t and 4.01-5 t a fare each, from 5.01 t a fare per tonne of it, "
                 "for each vehicle on its own, but a tractor with semi-trailer per tonne of the semi-trailer's (give truck.capacity_kg; without it the fare isn't priced). "
                 "Off-season and season prices by the season's days in each price list (or one price for the year). The prices include port dues and VAT; "
                 "VAT is taken out at Croatia's standard 25% (the rate Jadrolinija's price lists named until 2024), the port dues stay in. "
                 "Island residents' and public services' prices aren't used. The ports are OpenStreetMap's ferry terminals (else the place), "
                 "priced where a line goes out on OpenStreetMap's car ferry line from them; lines that share a ferry line or a harbour mouth are one system, "
                 "priced from the first port passed to the last. " + " ".join(f"{x}." for x in notes)),
         "sources": [{"title": f"Jadrolinija: line {n}, timetable and price list for {year}", "url": src[f"hr-jadro-{n}"]["url"]} for n in LINES]
                    + [{"title": "Jadrolinija: local lines", "url": "https://www.jadrolinija.hr/hr/putovanja/lokalne_linije"},
                       {"title": "OpenStreetMap (Overpass API): ferry lines, ferry terminals and places on the Croatian coast", "url": "https://www.openstreetmap.org/"}],
         "vehicles": "Goods vehicles over 3.5 t, by load capacity (give truck.capacity_kg: the semi-trailer's for a tractor with semi-trailer)", "min_kg": 3501,
         "tolled_roads": "Jadrolinija's state ferry lines on the Croatian coast, from port to port.",
         "closed_systems": systems, "rows": []}
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"hr-jadrolinija-{year}-01-01.json")
    json.dump(t, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, len(systems), "systems;", "; ".join(notes))


if __name__ == "__main__":
    main(*sys.argv[1:])
