"""Builds the national CO2 prices on road fuel (rates/data/fuelco2-*.json)
from the fetched law texts (sources.json, table fuelco2-*):

- Germany, BEHG § 10 (2): the fixed certificate price of 2024 and 2025,
  and for 2026 the corridor of 55 to 65 euro; the 2026 price is the
  auctions' clearing price, 65 euro when every auction applied the
  "65 EUR rule" (BEHV § 12 (4): more volume allotted because the price
  reached the ceiling), read from EEX's auction calendar;
- Austria, NEHG 2022 § 10 (1): the certificate value by calendar year
  (to 2025; the law sets none for later years).

Usage: python3 fuel_co2.py fetched/ out-dir"""
import html, json, os, re, sys


def text(path):
    t = open(path, encoding="utf-8", errors="replace").read()
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", t, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t)))


def src(srcs, sid):
    return {"title": srcs[sid]["what"], "url": srcs[sid]["url"]}


def write(out, f):
    path = os.path.join(out, f"fuelco2-{f['country'].lower()}-{f['valid_from']}.json")
    json.dump(f, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, f["rate_per_t"])


def germany(fetched, out, srcs):
    t = text(os.path.join(fetched, "de-behg-10.html"))
    for y in (2024, 2025):
        m = re.search(rf"im Zeitraum vom 1\. Januar {y} bis zum 31\. Dezember {y}: (\d+) Euro", t)
        if not m:
            sys.exit(f"BEHG § 10: no fixed price for {y}")
        write(out, {"country": "DE", "currency": "EUR", "valid_from": f"{y}-01-01", "valid_to": f"{y}-12-31",
                    "name": "Brennstoffemissionshandel (nEHS) certificate price", "rate_per_t": float(m.group(1)),
                    "law": f"BEHG § 10 (2): fixed price of {m.group(1)} euro per certificate (one tonne of CO2) in {y}. Fuel suppliers buy a certificate for each tonne of CO2 their fuel emits and pass the cost on in the fuel price.",
                    "sources": [src(srcs, "de-behg-10")]})
    m = re.search(r"Für das Jahr 2026 wird ein Preiskorridor mit einem Mindestpreis von (\d+) Euro pro Emissionszertifikat und einem Höchstpreis von (\d+) Euro", t)
    if not m:
        sys.exit("BEHG § 10: no 2026 price corridor")
    lo, hi = float(m.group(1)), float(m.group(2))
    rows = []
    for line in open(os.path.join(fetched, "de-eex-nehs-auctions.csv"), encoding="utf-8-sig").read().splitlines()[1:]:
        f = line.split(";")
        if len(f) > 5 and f[3] == "2026":
            rows.append((f[0], float(f[4]), int(f[5])))
    if not rows or any(not lo <= p <= hi for _, p, _ in rows):
        sys.exit(f"EEX: no 2026 auctions in the corridor ({rows[:3]})")
    vol = sum(v for _, _, v in rows)
    avg = round(sum(p * v for _, p, v in rows) / vol, 2)
    prices = sorted({p for _, p, _ in rows})
    write(out, {"country": "DE", "currency": "EUR", "valid_from": "2026-01-01", "valid_to": "2026-12-31",
                "name": "Brennstoffemissionshandel (nEHS) certificate price", "rate_per_t": avg,
                "law": f"BEHG § 10 (2): 2026 certificates are auctioned in a corridor of {m.group(1)} to {m.group(2)} euro. This is the volume-weighted clearing price of the {len(rows)} auctions EEX held ({rows[-1][0]} to {rows[0][0]}; clearing prices {', '.join(f'{p:g}' for p in prices)} euro). Certificates bought after the auctions cost 68 euro (the excess quantity price), so a supplier's average may be a little higher.",
                "sources": [src(srcs, "de-behg-10"), src(srcs, "de-eex-nehs-auctions")]})


