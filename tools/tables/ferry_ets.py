"""Builds ferries/data/ets-surcharges.json: the EU ETS surcharges ferry
lines publish for freight, per metre of the vehicle's length, from

- DFDS's ETS surcharges page (dfds-ets.html; else the capture
  tools/tables/browser/dfds-ets.txt): each route's surcharge per lane metre
  for the month, in EUR, by the month's average EU allowance price (the
  band the page prints in bold);
- Scandlines' monthly surcharges notices (scl-surcharges-<yyyy>-<mm>.txt,
  as tools/tables/scandlines.py reads them): the ETS surcharge per
  commencing metre, at least 7, on Puttgarden–Rødby and Rostock–Gedser;
- POLSCA Baltic Ferries' ETS surcharge announcements
  (polsca-ets-surcharge-*announcement-<dd.mm.yyyy>.txt): EUR per commenced
  metre on each line, from a day until the next announcement.

Each route names the crossings (ferries/data/crossings*.json) whose two
terminals are its ports. The earlier months already in the committed file
are kept: DFDS's page shows only the month in force.

Usage: python3 ferry_ets.py <fetched dir> <out dir> [<committed ets-surcharges.json>]
"""
import datetime, glob, html.parser, json, os, re, sys, unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scandlines import MONTHS, surcharges as scl_surcharges  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DFDS_URL = "https://www.dfds.com/en/freight-ferries-and-logistics/ets-surcharges"
SCL_URL = "https://freight.scandlines.com/freight-conditions/fuel-surcharges/"
POLSCA_URL = "https://www.unityline.eu/en/documents"
# The routes' port names as the crossings' terminals name them.
ALIAS = {"ijmuiden": "ijmuiden", "vlaardingen": "rotterdam", "dunkirk": "dunkerque", "gothenburg": "gothenburg",
         "rodby": "rodby", "rostock": "rostock", "gedser": "gedser", "puttgarden": "puttgarden"}


# Words a terminal's name may add to its port's (Rødby Færgehavn).
PORT_WORDS = {"faergehavn", "havn", "port", "harbour", "terminal", "ferry"}
# POLSCA's announcements as read print some s as ś; their ports' names.
POLSCA_PORTS = {"swinoujscie": "Świnoujście", "ystad": "Ystad", "trelleborg": "Trelleborg", "gdansk": "Gdańsk", "karlshamn": "Karlshamn",
                "nynashamn": "Nynäshamn"}


def norm(s):
    s = re.sub(r"\(.*?\)", "", s).strip().casefold()
    s = s.replace("æ", "ae").replace("ø", "o").replace("ł", "l").replace("ś", "s")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = " ".join(w for w in re.sub(r"[^a-z ]", "", s).split() if w not in PORT_WORDS)
    return ALIAS.get(s, s)


def crossings_index():
    """Pairs of normalised terminal names -> crossing ids."""
    idx = {}
    for path in sorted(glob.glob(os.path.join(ROOT, "ferries", "data", "crossings*.json"))):
        for c in json.load(open(path, encoding="utf-8"))["crossings"]:
            names = frozenset(norm(t["name"]) for t in c["terminals"])
            if len(names) == 2:
                idx.setdefault(names, []).append(c["id"])
    return idx


def route_crossings(idx, name, sep):
    """The crossings of a route "A/B – C/D": every port of one side with
    every port of the other."""
    sides = [s.split("/") for s in re.split(sep, name, maxsplit=1)]
    if len(sides) != 2:
        return []
    out = []
    for a in sides[0]:
        for b in sides[1]:
            out += idx.get(frozenset((norm(a), norm(b))), [])
    return sorted(set(out))


class Tables(html.parser.HTMLParser):
    """The page's tables as rows of (text, bold) cells, and its text."""

    def __init__(self):
        super().__init__()
        self.tables, self.text, self.row, self.cell, self.bold, self.depth = [], [], None, None, False, 0

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.tables.append([])
        elif tag == "tr" and self.tables:
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell, self.bold = [], False
        elif tag in ("strong", "b") and self.cell is not None:
            self.bold = True

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None and self.row is not None:
            self.row.append(("".join(self.cell).strip(), self.bold))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.tables[-1].append(self.row)
            self.row = None

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)
        self.text.append(data)


def num(s):
    return float(s.replace(",", "."))


