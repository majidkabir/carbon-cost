"""Builds fuel/data/wob-diesel.csv from the European Commission's Weekly
Oil Bulletin price history (Weekly_Oil_Bulletin_Prices_History_maticni_4web.xlsx,
https://energy.ec.europa.eu/data-and-analysis/weekly-oil-bulletin_en): each
EU country's national average pump price of automotive gas oil (diesel)
on each bulletin's Monday from FROM on, in EUR per litre without VAT.

Usage: python3 wob.py history.xlsx out.csv

The bulletin's sheet "Prices with taxes" gives the price with all duties
and taxes, in EUR per 1,000 litres, a column per country
(<CC>_price_with_tax_diesel); the sheet "VAT" gives each country's VAT
rate on diesel and the day it applies from ("Since:"; a country's rows run
newest first, its code on the first only). The price without VAT is the
price with taxes / (1 + the VAT rate on that Monday): what a business
that reclaims VAT pays at the pump on average; the excise duties and the
national CO2 prices on fuel stay in it.
"""
import csv, datetime, sys

import openpyxl

FROM = datetime.date(2024, 1, 1)
# The bulletin's codes that differ from ISO 3166-1 alpha-2.
ISO = {"GR": "GR", "EL": "GR", "UK": "GB"}


def vat_table(ws):
    """{country: [(since, rate %)], newest first}: rows without a rate
    are left out, so the rate in force is the newest given on or before a
    day."""
    out, cc = {}, None
    for row in ws.iter_rows(min_row=5, values_only=True):
        code, since, diesel = row[0], row[1], row[3] if len(row) > 3 else None
        if code:
            cc = str(code).strip().rstrip("_")
        if not cc or not isinstance(since, datetime.datetime) or diesel in (None, ""):
            continue
        out.setdefault(ISO.get(cc, cc), []).append((since.date(), float(diesel)))
    for v in out.values():
        v.sort(reverse=True)
    return out


def rate_on(rates, day):
    for since, r in rates:
        if since <= day:
            return r
    return None


def main(src, out):
    wb = openpyxl.load_workbook(src, read_only=True, data_only=True)
    vat = vat_table(wb["VAT"])
    ws = wb["Prices with taxes"]
    rows = ws.iter_rows(values_only=True)
    head = next(rows)
    cols = {}
    for i, h in enumerate(head):
        if isinstance(h, str) and h.endswith("_price_with_tax_diesel"):
            cc = h.split("_")[0]
            if cc in ("EU", "EUR"):  # the averages
                continue
            cols[ISO.get(cc, cc)] = i
    countries = sorted(cols)
    keep, unvatted = [], set()
    for row in rows:
        day = row[0]
        if not isinstance(day, datetime.datetime) or day.date() < FROM:
            continue
        day = day.date()
        rec = [day.isoformat()]
        for cc in countries:
            v = row[cols[cc]] if cols[cc] < len(row) else None
            r = rate_on(vat.get(cc, []), day)
            if not isinstance(v, (int, float)) or v <= 0:
                rec.append("")
            elif r is None:
                unvatted.add(cc)
                rec.append("")
            else:
                rec.append(f"{v / 1000 / (1 + r / 100):.4f}")
        keep.append(rec)
    keep.sort()
    # A country that never had a price (the UK since it left) is dropped.
    used = [i for i, cc in enumerate(countries) if any(r[i + 1] for r in keep)]
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date"] + [countries[i] for i in used])
        for r in keep:
            w.writerow([r[0]] + [r[i + 1] for i in used])
    if unvatted:
        print("no VAT rate for", ", ".join(sorted(unvatted)), file=sys.stderr)
    print(len(keep), "bulletins from", keep[0][0], "to", keep[-1][0], "for", len(used), "countries")


if __name__ == "__main__":
    main(*sys.argv[1:])
