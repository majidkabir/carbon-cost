"""Builds Denmark's domestic car ferries for trucks, a dataset per line and
price list (dk-<line>-<from>.json), from

- each line's freight page: MOLSLINJEN's own lines SAMSØLINJEN
  (Kalundborg–Ballen, run for the state under its contract with the
  Ministry of Transport), ALSLINJEN (Bøjden–Fynshav, likewise), FANØLINJEN
  (Esbjerg–Nordby) and LANGELANDSLINJEN (Spodsbjerg–Tårs), each a list of
  truck prices per single trip by length for each year it gives ("Priser
  2026", "Gældende fra 1. januar til 31. december 2026"), stated with or
  without VAT; MOLSLINJEN (Aarhus–Odden, Ebeltoft–Odden), its prices
  without VAT and without a date, plus an ETS fee; and Samsø Rederi
  (Hou–Sælvig, the municipality's line), its prices with VAT and the VAT
  amount, without a date;
- OpenStreetMap (dk-ferries-osm.json, Overpass): the ferry lines and the
  ferry terminals.

carbon-cost prices a trip by the truck's length (truck.length_m) in the
bands each line gives; a band "max. 12 m" holds lengths over the band
before it up to 12 m. Prices given with VAT are taken without it (25%,
or the VAT amount Samsø Rederi states). MOLSLINJEN's ETS fee isn't added:
carbon-cost prices the EU ETS on a crossing itself, from the ships' MRV
data (eua_eur_per_t). Prices only given "from" (MOLSLINJEN's other
vehicles to 25 m) and special transports (wide loads) aren't used. Each
line is a closed system on OpenStreetMap's car ferry lines (ferry_osm.py).

Usage: python3 dk_ferries.py <fetched dir> <out dir>
"""
import html, json, math, os, re, sys

from ferry_osm import MATCH_KM, lines_of, port_places, systems as place_systems

START = "2026-11-19"  # the day the undated pages (MOLSLINJEN, Samsø Rederi) were first read
MAX_M = 26  # the longest truck priced (Directive 96/53/EC's 25.25 m modular combinations)

LINES = {
    "samsoelinjen": {"op": "SAMSØLINJEN", "src": "dk-samsoelinjen-freight", "url": "https://www.samsoelinjen.dk/alt-det-praktiske/fragt",
                     "ports": {"Kalundborg": ("terminal", "SamsøFærgen"), "Ballen": ("terminal", "Ballen Færgehavn")},
                     "routes": {"Kalundborg–Ballen": [("Kalundborg", "Ballen")]},
                     # The state's contract (Bilag 2, pkt. 3.2, Tabel 4) prices a goods vehicle "over 10 m and up to 20 m" alike,
                     # so the page's last band (road train to 19 m) runs to 20 m, where its price per metre over begins.
                     "contract": ("Transportministeriet: contract with Molslinjen on Ballen–Kalundborg 2025–2034, Bilag 2 pkt. 3.2",
                                  "https://www.trm.dk/media/rpchpvqy/faergekontrakt-for-samsoe-kalundborg-2024-2035ny.pdf")},
    "alslinjen": {"op": "ALSLINJEN", "src": "dk-alslinjen-freight", "url": "https://www.alslinjen.dk/alt-det-praktiske/fragt",
                  "ports": {"Bøjden": ("terminal", "Bøjden"), "Fynshav": ("terminal", "Fynshav")},
                  "routes": {"Bøjden–Fynshav": [("Bøjden", "Fynshav")]}},
    "fanoelinjen": {"op": "FANØLINJEN", "src": "dk-fanoelinjen-freight", "url": "https://www.fanoelinjen.dk/alt-det-praktiske/fragt",
                    "ports": {"Esbjerg": ("terminal", "Esbjerg"), "Nordby": ("terminal", "Nordby")},
                    "routes": {"Esbjerg–Nordby": [("Esbjerg", "Nordby")]}},
    "langelandslinjen": {"op": "LANGELANDSLINJEN", "src": "dk-langelandslinjen-freight", "url": "https://www.langelandslinjen.dk/alt-det-praktiske/fragt",
                         "ports": {"Spodsbjerg": ("terminal", "Spodsbjerg Færgehavn"), "Tårs": ("terminal", "Tårs Færgehavn")},
                         "routes": {"Spodsbjerg–Tårs": [("Spodsbjerg", "Tårs")]}},
    "molslinjen": {"op": "MOLSLINJEN", "src": "dk-molslinjen-freight", "url": "https://www.molslinjen.dk/alt-det-praktiske/fragt",
                   "ports": {"Aarhus": ("terminal", "Molslinjen Aarhus"), "Ebeltoft": ("terminal", "Molslinjen Ebeltoft"), "Odden": ("terminal", "Molslinjen Odden")},
                   "routes": {"Aarhus–Odden": [("Aarhus", "Odden")], "Ebeltoft–Odden": [("Ebeltoft", "Odden")]}},
    "samsoe-rederi": {"op": "Samsø Rederi", "src": "dk-samsoe-rederi-freight", "url": "https://www.tilsamsoe.dk/priser-lastbiler/",
                      "ports": {"Hou": ("terminal", "Samsø - Hou"), "Sælvig": ("terminal", "Hou")},
                      "routes": {"Hou–Sælvig": [("Hou", "Sælvig")]}},
}
NUM = r"(\d[\d.]*(?:,\d\d)?)"


