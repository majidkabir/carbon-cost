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
- Irish Ferries Freight's route pages (irishferries-routes-<route>.html,
  linked from its home page): the ports in the page's address, the ships
  and their IMO numbers in its vessel specifications;
- P&O Freight's route pages (po-routes-<route>-freight.html, linked from
  its routes page): the ports in the page's address, the ships in its "Our
  Fleet" section (IMO numbers where it gives them); when its sailing tables
  name ships ("13:40 Pioneer"), only those;
- one operator's ships join another's on the same two ports (TT-Line's and
  Stena Line's on Rostock–Trelleborg);
- OpenStreetMap (polsca-osm.json, dk-bornholm-osm.json, ttline-osm.json):
  the terminals, as polsca.py and dk_bornholm.py place them; TT-Line's
  Travemünde and Rostock at the far end of its lines from Trelleborg;
  Stena Line's and Finnlines' (ferry-ships-osm.json, -osm-2.json) at the
  ends of the ferry line whose name has both ports (the operator's, when it
  has one), each port at the end nearest its town (PORTS); a line trucks may take (hgv=yes) counts though cars may not. A
  route with no such line isn't built: no route can take it;
- Commission Implementing Decision (EU) 2023/2895, Annex I
  (ets-islands-2023-2895.html): Bornholm's port Rønne is under the island
  derogation (Directive 2003/87/EC, Art. 12(3-d)) for voyages to a port in
  Denmark until 31 December 2030;
- the EU MRV reports' ship lists (ferries/data/mrv-ships-<year>.json): a
  ship's IMO number, by its name (letters such as Å read as A), when one
  ship of that name is listed.

- for ports outside the EU and the EEA (the UK, the Isle of Man, the
  Channel Islands, the Faroes; Morocco, Algeria, Tunisia, Albania,
  Montenegro and Turkey), the OpenStreetMap ferry lines between one of
  them and a port in PORTS: the ships aren't named, but the ports'
  countries give the share of the EU ETS (Directive 2003/87/EC, Art.
  3ga(1)): 50% with a port in the EU or the EEA, none between two outside.

Usage: python3 ferry_ships.py <fetched dir> <out dir>
       python3 ferry_ships.py --osm-query   (the Overpass queries for sources.json)
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
# The ports: country, the names OpenStreetMap's lines give them, and where
# the town is (lat, lon, to tell a line's ends apart: the end nearest it,
# within 40 km).
PORTS = {
    # Stena Line's and Finnlines' routes
    "Belfast": ("GB", ["Belfast"], (54.60, -5.93)), "Cairnryan": ("GB", ["Cairnryan"], (54.97, -5.02)),
    "Heysham": ("GB", ["Heysham"], (54.03, -2.91)), "Liverpool": ("GB", ["Liverpool", "Birkenhead"], (53.41, -3.00)),
    "Dublin": ("IE", ["Dublin"], (53.35, -6.26)), "Holyhead": ("GB", ["Holyhead"], (53.31, -4.63)),
    "Gdynia": ("PL", ["Gdynia"], (54.52, 18.53)), "Karlskrona": ("SE", ["Karlskrona"], (56.16, 15.59)),
    "Gothenburg": ("SE", ["Göteborg", "Gothenburg"], (57.71, 11.97)), "Kiel": ("DE", ["Kiel"], (54.32, 10.13)),
    "Frederikshavn": ("DK", ["Frederikshavn"], (57.44, 10.54)),
    "Hoek van Holland": ("NL", ["Hoek van Holland", "Hook of Holland"], (51.98, 4.13)), "Harwich": ("GB", ["Harwich"], (51.94, 1.28)),
    "Immingham": ("GB", ["Immingham", "Killingholme"], (53.62, -0.22)), "Ventspils": ("LV", ["Ventspils"], (57.39, 21.56)),
    "Rosslare": ("IE", ["Rosslare"], (52.25, -6.34)), "Fishguard": ("GB", ["Fishguard"], (51.99, -4.98)),
    "Rotterdam": ("NL", ["Rotterdam", "Europoort", "Maasvlakte", "Vlaardingen"], (51.92, 4.30)),
    "Liepāja": ("LV", ["Liepāja", "Liepaja"], (56.51, 21.01)), "Malmö": ("SE", ["Malmö"], (55.60, 13.00)),
    "Helsinki": ("FI", ["Helsinki"], (60.17, 24.94)), "Nynäshamn": ("SE", ["Nynäshamn"], (58.90, 17.95)),
    "Travemünde": ("DE", ["Travemünde"], (53.96, 10.87)), "Rostock": ("DE", ["Rostock"], (54.09, 12.13)),
    "Trelleborg": ("SE", ["Trelleborg"], (55.38, 13.16)), "Świnoujście": ("PL", ["Świnoujście"], (53.91, 14.25)),
    # ports outside the EU and the EEA, and the ports across from them
    "Dover": ("GB", ["Dover", "Douvres"], (51.12, 1.33)), "Newhaven": ("GB", ["Newhaven"], (50.79, 0.05)),
    "Portsmouth": ("GB", ["Portsmouth"], (50.81, -1.09)), "Poole": ("GB", ["Poole"], (50.71, -1.98)),
    "Plymouth": ("GB", ["Plymouth"], (50.37, -4.14)), "Hull": ("GB", ["Hull", "Kingston upon Hull"], (53.74, -0.33)),
    "Newcastle": ("GB", ["Newcastle", "North Shields"], (55.00, -1.50)), "Tilbury": ("GB", ["Tilbury"], (51.46, 0.36)),
    "Purfleet": ("GB", ["Purfleet"], (51.48, 0.24)), "Teesport": ("GB", ["Teesport", "Middlesbrough"], (54.60, -1.16)),
    "Felixstowe": ("GB", ["Felixstowe"], (51.96, 1.33)), "Pembroke": ("GB", ["Pembroke", "Pembroke Dock"], (51.69, -4.94)),
    "Larne": ("GB", ["Larne"], (54.85, -5.82)), "Aberdeen": ("GB", ["Aberdeen"], (57.14, -2.09)),
    "Lerwick": ("GB", ["Lerwick"], (60.15, -1.14)), "Kirkwall": ("GB", ["Kirkwall"], (58.98, -2.96)),
    "Douglas": ("IM", ["Douglas"], (54.15, -4.48)), "St Helier": ("JE", ["St Helier", "Saint Helier"], (49.18, -2.11)),
    "St Peter Port": ("GG", ["St Peter Port", "Saint Peter Port"], (49.46, -2.53)),
    "Tórshavn": ("FO", ["Tórshavn", "Torshavn"], (62.01, -6.77)), "Cork": ("IE", ["Cork", "Ringaskiddy"], (51.83, -8.32)),
    "Calais": ("FR", ["Calais"], (50.96, 1.86)), "Dunkerque": ("FR", ["Dunkerque", "Dunkirk", "Loon-Plage"], (51.03, 2.30)),
    "Dieppe": ("FR", ["Dieppe"], (49.93, 1.08)), "Le Havre": ("FR", ["Le Havre"], (49.49, 0.11)),
    "Caen": ("FR", ["Ouistreham", "Caen"], (49.28, -0.25)), "Cherbourg": ("FR", ["Cherbourg", "Cherbourg-en-Cotentin"], (49.64, -1.62)),
    "Saint-Malo": ("FR", ["Saint-Malo", "St Malo", "St-Malo"], (48.65, -2.01)), "Roscoff": ("FR", ["Roscoff"], (48.72, -3.97)),
    "IJmuiden": ("NL", ["IJmuiden", "Amsterdam"], (52.46, 4.61)), "Zeebrugge": ("BE", ["Zeebrugge"], (51.33, 3.20)),
    "Santander": ("ES", ["Santander"], (43.46, -3.80)), "Bilbao": ("ES", ["Bilbao", "Santurtzi"], (43.35, -3.04)),
    "Esbjerg": ("DK", ["Esbjerg"], (55.47, 8.44)), "Hirtshals": ("DK", ["Hirtshals"], (57.59, 9.96)),
    "Seyðisfjörður": ("IS", ["Seyðisfjörður", "Seydisfjordur"], (65.26, -14.01)),
    # the Mediterranean: Morocco, Algeria, Tunisia, Albania, Montenegro and
    # Turkey, and the EU ports across from them
    "Tanger Med": ("MA", ["Tanger Med", "Tanger-Med", "Tangier Med", "Ksar Sghir"], (35.89, -5.50)),
    "Tanger": ("MA", ["Tanger", "Tangier", "Tánger", "Tangeri", "Tanger Ville"], (35.78, -5.81)),
    "Nador": ("MA", ["Nador", "Beni Ansar", "Beni Enzar"], (35.20, -2.93)), "Al Hoceima": ("MA", ["Al Hoceima"], (35.25, -3.93)),
    "Alger": ("DZ", ["Alger", "Algiers", "Algeri"], (36.77, 3.06)), "Oran": ("DZ", ["Oran"], (35.70, -0.64)),
    "Béjaïa": ("DZ", ["Béjaïa", "Bejaia"], (36.75, 5.08)), "Skikda": ("DZ", ["Skikda"], (36.88, 6.91)),
    "Annaba": ("DZ", ["Annaba"], (36.90, 7.76)), "Mostaganem": ("DZ", ["Mostaganem"], (35.93, 0.09)),
    "Ghazaouet": ("DZ", ["Ghazaouet"], (35.10, -1.86)),
    "Tunis": ("TN", ["Tunis", "Tunisi", "La Goulette", "Halq al Wadi"], (36.81, 10.25)), "Zarzis": ("TN", ["Zarzis"], (33.50, 11.11)),
    "Durrës": ("AL", ["Durrës", "Durres", "Durazzo"], (41.31, 19.45)), "Vlorë": ("AL", ["Vlorë", "Vlora", "Valona"], (40.47, 19.49)),
    "Bar": ("ME", ["Bar"], (42.10, 19.09)),
    "Çeşme": ("TR", ["Çeşme", "Cesme"], (38.32, 26.30)), "Ayvalık": ("TR", ["Ayvalık", "Ayvalik"], (39.32, 26.69)),
    "Pendik": ("TR", ["Pendik"], (40.87, 29.25)), "Ambarlı": ("TR", ["Ambarlı", "Ambarli"], (40.97, 28.69)),
    "Mersin": ("TR", ["Mersin"], (36.80, 34.63)),
    "Algeciras": ("ES", ["Algeciras"], (36.13, -5.44)), "Tarifa": ("ES", ["Tarifa"], (36.01, -5.60)),
    "Almería": ("ES", ["Almería", "Almeria"], (36.83, -2.46)), "Motril": ("ES", ["Motril"], (36.72, -3.52)),
    "Málaga": ("ES", ["Málaga", "Malaga"], (36.72, -4.42)), "Barcelona": ("ES", ["Barcelona"], (41.38, 2.17)),
    "Valencia": ("ES", ["Valencia", "València"], (39.45, -0.33)), "Alicante": ("ES", ["Alicante", "Alacant"], (38.34, -0.48)),
    "Sète": ("FR", ["Sète", "Sete"], (43.40, 3.70)), "Marseille": ("FR", ["Marseille", "Marsiglia"], (43.30, 5.37)),
    "Toulon": ("FR", ["Toulon"], (43.12, 5.93)),
    "Genova": ("IT", ["Genova", "Genoa", "Gênes"], (44.41, 8.92)), "Civitavecchia": ("IT", ["Civitavecchia"], (42.09, 11.79)),
    "Salerno": ("IT", ["Salerno"], (40.68, 14.76)), "Palermo": ("IT", ["Palermo"], (38.12, 13.36)),
    "Trapani": ("IT", ["Trapani"], (38.02, 12.51)), "Bari": ("IT", ["Bari"], (41.12, 16.87)),
    "Ancona": ("IT", ["Ancona"], (43.62, 13.51)), "Brindisi": ("IT", ["Brindisi"], (40.64, 17.94)),
    "Trieste": ("IT", ["Trieste"], (45.65, 13.77)), "Igoumenitsa": ("GR", ["Igoumenitsa", "Ηγουμενίτσα"], (39.50, 20.26)),
    "Patras": ("GR", ["Patras", "Patra", "Πάτρα"], (38.25, 21.73)), "Lavrio": ("GR", ["Lavrio", "Λαύριο"], (37.71, 24.06)),
    "Chios": ("GR", ["Chios", "Χίος"], (38.37, 26.14)), "Mytilene": ("GR", ["Mytilene", "Lesvos", "Μυτιλήνη"], (39.10, 26.55)),
}
# The UK nation of the UK ports where the UK ETS's rules differ: Northern
# Ireland (50% to and from Great Britain) and Scotland (its ferry services
# between points in Scotland are outside).
REGION = {"Belfast": "GB-NIR", "Larne": "GB-NIR", "Cairnryan": "GB-SCT", "Aberdeen": "GB-SCT", "Kirkwall": "GB-SCT",
          "Lerwick": "GB-SCT"}
# Other names the pages give a port.
PAGE_PORT = {"gothenburg masthugget": "Gothenburg", "hoek van holland": "Hoek van Holland", "europoort": "Rotterdam"}
# The EU and the EEA EFTA states (ferries.go's eea).
EEA = {"AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL",
       "PL", "PT", "RO", "SK", "SI", "ES", "SE", "IS", "LI", "NO"}
UPPER = "A-ZĄĆĘŁŃÓŚŹŻÅÄÖ"
SHIP = re.compile(rf"(?:^|\s{{2,}})([{UPPER}][^\W\d_]+(?: [{UPPER}][^\W\d_]+)*)\s{{2,}}(?=\d\d[.:]\d\d|-{{3,}}|stoppage)")


def ascii(s):
    return unicodedata.normalize("NFKD", s.replace("ø", "o").replace("Ø", "O").replace("ı", "i")).encode("ascii", "ignore").decode().lower()


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


def fold(s):
    """Lower case without accents, other scripts kept (Πάτρα: πατρα)."""
    s = unicodedata.normalize("NFKD", s.replace("ø", "o").replace("Ø", "O").replace("ı", "i"))
    return "".join(ch for ch in s if not unicodedata.combining(ch)).lower()


def spans(name, p):
    """Where the port's names stand in a line's name, as words."""
    return [m.span() for x in PORTS[p][1] for m in re.finditer(rf"(?<!\w){re.escape(fold(x))}(?!\w)", fold(name))]


def named(name, p):
    """Whether a line's name has one of the port's names (as a word)."""
    return bool(spans(name, p))


def named_ports(name):
    """The ports a line's name has; a name inside another port's longer
    name (Tanger in Tanger Med) doesn't count."""
    found = {p: spans(name, p) for p in PORTS}
    found = {p: s for p, s in found.items() if s}
    return [p for p, ss in found.items() if not all(any(q != p and a <= x and y <= b and (b - a) > (y - x)
                                                        for q, qs in found.items() for a, b in qs) for x, y in ss)]


def irishferries(pages):
    """[(ports, {ship: IMO number}, heading, file)] from Irish Ferries
    Freight's route pages: the ports from the page's address
    (route-information/dover-calais/), the ships and their IMO numbers from
    its vessel specifications ("ISLE OF INISHMORE Vessel IMO 9142605")."""
    out = []
    for path, t in pages:
        name = os.path.basename(path)
        slug = re.sub(r"^irishferries-routes-|\.html$", "", name)
        parts = slug.split("-")
        flat = re.sub(r"\s+", " ", page_text(t))
        i = flat.find("Vessel Specification")
        ships = dict(re.findall(r"([A-Z][A-Z.' ]+?) Vess(?:el|le) IMO (\d{7})", flat[i:])) if i >= 0 else {}
        if len(parts) != 2 or not ships:
            sys.exit(f"ferry ships: {name}: the route or its vessels not read")
        ports = tuple(port_of(p, name) for p in parts)
        out.append((ports, {s.strip(): imo for s, imo in ships.items()}, "–".join(ports), path))
    return out


def poferries(pages):
    """[(ports, {ship: IMO number or None}, heading, file)] from P&O Freight's
    route pages: the ports from the page's address (route/dover-calais-freight),
    the ships from its "Our Fleet" section, with the IMO numbers it gives
    ("IMO Number - 9244116"). When the page's sailing tables name ships
    ("13:40 Pioneer"), only those: the section also names ships no longer on
    the route."""
    out = []
    for path, t in pages:
        name = os.path.basename(path)
        parts = re.sub(r"^po-routes-|-freight\.html$", "", name).split("-")
        i = t.find('id="accordionFerries"')
        fleet = {}
        for card in re.split(r"(?=<button[^>]*data-target=\"#collapse-)", t[i:])[1:] if i >= 0 else []:
            names = [x.strip() for x in re.split(r"\s+(?:and|&)\s+", page_text(card[card.find(">") + 1:card.find("</button>")])) if x.strip()]
            imo = re.search(r"IMO (?:Number|number)\s*-\s*(\d{7})", page_text(card).replace("\xa0", " "))
            fleet.update({n: imo.group(1) if imo and len(names) == 1 else None for n in names})
        tables = " ".join(page_text(x) for x in re.findall(r"<table\b.*?</table>", t, re.S)).replace("\xa0", " ")
        short = lambda n: re.sub(r"^P&O\s+", "", n)
        sailing = {n: imo for n, imo in fleet.items() if re.search(rf"(?<!\w){re.escape(fold(short(n)))}(?!\w)", fold(tables))}
        if len(parts) != 2 or not fleet:
            sys.exit(f"ferry ships: {name}: the route or its fleet not read")
        ports = tuple(port_of(p, name) for p in parts)
        heading = "–".join(ports) + (", its ferries in its sailing tables" if sailing else "")
        if "Space Charter" in tables:
            heading += " (its Space Charter sailings' ships not named)"
        out.append((ports, sailing or fleet, heading, path))
    return out


def osm_query():
    """The Overpass queries of ferry-ships-osm (lines named after a port,
    crossing the North Sea, the Channel or the Baltic: a line to a port
    further off, Santander or Tórshavn, passes through it) and -osm-2 (the
    Mediterranean), as sources.json has them."""
    import urllib.parse
    names = "|".join(sorted({x for _, xs, _ in PORTS.values() for x in xs}))
    lines = ['[out:json][timeout:300];way["route"="ferry"]["name"~"' + names + f'"]{bbox};out geom tags;'
             for bbox in ("(49.0,-11.0,61.0,26.0)", "(30.0,-10.0,46.5,36.0)")]
    return ["https://overpass-api.de/api/interpreter?data=" + urllib.parse.quote(q, safe="") for q in lines]


def osm_place(osm, a, b, operator):
    """{port: (lat, lon)}: the ends of the ferry line (for cars or trucks)
    whose name has both ports (the operator's, if one is), each port at the
    end nearest its town (PORTS); None when OpenStreetMap has no such line,
    or one that doesn't come within 40 km of a port's town."""
    from ferry_osm import km
    car = {i for i, _ in lines_of(osm)[0]} | {w["id"] for w in osm.get("elements", []) if w.get("tags", {}).get("hgv") in ("yes", "designated")}
    has = lambda name, p: named(name, p)
    ways = [w for w in osm.get("elements", []) if w["type"] == "way" and w["id"] in car and has(w.get("tags", {}).get("name", ""), a)
            and has(w.get("tags", {}).get("name", ""), b)]
    own = [w for w in ways if ascii(operator) in ascii(w.get("tags", {}).get("operator", ""))]
    ways = own or ways
    if not ways:
        print(f"ferry ships: {a}–{b}: OpenStreetMap has no ferry line named after both")
        return None
    ends = [(g["lat"], g["lon"]) for w in ways for g in (w["geometry"][0], w["geometry"][-1])]
    pos = {}
    for p in (a, b):
        best = min((km(e, PORTS[p][2]), e) for e in ends)
        if best[0] > 40:
            print(f"ferry ships: {a}–{b}: OpenStreetMap's line doesn't reach {p}")
            return None
        pos[p] = best[1]
    if km(pos[a], pos[b]) < 5:
        print(f"ferry ships: {a}–{b}: both ports at one end of OpenStreetMap's line")
        return None
    return pos


def crossing(cid, ports, pos, operator, ships, source, ids, exemptions=()):
    return {"id": cid, "name": "–".join(ports), "operator": operator,
            "terminals": [{"name": p, "lat": round(pos[p][0], 6), "lon": round(pos[p][1], 6), "country": COUNTRY[p],
                           **({"region": REGION[p]} if p in REGION else {})} for p in ports],
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
        ipages = [(p, open(p, encoding="utf-8").read()) for p in sorted(glob.glob(os.path.join(fetched, "irishferries-routes-*.html")))]
        ppages = [(p, open(p, encoding="utf-8").read()) for p in sorted(glob.glob(os.path.join(fetched, "po-routes-*.html")))]
        fsched = "".join(open(p, encoding="utf-8").read() for p in sorted(glob.glob(os.path.join(fetched, "finnlines-schedules-*master-schedule*.txt"))))
        gosm = {"elements": []}
        for p in ("ferry-ships-osm.json", "ferry-ships-osm-2.json"):
            gosm["elements"] += json.load(open(os.path.join(fetched, p), encoding="utf-8"))["elements"]
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
    if not spages or not fpages or not ipages or not ppages:
        sys.exit(f"ferry ships: {len(spages)} Stena Line, {len(fpages)} Finnlines, {len(ipages)} Irish Ferries and {len(ppages)} P&O Freight route pages")
    have = {frozenset(t["name"] for t in c["terminals"]): c for c in crossings}
    for operator, routes in (("Stena Line", stena(spages)), ("Finnlines", finnlines(fpages, fsched)), ("Irish Ferries", irishferries(ipages)),
                             ("P&O Ferries", poferries(ppages))):
        for ports, ships, heading, path in routes:
            if isinstance(ships, dict):
                # the page gives the IMO numbers
                ids = {**ids, **{ascii(s).upper(): imo for s, imo in ships.items() if imo}}
                ships = set(ships)
            url = urls.get(os.path.basename(path), "")
            title = f"{operator}: {heading}" + ("" if "its ferries" in heading else ", its ferries")
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

    # Crossings to and from ports outside the EU and the EEA, by
    # OpenStreetMap's lines: their ships aren't named, but the ports' countries
    # give the share of the emissions under the EU ETS.
    car = {i for i, _ in lines_of(gosm)[0]} | {w["id"] for w in gosm["elements"] if w.get("tags", {}).get("hgv") in ("yes", "designated")}
    pairs = {}
    for w in gosm["elements"]:
        if w["type"] != "way" or w["id"] not in car:
            continue
        name = w.get("tags", {}).get("name", "")
        ports = named_ports(name)
        if len(ports) != 2 or all(PORTS[p][0] in EEA for p in ports):
            continue
        pairs.setdefault(frozenset(ports), []).append(w)
    for key, ways in sorted(pairs.items(), key=lambda kv: sorted(kv[0])):
        if key in have:
            # An operator's page named this crossing's ships: say which other
            # operators OpenStreetMap's lines name, whose ships aren't in it.
            ops = sorted({o.strip() for w in ways for o in re.split(r"[;/,]", w["tags"].get("operator", "")) if o.strip()})
            same = lambda x: re.sub(r"\s*&\s*", "&", fold(x))
            others = [o for o in ops if not any(same(x) in same(o) or same(o) in same(x) for x in re.split(r";\s*", have[key]["operator"]))]
            if others and "also name" not in have[key]["source"]["title"]:
                have[key]["source"]["title"] += f"; OpenStreetMap's lines also name {', '.join(others)}, whose ships aren't in it"
            continue
        a, b = sorted(key, key=lambda p: (PORTS[p][0] in EEA, p))
        pos = osm_place(gosm, a, b, "")
        if not pos:
            continue
        COUNTRY.update({p: PORTS[p][0] for p in (a, b)})
        ops = sorted({w["tags"]["operator"] for w in ways if w["tags"].get("operator")})
        cid = "-".join(re.sub(r"[^a-z0-9]+", "-", ascii(p)).strip("-") for p in (a, b))
        c = crossing(cid, (a, b), pos, "; ".join(ops), set(), {
            "title": "OpenStreetMap: " + "; ".join(sorted({w["tags"]["name"] for w in ways})) + " (its ships not named; the ports' countries)",
            "url": f"https://www.openstreetmap.org/way/{min(w['id'] for w in ways)}"}, ids)
        crossings.append(c)
        have[key] = c

    crossings.sort(key=lambda c: c["id"])
    os.makedirs(out, exist_ok=True)
    doc = {"note": "Ferry crossings with the ships their operators' timetables and pages name, built by tools/tables/ferry_ships.py; "
                   "IMO numbers from the EU MRV reports' ship lists.", "crossings": crossings}
    path = os.path.join(out, "crossings-ships.json")
    json.dump(doc, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, len(crossings), "crossings")


if __name__ == "__main__":
    if sys.argv[1:] == ["--osm-query"]:
        print("\n".join(osm_query()))
    else:
        main(*sys.argv[1:])
