"""Builds the ferry crossings whose ships carbon-cost reads from the
operators' own documents (crossings-ships.json, for ferries/data), from

- POLSCA Baltic Ferries' timetables (Polferries and Unity Line, on
  unityline.eu; polsca-timetables.html and the PDFs it links,
  polsca-timetables-*.txt): each timetable has a column for each of its
  two ports ("ŚWINOUJŚCIE   YSTAD") and names the ferry of every
  departure; a ship with a departure in any of the listed timetables
  sails the crossing. A ship the page says is out of service
  ("the departures of the ferry Galileusz from 6.11.2026 until further
  notice have been cancelled") is left out;
- Bornholmslinjen's ferries page (bornholm-ferries.html): each ferry's
  crossing times ("Rønne - Køge", "Rønne-Ystad") and description ("på
  ruten mellem Rønne og Ystad") name its routes;
- OpenStreetMap (polsca-osm.json, dk-bornholm-osm.json): the terminals,
  as polsca.py and dk_bornholm.py place them;
- Commission Implementing Decision (EU) 2023/2895, Annex I
  (ets-islands-2023-2895.html): Bornholm's port Rønne is under the island
  derogation (Directive 2003/87/EC, Art. 12(3-d)) for voyages to a port in
  Denmark until 31 December 2030;
- the EU MRV reports' ship lists (ferries/data/mrv-ships-<year>.json): a
  ship's IMO number, by its name, when one ship of that name is listed.

Usage: python3 ferry_ships.py <fetched dir> <out dir>
"""
import glob, html, json, os, re, sys, unicodedata

import dk_bornholm
import polsca
from ets_islands import DECISION, FROM, UNTIL, text
from ferry_osm import lines_of, port_places

HERE = os.path.dirname(os.path.abspath(__file__))
MRV = os.path.join(HERE, "..", "..", "ferries", "data")
COUNTRY = {"Świnoujście": "PL", "Gdańsk": "PL", "Ystad": "SE", "Trelleborg": "SE", "Nynäshamn": "SE", "Karlshamn": "SE",
           "Rønne": "DK", "Køge": "DK", "Sassnitz": "DE"}
# (id, ports): the crossings, by the ports' names in polsca.PORTS and dk_bornholm.PORTS.
POLSCA = [("swinoujscie-ystad", ("Świnoujście", "Ystad")), ("swinoujscie-trelleborg", ("Świnoujście", "Trelleborg")),
          ("gdansk-nynashamn", ("Gdańsk", "Nynäshamn")), ("gdansk-karlshamn", ("Gdańsk", "Karlshamn"))]
BORNHOLM = [("koge-ronne", ("Køge", "Rønne")), ("ystad-ronne", ("Ystad", "Rønne")), ("sassnitz-ronne", ("Sassnitz", "Rønne"))]
UPPER = "A-ZĄĆĘŁŃÓŚŹŻÅÄÖ"
SHIP = re.compile(rf"(?:^|\s{{2,}})([{UPPER}][^\W\d_]+(?: [{UPPER}][^\W\d_]+)*)\s{{2,}}(?=\d\d[.:]\d\d|-{{3,}}|stoppage)")


def ascii(s):
    return unicodedata.normalize("NFKD", s.replace("ø", "o").replace("Ø", "O")).encode("ascii", "ignore").decode().lower()


def imos():
    """{name: IMO number} of the names the MRV ship lists give one IMO number."""
    seen = {}
    for p in sorted(glob.glob(os.path.join(MRV, "mrv-ships-*.json"))):
        for s in json.load(open(p, encoding="utf-8"))["ships"]:
            seen.setdefault(s["name"], set()).add(s["imo"])
    return {n: next(iter(i)) for n, i in seen.items() if len(i) == 1}


def timetable(t, path):
    """(ports, {ships}) of a POLSCA timetable, weekly or by date (the
    Christmas ones): the ports are the first line naming two in capitals
    ("ŚWINOUJŚCIE   YSTAD", "DATE / DATA FERRY / PROM ŚWINOUJŚCIE   YSTAD");
    a ship is a name followed by a time or "-------" with a time on its
    line ("Polonia   06.30   10.30 ...", "JANTAR UNITY   05.00 - 09.45 ...")."""
    names = {ascii(p).upper(): p for p in COUNTRY}
    ports = None
    for line in t.splitlines():
        found = [names[ascii(w).upper()] for w in re.findall(r"[^\W\d_]{3,}", line) if w == w.upper() and ascii(w).upper() in names]
        if len(found) == 2 and found[0] != found[1]:
            ports = tuple(found)
            break
    if not ports:
        sys.exit(f"ferry ships: {path}: the ports' columns not read")
    ships = set()
    for line in t.splitlines():
        for m in SHIP.finditer(line):
            if re.search(r"\d\d[.:]\d\d", line[m.end():]):
                ships.add(m.group(1).upper())
    if not ships:
        sys.exit(f"ferry ships: {path}: no ships read")
    return ports, ships


def nuxt(page):
    """The page's Nuxt data: its flat array of values."""
    m = re.search(r'<script[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>', page, re.S)
    if not m:
        sys.exit("ferry ships: Bornholmslinjen's page has no Nuxt data")
    return json.loads(m.group(1))