def austria(fetched, out, srcs):
    t = text(os.path.join(fetched, "at-nehg.html"))
    if "Ausgabewert" not in t:
        # RIS refuses the workflow (503) and the Internet Archive has no
        # copy yet: Austria isn't priced until the page can be read.
        print("NEHG 2022: the RIS page wasn't fetched; Austria not built")
        return
    m = re.search(r"Die nationalen Emissionszertifikate haben einen Ausgabewert von: ?Kalenderjahr ?Betrag (.*?) \(2\)", t)
    if not m:
        sys.exit("NEHG 2022 § 10 (1) not found")
    vals = dict(re.findall(r"(20\d\d) (\d+(?:,\d+)?) Euro", m.group(1)))
    for y in ("2024", "2025"):
        if y not in vals:
            sys.exit(f"NEHG 2022 § 10 (1): no value for {y}")
        write(out, {"country": "AT", "currency": "EUR", "valid_from": f"{y}-01-01", "valid_to": f"{y}-12-31",
                    "name": "Nationaler Emissionszertifikatehandel certificate value", "rate_per_t": float(vals[y].replace(",", ".")),
                    "law": f"NEHG 2022 § 10 (1): certificate value of {vals[y]} euro per tonne of CO2 in {y}. Fuel suppliers pay it for the CO2 their fuel emits and pass it on in the fuel price. The law sets no value for 2026 or later, so those years aren't priced.",
                    "sources": [src(srcs, "at-nehg")]})


MONTHS = {m: i + 1 for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"])}


def irish_date(d):
    day, month, year = d.split()
    return f"{year}-{MONTHS[month]:02d}-{int(day):02d}"


def ireland(fetched, out, srcs):
    """Mineral Oil Tax's carbon component on auto-diesel ("heavy oil used as
    a propellant"), as Revenue's Excise Duty Rates manual gives the amount
    charged per tonne of CO2 for each period (Finance Act 1999 Schedule 2A)."""
    p = os.path.join(fetched, "ie-revenue-energy-rates.txt")
    if not os.path.exists(p):
        print("Ireland: Revenue's rates manual wasn't fetched; not built")
        return
    t = open(p, encoding="utf-8").read()
    periods = []
    for m in re.finditer(r"Mineral Oil Tax \(MOT\) rates effective from (\d+ \w+ \d{4})(?: to (\d+ \w+ \d{4}))?\n", t):
        if m.group(2) and irish_date(m.group(2)) < "2024-01-01":
            continue  # older tables, laid out differently
        seg = t[m.end():m.end() + 6000]
        h = seg.find("Heavy Oil:")
        r = re.search(r"Used as a propellant[.…\s]*€([\d.]+)\*?\s", seg[h:])
        if h < 0 or not r:
            sys.exit(f"Ireland: no auto-diesel rate in the period from {m.group(1)}")
        periods.append((irish_date(m.group(1)), irish_date(m.group(2)) if m.group(2) else "", float(r.group(1))))
    periods.sort()
    for a, b in zip(periods, periods[1:]):
        if a[1] and a[1] >= b[0]:
            sys.exit(f"Ireland: overlapping periods {a} {b}")
    # From 2024, merging consecutive periods at the same rate.
    merged = []
    for vf, vt, rate in periods:
        if (vt or "9999") < "2024-01-01":
            continue
        vf = max(vf, "2024-01-01")
        if merged and merged[-1][2] == rate:
            merged[-1][1] = vt
        else:
            merged.append([vf, vt, rate])
    for vf, vt, rate in merged:
        f = {"country": "IE", "currency": "EUR", "valid_from": vf,
             "name": "Carbon tax (carbon component of Mineral Oil Tax) on auto-diesel", "rate_per_t": rate,
             "law": f"Finance Act 1999 Schedule 2A, as Revenue's Excise Duty Rates manual gives it: the carbon component of Mineral Oil Tax on heavy oil used as a propellant (auto-diesel) charges {rate:.2f} euro per tonne of CO2 its burning emits. Fuel suppliers pay it with the Mineral Oil Tax and pass it on in the fuel price.",
             "sources": [src(srcs, "ie-revenue-energy-rates")]}
        if vt:
            f["valid_to"] = vt
        write(out, f)


def main(fetched, out):
    os.makedirs(out, exist_ok=True)
    srcs = {s["id"]: s for s in json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources.json"), encoding="utf-8"))["sources"]}
    germany(fetched, out, srcs)
    austria(fetched, out, srcs)
    ireland(fetched, out, srcs)


if __name__ == "__main__":
    main(*sys.argv[1:])
