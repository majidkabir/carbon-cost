"""Builds fx/data/nbs-eur-rsd.csv: the National Bank of Serbia's official
middle exchange rate of the dinar against the euro (zvanični srednji kurs),
of each day from FROM on (a weekend's or holiday's is the last working
day's list).

The ECB publishes no dinar rate; the NBS's official middle rate is the one
Serbian law uses (Zakon o deviznom poslovanju, art. 41: for bookkeeping,
statistics, customs duty and other import fees). Its exchange rate web app
gives a period's lists (ExchangeRate/IndexPeriod: EUR, middle rate,
working and non-working days), a year at a time here.

Usage: python3 nbs.py out.csv
"""
import csv, datetime, html, re, sys, time, urllib.request

FROM = 2024
URL = ("https://webappcenter.nbs.rs/ExchangeRateWebApp/ExchangeRate/IndexPeriod?isSearchExecuted=true"
       "&DateFrom={a}&DateTo={b}&CurrencyCode=978&ExchangeRateListTypeID=3&WorkingDays=2")
UA = "carbon-cost history fetch (github.com/majidkabir/carbon-cost)"
# Day formed, day it applies (every day: a weekend's or holiday's is the
# last working day's list), unit, rate.
DAY = r"<td>\s*(\d{1,2})\.(\d{1,2})\.(\d{4})\.?\s*</td>\s*"
ROW = re.compile(r"<tr>\s*" + DAY + DAY + r"<td>\s*1\s*</td>\s*<td>\s*(\d{3}),(\d{4})\s*</td>\s*</tr>")


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
    for year in range(FROM, today.year + 1):
        end = min(datetime.date(year, 12, 31), today)
        h = page(URL.format(a=f"01.01.{year}.", b=end.strftime("%d.%m.%Y.")))
        if "СРЕДЊИ КУРС" not in h.upper():
            sys.exit(f"nbs: {year}: not the middle rate table")
        for fd, fm, fy, ad, am, ay, whole, frac in ROW.findall(h):
            rate = float(f"{whole}.{frac}")
            if not 100 < rate < 130:
                sys.exit(f"nbs: {ay}-{am}-{ad}: {rate} dinars per euro")
            rows[f"{ay}-{int(am):02d}-{int(ad):02d}"] = f"{whole}.{frac}"
    days = sorted(rows)
    # A rate for every day, from 1 January of FROM to (about) today.
    want = (datetime.date.fromisoformat(days[-1]) - datetime.date(FROM, 1, 1)).days + 1 if days else 0
    if not days or days[0] != f"{FROM}-01-01" or len(days) != want or (today - datetime.date.fromisoformat(days[-1])).days > 4:
        sys.exit(f"nbs: {len(days)} days from {days[:1]} to {days[-1:]}, not every day to {today}")
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "RSD"])
        w.writerows([d, rows[d]] for d in days)
    print(len(days), "days from", days[0], "to", days[-1])


if __name__ == "__main__":
    main(*sys.argv[1:])
