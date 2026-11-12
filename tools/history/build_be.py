"""Builds Belgium's kilometre charge tables from 1 January 2024 to 30 June
2026, by region, from Viapass's rate grids: the images transcribed in
tools/history/transcribed/be-grids.json (checked here against the fetched
images' sha256), and the Viapass pages giving Wallonia's 2025 and 2026
indexed rates and Flanders' and Brussels' 2026 zero-emission rates as
HTML tables (be-vp-wal-2025.html, be-vp-wal-2026.html, be-vp-zev-2026.html).

Usage: python3 build_be.py fetched/ out-dir

Each table has a row per mass band (3.5-12 t, 12-32 t, over 32 t) and
EURO class, and zero-emission rows (CO2 class 5), as the July 2026 tables.
"""
import copy, hashlib, html, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
BANDS = [{"min_kg": 3501, "max_kg": 12000}, {"min_kg": 12001, "max_kg": 32000}, {"min_kg": 32001}]
REGION = {"BE-VLG": "be-vlg", "BE-BRU": "be-bru", "BE-WAL": "be-wal"}
NAMES = {"BE-VLG": "Flanders", "BE-BRU": "Brussels, highway and urban area (all local and regional roads that are not highway)", "BE-WAL": "Wallonia (SOFICO), excluding VAT"}
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
    for region, frm, to, src, zpage in PERIODS:
        tmpl = json.load(open(os.path.join(ROOT, "rates", "data", f"{REGION[region]}-2026-07-01.json"), encoding="utf-8"))
        tb = {k: copy.deepcopy(v) for k, v in tmpl.items() if k not in ("rows", "law", "sources")}
        tb["valid_from"], tb["valid_to"] = frm, to
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