def text(path):
    t = open(path, encoding="utf-8").read()
    t = re.sub(r"<script.*?</script>", " ", t, flags=re.S)
    t = re.sub(r"<style.*?</style>", " ", t, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", html.unescape(t))


def dkk(s):
    return float(s.replace(".", "").replace(",", "."))


def bands(items, over=None):
    """Price bands [(from m, to m, DKK)] from [(kind, "maks"|"over", m, DKK)]
    and a price per started metre over a length (m, DKK)."""
    out, lo = [], 0
    for kind, bound, m, p in sorted(items, key=lambda x: (x[2], x[1] == "over")):
        if bound == "maks":
            if out and out[-1][2] == p and out[-1][1] == lo:
                out[-1] = (out[-1][0], m, p)
            else:
                out.append((lo, m, p))
            lo = m
        else:
            if m != lo:
                sys.exit(f"a band over {m} m doesn't start where the last ends ({lo} m)")
            out.append((m, MAX_M, p))
            lo = MAX_M
    if over:
        start, per = over
        if lo > start:
            sys.exit(f"the price per metre begins at {start} m, inside a band to {lo} m")
        out[-1] = (out[-1][0], start, out[-1][2])  # the last band runs to where the price per metre begins
        base = out[-1][2]
        for m in range(start + 1, MAX_M + 1):  # each started metre over
            out.append((m - 1, m, base + per * (m - start)))
    return out


def molslinjen_family(page, op):
    """{year: (bands, VAT note)} from a "Priser <year>" freight page."""
    years = re.findall(r"Gældende fra 1\. januar til 31\. december (\d{4})", page) or re.findall(r"Priser (\d{4}) Priser for lastbiler", page) \
        or re.findall(r"Priser (\d{4}) Priser opgives", page)
    heads = []
    for y in dict.fromkeys(years):
        i = page.find(f"Priser {y} ")
        if i < 0:
            sys.exit(f"{op}: the heading Priser {y} not found")
        heads.append((y, i))
    if not heads:
        sys.exit(f"{op}: no year's prices found")
    out = {}
    for k, (y, i) in enumerate(heads):
        sec = page[i:heads[k + 1][1] if k + 1 < len(heads) else len(page)]
        m = re.search(r"Priser for lastbiler (?:\d{4} )?\((ekskl|inkl)\. moms\) DKK: (.*?)(?:Priser for specialtransporter|$)", sec)
        if not m:
            sys.exit(f"{op} {y}: the truck prices not found")
        vat, body = m.groups()
        if vat == "inkl" and "inkl. moms" not in sec[:m.start() + 60]:
            sys.exit(f"{op} {y}: VAT unclear")
        items = [(kind, bound, int(l), dkk(p)) for kind, bound, l, p in
                 re.findall(r"(Lastbil/sættevogn|Lastbil|Sættevogn|Vogntog) (maks\.|over) (\d+) m\. lang(?: inkl\. fører)?: DKK " + NUM, body)]
        items = [(k_, "maks" if b == "maks." else "over", l, p) for k_, b, l, p in items]
        per = re.search(r"Tillæg pr\. ekstra påbegyndt meter(?: over (\d+) meter)?: DKK " + NUM, body)
        if len(items) < 3:
            sys.exit(f"{op} {y}: only {len(items)} truck prices read")
        # A price per started metre with no length it begins at follows the
        # longest band: beyond the lengths priced here.
        over = (int(per.group(1)), dkk(per.group(2))) if per and per.group(1) else None
        b = bands(items, over)
        if vat == "inkl":
            b = [(lo, hi, round(p / 1.25, 2)) for lo, hi, p in b]
        out[y] = (b, "excluding VAT" if vat == "ekskl" else "including 25% VAT, taken out", items, per.group(0) if per else "")
    return out


def molslinjen(page):
    if "Alle priser er ekskl. moms." not in page:
        sys.exit("MOLSLINJEN: the page no longer says its prices exclude VAT")
    items, ets = [], {}
    for kind, m, p, e in re.findall(r"(Forvogn|Sættevogn|Vogntog) max (\d+) meter: DKK " + NUM + r" \+ ETS-gebyr: DKK " + NUM, page):
        items.append((kind, "maks", int(m), dkk(p)))
        ets[kind] = dkk(e)
    if len(items) != 3:
        sys.exit(f"MOLSLINJEN: {len(items)} truck prices read, not 3")
    if not re.search(r"Øvrige vogntyper, max 25 m\. og 40 tons fra DKK", page):
        sys.exit("MOLSLINJEN: the note on other vehicles changed")
    return bands(items), items, ets


def samsoe_rederi(page):
    i = page.find("LASTBILER")
    j = page.find("TRAKTOR", i)
    if i < 0 or j < i or "ENKELTBILLET INKL. MOMS" not in page:
        sys.exit("Samsø Rederi: the trucks' prices not found")
    rows = re.findall(r"(Max 10|10-12|12-17|17-19) meter [….]+ " + NUM + r",- Inkl\. chauffør\. Pris inkl\. moms inden fragtstøtte: " + NUM + r",- Momsbeløb: " + NUM, page[i:j])
    if [r[0] for r in rows] != ["Max 10", "10-12", "12-17", "17-19"]:
        sys.exit(f"Samsø Rederi: the bands read: {[r[0] for r in rows]}")
    out, items = [], []
    for band, p, before, vat in rows:
        lo, hi = (0, 10) if band == "Max 10" else map(int, band.split("-"))
        out.append((lo, hi, round(dkk(p) - dkk(vat), 2)))
        items.append((band, dkk(p), dkk(before), dkk(vat)))
    return out, items


def group_name(lo, hi):
    return f"up to {hi} m" if lo == 0 else f"{lo}-{hi} m"


def build(line, cfg, b, valid_from, valid_to, law, osm, lines, permit, out):
    pos = port_places(osm, lines, cfg["ports"])
    missing = [p for p in cfg["ports"] if p not in pos]
    if missing:
        sys.exit(f"{cfg['op']}: ports not placed: {missing}")
    placed, notes = place_systems(cfg["routes"], pos, lines, permit, lambda msg: sys.exit(f"{cfg['op']}: {msg}"))
    groups = [{"name": group_name(lo, hi), "min_kg": 3501, "max_length_m": hi, **({"min_length_m": lo} if lo else {})} for lo, hi, _ in b]
    systems = []
    for rs, stations, pairs in placed:
        prices = {f"{a}|{c}": {group_name(lo, hi): p for lo, hi, p in b} for _, a, c in pairs}
        systems.append({"name": f"{cfg['op']}: {' / '.join(rs)}", "law": f"{cfg['op']}'s freight prices: {' / '.join(rs)}", "groups": groups,
                        "stations": [{"name": n, "points": pts} for n, pts in sorted(stations.items())], "station_match_km": MATCH_KM, "prices": prices})
    sources = [{"title": f"{cfg['op']}: freight prices", "url": cfg["url"]}]
    if "contract" in cfg:
        sources.append({"title": cfg["contract"][0], "url": cfg["contract"][1]})
    sources.append({"title": "OpenStreetMap (Overpass API): Denmark's ferry lines and terminals", "url": "https://www.openstreetmap.org/"})
    t = {"country": "DK", "currency": "DKK", "valid_from": valid_from, **({"valid_to": valid_to} if valid_to else {}), "crossings": True,
         "name": f"{cfg['op']}'s ferries {', '.join(cfg['routes'])}, trucks",
         "law": law + " Ports at OpenStreetMap's ferry terminals, priced where the line goes out on its car ferry line." + "".join(f" {x}." for x in notes),
         "sources": sources, "vehicles": "Trucks over 3.5 t, by length (truck.length_m)", "min_kg": 3501,
         "tolled_roads": f"{cfg['op']}'s ferries {', '.join(cfg['routes'])}.", "closed_systems": systems, "rows": []}
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"dk-{line}-{valid_from}.json")
    json.dump(t, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, [(lo, hi, p) for lo, hi, p in b])


