"""Builds fx/data/ecb-hist.csv from the ECB's eurofxref-hist.csv: the euro
reference rates of each working day from FROM on, for the currencies the
rate tables use.

Usage: python3 ecb.py eurofxref-hist.csv out.csv

The ECB file has one row per day (newest first), a column per currency
and "N/A" where a currency had no rate.
"""
import csv, sys

FROM = "2024-01-01"
CURRENCIES = ["CHF", "CZK", "DKK", "GBP", "HUF", "NOK", "PLN", "RON", "SEK", "TRY", "BGN"]


def main(src, out):
    rows = list(csv.DictReader(open(src, encoding="utf-8")))
    keep = []
    for r in rows:
        d = r["Date"].strip()
        if d < FROM:
            continue
        vals = [(r.get(c) or "").strip() for c in CURRENCIES]
        keep.append([d] + ["" if v in ("", "N/A") else v for v in vals])
    keep.sort()
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date"] + CURRENCIES)
        w.writerows(keep)
    print(len(keep), "days from", keep[0][0], "to", keep[-1][0])


if __name__ == "__main__":
    main(*sys.argv[1:])
