"""Builds fx/data/ecb-hist.csv from the ECB's eurofxref-hist.csv: the euro
reference rates of each working day from FROM on, for every currency the
ECB gave a rate for in that time (the rate tables' and those a result may
be asked in).

Usage: python3 ecb.py eurofxref-hist.csv out.csv

The ECB file has one row per day (newest first), a column per currency
and "N/A" where a currency had no rate.
"""
import csv, re, sys

# A month before the first tables (1 January 2024), so their first days
# have the last working day's rates.
FROM = "2023-12-01"


def main(src, out):
    rows = [{k.strip(): (v or "").strip() for k, v in r.items() if k} for r in csv.DictReader(open(src, encoding="utf-8"))]
    rows = [r for r in rows if r["Date"] >= FROM]
    given = lambda v: v not in ("", "N/A")
    currencies = sorted(c for c in rows[0] if re.fullmatch(r"[A-Z]{3}", c) and any(given(r.get(c, "")) for r in rows))
    for c in ("CHF", "CZK", "GBP", "HUF", "NOK", "PLN", "RON", "SEK", "TRY", "ISK", "USD"):
        if c not in currencies:
            sys.exit(f"ECB: no {c} rates since {FROM}")
    keep = []
    for r in rows:
        keep.append([r["Date"]] + [r.get(c, "") if given(r.get(c, "")) else "" for c in currencies])
    keep.sort()
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date"] + currencies)
        w.writerows(keep)
    print(len(keep), "days from", keep[0][0], "to", keep[-1][0])


if __name__ == "__main__":
    main(*sys.argv[1:])
