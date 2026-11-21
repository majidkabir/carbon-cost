"""Builds Belgium's kilometre charge tables from 1 January 2024, by region,
from Viapass's rate grids: the images transcribed in
tools/history/transcribed/be-grids.json (checked here against the fetched
images' sha256), and the Viapass pages giving Wallonia's 2025 and 2026
indexed rates and Flanders' and Brussels' 2026 zero-emission rates as
HTML tables (be-vp-wal-2025.html, be-vp-wal-2026.html, be-vp-zev-2026.html).

Usage: python3 build_be.py fetched/ out-dir

Each table has a row per mass band (3.5-12 t, 12-32 t, over 32 t) and
EURO class, and zero-emission rows (CO2 class 5), as the July 2026 tables.
"""
import copy, html, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
BANDS = [{"min_kg": 3501, "max_kg": 12000}, {"min_kg": 12001, "max_kg": 32000}, {"min_kg": 32001}]
REGION = {"BE-VLG": "be-vlg", "BE-BRU": "be-bru", "BE-WAL": "be-wal"}
NAMES = {"BE-VLG": "Flanders", "BE-BRU": "Brussels, highway and urban area (all local and regional roads that are not highway)", "BE-WAL": "Wallonia (SOFICO), excluding VAT"}
VEHICLES = "Vehicles over 3.5 t maximum authorised mass for goods transport, by mass band (3.5-12 t, 12-32 t, over 32 t)"
META = {  # each table's fields besides its dates, law, sources and rows
    "BE-VLG": {"vehicles": VEHICLES, "min_kg": 3501, "region": "BE-VLG", "name": "Belgian kilometre charge, Flemish Region",
               "tolled_roads": "The Flemish toll road network (motorways and listed regional and local roads)."},
    "BE-BRU": {"vehicles": VEHICLES, "min_kg": 3501, "region": "BE-BRU", "name": "Belgian kilometre charge, Brussels-Capital Region",
               "tolled_roads": "All roads in the Brussels-Capital Region: highway and urban-area rates."},
    "BE-WAL": {"vehicles": VEHICLES, "min_kg": 3501, "region": "BE-WAL", "name": "Belgian kilometre charge, Walloon Region (SOFICO)",
               "tolled_roads": "The Walloon toll road network (SOFICO motorways and listed regional roads)."},
}
# (region, from, to, grid id or page, zero-emission page)
PERIODS = [
    ("BE-VLG", "2024-01-01", "2024-06-30", "be-vp-2024-01-table", None),
    ("BE-VLG", "2024-07-01", "2025-06-30", "be-vp-2024-07-table", None),
    ("BE-VLG", "2025-07-01", "2025-12-31", "be-vp-2025-07-table", None),
    ("BE-VLG", "2026-01-01", "2026-06-30", "be-vp-2025-07-table", "be-vp-zev-2026"),
    ("BE-BRU", "2024-01-01", "2024-06-30", "be-vp-2024-01-table", None),
    ("BE-BRU", "2024-07-01", "2025-06-30", "be-vp-2024-07-table", None),
    ("BE-BRU", "2025-07-01", "2025-12-31", "be-vp-2025-07-table", None),
    ("BE-BRU", "2026-01-01", "2026-06-30", "be-vp-2025-07-table", "be-vp-zev-2026"),
    ("BE-WAL", "2024-01-01", "2024-12-31", "be-vp-2024-01-table", None),
    ("BE-WAL", "2025-01-01", "2025-12-31", "be-vp-wal-2025", None),
    ("BE-WAL", "2026-01-01", "2026-06-30", "be-vp-wal-2026", None),
]


def text(path):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", open(path, encoding="utf-8").read())))


def page_url(fetched, sid):
    return next(f["url"] for f in json.load(open(os.path.join(fetched, "manifest.json")))["files"] if f["file"].startswith(sid + "."))


def wallonia(fetched, sid):
    """EURO 0-6 by band from SOFICO's indexation page; ZEV pays EURO 6."""
    t = text(os.path.join(fetched, sid + ".html"))
    out = []
    for band in ("> 3,5 tons & < 12 tons", "≥ 12 tons & ≤ 32 tons", "> 32 tons"):
        m = re.search(re.escape(band) + r"((?: [\d,]+ €){7})", t)
        out.append([float(x.replace(",", ".")) for x in re.findall(r"[\d,]+", m.group(1))])
    rows = [list(r) for r in zip(*out)]
    return rows + [rows[6]]


def zev(fetched, sid):
    t = text(os.path.join(fetched, sid + ".html"))
    v = [float(x.replace(",", ".")) for x in re.search(r"ZEV((?: [\d,]+){9})", t).group(1).split()]
    return {"BE-VLG": v[0:3], "BE-BRU motorway": v[3:6], "BE-BRU other": v[6:9]}


