"""Builds fuel/data/wob-diesel.csv from the European Commission's Weekly
Oil Bulletin price history (Weekly_Oil_Bulletin_Prices_History_maticni_4web.xlsx,
https://energy.ec.europa.eu/data-and-analysis/weekly-oil-bulletin_en): each
EU country's national average pump price of automotive gas oil (diesel)
on each bulletin's Monday from FROM on, in EUR per litre without VAT.

Usage: python3 wob.py history.xlsx out.csv [duties.csv]

With duties.csv, and when the workbook has a sheet of the prices without
taxes, it also writes each country's duties and taxes other than VAT on
diesel, EUR per litre: the price with taxes / (1 + VAT) less the price
without taxes. Some countries refund hauliers the excise above a floor
set by law (Italy: EUR 403.22 per 1,000 litres), so the refund follows
these. It prints the workbook's sheets, to see what the bulletin gives.

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


def net_sheet(wb):
    """The sheet of the prices without taxes, if the workbook has one."""
    for name in wb.sheetnames:
        n = name.lower()
        if ("wo" in n.split() or "without" in n or "w/o" in n) and "tax" in n:
            return wb[name]
    return None


def duties(wb, vat, out):
    ws = net_sheet(wb)
    if ws is None:
        print("no sheet of prices without taxes: duties not written", file=sys.stderr)
        return
    rows = ws.iter_rows(values_only=True)
    head = next(rows)
    print("prices without taxes:", ws.title, [h for h in head if isinstance(h, str)][:6], "...")
    net = {}
    for i, h in enumerate(head):
        if isinstance(h, str) and h.endswith("_diesel"):
            cc = h.split("_")[0]
            if cc not in ("EU", "EUR"):
                net[ISO.get(cc, cc)] = i
    withtax = {}
    ws = wb["Prices with taxes"]
    rows2 = ws.iter_rows(values_only=True)
    head2 = next(rows2)
    cols = {ISO.get(h.split("_")[0], h.split("_")[0]): i for i, h in enumerate(head2)
            if isinstance(h, str) and h.endswith("_price_with_tax_diesel")}
    for row in rows2:
        if isinstance(row[0], datetime.datetime) and row[0].date() >= FROM:
            withtax[row[0].date()] = row
    keep = []
    countries = sorted(set(net) & set(cols))
    for row in rows:
        day = row[0]
        if not isinstance(day, datetime.datetime) or day.date() < FROM or day.date() not in withtax:
            continue
        day = day.date()
        rec = [day.isoformat()]
        for cc in countries:
            n = row[net[cc]] if net[cc] < len(row) else None
            w = withtax[day][cols[cc]] if cols[cc] < len(withtax[day]) else None
            r = rate_on(vat.get(cc, []), day)
            if not all(isinstance(v, (int, float)) and v > 0 for v in (n, w)) or r is None:
                rec.append("")
            else:
                rec.append(f"{(w / (1 + r / 100) - n) / 1000:.4f}")
        keep.append(rec)
    keep.sort()
    used = [i for i, cc in enumerate(countries) if any(r[i + 1] for r in keep)]
    with open(out, "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["date"] + [countries[i] for i in used])
        for r in keep:
            wr.writerow([r[0]] + [r[i + 1] for i in used])
    if keep:
        print("duties:", len(keep), "bulletins from", keep[0][0], "to", keep[-1][0], "for", len(used), "countries")


def main(src, out, duties_out=None):
    wb = openpyxl.load_workbook(src, read_only=True, data_only=True)
    print("sheets:", wb.sheetnames)
    vat = vat_table(wb["VAT"])
    if duties_out:
        duties(wb, vat, duties_out)
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
