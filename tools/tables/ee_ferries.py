"""Builds Estonia's state ferry lines to Saaremaa (Muhu) and Hiiumaa for
trucks (ee-ferries-<date>.json), from

- the minister's regulation on the ferry prices on the Kuivastu-Virtsu,
  Rohuküla-Heltermaa and Sõru-Triigi lines (nr 120 of 25.09.2015) in force,
  as Riigi Teataja's public API gives it (ee-ferries.json, the text
  ee-ferries-text.html and its annex ee-ferries-lisa-1.txt): the annex's
  ticket for a truck over 3,500 kg of maximum mass ("Täismassiga üle 3500
  kg veoauto, traktori ja liikurmasina pilet") per line; § 6 raises it by
  1.2 for departures towards the islands (Virtsu-Kuivastu,
  Rohuküla-Heltermaa) on Fridays from 13:00 and back (Kuivastu-Virtsu,
  Heltermaa-Rohuküla) on Sundays from 13:00, rounded to 5 cents; by 1.5
  for a vehicle over 2.6 m wide and 2.0 for one over 4 m high (not
  applied: a truck within the EU's 2.55 m and 4 m);
- OpenStreetMap (ee-ferries-osm.json, Overpass): the ferry lines, the
  ferry terminals and the places of the ports.

Each line is a closed system, directed, placed on OpenStreetMap's car
ferry lines (ferry_osm.py). The regulation doesn't say whether VAT is in
the prices; they are taken as it sets them. Residents' prices aren't used.

Usage: python3 ee_ferries.py <fetched dir> <out dir>
"""
import datetime, html, json, os, re, sys

from ferry_osm import MATCH_KM, lines_of, port_places, systems as place_systems

LINES = {"Kuivastu–Virtsu": ("2.1", ("Virtsu", "Kuivastu")), "Rohuküla–Heltermaa": ("2.2", ("Rohuküla", "Heltermaa")),
         "Sõru–Triigi": ("2.3", ("Triigi", "Sõru"))}
# (mainland or Muhu side, island side): the Friday coefficient goes towards
# the islands, the Sunday one back, on the first two lines.
PORTS = {"Virtsu": ("terminal", "Virtsu sadam"), "Kuivastu": ("terminal", "Kuivastu sadam"), "Rohuküla": ("terminal", "Rohuküla sadam"),
         "Heltermaa": ("place", "Heltermaa"), "Sõru": ("place", "Sõru"), "Triigi": ("terminal", "Triigi")}
TRUCK = "Täismassiga üle 3500 kg veoauto, traktori ja liikurmasina pilet"


def text(path):
    t = open(path, encoding="utf-8").read()
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", html.unescape(t))


def num(s):
    return float(s.replace(",", "."))


def day(s):
    return datetime.datetime.strptime(s, "%d.%m.%Y").date().isoformat()


def round5(v):
    return round(round(v * 20) / 20, 2)


