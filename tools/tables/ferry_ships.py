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
- TT-Line's freight timetable (browser/ttline-timetable.txt: the site
  refuses scripted requests, so its text was read in Chrome): the ship of
  each departure, by its initials, which the page names ("PP = Peter
  Pan"). Its ships join POLSCA's on Świnoujście–Trelleborg;
- Stena Line Freight's route pages (stena-routes-<route>.html, linked
  from its route list): each page's heading names the ports ("Gdynia –
  Karlskrona") and its "Vessels" section the ships;
- Finnlines' route pages (finnlines-schedules-<route>.html, linked from its
  freight schedules page): the heading and "Ferries on the route"; for a
  route whose page has no such section, its master schedule
  (finnlines-schedules-*master-schedule*.txt: "Travemünde – Helsinki ...
  Finnstar/ Finnmaid/ Finnlady 7/7"). A route with a call on the way
  (Kapellskär–Långnäs–Naantali) isn't built;
- one operator's ships join another's on the same two ports (TT-Line's and
  Stena Line's on Rostock–Trelleborg);
- OpenStreetMap (polsca-osm.json, dk-bornholm-osm.json, ttline-osm.json):
  the terminals, as polsca.py and dk_bornholm.py place them; TT-Line's
  Travemünde and Rostock at the far end of its lines from Trelleborg;
  Stena Line's and Finnlines' (ferry-ships-osm.json, ferry-ships-places.json)
  at the ends of the car ferry line whose name has both ports (the
  operator's, when it has one), each port at the end nearer a place of its
  name; a line trucks may take (hgv=yes) counts though cars may not. A
  route with no such line isn't built: no route can take it;
- Commission Implementing Decision (EU) 2023/2895, Annex I
  (ets-islands-2023-2895.html): Bornholm's port Rønne is under the island
  derogation (Directive 2003/87/EC, Art. 12(3-d)) for voyages to a port in
  Denmark until 31 December 2030;
- the EU MRV reports' ship lists (ferries/data/mrv-ships-<year>.json): a
  ship's IMO number, by its name (letters such as Å read as A), when one
  ship of that name is listed.

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
           "Travemünde": "DE", "Rostock": "DE",
           "Rønne": "DK", "Køge": "DK", "Sassnitz": "DE"}
# (id, ports): the crossings, by the ports' names in polsca.PORTS and dk_bornholm.PORTS.
POLSCA = [("swinoujscie-ystad", ("Świnoujście", "Ystad")), ("swinoujscie-trelleborg", ("Świnoujście", "Trelleborg")),
          ("gdansk-nynashamn", ("Gdańsk", "Nynäshamn")), ("gdansk-karlshamn", ("Gdańsk", "Karlshamn"))]
BORNHOLM = [("koge-ronne", ("Køge", "Rønne")), ("ystad-ronne", ("Ystad", "Rønne")), ("sassnitz-ronne", ("Sassnitz", "Rønne"))]
# TT-Line: (id, ports, the timetable's route); its ports on its own lines.
TTLINE = [("travemunde-trelleborg", ("Travemünde", "Trelleborg"), "Travemünde - Trelleborg"),
          ("rostock-trelleborg", ("Rostock", "Trelleborg"), "Rostock - Trelleborg"),
          ("swinoujscie-trelleborg", ("Świnoujście", "Trelleborg"), "Świnoujście - Trelleborg")]
TTLINE_PORTS = {"Trelleborg": ("place", "Trelleborg"), "Travemünde": ("end", "Travemünde (D) – Trelleborg (SE)", "Trelleborg"),
                "Rostock": ("end", "Rostock (D) - Trelleborg (SE)", "Trelleborg")}
TTLINE_FILE = os.path.join(HERE, "browser", "ttline-timetable.txt")
# The ports Stena Line's and Finnlines' pages name: country, and the names
# OpenStreetMap gives their places and lines.
PORTS = {"Belfast": ("GB", ["Belfast"]), "Cairnryan": ("GB", ["Cairnryan"]), "Heysham": ("GB", ["Heysham"]),
         "Liverpool": ("GB", ["Liverpool", "Birkenhead"]), "Dublin": ("IE", ["Dublin"]), "Holyhead": ("GB", ["Holyhead"]),
         "Gdynia": ("PL", ["Gdynia"]), "Karlskrona": ("SE", ["Karlskrona"]), "Gothenburg": ("SE", ["Göteborg", "Gothenburg"]),
         "Kiel": ("DE", ["Kiel"]), "Frederikshavn": ("DK", ["Frederikshavn"]),
         "Hoek van Holland": ("NL", ["Hoek van Holland", "Hook of Holland"]), "Harwich": ("GB", ["Harwich"]),
         "Immingham": ("GB", ["Immingham", "Killingholme"]), "Ventspils": ("LV", ["Ventspils"]), "Rosslare": ("IE", ["Rosslare"]),
         "Fishguard": ("GB", ["Fishguard"]), "Rotterdam": ("NL", ["Rotterdam", "Europoort", "Maasvlakte"]),
         "Liepāja": ("LV", ["Liepāja", "Liepaja"]), "Malmö": ("SE", ["Malmö"]), "Helsinki": ("FI", ["Helsinki"]),
         "Nynäshamn": ("SE", ["Nynäshamn"]), "Travemünde": ("DE", ["Travemünde"]), "Rostock": ("DE", ["Rostock"]),
         "Trelleborg": ("SE", ["Trelleborg"]), "Świnoujście": ("PL", ["Świnoujście"])}
# Other names the pages give a port.
PAGE_PORT = {"gothenburg masthugget": "Gothenburg", "hoek van holland": "Hoek van Holland"}
UPPER = "A-ZĄĆĘŁŃÓŚŹŻÅÄÖ"
SHIP = re.compile(rf"(?:^|\s{{2,}})([{UPPER}][^\W\d_]+(?: [{UPPER}][^\W\d_]+)*)\s{{2,}}(?=\d\d[.:]\d\d|-{{3,}}|stoppage)")


def ascii(s):
    return unicodedata.normalize("NFKD", s.replace("ø", "o").replace("Ø", "O")).encode("ascii", "ignore").decode().lower()


def imos():
    """{name: IMO number} of the names the MRV ship lists give one IMO number."""
    seen = {}
    for p in sorted(glob.glob(os.path.join(MRV, "mrv-ships-*.json"))):
        for s in json.load(open(p, encoding="utf-8"))["ships"]:
            seen.setdefault(ascii(s["name"]).upper(), set()).add(s["imo"])
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


def ttline(t):
    """({route: {ships}}, page URL, day read) from the capture of TT-Line's timetable."""
    legend = dict(re.findall(r"([A-Z]{2}) = ([A-Z][\w ]+?)(?=;|$)", next((l for l in t.splitlines() if " = " in l), ""), re.M))
    url = re.search(r"^# Page: (\S+)", t, re.M)
    day = re.search(r"read on (\d{4}-\d\d-\d\d)", t)
    if not legend or not url or not day:
        sys.exit("ferry ships: TT-Line's capture: the header not read")
    routes = {}
    for line in t.splitlines():
        m = re.search(r"\d{1,2}:\d\d ([A-Z]{2}) (\S+ - \S+) ", line)
        if m and not line.startswith("#"):
            if m.group(1) not in legend:
                sys.exit(f"ferry ships: TT-Line's capture: {m.group(1)} not named")
            routes.setdefault(m.group(2), set()).add(legend[m.group(1)].upper())
    return routes, url.group(1), day.group(1)


def port_of(name, where):
    k = ascii(name).strip()
    for p in PORTS:
        if ascii(p) == k:
            return p
    if k in PAGE_PORT:
        return PAGE_PORT[k]
    sys.exit(f"ferry ships: {where}: the port {name!r} isn't known (PORTS)")


def page_text(s):
    return html.unescape(re.sub(r"<[^>]+>", " ", s)).strip()


def stena(pages):
    """[(ports, {ships}, heading, file)] from Stena Line Freight's route pages."""
    out = []
    for path, t in pages:
        h1 = re.findall(r"<h1[^>]*>(.*?)</h1>", t, re.S)
        parts = re.split(r"\s+[–-]\s+", page_text(h1[0])) if h1 else []
        i = t.find('id="vessels"')
        ships = [page_text(x) for x in re.findall(r'<h3 class="heading">([^<]+)<', t[i:t.find("</section>", i)])] if i >= 0 else []
        if len(parts) != 2 or not ships:
            sys.exit(f"ferry ships: {os.path.basename(path)}: the route or its vessels not read")
        out.append((tuple(port_of(p, os.path.basename(path)) for p in parts), set(ships), page_text(h1[0]), path))
    return out


def finnlines(pages, schedule):
    """[(ports, {ships}, heading, file)] from Finnlines' route pages, and the
    master schedule for a page that doesn't name its ferries."""
    out = []
    for path, t in pages:
        h1 = re.findall(r"<h1[^>]*>(.*?)</h1>", t, re.S)
        parts = re.split(r"\s*[–-]\s*", page_text(h1[0])) if h1 else []
        name = os.path.basename(path)
        if len(parts) > 2:
            print(f"ferry ships: {name}: {page_text(h1[0])} calls on the way: not built")
            continue
        if len(parts) != 2:
            sys.exit(f"ferry ships: {name}: the route not read")
        ports = tuple(port_of(p, name) for p in parts)
        ships = set()
        i = t.find("Ferries on the route")
        if i >= 0:
            # The ferries' headings follow, up to the first that isn't a
            # ship's name ("Latest offers on the route").
            for h in re.findall(r"<h[2-4][^>]*>(.*?)</h[2-4]>", t[i:], re.S):
                names = re.split(r"\s*&\s*", page_text(h))
                if not all(re.fullmatch(r"[A-Z][\w-]*(?: [A-Z][\w-]*){0,2}", s) for s in names):
                    break
                ships.update(names)
        else:
            lines = schedule.splitlines()
            for k, line in enumerate(lines):
                m = re.fullmatch(r"\s*(\S[^–]*?)\s+–\s+(\S.*?)\s*", line)
                if m and {ascii(x) for x in m.groups()} == {ascii(p) for p in ports}:
                    for nxt in lines[k + 1:k + 10]:
                        f = re.search(r"([A-Z][a-z]+(?:\s*/\s*[A-Z][a-z]+)+)\s+\d/7", nxt)
                        if f:
                            ships = {s.strip() for s in f.group(1).split("/")}
                            break
                    break
        if not ships:
            sys.exit(f"ferry ships: {name}: no ferries named for {page_text(h1[0])}")
        out.append((ports, ships, page_text(h1[0]), path))
    return out


def osm_place(osm, a, b, operator):
    """{port: (lat, lon)}: the ends of the ferry line (for cars or trucks)
    whose name has both ports (the operator's, if one is), each port at the
    end nearer a place of its name; None when OpenStreetMap has no such
    line, or one that doesn't reach a port."""
    from ferry_osm import km
    car = {i for i, _ in lines_of(osm)[0]} | {w["id"] for w in osm.get("elements", []) if w.get("tags", {}).get("hgv") in ("yes", "designated")}
    has = lambda name, p: any(ascii(x) in ascii(name) for x in PORTS[p][1])
    ways = [w for w in osm.get("elements", []) if w["type"] == "way" and w["id"] in car and has(w.get("tags", {}).get("name", ""), a)
            and has(w.get("tags", {}).get("name", ""), b)]
    own = [w for w in ways if ascii(operator) in ascii(w.get("tags", {}).get("operator", ""))]
    ways = own or ways
    if not ways:
        print(f"ferry ships: {a}–{b}: OpenStreetMap has no ferry line named after both")
        return None
    ends = [(g["lat"], g["lon"]) for w in ways for g in (w["geometry"][0], w["geometry"][-1])]
    places = {p: [(e["lat"], e["lon"]) for e in osm["elements"] if e["type"] == "node" and e.get("tags", {}).get("place")
                  and ascii(e["tags"].get("name", "")) in {ascii(x) for x in PORTS[p][1]}] for p in (a, b)}
    pos = {}
    for p in (a, b):
        best = min(((km(e, q), e) for e in ends for q in places[p]), default=None)
        if not best or best[0] > 40:
            print(f"ferry ships: {a}–{b}: OpenStreetMap's line doesn't reach {p}")
            return None
        pos[p] = best[1]
    if km(pos[a], pos[b]) < 5:
        print(f"ferry ships: {a}–{b}: both ports at one end of OpenStreetMap's line")
        return None
    return pos


def crossing(cid, ports, pos, operator, ships, source, ids, exemptions=()):
    return {"id": cid, "name": "–".join(ports), "operator": operator,
            "terminals": [{"name": p, "lat": round(pos[p][0], 6), "lon": round(pos[p][1], 6), "country": COUNTRY[p]} for p in ports],
            "ships": [{**({"imo": ids[ascii(s).upper()]} if ascii(s).upper() in ids else {}), "name": s.upper()} for s in sorted(ships)],
            **({"exemptions": list(exemptions)} if exemptions else {}), "source": source}


def main(fetched, out):
    try:
        page = open(os.path.join(fetched, "polsca-timetables.html"), encoding="utf-8").read()
        tts = {p: open(p, encoding="utf-8").read() for p in sorted(glob.glob(os.path.join(fetched, "polsca-timetables-*.txt")))}
        bpage = open(os.path.join(fetched, "bornholm-ferries.html"), encoding="utf-8").read()
        posm = json.load(open(os.path.join(fetched, "polsca-osm.json"), encoding="utf-8"))
        bosm = json.load(open(os.path.join(fetched, "dk-bornholm-osm.json"), encoding="utf-8"))
        decision = text(os.path.join(fetched, "ets-islands-2023-2895.html"))
        tosm = json.load(open(os.path.join(fetched, "ttline-osm.json"), encoding="utf-8"))
        tcap = open(TTLINE_FILE, encoding="utf-8").read()
        spages = [(p, open(p, encoding="utf-8").read()) for p in sorted(glob.glob(os.path.join(fetched, "stena-routes-*.html")))]
        fpages = [(p, open(p, encoding="utf-8").read()) for p in sorted(glob.glob(os.path.join(fetched, "finnlines-schedules-*.html")))]
        fsched = "".join(open(p, encoding="utf-8").read() for p in sorted(glob.glob(os.path.join(fetched, "finnlines-schedules-*master-schedule*.txt"))))
        gosm = json.load(open(os.path.join(fetched, "ferry-ships-osm.json"), encoding="utf-8"))
        gosm["elements"] += json.load(open(os.path.join(fetched, "ferry-ships-places.json"), encoding="utf-8"))["elements"]
        urls = {f["file"]: f["url"] for f in json.load(open(os.path.join(fetched, "manifest.json")))["files"]}
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

    # TT-Line
    troutes, turl, tday = ttline(tcap)
    lines, _ = lines_of(tosm)
    pos = port_places(tosm, lines, TTLINE_PORTS)
    have = {c["id"]: c for c in crossings}
    title = f"TT-Line: freight timetable, the ship of each departure (read in Chrome on {tday}, tools/tables/browser/ttline-timetable.txt)"
    for cid, ports, route in TTLINE:
        ships = troutes.get(route)
        if not ships:
            sys.exit(f"ferry ships: TT-Line's capture has no {route}")
        if cid in have:
            c = have[cid]
            c["operator"] += "; TT-Line"
            c["ships"] = crossing(cid, ports, {p: (0, 0) for p in ports}, "", {s["name"] for s in c["ships"]} | ships, None, ids)["ships"]
            c["source"]["title"] += f"; {title}"
            continue
        if any(p not in pos for p in ports):
            sys.exit(f"ferry ships: {'–'.join(ports)}: ports not placed")
        crossings.append(crossing(cid, ports, pos, "TT-Line", ships, {"title": title, "url": turl}, ids))

    # Stena Line and Finnlines
    if not spages or not fpages:
        sys.exit(f"ferry ships: {len(spages)} Stena Line and {len(fpages)} Finnlines route pages")
    have = {frozenset(t["name"] for t in c["terminals"]): c for c in crossings}
    for operator, routes in (("Stena Line", stena(spages)), ("Finnlines", finnlines(fpages, fsched))):
        for ports, ships, heading, path in routes:
            url = urls.get(os.path.basename(path), "")
            title = f"{operator}: {heading}, its ferries"
            c = have.get(frozenset(ports))
            if c:
                c["operator"] += f"; {operator}"
                c["ships"] = crossing(c["id"], ports, {p: (0, 0) for p in ports}, "", {s["name"] for s in c["ships"]} | {s.upper() for s in ships}, None, ids)["ships"]
                c["source"]["title"] += f"; {title} ({url})"
                continue
            pos = osm_place(gosm, *ports, operator)
            if not pos:
                print(f"ferry ships: {'–'.join(ports)}: not built (no OpenStreetMap line between its ports)")
                continue
            COUNTRY.update({p: PORTS[p][0] for p in ports})
            cid = "-".join(re.sub(r"[^a-z0-9]+", "-", ascii(p)).strip("-") for p in ports)
            c = crossing(cid, ports, pos, operator, ships, {"title": title, "url": url}, ids)
            crossings.append(c)
            have[frozenset(ports)] = c

    crossings.sort(key=lambda c: c["id"])
    os.makedirs(out, exist_ok=True)
    doc = {"note": "Ferry crossings with the ships their operators' timetables and pages name, built by tools/tables/ferry_ships.py; "
                   "IMO numbers from the EU MRV reports' ship lists.", "crossings": crossings}
    path = os.path.join(out, "crossings-ships.json")
    json.dump(doc, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, len(crossings), "crossings")


if __name__ == "__main__":
    main(*sys.argv[1:])
