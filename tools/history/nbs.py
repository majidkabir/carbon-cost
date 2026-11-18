"""Builds fx/data/nbs-eur-rsd.csv: the National Bank of Serbia's official
middle exchange rate of the dinar against the euro (zvanični srednji kurs),
of each exchange rate list from FROM on, with the day it applies from.

The ECB publishes no dinar rate; the NBS's official middle rate is the one
Serbian law uses (Zakon o deviznom poslovanju, art. 41: for bookkeeping,
statistics, customs duty and other import fees). Its exchange rate web app
gives a period's lists (ExchangeRate/IndexPeriod: EUR, middle rate,
working days), a month at a time here.

Usage: python3 nbs.py out.csv
"""
import csv, datetime, html, re, sys, time, urllib.request

FROM = 2024
URL = ("https://webappcenter.nbs.rs/ExchangeRateWebApp/ExchangeRate/IndexPeriod?isSearchExecuted=true"
       "&DateFrom={a}&DateTo={b}&CurrencyCode=978&ExchangeRateListTypeID=3&WorkingDays=1")
UA = "carbon-cost history fetch (github.com/majidkabir/carbon-cost)"
ROW = re.compile(r"<tr>\s*<td>\s*(\d\d)\.(\d\d)\.(\d{4})\.?\s*</td>\s*<td>\s*(\d\d)\.(\d\d)\.(\d{4})\.?\s*</td>\s*"
                 r"<td>\s*1\s*</td>\s*<td>\s*(\d{3}),(\d{4})\s*</td>\s*</tr>")


def page(url):
    for i in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=120) as r:
                return html.unescape(r.read().decode("utf-8"))
        except Exception as e:
            print("retry", url, e, file=sys.stderr)
            time.sleep(30 * (i + 1))
    sys.exit(f"nbs: {url} not answered")


def main(out):
    today = datetime.date.today()
    rows = {}
    # A month a query (the app shows a page of some fifty lists).
    start = datetime.date(FROM, 1, 1)
    while start <= today:
        nxt = (start.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
        end = min(nxt - datetime.timedelta(days=1), today)
        h = page(URL.format(a=start.strftime("%d.%m.%Y."), b=end.strftime("%d.%m.%Y.")))
        if "СРЕДЊИ КУРС" not in h.upper():
            sys.exit(f"nbs: {start:%Y-%m}: not the middle rate table")
        got = ROW.findall(h)
        # Lists are formed each working day.
        if len(got) < (end - start).days * 0.5:
            sys.exit(f"nbs: {start:%Y-%m}: only {len(got)} lists")
        for fd, fm, fy, ad, am, ay, whole, frac in got:
            rate = float(f"{whole}.{frac}")
            if not 100 < rate < 130:
                sys.exit(f"nbs: {ay}-{am}-{ad}: {rate} dinars per euro")
            rows[f"{ay}-{am}-{ad}"] = f"{whole}.{frac}"
        start = nxt
    days = sorted(rows)
    for a, b in zip(days, days[1:]):
        if (datetime.date.fromisoformat(b) - datetime.date.fromisoformat(a)).days > 6:
            sys.exit(f"nbs: no list from {a} to {b}")
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["applies_from", "RSD"])
        w.writerows([d, rows[d]] for d in days)
    print(len(days), "lists from", days[0], "to", days[-1])


if __name__ == "__main__":
    main(*sys.argv[1:])