def dfds_rows(fetched):
    """(month yyyy-mm, average EUA price, its period, [(route, rate)], source)."""
    path = os.path.join(fetched, "dfds-ets.html")
    rows, text, src = None, "", DFDS_URL
    if os.path.exists(path):
        p = Tables()
        p.feed(open(path, encoding="utf-8", errors="replace").read())
        text = re.sub(r"\s+", " ", " ".join(p.text))
        eur = [t for t in p.tables if t and t[0] and t[0][0][0].startswith("ETS Charges")]
        if eur:
            rows = [[(c, b) for c, b in r] for r in eur[0][1:]]
    if rows is None:
        cap = os.path.join(HERE, "browser", "dfds-ets.txt")
        print(f"DFDS: dfds-ets.html not read; from {cap}")
        lines = [l for l in open(cap, encoding="utf-8").read().splitlines() if not l.startswith("#")]
        text = " ".join(lines)
        rows = [[(c.strip().lstrip("*"), c.strip().startswith("*")) for c in l.split("|")] for l in lines if "|" in l][1:]
        src = DFDS_URL + " (read in Chrome: tools/tables/browser/dfds-ets.txt)"
    m = re.search(r"average price of EU allowances in the period (\d\d)/(\d\d)/(\d{4}) - (\d\d)/(\d\d)/(\d{4}) was EUR ([\d.,]+) per allowance", text)
    mm = re.search(r"ETS surcharge per lane metre \(EUR\) (\w+) (\d{4})", text)
    if not m or not mm or mm.group(1) not in MONTHS:
        sys.exit("DFDS: the page's EUA price or month not read")
    month = f"{mm.group(2)}-{MONTHS.index(mm.group(1)) + 1:02d}"
    out = []
    for r in rows:
        if not r or not r[0][0] or r[0][0].startswith("Route"):
            continue
        bold = [c for c, b in r[1:] if b]
        if len(bold) != 1:
            sys.exit(f"DFDS {month}: {r[0][0]}: {len(bold)} bold rates")
        out.append((r[0][0], num(bold[0])))
    if len(out) < 10:
        sys.exit(f"DFDS {month}: only {len(out)} routes read")
    period = f"{m.group(3)}-{m.group(2)}-{m.group(1)} to {m.group(6)}-{m.group(5)}-{m.group(4)}"
    return month, num(m.group(7)), period, out, src


def scandlines(fetched):
    """[(from yyyy-mm-dd, {route: rate})] from the monthly notices."""
    out = []
    for path in sorted(glob.glob(os.path.join(fetched, "scl-surcharges-*.txt"))):
        month, s = scl_surcharges(open(path, encoding="utf-8").read())
        out.append((month, {"Puttgarden–Rødby": s["PR"]["ETS"], "Rostock–Gedser": s["RG"]["ETS"]}))
    return out


EN_MONTHS = {m: i + 1 for i, m in enumerate(MONTHS)}


def polsca(fetched):
    """[(from yyyy-mm-dd, {route: rate}, note)] from the announcements."""
    out = []
    for path in sorted(glob.glob(os.path.join(fetched, "polsca-ets-surcharge-*announcement-*.txt"))):
        name = os.path.basename(path)
        f = re.search(r"(\d\d)\.(\d\d)\.(\d{4})\.txt$", name)
        t = open(path, encoding="utf-8").read()
        en = re.sub(r"\s+", " ", t[t.find("Dear"):]).replace("ś", "s").replace("Ś", "S")
        d = re.search(r"effective from (\w+) (\d+), (\d{4})", en)
        if not f or not d or d.group(1) not in EN_MONTHS:
            sys.exit(f"POLSCA: {name}: the announcement's day not read")
        day = f"{f.group(3)}-{f.group(2)}-{f.group(1)}"
        said = f"{d.group(3)}-{EN_MONTHS[d.group(1)]:02d}-{int(d.group(2)):02d}"
        note = "" if said == day else f"the announcement's text says from {said}; its file name, {name}, and the series say {day}"
        rates = {}
        for route, rate in re.findall(r"on (\S.{4,60}?) link[s]? [–-] (\d+,\d\d) EUR", en):
            for r in route.split(" & "):
                ports = [POLSCA_PORTS.get(norm(x)) for x in r.split("-")]
                if len(ports) != 2 or None in ports:
                    sys.exit(f"POLSCA: {name}: route {r!r} not known")
                rates["–".join(ports)] = num(rate)
        if not rates:
            sys.exit(f"POLSCA: {name}: no rates read")
        out.append((day, rates, note))
    return sorted(out)