def bornholm(page):
    """{ferry: {ports}} from Bornholmslinjen's ferries page."""
    a = nuxt(page)
    port = r"(Ystad|Køge|Sassnitz)"
    routes = {}

    def strings(i, depth=0):
        v = a[i] if isinstance(i, int) and 0 <= i < len(a) else None
        if depth > 6 or v is None:
            return
        if isinstance(v, str):
            yield v
        elif isinstance(v, list):
            for x in v:
                yield from strings(x, depth + 1)
        elif isinstance(v, dict):
            for x in v.values():
                yield from strings(x, depth + 1)

    for v in a:
        if not isinstance(v, dict):
            continue
        if "ferrySpecifications" in v and "erpId" in v:
            name = a[v["name"]]
            for s in strings(v["ferrySpecifications"]):
                m = re.fullmatch(rf"Rønne ?[-–] ?{port}", s.strip())
                if m:
                    routes.setdefault(name, set()).add(m.group(1))
        if "ferry" in v and "description" in v:
            ferry = [x for x in strings(v["ferry"]) if x in {a[w["name"]] for w in a if isinstance(w, dict) and "erpId" in w}]
            for s in strings(v["description"]):
                for m in re.finditer(rf"Rønne ?- ?{port}|Rønne og {port}", html.unescape(re.sub(r"<[^>]+>", " ", s))):
                    for f in ferry[:1]:
                        routes.setdefault(f, set()).add(m.group(1) or m.group(2))
    return routes


def crossing(cid, ports, pos, operator, ships, source, ids, exemptions=()):
    return {"id": cid, "name": "–".join(ports), "operator": operator,
            "terminals": [{"name": p, "lat": round(pos[p][0], 6), "lon": round(pos[p][1], 6), "country": COUNTRY[p]} for p in ports],
            "ships": [{**({"imo": ids[s.upper()]} if s.upper() in ids else {}), "name": s.upper()} for s in sorted(ships)],
            **({"exemptions": list(exemptions)} if exemptions else {}), "source": source}


def main(fetched, out):
    try:
        page = open(os.path.join(fetched, "polsca-timetables.html"), encoding="utf-8").read()
        tts = {p: open(p, encoding="utf-8").read() for p in sorted(glob.glob(os.path.join(fetched, "polsca-timetables-*.txt")))}
        bpage = open(os.path.join(fetched, "bornholm-ferries.html"), encoding="utf-8").read()
        posm = json.load(open(os.path.join(fetched, "polsca-osm.json"), encoding="utf-8"))
        bosm = json.load(open(os.path.join(fetched, "dk-bornholm-osm.json"), encoding="utf-8"))
        decision = text(os.path.join(fetched, "ets-islands-2023-2895.html"))
    except (OSError, ValueError) as e:
        print(f"ferry ships: not built ({e})")
        return
    if not tts:
        sys.exit("ferry ships: no POLSCA timetables")
    src = {s["id"]: s for s in json.load(open(os.path.join(HERE, "sources.json"), encoding="utf-8"))["sources"]}
    ids = imos()
    crossings = []

    # POLSCA
    flat = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page)))
    out_of_service = {m.group(1): m.group(2) for m in re.finditer(r"departures of the ferry (\w[\w ]*?) from (\d{1,2}\.\d{1,2}\.\d{4}) until further notice have been cancelled", flat)}
    by_route = {}
    for p, t in tts.items():
        ports, ships = timetable(t, os.path.basename(p))
        by_route.setdefault(frozenset(ports), set()).update(ships)
    lines, _ = lines_of(posm)
    pos = port_places(posm, lines, polsca.PORTS)
    for cid, ports in POLSCA:
        ships = by_route.get(frozenset(ports), set()) - {s.upper() for s in out_of_service}
        if not ships:
            sys.exit(f"ferry ships: no POLSCA timetable for {'–'.join(ports)}")
        if any(p not in pos for p in ports):
            sys.exit(f"ferry ships: {'–'.join(ports)}: ports not placed")
        gone = "".join(f"; {s} left out, its departures cancelled from {d} until further notice" for s, d in sorted(out_of_service.items())
                       if s.upper() in by_route.get(frozenset(ports), set()))
        crossings.append(crossing(cid, ports, pos, "POLSCA Baltic Ferries (Polferries, Unity Line)", ships,
                                  {"title": f"POLSCA Baltic Ferries: timetables (the ferry of each departure){gone}", "url": src["polsca-timetables"]["url"]}, ids))

    # Bornholmslinjen
    dk = decision[decision.find(" DENMARK "):decision.find(" GREECE ")]
    if "List of islands and ports as referred to in Article 12(3-d)" not in decision or "BORNHOLM ROENNE" not in dk:
        sys.exit("ferry ships: the Decision doesn't list Bornholm, Rønne")
    routes = bornholm(bpage)
    lines, _ = lines_of(bosm)
    pos = port_places(bosm, lines, dk_bornholm.PORTS)
    for cid, ports in BORNHOLM:
        ships = {f for f, r in routes.items() if ports[0] in r}
        if not ships:
            sys.exit(f"ferry ships: Bornholmslinjen names no ferry on {'–'.join(ports)}")
        if any(p not in pos for p in ports):
            sys.exit(f"ferry ships: {'–'.join(ports)}: ports not placed")
        ex = [{"from": FROM, "until": UNTIL, "law": f"{DECISION[0]} (Denmark: Bornholm, Rønne)", "url": DECISION[1]}] if {COUNTRY[p] for p in ports} == {"DK"} else []
        crossings.append(crossing(cid, ports, pos, "Bornholmslinjen", ships,
                                  {"title": "Bornholmslinjen: the ferries (each one's crossings)", "url": src["bornholm-ferries"]["url"]}, ids, ex))

    crossings.sort(key=lambda c: c["id"])
    os.makedirs(out, exist_ok=True)
    doc = {"note": "Ferry crossings with the ships their operators' timetables and pages name, built by tools/tables/ferry_ships.py; "
                   "IMO numbers from the EU MRV reports' ship lists.", "crossings": crossings}
    path = os.path.join(out, "crossings-ships.json")
    json.dump(doc, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, len(crossings), "crossings")


if __name__ == "__main__":
    main(*sys.argv[1:])