def rows_of(grid, road=None):
    rows = []
    for euro, rates in enumerate(grid[:7]):
        for band, r in zip(BANDS, rates):
            row = {"component": "km_charge", **band, "co2_class": [1, 2, 3, 4], "euro": [euro], "rate": r}
            if road:
                row["road"] = road
            rows.append(row)
    for band, r in zip(BANDS, grid[7]):
        row = {"component": "km_charge", **band, "co2_class": [5], "rate": r}
        if road:
            row["road"] = road
        rows.append(row)
    return rows


JULY_2026_LAW = {
    "BE-VLG": "Viapass rate grid ed. 01/07/2026, Flanders (with the CO2 class element from 1 July 2026). The published rates are totals: the CO2 part is not shown separately.",
    "BE-BRU": "Viapass rate grid ed. 01/07/2026, Brussels, highway and urban area (all local and regional roads that are not highway). No CO2 element.",
    "BE-WAL": "Viapass rate grid ed. 01/07/2026, Wallonia, excluding VAT. No CO2 element; zero-emission trucks pay the Euro VI rate.",
}

JANUARY_2027_LAW = {
    "BE-VLG": "Viapass rate grid ed. 01/01/2027, Flanders: the rates indexed on 1 January 2027 (Flanders now indexes on 1 January, before on 1 July), with the CO2 class element; the published rates are totals, the CO2 part is not shown separately. Zero-emission trucks pay 60% of the infrastructure part in 2027 and no external-cost part until 31 December 2029; their share rises to 80% (40% reduction) on 1 January 2028, so the table ends on 31 December 2027.",
    "BE-BRU": "Viapass rate grid ed. 01/01/2027, Brussels, highway and urban area (all local and regional roads that are not highway): no indexation in 2027, no CO2 element. Zero-emission trucks pay 60% of the infrastructure part in 2027 and no external-cost part until 31 December 2029; their share changes on 1 January 2028, so the table ends on 31 December 2027.",
    "BE-WAL": "Viapass rate grid ed. 01/01/2027, Wallonia, excluding VAT: the rates indexed on 1 January 2027 on the consumer price index of August 2026 (Walloon decree of 16 July 2015, art. 7, § 4), as each year on 1 January, so the table ends on 31 December 2027. No CO2 element; zero-emission trucks pay the Euro VI rate.",
}


def grouped(grid, road=None):
    """The rows of a grid of EURO 0-5 (CO2 class 1), EURO 6 in CO2 classes
    1-4 and ZEV: EURO classes with the same rates in every band share a
    row (for CO2 classes 1-4, as the grid's EURO 0-5 rates hold for each),
    EURO 6 has a row per CO2 class unless they're all the same."""
    rows = []

    def add(rates, **sel):
        for band, r in zip(BANDS, rates):
            row = {"component": "km_charge", **band, **sel, "rate": r}
            if road:
                row["road"] = road
            rows.append(row)
    groups = []
    for euro, rates in enumerate(grid[:6]):
        if groups and groups[-1][1] == rates:
            groups[-1][0].append(euro)
        else:
            groups.append(([euro], rates))
    six = grid[6:10]
    if all(r == six[0] for r in six):
        groups.append(([6], six[0]))
    for euros, rates in groups:
        add(rates, co2_class=[1, 2, 3, 4], euro=euros)
    if not all(r == six[0] for r in six):
        for c, rates in enumerate(six, 1):
            add(rates, co2_class=[c], euro=[6])
    add(grid[10], co2_class=[5])
    return rows


def july2026(fetched, out, g):
    """The tables from 1 July 2026: Viapass's grid of that edition."""
    page = text(os.path.join(fetched, "be-vp-co2-vlg.html"))
    if "As from July 1st, 2026, a surcharge for CO2 emissions will be applied to the rates of the kilometer charge in Flanders" not in page:
        sys.exit("be-vp-co2-vlg: not the CO2 surcharge from 1 July 2026")
    for region in ("BE-VLG", "BE-BRU", "BE-WAL"):
        keys = ["BE-BRU motorway", "BE-BRU other"] if region == "BE-BRU" else [region]
        tb = {"country": "BE", "currency": "EUR", "valid_from": "2026-07-01", "valid_to": "2026-12-31", **META[region],
              "law": JULY_2026_LAW[region],
              "sources": [{"title": "Viapass: kilometer charge rates from 1 July 2026 (rate grid, ed. 01/07/2026)", "url": g["page"]},
                          {"title": "Viapass: CO2 surcharge in Flanders from 1 July 2026", "url": "https://www.viapass.be/en/news/surcharge-co2-emissions-flanders.html"}],
              "rows": [r for k in keys for r in grouped(g[k], {"BE-BRU motorway": "motorway", "BE-BRU other": "other"}.get(k))]}
        os.makedirs(out, exist_ok=True)
        path = os.path.join(out, f"{REGION[region]}-2026-07-01.json")
        json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
        print(path, len(tb["rows"]), "rows")


