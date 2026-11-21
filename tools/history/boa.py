"""Builds fx/data/boa-eur-all.csv: the Bank of Albania's official exchange
rate of the lek against the euro (kursi zyrtar i këmbimit), of each day
from FROM on (a weekend's or holiday's is the last working day's rate).

The ECB publishes no lek rate. The Bank of Albania calculates the official
rate each working day from the interbank market's quotations; its page
(Markets > Official exchange rate) gives a period's rates for a currency
when its form is sent: a POST of the page's own form (WebAppForm), whose
phpVars name the period, the currency (pubcat 1,2: EUR) and the page of
results (kk_rs_sr_CP, 20 a page). No cookie is needed.

Usage: python3 boa.py out.csv
"""
import csv, datetime, html, re, sys, time, urllib.parse, urllib.request

FROM = 2024
URL = "https://www.bankofalbania.org/Markets/Official_exchange_rate/"
UA = "carbon-cost history fetch (github.com/majidkabir/carbon-cost)"
SESSION = ("ln=2&ci_type=DI&languageCode=en&kk_rs_sr_CP=1&kkOther_rs_sr_CP=1&kk_rs_sr_bid_ask_CP=1"
           "&menyra_shfaqjes=T&crd=0,7,2,0,0,11288")
# The official rate's table: a date and one rate (the bid and ask table has two).
ROW = re.compile(r"<td[^>]*>\s*(\d\d)\.(\d\d)\.(\d{4})\s*</td>\s*<td[^>]*>\s*(\d+\.\d+)\s*</td>\s*</tr>", re.I)
TOTAL = re.compile(r"(\d+) - (\d+) of (\d+) results")


def page(a, b, n):
    body = urllib.parse.urlencode({"sourcePage": "", "targetPage": "", "ln": "", "sessionVars": SESSION,
                                   "phpVars": f"event=none.srm(kk_rs_sr_CP={n};startDate={a};endDate={b};pubcat=1,2;)"}).encode()
    for i in range(5):
        try:
            req = urllib.request.Request(URL, data=body, headers={"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded"})
            with urllib.request.urlopen(req, timeout=120) as r:
                return html.unescape(r.read().decode("utf-8", "replace"))
        except Exception as e:
            print("retry", a, b, n, e, file=sys.stderr)
            time.sleep(30 * (i + 1))
    sys.exit(f"boa: {a}-{b} page {n} not answered")


def period(a, b):
    """The official EUR rates of the period, {yyyy-mm-dd: rate}."""
    rows, n, pages = {}, 1, None
    while pages is None or n <= pages:
        h = page(a, b, n)
        m = TOTAL.search(h)
        if not m:
            sys.exit(f"boa: {a}-{b} page {n}: no result count (not the period table)")
        pages = -(-int(m.group(3)) // 20)
        got = ROW.findall(h)
        if not got and int(m.group(3)) > 0:
            sys.exit(f"boa: {a}-{b} page {n}: no rates read")
        for d, mo, y, rate in got:
            v = float(rate)
            if not 80 < v < 130:
                sys.exit(f"boa: {y}-{mo}-{d}: {v} lek per euro")
            rows[f"{y}-{mo}-{d}"] = rate
        n += 1
        time.sleep(1)
    return rows


def main(out):
    today = datetime.date.today()
    rows = {}
    # From December before FROM: 1 and 2 January are holidays, which take
    # the last working day's rate.
    for start, end in [(datetime.date(FROM - 1, 12, 1), datetime.date(FROM - 1, 12, 31))] + [
            (datetime.date(y, 1, 1), min(datetime.date(y, 12, 31), today)) for y in range(FROM, today.year + 1)]:
        got = period(start.strftime("%d.%m.%Y"), end.strftime("%d.%m.%Y"))
        if not got:
            sys.exit(f"boa: no rates from {start} to {end}")
        rows.update(got)
    days = sorted(rows)
    last = datetime.date.fromisoformat(days[-1])
    if days[0] > f"{FROM}-01-01" or (today - last).days > 5 or len([d for d in days if d >= f"{FROM}"]) < 240 * (today.year - FROM):
        sys.exit(f"boa: {len(days)} working days from {days[0]} to {days[-1]}, not every working day to {today}")
    # Every day from 1 January of FROM, each with the last working day's rate.
    out_rows, d, cur = [], datetime.date(FROM, 1, 1), None
    for x in days:
        if x < f"{FROM}-01-01":
            cur = rows[x]
    while d <= last:
        s = d.isoformat()
        cur = rows.get(s, cur)
        out_rows.append([s, cur])
        d += datetime.timedelta(days=1)
    with open(out, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["date", "ALL"])
        w.writerows(out_rows)
    print(len(out_rows), "days from", out_rows[0][0], "to", out_rows[-1][0], f"({len(days)} working days' rates)")


if __name__ == "__main__":
    main(*sys.argv[1:])