def main(fetched, out):
    try:
        meta = json.load(open(os.path.join(fetched, "ee-ferries.json")))
        raw = open(os.path.join(fetched, "ee-ferries-text.html"), encoding="utf-8").read()
        act = text(os.path.join(fetched, "ee-ferries-text.html"))
        lisa = open(os.path.join(fetched, "ee-ferries-lisa-1.txt"), encoding="utf-8").read()
        osm = json.load(open(os.path.join(fetched, "ee-ferries-osm.json")))
    except (OSError, ValueError):
        print("Estonia's ferries: a source wasn't fetched; not built")
        return
    p = meta["aktiParameetrid"]
    if not p["pealkiri"].startswith("Avaliku teenindamise lepingu alusel teostataval liiniveol sõitja kõrgeim piletihind"):
        sys.exit(f"Estonia's ferries: another act: {p['pealkiri']}")
    # The annex: the truck ticket per line.
    flat = re.sub(r"\s+", " ", lisa)
    m = re.search(r"\(\S+ (\d\d\.\d\d\.\d{4})\. a määruse nr (\d+) sõnastuses\)", flat)
    if not m:
        sys.exit("Estonia's ferries: the annex's wording not read")
    wording = m.group(1)
    prices = {}
    for line, (sec, _) in LINES.items():
        heads = {s: re.search(rf"(?<![\d.]){re.escape(s)}\.?\s*(?=[A-ZÕÄÖÜŠŽ])", flat) for s, _ in LINES.values()}
        if not all(heads.values()):
            sys.exit(f"Estonia's ferries: the annex's sections not found: {[s for s, h in heads.items() if not h]}")
        i = heads[sec].start()
        nxt = [h.start() for s, h in heads.items() if h.start() > i]
        part = flat[i:min(nxt) if nxt else len(flat)]
        # The price sits before or after the label's second line.
        mm = re.search(r"Täismassiga üle 3500 kg veoauto, traktori ja\s+(?:(\d+(?:,\d+)?)\s+)?liikurmasina pilet\s*(\d+(?:,\d+)?)?", part)
        v = mm and (mm.group(1) or mm.group(2))
        if not v:
            sys.exit(f"Estonia's ferries: {line}: the truck ticket not read")
        prices[line] = num(v)
    # § 6: the coefficients.
    s6 = act[act.index("§ 6."):act.index("§ 7.")]
    for needle in ("Virtsu-Kuivastu ja Rohuküla-Heltermaa suunal väljumistel reedeti alates kella 13.00 on sõidukipileti hinna kordaja 1,2",
                   "Kuivastu-Virtsu ja Heltermaa-Rohuküla suunal väljumistel pühapäeviti alates kella 13.00 on sõidukipileti hinna kordaja 1,2",
                   "ümardatakse hinnad viie sendi täpsusega", "üle 2,6-meetrise laiusega sõiduki pileti hinna kordaja on 1,5",
                   "üle neljameetrise kõrgusega sõiduki pileti hinna kordaja on 2,0"):
        if needle not in s6:
            sys.exit(f"Estonia's ferries: § 6 no longer says {needle!r}")
    # In force from the latest of the annex's wording and § 6's changes.
    amend = re.findall(r"(\d\d\.\d\d\.\d{4}) RT I, \d\d\.\d\d\.\d{4}, \d+ (\d\d\.\d\d\.\d{4})", act)
    starts = [day(j) for a, j in amend if a == wording] + [day(d) for d in re.findall(r"jõust\. (\d\d\.\d\d\.\d{4})", s6)]
    if not any(day(j) for a, j in amend if a == wording):
        sys.exit(f"Estonia's ferries: the annex's wording of {wording} isn't among the act's amendments")
    start = max(starts)
    # Places on OpenStreetMap's ferry lines.
    lines, permit = lines_of(osm)
    pos = port_places(osm, lines, PORTS)
    routes = {line: [ends] for line, (_, ends) in LINES.items()}
    placed, notes = place_systems(routes, pos, lines, permit, lambda msg: sys.exit(f"Estonia's ferries: {msg}"))
    group = [{"name": "trucks over 3.5 t", "min_kg": 3501}]
    systems = []
    for rs, stations, pairs in placed:
        base, timed = {}, []
        fri, sun = {}, {}
        for r, a, b in pairs:
            v = prices[r]
            out_, back = LINES[r][1]
            for x, y in ((a, b), (b, a)):
                base[f"{x}|{y}"] = {"trucks over 3.5 t": v}
            if r != "Sõru–Triigi":
                fri[f"{out_}|{back}"] = {"trucks over 3.5 t": round5(v * 1.2)}
                sun[f"{back}|{out_}"] = {"trucks over 3.5 t": round5(v * 1.2)}
        if fri:
            timed = [{"label": "Friday from 13:00 towards the islands (× 1.2)", "weekdays": [5], "times": [["13:00", "24:00"]], "prices": fri},
                     {"label": "Sunday from 13:00 back (× 1.2)", "weekdays": [7], "times": [["13:00", "24:00"]], "prices": sun}]
        s = {"name": f"Estonia's state ferries: {' / '.join(rs)}", "law": f"Regulation nr 120 of 25.09.2015, annex and § 6: {' / '.join(rs)}",
             "groups": group, "stations": [{"name": n, "points": pts} for n, pts in sorted(stations.items())],
             "station_match_km": MATCH_KM, "prices": base, "directed": True}
        if timed:
            s["time_prices"] = timed
        systems.append(s)
        print(" / ".join(rs), base, timed and {k: v for t in timed for k, v in t["prices"].items()})
    t = {"country": "EE", "currency": "EUR", "valid_from": start, "crossings": True, "ferry": True,
         "name": "Estonia's state ferries to Muhu, Saaremaa and Hiiumaa, trucks",
         "law": (f"Regulation nr 120 of 25.09.2015 of the minister on the ferry prices on the Kuivastu–Virtsu, Rohuküla–Heltermaa and Sõru–Triigi lines, "
                 f"version in force ({p['avaldamiseKuupaev'][:10]} publication), annex in the wording of {wording}: the ticket of a truck over 3,500 kg "
                 + ", ".join(f"{k} {v:.2f} EUR" for k, v in prices.items())
                 + "; § 6: × 1.2 for departures towards the islands (Virtsu–Kuivastu, Rohuküla–Heltermaa) on Fridays from 13:00 and back on Sundays from 13:00, "
                 "rounded to 5 cents; × 1.5 over 2.6 m wide and × 2.0 over 4 m high (not applied: a truck within 2.55 m and 4 m). "
                 "The regulation doesn't say whether VAT is in the prices; they are taken as it sets them. Residents' prices aren't used. "
                 "Ports at OpenStreetMap's ferry terminals (else the place), priced where the line goes out on OpenStreetMap's car ferry line. "
                 + " ".join(f"{x}." for x in notes)),
         "sources": [{"title": "Riigi Teataja: määrus nr 120 (25.09.2015), version in force", "url": f"https://www.riigiteataja.ee/akt/{meta['kehtivId']}"},
                     {"title": "Riigi Teataja: määrus nr 120, annex (ticket prices)",
                      "url": "https://www.riigiteataja.ee" + re.search(r"/aktilisa/[0-9/]+[^\"'#<>\s]*\.pdf", raw).group(0)},
                     {"title": "OpenStreetMap (Overpass API): ferry lines, ferry terminals and places on Estonia's west coast", "url": "https://www.openstreetmap.org/"}],
         "vehicles": "Trucks over 3.5 t", "min_kg": 3501,
         "tolled_roads": "The state ferry lines Virtsu–Kuivastu, Rohuküla–Heltermaa and Sõru–Triigi.",
         "closed_systems": systems, "rows": []}
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"ee-ferries-{start}.json")
    json.dump(t, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, len(systems), "systems;", "; ".join(notes))


if __name__ == "__main__":
    main(*sys.argv[1:])
