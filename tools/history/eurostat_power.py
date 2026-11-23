"""Builds fuel/data/eurostat-power.csv from Eurostat's electricity prices
for non-household consumers (dataset nrg_pc_205, bi-annual): each
country's average price in EUR per kWh, without VAT and other recoverable
taxes and levies, for the consumption band 500 to 2,000 MWh a year (band
ID, the middle band Eurostat headlines), on the first day of each half
year from FROM on.

Usage: python3 eurostat_power.py nrg_pc_205.json out.csv

The JSON is Eurostat's dissemination API answer (JSON-stat 2.0) for
  https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/nrg_pc_205
  ?format=JSON&lang=en&nrg_cons=MWH500-1999&tax=X_VAT&currency=EUR&unit=KWH
Every dimension but geo and time has one category; a country's code is
ISO 3166-1 alpha-2 but for EL (Greece: GR); aggregates (EU27_2020, EA)
are left out.
"""
import csv, json, sys

FROM = "2024-S1"
ISO = {"EL": "GR", "UK": "GB"}


def main(src, out):
    d = json.load(open(src, encoding="utf-8"))
    ids, size = d["id"], d["size"]
    cats = {k: d["dimension"][k]["category"]["index"] for k in ids}
    for k in ids:
        if k not in ("geo", "time") and len(cats[k]) != 1:
            sys.exit(f"dimension {k} has {len(cats[k])} categories: filter the request")
    pos = {k: {i: c for c, i in cats[k].items()} for k in ids}
    strides, s = [], 1
    for n in reversed(size):
        strides.insert(0, s)
        s *= n
    vals = d.get("value", {})
    if isinstance(vals, list):
        vals = {str(i): v for i, v in enumerate(vals) if v is not None}
    table = {}
    for flat, v in vals.items():
        flat, coord = int(flat), {}
        for k, st, n in zip(ids, strides, size):
            coord[k] = pos[k][(flat // st) % n]
        geo, t = coord["geo"], coord["time"]
        if len(geo) != 2 or t < FROM or v is None:
            continue
        year, half = t.split("-S")
        day = f"{year}-{'01' if half == '1' else '07'}-01"
        table.setdefault(day, {})[ISO.get(geo, geo)] = float(v)
    countries = sorted({c for row in table.values() for c in row})
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date"] + countries)
        for day in sorted(table):
            w.writerow([day] + [f"{table[day][c]:.4f}" if c in table[day] else "" for c in countries])
    print(len(table), "half years from", min(table), "to", max(table), "for", len(countries), "countries")


if __name__ == "__main__":
    main(*sys.argv[1:])