def band_text(b):
    return ", ".join(f"{group_name(lo, hi)} {p:g}" for lo, hi, p in b)


def main(fetched, out):
    try:
        osm = json.load(open(os.path.join(fetched, "dk-ferries-osm.json")))
    except (OSError, ValueError):
        print("Danish ferries: OpenStreetMap wasn't fetched; not built")
        return
    lines, permit = lines_of(osm)
    for line, cfg in LINES.items():
        try:
            page = text(os.path.join(fetched, cfg["src"] + ".html"))
        except OSError:
            print(f"{cfg['op']}: the page wasn't fetched; not built")
            continue
        routes = ", ".join(cfg["routes"])
        if line == "molslinjen":
            b, items, ets = molslinjen(page)
            law = (f"MOLSLINJEN's freight prices per single trip, excluding VAT, on {routes}: " + "; ".join(f"{k} to {m} m DKK {p:g}" for k, _, m, p in items)
                   + f" (DKK {band_text(b)} by length). Its ETS fee (DKK " + ", ".join(f"{v:g}" for v in dict.fromkeys(ets.values()))
                   + ") isn't added: carbon-cost prices the EU ETS on the crossing from the ships' MRV data. Other vehicles to 25 m are priced only "
                     "\"from DKK 3,300\": not used. The page gives no date: valid_from is the day it was first read.")
            build(line, cfg, b, START, None, law, osm, lines, permit, out)
        elif line == "samsoe-rederi":
            b, items = samsoe_rederi(page)
            law = ("Samsø Rederi's prices for trucks on Hou–Sælvig per single trip with driver, after the state's freight subsidy: "
                   + "; ".join(f"{band} m DKK {p:.2f} including VAT of {v:.2f} (before the subsidy {q:g})" for band, p, q, v in items)
                   + f"; taken without the VAT: DKK {band_text(b)}. The page gives no date: valid_from is the day it was first read.")
            build(line, cfg, b, START, None, law, osm, lines, permit, out)
        else:
            for y, (b, vat, items, per) in molslinjen_family(page, cfg["op"]).items():
                law = (f"{cfg['op']}'s freight prices for {y} per single trip ({vat}) on {routes}: "
                       + "; ".join(f"{k} {'maks.' if bd == 'maks' else 'over'} {m} m DKK {p:g}" for k, bd, m, p in items) + (f"; {per}" if per else "")
                       + f". By length, without VAT: DKK {band_text(b)}.")
                if "contract" in cfg:
                    law += " The road train's price runs to 20 m, where the price per metre over begins, as the state's contract prices goods vehicles over 10 m up to 20 m alike."
                build(line, cfg, b, f"{y}-01-01", f"{y}-12-31", law, osm, lines, permit, out)


if __name__ == "__main__":
    main(*sys.argv[1:])