def main(fetched, outdir, committed=None):
    committed = committed or os.path.join(ROOT, "ferries", "data", "ets-surcharges.json")
    prev = json.load(open(committed, encoding="utf-8")) if os.path.exists(committed) else {"operators": []}
    prev_ops = {o["operator"]: o for o in prev["operators"]}
    idx = crossings_index()
    ops = []

    # DFDS: this month's page, with the months kept from before.
    month, eua, period, rows, src = dfds_rows(fetched)
    first = datetime.date.fromisoformat(month + "-01")
    last = (first.replace(day=28) + datetime.timedelta(days=4)).replace(day=1) - datetime.timedelta(days=1)
    eds = [e for e in prev_ops.get("DFDS", {}).get("editions", []) if e["from"] != first.isoformat()]
    eds.append({"from": first.isoformat(), "to": last.isoformat(), "eua_eur_per_t": eua,
                "basis": f"the average EU allowance price {period}, EUR {eua:g}", "source": src,
                "rates": {r: v for r, v in rows}})
    routes = sorted({r for e in eds for r in e["rates"]})
    ops.append({"operator": "DFDS", "unit": "EUR per lane metre", "commenced_metre": False, "min_m": 0,
                "source": {"title": "DFDS: ETS surcharges (freight), per lane metre, monthly", "url": DFDS_URL},
                "routes": [{"name": r, "crossings": route_crossings(idx, r, r"\s+–\s+")} for r in routes],
                "editions": sorted(eds, key=lambda e: e["from"])})

    # Scandlines: each month's notice.
    scl = scandlines(fetched)
    if scl:
        eds = [{"from": m, "source": SCL_URL, "rates": r} for m, r in scl]
        for i, e in enumerate(eds[:-1]):
            e["to"] = (datetime.date.fromisoformat(eds[i + 1]["from"]) - datetime.timedelta(days=1)).isoformat()
        ops.append({"operator": "Scandlines", "unit": "EUR per commencing metre, at least 7", "commenced_metre": True, "min_m": 7,
                    "source": {"title": "Scandlines: surcharges notices (BAF, ETS, GIR), monthly", "url": SCL_URL},
                    "routes": [{"name": r, "crossings": route_crossings(idx, r, "–")} for r in ("Puttgarden–Rødby", "Rostock–Gedser")],
                    "editions": eds})
    elif "Scandlines" in prev_ops:
        ops.append(prev_ops["Scandlines"])

    # POLSCA: each announcement, until the next one for the route.
    pol = polsca(fetched)
    if pol:
        eds = []
        for day, rates, note in pol:
            e = {"from": day, "source": POLSCA_URL, "rates": rates}
            if note:
                e["note"] = note
            eds.append(e)
        routes = sorted({r for e in eds for r in e["rates"]})
        ops.append({"operator": "POLSCA Baltic Ferries (Polferries, Unity Line)", "unit": "EUR per commenced metre", "commenced_metre": True, "min_m": 0,
                    "source": {"title": "POLSCA Baltic Ferries: ETS surcharge announcements", "url": POLSCA_URL},
                    "routes": [{"name": r, "crossings": route_crossings(idx, r, "–")} for r in routes],
                    "editions": eds, "per_route": True})
    elif "POLSCA Baltic Ferries (Polferries, Unity Line)" in prev_ops:
        ops.append(prev_ops["POLSCA Baltic Ferries (Polferries, Unity Line)"])

    for o in ops:
        lost = [r["name"] for r in o["routes"] if not r["crossings"]]
        if lost:
            print(f"{o['operator']}: routes with no crossing here (not priced): {', '.join(lost)}")
    out = {"note": "The EU ETS surcharges ferry lines publish for freight, per metre of the vehicle's length, by route and period (built by "
                   "tools/tables/ferry_ets.py). An edition is in force from its day to its 'to' day, or, without one, until the operator's next "
                   "edition (POLSCA: the next one naming the route). carbon-cost prices a crossing's EU ETS at its operator's surcharge where "
                   "the crossing has only that operator.",
           "operators": ops}
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "ets-surcharges.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(f"ets-surcharges.json: {', '.join(f'{o['operator']} {len(o['editions'])} editions' for o in ops)}")


if __name__ == "__main__":
    main(*sys.argv[1:])