def january2027(fetched, out, g):
    """The tables from 1 January 2027: Viapass's grid of that edition."""
    page = text(os.path.join(fetched, "be-vp-2027-01.html"))
    if "Starting Friday, January 1st, 2027, new rates for the kilometer charge will be applicable" not in page:
        sys.exit("be-vp-2027-01: not the rates from 1 January 2027")
    for region in ("BE-VLG", "BE-BRU", "BE-WAL"):
        keys = ["BE-BRU motorway", "BE-BRU other"] if region == "BE-BRU" else [region]
        tb = {"country": "BE", "currency": "EUR", "valid_from": "2027-01-01", "valid_to": "2027-12-31", **META[region],
              "law": JANUARY_2027_LAW[region],
              "sources": [{"title": "Viapass: kilometer charge changes from 1 January 2027 (rate grid, ed. 01/01/2027)", "url": g["page"]},
                          {"title": "The rate grid image", "url": g["source"]["url"]}],
              "rows": [r for k in keys for r in grouped(g[k], {"BE-BRU motorway": "motorway", "BE-BRU other": "other"}.get(k))]}
        os.makedirs(out, exist_ok=True)
        path = os.path.join(out, f"{REGION[region]}-2027-01-01.json")
        json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
        print(path, len(tb["rows"]), "rows")


def main(fetched, out):
    tr = json.load(open(os.path.join(HERE, "transcribed", "be-grids.json"), encoding="utf-8"))
    grids = {g["id"]: g for g in tr["grids"]}
    files = {f["url"]: f for f in json.load(open(os.path.join(fetched, "manifest.json")))["files"]}
    for g in grids.values():
        f = files.get(g["source"]["url"])
        if f is None or f["sha256"] != g["source"]["sha256"]:
            sys.exit(f"{g['id']}: the fetched image isn't the one transcribed")
    # Wallonia's indexation pages agree with the grids that show them.
    assert wallonia(fetched, "be-vp-wal-2025") == grids["be-vp-2025-07-table"]["BE-WAL"]
    assert grids["be-vp-2024-01-table"]["BE-WAL"] == grids["be-vp-2024-07-table"]["BE-WAL"]
    july2026(fetched, out, grids["be-vp-2026-07-table"])
    january2027(fetched, out, grids["be-vp-2027-01-table"])
    for region, frm, to, src, zpage in PERIODS:
        tb = {"country": "BE", "currency": "EUR", "valid_from": frm, "valid_to": to, **META[region]}
        keys = ["BE-BRU motorway", "BE-BRU other"] if region == "BE-BRU" else [region]
        if src in grids:
            g = grids[src]
            vals = {k: copy.deepcopy(g[k]) for k in keys}
            law = f"Viapass rate grid {g['edition']}, {NAMES[region]}"
            sources = [{"title": f"Viapass: kilometer charge rates {g['edition']} (rate grid, transcribed in tools/history/transcribed/be-grids.json)", "url": g["page"]},
                       {"title": "The rate grid image", "url": g["source"]["url"]}]
        else:
            vals = {region: wallonia(fetched, src)}
            law = f"SOFICO's indexed rates from {frm} as published by Viapass, {NAMES[region]}. Zero-emission trucks pay the Euro VI rate"
            sources = [{"title": f"Viapass: indexation of the kilometer charge in Wallonia on {frm}", "url": page_url(fetched, src)}]
        if zpage:
            z = zev(fetched, zpage)
            for k in keys:
                vals[k][7] = z[k]
            law += "; zero-emission rates from 1 January 2026 (80% of the infrastructure part)"
            sources.append({"title": "Viapass: zero-emission rates from 1 January 2026", "url": page_url(fetched, zpage)})
        tb["law"] = law + "."
        tb["sources"] = sources
        tb["rows"] = [r for k in keys for r in rows_of(vals[k], {"BE-BRU motorway": "motorway", "BE-BRU other": "other"}.get(k))]
        os.makedirs(out, exist_ok=True)
        path = os.path.join(out, f"{REGION[region]}-{frm}.json")
        json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
        print(path, len(tb["rows"]), "rows")


if __name__ == "__main__":
    main(*sys.argv[1:])
